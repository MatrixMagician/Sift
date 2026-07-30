"""Failure surfaces (R012): a clear screen with a sanitised message.

The TUI's WR-02: a locked, corrupt or vanished case.db becomes one of these
screens, never a Python traceback and never a silently dead widget. Message
text can echo attacker-controlled db bytes, so every displayed string goes
through the same ``sanitise`` the CLI uses (T-04-01) and is rendered with
Textual markup disabled — hostile log bytes drive neither the terminal nor
Textual's markup parser.

These screens deliberately do NOT extend ``base.CaseScreen``: ``base``
imports ``ErrorScreen`` for its guarded-read contract, so this module stays
import-leaf and redeclares the three shared navigation bindings instead.
"""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Static

from sift.render._util import sanitise

_NAV_BINDINGS: list[BindingType] = [
    Binding("q", "app.quit", "Quit"),
    Binding("escape", "app.back", "Back"),
    Binding("question_mark", "app.help", "Help", key_display="?"),
]


class ErrorScreen(Screen[None]):
    """A store/DB failure, presented sanitised — the anti-traceback screen."""

    BINDINGS: ClassVar[list[BindingType]] = list(_NAV_BINDINGS)

    DEFAULT_CSS = """
    ErrorScreen {
        padding: 1 2;
    }
    #error-title {
        text-style: bold;
        color: $error;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = sanitise(message)

    def compose(self) -> ComposeResult:
        yield Static("Error", id="error-title")
        yield Static(self.message, id="error-message", markup=False)
        yield Static(
            "Press escape to go back, or q to quit.",
            id="error-hint",
        )
        yield Footer()


class NotAnalysedScreen(Screen[None]):
    """The case exists but has no triage results yet (R012): say so plainly.

    Opening the TUI on this screen (rather than exiting 1) is deliberate —
    S04 attaches its run-analyse-from-inside actions here.
    """

    BINDINGS: ClassVar[list[BindingType]] = list(_NAV_BINDINGS)

    DEFAULT_CSS = """
    NotAnalysedScreen {
        padding: 1 2;
    }
    #not-analysed-title {
        text-style: bold;
        color: $warning;
    }
    """

    def __init__(self, case_name: str) -> None:
        super().__init__()
        self.case_name = sanitise(case_name)

    def compose(self) -> ComposeResult:
        yield Static("Case not analysed", id="not-analysed-title")
        yield Static(
            f"Case {self.case_name!r} has no triage results yet.\n"
            f"Run: sift analyze {self.case_name}",
            id="not-analysed-message",
            markup=False,
        )
        yield Footer()
