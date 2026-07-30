"""The Textual application shell behind ``sift tui``.

The shell owns exactly three concerns every screen inherits:

* **Landing** — on mount it decides between the case overview (analysed),
  the not-analysed screen (R012's "clear screen, not an error exit"), and a
  sanitised :class:`ErrorScreen` when even that first meta read fails.
* **Navigation actions** — ``back`` (escape pops to the parent screen, a
  no-op on the landing screen) and ``help`` ('?' snapshots the current
  screen's active bindings into a :class:`HelpOverlay`, R013).
* **Zero egress** — the app talks only to the injected ``CaseStore``; it
  opens no HTTP client and closes nothing on exit (the CLI entry point owns
  the store's lifecycle, so the WAL checkpoint happens exactly once).
"""

import sqlite3
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Header, Static

from sift.render._util import sanitise
from sift.store import CaseStore
from sift.tui.screens.base import CaseScreen
from sift.tui.screens.error import ErrorScreen, NotAnalysedScreen
from sift.tui.screens.help_overlay import HelpOverlay


class OverviewScreen(CaseScreen):
    """Interim landing screen: the analysed case at a glance.

    T03 replaces this as the landing screen with the hypothesis list. It
    reads only the bounded aggregate tables (hypotheses, clusters) and meta —
    never an events scan — so mounting costs nothing at any case size (R008).
    """

    def __init__(self, store: CaseStore, case_name: str) -> None:
        super().__init__()
        self._store = store
        self._case_name = case_name

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="overview-summary", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        loaded = self.guarded(
            lambda: (
                len(self._store.query_hypotheses()),
                len(self._store.query_clusters()),
                self._store.get_meta("created_at"),
            )
        )
        if loaded is None:
            return
        n_hypotheses, n_clusters, created_at = loaded
        summary = (
            f"Case: {self._case_name}\n"
            f"Created: {created_at or '—'}\n"
            f"Hypotheses: {n_hypotheses}\n"
            f"Clusters: {n_clusters}\n"
            "\n"
            "Press ? for help."
        )
        # created_at is DB-sourced and therefore untrusted in a shared
        # case.db — sanitise the complete rendered block (WR-01).
        self.query_one("#overview-summary", Static).update(sanitise(summary))


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
            self.push_screen(OverviewScreen(self.store, self.case_name))
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
