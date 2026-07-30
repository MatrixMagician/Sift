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
from functools import partial
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
        self._pipeline_worker: Worker[tuple[int, list[str]]] | None = None

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

    def action_clusters(self) -> None:
        """'c': open the cluster browser (R002); a no-op if already there.

        The two roam surfaces are siblings, so hopping from the timeline
        replaces it instead of stacking — alternating c/t holds the stack
        flat and escape returns to wherever roaming started.
        """
        if isinstance(self.screen, ClustersScreen):
            return
        if isinstance(self.screen, TimelineScreen):
            # Textual types switch_screen's parameter as Screen[Unknown].
            self.switch_screen(  # pyright: ignore[reportUnknownMemberType]
                ClustersScreen(self.store)
            )
            return
        self.push_screen(ClustersScreen(self.store))

    def action_timeline(self) -> None:
        """'t': open the event timeline (R002); a no-op if already there.

        Sibling-switch mirror of :meth:`action_clusters`.
        """
        if isinstance(self.screen, TimelineScreen):
            return
        if isinstance(self.screen, ClustersScreen):
            self.switch_screen(  # pyright: ignore[reportUnknownMemberType]
                TimelineScreen(self.store)
            )
            return
        self.push_screen(TimelineScreen(self.store))

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

    def action_analyse(self) -> None:
        """'a': run the analyse pipeline in a background thread worker (R006).

        Re-entrancy guard: a second press while a pipeline worker is still
        in flight is a no-op — one case.db writer at a time, matching the
        CLI's one-process-per-run discipline.
        """
        if self._pipeline_worker is not None and (
            not self._pipeline_worker.is_finished
        ):
            return
        if self.config is None:
            self.config = load_config()
        self._show_pipeline_status("Analysing…", "running")
        self._pipeline_worker = self.run_worker(
            partial(self._run_analyse, self.config),
            name="analyse",
            group="pipeline",
            thread=True,
            exit_on_error=False,
        )

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

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route pipeline worker completion on the main thread (R012).

        Success (or degraded-but-persisted) with triage meta present
        switches the landing screen to the hypothesis list; every failure
        surfaces on the sanitised ErrorScreen with the app still navigable
        — never a crash (``exit_on_error=False`` on the worker).
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
        code, lines = cast("tuple[int, list[str]]", worker.result)
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
