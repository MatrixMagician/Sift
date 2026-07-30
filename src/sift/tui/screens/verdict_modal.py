"""The verdict capture modal (R003/R012): the TUI's only verdict write path.

:class:`VerdictModal` owns the whole capture interaction: it receives the
store and a pre-built :class:`~sift.verdicts.TargetSpec` plus a
human-readable target label, lets the operator pick a state and type an
optional note, performs the write itself through
:func:`sift.verdicts.record_validation` (the single mandatory write path;
the store's raw verdict-append method appears nowhere under
``src/sift/tui`` — grep-proven by the slice gate), and
dismisses with the :class:`~sift.verdicts.RecordedVerdict` on success or
``None`` on cancel. The invoking screen's dismissal callback is the ONLY
place a badge is painted or a progress count refreshed — what the operator
sees is literally what ``record_validation`` returned after its INSERT
landed (R012's commit gate).

Keyboard flow: a focused Textual ``Input`` consumes printable keys, so the
state shortcuts are deliberately modal-level bindings and nothing is
focused on open (``AUTO_FOCUS = None``) — press c/r/u to choose a state,
tab to reach the note field, enter to commit (from the note field too, via
``Input.Submitted``), escape to cancel.

Error handling stays inside the modal: ``guarded()`` catches only
``sqlite3.Error``, and :class:`~sift.verdicts.VerdictError` is a plain
Exception, so an uncaught raise would vanish into Textual's event loop.
Every commit failure becomes a sanitised, markup-inert inline message —
the locked-database case surfaces R012's exact wording "case locked by
another process" — the modal stays open, and nothing is written.
"""

import sqlite3
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from sift.render._util import sanitise
from sift.store import CaseStore
from sift.verdicts import (
    RecordedVerdict,
    TargetSpec,
    VerdictError,
    record_validation,
)

# R012's exact wording for a SQLITE_BUSY commit on the interactive surface.
LOCKED_MESSAGE = "Commit failed: case locked by another process. Nothing was recorded."
# Q7: committing with no state selected writes nothing — never a default.
NO_STATE_MESSAGE = "Choose a verdict state first: c confirm, r reject, u uncertain."

_KEY_HINTS = "c confirm · r reject · u uncertain · tab note · enter commit · esc cancel"


class VerdictModal(ModalScreen[RecordedVerdict | None]):
    """Capture confirmed/rejected/uncertain + optional note for one target."""

    # Nothing focused on open: c/r/u must reach the modal bindings, not the
    # note Input (a focused Input consumes printable keys). Tab opts in.
    # "" disables auto-focus; None would inherit the app-wide "*" default.
    AUTO_FOCUS = ""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "choose('confirmed')", "Confirm"),
        Binding("r", "choose('rejected')", "Reject"),
        Binding("u", "choose('uncertain')", "Uncertain"),
        Binding("enter", "commit", "Commit"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    VerdictModal {
        align: center middle;
    }
    #verdict-body {
        width: 70;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #verdict-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #verdict-message {
        text-style: bold;
    }
    """

    def __init__(
        self, store: CaseStore, target: TargetSpec, target_label: str
    ) -> None:
        """``target_label`` is shown to the operator; it carries DB/model
        bytes, so it is sanitised and rendered markup-inert (WR-01)."""
        super().__init__()
        self._store = store
        self._target = target
        self._label = target_label
        self.chosen_state: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="verdict-body"):
            yield Static("Record verdict", id="verdict-title")
            yield Static(
                sanitise(f"{self._target.target_type}: {self._label}"),
                id="verdict-target",
                markup=False,
            )
            yield Static(self._state_line(), id="verdict-state")
            yield Input(placeholder="optional note", id="verdict-note")
            yield Static("", id="verdict-message", markup=False)
            yield Static(_KEY_HINTS, id="verdict-keys")

    def _state_line(self) -> str:
        return f"State: {self.chosen_state or 'none selected'}"

    def _show_message(self, text: str) -> None:
        self.query_one("#verdict-message", Static).update(text)

    def action_choose(self, state: str) -> None:
        self.chosen_state = state
        self.query_one("#verdict-state", Static).update(self._state_line())
        self._show_message("")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_commit(self) -> None:
        self._commit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter inside the note field commits too — one key, one meaning.
        event.stop()
        self._commit()

    def _commit(self) -> None:
        """Route the write through record_validation; failures stay inline.

        Nothing is painted here on success — the RecordedVerdict travels out
        through ``dismiss`` to the invoking screen's callback, which is the
        commit gate (R012). On any failure the modal stays open with a
        sanitised message and zero rows written: ``record_validation`` is a
        single INSERT, so there is no partial state to roll back.
        """
        if self.chosen_state is None:
            self._show_message(NO_STATE_MESSAGE)
            return
        note = self.query_one("#verdict-note", Input).value
        try:
            recorded = record_validation(
                self._store, self._target, self.chosen_state, note=note
            )
        except VerdictError as exc:
            # UnknownTargetError: the case was re-analysed externally and the
            # target vanished mid-session — report, never crash (Q5).
            self._show_message(sanitise(f"Commit failed: {exc}"))
            return
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                self._show_message(LOCKED_MESSAGE)
            else:
                self._show_message(sanitise(f"Commit failed: {exc}"))
            return
        except sqlite3.Error as exc:
            # Corrupt or vanished case.db mid-commit: same inline surface —
            # the modal is self-contained, the operator escapes back out.
            self._show_message(sanitise(f"Commit failed: {exc}"))
            return
        self.dismiss(recorded)
