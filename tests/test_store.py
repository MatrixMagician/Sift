"""CaseStore tests: migrations, idempotency, ordering, name validation."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sift.models import Event, event_id
from sift.store import (
    CaseStore,
    _migration_1,  # pyright: ignore[reportPrivateUsage] — builds a v1 fixture db
    case_db_path,
    validate_case_name,
)


def _ev(
    source_file: str = "app.log",
    offset: int = 0,
    ts: datetime | None = datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC),
    line_start: int = 1,
    raw: str = "raw",
) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id="demo",
        ts=ts,
        ts_confidence="exact" if ts is not None else "missing",
        source="genericlog",
        source_file=source_file,
        line_start=line_start,
        line_end=line_start,
        severity="info" if ts is not None else "unknown",
        component=None,
        thread=None,
        session=None,
        message="msg",
        attrs={},
        raw=raw,
    )


def test_fresh_store_applies_migration_1(tmp_path: Path) -> None:
    db = tmp_path / "case.db"
    store = CaseStore(db)
    store.close()
    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"events", "meta"} <= tables
    finally:
        conn.close()


def test_reingest_idempotent(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    events = [_ev(offset=0), _ev(offset=50, line_start=2)]
    assert store.insert_events(events) == 2
    assert store.insert_events(events) == 0
    assert len(store.query_events()) == 2


def test_query_events_deterministic_order(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    t1 = datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 16, 10, 0, 5, tzinfo=UTC)
    events = [
        _ev("b.log", offset=0, ts=None, line_start=1),  # NULL ts -> last
        _ev("a.log", offset=10, ts=t2, line_start=3),
        _ev("b.log", offset=20, ts=t1, line_start=1),  # equal ts: a.log first
        _ev("a.log", offset=30, ts=t1, line_start=5),
        _ev("a.log", offset=40, ts=t1, line_start=2),  # equal ts+file: line order
    ]
    store.insert_events(events)
    got = [(e.source_file, e.line_start, e.ts) for e in store.query_events()]
    assert got == [
        ("a.log", 2, t1),
        ("a.log", 5, t1),
        ("b.log", 1, t1),
        ("a.log", 3, t2),
        ("b.log", 1, None),
    ]


def test_ts_roundtrip(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    aware = datetime(2026, 7, 16, 12, 34, 56, tzinfo=UTC)
    store.insert_events([_ev(offset=0, ts=aware), _ev(offset=99, ts=None)])
    by_offset = {e.event_id: e for e in store.query_events()}
    assert by_offset[event_id("app.log", 0)].ts == aware
    assert by_offset[event_id("app.log", 99)].ts is None


def test_meta_roundtrip(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    assert store.get_meta("input_dir") is None
    store.set_meta("input_dir", "/data/logs")
    store.set_meta("input_dir", "/data/logs2")
    assert store.get_meta("input_dir") == "/data/logs2"


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.insert_events([_ev()])
            store.set_meta("parse_coverage", "{}")
            raise RuntimeError("interrupted ingest")
    assert store.query_events() == []
    assert store.get_meta("parse_coverage") is None


@pytest.mark.parametrize("name", ["case-1.2_x", "demo", "A.B-C_9"])
def test_validate_case_name_accepts(name: str) -> None:
    assert validate_case_name(name) == name


@pytest.mark.parametrize("name", ["..", ".", "", "a/b", "../../evil", "a\\b"])
def test_validate_case_name_rejects(name: str) -> None:
    with pytest.raises(ValueError):
        validate_case_name(name)


def test_case_db_path_layout(tmp_path: Path) -> None:
    assert case_db_path(tmp_path, "demo") == tmp_path / "cases" / "demo" / "case.db"
    with pytest.raises(ValueError):
        case_db_path(tmp_path, "../escape")


# --- plan 02-01: migration 2 + transparent zstd (STORE-02) -----------------


def test_fresh_store_reaches_user_version_2(tmp_path: Path) -> None:
    db = tmp_path / "case.db"
    CaseStore(db).close()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert "template_groups" in tables


def test_v1_to_v2_upgrade(tmp_path: Path) -> None:
    """Pitfall 7: a Phase-1 case.db reopened with Phase 2 code migrates to
    user_version 2 with oversized raw compressed in place and still readable."""
    db = tmp_path / "case.db"
    conn = sqlite3.connect(db)
    _migration_1(conn)
    conn.execute("PRAGMA user_version = 1")
    big = "x" * 5000
    conn.execute(
        "INSERT INTO events (event_id, case_id, ts, ts_confidence, source, "
        "source_file, line_start, line_end, severity, component, thread, "
        "session, message, attrs, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id("app.log", 0),
            "demo",
            "2026-07-16T10:00:00+00:00",
            "exact",
            "genericlog",
            "app.log",
            1,
            1,
            "info",
            None,
            None,
            None,
            "msg",
            "{}",
            big,
        ),
    )
    conn.commit()
    conn.close()

    store = CaseStore(db)
    assert [e.raw for e in store.query_events()] == [big]
    store.close()

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT typeof(raw) FROM events").fetchone()[0] == "blob"
    finally:
        conn.close()


def test_raw_zstd_threshold_boundary(tmp_path: Path) -> None:
    """STORE-02 boundary: 0 and exactly 4096 encoded bytes stay TEXT;
    4097 encoded bytes becomes a zstd BLOB; all round-trip verbatim."""
    db = tmp_path / "case.db"
    store = CaseStore(db)
    payloads = {0: "", 1: "a" * 4096, 2: "b" * 4097}
    store.insert_events([_ev(offset=o, raw=r) for o, r in payloads.items()])
    got = {e.event_id: e.raw for e in store.query_events()}
    for o, r in payloads.items():
        assert got[event_id("app.log", o)] == r
    store.close()

    conn = sqlite3.connect(db)
    try:
        types: dict[str, str] = dict(
            conn.execute("SELECT event_id, typeof(raw) FROM events").fetchall()
        )
    finally:
        conn.close()
    assert types[event_id("app.log", 0)] == "text"
    assert types[event_id("app.log", 1)] == "text"
    assert types[event_id("app.log", 2)] == "blob"


def test_zstd_threshold_measured_in_encoded_bytes(tmp_path: Path) -> None:
    """Pitfall 3: the 4 KB threshold counts UTF-8 encoded bytes, not chars."""
    payload = "é" * 2500  # 2,500 chars but 5,000 UTF-8 bytes
    assert len(payload) < 4096 < len(payload.encode("utf-8"))
    db = tmp_path / "case.db"
    store = CaseStore(db)
    store.insert_events([_ev(raw=payload)])
    assert store.query_events()[0].raw == payload
    store.close()

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT typeof(raw) FROM events").fetchone()[0] == "blob"
    finally:
        conn.close()


def test_reopen_migrated_store_is_noop(tmp_path: Path) -> None:
    """Migration idempotency: reopening a v2 store leaves user_version at 2
    and stored row bytes unchanged."""
    db = tmp_path / "case.db"
    store = CaseStore(db)
    store.insert_events([_ev(offset=0, raw="z" * 5000), _ev(offset=1, raw="small")])
    store.close()

    def snapshot() -> tuple[int, list[Any]]:
        conn = sqlite3.connect(db)
        try:
            ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
            rows = conn.execute(
                "SELECT event_id, raw FROM events ORDER BY event_id"
            ).fetchall()
        finally:
            conn.close()
        return ver, rows

    first = snapshot()
    assert first[0] == 2
    CaseStore(db).close()
    assert snapshot() == first
