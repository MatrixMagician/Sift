"""Pilot tests for the S04 in-TUI pipeline actions (R006/R012).

The analyse action runs the shared ``sift.cli.run_analyze`` body in a
Textual thread worker against a fresh per-worker ``CaseStore``; these tests
drive it headlessly through the same fake-server kit the CLI suites use
(``tests/_report_fixtures.py``: ``_seed_case`` builds an ingested,
not-analysed case; ``_patch_http`` injects an ``httpx.MockTransport`` at
the ``sift.cli._make_http_client`` seam, so the autouse zero-network guard
stays active). Assertions follow the S02 discipline: plain attributes
(``pipeline_status``/``pipeline_state``/``pipeline_log``), which screen is
on top, never rendered pixels.
"""

from pathlib import Path

import httpx
import pytest

# The seeding/patching kit is module-private by convention but IS the shared
# surface (research: the S04 Pilot recipe); _report_fixtures itself is frozen
# by the R009 byte-identical gate, so no public re-export can be added there.
from _report_fixtures import (
    _handler,  # pyright: ignore[reportPrivateUsage]
    _patch_http,  # pyright: ignore[reportPrivateUsage]
    _seed_case,  # pyright: ignore[reportPrivateUsage]
    build_analysed_case,
)

from sift.config import load_config
from sift.store import CaseStore, case_db_path
from sift.tui.app import SiftApp
from sift.tui.screens.clusters import ClustersScreen
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
from sift.tui.screens.help_overlay import HelpOverlay
from sift.tui.screens.hypotheses import HypothesesScreen


def _open_store(case: str) -> CaseStore:
    return CaseStore(case_db_path(load_config().data_dir, case))


async def _wait_workers(app: SiftApp) -> None:
    """Await every worker; wrapped once so the partially-unknown Textual
    signature needs a single pyright ignore."""
    await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Happy path: a → worker → hypotheses landing (the acceptance-demo route)
# ---------------------------------------------------------------------------


async def test_analyse_key_runs_worker_and_lands_on_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("tuipipe")
    _patch_http(monkeypatch, _handler())
    config = load_config()
    store = _open_store("tuipipe")
    try:
        app = SiftApp(store, "tuipipe", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            landing = app.screen
            assert isinstance(landing, NotAnalysedScreen)
            await pilot.press("a")
            await _wait_workers(app)
            await pilot.pause()
            # The worker set triage meta through the shared run_analyze body;
            # the landing screen switched to the hypothesis list in place.
            assert isinstance(app.screen, HypothesesScreen)
            assert store.get_meta("triage_created_at") is not None
            # Visible progress: the status surface logged the running stage
            # before the switch discarded the not-analysed screen.
            assert ("Analysing…", "running") in landing.pipeline_log
            assert ("Analyse complete", "idle") in landing.pipeline_log
    finally:
        store.close()


async def test_analyse_reentry_guard_runs_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second 'a' while the worker is in flight must not double-run."""
    _seed_case("tuitwice")
    _patch_http(monkeypatch, _handler())
    config = load_config()
    store = _open_store("tuitwice")
    try:
        app = SiftApp(store, "tuitwice", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_analyse()
            app.action_analyse()  # no await between: worker still in flight
            assert len(app.workers) == 1
            await _wait_workers(app)
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Nothing to cluster: exit 0 without triage meta stays on the landing screen
# ---------------------------------------------------------------------------


async def test_analyse_with_no_events_reports_status_and_stays() -> None:
    """Zero ingested events: the probe short-circuits before any HTTP client
    is built (no seam patch needed — the network guard proves it), and the
    surfaced message is run_analyze's own stdout line."""
    store = _open_store("tuiempty")  # migrated, zero events
    try:
        # No config passed: exercises the lazy load_config fallback.
        app = SiftApp(store, "tuiempty")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            await _wait_workers(app)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, NotAnalysedScreen)
            assert "Nothing to cluster" in screen.pipeline_status
            assert screen.pipeline_state == "idle"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Failure path (R012): dead endpoint → sanitised ErrorScreen, TUI alive
# ---------------------------------------------------------------------------


async def test_analyse_endpoint_failure_shows_sanitised_error_and_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("tuifail")
    # No retries/backoff so the ConnectError surfaces immediately (no sleeps).
    monkeypatch.setenv("SIFT_GENERATION_RETRIES", "0")
    monkeypatch.setenv("SIFT_GENERATION_BACKOFF_BASE", "0")

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_http(monkeypatch, dead)
    config = load_config()
    store = _open_store("tuifail")
    try:
        app = SiftApp(store, "tuifail", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            await _wait_workers(app)
            await pilot.pause()
            error = app.screen
            assert isinstance(error, ErrorScreen)
            assert "embedding/clustering failed" in error.message
            assert "Traceback" not in error.message
            # Escape pops back to the still-alive landing screen, which
            # carries the failed state on its plain status surface.
            await pilot.press("escape")
            await pilot.pause()
            landing = app.screen
            assert isinstance(landing, NotAnalysedScreen)
            assert landing.pipeline_state == "failed"
            assert "embedding/clustering failed" in landing.pipeline_status
            assert app.is_running
    finally:
        store.close()


async def test_analyse_worker_crash_is_routed_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected worker exception (exit_on_error=False) must land on the
    sanitised ErrorScreen instead of tearing the app down."""
    _seed_case("tuicrash")
    config = load_config()
    store = _open_store("tuicrash")

    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("unexpected pipeline explosion")

    monkeypatch.setattr("sift.cli.run_analyze", boom)
    try:
        app = SiftApp(store, "tuicrash", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            await _wait_workers(app)
            await pilot.pause()
            error = app.screen
            assert isinstance(error, ErrorScreen)
            assert "unexpected pipeline explosion" in error.message
            assert app.is_running
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Ingest (T04): i → run_ingest worker → events committed, status surfaced
# ---------------------------------------------------------------------------


def _seed_ingest_case(case: str, input_dir: Path) -> None:
    """Create a migrated case.db whose input_dir meta points at ``input_dir``
    — the state ``sift new`` leaves behind, without invoking the CLI."""
    store = _open_store(case)
    try:
        with store.transaction():
            store.set_meta("input_dir", str(input_dir))
    finally:
        store.close()


async def test_ingest_key_runs_worker_and_commits_events(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "bundle"
    inputs.mkdir()
    (inputs / "case.log").write_text(
        "2026-07-17 09:00:00 ERROR alpha memory pressure warning\n"
        "2026-07-17 09:01:00 ERROR beta smtp delivery retries\n",
        encoding="utf-8",
    )
    _seed_ingest_case("tuiingest", inputs)
    store = _open_store("tuiingest")
    try:
        app = SiftApp(store, "tuiingest", config=load_config())
        async with app.run_test() as pilot:
            await pilot.pause()
            landing = app.screen
            assert isinstance(landing, NotAnalysedScreen)
            await pilot.press("i")
            await _wait_workers(app)
            await pilot.pause()
            # Still not analysed: ingest leaves the landing screen in place,
            # with the run visible on the plain status surface.
            assert isinstance(app.screen, NotAnalysedScreen)
            assert ("Ingesting…", "running") in landing.pipeline_log
            assert ("Ingest complete", "idle") in landing.pipeline_log
            # The worker's own store committed real events into case.db.
            assert len(store.query_events()) > 0
    finally:
        store.close()


async def test_ingest_failure_shows_sanitised_error_and_survives(
    tmp_path: Path,
) -> None:
    """A vanished input directory is an IngestError: sanitised ErrorScreen,
    failed status on the landing screen, app alive (R012)."""
    _seed_ingest_case("tuiingestfail", tmp_path / "vanished")
    store = _open_store("tuiingestfail")
    try:
        app = SiftApp(store, "tuiingestfail", config=load_config())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await _wait_workers(app)
            await pilot.pause()
            error = app.screen
            assert isinstance(error, ErrorScreen)
            assert "input directory no longer exists" in error.message
            assert "Traceback" not in error.message
            await pilot.press("escape")
            await pilot.pause()
            landing = app.screen
            assert isinstance(landing, NotAnalysedScreen)
            assert landing.pipeline_state == "failed"
            assert "input directory no longer exists" in landing.pipeline_status
            assert app.is_running
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Report export (T04): e → run_report worker → report.md next to case.db
# ---------------------------------------------------------------------------


async def test_report_key_writes_markdown_and_records_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_analysed_case(monkeypatch, case="tuireport")
    config = load_config()
    store = _open_store("tuireport")
    try:
        app = SiftApp(store, "tuireport", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            assert app.last_report_path is None
            await pilot.press("e")
            await _wait_workers(app)
            await pilot.pause()
            out = case_db_path(config.data_dir, "tuireport").parent / "report.md"
            assert app.last_report_path == out
            text = out.read_text(encoding="utf-8")
            assert "Memory pressure exhausted the worker" in text
            # No screen change: the export surfaces a path, not a viewer.
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


async def test_report_binding_inherited_on_roam_screens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'e' lives on the CaseScreen base, so the roam screens inherit it."""
    build_analysed_case(monkeypatch, case="tuireportroam")
    config = load_config()
    store = _open_store("tuireportroam")
    try:
        app = SiftApp(store, "tuireportroam", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            await pilot.press("e")
            await _wait_workers(app)
            await pilot.pause()
            out = (
                case_db_path(config.data_dir, "tuireportroam").parent
                / "report.md"
            )
            assert app.last_report_path == out
            assert out.is_file()
    finally:
        store.close()


async def test_busy_guard_blocks_cross_action_while_analysing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three pipeline actions share ONE worker guard slot: 'i' and 'e'
    during an in-flight analyse are no-ops — one case.db writer at a time."""
    _seed_case("tuibusy")
    _patch_http(monkeypatch, _handler())
    config = load_config()
    store = _open_store("tuibusy")
    try:
        app = SiftApp(store, "tuibusy", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_analyse()
            app.action_ingest()  # blocked by the shared guard slot
            app.action_report()  # blocked by the shared guard slot
            assert len(app.workers) == 1
            await _wait_workers(app)
            await pilot.pause()
            # Only the analyse ran: hypotheses landing, no report artefact.
            assert isinstance(app.screen, HypothesesScreen)
            assert app.last_report_path is None
            out = case_db_path(config.data_dir, "tuibusy").parent / "report.md"
            assert not out.exists()
    finally:
        store.close()


async def test_report_write_failure_shows_sanitised_error_and_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unwritable report target (a directory squatting on report.md) is
    run_report's OSError exit-1 path: sanitised ErrorScreen, app alive."""
    build_analysed_case(monkeypatch, case="tuireportfail")
    config = load_config()
    out = case_db_path(config.data_dir, "tuireportfail").parent / "report.md"
    out.mkdir()  # forces the write itself to fail — a real OSError, no stub
    store = _open_store("tuireportfail")
    try:
        app = SiftApp(store, "tuireportfail", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await _wait_workers(app)
            await pilot.pause()
            error = app.screen
            assert isinstance(error, ErrorScreen)
            assert "cannot write report" in error.message
            assert app.last_report_path is None
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            assert app.is_running
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Negative bindings (T05): pipeline keys are inert off their home screens
# ---------------------------------------------------------------------------


async def test_export_key_inert_on_not_analysed_screen() -> None:
    """'e' lives on the CaseScreen base only: on the not-analysed landing
    screen it must start no worker and write nothing — there is no report
    to export before analyse."""
    config = load_config()
    store = _open_store("tuinoexport")  # migrated, zero events, not analysed
    try:
        app = SiftApp(store, "tuinoexport", config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, NotAnalysedScreen)
            await pilot.press("e")
            await pilot.pause()
            assert len(app.workers) == 0
            assert app.last_report_path is None
            out = (
                case_db_path(config.data_dir, "tuinoexport").parent
                / "report.md"
            )
            assert not out.exists()
            assert isinstance(app.screen, NotAnalysedScreen)
    finally:
        store.close()


async def test_ingest_analyse_keys_inert_on_analysed_screens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'i'/'a' bind only on NotAnalysedScreen: on the hypothesis list they
    must start no worker. The autouse zero-network guard doubles the proof —
    an accidental analyse would try to reach the (unpatched-here-after-setup)
    endpoint through a worker this asserts never exists."""
    build_analysed_case(monkeypatch, case="tuinoipa")
    store = _open_store("tuinoipa")
    try:
        app = SiftApp(store, "tuinoipa", config=load_config())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("i")
            await pilot.press("a")
            await pilot.pause()
            assert len(app.workers) == 0
            assert isinstance(app.screen, HypothesesScreen)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Help truthfulness (R013): '?' lists exactly the live pipeline bindings
# ---------------------------------------------------------------------------


async def test_help_overlay_lists_pipeline_bindings_on_not_analysed() -> None:
    store = _open_store("tuihelpna")
    try:
        app = SiftApp(store, "tuihelpna")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, NotAnalysedScreen)
            await pilot.press("question_mark")
            overlay = app.screen
            assert isinstance(overlay, HelpOverlay)
            descriptions = {desc for _, desc in overlay.entries}
            assert {"Ingest", "Analyse"} <= descriptions
            # Truthful, not aspirational: 'e' is not bound on this screen.
            assert "Export report" not in descriptions
    finally:
        store.close()


async def test_help_overlay_lists_export_binding_on_analysed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_analysed_case(monkeypatch, case="tuihelpexp")
    store = _open_store("tuihelpexp")
    try:
        app = SiftApp(store, "tuihelpexp")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("question_mark")
            overlay = app.screen
            assert isinstance(overlay, HelpOverlay)
            descriptions = {desc for _, desc in overlay.entries}
            assert "Export report" in descriptions
            # The ingest/analyse pair belongs to the not-analysed state only.
            assert "Ingest" not in descriptions
            assert "Analyse" not in descriptions
    finally:
        store.close()
