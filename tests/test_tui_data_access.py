"""EventPager tests: lazy paging over a real CaseStore, never fetchall (R008)."""

import sqlite3
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sift.models import Event, event_id
from sift.store import CaseStore
from sift.tui.data_access import EventPager, EventRow

_BASE_TS = datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC)


def _ev(
    offset: int,
    ts: datetime | None = _BASE_TS,
    severity: str = "info",
    source_file: str = "app.log",
    message: str = "msg",
) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id="demo",
        ts=ts,
        ts_confidence="exact" if ts is not None else "missing",
        source="genericlog",
        source_file=source_file,
        line_start=offset + 1,
        line_end=offset + 1,
        severity=severity,
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw="raw",
    )


def _store_with(tmp_path: Path, events: list[Event]) -> CaseStore:
    store = CaseStore(tmp_path / "case.db")
    assert store.insert_events(events) == len(events)
    return store


def _sequential(n: int) -> list[Event]:
    """n events with strictly increasing timestamps, message = its index."""
    return [
        _ev(offset=i, ts=_BASE_TS + timedelta(seconds=i), message=f"m{i}")
        for i in range(n)
    ]


def _count_cursor_pulls(
    monkeypatch: pytest.MonkeyPatch, store: CaseStore
) -> dict[str, int]:
    """Wrap store.iter_event_rows so every row pulled from SQLite is counted."""
    pulled = {"rows": 0}
    real = store.iter_event_rows

    def counting(
        filters: Mapping[str, str | int] | None = None,
    ) -> Iterator[tuple[str, str | None, str, str, int, str]]:
        for row in real(filters):
            pulled["rows"] += 1
            yield row

    monkeypatch.setattr(store, "iter_event_rows", counting)
    return pulled


def test_pages_in_canonical_order(tmp_path: Path) -> None:
    # Inserted reversed; the store's ORDER BY must define page order.
    store = _store_with(tmp_path, list(reversed(_sequential(25))))
    pager = EventPager(store, page_size=10)
    assert [r.message for r in pager.page(0)] == [f"m{i}" for i in range(10)]
    assert [r.message for r in pager.page(1)] == [f"m{i}" for i in range(10, 20)]


def test_partial_last_page_then_empty_and_exhausted(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _sequential(25))
    pager = EventPager(store, page_size=10)
    assert len(pager.page(2)) == 5
    assert pager.exhausted
    assert pager.page(3) == []
    assert pager.page(99) == []


def test_page_pulls_only_one_page_from_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store_with(tmp_path, _sequential(50))
    pulled = _count_cursor_pulls(monkeypatch, store)
    pager = EventPager(store, page_size=10)
    assert pulled["rows"] == 0  # constructing the pager streams nothing
    pager.page(0)
    assert pulled["rows"] == 10  # a 50-event case: page 0 hydrates 10 rows
    pager.page(1)
    assert pulled["rows"] == 20  # next page resumes the SAME cursor


def test_revisited_page_replays_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store_with(tmp_path, _sequential(30))
    pulled = _count_cursor_pulls(monkeypatch, store)
    pager = EventPager(store, page_size=10)
    first = pager.page(0)
    pager.page(1)
    assert pulled["rows"] == 20
    assert pager.page(0) == first  # no further SQLite work
    assert pulled["rows"] == 20


def test_jumping_ahead_fills_intermediate_pages(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _sequential(50))
    pager = EventPager(store, page_size=10)
    page3 = pager.page(3)
    assert [r.message for r in page3] == [f"m{i}" for i in range(30, 40)]
    assert pager.loaded_count == 40
    assert not pager.exhausted  # never pulled past the requested page


def test_row_field_mapping(tmp_path: Path) -> None:
    store = _store_with(
        tmp_path, [_ev(offset=7, severity="error", message="boom")]
    )
    (row,) = EventPager(store).page(0)
    assert isinstance(row, EventRow)
    assert row.event_id == event_id("app.log", 7)
    assert row.ts == _BASE_TS.isoformat()  # stored ISO 8601 string, not datetime
    assert row.severity == "error"
    assert row.source_file == "app.log"
    assert row.line_start == 8
    assert row.message == "boom"


def test_timeline_includes_unknown_severity_and_missing_ts(
    tmp_path: Path,
) -> None:
    # R002: nothing disappears — unparseable regions must reach the timeline.
    events = [
        _ev(offset=0, message="dated"),
        _ev(offset=1, ts=None, severity="unknown", message="undated"),
    ]
    store = _store_with(tmp_path, events)
    rows = EventPager(store).page(0)
    assert [r.message for r in rows] == ["dated", "undated"]  # NULL ts sorts last
    assert rows[1].ts is None
    assert rows[1].severity == "unknown"


def test_filters_scope_rows(tmp_path: Path) -> None:
    events = _sequential(6) + [
        _ev(offset=100, severity="error", message="bad")
    ]
    store = _store_with(tmp_path, events)
    rows = EventPager(store, filters={"severity": "error"}).page(0)
    assert [r.message for r in rows] == ["bad"]


def test_empty_case_first_page_empty(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    pager = EventPager(store)
    assert pager.page(0) == []
    assert pager.exhausted
    assert pager.loaded_count == 0


def test_unknown_filter_key_raises_on_first_page(tmp_path: Path) -> None:
    # The store's allowlist check lives in the generator body, so it fires
    # on the first row pull — construction stays zero-cost by design.
    store = _store_with(tmp_path, _sequential(3))
    pager = EventPager(store, filters={"colour": "red"})
    with pytest.raises(ValueError, match="unknown filter key"):
        pager.page(0)


def test_invalid_page_size_rejected(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _sequential(3))
    with pytest.raises(ValueError, match="page_size"):
        EventPager(store, page_size=0)


def test_negative_page_index_rejected(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _sequential(3))
    with pytest.raises(ValueError, match="page index"):
        EventPager(store).page(-1)


def test_store_failure_mid_paging_bubbles(tmp_path: Path) -> None:
    # Q5: the pager adds NO error handling — a dead connection mid-session
    # must surface to the app shell's error screens, never be swallowed.
    store = _store_with(tmp_path, _sequential(30))
    pager = EventPager(store, page_size=10)
    assert len(pager.page(0)) == 10
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        pager.page(1)
