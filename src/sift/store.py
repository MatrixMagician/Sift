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
import uuid
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
from datetime import UTC, datetime
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


def _blob_to_vec(
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


def _migration_5(conn: sqlite3.Connection) -> None:
    """Add the separate, structurally non-citable KB namespace (RAG-07, D-01).

    KB chunks live in their OWN table with NO ``event_id`` column anywhere —
    so a KB row can never be assigned an event id and can never enter the
    citable set (``prompted_ids`` / ``supporting_event_ids``). Non-citability
    is a structural guarantee here, not a prompt wording. The ``kb_vectors``
    vec0 table is created lazily (dim unknown until the first embed), mirroring
    ``ensure_vectors_table`` — it is deliberately NOT created in this migration.
    """
    conn.execute(
        """
        CREATE TABLE kb_chunks (
            kb_chunk_id INTEGER PRIMARY KEY,
            source_file TEXT NOT NULL,    -- runbook path, KB-relative
            ordinal     INTEGER NOT NULL, -- chunk index within the file
            text        TEXT NOT NULL     -- chunk text (NEVER an event, NEVER cited)
        )
        """
    )


def _migration_6(conn: sqlite3.Connection) -> None:
    """Add the append-only verdicts table — the M002 learning contract (D003).

    Three states at three target levels, CHECK-enforced as defence in depth
    behind the Python allowlists in :meth:`CaseStore.record_verdict`. The
    ``context`` and ``provenance`` columns are JSON snapshots so M002 can
    harvest every case.db directly without this milestone's runtime (D005).
    Append-only is an API invariant, not a trigger: no UPDATE/DELETE path for
    verdicts exists anywhere in this module — re-analysis keeps prior verdicts
    as visible history.
    """
    conn.execute(
        """
        CREATE TABLE verdicts (
            verdict_id  TEXT PRIMARY KEY,      -- uuid4 hex
            target_type TEXT NOT NULL
                CHECK (target_type IN ('hypothesis','cluster','template')),
            target_id   TEXT NOT NULL,
            verdict     TEXT NOT NULL
                CHECK (verdict IN ('confirmed','rejected','uncertain')),
            note        TEXT NOT NULL DEFAULT '',
            context     TEXT NOT NULL,         -- JSON snapshot of the target
            provenance  TEXT NOT NULL,         -- JSON: run marker, model, prompt hash
            created_at  TEXT NOT NULL          -- ISO 8601, UTC
        )
        """
    )
    conn.execute("CREATE INDEX idx_verdicts_target ON verdicts(target_type, target_id)")
    conn.execute("CREATE INDEX idx_verdicts_created ON verdicts(created_at)")


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,  # chunks + clusters tables (NOT vectors — that is lazy)
    4: _migration_4,  # hypotheses table (citation-gated triage output)
    5: _migration_5,  # kb_chunks table (separate non-citable KB namespace, D-01)
    6: _migration_6,  # verdicts table (append-only M002 learning contract, D003)
}

# The single spelling of the verdict vocabulary (D003). The CLI, TUI and the
# CHECK constraints in migration 6 must all agree — export these rather than
# re-typing the literals anywhere else (S01 research Pitfall 4).
VERDICT_STATES: frozenset[str] = frozenset({"confirmed", "rejected", "uncertain"})
VERDICT_TARGET_TYPES: frozenset[str] = frozenset({"hypothesis", "cluster", "template"})

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

# KB namespace columns (D-01): deliberately NO event_id — KB is never citable.
_KB_CHUNK_COLUMNS = "kb_chunk_id, source_file, ordinal, text"

_CLUSTER_COLUMNS = (
    "cluster_id, label, signature, severity_max, count, template_ids"
)

_HYP_COLUMNS = (
    "hyp_index, title, narrative, confidence, confidence_reasoning, "
    "supporting_event_ids, contradicting_evidence, suggested_next_steps, "
    "citations_valid"
)

_VERDICT_COLUMNS = (
    "verdict_id, target_type, target_id, verdict, note, context, "
    "provenance, created_at"
)

# Sources held out of every ranking stage (PERF-03, EUS-11). Perfmon samples
# are periodic observations, not diagnostics: they carry no incident signal
# to dedup, cluster, salience or hypothesis excerpts, and thousands of near-
# identical rows would dominate template counts. Eu-stack thread records are
# a population census, not diagnostics either: they are replaced for ranking
# purposes by the deterministic `sift eustack` analyser and the Phase-18 fact
# block, and thousands of near-identical thread bodies would likewise
# dominate template counts. Both stay FULLY retrievable by identifier, so
# citation and `show events` are unaffected — see the paired comments on
# iter_event_summaries / iter_event_rows below.
# Owned here, never caller-supplied: exclusion is a property of the source
# kind, not of the caller (D-07).
EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon", "eustack"})

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

# Allowlist for the verdicts table (list_verdicts). Exact-match keys only —
# verdict browsing narrows by level, target and state (D003).
_VERDICT_FILTER_SQL: dict[str, str] = {
    "target-type": "target_type = ?",
    "target-id": "target_id = ?",
    "verdict": "verdict = ?",
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
    render-time sanitisation strips hostile bytes. Shared by the template-group,
    cluster and hypothesis read paths.
    """
    loaded: object = json.loads(value)
    if not isinstance(loaded, list):
        loaded = [loaded]
    items = cast("list[object]", loaded)
    return [str(x) for x in items]


def _coerce_json_dict(value: str) -> dict[str, object]:
    """WR-01: decode a JSON object column from an UNTRUSTED case.db to a dict.

    Verdict ``context``/``provenance`` snapshots are harvested cross-case by
    M002 (D005), so this read path is extra defensive: invalid JSON or a
    non-object payload is wrapped under a fixed ``"value"`` key rather than
    crashing — tampering stays visible, the type contract holds.
    """
    try:
        loaded: object = json.loads(value)
    except json.JSONDecodeError:
        return {"value": value}
    if not isinstance(loaded, dict):
        return {"value": loaded}
    items = cast("dict[object, object]", loaded)
    return {str(k): v for k, v in items.items()}


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


@dataclass(frozen=True)
class Verdict:
    """One append-only human verdict row (D003) — the M002 learning contract.

    ``context`` and ``provenance`` are the parsed JSON snapshot columns; their
    field vocabulary is owned by the shared verdict service (verdicts.py), not
    the store — the store persists and returns them opaquely.
    """

    verdict_id: str  # uuid4 hex
    target_type: str  # 'hypothesis' | 'cluster' | 'template' (CHECK-enforced)
    target_id: str
    verdict: str  # 'confirmed' | 'rejected' | 'uncertain' (CHECK-enforced)
    note: str  # free text, '' when the operator gave none
    context: dict[str, object]  # snapshot of the judged target
    provenance: dict[str, object]  # run marker, model, prompt hash
    created_at: str  # ISO 8601, UTC


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
    def savepoint(self) -> Generator[None]:
        """Nested atomic unit inside an open transaction (CR-01).

        Ingest wraps each file's detect+parse+insert body so a mid-stream
        parse failure rolls that FILE back to zero rows while the outer
        all-or-nothing BEGIN IMMEDIATE transaction survives — SQLite
        savepoints nest inside an open transaction natively. The name is
        interpolated into SQL text but comes only from the module constant
        ``_SAVEPOINT_INGEST_FILE`` — a code constant, never user data
        (the PRAGMA user_version precedent, T-02-13).
        """
        name = _SAVEPOINT_INGEST_FILE
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

    def query_events(self, sources: Sequence[str] | None = None) -> list[Event]:
        """Events ordered by ts (NULLs last), source_file, line_start.

        ``sources`` scopes the result to those ``Event.source`` values — the
        memory seam for full-``Event`` consumers: every row hydrates its
        (possibly zstd-compressed) ``raw``, so an unscoped call materialises
        the entire decompressed case. Analyser paths pass the sources they
        actually consume (e.g. ``analysers.ANALYSER_SOURCES``) so a huge
        genericlog case is never decompressed just to build fact blocks.
        ``None`` keeps the read-everything behaviour. Source values are
        ``?``-bound, never interpolated.
        """
        where = ""
        params: tuple[str, ...] = ()
        if sources is not None:
            ordered = sorted(set(sources))
            placeholders = ",".join("?" for _ in ordered)
            # S608: only the placeholder COUNT is interpolated; every source
            # value is ?-bound (iter_event_summaries idiom).
            where = f"WHERE source IN ({placeholders}) "  # noqa: S608
            params = tuple(ordered)
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM events "  # noqa: S608 — column list is a module constant
            + where
            + "ORDER BY ts IS NULL, ts, source_file, line_start",
            params,
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

        EXCLUDES ``EXCLUDED_FROM_RANKING`` sources by source kind (PERF-03).
        This is the single seam every ranking stage reads: dedup, cluster
        exemplars, hypothesis excerpts and the eval runner all inherit the
        filter from here, so no stage re-implements it. The near-identical
        ``iter_event_rows`` below deliberately does NOT filter — see its
        docstring before merging these two into a shared helper.
        Pinned by test_iter_event_summaries_excludes_perfmon and
        test_template_groups_exclude_perfmon.
        """
        # sorted() fixes parameter order: frozenset iteration order is not
        # guaranteed stable across builds and this query feeds a
        # determinism-critical pipeline.
        excluded = sorted(EXCLUDED_FROM_RANKING)
        placeholders = ",".join("?" for _ in excluded)
        cursor = self._conn.execute(
            # S608: only the placeholder COUNT is interpolated; every source
            # value is ?-bound from a module constant (get_events_by_ids idiom).
            "SELECT event_id, ts, severity, message FROM events "  # noqa: S608
            f"WHERE source NOT IN ({placeholders}) "
            "ORDER BY ts IS NULL, ts, source_file, line_start",
            tuple(excluded),
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

        Deliberately does NOT apply ``EXCLUDED_FROM_RANKING``, unlike the
        near-identical ``iter_event_summaries`` above. PERF-03 holds perfmon
        out of RANKING only; citation and evidence display must never be
        filtered, or evidence silently vanishes from a triage report. The
        asymmetry is the point, not an oversight — do not unify these two
        methods into a shared helper. Pinned by test_iter_event_rows_unfiltered
        and test_show_events_includes_perfmon.
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
            groups.append(
                TemplateGroup(
                    template_id=r[0],
                    template=r[1],
                    count=r[2],
                    first_ts=r[3],
                    last_ts=r[4],
                    severity_max=r[5],
                    # WR-01: a tampered case.db can hold ANY JSON here —
                    # _coerce_str_list keeps the tampering visible instead of
                    # crashing the read path.
                    exemplar_event_ids=_coerce_str_list(r[6]),
                )
            )
        return groups

    def _check_embedding_dim(self, dim: int) -> str | None:
        """STORE-03 guard: return ``meta.embedding_dim``, raising on a mismatch
        with ``dim`` — a differing dimension is never silently re-indexed."""
        existing = self.get_meta("embedding_dim")
        if existing is not None and int(existing) != dim:
            raise ValueError(
                f"embedding dimension mismatch: index has {existing}, "
                f"server returned {dim}"
            )
        return existing

    def _ensure_vec_table(self, table: str, id_col: str, dim: int) -> None:
        """Shared body of the two vec0 ensure-* methods: same STORE-03 guard,
        same lazy extension load, same DDL shape, same meta writes."""
        existing = self._check_embedding_dim(dim)
        self._ensure_vec_loaded()
        self._conn.execute(
            # dim is our validated int, never user text (the PRAGMA
            # user_version precedent, T-02-13).
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "  # noqa: S608 — table/id_col are module-fixed names; dim is our int, never user text
            f"USING vec0({id_col} INTEGER PRIMARY KEY, embedding FLOAT[{int(dim)}])"
        )
        if existing is None:
            self.set_meta("embedding_dim", str(dim))
            self.set_meta("embedding_metric", "cosine")

    def ensure_vectors_table(self, dim: int) -> None:
        """Lazily create the sqlite-vec vec0 vectors table at ``dim`` (D-03).

        The dimension is unknown until the server returns the first embedding,
        so the ``vec0`` table cannot live in a migration. STORE-03 hard error:
        if ``meta.embedding_dim`` already records a different dimension, raise
        ValueError naming both dims BEFORE loading the extension or writing
        anything — a mismatch is never silently re-indexed. sqlite-vec is
        loaded lazily here (never in ``__init__``). KNN retrieval in Phase 4/6
        uses ``WHERE embedding MATCH ? AND k = ?`` against this table.
        """
        self._ensure_vec_table("vectors", "chunk_id", dim)

    def record_embedding_identity(self, model: str, dim: int) -> None:
        """Record the server's embedding model + dimension in meta (STORE-03).

        ``embedding_dim`` is owned by :meth:`ensure_vectors_table` (the
        mismatch guard); this method records the model for provenance and only
        sets the dim when absent — a differing dim raises, so it can never mask
        the hard-error guard on reload.
        """
        self.set_meta("embedding_model", model)
        existing = self._check_embedding_dim(dim)
        if existing is None:
            self.set_meta("embedding_dim", str(dim))

    def record_embedding_batch_knobs(
        self, *, context: int, batch_size: int, max_input_chars: int
    ) -> None:
        """Record the embedding batch-layout knobs actually used, as meta (0014).

        Batch composition perturbs the embedding vectors well above float32
        noise (`.planning/todos/pending/2026-07-21-embedding-batch-composition-
        determinism.md`, ADR 0014), so the layout must be recoverable from the
        case to make a divergent re-run diagnosable.

        Deliberately does NOT mirror :meth:`record_embedding_identity`'s
        mismatch guard: an unconditional overwrite, no read, no comparison, no
        raise. Unlike the model/dim identity (which should not silently
        change), these three knobs legitimately vary between runs as ordinary
        reconfiguration — hard-failing on a changed value would make a
        re-analyze impossible after any config tweak.
        """
        self.set_meta("embedding_context", str(context))
        self.set_meta("embedding_batch_size", str(batch_size))
        self.set_meta("embedding_max_input_chars", str(max_input_chars))

    def load_vectors_by_text(self) -> dict[str, list[float]]:
        """Read every stored (chunks.text, vector) pair, keyed by exact text (D-01).

        The DET-01 reuse read: joining ``chunks`` to ``vectors`` on
        ``chunk_id`` recovers the text-to-embedding map with no schema
        migration. The ``ORDER BY`` on ``chunks.chunk_id`` makes the winner
        deterministic if two rows ever hold byte-identical text — the highest
        ``chunk_id`` wins, never unspecified SQLite row order. A case with no
        ``vectors`` table yet (vec0 tables are created lazily) degrades to an
        empty map so a first run simply embeds everything.
        """
        self._ensure_vec_loaded()
        try:
            rows = self._conn.execute(
                "SELECT chunks.text, vectors.embedding FROM chunks "
                "JOIN vectors USING (chunk_id) ORDER BY chunks.chunk_id"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {str(text): _blob_to_vec(blob) for text, blob in rows}

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

    def ensure_kb_vectors_table(self, dim: int) -> None:
        """Lazily create the sqlite-vec vec0 ``kb_vectors`` table at ``dim``.

        Mirrors :meth:`ensure_vectors_table`: the KB shares the case's embedding
        model and dimension, so it reuses the SAME ``meta.embedding_dim`` guard
        (STORE-03) — a mismatch is a hard error, never a silent re-index
        (Pitfall 3). The vec0 table is created lazily here (dim unknown until
        the first embed), never in a migration. The KB namespace is physically
        separate from the citable ``vectors`` table (D-01).
        """
        self._ensure_vec_table("kb_vectors", "kb_chunk_id", dim)

    def drop_vector_tables(self) -> tuple[int, int]:
        """Drop BOTH vec0 tables and clear the shared dimension meta (D-08).

        Returns ``(dropped_vectors, dropped_kb_vectors)`` — the real counted row
        totals, so the caller's operator-facing announcement cannot disagree
        with what was actually discarded.

        The CALLER owns the transaction (mirrors :meth:`upsert_vectors`):
        pipeline/cluster.py calls this as the first statement of the one
        ``store.transaction()`` that owns every write in a run, so an
        interrupted rebuild rolls back to the ORIGINAL tables at their ORIGINAL
        declared widths.

        Both tables are dropped together and unconditionally. ``vectors`` and
        ``kb_vectors`` share ``meta.embedding_dim``, so dropping one alone would
        leave the other at a stale declared width that
        ``CREATE VIRTUAL TABLE IF NOT EXISTS`` silently no-ops against — the
        latent corruption D-08 exists to prevent. Pairing them in one method
        makes that mistake structurally impossible rather than merely tested.

        ``kb_chunks`` is cleared alongside, so the KB namespace never retains
        chunks whose vectors were just discarded; ``index_kb`` replaces the
        whole table on every ``--kb`` run anyway, so nothing is lost that would
        not have been replaced.

        Recreation is deliberately NOT done here: ``vectors`` is recreated by
        the ``ensure_vectors_table(dim)`` call the caller already makes, and
        ``kb_vectors`` lazily on the next ``--kb`` run at the new width. That
        keeps this phase free of any new dimension-interpolating DDL — the only
        such sites in this file remain the two reviewed ``ensure_*_table``
        statements (T-20-04).
        """
        self._ensure_vec_loaded()

        def _count(sql: str) -> int:
            try:
                row = self._conn.execute(sql).fetchone()
            except sqlite3.OperationalError:
                return 0  # table absent — nothing stored to discard
            return int(row[0])

        # Fully literal SQL: no table name is ever interpolated here, so this
        # method adds no S608-suppressed site (T-20-04).
        dropped_vectors = _count("SELECT count(*) FROM vectors")
        dropped_kb = _count("SELECT count(*) FROM kb_vectors")
        # Dropping the primary vec0 name drops all four shadow tables with it
        # (verified against the pinned sqlite-vec==0.1.9) — no manual cleanup.
        self._conn.execute("DROP TABLE IF EXISTS vectors")
        self._conn.execute("DROP TABLE IF EXISTS kb_vectors")
        self._conn.execute("DELETE FROM kb_chunks")
        # Clearing the shared dim is what lets the very next
        # ensure_vectors_table(new_dim) take its create-and-record branch. The
        # STORE-03 guard is never weakened or given a bypass: the rebuild works
        # by clearing state BEFORE the guard runs (RESEARCH Pitfall 4).
        self._conn.executemany(
            "DELETE FROM meta WHERE key = ?",
            [("embedding_dim",), ("embedding_metric",)],
        )
        return dropped_vectors, dropped_kb

    def replace_kb_chunks(
        self, chunks: Iterable[tuple[int, str, int, str]]
    ) -> None:
        """DELETE FROM kb_chunks then insert (kb_chunk_id, source_file, ordinal, text).

        The CALLER owns the transaction (mirrors replace_chunks): retrieve.py
        wraps this with the KB vector writes so an interrupted index rolls back
        to zero KB rows. KB rows carry NO event_id — non-citability is
        structural (D-01).
        """
        self._conn.execute("DELETE FROM kb_chunks")
        self._conn.executemany(
            f"INSERT INTO kb_chunks ({_KB_CHUNK_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?)",
            list(chunks),
        )

    def upsert_kb_vectors(self, rows: Iterable[tuple[int, list[float]]]) -> None:
        """Write (kb_chunk_id, embedding) pairs to the KB vec0 table.

        The CALLER owns the transaction (mirrors upsert_vectors). Every vector
        byte is produced here via ``_vec_to_blob`` — the confinement invariant.
        vec0 has no ``INSERT OR REPLACE`` so a prior row is deleted first.
        """
        self._ensure_vec_loaded()
        pairs = [(kb_chunk_id, _vec_to_blob(vec)) for kb_chunk_id, vec in rows]
        self._conn.executemany(
            "DELETE FROM kb_vectors WHERE kb_chunk_id = ?",
            [(kb_chunk_id,) for kb_chunk_id, _ in pairs],
        )
        self._conn.executemany(
            "INSERT INTO kb_vectors (kb_chunk_id, embedding) VALUES (?, ?)", pairs
        )

    def knn_kb_chunks(self, qvec: list[float], k: int) -> list[str]:
        """Return the k nearest KB chunk texts by vector similarity (RAG-07).

        The vec0 KNN idiom (``WHERE embedding MATCH ? AND k = ?``) confined to
        store.py alongside the blob pair. Returns KB texts only — NEVER event
        ids, because the KB namespace has no event_id (D-01).
        """
        self._ensure_vec_loaded()
        try:
            rows = self._conn.execute(
                "SELECT kb.text FROM kb_vectors v "
                "JOIN kb_chunks kb ON kb.kb_chunk_id = v.kb_chunk_id "
                "WHERE v.embedding MATCH ? AND k = ? ORDER BY distance",
                (_vec_to_blob(qvec), int(k)),
            ).fetchall()
        except sqlite3.OperationalError:
            # CR-01: the lazy kb_vectors vec0 table is only created once a KB is
            # actually indexed (index_kb short-circuits on an empty/Markdown-free
            # --kb dir). An un-indexed KB is an empty index, not a crash — never
            # let a raw OperationalError escape to the CLI (never-crash invariant).
            return []
        return [str(r[0]) for r in rows]

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
            clusters.append(
                Cluster(
                    cluster_id=r[0],
                    label=r[1],
                    signature=r[2],
                    severity_max=r[3],
                    count=r[4],
                    # WR-01: a tampered case.db can hold ANY JSON here —
                    # _coerce_str_list keeps the tampering visible instead of
                    # crashing the read path.
                    template_ids=_coerce_str_list(r[5]),
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

    def record_verdict(
        self,
        *,
        target_type: str,
        target_id: str,
        verdict: str,
        context: Mapping[str, object],
        provenance: Mapping[str, object],
        note: str = "",
        created_at: str | None = None,
    ) -> str:
        """Append ONE verdict row; returns its new verdict_id (D003, D004).

        The SINGLE verdict write path — the CLI and the TUI both land here.
        INSERT-only: no update or delete method for verdicts exists anywhere
        in this module, so re-analysis keeps prior verdicts as history.
        Vocabulary is validated in Python first (helpful ValueError naming the
        valid values, mirroring _build_filter_clauses) with the migration-6
        CHECK constraints as defence in depth.

        A single INSERT statement: atomic on its own in autocommit mode, and
        it joins a caller-owned :meth:`transaction` when one is open — the TUI
        batches multiple verdicts that way. ``created_at`` defaults to now in
        UTC; callers may pin it (tests, replayed imports) but never rewrite it.
        """
        if target_type not in VERDICT_TARGET_TYPES:
            valid = ", ".join(sorted(VERDICT_TARGET_TYPES))
            raise ValueError(
                f"unknown verdict target type {target_type!r}; valid: {valid}"
            )
        if verdict not in VERDICT_STATES:
            valid = ", ".join(sorted(VERDICT_STATES))
            raise ValueError(f"unknown verdict state {verdict!r}; valid: {valid}")
        verdict_id = uuid.uuid4().hex
        stamp = (
            created_at
            if created_at is not None
            else datetime.now(UTC).isoformat()
        )
        self._conn.execute(
            f"INSERT INTO verdicts ({_VERDICT_COLUMNS}) "  # noqa: S608 — column list is a module constant, values are all ?
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                verdict_id,
                target_type,
                target_id,
                verdict,
                note,
                json.dumps(dict(context), sort_keys=True),
                json.dumps(dict(provenance), sort_keys=True),
                stamp,
            ),
        )
        return verdict_id

    def list_verdicts(
        self, filters: Mapping[str, str | int] | None = None
    ) -> list[Verdict]:
        """Verdicts ordered newest first: created_at DESC, then rowid DESC.

        The rowid tiebreak makes equal timestamps deterministic (latest
        insertion first), never unspecified SQLite row order. Filters use the
        allowlisted _VERDICT_FILTER_SQL snippets with ?-bound values
        (T-02-08); an unknown key raises ValueError. The JSON snapshot columns
        are coerced defensively — a tampered case.db can hold ANY JSON there
        (WR-01), and M002 reads these cross-case.
        """
        where_sql, limit_sql, params = _build_filter_clauses(
            filters, _VERDICT_FILTER_SQL
        )
        rows = self._conn.execute(
            f"SELECT {_VERDICT_COLUMNS} FROM verdicts"  # noqa: S608 — column list and WHERE snippets are module constants; values are all ?
            f"{where_sql} ORDER BY created_at DESC, rowid DESC{limit_sql}",
            params,
        ).fetchall()
        return [
            Verdict(
                verdict_id=r[0],
                target_type=r[1],
                target_id=r[2],
                verdict=r[3],
                note=r[4],
                context=_coerce_json_dict(r[5]),
                provenance=_coerce_json_dict(r[6]),
                created_at=r[7],
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
