"""CaseStore tests: migrations, idempotency, ordering, name validation."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sift.models import Event, event_id
from sift.store import (
    CaseStore,
    TemplateGroup,
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
    severity: str | None = None,
    message: str = "msg",
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
        severity=severity or ("info" if ts is not None else "unknown"),
        component=None,
        thread=None,
        session=None,
        message=message,
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


# --- plan 02-03: filtered queries + streaming rows (STORE-04) ---------------


def _rows(
    store: CaseStore, filters: dict[str, str | int] | None = None
) -> list[tuple[str, str | None, str, str, int, str]]:
    return list(store.iter_event_rows(filters))


def _groups(
    store: CaseStore, filters: dict[str, str | int] | None = None
) -> list[TemplateGroup]:
    return store.query_template_groups(filters)


def _seed_filter_events(store: CaseStore) -> None:
    def t(second: int) -> datetime:
        return datetime(2026, 7, 16, 10, 0, second, tzinfo=UTC)

    store.insert_events(
        [
            _ev("a.log", offset=0, ts=t(0), severity="error", message="boom"),
            _ev("a.log", offset=50, ts=t(1), line_start=2, message="fine"),
            _ev("b.log", offset=0, ts=t(2), severity="error", message="boom too"),
            _ev("b.log", offset=50, ts=None, line_start=2, message="lost in time"),
        ]
    )


def test_iter_event_rows_yields_scoped_tuples(tmp_path: Path) -> None:
    """Rows are 6-tuples (event_id, ts, severity, source_file, line_start,
    message) in the canonical query_events order — arity proves raw is never
    selected (T-02-10)."""
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    rows = _rows(store)
    assert len(rows) == 4
    assert all(isinstance(r, tuple) and len(r) == 6 for r in rows)
    expected = [
        (
            e.event_id,
            e.ts.isoformat() if e.ts is not None else None,
            e.severity,
            e.source_file,
            e.line_start,
            e.message,
        )
        for e in store.query_events()
    ]
    assert rows == expected


def test_iter_event_rows_severity_filter(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    rows = _rows(store, {"severity": "error"})
    assert [r[2] for r in rows] == ["error", "error"]


def test_iter_event_rows_file_substring_filter(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    assert {r[3] for r in _rows(store, {"file": "a."})} == {"a.log"}
    assert _rows(store, {"file": "nowhere"}) == []


def test_iter_event_rows_source_filter(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    assert len(_rows(store, {"source": "genericlog"})) == 4
    assert _rows(store, {"source": "journald"}) == []


def test_iter_event_rows_since_until_exclude_null_ts(tmp_path: Path) -> None:
    """since/until bound the ts range AND exclude NULL-ts rows — a documented
    filter semantic, not silent loss (recorded in --help)."""
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    since = _rows(store, {"since": "2026-07-16T10:00:01+00:00"})
    assert [r[5] for r in since] == ["fine", "boom too"]  # NULL-ts row absent
    until = _rows(store, {"until": "2026-07-16T10:00:01+00:00"})
    assert [r[5] for r in until] == ["boom", "fine"]  # NULL-ts row absent


def test_iter_event_rows_limit(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    rows = _rows(store, {"limit": 2})
    assert [r[5] for r in rows] == ["boom", "fine"]  # first 2 in canonical order


def test_iter_event_rows_filters_and_combine(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    rows = _rows(store, {"severity": "error", "file": "b."})
    assert [(r[2], r[3]) for r in rows] == [("error", "b.log")]


def test_iter_event_rows_unknown_key_raises_valueerror(tmp_path: Path) -> None:
    """Defence in depth behind the CLI validation (T-02-08)."""
    store = CaseStore(tmp_path / "case.db")
    _seed_filter_events(store)
    with pytest.raises(ValueError, match="severity"):
        _rows(store, {"bogus": "1"})


def _seed_groups(store: CaseStore) -> None:
    def g(template: str, count: int, severity_max: str) -> TemplateGroup:
        return TemplateGroup(
            template_id=template[:16].ljust(16, "0"),
            template=template,
            count=count,
            first_ts=None,
            last_ts=None,
            severity_max=severity_max,
            exemplar_event_ids=[],
        )

    store.replace_template_groups(
        [
            g("connection pool exhausted after <NUM> retries", 30, "error"),
            g("disk <NUM>% full", 5, "warn"),
            g("service started", 1, "info"),
        ]
    )


def test_query_template_groups_min_count_filter(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_groups(store)
    got = _groups(store, {"min-count": 5})
    assert [grp.count for grp in got] == [30, 5]


def test_query_template_groups_contains_is_literal_not_like(tmp_path: Path) -> None:
    """contains uses instr semantics: a % in the value matches only a literal
    % — never a LIKE wildcard (T-02-08)."""
    store = CaseStore(tmp_path / "case.db")
    _seed_groups(store)
    assert [grp.template for grp in _groups(store, {"contains": "pool"})] == [
        "connection pool exhausted after <NUM> retries"
    ]
    # Literal-% positive match...
    assert [grp.template for grp in _groups(store, {"contains": "<NUM>% full"})] == [
        "disk <NUM>% full"
    ]
    # ...and a LIKE-style wildcard pattern matches nothing.
    assert _groups(store, {"contains": "d%full"}) == []


def test_query_template_groups_severity_and_limit_filters(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_groups(store)
    assert [grp.severity_max for grp in _groups(store, {"severity": "error"})] == [
        "error"
    ]
    assert [grp.count for grp in _groups(store, {"limit": 1})] == [30]


def test_query_template_groups_unknown_key_raises_valueerror(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    _seed_groups(store)
    with pytest.raises(ValueError, match="min-count"):
        _groups(store, {"bogus": "1"})
