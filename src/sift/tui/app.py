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
* **Zero egress** — the app talks only to the injected ``CaseStore``; it
  opens no HTTP client and closes nothing on exit (the CLI entry point owns
  the store's lifecycle, so the WAL checkpoint happens exactly once).
"""

import sqlite3
from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from sift.render._util import sanitise
from sift.store import CaseStore
from sift.tui.screens.clusters import ClustersScreen
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
from sift.tui.screens.help_overlay import HelpOverlay
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import TimelineScreen


class SiftApp(App[None]):
    """Read-only case browser over one injected ``CaseStore`` (SPEC.md §5.7)."""

    TITLE = "Sift"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(self, store: CaseStore, case_name: str) -> None:
        super().__init__()
        self.store = store
        self.case_name = case_name
        self.sub_title = sanitise(case_name)

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
        """'c': open the cluster browser (R002); a no-op if already there."""
        if isinstance(self.screen, ClustersScreen):
            return
        self.push_screen(ClustersScreen(self.store))

    def action_timeline(self) -> None:
        """'t': open the event timeline (R002); a no-op if already there."""
        if isinstance(self.screen, TimelineScreen):
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
