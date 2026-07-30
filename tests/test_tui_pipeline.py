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

import httpx
import pytest

# The seeding/patching kit is module-private by convention but IS the shared
# surface (research: the S04 Pilot recipe); _report_fixtures itself is frozen
# by the R009 byte-identical gate, so no public re-export can be added there.
from _report_fixtures import (
    _handler,  # pyright: ignore[reportPrivateUsage]
    _patch_http,  # pyright: ignore[reportPrivateUsage]
    _seed_case,  # pyright: ignore[reportPrivateUsage]
)

from sift.config import load_config
from sift.store import CaseStore, case_db_path
from sift.tui.app import SiftApp
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
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
