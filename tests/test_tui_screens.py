"""Screen-level tests for the T03 hypothesis/evidence/raw-source screens.

Complements tests/test_tui_pilot.py (which drives whole-app flows): these
tests pin the screens' contracts — FLAGGED marking, cited-but-absent ids
shown rather than dropped, sanitisation of hostile DB bytes, mid-session
store failures becoming ErrorScreen, and the hard-degraded empty state.
All headless via Pilot against real analysed cases (zero sockets; the
autouse network guard stays active). R019: structure assertions only,
never rendered pixels.
"""

import dataclasses
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from _report_fixtures import (
    MISSING_ID,
    REAL_ID,
    build_analysed_case,
    open_case,
)
from textual.widgets import Static

from sift.models import Event
from sift.store import StoredHypothesis
from sift.tui.app import SiftApp
from sift.tui.screens.error import ErrorScreen
from sift.tui.screens.evidence import (
    MISSING_EVENT_LABEL,
    EvidenceScreen,
    RawSourceScreen,
)
from sift.tui.screens.hypotheses import HypothesesScreen


def _static_text(app: SiftApp, widget_id: str) -> str:
    return str(app.screen.query_one(f"#{widget_id}", Static).content)


def _hostile_hypothesis(title: str, narrative: str) -> StoredHypothesis:
    return StoredHypothesis(
        hyp_index=0,
        title=title,
        narrative=narrative,
        confidence="low",
        confidence_reasoning="planted",
        supporting_event_ids=[REAL_ID],
        contradicting_evidence=None,
        suggested_next_steps=[],
        citations_valid=True,
    )


# ---------------------------------------------------------------------------
# Hypothesis list: FLAGGED marking and the hard-degraded empty state
# ---------------------------------------------------------------------------


async def test_flagged_hypothesis_marked_in_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """citations_valid=0 must be visible at the ranking level (T-04-02)."""
    case = build_analysed_case(monkeypatch, case="scrflag", degraded=True)
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            table = app.screen.table
            assert [c.plain for c in table.get_row_at(0)][2] == "ok"
            assert [c.plain for c in table.get_row_at(1)][2] == "FLAGGED"
    finally:
        store.close()


async def test_zero_hypotheses_shows_degraded_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hard-degraded run (analysed, zero rows) says so — never an empty
    table masquerading as 'no findings' (nothing disappears silently)."""
    case = build_analysed_case(monkeypatch, case="scrempty")
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_hypotheses([])
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            assert app.screen.table.row_count == 0
            message = _static_text(app, "hypotheses-empty")
            assert "No schema-valid hypotheses" in message
            assert "sift report" in message
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Evidence screen: cited events, absent ids, hypothesis detail
# ---------------------------------------------------------------------------


async def test_evidence_screen_shows_contradicting_and_next_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="scrdetail")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # hyp 1: the SMTP hypothesis
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert "Confidence: low" in _static_text(app, "evidence-confidence")
            assert "Delivery resumed" in _static_text(
                app, "evidence-contradicting"
            )
            assert "Confirm queue drained" in _static_text(app, "evidence-steps")
            # The one cited event row carries provenance for drill-down.
            row = [c.plain for c in app.screen.table.get_row_at(0)]
            assert row[0] == REAL_ID
            assert row[3] == "case.log:1"
    finally:
        store.close()


async def test_missing_cited_event_shown_and_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cited-but-absent id is shown as such (Pitfall 2) and selecting it
    does nothing — there is no stored raw source to open."""
    case = build_analysed_case(monkeypatch, case="scrmiss", degraded=True)
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # hyp 1 cites only MISSING_ID
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert "FLAGGED" in _static_text(app, "evidence-confidence")
            row = [c.plain for c in app.screen.table.get_row_at(0)]
            assert row[0] == MISSING_ID
            assert MISSING_EVENT_LABEL in row
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)  # inert, no crash
    finally:
        store.close()


async def test_duplicate_citation_ids_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tampered case.db can repeat a cited id; the table must not crash
    on a duplicate row key and shows the citation once."""
    case = build_analysed_case(monkeypatch, case="scrdupe")
    store = open_case(case)
    try:
        hyp = _hostile_hypothesis("dupe", "dupe narrative")
        hyp = dataclasses.replace(
            hyp, supporting_event_ids=[REAL_ID, REAL_ID]
        )
        with store.transaction():
            store.replace_hypotheses([hyp])
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert app.screen.table.row_count == 1
    finally:
        store.close()


async def test_store_failure_on_evidence_read_shows_error_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locked/busy database mid-drill-down becomes a sanitised ErrorScreen
    (R012), never a traceback swallowed by Textual's event loop."""
    case = build_analysed_case(monkeypatch, case="scrlock")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()

            def _locked(ids: Sequence[str]) -> dict[str, Event]:
                raise sqlite3.OperationalError("database is locked")

            monkeypatch.setattr(store, "get_events_by_ids", _locked)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ErrorScreen)
            assert "database is locked" in app.screen.message
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Sanitisation (WR-01/T-04-01): hostile DB bytes never reach the terminal
# ---------------------------------------------------------------------------


async def test_hostile_hypothesis_bytes_sanitised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="screvil")
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_hypotheses(
                [
                    _hostile_hypothesis(
                        "evil\x1b[2Jtitle",
                        "evil\x9bnarrative‮done",
                    )
                ]
            )
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            title = [c.plain for c in app.screen.table.get_row_at(0)][3]
            assert "\x1b" not in title
            assert "evil[2Jtitle" in title  # byte stripped, text kept
            await pilot.press("enter")
            await pilot.pause()
            narrative = _static_text(app, "evidence-narrative")
            assert "\x9b" not in narrative
            assert "‮" not in narrative
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Raw source screen: provenance header and verbatim raw
# ---------------------------------------------------------------------------


async def test_raw_source_screen_shows_line_range_and_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="scrraw")
    store = open_case(case)
    try:
        multiline = Event(
            event_id="feedfacefeedface",
            case_id=case,
            ts=datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC),
            ts_confidence="exact",
            source="genericlog",
            source_file="threads/dump.txt",
            line_start=3,
            line_end=7,
            severity="unknown",
            component=None,
            thread=None,
            session=None,
            message="stack trace",
            attrs={},
            raw="line one\nline two\nline three",
        )
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            app.screen.push(RawSourceScreen(multiline))
            await pilot.pause()
            assert isinstance(app.screen, RawSourceScreen)
            context = _static_text(app, "raw-context")
            assert "threads/dump.txt:3-7" in context
            assert "feedfacefeedface" in context
            assert "unknown" in context
            raw = _static_text(app, "raw-text")
            assert "line one\nline two\nline three" in raw
    finally:
        store.close()
