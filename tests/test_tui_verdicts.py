"""Pilot tests for the S03 verdict capture modal (R003/R012/Q5/Q7).

The modal is proven standalone here — screens gain their ``v`` bindings in a
later task — by pushing :class:`VerdictModal` directly onto a real analysed
case (``tests/_report_fixtures.build_analysed_case``, zero sockets) and
driving the documented key flow: c/r/u chooses a state, tab reaches the
note field, enter commits, escape cancels.

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
* the rendered target label is sanitised (WR-01/T-04-01).
"""

import sqlite3
from functools import partial

import pytest
from _report_fixtures import TRIAGE_MODEL, build_analysed_case, open_case
from textual.widgets import Static

from sift.config import load_config
from sift.store import CaseStore, case_db_path
from sift.tui.app import SiftApp
from sift.tui.screens.hypotheses import HypothesesScreen
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
