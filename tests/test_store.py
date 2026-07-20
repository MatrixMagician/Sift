"""CaseStore tests: migrations, idempotency, ordering, name validation."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.store import (
    CaseStore,
    StoredHypothesis,
    TemplateGroup,
    _migration_1,  # pyright: ignore[reportPrivateUsage] — builds a v1 fixture db
    _migration_3,  # pyright: ignore[reportPrivateUsage] — builds a v3 fixture db
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
    source: str = "genericlog",
) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id="demo",
        ts=ts,
        ts_confidence="exact" if ts is not None else "missing",
        source=source,
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


def test_fresh_store_reaches_latest_user_version(tmp_path: Path) -> None:
    db = tmp_path / "case.db"
    CaseStore(db).close()
    conn = sqlite3.connect(db)
    try:
        # Plan 06-03 migration 5 adds the KB namespace, head schema is v5.
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
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
    """Pitfall 7: a Phase-1 case.db reopened with later code migrates through
    to the latest schema (v5) with oversized raw compressed in place and still
    readable — migration 2's zstd-in-place upgrade still runs on the way up."""
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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
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
    """Migration idempotency: reopening a fully-migrated store leaves
    user_version at the latest schema (5) and stored row bytes unchanged."""
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
    assert first[0] == 5
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


# --- plan 02-04: gap closure (WR-01, WR-02) ---------------------------------


def test_query_template_groups_non_list_exemplar_json_coerced(
    tmp_path: Path,
) -> None:
    """WR-01: tampered non-array exemplar_event_ids JSON is coerced to a
    list[str] instead of poisoning TemplateGroup's type contract."""
    store = CaseStore(tmp_path / "case.db")
    _seed_groups(store)
    store._conn.execute(  # pyright: ignore[reportPrivateUsage] — tampering fixture
        "UPDATE template_groups SET exemplar_event_ids = ? "
        "WHERE rowid = (SELECT rowid FROM template_groups LIMIT 1)",
        ('{"a": 1}',),
    )
    groups = store.query_template_groups()
    for g in groups:
        assert isinstance(g.exemplar_event_ids, list)
        assert all(isinstance(x, str) for x in g.exemplar_event_ids)
    store.close()


def test_migration_prints_stderr_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """WR-02: applying a migration announces itself on stderr — `show` never
    rewrites evidence files silently. Reopening at head is silent."""
    db = tmp_path / "case.db"
    CaseStore(db).close()
    err = capsys.readouterr().err
    assert "migrating case.db to schema v1" in err
    assert "migrating case.db to schema v2" in err

    CaseStore(db).close()  # already at head: no migration, no notice
    assert "migrating" not in capsys.readouterr().err


# --- plan 04-01: migration 4 — hypotheses table (RAG-02, RAG-04) ------------


def _hyp(index: int, *, valid: bool = True) -> StoredHypothesis:
    return StoredHypothesis(
        hyp_index=index,
        title=f"hypothesis {index}",
        narrative="working-set pressure evicted cubes",
        confidence="high",
        confidence_reasoning="three fatal events share a SID",
        supporting_event_ids=[event_id("app.log", index)],
        contradicting_evidence=None if index else "cube cache was warm",
        suggested_next_steps=["raise the working-set cap"],
        citations_valid=valid,
    )


def test_v3_to_v4_migration_adds_hypotheses_table(tmp_path: Path) -> None:
    """A v3 case.db opened by the new code migrates to v4 and gains the
    hypotheses table (the runner announces v4 on stderr)."""
    db = tmp_path / "case.db"
    conn = sqlite3.connect(db)
    _migration_1(conn)
    _migration_3(conn)  # migration 2 is an in-place raw compression, table-free
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    CaseStore(db).close()  # applies migrations 4 and 5

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert "hypotheses" in tables


def test_replace_and_query_hypotheses_roundtrip(tmp_path: Path) -> None:
    """replace_hypotheses persists rows; query_hypotheses reads them back equal,
    ordered by hyp_index; a second replace is idempotent (RAG-02)."""
    store = CaseStore(tmp_path / "case.db")
    rows = [_hyp(2, valid=False), _hyp(0), _hyp(1)]
    with store.transaction():
        store.replace_hypotheses(rows)
    got = store.query_hypotheses()
    assert [h.hyp_index for h in got] == [0, 1, 2]  # ordered ASC
    assert got[2].citations_valid is False
    assert got[0].supporting_event_ids == [event_id("app.log", 0)]

    with store.transaction():
        store.replace_hypotheses([_hyp(0)])
    assert [h.hyp_index for h in store.query_hypotheses()] == [0]
    store.close()


def test_query_hypotheses_non_list_json_coerced(tmp_path: Path) -> None:
    """WR-01: tampered non-array JSON in a list column coerces to list[str]
    instead of crashing the read path."""
    store = CaseStore(tmp_path / "case.db")
    with store.transaction():
        store.replace_hypotheses([_hyp(0)])
    store._conn.execute(  # pyright: ignore[reportPrivateUsage] — tampering fixture
        "UPDATE hypotheses SET supporting_event_ids = ?, "
        "suggested_next_steps = ? WHERE hyp_index = 0",
        ('{"a": 1}', "42"),
    )
    got = store.query_hypotheses()
    for h in got:
        assert isinstance(h.supporting_event_ids, list)
        assert all(isinstance(x, str) for x in h.supporting_event_ids)
        assert all(isinstance(x, str) for x in h.suggested_next_steps)
    store.close()


# --- PERF-03: perfmon held out of ranking, never out of citation ---------
#
# These four sit as a deliberate pair of pairs. The first two pin the
# exclusion seam; the last two pin the citation paths that must NOT inherit
# it. Read them together — half of PERF-03 is what is filtered, the other
# half is what must never be.


def _seed_mixed_sources(store: CaseStore) -> tuple[str, str]:
    """Insert one dsserrors and one dssperfmon event; return their ids."""
    diag = _ev(
        source_file="DSSErrors.log",
        offset=0,
        message="MCM denial on cube load",
        source="dsserrors",
    )
    sample = _ev(
        source_file="perf.csv",
        offset=100,
        line_start=2,
        message="Total MCM Denial = 3",
        source="dssperfmon",
    )
    with store.transaction():
        store.insert_events([diag, sample])
    return diag.event_id, sample.event_id


def test_iter_event_summaries_excludes_perfmon(tmp_path: Path) -> None:
    """The one ranking seam: perfmon samples never reach dedup (PERF-03)."""
    store = CaseStore(tmp_path / "case.db")
    try:
        diag_id, sample_id = _seed_mixed_sources(store)
        ids = [row[0] for row in store.iter_event_summaries()]
        assert diag_id in ids
        assert sample_id not in ids
    finally:
        store.close()


def test_iter_event_rows_unfiltered(tmp_path: Path) -> None:
    """`show events` must keep rendering perfmon rows (criterion 5)."""
    store = CaseStore(tmp_path / "case.db")
    try:
        diag_id, sample_id = _seed_mixed_sources(store)
        ids = [row[0] for row in store.iter_event_rows()]
        assert diag_id in ids
        assert sample_id in ids
    finally:
        store.close()


def test_get_events_returns_perfmon(tmp_path: Path) -> None:
    """Citation by identifier must resolve perfmon events (criterion 5)."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _, sample_id = _seed_mixed_sources(store)
        got = store.get_events_by_ids([sample_id])
        assert sample_id in got
        assert got[sample_id].source == "dssperfmon"
    finally:
        store.close()


def test_template_groups_exclude_perfmon(tmp_path: Path) -> None:
    """Criterion 4 at store level: template groups are byte-identical whether
    or not the case also holds perfmon events."""
    with_perf = CaseStore(tmp_path / "with.db")
    without_perf = CaseStore(tmp_path / "without.db")
    try:
        _seed_mixed_sources(with_perf)
        diag = _ev(
            source_file="DSSErrors.log",
            offset=0,
            message="MCM denial on cube load",
            source="dsserrors",
        )
        with without_perf.transaction():
            without_perf.insert_events([diag])

        for store in (with_perf, without_perf):
            dedup.rebuild_template_groups(store)

        assert with_perf.query_template_groups() == (
            without_perf.query_template_groups()
        )
        # Non-vacuity: the perfmon event really is stored, just not ranked.
        assert len(with_perf.query_events()) == 2
        assert len(without_perf.query_events()) == 1
    finally:
        with_perf.close()
        without_perf.close()


def test_triage_run_meta_roundtrip(tmp_path: Path) -> None:
    """Run-level triage status lives in meta (no separate table)."""
    store = CaseStore(tmp_path / "case.db")
    store.set_meta("triage_timeline_summary", "failures around 14:20 UTC")
    store.set_meta("triage_degraded", "0")
    store.set_meta("triage_model", "qwen2.5-coder")
    assert store.get_meta("triage_timeline_summary") == "failures around 14:20 UTC"
    assert store.get_meta("triage_degraded") == "0"
    assert store.get_meta("triage_model") == "qwen2.5-coder"
    store.close()
