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
from _report_fixtures import build_analysed_case, open_case
from textual.widgets import Static
from typer.testing import CliRunner

from sift.cli import app as cli_app
from sift.config import load_config
from sift.store import CaseStore, case_db_path
from sift.tui.app import OverviewScreen, SiftApp
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
from sift.tui.screens.help_overlay import HelpOverlay

runner = CliRunner()


def _static_text(app: SiftApp, widget_id: str) -> str:
    """The plain content of a Static on the current screen."""
    return str(app.screen.query_one(f"#{widget_id}", Static).content)


# ---------------------------------------------------------------------------
# Landing: analysed case → overview
# ---------------------------------------------------------------------------


async def test_open_analysed_case_lands_on_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch, case="tuidemo")
    store = open_case(case)
    try:
        app = SiftApp(store, case)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, OverviewScreen)
            summary = _static_text(app, "overview-summary")
            assert "Case: tuidemo" in summary
            # build_analysed_case plants 2 hypotheses over 3 real clusters.
            assert "Hypotheses: 2" in summary
            assert "Clusters: 3" in summary
            assert "Press ? for help" in summary
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
            assert isinstance(app.screen, OverviewScreen)
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
            assert isinstance(app.screen, OverviewScreen)
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
            assert isinstance(app.screen, OverviewScreen)
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
            assert isinstance(app.screen, OverviewScreen)
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
