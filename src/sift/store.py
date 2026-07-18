"""Per-case SQLite store.

This module owns ALL SQL in the codebase (single reviewable SQL owner,
T-02-02): every statement uses parameterised ``?`` placeholders — no value is
ever interpolated into SQL text. Migrations are numbered functions applied by
a ``PRAGMA user_version`` runner (D-03); Phase 2 extends the same store.
"""

import json
import re
import sqlite3
import sys
from collections.abc import (
    Callable,
    Generator,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import numpy as np
import sqlite_vec  # pyright: ignore[reportMissingTypeStubs] — pre-v1, no stubs
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

def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the vetted sqlite-vec extension, re-locking loading immediately.

    Native extension loading is a code-execution surface (T-03-09): loading is
    enabled only around the single vetted ``sqlite_vec.load`` call and disabled
    again in a ``finally`` so no other extension can be loaded on this
    connection. Called lazily (first embed), never in ``__init__`` — a
    llama-free environment must still open Phase-1/2 cases.
    """
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def vec_version() -> str:
    """Load sqlite-vec on a throwaway connection and return ``vec_version()``.

    ``sift doctor``'s Pitfall-5 probe: proves the interpreter's SQLite permits
    extension loading (Fedora's python3 does; some macOS system Pythons do not).
    Uses an in-memory connection so it needs no case. Reuses the single vetted
    ``_load_sqlite_vec`` path (enable → load → re-lock) rather than duplicating
    the native-extension surface (T-03-09).

    Raises:
        Exception: If ``enable_load_extension`` is unavailable on this build or
            the extension cannot load — the doctor names the caveat.
    """
    conn = sqlite3.connect(":memory:")
    try:
        _load_sqlite_vec(conn)
        row = conn.execute("SELECT vec_version()").fetchone()
        return str(row[0])
    finally:
        conn.close()


def _vec_to_blob(vec: list[float]) -> bytes:
    """SINGLE vector write path: float32 little-endian bytes for sqlite-vec.

    Mirrors the ``_encode_raw``/``_decode_raw`` single-path idiom — all vector
    (de)serialisation lives in store.py so the documented BLOB+numpy escape
    hatch (drop sqlite-vec for a numpy brute-force scan) stays an afternoon's
    work.
    """
    return np.asarray(vec, dtype="<f4").tobytes()


def _blob_to_vec(  # pyright: ignore[reportUnusedFunction] — read half of the confined pair; KNN retrieval (Phase 4/6) + tests use it
    blob: bytes,
) -> list[float]:
    """SINGLE vector read path — the inverse of ``_vec_to_blob``."""
    return [float(x) for x in np.frombuffer(blob, dtype="<f4")]


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


def _migration_3(conn: sqlite3.Connection) -> None:
    """Add the chunks and clusters tables (STORE-03, CLUS-02).

    The sqlite-vec ``vectors`` table is deliberately NOT created here: its
    dimension is unknown until the first embedding round-trip, so it is built
    lazily by ``ensure_vectors_table`` (D-03). A llama-free environment
    therefore still opens a Phase-1/2 case at schema v3 without ever touching
    the sqlite-vec extension.
    """
    conn.execute(
        """
        CREATE TABLE chunks (
            chunk_id    INTEGER PRIMARY KEY,
            template_id TEXT NOT NULL,   -- the template group this chunk represents
            text        TEXT NOT NULL,   -- exemplar event message chosen for embedding
            event_ids   TEXT NOT NULL    -- JSON array of the group's exemplar event ids
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE clusters (
            cluster_id   INTEGER PRIMARY KEY,
            label        TEXT,               -- NULL until an LLM label exists (D-01)
            signature    TEXT NOT NULL,      -- shown until a label exists
            severity_max TEXT NOT NULL
                CHECK (severity_max IN
                    ('fatal','error','warn','info','debug','unknown')),
            count        INTEGER NOT NULL,
            template_ids TEXT NOT NULL       -- JSON array of member template ids
        )
        """
    )


def _migration_4(conn: sqlite3.Connection) -> None:
    """Add the hypotheses table (RAG-02, RAG-04).

    One row per ranked hypothesis in the latest triage run. The list-valued
    fields (supporting_event_ids, suggested_next_steps) are JSON arrays, and
    citations_valid persists the per-hypothesis citation-gate verdict so an
    invalid/unverifiable citation stays visibly flagged for the report rather
    than being silently dropped (T-04-02). Run-level status lives in meta under
    the triage_* keys (see replace_hypotheses) — no separate table needed.
    """
    conn.execute(
        """
        CREATE TABLE hypotheses (
            hyp_index            INTEGER PRIMARY KEY,
            title                TEXT NOT NULL,
            narrative            TEXT NOT NULL,
            confidence           TEXT NOT NULL
                CHECK (confidence IN ('high','medium','low')),
            confidence_reasoning TEXT NOT NULL,
            supporting_event_ids TEXT NOT NULL,   -- JSON array of event ids
            contradicting_evidence TEXT,          -- nullable free text
            suggested_next_steps TEXT NOT NULL,   -- JSON array of steps
            citations_valid      INTEGER NOT NULL -- 0/1 citation-gate verdict
        )
        """
    )


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,  # chunks + clusters tables (NOT vectors — that is lazy)
    4: _migration_4,  # hypotheses table (citation-gated triage output)
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

_CHUNK_COLUMNS = "chunk_id, template_id, text, event_ids"

_CLUSTER_COLUMNS = (
    "cluster_id, label, signature, severity_max, count, template_ids"
)

_HYP_COLUMNS = (
    "hyp_index, title, narrative, confidence, confidence_reasoning, "
    "supporting_event_ids, contradicting_evidence, suggested_next_steps, "
    "citations_valid"
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

# Allowlist for the clusters table (query_clusters). `contains` searches the
# signature — the label is optional and may be NULL until clustering labels.
_CLUSTERS_TABLE_FILTER_SQL: dict[str, str] = {
    "severity": "severity_max = ?",
    "min-count": "count >= ?",
    "contains": "instr(signature, ?) > 0",
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


def _coerce_str_list(value: str) -> list[str]:
    """WR-01: decode a JSON list column from an UNTRUSTED case.db to list[str].

    A tampered case.db can hold ANY JSON in a list column. Guard while the value
    is still typed Any: wrap a non-array as a single element and coerce every
    element to str, so tampering stays visible (never crashes the read path) and
    render-time sanitisation strips hostile bytes. Mirrors the inline idiom in
    query_clusters/query_template_groups.
    """
    loaded: object = json.loads(value)
    if not isinstance(loaded, list):
        loaded = [loaded]
    items = cast("list[object]", loaded)
    return [str(x) for x in items]


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


@dataclass(frozen=True)
class Cluster:
    """One semantic cluster of template groups (CLUS-02), persisted in clusters."""

    cluster_id: int
    label: str | None  # NULL until an LLM label exists (D-01)
    signature: str  # shown until a label exists
    severity_max: str  # six-severity CHECK vocabulary
    count: int
    template_ids: list[str]  # member template ids


@dataclass(frozen=True)
class StoredHypothesis:
    """One persisted triage hypothesis (RAG-02), a row in the hypotheses table."""

    hyp_index: int
    title: str
    narrative: str
    confidence: str  # 'high' | 'medium' | 'low' (CHECK-enforced on insert)
    confidence_reasoning: str
    supporting_event_ids: list[str]
    contradicting_evidence: str | None
    suggested_next_steps: list[str]
    citations_valid: bool  # the per-hypothesis citation-gate verdict (T-04-02)


class CaseStore:
    """One SQLite database per case (D-03/D-04)."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # autocommit mode: transactions are explicit via transaction()
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # sqlite-vec is loaded lazily on first embed, NOT here — a llama-free
        # environment must still open Phase-1/2 cases. This flag only records
        # whether the extension has been loaded on this connection yet.
        self._vec_loaded = False
        self._migrate()

    def _ensure_vec_loaded(self) -> None:
        """Load sqlite-vec once per connection (idempotent lazy loader)."""
        if not self._vec_loaded:
            _load_sqlite_vec(self._conn)
            self._vec_loaded = True

    def _migrate(self) -> None:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        current = int(row[0])
        for version in sorted(v for v in _MIGRATIONS if v > current):
            # WR-02: opening a case never rewrites evidence files silently —
            # announce on stderr (stdout stays scriptable) when a migration
            # actually applies.
            print(f"note: migrating case.db to schema v{version}", file=sys.stderr)
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

    def get_events_by_ids(self, ids: Sequence[str]) -> dict[str, Event]:
        """Fetch ONLY the requested events, keyed by event_id (REPT-01, Pitfall 1).

        The evidence appendix needs raw + provenance for the handful of cited
        ids — NOT ``query_events()``, which hydrates and zstd-decompresses the
        whole case. This selects just the rows whose event_id is in ``ids`` via
        a ``?``-bound ``IN (...)`` placeholder list (the id never reaches SQL
        text, T-06-03) and decodes raw through the single ``_decode_raw`` path.
        Unknown ids are simply absent from the returned dict; an empty ``ids``
        returns ``{}`` without a query.
        """
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            # S608: column list is a module constant; every id is ?-bound.
            f"SELECT {_EVENT_COLUMNS} FROM events "  # noqa: S608
            f"WHERE event_id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
        return {
            r[0]: Event(
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
                raw=_decode_raw(r[14]),  # single raw read path (Pitfall 1)
            )
            for r in rows
        }

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
        groups: list[TemplateGroup] = []
        for r in rows:
            # WR-01: a tampered case.db can hold ANY JSON here. Guard while
            # the value is still typed Any (pyright strict forbids a
            # redundant isinstance on the list[str] dataclass field later):
            # wrap non-arrays as a single element and coerce all elements to
            # str, so the tampering stays visible to the operator and
            # render-time sanitisation strips hostile bytes.
            loaded: object = json.loads(r[6])
            if not isinstance(loaded, list):
                loaded = [loaded]
            items = cast("list[object]", loaded)
            groups.append(
                TemplateGroup(
                    template_id=r[0],
                    template=r[1],
                    count=r[2],
                    first_ts=r[3],
                    last_ts=r[4],
                    severity_max=r[5],
                    exemplar_event_ids=[str(x) for x in items],
                )
            )
        return groups

    def ensure_vectors_table(self, dim: int) -> None:
        """Lazily create the sqlite-vec vec0 vectors table at ``dim`` (D-03).

        The dimension is unknown until the server returns the first embedding,
        so the ``vec0`` table cannot live in a migration. STORE-03 hard error:
        if ``meta.embedding_dim`` already records a different dimension, raise
        ValueError naming both dims BEFORE loading the extension or writing
        anything — a mismatch is never silently re-indexed. sqlite-vec is
        loaded lazily here (never in ``__init__``).
        """
        existing = self.get_meta("embedding_dim")
        if existing is not None and int(existing) != dim:
            raise ValueError(
                f"embedding dimension mismatch: index has {existing}, "
                f"server returned {dim}"
            )
        self._ensure_vec_loaded()
        self._conn.execute(
            # dim is our validated int, never user text (the PRAGMA
            # user_version precedent, T-02-13). KNN retrieval in Phase 4/6 will
            # use `WHERE embedding MATCH ? AND k = ?` against this table.
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vectors "  # noqa: S608 — dim is our int, never user text
            f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{int(dim)}])"
        )
        if existing is None:
            self.set_meta("embedding_dim", str(dim))
            self.set_meta("embedding_metric", "cosine")

    def record_embedding_identity(self, model: str, dim: int) -> None:
        """Record the server's embedding model + dimension in meta (STORE-03).

        ``embedding_dim`` is owned by :meth:`ensure_vectors_table` (the
        mismatch guard); this method records the model for provenance and only
        sets the dim when absent — a differing dim raises, so it can never mask
        the hard-error guard on reload.
        """
        self.set_meta("embedding_model", model)
        existing = self.get_meta("embedding_dim")
        if existing is None:
            self.set_meta("embedding_dim", str(dim))
        elif int(existing) != dim:
            raise ValueError(
                f"embedding dimension mismatch: index has {existing}, "
                f"server returned {dim}"
            )

    def upsert_vectors(self, rows: Iterable[tuple[int, list[float]]]) -> None:
        """Write (chunk_id, embedding) pairs, replacing any prior vector.

        The CALLER owns the transaction (mirrors replace_template_groups):
        pipeline/cluster.py wraps this in ``store.transaction()``. Every vector
        byte is produced here via ``_vec_to_blob`` — the confinement invariant.
        vec0 does not support ``INSERT OR REPLACE``, so a prior row for the
        same chunk_id is deleted first.
        """
        self._ensure_vec_loaded()
        pairs = [(chunk_id, _vec_to_blob(vec)) for chunk_id, vec in rows]
        self._conn.executemany(
            "DELETE FROM vectors WHERE chunk_id = ?",
            [(chunk_id,) for chunk_id, _ in pairs],
        )
        self._conn.executemany(
            "INSERT INTO vectors (chunk_id, embedding) VALUES (?, ?)", pairs
        )

    def replace_chunks(
        self, chunks: Iterable[tuple[int, str, str, list[str]]]
    ) -> None:
        """DELETE FROM chunks then insert (chunk_id, template_id, text, event_ids).

        The CALLER owns the transaction (mirrors replace_template_groups):
        pipeline/cluster.py wraps this with the vector + cluster writes.
        """
        self._conn.execute("DELETE FROM chunks")
        self._conn.executemany(
            f"INSERT INTO chunks ({_CHUNK_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?)",
            [
                (chunk_id, template_id, text, json.dumps(event_ids))
                for chunk_id, template_id, text, event_ids in chunks
            ],
        )

    def replace_clusters(self, clusters: Iterable[Cluster]) -> None:
        """DELETE FROM clusters then insert all clusters (CLUS-02).

        The CALLER owns the transaction — cluster.py wraps this together with
        the vector upserts and the label-prompt-hash meta write.
        """
        self._conn.execute("DELETE FROM clusters")
        self._conn.executemany(
            f"INSERT INTO clusters ({_CLUSTER_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    c.cluster_id,
                    c.label,
                    c.signature,
                    c.severity_max,
                    c.count,
                    json.dumps(c.template_ids),
                )
                for c in clusters
            ],
        )

    def query_clusters(
        self, filters: Mapping[str, str | int] | None = None
    ) -> list[Cluster]:
        """Clusters ordered by count DESC, cluster_id ASC (STORE-04).

        Optional filters use the allowlisted _CLUSTERS_TABLE_FILTER_SQL
        snippets with ?-bound values (T-02-08); an unknown key raises
        ValueError. template_ids is coerced defensively — a tampered case.db
        can hold ANY JSON here (the exemplar_event_ids precedent).
        """
        where_sql, limit_sql, params = _build_filter_clauses(
            filters, _CLUSTERS_TABLE_FILTER_SQL
        )
        rows = self._conn.execute(
            f"SELECT {_CLUSTER_COLUMNS} FROM clusters"  # noqa: S608 — column list and WHERE snippets are module constants; values are all ?
            f"{where_sql} ORDER BY count DESC, cluster_id{limit_sql}",
            params,
        ).fetchall()
        clusters: list[Cluster] = []
        for r in rows:
            # WR-01: a tampered case.db can hold ANY JSON in template_ids. Guard
            # while the value is still typed Any: wrap non-arrays as a single
            # element and coerce every element to str, so tampering stays
            # visible and render-time sanitisation strips hostile bytes.
            loaded: object = json.loads(r[5])
            if not isinstance(loaded, list):
                loaded = [loaded]
            items = cast("list[object]", loaded)
            clusters.append(
                Cluster(
                    cluster_id=r[0],
                    label=r[1],
                    signature=r[2],
                    severity_max=r[3],
                    count=r[4],
                    template_ids=[str(x) for x in items],
                )
            )
        return clusters

    def set_cluster_labels(self, labels: Mapping[int, str]) -> None:
        """Update clusters.label by cluster_id (D-01, caller owns transaction)."""
        self._conn.executemany(
            "UPDATE clusters SET label = ? WHERE cluster_id = ?",
            [(label, cluster_id) for cluster_id, label in labels.items()],
        )

    def replace_hypotheses(self, rows: Iterable[StoredHypothesis]) -> None:
        """DELETE FROM hypotheses then insert all rows (RAG-02, idempotent).

        The CALLER owns the transaction — hypothesise.py wraps this with the
        triage_* run-meta writes (get_meta/set_meta) that record the run-level
        status: triage_timeline_summary, triage_unexplained_signals,
        triage_degraded, triage_raw, triage_model, triage_prompt_hash,
        triage_created_at. The two list fields are json.dumps'd; citations_valid
        stores as int (T-04-02). No model value ever reaches SQL text —
        _HYP_COLUMNS is a module constant, values are all ?-bound (T-04-05).
        """
        self._conn.execute("DELETE FROM hypotheses")
        self._conn.executemany(
            f"INSERT INTO hypotheses ({_HYP_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    h.hyp_index,
                    h.title,
                    h.narrative,
                    h.confidence,
                    h.confidence_reasoning,
                    json.dumps(h.supporting_event_ids),
                    h.contradicting_evidence,
                    json.dumps(h.suggested_next_steps),
                    int(h.citations_valid),
                )
                for h in rows
            ],
        )

    def query_hypotheses(self) -> list[StoredHypothesis]:
        """Persisted hypotheses ordered by hyp_index ASC (RAG-02).

        Both JSON list columns are coerced defensively — a tampered case.db can
        hold ANY JSON here (WR-01, the query_clusters precedent): wrap a
        non-array as a single element and str() every element, so tampering
        stays visible and render-time sanitisation strips hostile bytes.
        """
        rows = self._conn.execute(
            f"SELECT {_HYP_COLUMNS} FROM hypotheses ORDER BY hyp_index"  # noqa: S608 — column list is a module constant
        ).fetchall()
        hyps: list[StoredHypothesis] = []
        for r in rows:
            hyps.append(
                StoredHypothesis(
                    hyp_index=r[0],
                    title=r[1],
                    narrative=r[2],
                    confidence=r[3],
                    confidence_reasoning=r[4],
                    supporting_event_ids=_coerce_str_list(r[5]),
                    contradicting_evidence=r[6],
                    suggested_next_steps=_coerce_str_list(r[7]),
                    citations_valid=bool(r[8]),
                )
            )
        return hyps

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
