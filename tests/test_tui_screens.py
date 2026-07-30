"""Screen-level tests for the T03/T04 case-browsing screens.

Complements tests/test_tui_pilot.py (which drives whole-app flows): these
tests pin the screens' contracts — FLAGGED marking, cited-but-absent ids
shown rather than dropped, sanitisation of hostile DB bytes, mid-session
store failures becoming ErrorScreen, the hard-degraded empty state, the
cluster browser's member-template expansion (R002) and the timeline's
lazy paging (R008). All headless via Pilot against real analysed cases
(zero sockets; the autouse network guard stays active). R019: structure
assertions only, never rendered pixels.
"""

import dataclasses
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime

import pytest
from _report_fixtures import (
    MISSING_ID,
    REAL_ID,
    REAL_RAW,
    build_analysed_case,
    open_case,
)
from textual.widgets import Static

from sift.models import Event, event_id
from sift.store import Cluster, StoredHypothesis
from sift.tui.app import SiftApp
from sift.tui.screens.clusters import (
    MISSING_TEMPLATE_LABEL,
    ClusterDetailScreen,
    ClustersScreen,
)
from sift.tui.screens.error import ErrorScreen
from sift.tui.screens.evidence import (
    MISSING_EVENT_LABEL,
    EvidenceScreen,
    RawSourceScreen,
)
from sift.tui.screens.help_overlay import HelpOverlay
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import NO_EVENTS_MESSAGE, TimelineScreen


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


# ---------------------------------------------------------------------------
# Cluster browser (R002): keybinding, ranked list, member-template expansion
# ---------------------------------------------------------------------------


async def test_clusters_keybinding_opens_ranked_cluster_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'c' opens the cluster browser: count DESC, cluster_id ASC (STORE-04)."""
    case = build_analysed_case(monkeypatch, case="scrclus")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            table = app.screen.table
            # build_analysed_case clusters to 3: alpha (2 events), beta (2),
            # gamma singleton.
            assert table.row_count == 3
            first = [c.plain for c in table.get_row_at(0)]
            assert first[0] == "0"
            assert first[1] == "error"
            assert first[2] == "2"  # events in the cluster
            assert first[4] == "Memory pressure"  # the LLM label, not signature
    finally:
        store.close()


async def test_cluster_detail_expands_member_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enter on a cluster shows its member template groups (the expansion)."""
    case = build_analysed_case(monkeypatch, case="scrmemb")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            assert "Memory pressure" in _static_text(app, "cluster-title")
            summary = _static_text(app, "cluster-summary")
            assert "2 events" in summary
            assert "2 templates" in summary
            table = app.screen.table
            assert table.row_count == 2
            rows = [
                [c.plain for c in table.get_row_at(i)]
                for i in range(table.row_count)
            ]
            texts = {r[5] for r in rows}
            assert "alpha memory pressure warning" in texts
            assert "alpha memory watermark exceeded" in texts
            assert all(r[1] == "1" for r in rows)  # one event per template
    finally:
        store.close()


async def test_cluster_absent_template_id_shown_and_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tampered cluster: NULL label falls back to the signature, a repeated
    member id is deduped, and an id the store does not hold is shown as such
    (nothing disappears silently) with selection a no-op."""
    case = build_analysed_case(monkeypatch, case="scrtamp")
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_clusters(
                [
                    Cluster(
                        cluster_id=7,
                        label=None,
                        signature="tampered signature",
                        severity_max="error",
                        count=1,
                        template_ids=["f" * 16, "f" * 16],
                    )
                ]
            )
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            row = [c.plain for c in app.screen.table.get_row_at(0)]
            assert row[4] == "tampered signature"  # D-01 signature fallback
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            assert app.screen.table.row_count == 1  # duplicate id deduped
            member = [c.plain for c in app.screen.table.get_row_at(0)]
            assert MISSING_TEMPLATE_LABEL in member
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)  # inert
    finally:
        store.close()


async def test_hostile_cluster_label_sanitised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cluster labels are model text and signatures are log bytes (WR-01)."""
    case = build_analysed_case(monkeypatch, case="scrcevil")
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_clusters(
                [
                    Cluster(
                        cluster_id=0,
                        label="evil\x1b[2Jlabel",
                        signature="sig",
                        severity_max="error",
                        count=1,
                        template_ids=[],
                    )
                ]
            )
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            label = [c.plain for c in app.screen.table.get_row_at(0)][4]
            assert "\x1b" not in label
            assert "evil[2Jlabel" in label  # byte stripped, text kept
    finally:
        store.close()


async def test_zero_clusters_shows_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An analysed case with an empty clusters table says so on screen."""
    case = build_analysed_case(monkeypatch, case="scrcnone")
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_clusters([])
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            assert app.screen.table.row_count == 0
            message = _static_text(app, "clusters-empty")
            assert "No semantic clusters" in message
            assert "sift analyze" in message
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Event timeline (R002 + R008): keybinding, uncited/unknown events, paging
# ---------------------------------------------------------------------------


async def test_timeline_includes_uncited_and_unknown_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'t' opens the full timeline: uncited events and severity="unknown"
    events appear — iter_event_rows applies no ranking exclusions (R002)."""
    case = build_analysed_case(monkeypatch, case="scrtline")
    store = open_case(case)
    try:
        unknown = Event(
            event_id=event_id("unparsed.log", 0),
            case_id=case,
            ts=None,
            ts_confidence="missing",
            source="genericlog",
            source_file="unparsed.log",
            line_start=9,
            line_end=9,
            severity="unknown",
            component=None,
            thread=None,
            session=None,
            message="garbled region",
            attrs={},
            raw="garbled region",
        )
        with store.transaction():
            store.insert_events([unknown])
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            table = app.screen.table
            assert table.row_count == 6  # five corpus events + the unknown one
            rows = [
                [c.plain for c in table.get_row_at(i)]
                for i in range(table.row_count)
            ]
            # Only REAL_ID is ever cited; the gamma event appears regardless.
            assert "gamma unrelated disk anomaly" in {r[4] for r in rows}
            # ts=None sorts last (canonical order); unknown is not filtered.
            assert rows[5][2] == "unknown"
            assert rows[5][1] == "—"
            assert "6 events loaded" in _static_text(app, "timeline-status")
    finally:
        store.close()


async def test_timeline_pages_lazily_as_cursor_reaches_bottom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only page 0 loads on mount; each further page loads when the cursor
    reaches the last loaded row — never a fetchall (R008)."""
    case = build_analysed_case(monkeypatch, case="scrpage")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            screen = TimelineScreen(store, page_size=2)
            app.screen.push(screen)
            await pilot.pause()
            assert screen.table.row_count == 2  # page 0 only
            assert "scroll down for more" in _static_text(
                app, "timeline-status"
            )
            await pilot.press("down")  # cursor onto the last loaded row
            await pilot.pause()
            assert screen.table.row_count == 4
            await pilot.press("down", "down")
            await pilot.pause()
            assert screen.table.row_count == 5  # exhausted: whole corpus
            status = _static_text(app, "timeline-status")
            assert "5 events loaded" in status
            assert "scroll down" not in status
    finally:
        store.close()


async def test_timeline_select_opens_raw_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enter hydrates the single selected event and opens its raw source."""
    case = build_analysed_case(monkeypatch, case="scrtraw")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            await pilot.press("enter")  # first row is REAL_ID (case.log:1)
            await pilot.pause()
            assert isinstance(app.screen, RawSourceScreen)
            assert REAL_RAW in _static_text(app, "raw-text")
            assert "case.log:1" in _static_text(app, "raw-context")
            await pilot.press("escape")
            assert isinstance(app.screen, TimelineScreen)
    finally:
        store.close()


async def test_timeline_store_failure_shows_error_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locked database on the first page pull becomes a sanitised
    ErrorScreen (R012) — the pager's deferred cursor errors on the pull
    (MEM014), which the screen wraps in guarded()."""
    case = build_analysed_case(monkeypatch, case="scrtlock")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()

            def _locked(
                filters: Mapping[str, str | int] | None = None,
            ) -> Iterator[tuple[str, str | None, str, str, int, str]]:
                # A generator like the real method: raises on the first
                # pull, not at pager construction.
                raise sqlite3.OperationalError("database is locked")
                yield ("", None, "", "", 0, "")  # pragma: no cover

            monkeypatch.setattr(store, "iter_event_rows", _locked)
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, ErrorScreen)
            assert "database is locked" in app.screen.message
    finally:
        store.close()


async def test_timeline_with_no_events_shows_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty events table is stated on screen, never a blank table."""
    case = build_analysed_case(monkeypatch, case="scrtnone")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()

            def _empty(
                filters: Mapping[str, str | int] | None = None,
            ) -> Iterator[tuple[str, str | None, str, str, int, str]]:
                return iter(())

            monkeypatch.setattr(store, "iter_event_rows", _empty)
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            assert app.screen.table.row_count == 0
            assert NO_EVENTS_MESSAGE in _static_text(app, "timeline-status")
    finally:
        store.close()


async def test_help_overlay_lists_roam_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The '?' overlay stays truthful: the new c/t bindings appear (R013)."""
    case = build_analysed_case(monkeypatch, case="scrhelp2")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpOverlay)
            descriptions = {d for _, d in app.screen.entries}
            assert {"Clusters", "Timeline"} <= descriptions
    finally:
        store.close()
