"""Review-state helper tests: latest-verdict badges and progress counts.

Store-level unit tests only — no Textual, no Pilot. The helpers are pure
functions over the bounded aggregate queries (R008/R014), so everything
here asserts against a real CaseStore in tmp_path, with verdict rows
appended via ``CaseStore.record_verdict`` directly: pinned ``created_at``
values are the only way to prove the newest-first/latest-wins ordering,
and the single-write-path constraint (MEM008) scopes to ``src/sift/tui``,
not tests.
"""

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest

from sift.models import Event
from sift.store import CaseStore, Cluster, StoredHypothesis, TemplateGroup
from sift.tui.review_state import (
    LevelProgress,
    format_progress,
    latest_verdicts,
    review_progress,
)

TID_A = "aaaa1111bbbb2222"
TID_B = "cccc3333dddd4444"

T1 = "2026-07-30T10:00:00+00:00"
T2 = "2026-07-30T11:00:00+00:00"


def _empty_store(tmp_path: Path) -> CaseStore:
    return CaseStore(tmp_path / "case.db")


def _seeded_store(tmp_path: Path) -> CaseStore:
    """Two hypotheses, one cluster, two templates — no events needed."""
    store = _empty_store(tmp_path)
    store.replace_template_groups(
        [
            TemplateGroup(
                template_id=TID_A,
                template="Connection to <IP> refused after <NUM> s",
                count=2,
                first_ts=T1,
                last_ts=T2,
                severity_max="error",
                exemplar_event_ids=[],
            ),
            TemplateGroup(
                template_id=TID_B,
                template="Pool exhausted: <NUM> of <NUM> slots free",
                count=1,
                first_ts=None,
                last_ts=None,
                severity_max="warn",
                exemplar_event_ids=[],
            ),
        ]
    )
    store.replace_clusters(
        [
            Cluster(
                cluster_id=3,
                label=None,
                signature="connection-refused",
                severity_max="error",
                count=2,
                template_ids=[TID_A, TID_B],
            )
        ]
    )
    store.replace_hypotheses(
        [
            StoredHypothesis(
                hyp_index=0,
                title="Network partition",
                narrative="The firewall dropped the pool connections.",
                confidence="high",
                confidence_reasoning="All evidence agrees.",
                supporting_event_ids=[],
                contradicting_evidence=None,
                suggested_next_steps=[],
                citations_valid=True,
            ),
            StoredHypothesis(
                hyp_index=1,
                title="Pool sizing",
                narrative="The pool is simply too small.",
                confidence="low",
                confidence_reasoning="Only one weak signal.",
                supporting_event_ids=[],
                contradicting_evidence=None,
                suggested_next_steps=[],
                citations_valid=True,
            ),
        ]
    )
    return store


def _record(
    store: CaseStore,
    target_type: str,
    target_id: str,
    verdict: str,
    created_at: str,
) -> None:
    store.record_verdict(
        target_type=target_type,
        target_id=target_id,
        verdict=verdict,
        context={},
        provenance={},
        created_at=created_at,
    )


# --- latest_verdicts --------------------------------------------------------


def test_latest_verdicts_empty_store(tmp_path: Path) -> None:
    assert latest_verdicts(_empty_store(tmp_path)) == {}


def test_latest_verdicts_latest_wins_over_history(tmp_path: Path) -> None:
    # Verdicts are append-only: a re-ruling adds a row, and the badge must
    # show the newest one, not the first ever recorded.
    store = _seeded_store(tmp_path)
    _record(store, "hypothesis", "0", "confirmed", T1)
    _record(store, "hypothesis", "0", "rejected", T2)
    assert latest_verdicts(store) == {("hypothesis", "0"): "rejected"}


def test_latest_verdicts_equal_timestamps_use_insertion_order(
    tmp_path: Path,
) -> None:
    # list_verdicts breaks created_at ties by rowid DESC, so the later
    # insertion wins deterministically even with identical stamps.
    store = _seeded_store(tmp_path)
    _record(store, "cluster", "3", "uncertain", T1)
    _record(store, "cluster", "3", "confirmed", T1)
    assert latest_verdicts(store) == {("cluster", "3"): "confirmed"}


def test_latest_verdicts_spans_all_levels(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    _record(store, "hypothesis", "0", "confirmed", T1)
    _record(store, "cluster", "3", "rejected", T1)
    _record(store, "template", TID_A, "uncertain", T1)
    assert latest_verdicts(store) == {
        ("hypothesis", "0"): "confirmed",
        ("cluster", "3"): "rejected",
        ("template", TID_A): "uncertain",
    }


def test_latest_verdicts_target_type_filter_narrows(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    _record(store, "hypothesis", "0", "confirmed", T1)
    _record(store, "template", TID_A, "rejected", T1)
    assert latest_verdicts(store, "template") == {
        ("template", TID_A): "rejected"
    }


def test_latest_verdicts_rejects_unknown_target_type(tmp_path: Path) -> None:
    # Q7: a typo'd level must fail loudly, never silently return {}.
    store = _empty_store(tmp_path)
    with pytest.raises(ValueError, match="unknown verdict target type"):
        latest_verdicts(store, "hypotheses")


# --- review_progress --------------------------------------------------------


def test_review_progress_empty_case(tmp_path: Path) -> None:
    progress = review_progress(_empty_store(tmp_path))
    assert progress.hypotheses == LevelProgress(ruled=0, total=0)
    assert progress.clusters == LevelProgress(ruled=0, total=0)
    assert progress.templates == LevelProgress(ruled=0, total=0)


def test_review_progress_totals_without_verdicts(tmp_path: Path) -> None:
    progress = review_progress(_seeded_store(tmp_path))
    assert progress.hypotheses == LevelProgress(ruled=0, total=2)
    assert progress.clusters == LevelProgress(ruled=0, total=1)
    assert progress.templates == LevelProgress(ruled=0, total=2)


def test_review_progress_counts_each_target_once(tmp_path: Path) -> None:
    # Re-ruling the same hypothesis twice is one ruled target, not two.
    store = _seeded_store(tmp_path)
    _record(store, "hypothesis", "0", "confirmed", T1)
    _record(store, "hypothesis", "0", "rejected", T2)
    _record(store, "template", TID_B, "uncertain", T1)
    progress = review_progress(store)
    assert progress.hypotheses == LevelProgress(ruled=1, total=2)
    assert progress.clusters == LevelProgress(ruled=0, total=1)
    assert progress.templates == LevelProgress(ruled=1, total=2)


def test_review_progress_ignores_stale_targets(tmp_path: Path) -> None:
    # Q7: verdicts whose targets vanished under external re-analysis are
    # history, not progress — ruled never exceeds total.
    store = _seeded_store(tmp_path)
    _record(store, "hypothesis", "99", "confirmed", T1)
    _record(store, "cluster", "42", "rejected", T1)
    _record(store, "template", "feedfacefeedface", "uncertain", T1)
    progress = review_progress(store)
    assert progress.hypotheses == LevelProgress(ruled=0, total=2)
    assert progress.clusters == LevelProgress(ruled=0, total=1)
    assert progress.templates == LevelProgress(ruled=0, total=2)


class _EventReadGuard(CaseStore):
    """Fails the test on ANY events-table read path (R008 structural proof)."""

    def query_events(
        self, sources: Sequence[str] | None = None
    ) -> list[Event]:
        raise AssertionError("review_state must never read the events table")

    def get_events_by_ids(self, ids: Sequence[str]) -> dict[str, Event]:
        raise AssertionError("review_state must never read the events table")

    def iter_event_rows(
        self, filters: Mapping[str, str | int] | None = None
    ) -> Iterator[tuple[str, str | None, str, str, int, str]]:
        raise AssertionError("review_state must never read the events table")


def test_helpers_never_touch_the_events_table(tmp_path: Path) -> None:
    # R008: badges and counts read bounded aggregates only. A guard store
    # that explodes on every events read proves it structurally.
    store = _EventReadGuard(tmp_path / "case.db")
    _record(store, "hypothesis", "0", "confirmed", T1)
    assert latest_verdicts(store) == {("hypothesis", "0"): "confirmed"}
    progress = review_progress(store)
    assert progress.hypotheses == LevelProgress(ruled=0, total=0)


# --- format_progress --------------------------------------------------------


def test_format_progress_line(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    _record(store, "hypothesis", "1", "confirmed", T1)
    _record(store, "template", TID_A, "rejected", T1)
    _record(store, "template", TID_B, "uncertain", T1)
    line = format_progress(review_progress(store))
    assert line == (
        "Reviewed 1/2 hypotheses · 0/1 clusters · 2/2 templates"
    )
