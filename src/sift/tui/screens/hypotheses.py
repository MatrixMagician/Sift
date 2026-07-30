"""The landing screen (R001): the ranked hypothesis list.

The table reads the whole persisted set through ``query_hypotheses`` — a
bounded aggregate (hyp_index-ordered, a handful of rows), never an events
scan, so landing costs nothing at any case size (R008). Enter drills into
the selected hypothesis's :class:`~sift.tui.screens.evidence.EvidenceScreen`.

A ``citations_valid=False`` row is marked FLAGGED in its own column — the
citation gate's verdict must stay visible at the ranking level, not only
after drill-down. An analysed case with ZERO schema-valid rows (a
hard-degraded run) says so on screen instead of presenting an empty table
as "no findings" — nothing disappears silently.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from sift.store import CaseStore, StoredHypothesis
from sift.tui.screens.base import CaseScreen
from sift.tui.screens.evidence import EvidenceScreen, cell

# Shown when analyze ran but persisted zero schema-valid hypotheses
# (mirrors the `sift show hypotheses` degraded-run wording).
NO_HYPOTHESES_MESSAGE = (
    "No schema-valid hypotheses; the last analyze may have degraded.\n"
    "Run 'sift report' to view the DEGRADED banner and raw output."
)


class HypothesesScreen(CaseScreen):
    """Ranked hypotheses; enter opens the cited-evidence drill-down."""

    DEFAULT_CSS = """
    HypothesesScreen #hypotheses-empty {
        padding: 0 1;
    }
    """

    table: DataTable[Text]

    def __init__(self, store: CaseStore) -> None:
        super().__init__()
        self._store = store
        self._hyps: dict[str, StoredHypothesis] = {}

    def compose(self) -> ComposeResult:
        self.table = DataTable[Text](id="hypotheses-table", cursor_type="row")
        yield Header()
        yield Static("", id="hypotheses-empty", markup=False)
        yield self.table
        yield Footer()

    def on_mount(self) -> None:
        hyps = self.guarded(self._store.query_hypotheses)
        if hyps is None:
            return
        if not hyps:
            self.query_one("#hypotheses-empty", Static).update(
                NO_HYPOTHESES_MESSAGE
            )
            return
        self.table.add_columns("#", "Confidence", "Citations", "Title")
        for hyp in hyps:
            key = str(hyp.hyp_index)
            self._hyps[key] = hyp
            self.table.add_row(
                Text(str(hyp.hyp_index)),
                cell(hyp.confidence),
                Text("ok" if hyp.citations_valid else "FLAGGED"),
                cell(hyp.title),
                key=key,
            )
        self.table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        hyp = self._hyps.get(key)
        if hyp is None:
            return
        self.push(EvidenceScreen(self._store, hyp))
