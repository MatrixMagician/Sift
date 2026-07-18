"""Byte-identical JSON reproducibility contract (REPT-03).

Two independent ``analyze`` runs over the same seeded case + identical
fake-LLM responses + seed, each rendered to JSON, are byte-identical after
normalising ONLY the D-06 excluded fields (generated-at timestamp, absolute
filesystem paths, wall-clock durations). The excluded-field set lives in ONE
place — ``json_out.normalise_for_determinism`` — referenced here and in
ADR 0008 (Pitfall 4).

Network-free by construction: the analysed ``case.db`` is produced via the
injected ``httpx.MockTransport`` fake server (autouse ``_no_network`` guard).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from _report_fixtures import build_analysed_case, open_case

from sift.render.json_out import normalise_for_determinism, render_json

if TYPE_CHECKING:
    import pytest


def _canonical(doc: dict[str, object]) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2)


def _render(case: str) -> str:
    store = open_case(case)
    try:
        return render_json(store)
    finally:
        store.close()


def test_two_runs_byte_identical_after_normalisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_a = build_analysed_case(monkeypatch, case="run_a")
    case_b = build_analysed_case(monkeypatch, case="run_b")

    # Perturb ONLY the excluded generated-at field on run_b so the raw dumps
    # genuinely differ — this proves normalisation (not luck) makes them equal.
    store_b = open_case(case_b)
    try:
        with store_b.transaction():
            store_b.set_meta("triage_created_at", "2099-12-31T23:59:59+00:00")
    finally:
        store_b.close()

    raw_a = _render(case_a)
    raw_b = _render(case_b)
    assert raw_a != raw_b, "raw dumps must differ only by the excluded field"

    norm_a = normalise_for_determinism(json.loads(raw_a))
    norm_b = normalise_for_determinism(json.loads(raw_b))
    assert _canonical(norm_a) == _canonical(norm_b)


def test_normalise_drops_exactly_the_d06_fields() -> None:
    """The single exclusion helper drops generated_at, absolute paths and
    durations — and nothing else (case-relative paths are retained)."""
    doc: dict[str, object] = {
        "run": {
            "generated_at": "2026-07-17T09:10:00+00:00",
            "out_path": "/home/user/.local/share/sift/demo/case.db",
            "wall_duration_s": "1.234",
            "model": "keep-me",
        },
        "clusters": [{"signature": "case.log:12", "count": 3}],
        "timeline_summary": "keep this",
    }
    out = normalise_for_determinism(doc)

    run = out["run"]
    assert isinstance(run, dict)
    assert "generated_at" not in run
    assert "out_path" not in run  # absolute path dropped
    assert "wall_duration_s" not in run  # duration dropped
    assert run["model"] == "keep-me"

    # Case-relative content is retained untouched (D-06: only absolute paths go).
    assert out["timeline_summary"] == "keep this"
    clusters = out["clusters"]
    assert isinstance(clusters, list)
    assert clusters[0]["signature"] == "case.log:12"


def test_normalise_retains_slash_value_under_non_path_key() -> None:
    """IN-01: a content value that merely starts with '/' under a NON-path key
    (a signature/narrative quoting a log path) is retained — only absolute paths
    under path-named keys are volatile. Stripping by value alone could mask a
    real run-to-run difference and contradicts the ADR 0008 promise."""
    doc: dict[str, object] = {
        "run": {"generated_at": "t"},
        "clusters": [{"signature": "/var/log/app spike", "cluster_id": 1}],
        "hypotheses": [{"narrative": "/etc/passwd was read", "hyp_index": 0}],
    }
    out = normalise_for_determinism(doc)

    run = out["run"]
    assert isinstance(run, dict)
    assert "generated_at" not in run  # the sole wall-clock field still goes

    clusters = out["clusters"]
    assert isinstance(clusters, list)
    assert clusters[0]["signature"] == "/var/log/app spike"  # retained (non-path key)
    hyps = out["hypotheses"]
    assert isinstance(hyps, list)
    assert hyps[0]["narrative"] == "/etc/passwd was read"  # retained


def test_normalise_does_not_mutate_input() -> None:
    doc: dict[str, object] = {"run": {"generated_at": "x", "model": "m"}}
    normalise_for_determinism(doc)
    run = doc["run"]
    assert isinstance(run, dict)
    assert run["generated_at"] == "x", "helper must not mutate the caller's doc"
