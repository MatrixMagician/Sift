"""S02 perf gate (R008): TUI paging stays bounded at case sizes orders of
magnitude beyond the interaction fixtures.

Runs explicitly via ``uv run pytest -m perf tests/test_tui_perf.py`` — the
default suite excludes the ``perf`` marker (addopts, Pitfall 5). The case is
built directly through the public store API (the same ``insert_events`` seam
every adapter feeds): the M2 gate in tests/perf/test_perf_ingest.py already
proves the parse-and-ingest path at 100 MB, so this gate spends its budget on
what S02 added — the paging layer and the screens over it. 200 000 events is
~4.5 orders of magnitude above the five-event Pilot fixtures.

Budgets are ~10-100x the measured baselines (page 0 ≈ 36 ms including the
one-off ORDER BY sort, next page < 1 ms) so the gate catches a paging
regression — an accidental fetchall or a per-page re-sort — without flaking
on slow CI. The measured numbers print as acceptance evidence (``-s``).
"""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sift.models import Event, event_id
from sift.store import CaseStore, StoredHypothesis
from sift.tui.app import SiftApp
from sift.tui.data_access import DEFAULT_PAGE_SIZE, EventPager
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import TimelineScreen

pytestmark = pytest.mark.perf

EVENT_COUNT = 200_000
_BATCH = 20_000
_BASE = datetime(2026, 7, 16, 0, 0, 0, tzinfo=UTC)
_SEVERITIES = ("info", "warning", "error", "unknown")


def _event(i: int) -> Event:
    """Deterministic synthetic event ``i`` — no clock, no randomness."""
    message = f"worker {i % 128} completed job {i} in {i % 977} ms"
    source_file = f"synthetic/shard{i % 8}.log"
    return Event(
        event_id=event_id(source_file, i * 64),
        case_id="perfcase",
        ts=_BASE + timedelta(seconds=i),
        ts_confidence="exact",
        source="genericlog",
        source_file=source_file,
        line_start=i // 8 + 1,
        line_end=i // 8 + 1,
        severity=_SEVERITIES[i % 4],
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw=message,
    )


@pytest.fixture(scope="module")
def big_case_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 200k-event analysed case.db, built once for the whole module.

    Hypotheses and the ``triage_created_at`` marker are planted through the
    public store API (the _report_fixtures idiom) so the app lands on the
    hypothesis list exactly as it would for a real analysed case.
    """
    db_path = tmp_path_factory.mktemp("perfcase") / "case.db"
    store = CaseStore(db_path)
    try:
        cited = _event(0).event_id
        with store.transaction():
            for start in range(0, EVENT_COUNT, _BATCH):
                store.insert_events(
                    [_event(i) for i in range(start, start + _BATCH)]
                )
            store.replace_hypotheses(
                [
                    StoredHypothesis(
                        hyp_index=0,
                        title="Synthetic saturation hypothesis",
                        narrative=f"Load test narrative; see [evt:{cited}].",
                        confidence="high",
                        confidence_reasoning="Planted for the perf gate.",
                        supporting_event_ids=[cited],
                        contradicting_evidence=None,
                        suggested_next_steps=["None — synthetic case"],
                        citations_valid=True,
                    )
                ]
            )
            store.set_meta("triage_created_at", "2026-07-16T12:00:00+00:00")
    finally:
        store.close()
    return db_path


def test_pager_latency_bounded_on_200k_events(big_case_db: Path) -> None:
    """Page pulls stay bounded (R008): the first pull pays the one-off
    ORDER BY sort, every further page costs at most ``page_size`` streamed
    rows, and a revisited page never touches SQLite again."""
    store = CaseStore(big_case_db)
    try:
        pager = EventPager(store)

        start = time.perf_counter()
        first = pager.page(0)
        first_s = time.perf_counter() - start
        assert len(first) == DEFAULT_PAGE_SIZE
        assert first_s < 2.0, f"first page took {first_s:.3f}s (budget 2.0s)"

        worst = 0.0
        for index in range(1, 51):
            start = time.perf_counter()
            rows = pager.page(index)
            worst = max(worst, time.perf_counter() - start)
            assert len(rows) == DEFAULT_PAGE_SIZE
        assert worst < 0.1, (
            f"worst next-page pull took {worst * 1000:.1f}ms (budget 100ms)"
        )

        # 51 pages paged in exactly 51 pages of rows — never the whole table.
        assert pager.loaded_count == 51 * DEFAULT_PAGE_SIZE

        start = time.perf_counter()
        revisited = pager.page(0)
        revisit_s = time.perf_counter() - start
        assert revisited == first
        assert pager.loaded_count == 51 * DEFAULT_PAGE_SIZE  # no re-fetch
        assert revisit_s < 0.05, (
            f"page replay took {revisit_s * 1000:.1f}ms (budget 50ms)"
        )

        print(
            f"\n{EVENT_COUNT} events: page 0 {first_s * 1000:.1f}ms, "
            f"worst next page {worst * 1000:.2f}ms, "
            f"replay {revisit_s * 1000:.3f}ms"
        )
    finally:
        store.close()


async def test_tui_screens_stay_page_bounded_at_scale(
    big_case_db: Path,
) -> None:
    """Opening the app and the timeline on a 200k-event case stays fast and
    loads exactly one page; the cursor trigger pulls exactly one more."""
    store = CaseStore(big_case_db)
    try:
        app = SiftApp(store, "perfcase")
        start = time.perf_counter()
        async with app.run_test() as pilot:
            await pilot.pause()
            first_paint_s = time.perf_counter() - start
            assert isinstance(app.screen, HypothesesScreen)
            # The landing reads hypotheses + one meta key — neither scales
            # with the events table, so first paint stays bounded.
            assert first_paint_s < 3.0, (
                f"first paint took {first_paint_s:.2f}s (budget 3.0s)"
            )

            start = time.perf_counter()
            await pilot.press("t")
            await pilot.pause()
            open_s = time.perf_counter() - start
            screen = app.screen
            assert isinstance(screen, TimelineScreen)
            # Page 0 only — an accidental fetchall would show 200k rows.
            assert screen.table.row_count == DEFAULT_PAGE_SIZE
            assert open_s < 3.0, (
                f"timeline open took {open_s:.2f}s (budget 3.0s)"
            )

            start = time.perf_counter()
            screen.table.move_cursor(row=screen.table.row_count - 1)
            await pilot.pause()
            next_page_s = time.perf_counter() - start
            assert screen.table.row_count == 2 * DEFAULT_PAGE_SIZE
            assert next_page_s < 1.0, (
                f"cursor-driven page took {next_page_s:.2f}s (budget 1.0s)"
            )

            print(
                f"\nfirst paint {first_paint_s * 1000:.0f}ms, "
                f"timeline open {open_s * 1000:.0f}ms, "
                f"next page {next_page_s * 1000:.0f}ms"
            )
    finally:
        store.close()
