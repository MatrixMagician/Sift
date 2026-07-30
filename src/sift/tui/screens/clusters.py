"""Cluster browser (R002): semantic clusters and their member templates.

Two screens cover the roam-beyond-the-hypothesis-chain requirement's
cluster half:

* :class:`ClustersScreen` — every persisted cluster, count DESC then
  cluster_id ASC (the store's canonical order, matching ``sift show
  clusters``). Both cluster and template tables are bounded aggregates
  orders of magnitude smaller than events, so they stay on the store's
  list-returning APIs — the R008 paging contract applies to events only
  (see ``data_access``). A cluster shows its LLM label when one exists,
  else its signature (D-01).
* :class:`ClusterDetailScreen` — one cluster's member template groups (the
  member-template expansion). A ``template_ids`` entry the store does not
  hold is shown as such rather than dropped — a tampered case.db is
  surfaced as evidence, never an error — and selecting such a row is a
  no-op, mirroring the cited-but-absent contract on the evidence screen.

Every DB-sourced string (labels are model-generated, signatures and
templates carry raw log bytes) is sanitised and rendered markup-inert
(WR-01, T-04-01) via the shared ``cell`` helper / ``markup=False``.
"""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import DataTable, Footer, Header, Static
from textual.widgets.data_table import ColumnKey

from sift.render._util import sanitise
from sift.store import CaseStore, Cluster
from sift.tui.review_state import latest_verdicts
from sift.tui.screens.base import CaseScreen
from sift.tui.screens.evidence import cell
from sift.verdicts import RecordedVerdict, TargetSpec

# What the member-templates table shows for a template_id the store does
# not hold (the evidence screen's cited-but-absent idiom).
MISSING_TEMPLATE_LABEL = "not in case store"

# Shown when the case is analysed but the clusters table is empty.
NO_CLUSTERS_MESSAGE = (
    "No semantic clusters stored for this case.\n"
    "Run 'sift analyze' to build clusters."
)


def _first_line(text: str) -> str:
    """A template's first line — multi-line templates stay one table row."""
    return text.splitlines()[0] if text else ""


class ClustersScreen(CaseScreen):
    """Semantic clusters ranked by size; enter expands member templates."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "verdict", "Record verdict"),
    ]

    DEFAULT_CSS = """
    ClustersScreen #clusters-empty {
        padding: 0 1;
    }
    """

    table: DataTable[Text]

    def __init__(self, store: CaseStore) -> None:
        super().__init__()
        self._store = store
        self._clusters: dict[str, Cluster] = {}
        self._verdict_col: ColumnKey | None = None
        # False until the mount-time read succeeds (see HypothesesScreen).
        self._ready = False

    def compose(self) -> ComposeResult:
        self.table = DataTable[Text](id="clusters-table", cursor_type="row")
        yield Header()
        yield Static("", id="clusters-empty", markup=False)
        yield self.table
        yield Footer()

    def on_mount(self) -> None:
        clusters = self.guarded(self._store.query_clusters)
        if clusters is None:
            return
        self._ready = True
        if not clusters:
            self.query_one("#clusters-empty", Static).update(
                NO_CLUSTERS_MESSAGE
            )
            return
        columns = self.table.add_columns(
            "Cluster", "Severity", "Events", "Templates", "Label", "Verdict"
        )
        self._verdict_col = columns[-1]
        for cluster in clusters:
            key = str(cluster.cluster_id)
            self._clusters[key] = cluster
            self.table.add_row(
                Text(str(cluster.cluster_id)),
                cell(cluster.severity_max),
                Text(str(cluster.count)),
                Text(str(len(cluster.template_ids))),
                cell(cluster.label or cluster.signature),
                Text(""),
                key=key,
            )
        self.table.focus()

    def on_screen_resume(self) -> None:
        """DB re-read of cluster rulings on surface/return (R012)."""
        if not self._ready or self._verdict_col is None:
            return
        badges = self.guarded(lambda: latest_verdicts(self._store, "cluster"))
        if badges is None:
            return
        for key in self._clusters:
            self.table.update_cell(
                key,
                self._verdict_col,
                Text(badges.get(("cluster", key), "")),
            )

    def action_verdict(self) -> None:
        """v: capture a verdict for the highlighted cluster (R003)."""
        if self.table.row_count == 0:
            return
        key = self.table.coordinate_to_cell_key(
            self.table.cursor_coordinate
        ).row_key.value
        if key is None:
            return
        cluster = self._clusters.get(key)
        if cluster is None:
            return
        self.capture_verdict(
            self._store,
            TargetSpec("cluster", key),
            cluster.label or cluster.signature,
            self._paint_recorded,
        )

    def _paint_recorded(self, recorded: RecordedVerdict) -> None:
        """The R012 commit gate: paint exactly what the INSERT returned."""
        if self._verdict_col is not None:
            self.table.update_cell(
                recorded.target_id, self._verdict_col, Text(recorded.verdict)
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        cluster = self._clusters.get(key)
        if cluster is None:
            return
        self.push(ClusterDetailScreen(self._store, cluster))


class ClusterDetailScreen(CaseScreen):
    """One cluster's member template groups (the R002 expansion)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "verdict", "Record verdict"),
    ]

    DEFAULT_CSS = """
    ClusterDetailScreen #cluster-title {
        text-style: bold;
        padding: 0 1;
    }
    ClusterDetailScreen #cluster-summary {
        padding: 0 1;
    }
    """

    table: DataTable[Text]

    def __init__(self, store: CaseStore, cluster: Cluster) -> None:
        super().__init__()
        self._store = store
        self._cluster = cluster
        # Labels for member ids the store actually holds — a MISSING row is
        # absent here, which is what makes it verdict-inert (Q7).
        self._labels: dict[str, str] = {}
        self._member_ids: list[str] = []
        self._verdict_col: ColumnKey | None = None
        # False until the mount-time read succeeds (see HypothesesScreen).
        self._ready = False

    def compose(self) -> ComposeResult:
        cluster = self._cluster
        self.table = DataTable[Text](
            id="cluster-members-table", cursor_type="row"
        )
        yield Header()
        yield Static(
            sanitise(
                f"Cluster {cluster.cluster_id}: "
                f"{cluster.label or cluster.signature}"
            ),
            id="cluster-title",
            markup=False,
        )
        yield Static(
            sanitise(
                f"Severity {cluster.severity_max} · {cluster.count} events · "
                f"{len(cluster.template_ids)} templates"
            ),
            id="cluster-summary",
            markup=False,
        )
        yield Static("Member templates:", id="cluster-members-label")
        yield self.table
        yield Footer()

    def on_mount(self) -> None:
        groups = self.guarded(self._store.query_template_groups)
        if groups is None:
            return
        self._ready = True
        by_id = {g.template_id: g for g in groups}
        # Dedupe while preserving order: a tampered case.db can repeat a
        # template id, and a duplicate would collide as a table row key.
        self._member_ids = list(dict.fromkeys(self._cluster.template_ids))
        columns = self.table.add_columns(
            "Template", "Count", "Severity", "First", "Last", "Text", "Verdict"
        )
        self._verdict_col = columns[-1]
        for tid in self._member_ids:
            group = by_id.get(tid)
            if group is None:
                self.table.add_row(
                    cell(tid),
                    Text("—"),
                    Text("—"),
                    Text("—"),
                    Text("—"),
                    Text(MISSING_TEMPLATE_LABEL),
                    Text(""),
                    key=tid,
                )
                continue
            self._labels[tid] = _first_line(group.template)
            self.table.add_row(
                cell(tid),
                Text(str(group.count)),
                cell(group.severity_max),
                cell(group.first_ts or "—"),
                cell(group.last_ts or "—"),
                cell(_first_line(group.template)),
                Text(""),
                key=tid,
            )
        self.table.focus()

    def on_screen_resume(self) -> None:
        """DB re-read of template rulings on surface/return (R012)."""
        if not self._ready or self._verdict_col is None:
            return
        badges = self.guarded(
            lambda: latest_verdicts(self._store, "template")
        )
        if badges is None:
            return
        for tid in self._member_ids:
            self.table.update_cell(
                tid,
                self._verdict_col,
                Text(badges.get(("template", tid), "")),
            )

    def action_verdict(self) -> None:
        """v: capture a verdict for the highlighted member template (R003).

        A MISSING row (a template id the store does not hold) is
        verdict-inert: there is nothing in this case to rule on (Q7).
        """
        if self.table.row_count == 0:
            return
        key = self.table.coordinate_to_cell_key(
            self.table.cursor_coordinate
        ).row_key.value
        if key is None or key not in self._labels:
            return
        self.capture_verdict(
            self._store,
            TargetSpec("template", key),
            self._labels[key],
            self._paint_recorded,
        )

    def _paint_recorded(self, recorded: RecordedVerdict) -> None:
        """The R012 commit gate: paint exactly what the INSERT returned."""
        if self._verdict_col is not None:
            self.table.update_cell(
                recorded.target_id, self._verdict_col, Text(recorded.verdict)
            )
