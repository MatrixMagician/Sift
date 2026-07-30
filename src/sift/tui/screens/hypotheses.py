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

As the landing screen it also carries the review-progress line (R014,
ruled-vs-total per level) and a Verdict badge column. Both repaint only
from the modal-dismissal callback carrying a :class:`RecordedVerdict` or
from DB re-reads on mount/resume (R012) — resume matters because
EvidenceScreen rules on the very hypotheses this table shows.
"""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import DataTable, Footer, Header, Static
from textual.widgets.data_table import ColumnKey

from sift.store import CaseStore, StoredHypothesis
from sift.tui.review_state import (
    format_progress,
    latest_verdicts,
    review_progress,
)
from sift.tui.screens.base import CaseScreen
from sift.tui.screens.evidence import EvidenceScreen, cell
from sift.verdicts import RecordedVerdict, TargetSpec

# Shown when analyze ran but persisted zero schema-valid hypotheses
# (mirrors the `sift show hypotheses` degraded-run wording).
NO_HYPOTHESES_MESSAGE = (
    "No schema-valid hypotheses; the last analyze may have degraded.\n"
    "Run 'sift report' to view the DEGRADED banner and raw output."
)


class HypothesesScreen(CaseScreen):
    """Ranked hypotheses; enter opens the cited-evidence drill-down."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "verdict", "Record verdict"),
    ]

    DEFAULT_CSS = """
    HypothesesScreen #hypotheses-empty {
        padding: 0 1;
    }
    HypothesesScreen #hypotheses-progress {
        padding: 0 1;
    }
    """

    table: DataTable[Text]

    def __init__(self, store: CaseStore) -> None:
        super().__init__()
        self._store = store
        self._hyps: dict[str, StoredHypothesis] = {}
        self._verdict_col: ColumnKey | None = None
        # False until the mount-time read succeeds: a dead store already
        # pushed one ErrorScreen from on_mount, so resume repaints stay
        # inert instead of stacking a second one.
        self._ready = False

    def compose(self) -> ComposeResult:
        self.table = DataTable[Text](id="hypotheses-table", cursor_type="row")
        yield Header()
        yield Static("", id="hypotheses-progress", markup=False)
        yield Static("", id="hypotheses-empty", markup=False)
        yield self.table
        yield Footer()

    def on_mount(self) -> None:
        hyps = self.guarded(self._store.query_hypotheses)
        if hyps is None:
            return
        self._ready = True
        if not hyps:
            self.query_one("#hypotheses-empty", Static).update(
                NO_HYPOTHESES_MESSAGE
            )
            return
        columns = self.table.add_columns(
            "#", "Confidence", "Citations", "Title", "Verdict"
        )
        self._verdict_col = columns[-1]
        for hyp in hyps:
            key = str(hyp.hyp_index)
            self._hyps[key] = hyp
            self.table.add_row(
                Text(str(hyp.hyp_index)),
                cell(hyp.confidence),
                Text("ok" if hyp.citations_valid else "FLAGGED"),
                cell(hyp.title),
                Text(""),
                key=key,
            )
        self.table.focus()

    def on_screen_resume(self) -> None:
        """DB re-read whenever this screen surfaces (R012's second source).

        Fires on the initial push and every return — a deeper screen may
        have ruled on these same rows (EvidenceScreen rules hypotheses,
        ClustersScreen commits count towards the progress line).
        """
        if not self._ready:
            return
        self._refresh_progress()
        self._refresh_badges()

    def _refresh_progress(self) -> None:
        progress = self.guarded(lambda: review_progress(self._store))
        if progress is None:
            return
        self.query_one("#hypotheses-progress", Static).update(
            format_progress(progress)
        )

    def _refresh_badges(self) -> None:
        if self._verdict_col is None:
            return
        badges = self.guarded(
            lambda: latest_verdicts(self._store, "hypothesis")
        )
        if badges is None:
            return
        for key in self._hyps:
            self.table.update_cell(
                key,
                self._verdict_col,
                Text(badges.get(("hypothesis", key), "")),
            )

    def action_verdict(self) -> None:
        """v: capture a verdict for the highlighted hypothesis (R003)."""
        if self.table.row_count == 0:
            return
        key = self.table.coordinate_to_cell_key(
            self.table.cursor_coordinate
        ).row_key.value
        if key is None:
            return
        hyp = self._hyps.get(key)
        if hyp is None:
            return
        self.capture_verdict(
            self._store,
            TargetSpec("hypothesis", key),
            hyp.title,
            self._paint_recorded,
        )

    def _paint_recorded(self, recorded: RecordedVerdict) -> None:
        """The R012 commit gate: paint exactly what the INSERT returned."""
        if self._verdict_col is not None:
            self.table.update_cell(
                recorded.target_id, self._verdict_col, Text(recorded.verdict)
            )
        self._refresh_progress()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        hyp = self._hyps.get(key)
        if hyp is None:
            return
        self.push(EvidenceScreen(self._store, hyp))
