"""Per-case SQLite store.

This module owns ALL SQL in the codebase (single reviewable SQL owner,
T-02-02): every statement uses parameterised ``?`` placeholders — no value is
ever interpolated into SQL text. Migrations are numbered functions applied by
a ``PRAGMA user_version`` runner (D-03); Phase 2 extends the same store.
"""

import json
import re
import sqlite3
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sift.models import Event

_CASE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
}

_EVENT_COLUMNS = (
    "event_id, case_id, ts, ts_confidence, source, source_file, "
    "line_start, line_end, severity, component, thread, session, "
    "message, attrs, raw"
)


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
                self._conn.execute("ROLLBACK")
                raise

    @contextmanager
    def transaction(self) -> Generator[None]:
        """One atomic unit — ingest wraps all inserts plus the coverage meta write."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

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
                e.raw,
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
                raw=r[14],
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
