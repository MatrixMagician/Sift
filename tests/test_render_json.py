"""JSON report shape + canonical-serialisation tests (REPT-02).

The renderer is a pure function of an analysed ``case.db`` (no inference), so
these run network-free under the autouse ``_no_network`` guard: the analysed
case is built via the ``MockTransport`` fake server in ``_report_fixtures``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from _report_fixtures import (
    PROMPT_HASH,
    TIMELINE_SUMMARY,
    TRIAGE_MODEL,
    UNEXPLAINED,
    build_analysed_case,
    open_case,
)

from sift.render.json_out import render_json

if TYPE_CHECKING:
    import pytest

_HYP_FIELDS = (
    "hyp_index",
    "title",
    "narrative",
    "confidence",
    "confidence_reasoning",
    "supporting_event_ids",
    "contradicting_evidence",
    "suggested_next_steps",
    "citations_valid",
)
_CLUSTER_FIELDS = ("cluster_id", "label", "signature", "severity_max", "count")
_RUN_FIELDS = ("model", "prompt_hash", "embedding_model", "degraded", "generated_at")


def test_render_json_carries_full_document(monkeypatch: pytest.MonkeyPatch) -> None:
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        raw = render_json(store)
    finally:
        store.close()

    doc: dict[str, object] = json.loads(raw)

    hyps = cast("list[dict[str, object]]", doc["hypotheses"])
    assert hyps
    for h in hyps:
        for field in _HYP_FIELDS:
            assert field in h, f"hypothesis missing {field}"
    assert isinstance(hyps[0]["citations_valid"], bool)

    clusters = cast("list[dict[str, object]]", doc["clusters"])
    assert clusters
    for c in clusters:
        for field in _CLUSTER_FIELDS:
            assert field in c, f"cluster missing {field}"

    assert doc["timeline_summary"] == TIMELINE_SUMMARY
    assert doc["unexplained_signals"] == UNEXPLAINED
    assert isinstance(doc["unexplained_signals"], list)

    run = cast("dict[str, object]", doc["run"])
    for field in _RUN_FIELDS:
        assert field in run, f"run block missing {field}"
    assert run["model"] == TRIAGE_MODEL
    assert run["prompt_hash"] == PROMPT_HASH
    assert run["degraded"] is False
    assert run["generated_at"] == "2026-07-17T09:10:00+00:00"


def test_render_json_is_key_sorted_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    """The emitted string equals a re-dump with sort_keys=True (Pattern 3)."""
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        raw = render_json(store)
    finally:
        store.close()

    doc = json.loads(raw)
    assert raw == json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    assert raw.endswith("\n")


def test_render_json_degraded_run_flags_row(monkeypatch: pytest.MonkeyPatch) -> None:
    case = build_analysed_case(monkeypatch, case="deg", degraded=True)
    store = open_case(case)
    try:
        doc = json.loads(render_json(store))
    finally:
        store.close()

    assert doc["run"]["degraded"] is True
    flagged = [h for h in doc["hypotheses"] if h["citations_valid"] is False]
    assert flagged, "a degraded run must surface the persisted FLAGGED verdict"
