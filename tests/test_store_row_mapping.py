"""Characterisation pin for the store's row-to-dataclass mapping.

Column order is load-bearing: every read path builds its dataclass from a
positional row, so a reordered SELECT list would populate the wrong fields
with values of the right type and produce a plausible wrong object rather
than an error. These tests round-trip ONE fully-populated row of each
persisted dataclass through the public store API and compare field by field.

Every fixture value is pairwise distinct, and ``_assert_round_trip`` asserts
that distinctness before comparing. Without it the pin would quietly weaken
the moment someone reused a value across two fields of the same type.
"""

from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sift.models import Event, event_id
from sift.store import (
    CaseStore,
    Cluster,
    StoredHypothesis,
    TemplateGroup,
    Verdict,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def _assert_round_trip[T: "DataclassInstance"](expected: T, actual: T) -> None:
    values = [getattr(expected, f.name) for f in fields(expected)]
    assert len({repr(v) for v in values}) == len(values), (
        "fixture values must be pairwise distinct, or two swapped columns "
        "would still compare equal"
    )
    for f in fields(expected):
        assert getattr(actual, f.name) == getattr(expected, f.name), f.name


def _store(tmp_path: Path) -> CaseStore:
    return CaseStore(tmp_path / "case.db")


_EVENT = Event(
    event_id=event_id("dss.log", 4096),
    case_id="case-alpha",
    ts=datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC),
    ts_confidence="exact",
    source="dsserrors",
    source_file="dss.log",
    # Distinct from line_end, and neither is 0 or 1: an int swapped with
    # citations_valid-style booleans would compare equal at those values.
    line_start=41,
    line_end=42,
    severity="error",
    component="component-c",
    thread="thread-t",
    session="session-s",
    message="message-m",
    attrs={"attr-key": "attr-value"},
    raw="raw-r",
)


def test_event_round_trips_field_by_field(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.insert_events([_EVENT])
        (actual,) = store.query_events()
        _assert_round_trip(_EVENT, actual)
    finally:
        store.close()


def test_event_by_id_round_trips_field_by_field(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.insert_events([_EVENT])
        actual = store.get_events_by_ids([_EVENT.event_id])[_EVENT.event_id]
        _assert_round_trip(_EVENT, actual)
    finally:
        store.close()


def test_template_group_round_trips_field_by_field(tmp_path: Path) -> None:
    expected = TemplateGroup(
        template_id="template-id-1",
        template="template-text",
        count=9,
        first_ts="2026-07-16T10:00:00+00:00",
        last_ts="2026-07-16T11:00:00+00:00",
        severity_max="fatal",
        exemplar_event_ids=["exemplar-1", "exemplar-2"],
    )
    store = _store(tmp_path)
    try:
        store.replace_template_groups([expected])
        (actual,) = store.query_template_groups()
        _assert_round_trip(expected, actual)
    finally:
        store.close()


def test_cluster_round_trips_field_by_field(tmp_path: Path) -> None:
    expected = Cluster(
        cluster_id=7,
        label="label-l",
        signature="signature-s",
        severity_max="warn",
        count=5,
        template_ids=["template-1"],
    )
    store = _store(tmp_path)
    try:
        store.replace_clusters([expected])
        (actual,) = store.query_clusters()
        _assert_round_trip(expected, actual)
    finally:
        store.close()


def test_hypothesis_round_trips_field_by_field(tmp_path: Path) -> None:
    expected = StoredHypothesis(
        # Not 0 or 1: citations_valid is a bool, and True == 1 in Python, so a
        # swap between the two would pass equality at those values.
        hyp_index=3,
        title="title-t",
        narrative="narrative-n",
        confidence="medium",
        confidence_reasoning="reasoning-r",
        supporting_event_ids=["event-1"],
        contradicting_evidence="contradicting-c",
        suggested_next_steps=["step-1", "step-2"],
        citations_valid=True,
    )
    store = _store(tmp_path)
    try:
        store.replace_hypotheses([expected])
        (actual,) = store.query_hypotheses()
        _assert_round_trip(expected, actual)
    finally:
        store.close()


def test_verdict_round_trips_field_by_field(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        verdict_id = store.record_verdict(
            target_type="hypothesis",
            target_id="target-1",
            verdict="confirmed",
            note="note-n",
            context={"context-key": "context-value"},
            provenance={"provenance-key": "provenance-value"},
            created_at="2026-07-16T12:00:00+00:00",
        )
        expected = Verdict(
            verdict_id=verdict_id,
            target_type="hypothesis",
            target_id="target-1",
            verdict="confirmed",
            note="note-n",
            context={"context-key": "context-value"},
            provenance={"provenance-key": "provenance-value"},
            created_at="2026-07-16T12:00:00+00:00",
        )
        (actual,) = store.list_verdicts()
        _assert_round_trip(expected, actual)
    finally:
        store.close()
