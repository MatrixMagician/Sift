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
_VERDICT_FIELDS = (
    "verdict_id",
    "target_type",
    "target_id",
    "verdict",
    "note",
    "context",
    "provenance",
    "created_at",
)


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
    assert raw == json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"
    assert raw.endswith("\n")


def test_render_json_escapes_c1_and_bidi_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """IN-02: the JSON report must not emit raw C1 controls or bidi/format
    characters (terminal-injection), while preserving round-trip fidelity."""
    # U+009B single-byte CSI (C1) and U+202E right-to-left override (bidi),
    # built from escapes so no raw hazardous byte lands in this source file.
    csi = "\u009b"
    rlo = "\u202e"
    hostile = f"watermark {csi}31m {rlo} overrides"
    case = build_analysed_case(monkeypatch, case="c1bidi")
    store = open_case(case)
    try:
        with store.transaction():
            store.set_meta("triage_timeline_summary", hostile)
        raw = render_json(store)
    finally:
        store.close()

    # The raw hazardous code points never appear literally in the emitted text.
    assert csi not in raw
    assert rlo not in raw
    # They are backslash-u escaped instead (terminal-safe).
    assert "\\u009b" in raw
    assert "\\u202e" in raw
    # A JSON parser round-trips them back verbatim (fidelity preserved).
    assert json.loads(raw)["timeline_summary"] == hostile


def test_render_json_verdicts_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    # R007: a case with no recorded verdicts still carries the key, as an
    # empty list — consumers never need a key-existence probe.
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        doc = json.loads(render_json(store))
    finally:
        store.close()
    assert doc["verdicts"] == []


def test_render_json_verdicts_all_fields_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The full append-only history rides along, newest first (list_verdicts
    # order), each row carrying all eight Verdict fields verbatim.
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        with store.transaction():
            store.record_verdict(
                target_type="hypothesis",
                target_id="0",
                verdict="rejected",
                context={"title": "older hypothesis verdict"},
                provenance={"model": "fake-model"},
                note="looked wrong",
                created_at="2026-07-17T10:00:00+00:00",
            )
            store.record_verdict(
                target_type="template",
                target_id="ab" * 8,
                verdict="confirmed",
                context={"template": "alpha memory <NUM> warning"},
                provenance={},
                created_at="2026-07-17T11:00:00+00:00",
            )
        doc = json.loads(render_json(store))
    finally:
        store.close()

    verdicts = cast("list[dict[str, object]]", doc["verdicts"])
    assert len(verdicts) == 2
    for v in verdicts:
        for field in _VERDICT_FIELDS:
            assert field in v, f"verdict missing {field}"
    # Newest first: the later template verdict precedes the older hypothesis one.
    assert verdicts[0]["target_type"] == "template"
    assert verdicts[0]["target_id"] == "ab" * 8
    assert verdicts[0]["verdict"] == "confirmed"
    assert verdicts[0]["note"] == ""
    assert verdicts[0]["created_at"] == "2026-07-17T11:00:00+00:00"
    assert verdicts[1]["target_type"] == "hypothesis"
    assert verdicts[1]["verdict"] == "rejected"
    assert verdicts[1]["note"] == "looked wrong"
    # The opaque JSON snapshot columns round-trip as objects, not strings.
    assert verdicts[1]["context"] == {"title": "older hypothesis verdict"}
    assert verdicts[1]["provenance"] == {"model": "fake-model"}


def test_render_json_verdicts_stay_canonical_and_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With verdict rows present the emitted string is still the canonical
    # key-sorted dump, and two renders of the same case stay byte-identical.
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        with store.transaction():
            store.record_verdict(
                target_type="cluster",
                target_id="2",
                verdict="uncertain",
                context={"label": "Memory pressure"},
                provenance={},
                created_at="2026-07-17T10:30:00+00:00",
            )
        raw_first = render_json(store)
        raw_second = render_json(store)
    finally:
        store.close()

    assert raw_first == raw_second
    doc = json.loads(raw_first)
    assert raw_first == (
        json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"
    )


def test_render_json_verdict_note_escapes_hostile_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # IN-02 applies to operator text too: a hostile note must reach the file
    # backslash-u escaped (terminal-safe) yet round-trip verbatim via a parser.
    # Built via chr() so no raw hazardous byte lands in this source file.
    csi = chr(0x9B)  # single-byte CSI (C1)
    rlo = chr(0x202E)  # right-to-left override (bidi)
    hostile = f"note {csi}31m {rlo} overrides"
    case = build_analysed_case(monkeypatch, case="verdicthostile")
    store = open_case(case)
    try:
        with store.transaction():
            store.record_verdict(
                target_type="hypothesis",
                target_id="0",
                verdict="confirmed",
                context={},
                provenance={},
                note=hostile,
                created_at="2026-07-17T10:00:00+00:00",
            )
        raw = render_json(store)
    finally:
        store.close()

    assert csi not in raw
    assert rlo not in raw
    assert "\\u009b" in raw
    assert "\\u202e" in raw
    verdicts = cast("list[dict[str, object]]", json.loads(raw)["verdicts"])
    assert verdicts[0]["note"] == hostile


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
