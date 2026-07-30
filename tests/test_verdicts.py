"""Shared verdict service tests: target parsing, snapshots, provenance."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.store import CaseStore, Cluster, StoredHypothesis, TemplateGroup
from sift.verdicts import (
    TargetSpec,
    TargetSpecError,
    UnknownTargetError,
    parse_target,
    record_validation,
)

# Two messages sharing one masked template, one with a different shape.
MSG_A1 = "Connection to 10.0.0.5 refused after 30 s"
MSG_A2 = "Connection to 10.9.9.9 refused after 45 s"
MSG_B = "Pool exhausted: 0 of 64 slots free"

TMPL_A = dedup.mask(MSG_A1)
TMPL_B = dedup.mask(MSG_B)
TID_A = dedup.template_id(TMPL_A)
TID_B = dedup.template_id(TMPL_B)


def _ev(source_file: str, offset: int, message: str) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id="demo",
        ts=datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC),
        ts_confidence="exact",
        source="genericlog",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="error",
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw=message,
    )


E1 = _ev("a.log", 0, MSG_A1)
E2 = _ev("a.log", 100, MSG_A2)
E3 = _ev("b.log", 0, MSG_B)


def _seeded_store(tmp_path: Path) -> CaseStore:
    """A case with events, template groups, one cluster, one hypothesis."""
    store = CaseStore(tmp_path / "case.db")
    store.insert_events([E1, E2, E3])
    store.replace_template_groups(
        [
            TemplateGroup(
                template_id=TID_A,
                template=TMPL_A,
                count=2,
                first_ts="2026-07-16T10:00:00+00:00",
                last_ts="2026-07-16T10:05:00+00:00",
                severity_max="error",
                exemplar_event_ids=[E1.event_id],
            ),
            TemplateGroup(
                template_id=TID_B,
                template=TMPL_B,
                count=1,
                first_ts=None,
                last_ts=None,
                severity_max="warn",
                exemplar_event_ids=[E3.event_id],
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
                supporting_event_ids=[E1.event_id, E2.event_id, E3.event_id],
                contradicting_evidence=None,
                suggested_next_steps=["Check firewall rules"],
                citations_valid=True,
            )
        ]
    )
    store.set_meta("triage_model", "qwen3:32b")
    store.set_meta("triage_prompt_hash", "abc123")
    store.set_meta("triage_created_at", "2026-07-30T10:00:00+00:00")
    store.set_meta("mask_version", str(dedup.MASK_VERSION))
    return store


# --- parse_target -----------------------------------------------------------


def test_parse_target_happy_paths() -> None:
    assert parse_target("hypothesis:0") == TargetSpec("hypothesis", "0")
    assert parse_target("cluster:3") == TargetSpec("cluster", "3")
    assert parse_target(f"template:{TID_A}") == TargetSpec("template", TID_A)


def test_parse_target_normalises_numeric_ids() -> None:
    # Leading zeros and outer whitespace normalise to the canonical decimal
    # spelling so stored target_id values always filter/compare cleanly.
    assert parse_target("hypothesis:007") == TargetSpec("hypothesis", "7")
    assert parse_target("  cluster:03  ") == TargetSpec("cluster", "3")


@pytest.mark.parametrize(
    "spec",
    [
        "0",  # no colon
        "hypothesis:",  # missing id
        ":0",  # missing type
        "hyp:0",  # unknown type
        "hypothesis:abc",  # non-numeric hypothesis id
        "cluster:x2",  # non-numeric cluster id
        "hypothesis:-1",  # negative index
        "",
    ],
)
def test_parse_target_malformed(spec: str) -> None:
    with pytest.raises(TargetSpecError):
        parse_target(spec)


def test_parse_target_error_names_valid_types() -> None:
    with pytest.raises(TargetSpecError, match="cluster, hypothesis, template"):
        parse_target("hyp:0")


# --- record_validation: snapshots and provenance ----------------------------


def test_record_validation_hypothesis_snapshot(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    recorded = record_validation(
        store, "hypothesis:0", "confirmed", note="Root cause confirmed"
    )
    assert recorded.target_type == "hypothesis"
    assert recorded.target_id == "0"
    assert recorded.verdict == "confirmed"

    (row,) = store.list_verdicts()
    assert row.verdict_id == recorded.verdict_id
    assert row.note == "Root cause confirmed"
    assert row.context["title"] == "Network partition"
    assert row.context["narrative"] == "The firewall dropped the pool connections."
    assert row.context["confidence"] == "high"
    assert row.context["citations_valid"] is True
    assert row.context["supporting_event_ids"] == [
        E1.event_id,
        E2.event_id,
        E3.event_id,
    ]
    # E1/E2 share one masked shape; order is first-seen, deduplicated.
    assert row.context["evidence_templates"] == [TMPL_A, TMPL_B]
    assert row.context["sources"] == ["a.log", "b.log"]


def test_record_validation_provenance(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    recorded = record_validation(store, "hypothesis:0", "uncertain")
    (row,) = store.list_verdicts()
    assert row.provenance["model"] == "qwen3:32b"
    assert row.provenance["prompt_hash"] == "abc123"
    assert row.provenance["triage_created_at"] == "2026-07-30T10:00:00+00:00"
    assert row.provenance["mask_version"] == str(dedup.MASK_VERSION)
    # The row stamp and the snapshot's recorded_at are the same instant.
    assert row.provenance["recorded_at"] == row.created_at == recorded.created_at
    parsed = datetime.fromisoformat(row.created_at)
    assert parsed.tzinfo is not None


def test_record_validation_cluster_snapshot(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    record_validation(store, "cluster:3", "rejected")
    (row,) = store.list_verdicts()
    assert row.target_type == "cluster"
    assert row.target_id == "3"
    assert row.context["cluster_id"] == 3
    assert row.context["label"] is None
    assert row.context["signature"] == "connection-refused"
    assert row.context["severity_max"] == "error"
    assert row.context["template_ids"] == [TID_A, TID_B]
    # Member template shapes are snapshotted so M002 never needs the case.
    assert row.context["templates"] == [TMPL_A, TMPL_B]


def test_record_validation_template_snapshot(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    record_validation(store, f"template:{TID_A}", "confirmed")
    (row,) = store.list_verdicts()
    assert row.target_type == "template"
    assert row.target_id == TID_A
    assert row.context["template"] == TMPL_A
    assert row.context["count"] == 2
    assert row.context["severity_max"] == "error"
    assert row.context["exemplar_event_ids"] == [E1.event_id]


def test_record_validation_accepts_parsed_spec(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    recorded = record_validation(
        store, TargetSpec("template", TID_B), "uncertain", note="odd shape"
    )
    (row,) = store.list_verdicts()
    assert row.verdict_id == recorded.verdict_id
    assert row.context["template"] == TMPL_B


# --- record_validation: failure paths ---------------------------------------


@pytest.mark.parametrize(
    "spec",
    ["hypothesis:99", "cluster:99", "template:deadbeefdeadbeef"],
)
def test_record_validation_unknown_target(tmp_path: Path, spec: str) -> None:
    store = _seeded_store(tmp_path)
    with pytest.raises(UnknownTargetError, match=spec.partition(":")[2]):
        record_validation(store, spec, "confirmed")
    assert store.list_verdicts() == []


def test_record_validation_rejects_bogus_spec_object(tmp_path: Path) -> None:
    # A TargetSpec built by hand (the TUI path) with a bad type must fail
    # the same way a malformed string spec does — before any DB read.
    store = _seeded_store(tmp_path)
    with pytest.raises(TargetSpecError):
        record_validation(store, TargetSpec("bogus", "1"), "confirmed")
    assert store.list_verdicts() == []


def test_record_validation_unknown_state(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    with pytest.raises(ValueError, match="confirmed, rejected, uncertain"):
        record_validation(store, "hypothesis:0", "maybe")
    assert store.list_verdicts() == []


def test_record_validation_without_analysis_meta(tmp_path: Path) -> None:
    # Template verdicts are legal before any analyze run: provenance keys are
    # present with null values rather than being silently dropped.
    store = CaseStore(tmp_path / "case.db")
    store.replace_template_groups(
        [
            TemplateGroup(
                template_id=TID_A,
                template=TMPL_A,
                count=1,
                first_ts=None,
                last_ts=None,
                severity_max="error",
                exemplar_event_ids=[],
            )
        ]
    )
    record_validation(store, f"template:{TID_A}", "confirmed")
    (row,) = store.list_verdicts()
    assert row.provenance["model"] is None
    assert row.provenance["prompt_hash"] is None
    assert row.provenance["triage_created_at"] is None


def test_record_validation_missing_supporting_events(tmp_path: Path) -> None:
    # A hypothesis citing an id absent from the events table (invalid citation
    # flagged upstream): the snapshot keeps the full cited list so the gap
    # stays auditable, while templates/sources cover only resolvable events.
    store = _seeded_store(tmp_path)
    ghost = "f" * 16
    store.replace_hypotheses(
        [
            StoredHypothesis(
                hyp_index=0,
                title="Ghost citation",
                narrative="n",
                confidence="low",
                confidence_reasoning="r",
                supporting_event_ids=[ghost, E3.event_id],
                contradicting_evidence=None,
                suggested_next_steps=[],
                citations_valid=False,
            )
        ]
    )
    record_validation(store, "hypothesis:0", "rejected")
    (row,) = store.list_verdicts()
    assert row.context["supporting_event_ids"] == [ghost, E3.event_id]
    assert row.context["evidence_templates"] == [TMPL_B]
    assert row.context["sources"] == ["b.log"]
    assert row.context["citations_valid"] is False


def test_record_validation_note_defaults_empty(tmp_path: Path) -> None:
    store = _seeded_store(tmp_path)
    record_validation(store, "cluster:3", "confirmed")
    (row,) = store.list_verdicts()
    assert row.note == ""
