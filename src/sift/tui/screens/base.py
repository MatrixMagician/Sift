"""Shared behaviour every case-browsing screen inherits.

Three contracts live here and nowhere else:

* **Navigation bindings** — q quits, escape goes back, '?' opens the help
  overlay. All three dispatch to app-level actions (``app.quit``,
  ``app.back``, ``app.help``) so the behaviour is defined once on
  ``SiftApp`` rather than re-implemented per screen; Textual merges these
  BINDINGS into every subclass.

* **The guarded-read contract** — every ``CaseStore`` read a screen makes
  goes through :meth:`CaseScreen.guarded`, so a locked, corrupt or vanished
  case.db mid-session becomes a sanitised :class:`ErrorScreen` (R012)
  instead of an exception Textual's event loop would swallow. MEM014: wrap
  the *pull* (e.g. ``EventPager.page``), never just construction — the
  store's deferred generator errors fire on the first row, not at build.

* **The commit gate** — :meth:`CaseScreen.capture_verdict` is how every
  screen opens the verdict modal, and its dismissal filter is the ONLY
  place a screen's paint callback fires: with the ``RecordedVerdict`` the
  modal's committed INSERT returned, never on cancel or failure (R012).
"""

import sqlite3
from collections.abc import Callable
from typing import ClassVar, cast

from textual.app import App
from textual.binding import Binding, BindingType
from textual.screen import Screen

from sift.store import CaseStore
from sift.tui.screens.error import ErrorScreen
from sift.tui.screens.verdict_modal import VerdictModal
from sift.verdicts import RecordedVerdict, TargetSpec


class CaseScreen(Screen[None]):
    """Base for case-browsing screens: shared bindings + guarded store reads."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "app.quit", "Quit"),
        Binding("escape", "app.back", "Back"),
        Binding("c", "app.clusters", "Clusters"),
        Binding("t", "app.timeline", "Timeline"),
        Binding("question_mark", "app.help", "Help", key_display="?"),
    ]

    def push(self, screen: Screen[None]) -> None:
        """Push a screen via the app, typed once here for every subclass.

        Textual types Screen.app as App[Unknown]; the typed alternative
        (getters.app(SiftApp)) would be a circular import, so cast once.
        """
        app = cast(
            "App[object]",
            self.app,  # pyright: ignore[reportUnknownMemberType]
        )
        app.push_screen(screen)

    def capture_verdict(
        self,
        store: CaseStore,
        target: TargetSpec,
        label: str,
        on_recorded: Callable[[RecordedVerdict], None],
    ) -> None:
        """Open the verdict capture modal for one target (R003).

        ``on_recorded`` is the R012 commit gate: it fires only when the
        modal dismissed with the :class:`RecordedVerdict` its committed
        INSERT returned. Cancel and every failure path dismiss with
        ``None``, so the caller's badge/progress paint never runs for a
        verdict that did not land.
        """

        def gate(recorded: RecordedVerdict | None) -> None:
            if recorded is not None:
                on_recorded(recorded)

        app = cast(
            "App[object]",
            self.app,  # pyright: ignore[reportUnknownMemberType]
        )
        app.push_screen(VerdictModal(store, target, label), gate)

    def guarded[T](self, read: Callable[[], T]) -> T | None:
        """Run a store read; a sqlite failure becomes a sanitised ErrorScreen.

        Returns ``None`` when the read failed — the error screen is already
        pushed, so the caller simply stops rendering.
        """
        try:
            return read()
        except sqlite3.Error as exc:
            self.push(ErrorScreen(str(exc)))
            return None
