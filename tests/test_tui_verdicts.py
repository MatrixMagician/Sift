"""Pilot tests for S03 verdict capture (R003/R012/R014/Q5/Q7).

The modal is proven standalone first — by pushing :class:`VerdictModal`
directly onto a real analysed case
(``tests/_report_fixtures.build_analysed_case``, zero sockets) and driving
the documented key flow: c/r/u chooses a state, tab reaches the note
field, enter commits, escape cancels. The screen-wiring section then
proves the per-screen ``v`` bindings, the commit-gated Verdict badges, and
the landing screen's review-progress line.

What these tests pin down:

* every commit lands exactly one row through ``verdicts.record_validation``
  — the context snapshot fields (``hyp_index``/``cluster_id``/
  ``template_id`` plus evidence/provenance) prove the service built the
  row, not a raw ``store.record_verdict`` call;
* the dismissal callback receives the :class:`RecordedVerdict` matching the
  stored row (the R012 commit gate's input);
* cancel and no-state-selected write nothing (Q7);
* a genuinely locked case.db (BEGIN EXCLUSIVE on a second connection, per
  the established locked-DB idiom) surfaces R012's exact "case locked by
  another process" wording inline and writes nothing (Q5);
* a vanished target (case re-analysed externally) surfaces a sanitised
  inline message without crashing (Q5);
* the rendered target label is sanitised (WR-01/T-04-01);
* '?' declares "Record verdict" on exactly the four capture screens and
  never on Timeline/RawSource, whose v key is inert (R013, Q7);
* no module under ``sift.tui`` names the raw ``record_verdict`` store API
  — ``verdicts.record_validation`` is the only TUI write path (MEM008).
"""

import sqlite3
from functools import partial
from pathlib import Path

import pytest
from _report_fixtures import TRIAGE_MODEL, build_analysed_case, open_case
from textual.widgets import Static

import sift.tui
from sift.config import load_config
from sift.store import CaseStore, Cluster, case_db_path
from sift.tui.app import SiftApp
from sift.tui.screens.clusters import ClusterDetailScreen, ClustersScreen
from sift.tui.screens.evidence import EvidenceScreen, RawSourceScreen
from sift.tui.screens.help_overlay import HelpOverlay
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import TimelineScreen
from sift.tui.screens.verdict_modal import VerdictModal
from sift.verdicts import RecordedVerdict, TargetSpec


def _push_modal(
    app: SiftApp,
    store: CaseStore,
    target: TargetSpec,
    label: str,
    results: list[RecordedVerdict | None],
) -> VerdictModal:
    modal = VerdictModal(store, target, label)
    app.push_screen(modal, results.append)
    return modal


def _message(app: SiftApp) -> str:
    return str(app.screen.query_one("#verdict-message", Static).content)


def _static(app: SiftApp, widget_id: str) -> str:
    return str(app.screen.query_one(f"#{widget_id}", Static).content)


# ---------------------------------------------------------------------------
# Happy paths: one committed row per level, via record_validation only
# ---------------------------------------------------------------------------


async def test_commit_confirmed_hypothesis_with_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="vmodhyp")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("hypothesis", "0"), "Memory pressure", results
            )
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("c")  # choose confirmed
            await pilot.press("tab")  # focus the note field
            await pilot.press(*"plausible")
            await pilot.press("enter")  # commits from the note field too
            await pilot.pause()
            # Modal dismissed back to the underlying screen.
            assert isinstance(app.screen, HypothesesScreen)
        rows = store.list_verdicts()
        assert len(rows) == 1
        row = rows[0]
        assert row.target_type == "hypothesis"
        assert row.target_id == "0"
        assert row.verdict == "confirmed"
        assert row.note == "plausible"
        # Snapshot fields prove the write went through record_validation:
        # a raw store.record_verdict call would carry no built context.
        assert row.context["hyp_index"] == 0
        assert row.context["evidence_templates"]
        assert row.provenance["model"] == TRIAGE_MODEL
        # The dismissal callback (the R012 commit gate) got the same row.
        assert len(results) == 1
        recorded = results[0]
        assert recorded is not None
        assert recorded.verdict_id == row.verdict_id
        assert recorded.target_type == "hypothesis"
        assert recorded.target_id == "0"
        assert recorded.verdict == "confirmed"
    finally:
        store.close()


async def test_commit_rejected_cluster_without_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="vmodclu")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        cluster_id = str(store.query_clusters()[0].cluster_id)
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("cluster", cluster_id), "a cluster", results
            )
            await pilot.pause()
            await pilot.press("r")  # choose rejected
            await pilot.press("enter")  # commit via the screen binding
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
        rows = store.list_verdicts()
        assert len(rows) == 1
        row = rows[0]
        assert row.target_type == "cluster"
        assert row.target_id == cluster_id
        assert row.verdict == "rejected"
        assert row.note == ""
        assert row.context["cluster_id"] == int(cluster_id)
        assert "templates" in row.context
        assert results and results[0] is not None
        assert results[0].verdict_id == row.verdict_id
    finally:
        store.close()


async def test_commit_uncertain_template(monkeypatch: pytest.MonkeyPatch) -> None:
    case = build_analysed_case(monkeypatch, case="vmodtpl")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        template_id = store.query_template_groups()[0].template_id
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("template", template_id), "a template", results
            )
            await pilot.pause()
            await pilot.press("u")  # choose uncertain
            await pilot.press("enter")
            await pilot.pause()
        rows = store.list_verdicts()
        assert len(rows) == 1
        row = rows[0]
        assert row.target_type == "template"
        assert row.target_id == template_id
        assert row.verdict == "uncertain"
        assert row.context["template_id"] == template_id
        assert results and results[0] is not None
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Q7 negative paths: cancel and no-state-selected write nothing
# ---------------------------------------------------------------------------


async def test_cancel_writes_nothing_and_dismisses_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="vmodcan")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("hypothesis", "0"), "Memory pressure", results
            )
            await pilot.pause()
            await pilot.press("c")  # even with a state chosen...
            await pilot.press("escape")  # ...escape commits nothing
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
        assert store.list_verdicts() == []
        assert results == [None]
    finally:
        store.close()


async def test_commit_without_state_shows_message_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="vmodnost")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("hypothesis", "0"), "Memory pressure", results
            )
            await pilot.pause()
            await pilot.press("enter")  # no state chosen — never a default
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)  # still open
            assert "Choose a verdict state" in _message(app)
            # Choosing a state clears the inline message.
            await pilot.press("r")
            assert _message(app) == ""
            await pilot.press("escape")
            await pilot.pause()
        assert store.list_verdicts() == []
        assert results == [None]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Q5 failure paths: locked case.db and vanished target
# ---------------------------------------------------------------------------


async def test_locked_db_shows_r012_wording_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A GENUINELY locked database: a second connection holds an exclusive
    # write lock while the modal commits. The store under test is entirely
    # real; the only test-speed concession is a short busy timeout, patched
    # BEFORE the store's connection is opened so it takes effect.
    case = build_analysed_case(monkeypatch, case="vmodlock")
    db_path = case_db_path(load_config().data_dir, case)
    monkeypatch.setattr(
        "sift.store.sqlite3.connect", partial(sqlite3.connect, timeout=0.2)
    )
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    lock = sqlite3.connect(db_path)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("hypothesis", "0"), "Memory pressure", results
            )
            await pilot.pause()
            await pilot.press("c")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)  # still open, no crash
            assert "case locked by another process" in _message(app)
            await pilot.press("escape")
            await pilot.pause()
    finally:
        lock.rollback()
        lock.close()
    try:
        assert store.list_verdicts() == []
        assert results == [None]
    finally:
        store.close()


async def test_vanished_target_shows_sanitised_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The case was re-analysed externally mid-session: the hypothesis index
    # no longer exists. UnknownTargetError is NOT a sqlite3.Error, so the
    # modal must handle it itself — inline message, no crash, no row.
    case = build_analysed_case(monkeypatch, case="vmodgone")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app, store, TargetSpec("hypothesis", "99"), "long gone", results
            )
            await pilot.pause()
            await pilot.press("u")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            assert "no hypothesis 99" in _message(app)
            await pilot.press("escape")
            await pilot.pause()
        assert store.list_verdicts() == []
        assert results == [None]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# WR-01: the target label carries DB/model bytes — sanitised, markup-inert
# ---------------------------------------------------------------------------


async def test_target_label_is_sanitised(monkeypatch: pytest.MonkeyPatch) -> None:
    case = build_analysed_case(monkeypatch, case="vmodsan")
    store = open_case(case)
    results: list[RecordedVerdict | None] = []
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            _push_modal(
                app,
                store,
                TargetSpec("hypothesis", "0"),
                "bad\x1b[2Jlabel\x9b‮done",
                results,
            )
            await pilot.pause()
            shown = str(app.screen.query_one("#verdict-target", Static).content)
            assert "\x1b" not in shown
            assert "\x9b" not in shown
            assert "‮" not in shown
            assert "bad[2Jlabeldone" in shown
            await pilot.press("escape")
            await pilot.pause()
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Screen wiring (T03): v bindings, commit-gated badges, progress counts
# ---------------------------------------------------------------------------


async def test_v_on_hypotheses_row_commits_and_gates_badge_on_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v on the landing screen's highlighted row captures a hypothesis
    verdict; the Verdict badge and the R014 progress line repaint only
    after the dismissal callback receives the RecordedVerdict."""
    case = build_analysed_case(monkeypatch, case="vwirehyp")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            # build_analysed_case plants 2 hypotheses; nothing ruled yet.
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 0/2 hypotheses"
            )
            assert [c.plain for c in app.screen.table.get_row_at(0)][4] == ""
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("c")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            row = [c.plain for c in app.screen.table.get_row_at(0)]
            assert row[4] == "confirmed"
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 1/2 hypotheses"
            )
        rows = store.list_verdicts()
        assert len(rows) == 1
        assert rows[0].target_type == "hypothesis"
        assert rows[0].target_id == "0"
        assert rows[0].verdict == "confirmed"
        # The context snapshot proves the write went through
        # record_validation, not a raw store call (MEM008).
        assert rows[0].context["hyp_index"] == 0
    finally:
        store.close()


async def test_v_cancel_on_hypotheses_paints_no_badge_or_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel dismisses with None: zero rows, blank badge, 0/2 progress —
    the commit gate never fires (R012, Q7)."""
    case = build_analysed_case(monkeypatch, case="vwirecan")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("r")  # even with a state chosen...
            await pilot.press("escape")  # ...cancel paints nothing
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            assert [c.plain for c in app.screen.table.get_row_at(0)][4] == ""
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 0/2 hypotheses"
            )
        assert store.list_verdicts() == []
    finally:
        store.close()


async def test_v_on_evidence_screen_rules_its_own_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v on the evidence screen targets the hypothesis being viewed; its
    verdict line paints from the callback, and returning to the landing
    screen repaints badge + progress from the DB re-read on resume."""
    case = build_analysed_case(monkeypatch, case="vwireevi")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")  # drill into hypothesis 0
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert _static(app, "evidence-verdict") == ""
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("r")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert _static(app, "evidence-verdict") == "Verdict: rejected"
            await pilot.press("escape")  # back to the landing screen
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            assert (
                [c.plain for c in app.screen.table.get_row_at(0)][4]
                == "rejected"
            )
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 1/2 hypotheses"
            )
        rows = store.list_verdicts()
        assert len(rows) == 1
        assert rows[0].target_type == "hypothesis"
        assert rows[0].target_id == "0"
        assert rows[0].verdict == "rejected"
    finally:
        store.close()


async def test_v_on_clusters_row_commits_cluster_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="vwireclu")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            assert [c.plain for c in app.screen.table.get_row_at(0)][5] == ""
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("c")  # inside the modal: confirmed, not roam
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            assert (
                [c.plain for c in app.screen.table.get_row_at(0)][5]
                == "confirmed"
            )
        rows = store.list_verdicts()
        assert len(rows) == 1
        assert rows[0].target_type == "cluster"
        assert rows[0].target_id == "0"
        assert rows[0].context["cluster_id"] == 0
    finally:
        store.close()


async def test_v_on_cluster_detail_member_commits_template_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="vwiretpl")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("enter")  # expand the top cluster's members
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            first = [c.plain for c in app.screen.table.get_row_at(0)]
            template_id = first[0]
            assert first[6] == ""
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("u")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            assert (
                [c.plain for c in app.screen.table.get_row_at(0)][6]
                == "uncertain"
            )
        rows = store.list_verdicts()
        assert len(rows) == 1
        assert rows[0].target_type == "template"
        assert rows[0].target_id == template_id
        assert rows[0].context["template_id"] == template_id
    finally:
        store.close()


async def test_v_on_empty_hypotheses_table_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hard-degraded case (zero hypotheses): v opens nothing and writes
    nothing — there is no row to rule on (Q7)."""
    case = build_analysed_case(monkeypatch, case="vwirenone")
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_hypotheses([])
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)  # no modal
            # The progress line still reports the other levels (R014).
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 0/0 hypotheses"
            )
        assert store.list_verdicts() == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# T04 — help-overlay truthfulness (R013): '?' declares "Record verdict" on
# exactly the screens whose v binding captures, and nowhere else
# ---------------------------------------------------------------------------


def _help_descriptions(app: SiftApp) -> set[str]:
    """The binding descriptions the open HelpOverlay is showing."""
    screen = app.screen
    assert isinstance(screen, HelpOverlay)
    return {description for _, description in screen.entries}


async def test_help_lists_record_verdict_on_all_four_capture_screens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'?' snapshots the active bindings, so every screen that binds v
    declares "Record verdict" with zero extra work (R013)."""
    case = build_analysed_case(monkeypatch, case="vhelp4")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            assert "Record verdict" in _help_descriptions(app)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("enter")  # drill into hypothesis 0
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            assert "Record verdict" in _help_descriptions(app)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            assert "Record verdict" in _help_descriptions(app)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("enter")  # expand the top cluster's members
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            assert "Record verdict" in _help_descriptions(app)
        assert store.list_verdicts() == []
    finally:
        store.close()


async def test_help_omits_record_verdict_on_timeline_and_raw_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeline and RawSource bind no v, so '?' must not advertise capture
    there — the overlay stays truthful per screen (R013)."""
    case = build_analysed_case(monkeypatch, case="vhelpnot")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            descriptions = _help_descriptions(app)
            assert "Record verdict" not in descriptions
            assert "Help" in descriptions  # the overlay itself rendered
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")  # back to the landing screen
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("enter")  # into the evidence screen
            await pilot.pause()
            await pilot.press("enter")  # open the first citation's raw
            await pilot.pause()
            assert isinstance(app.screen, RawSourceScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            descriptions = _help_descriptions(app)
            assert "Record verdict" not in descriptions
            assert "Help" in descriptions
    finally:
        store.close()


# ---------------------------------------------------------------------------
# T04 — Q7 negative paths: verdict-inert surfaces open nothing, write nothing
# ---------------------------------------------------------------------------


async def test_v_on_timeline_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    """v on the timeline is a no-op: no modal opens and nothing is written
    — events are not a verdict level (Q7)."""
    case = build_analysed_case(monkeypatch, case="vinertt")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)  # no modal
        assert store.list_verdicts() == []
    finally:
        store.close()


async def test_v_on_missing_template_row_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member row whose template_id the store does not hold is
    verdict-inert: there is nothing in this case to rule on (Q7)."""
    case = build_analysed_case(monkeypatch, case="vinertm")
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
                        template_ids=["f" * 16],
                    )
                ]
            )
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)  # no modal
        assert store.list_verdicts() == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# T04 — MEM008 structural proof: record_validation is the only write path
# ---------------------------------------------------------------------------


def test_tui_never_names_the_raw_store_write_api() -> None:
    """No module under sift.tui may even name ``record_verdict``: every TUI
    verdict write goes through verdicts.record_validation, which owns the
    context snapshot and provenance the report layer relies on (MEM008)."""
    tui_file = sift.tui.__file__
    assert tui_file is not None
    offenders = [
        path.name
        for path in sorted(Path(tui_file).parent.rglob("*.py"))
        if "record_verdict" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
