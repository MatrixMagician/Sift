"""Evidence drill-down (R001): hypothesis → cited events → raw source.

Two screens cover the inner two hops of the primary review loop:

* :class:`EvidenceScreen` — one hypothesis in full (narrative, confidence
  reasoning, contradicting evidence, next steps) above the table of events
  it cites. Cited ids are hydrated through ``CaseStore.get_events_by_ids``
  — exactly the drill-down boundary T01 deferred raw hydration to — and an
  id the store does not hold is shown as such rather than dropped: a
  cited-but-absent id is evidence of a hallucinated citation, and nothing
  disappears silently. Selecting such a row is a no-op (there is no raw
  source to show).
* :class:`RawSourceScreen` — the verbatim stored ``raw`` text one citation
  points at, headed by its source_file:line provenance. Built purely from
  the already-hydrated ``Event``, so it performs no store reads at all.

Every DB-sourced string is sanitised and rendered markup-inert (WR-01,
T-04-01): hostile log bytes drive neither the terminal nor Textual's
markup parser — table cells are ``rich.text.Text`` (never markup-parsed
str) and Statics set ``markup=False``.
"""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static

from sift.models import Event
from sift.render._util import sanitise
from sift.store import CaseStore, StoredHypothesis
from sift.tui.review_state import latest_verdicts
from sift.tui.screens.base import CaseScreen
from sift.verdicts import RecordedVerdict, TargetSpec

# What the cited-events table shows for an id the store does not hold.
MISSING_EVENT_LABEL = "not in case store"


def cell(text: str) -> Text:
    """A sanitised, markup-inert table cell (WR-01, T-04-01)."""
    return Text(sanitise(text))


def _first_line(text: str) -> str:
    """A message's first line — multi-line records stay one table row."""
    return text.splitlines()[0] if text else ""


class EvidenceScreen(CaseScreen):
    """One hypothesis in full, above the table of events it cites."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "verdict", "Record verdict"),
    ]

    DEFAULT_CSS = """
    EvidenceScreen #evidence-detail {
        height: auto;
        max-height: 50%;
        padding: 0 1;
    }
    EvidenceScreen #evidence-title {
        text-style: bold;
    }
    """

    table: DataTable[Text]

    def __init__(self, store: CaseStore, hypothesis: StoredHypothesis) -> None:
        super().__init__()
        self._store = store
        self._hyp = hypothesis
        self._events: dict[str, Event] = {}
        # False until the mount-time read succeeds (see HypothesesScreen).
        self._ready = False

    def compose(self) -> ComposeResult:
        hyp = self._hyp
        self.table = DataTable[Text](id="evidence-table", cursor_type="row")
        yield Header()
        with VerticalScroll(id="evidence-detail"):
            yield Static(
                sanitise(f"#{hyp.hyp_index}  {hyp.title}"),
                id="evidence-title",
                markup=False,
            )
            confidence = (
                f"Confidence: {hyp.confidence} — {hyp.confidence_reasoning}"
            )
            if not hyp.citations_valid:
                confidence += (
                    "\nFLAGGED: citations failed validation; treat with care"
                )
            yield Static(
                sanitise(confidence), id="evidence-confidence", markup=False
            )
            yield Static("", id="evidence-verdict", markup=False)
            yield Static(
                sanitise(hyp.narrative), id="evidence-narrative", markup=False
            )
            if hyp.contradicting_evidence:
                yield Static(
                    sanitise(f"Contradicting: {hyp.contradicting_evidence}"),
                    id="evidence-contradicting",
                    markup=False,
                )
            if hyp.suggested_next_steps:
                steps = "\n".join(f"- {s}" for s in hyp.suggested_next_steps)
                yield Static(
                    sanitise(f"Next steps:\n{steps}"),
                    id="evidence-steps",
                    markup=False,
                )
        yield Static(
            "Cited events (enter opens the raw source):",
            id="evidence-cited-label",
        )
        yield self.table
        yield Footer()

    def on_mount(self) -> None:
        # Dedupe while preserving citation order: a tampered case.db can
        # repeat an id, and a duplicate would collide as a table row key.
        cited = list(dict.fromkeys(self._hyp.supporting_event_ids))
        events = self.guarded(lambda: self._store.get_events_by_ids(cited))
        if events is None:
            return
        self._ready = True
        self._events = events
        self.table.add_columns("Event", "Timestamp", "Severity", "Where", "Message")
        for eid in cited:
            ev = events.get(eid)
            if ev is None:
                self.table.add_row(
                    cell(eid),
                    Text("—"),
                    Text("—"),
                    Text("—"),
                    Text(MISSING_EVENT_LABEL),
                    key=eid,
                )
                continue
            self.table.add_row(
                cell(eid),
                Text(ev.ts.isoformat() if ev.ts else "—"),
                cell(ev.severity),
                cell(f"{ev.source_file}:{ev.line_start}"),
                cell(_first_line(ev.message)),
                key=eid,
            )
        self.table.focus()

    def on_screen_resume(self) -> None:
        """DB re-read of this hypothesis's latest ruling on surface/return."""
        if not self._ready:
            return
        badges = self.guarded(
            lambda: latest_verdicts(self._store, "hypothesis")
        )
        if badges is None:
            return
        self._show_verdict(
            badges.get(("hypothesis", str(self._hyp.hyp_index)))
        )

    def _show_verdict(self, verdict: str | None) -> None:
        # Verdict states come from the store's allowlisted vocabulary, so
        # the line is safe text; empty means not yet ruled on.
        self.query_one("#evidence-verdict", Static).update(
            f"Verdict: {verdict}" if verdict else ""
        )

    def action_verdict(self) -> None:
        """v: capture a verdict for THIS hypothesis (R003) — the screen is
        one hypothesis in full, so the target is unambiguous."""
        self.capture_verdict(
            self._store,
            TargetSpec("hypothesis", str(self._hyp.hyp_index)),
            self._hyp.title,
            self._paint_recorded,
        )

    def _paint_recorded(self, recorded: RecordedVerdict) -> None:
        """The R012 commit gate: show exactly what the INSERT returned."""
        self._show_verdict(recorded.verdict)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        ev = self._events.get(key)
        if ev is None:
            # Cited-but-absent: nothing stored to show, deliberately inert.
            return
        self.push(RawSourceScreen(ev))


class RawSourceScreen(CaseScreen):
    """The verbatim stored source text one citation points at (R001)."""

    DEFAULT_CSS = """
    RawSourceScreen #raw-context {
        text-style: bold;
        padding: 0 1;
    }
    RawSourceScreen #raw-body {
        padding: 0 1;
    }
    """

    def __init__(self, event: Event) -> None:
        super().__init__()
        self._event = event

    def compose(self) -> ComposeResult:
        ev = self._event
        lines = (
            f"{ev.line_start}"
            if ev.line_end == ev.line_start
            else f"{ev.line_start}-{ev.line_end}"
        )
        context = (
            f"{ev.source_file}:{lines}\n"
            f"Event {ev.event_id} · source {ev.source} · severity {ev.severity}"
        )
        if ev.ts is not None:
            context += f" · {ev.ts.isoformat()}"
        yield Header()
        yield Static(sanitise(context), id="raw-context", markup=False)
        with VerticalScroll(id="raw-body"):
            yield Static(sanitise(ev.raw), id="raw-text", markup=False)
        yield Footer()
