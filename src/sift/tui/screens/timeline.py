"""Event timeline (R002 + R008): every stored event, lazily paged.

The events table is the one unbounded case table, so this is the one
screen that reads through :class:`~sift.tui.data_access.EventPager`: page 0
loads on mount, and moving the cursor onto the last loaded row pulls the
next page — never a fetchall, so opening the timeline costs one page at
any case size. The pager wraps ``iter_event_rows``, which deliberately
applies NO ranking exclusions: uncited, perfmon and severity="unknown"
events all appear (R002 — the operator must see what the LLM was never
shown or never cited).

Selecting a row hydrates that single event through
``CaseStore.get_events_by_ids`` — the drill-down boundary where raw is
first read (and possibly zstd-decompressed) — and opens the shared
:class:`~sift.tui.screens.evidence.RawSourceScreen`.

Every DB-sourced string is sanitised and rendered markup-inert (WR-01,
T-04-01) via the shared ``cell`` helper.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from sift.store import CaseStore
from sift.tui.data_access import DEFAULT_PAGE_SIZE, EventPager
from sift.tui.screens.base import CaseScreen
from sift.tui.screens.evidence import RawSourceScreen, cell

# Shown when the events table holds nothing at all.
NO_EVENTS_MESSAGE = "No events stored for this case."


def _first_line(text: str) -> str:
    """A message's first line — multi-line records stay one table row."""
    return text.splitlines()[0] if text else ""


class TimelineScreen(CaseScreen):
    """The full event timeline, paged lazily over the store's cursor."""

    DEFAULT_CSS = """
    TimelineScreen #timeline-status {
        padding: 0 1;
        color: $text-muted;
    }
    """

    table: DataTable[Text]

    def __init__(
        self, store: CaseStore, page_size: int = DEFAULT_PAGE_SIZE
    ) -> None:
        super().__init__()
        self._store = store
        self._pager = EventPager(store, page_size=page_size)
        self._next_page = 0

    def compose(self) -> ComposeResult:
        self.table = DataTable[Text](id="timeline-table", cursor_type="row")
        yield Header()
        yield Static("", id="timeline-status", markup=False)
        yield self.table
        yield Footer()

    def on_mount(self) -> None:
        self.table.add_columns(
            "Event", "Timestamp", "Severity", "Where", "Message"
        )
        self._load_next_page()
        self.table.focus()

    def _load_next_page(self) -> None:
        """Append one page of rows; a store failure becomes ErrorScreen.

        MEM014: the guarded call wraps the *pull* — the store's deferred
        cursor errors fire on the first row, not at pager construction.
        """
        rows = self.guarded(lambda: self._pager.page(self._next_page))
        if rows is None:
            return
        self._next_page += 1
        for row in rows:
            self.table.add_row(
                cell(row.event_id),
                cell(row.ts or "—"),
                cell(row.severity),
                cell(f"{row.source_file}:{row.line_start}"),
                cell(_first_line(row.message)),
                key=row.event_id,
            )
        self._update_status()

    def _update_status(self) -> None:
        if self._pager.loaded_count == 0 and self._pager.exhausted:
            status = NO_EVENTS_MESSAGE
        else:
            status = f"{self._pager.loaded_count} events loaded"
            if not self._pager.exhausted:
                status += " — scroll down for more"
        self.query_one("#timeline-status", Static).update(status)

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        # Reaching the last loaded row pulls the next page: the load trigger
        # is the cursor, so cost per keystroke is bounded by page_size (R008).
        if self._pager.exhausted:
            return
        if event.cursor_row >= self.table.row_count - 1:
            self._load_next_page()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        events = self.guarded(lambda: self._store.get_events_by_ids([key]))
        if events is None:
            return
        hydrated = events.get(key)
        if hydrated is None:
            # The row vanished from the store since it was paged in —
            # nothing stored to show, deliberately inert.
            return
        self.push(RawSourceScreen(hydrated))
