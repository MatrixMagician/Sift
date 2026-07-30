"""Pilot headless interaction tests for the S02 TUI shell (R012/R013/R019).

CliRunner cannot drive Textual (no TTY), so the split is deliberate:

* The ``sift tui`` command's error paths that exit BEFORE ``App.run()``
  (missing case, invalid name, corrupt db) run through CliRunner like every
  other CLI test.
* Everything interactive — landing screens, help overlay, error screens,
  navigation, quit — runs through Textual's Pilot against a real analysed
  case built by ``tests/_report_fixtures.build_analysed_case`` (zero
  sockets; the autouse network guard stays active).

R019 excludes visual snapshot testing: these tests assert structure
(which screen is on top, what text a widget holds), never rendered pixels.
"""

import pytest
from _report_fixtures import REAL_RAW, build_analysed_case, open_case
from textual.widgets import Static
from typer.testing import CliRunner

from sift.cli import app as cli_app
from sift.config import load_config
from sift.store import CaseStore, case_db_path
from sift.tui.app import SiftApp
from sift.tui.screens.clusters import ClusterDetailScreen, ClustersScreen
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
from sift.tui.screens.evidence import EvidenceScreen, RawSourceScreen
from sift.tui.screens.help_overlay import HelpOverlay
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import TimelineScreen

runner = CliRunner()


def _static_text(app: SiftApp, widget_id: str) -> str:
    """The plain content of a Static on the current screen."""
    return str(app.screen.query_one(f"#{widget_id}", Static).content)


# ---------------------------------------------------------------------------
# Landing: analysed case → ranked hypothesis list (R001)
# ---------------------------------------------------------------------------


async def test_open_analysed_case_lands_on_hypothesis_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="tuidemo")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            table = app.screen.table
            # build_analysed_case plants 2 hypotheses, hyp_index-ordered.
            assert table.row_count == 2
            first = [c.plain for c in table.get_row_at(0)]
            assert first[0] == "0"
            assert first[1] == "high"
            assert "Memory pressure" in first[3]
    finally:
        store.close()


async def test_drill_down_hypothesis_to_evidence_to_raw_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full R001 review loop: list → evidence → raw source and back."""
    case = build_analysed_case(monkeypatch, case="tuidrill")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert "memory watermark" in _static_text(app, "evidence-narrative")
            assert "Confidence: high" in _static_text(app, "evidence-confidence")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, RawSourceScreen)
            assert REAL_RAW in _static_text(app, "raw-text")
            assert "case.log:1" in _static_text(app, "raw-context")
            await pilot.press("escape")
            assert isinstance(app.screen, EvidenceScreen)
            await pilot.press("escape")
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


async def test_escape_on_landing_screen_is_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Escape must never pop below the landing screen onto the blank default."""
    case = build_analysed_case(monkeypatch, case="tuiesc")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.is_running
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


async def test_quit_key_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    case = build_analysed_case(monkeypatch, case="tuiquit")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.press("q")
        assert not app.is_running
        assert app.return_code == 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Landing: not-analysed case → clear screen, not an error exit (R012)
# ---------------------------------------------------------------------------


async def test_not_analysed_case_opens_not_analysed_screen() -> None:
    db_path = case_db_path(load_config().data_dir, "fresh")
    store = CaseStore(db_path)  # migrated, zero events, no triage meta
    try:
        app = SiftApp(store, "fresh")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, NotAnalysedScreen)
            message = _static_text(app, "not-analysed-message")
            assert "no triage results" in message
            assert "sift analyze fresh" in message
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Error screens (R012): sanitised store failures, never a traceback
# ---------------------------------------------------------------------------


async def test_store_failure_at_mount_shows_error_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead connection on the very first read lands on ErrorScreen."""
    case = build_analysed_case(monkeypatch, case="tuierr")
    store = open_case(case)
    store.close()  # every later read raises sqlite3.ProgrammingError
    app = SiftApp(store, case)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ErrorScreen)
        assert app.screen.message  # a real message, not an empty banner


async def test_error_screen_escape_pops_back_to_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="tuipop")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ErrorScreen("mid-session store failure"))
            await pilot.pause()
            assert isinstance(app.screen, ErrorScreen)
            await pilot.press("escape")
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


def test_error_screen_sanitises_control_bytes() -> None:
    """Hostile db bytes must never drive the terminal (T-04-01)."""
    screen = ErrorScreen("bad\x1b[2Jmessage\x9b‮done")
    assert screen.message == "bad[2Jmessagedone"


def test_not_analysed_screen_sanitises_case_name() -> None:
    screen = NotAnalysedScreen("odd\x1bname")
    assert "\x1b" not in screen.case_name


# ---------------------------------------------------------------------------
# Help overlay (R013)
# ---------------------------------------------------------------------------


async def test_help_overlay_lists_active_bindings_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="tuihelp")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpOverlay)
            entries = app.screen.entries
            descriptions = {description for _, description in entries}
            assert {"Quit", "Back", "Help"} <= descriptions
            keys = {key for key, _ in entries}
            assert "?" in keys  # key_display honoured, not "question_mark"
            await pilot.press("escape")
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


async def test_help_key_toggles_and_never_stacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="tuitoggle")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpOverlay)
            # A second '?' closes the overlay (toggle), never stacks another.
            await pilot.press("question_mark")
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


async def test_help_overlay_available_on_not_analysed_screen() -> None:
    """The overlay is a shell-level concern every screen inherits (R013)."""
    db_path = case_db_path(load_config().data_dir, "freshhelp")
    store = CaseStore(db_path)
    try:
        app = SiftApp(store, "freshhelp")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, NotAnalysedScreen)
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpOverlay)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# CLI entry point: the paths that exit before App.run()
# ---------------------------------------------------------------------------


def test_tui_command_registered_with_help() -> None:
    result = runner.invoke(cli_app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "interactive terminal browser" in result.output


def test_tui_missing_case_exits_one() -> None:
    result = runner.invoke(cli_app, ["tui", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert "Traceback" not in result.output


def test_tui_invalid_case_name_exits_one() -> None:
    result = runner.invoke(cli_app, ["tui", "../evil"])
    assert result.exit_code == 1
    assert "Error" in result.output
    assert "Traceback" not in result.output


def test_tui_corrupt_case_exits_one_sanitised() -> None:
    db_path = case_db_path(load_config().data_dir, "corrupt")
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"\x00not a sqlite database\x1b[2J")
    result = runner.invoke(cli_app, ["tui", "corrupt"])
    assert result.exit_code == 1
    assert "cannot open case" in result.output
    assert "\x1b" not in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# Navigation integration (T05): the full roam across every screen
# ---------------------------------------------------------------------------


async def test_full_roam_across_every_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One session roams the whole case: the R001 drill-down chain, both
    R002 roam surfaces, cluster expansion, and the escape trail home."""
    case = build_analysed_case(monkeypatch, case="tuiroam")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, RawSourceScreen)
            await pilot.press("t")  # roam out of the drill-down
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            await pilot.press("c")  # sibling switch, not a push
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            # Escape retraces the trail exactly, ending on the landing screen.
            for expected in (
                ClustersScreen,
                RawSourceScreen,
                EvidenceScreen,
                HypothesesScreen,
            ):
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, expected)
            await pilot.press("escape")  # landing: a no-op, never blank
            assert isinstance(app.screen, HypothesesScreen)
            assert app.is_running
    finally:
        store.close()


async def test_roam_toggle_keeps_stack_flat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alternating c/t hops between the sibling roam surfaces in place —
    the screen stack must not grow — and a repeated key is a no-op."""
    case = build_analysed_case(monkeypatch, case="tuiflat")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            depth = len(app.screen_stack)
            hops = [
                ("t", TimelineScreen),
                ("t", TimelineScreen),  # repeat: no-op, no restacking
                ("c", ClustersScreen),
                ("t", TimelineScreen),
            ]
            for key, expected in hops:
                await pilot.press(key)
                await pilot.pause()
                assert isinstance(app.screen, expected)
                assert len(app.screen_stack) == depth
            # One escape lands back where roaming started.
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()
