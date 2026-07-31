"""The Textual application shell behind ``sift tui``.

The shell owns exactly three concerns every screen inherits:

* **Landing** — on mount it decides between the hypothesis list (analysed;
  the R001 review loop's entry point), the not-analysed screen (R012's
  "clear screen, not an error exit"), and a sanitised :class:`ErrorScreen`
  when even that first meta read fails.
* **Navigation actions** — ``back`` (escape pops to the parent screen, a
  no-op on the landing screen), ``help`` ('?' snapshots the current
  screen's active bindings into a :class:`HelpOverlay`, R013), and the
  roam actions ``clusters``/``timeline`` ('c'/'t' from any case screen,
  R002) — defined once here so every screen inherits them via the shared
  ``CaseScreen`` bindings.
* **Local-only egress** — browsing talks only to the injected ``CaseStore``
  and closes nothing on exit (the CLI entry point owns the store's
  lifecycle, so the WAL checkpoint happens exactly once). The single
  network path is the analyse worker's ``InferenceClient`` against the
  configured localhost endpoint, constructed by the same ``run_analyze``
  body the CLI runs (SSRF guard included).
"""

import sqlite3
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import ClassVar, cast

from textual.app import App
from textual.binding import Binding, BindingType
from textual.worker import Worker, WorkerState

from sift.config import SiftConfig, load_config
from sift.render._util import sanitise
from sift.store import CaseStore, case_db_path
from sift.tui.screens.clusters import ClustersScreen
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
from sift.tui.screens.help_overlay import HelpOverlay
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import TimelineScreen


class SiftApp(App[None]):
    """Case browser + pipeline runner over one injected ``CaseStore`` (§5.7)."""

    TITLE = "Sift"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(
        self,
        store: CaseStore,
        case_name: str,
        config: SiftConfig | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.case_name = case_name
        self.sub_title = sanitise(case_name)
        # The tui command threads its resolved SiftConfig in so pipeline
        # workers can derive the endpoint and db path; ``None`` (read-only
        # embedding contexts, older tests) resolves lazily on first use.
        self.config = config
        # One guard slot for all pipeline workers (ingest/analyse/report):
        # one case.db writer at a time, matching the CLI's one-process-per-run
        # discipline. Result shapes differ per worker, so the slot is typed
        # to the common supertype and the completion handler casts by name.
        self._pipeline_worker: Worker[object] | None = None
        # Where the last successful 'e' export landed — the plain assertable
        # surface behind the toast (S02 discipline).
        self.last_report_path: Path | None = None

    def on_mount(self) -> None:
        # The analysed-or-not probe is the app's first store read, so it gets
        # the same sanitised failure path guarded() gives screens: a corrupt
        # or vanished case.db lands on ErrorScreen, never a traceback (R012).
        try:
            analysed = self.store.get_meta("triage_created_at") is not None
        except sqlite3.Error as exc:
            self.push_screen(ErrorScreen(str(exc)))
            return
        if analysed:
            self.push_screen(HypothesesScreen(self.store))
        else:
            self.push_screen(NotAnalysedScreen(self.case_name))

    async def action_back(self) -> None:
        """Escape: pop to the parent screen; a no-op on the landing screen.

        Overrides Textual's built-in (async) action: the stack is
        [default, landing, ...], and the built-in would happily pop the
        landing screen, stranding the user on the blank default screen.
        """
        if len(self.screen_stack) > 2:
            self.pop_screen()

    def _roam(
        self,
        target_cls: type[ClustersScreen] | type[TimelineScreen],
        sibling_cls: type[ClustersScreen] | type[TimelineScreen],
    ) -> None:
        """Shared roam body: a no-op on the target screen already.

        The two roam surfaces are siblings, so hopping from one replaces
        the other instead of stacking — alternating c/t holds the stack
        flat and escape returns to wherever roaming started.
        """
        if isinstance(self.screen, target_cls):
            return
        if isinstance(self.screen, sibling_cls):
            # Textual types switch_screen's parameter as Screen[Unknown].
            self.switch_screen(  # pyright: ignore[reportUnknownMemberType]
                target_cls(self.store)
            )
            return
        self.push_screen(target_cls(self.store))

    def action_clusters(self) -> None:
        """'c': open the cluster browser (R002); a no-op if already there."""
        self._roam(ClustersScreen, TimelineScreen)

    def action_timeline(self) -> None:
        """'t': open the event timeline (R002); a no-op if already there."""
        self._roam(TimelineScreen, ClustersScreen)

    def action_help(self) -> None:
        """'?': overlay the current screen's active bindings (R013)."""
        if isinstance(self.screen, HelpOverlay):
            return
        entries = [
            (self.get_key_display(active.binding), active.binding.description)
            for active in self.screen.active_bindings.values()
            if active.binding.description
        ]
        self.push_screen(HelpOverlay(entries))

    # ------------------------------------------------------------------
    # Pipeline actions (S04): the shared cli.py bodies in thread workers
    # ------------------------------------------------------------------

    def _pipeline_busy(self) -> bool:
        """Re-entrancy guard shared by every pipeline action: a key press
        while any pipeline worker is still in flight is a no-op."""
        return self._pipeline_worker is not None and (
            not self._pipeline_worker.is_finished
        )

    def _resolve_config(self) -> SiftConfig:
        """The threaded-in SiftConfig, or a lazy load_config on first use."""
        if self.config is None:
            self.config = load_config()
        return self.config

    def _start_pipeline_worker(
        self, work: Callable[[], object], name: str
    ) -> None:
        self._pipeline_worker = self.run_worker(
            work,
            name=name,
            group="pipeline",
            thread=True,
            exit_on_error=False,
        )

    def action_analyse(self) -> None:
        """'a': run the analyse pipeline in a background thread worker (R006)."""
        if self._pipeline_busy():
            return
        config = self._resolve_config()
        self._show_pipeline_status("Analysing…", "running")
        self._start_pipeline_worker(partial(self._run_analyse, config), "analyse")

    def action_ingest(self) -> None:
        """'i': run ingest in a background thread worker (R006).

        Reuses the CLI's ``run_ingest`` body against the case's recorded
        ``input_dir`` — re-ingesting the same snapshot adds zero events.
        """
        if self._pipeline_busy():
            return
        config = self._resolve_config()
        self._show_pipeline_status("Ingesting…", "running")
        self._start_pipeline_worker(partial(self._run_ingest, config), "ingest")

    def action_report(self) -> None:
        """'e': export the Markdown report next to case.db in a worker (R006).

        Per the S04 planning decision there is no in-TUI viewer: the shared
        ``run_report`` body writes ``report.md`` into the case directory and
        the completion handler surfaces the written path.
        """
        if self._pipeline_busy():
            return
        config = self._resolve_config()
        self._start_pipeline_worker(partial(self._run_report, config), "report")

    def _run_analyse(self, config: SiftConfig) -> tuple[int, list[str]]:
        """Thread-worker body: the CLI's ``run_analyze`` on a fresh store.

        The app's main-thread ``CaseStore`` cannot cross threads (sqlite's
        default ``check_same_thread``), so the worker opens its OWN store
        against the same case.db (WAL: one writer + readers; migrations are
        idempotent) and closes it on every path. Returns the CLI-04 exit
        code plus every echoed line, for the main-thread completion handler
        to route. ``run_analyze`` is resolved late off the module so the
        test seams (``sift.cli._make_http_client``) keep working.
        """
        from sift import cli  # deferred: cli imports this module's package

        lines: list[str] = []

        def announce(message: str) -> None:
            self.call_from_thread(
                self._show_pipeline_status, message, "running"
            )

        store = CaseStore(case_db_path(config.data_dir, self.case_name))
        try:
            code = cli.run_analyze(
                store,
                config,
                echo=lines.append,
                echo_err=lines.append,
                announce=announce,
            )
        finally:
            store.close()
        return code, lines

    def _run_ingest(self, config: SiftConfig) -> None:
        """Thread-worker body: the CLI's ``run_ingest`` on a fresh store.

        Same per-worker store discipline as :meth:`_run_analyse`. IngestError
        and IngestUsageError bubble deliberately — the ERROR routing in
        :meth:`on_worker_state_changed` is the sanitised failure surface.
        ``run_ingest`` resolves late off the cli module so tests can patch
        the same ``sift.cli`` seam family the analyse worker uses.
        """
        from sift import cli  # deferred: cli imports this module's package

        store = CaseStore(case_db_path(config.data_dir, self.case_name))
        try:
            cli.run_ingest(self.case_name, config, store)
        finally:
            store.close()

    def _run_report(self, config: SiftConfig) -> tuple[int, list[str], Path]:
        """Thread-worker body: the CLI's ``run_report`` on a fresh store.

        Writes Markdown to ``report.md`` next to case.db (the S04 planning
        decision: export to the case directory, no in-TUI viewer). Returns
        the ADR 0007 exit code, every echoed line and the target path for
        the main-thread completion handler to route.
        """
        from sift import cli  # deferred: cli imports this module's package

        lines: list[str] = []
        db_path = case_db_path(config.data_dir, self.case_name)
        out = db_path.parent / "report.md"
        store = CaseStore(db_path)
        try:
            code = cli.run_report(store, out=out, echo=lines.append)
        finally:
            store.close()
        return code, lines, out

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route pipeline worker completion on the main thread (R012).

        The ERROR leg is shared: any pipeline worker exception surfaces on
        the sanitised ErrorScreen with the app still navigable — never a
        crash (``exit_on_error=False`` on the worker). SUCCESS routes by
        worker name, since each body returns its own result shape.
        """
        worker = cast(
            "Worker[object]",
            event.worker,  # pyright: ignore[reportUnknownMemberType]
        )
        if worker.group != "pipeline":
            return
        if event.state == WorkerState.ERROR:
            detail = str(worker.error or "pipeline worker failed")
            self._show_pipeline_status(detail, "failed")
            self.push_screen(ErrorScreen(detail))
            return
        if event.state != WorkerState.SUCCESS:
            return
        if worker.name == "ingest":
            self._show_pipeline_status("Ingest complete", "idle")
            return
        if worker.name == "report":
            self._route_report(
                cast("tuple[int, list[str], Path]", worker.result)
            )
            return
        self._route_analyse(cast("tuple[int, list[str]]", worker.result))

    def _route_report(self, result: tuple[int, list[str], Path]) -> None:
        """Surface one report export: the written path, or a sanitised error."""
        code, lines, out = result
        if code:
            self.push_screen(ErrorScreen(lines[-1] if lines else "Report failed"))
            return
        self.last_report_path = out
        # markup=False for the same reason every Static is markup=False:
        # the path embeds the user-supplied case name (T-04-01).
        self.notify(f"Report written to {sanitise(str(out))}", markup=False)

    def _route_analyse(self, result: tuple[int, list[str]]) -> None:
        """Route one analyse completion: success (or degraded-but-persisted)
        with triage meta present switches the landing screen to the
        hypothesis list; failure exit codes surface on the ErrorScreen."""
        code, lines = result
        detail = lines[-1] if lines else ""
        if code not in (0, 3):
            self._show_pipeline_status(detail or "Analyse failed", "failed")
            self.push_screen(ErrorScreen(detail or "Analyse failed"))
            return
        try:
            analysed = self.store.get_meta("triage_created_at") is not None
        except sqlite3.Error as exc:
            self.push_screen(ErrorScreen(str(exc)))
            return
        if not analysed:
            # Exit 0 without triage meta: the nothing-to-cluster path —
            # surface run_analyze's own message and rest, still analysable.
            self._show_pipeline_status(detail or "Nothing to analyse", "idle")
            return
        self._show_pipeline_status("Analyse complete", "idle")
        if isinstance(self.screen, NotAnalysedScreen):
            self.switch_screen(  # pyright: ignore[reportUnknownMemberType]
                HypothesesScreen(self.store)
            )

    def _show_pipeline_status(self, message: str, state: str) -> None:
        """Paint one status transition on the not-analysed landing screen.

        A no-op once the screen has been switched away — late worker
        messages after the hypotheses transition have nowhere to land.
        """
        for screen in self.screen_stack:
            if isinstance(screen, NotAnalysedScreen):
                screen.set_pipeline_status(message, state)
