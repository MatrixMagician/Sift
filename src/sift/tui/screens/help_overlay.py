"""The '?' help overlay (R013): a modal listing the active key bindings.

The overlay is built from whatever bindings were ACTIVE on the screen
underneath when '?' was pressed (``SiftApp.action_help`` snapshots them), so
it is discoverable and always truthful — a screen that adds a binding never
has to remember to update a separate help table. Binding descriptions are
code constants, never DB or model text, so no sanitisation is needed here.
"""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpOverlay(ModalScreen[None]):
    """Modal list of the underlying screen's active bindings."""

    BINDINGS: ClassVar[list[BindingType]] = [
        # '?' closes as well as opens, so the key is a toggle; q closes the
        # overlay rather than quitting the app (screen bindings win).
        Binding("escape,question_mark,q", "close_help", "Close", key_display="esc"),
    ]

    DEFAULT_CSS = """
    HelpOverlay {
        align: center middle;
    }
    #help-body {
        width: 60;
        max-height: 80%;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #help-title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def __init__(self, entries: list[tuple[str, str]]) -> None:
        """``entries`` is (displayed key, description) per active binding."""
        super().__init__()
        self.entries = entries

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Static("Key bindings", id="help-title")
            for key, description in self.entries:
                yield Static(f"{key:>8}  {description}", markup=False)

    def action_close_help(self) -> None:
        self.dismiss()
