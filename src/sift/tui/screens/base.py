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
from collections.abc import Callable, Iterable
from typing import ClassVar, cast

from rich.text import Text
from textual.app import App
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable
from textual.widgets.data_table import ColumnKey

from sift.store import CaseStore
from sift.tui.review_state import latest_verdicts
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
        Binding("e", "app.report", "Export report"),
        Binding("question_mark", "app.help", "Help", key_display="?"),
    ]

    # Populated by the table-bearing subclasses; the shared badge helpers
    # below read them and stay inert until a mount assigns _verdict_col.
    _store: CaseStore
    table: DataTable[Text]
    _verdict_col: ColumnKey | None = None

    @property
    def _app(self) -> App[object]:
        """The running app, cast once for every subclass.

        Textual types Screen.app as App[Unknown]; the typed alternative
        (getters.app(SiftApp)) would be a circular import, so cast once.
        """
        return cast(
            "App[object]",
            self.app,  # pyright: ignore[reportUnknownMemberType]
        )

    def push(self, screen: Screen[None]) -> None:
        """Push a screen via the app, typed once here for every subclass."""
        self._app.push_screen(screen)

    def _refresh_badges(self, level: str, keys: Iterable[str]) -> None:
        """DB re-read of ``level`` rulings into the Verdict column (R012).

        ``keys`` are the screen's row keys, which double as target ids; a
        target with no ruling paints the empty badge.
        """
        if self._verdict_col is None:
            return
        badges = self.guarded(lambda: latest_verdicts(self._store, level))
        if badges is None:
            return
        for key in keys:
            self.table.update_cell(
                key,
                self._verdict_col,
                Text(badges.get((level, key), "")),
            )

    def _paint_recorded(self, recorded: RecordedVerdict) -> None:
        """The R012 commit gate: paint exactly what the INSERT returned."""
        if self._verdict_col is not None:
            self.table.update_cell(
                recorded.target_id, self._verdict_col, Text(recorded.verdict)
            )

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

        self._app.push_screen(VerdictModal(store, target, label), gate)

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
