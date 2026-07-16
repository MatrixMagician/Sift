"""Per-case SQLite store.

This module owns ALL SQL in the codebase (single reviewable SQL owner,
T-02-02): every statement uses parameterised ``?`` placeholders — no value is
ever interpolated into SQL text. Migrations are numbered functions applied by
a ``PRAGMA user_version`` runner (D-03); Phase 2 extends the same store.
"""

import json
import re
import sqlite3
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import zstandard

from sift.models import Event

_RAW_ZSTD_THRESHOLD = 4096  # UTF-8 encoded bytes (STORE-02)
_MAX_RAW_BYTES = 128 * 2**20  # zstd-bomb cap for tampered case files (T-02-01)
# Constructor defaults: level 3, single-threaded. Never pass threads= — frames
# must be deterministic per library version (RESEARCH A1).
_CCTX = zstandard.ZstdCompressor()
_DCTX = zstandard.ZstdDecompressor()


def _encode_raw(raw: str) -> str | bytes:
    """Compress raw whose UTF-8 encoding exceeds the 4 KB threshold (STORE-02).

    The threshold counts encoded bytes, not characters (Pitfall 3).
    """
    data = raw.encode("utf-8")
    return _CCTX.compress(data) if len(data) > _RAW_ZSTD_THRESHOLD else raw


def _decode_raw(value: str | bytes) -> str:
    """SINGLE read path for raw: transparently decompress zstd BLOBs (STORE-02).

    max_output_size caps decompression because a shared case.db is untrusted
    input (T-02-01 zstd bomb).
    """
    if isinstance(value, bytes):
        return _DCTX.decompress(value, max_output_size=_MAX_RAW_BYTES).decode("utf-8")
    return value

_CASE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Savepoint name for the per-file ingest unit (CR-01). Interpolated into SQL
# text, but it is a code constant — never user data (the PRAGMA user_version
# precedent, T-02-13).
_SAVEPOINT_INGEST_FILE = "ingest_file"


def validate_case_name(name: str) -> str:
    """Allowlist validation of user-supplied case names (T-02-01 path traversal)."""
    if not name or name in {".", ".."} or not _CASE_NAME_RE.fullmatch(name):
        raise ValueError(
            f"invalid case name {name!r}: use ASCII letters, digits, '_', '.' or '-'"
        )
    return name


def case_db_path(data_dir: Path, name: str) -> Path:
    """Return data_dir/cases/<name>/case.db, asserting containment (D-04)."""
    validate_case_name(name)
    cases = data_dir / "cases"
    path = cases / name / "case.db"
    if not path.resolve().is_relative_to(cases.resolve()):
        raise ValueError(f"case path escapes {cases}: {name!r}")
    return path


def _migration_1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE events (
            event_id      TEXT PRIMARY KEY,
            case_id       TEXT NOT NULL,
            ts            TEXT,
            ts_confidence TEXT NOT NULL
                CHECK (ts_confidence IN ('exact','inferred','missing')),
            source        TEXT NOT NULL,
            source_file   TEXT NOT NULL,
            line_start    INTEGER NOT NULL,
            line_end      INTEGER NOT NULL,
            severity      TEXT NOT NULL
                CHECK (severity IN ('fatal','error','warn','info','debug','unknown')),
            component     TEXT,
            thread        TEXT,
            session       TEXT,
            message       TEXT NOT NULL,
            attrs         TEXT NOT NULL DEFAULT '{}',
            raw           TEXT NOT NULL
        )
        """
        # raw stays plain TEXT in Phase 1; STORE-02 (Phase 2) adds zstd
        # compression for raw > 4 KB via migration 2.
    )
    conn.execute("CREATE INDEX idx_events_ts ON events(ts)")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _migration_2(conn: sqlite3.Connection) -> None:
    """Add template_groups and zstd-compress oversized raw in place (STORE-02).

    Runs inside the BEGIN IMMEDIATE migration runner, so a concurrent opener
    never observes a half-migrated schema.
    """
    conn.execute(
        """
        CREATE TABLE template_groups (
            template_id  TEXT PRIMARY KEY,      -- sha256(template)[:16]
            template     TEXT NOT NULL UNIQUE,  -- masked message (CLUS-01)
            count        INTEGER NOT NULL,
            first_ts     TEXT,                  -- ISO 8601, NULL if all ts missing
            last_ts      TEXT,
            severity_max TEXT NOT NULL
                CHECK (severity_max IN
                    ('fatal','error','warn','info','debug','unknown')),
            exemplar_event_ids TEXT NOT NULL    -- JSON array, canonical order
        )
        """
    )
    # Compress pre-existing Phase-1 oversized rows in place (Pitfall 7). The
    # SQL predicate counts UTF-8 encoded bytes, matching _encode_raw exactly.
    rows = conn.execute(
        "SELECT event_id, raw FROM events WHERE length(CAST(raw AS BLOB)) > ?",
        (_RAW_ZSTD_THRESHOLD,),
    ).fetchall()
    for eid, raw in rows:
        if isinstance(raw, str):
            conn.execute(
                "UPDATE events SET raw = ? WHERE event_id = ?",
                (_CCTX.compress(raw.encode("utf-8")), eid),
            )


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
}

_EVENT_COLUMNS = (
    "event_id, case_id, ts, ts_confidence, source, source_file, "
    "line_start, line_end, severity, component, thread, session, "
    "message, attrs, raw"
)

_TEMPLATE_GROUP_COLUMNS = (
    "template_id, template, count, first_ts, last_ts, severity_max, "
    "exemplar_event_ids"
)

# Allowlisted filter key -> fixed WHERE snippet (T-02-08). Filter VALUES are
# only ever bound via ?; keys never reach SQL text — an unknown key raises
# ValueError before any query is built. Substring keys use instr, not LIKE,
# so % and _ in values stay literal. `limit` is handled separately as a
# trailing "LIMIT ?" clause, never via these dicts.
_EVENT_FILTER_SQL: dict[str, str] = {
    "severity": "severity = ?",
    "source": "source = ?",
    "file": "instr(source_file, ?) > 0",
    "since": "ts >= ?",
    "until": "ts <= ?",
}

_CLUSTER_FILTER_SQL: dict[str, str] = {
    "severity": "severity_max = ?",
    "min-count": "count >= ?",
    "contains": "instr(template, ?) > 0",
}


def _build_filter_clauses(
    filters: Mapping[str, str | int] | None,
    allowed: Mapping[str, str],
) -> tuple[str, str, list[str | int]]:
    """Return (where_sql, limit_sql, params) from allowlisted filters.

    Defence in depth behind the CLI validation (T-02-08): an unknown key
    raises ValueError naming the valid keys — it can never reach SQL text.
    Snippets AND-combine; params line up with the chosen snippets, with the
    LIMIT value (if any) appended last.
    """
    if not filters:
        return "", "", []
    snippets: list[str] = []
    params: list[str | int] = []
    limit: str | int | None = None
    for key, value in filters.items():
        if key == "limit":
            limit = value
            continue
        if key not in allowed:
            valid = ", ".join([*allowed, "limit"])
            raise ValueError(f"unknown filter key {key!r}; valid keys: {valid}")
        snippets.append(allowed[key])
        params.append(value)
    where_sql = f" WHERE {' AND '.join(snippets)}" if snippets else ""
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    return where_sql, limit_sql, params


@dataclass(frozen=True)
class TemplateGroup:
    """One template dedup group (CLUS-01), persisted in template_groups."""

    template_id: str  # sha256(template)[:16], mirrors the event_id idiom
    template: str  # masked message
    count: int
    first_ts: str | None  # ISO 8601 string or None
    last_ts: str | None
    severity_max: str  # six-severity CHECK vocabulary
    exemplar_event_ids: list[str]


class CaseStore:
    """One SQLite database per case (D-03/D-04)."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # autocommit mode: transactions are explicit via transaction()
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        current = int(row[0])
        for version in sorted(v for v in _MIGRATIONS if v > current):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                _MIGRATIONS[version](self._conn)
                # PRAGMA cannot take ? parameters; version is an internal
                # migration number, never user data.
                self._conn.execute(f"PRAGMA user_version = {int(version)}")
                self._conn.execute("COMMIT")
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    # IN-03: a dead transaction (e.g. the connection already
                    # rolled back) must never mask the original error.
                    pass
                raise

    @contextmanager
    def transaction(self) -> Generator[None]:
        """One atomic unit — ingest wraps all inserts plus the coverage meta write."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                # IN-03: never mask the original error with a rollback error.
                pass
            raise
        else:
            self._conn.execute("COMMIT")

    @contextmanager
    def savepoint(self, name: str = _SAVEPOINT_INGEST_FILE) -> Generator[None]:
        """Nested atomic unit inside an open transaction (CR-01).

        Ingest wraps each file's detect+parse+insert body so a mid-stream
        parse failure rolls that FILE back to zero rows while the outer
        all-or-nothing BEGIN IMMEDIATE transaction survives — SQLite
        savepoints nest inside an open transaction natively. The name is
        interpolated into SQL text but comes only from the module constant
        ``_SAVEPOINT_INGEST_FILE`` — a code constant, never user data
        (the PRAGMA user_version precedent, T-02-13).
        """
        self._conn.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            try:
                self._conn.execute(f"ROLLBACK TO {name}")
                self._conn.execute(f"RELEASE {name}")
            except sqlite3.OperationalError:
                # IN-03: never mask the original error with a rollback error.
                pass
            raise
        else:
            self._conn.execute(f"RELEASE {name}")

    def insert_events(self, events: Iterable[Event]) -> int:
        """INSERT OR IGNORE; returns the number of NEWLY inserted rows (INGST-02)."""
        rows = [
            (
                e.event_id,
                e.case_id,
                # sqlite3's default datetime adapter is deprecated on 3.12+:
                # always store explicit ISO 8601 strings.
                e.ts.isoformat() if e.ts is not None else None,
                e.ts_confidence,
                e.source,
                e.source_file,
                e.line_start,
                e.line_end,
                e.severity,
                e.component,
                e.thread,
                e.session,
                e.message,
                json.dumps(e.attrs, sort_keys=True),
                _encode_raw(e.raw),  # zstd BLOB when > 4 KB encoded (STORE-02)
            )
            for e in events
        ]
        before = self._conn.total_changes
        self._conn.executemany(
            f"INSERT OR IGNORE INTO events ({_EVENT_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        return self._conn.total_changes - before

    def query_events(self) -> list[Event]:
        """All events, ordered by ts (NULLs last), source_file, line_start."""
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM events "
            "ORDER BY ts IS NULL, ts, source_file, line_start"
        ).fetchall()
        return [
            Event(
                event_id=r[0],
                case_id=r[1],
                ts=datetime.fromisoformat(r[2]) if r[2] is not None else None,
                ts_confidence=r[3],
                source=r[4],
                source_file=r[5],
                line_start=r[6],
                line_end=r[7],
                severity=r[8],
                component=r[9],
                thread=r[10],
                session=r[11],
                message=r[12],
                attrs=json.loads(r[13]),
                raw=_decode_raw(r[14]),  # single raw read path (Pitfall 2)
            )
            for r in rows
        ]

    def iter_event_summaries(self) -> Iterator[tuple[str, str | None, str, str]]:
        """Yield (event_id, ts, severity, message) in canonical order (CLUS-01).

        Streams rows from the cursor — never fetchall — and never selects
        raw, so nothing is decompressed during dedup.
        """
        cursor = self._conn.execute(
            "SELECT event_id, ts, severity, message FROM events "
            "ORDER BY ts IS NULL, ts, source_file, line_start"
        )
        for row in cursor:
            yield (row[0], row[1], row[2], row[3])

    def iter_event_rows(
        self, filters: Mapping[str, str | int] | None = None
    ) -> Iterator[tuple[str, str | None, str, str, int, str]]:
        """Yield (event_id, ts, severity, source_file, line_start, message).

        Exactly the six fields `show events` renders, in the canonical order,
        streamed from the cursor — never fetchall, never selecting raw, so a
        1M-event case renders without hydrating Events or decompressing zstd
        (T-02-10, STORE-04). Filters are allowlisted keys mapped to fixed
        ?-bound WHERE snippets (T-02-08).
        """
        where_sql, limit_sql, params = _build_filter_clauses(
            filters, _EVENT_FILTER_SQL
        )
        cursor = self._conn.execute(
            "SELECT event_id, ts, severity, source_file, line_start, message "
            # S608 convention: where/limit SQL comes from the module-constant
            # allowlist dicts; every value is ?-bound.
            f"FROM events{where_sql} "  # noqa: S608
            f"ORDER BY ts IS NULL, ts, source_file, line_start{limit_sql}",
            params,
        )
        for row in cursor:
            yield (row[0], row[1], row[2], row[3], row[4], row[5])

    def replace_template_groups(self, groups: Iterable[TemplateGroup]) -> None:
        """DELETE FROM template_groups then insert all groups (CLUS-01).

        The CALLER owns the transaction — rebuild_template_groups wraps this
        together with the mask_version meta write.
        """
        self._conn.execute("DELETE FROM template_groups")
        self._conn.executemany(
            f"INSERT INTO template_groups ({_TEMPLATE_GROUP_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    g.template_id,
                    g.template,
                    g.count,
                    g.first_ts,
                    g.last_ts,
                    g.severity_max,
                    json.dumps(g.exemplar_event_ids),
                )
                for g in groups
            ],
        )

    def query_template_groups(
        self, filters: Mapping[str, str | int] | None = None
    ) -> list[TemplateGroup]:
        """Template groups ordered by count DESC, template ASC (STORE-04).

        Optional filters use the allowlisted _CLUSTER_FILTER_SQL snippets with
        ?-bound values (T-02-08); an unknown key raises ValueError.
        """
        where_sql, limit_sql, params = _build_filter_clauses(
            filters, _CLUSTER_FILTER_SQL
        )
        rows = self._conn.execute(
            f"SELECT {_TEMPLATE_GROUP_COLUMNS} FROM template_groups"  # noqa: S608 — column list and WHERE snippets are module constants; values are all ?
            f"{where_sql} ORDER BY count DESC, template{limit_sql}",
            params,
        ).fetchall()
        return [
            TemplateGroup(
                template_id=r[0],
                template=r[1],
                count=r[2],
                first_ts=r[3],
                last_ts=r[4],
                severity_max=r[5],
                exemplar_event_ids=json.loads(r[6]),
            )
            for r in rows
        ]

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )

    def close(self) -> None:
        self._conn.close()
