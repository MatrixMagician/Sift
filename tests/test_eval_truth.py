"""Truth-loader + pure-metric unit tests (EVAL-01/02).

These are *machinery* tests: they exercise the truth.yaml schema (safe parse,
extra=forbid) and the four metric functions on fabricated rows — no pipeline
run, no client, no sockets. Real hypothesis quality is a live concern (see
tests/test_eval_harness.py for the offline end-to-end machinery test).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.eval.metrics import (
    citation_validity_rate,
    determinism_stability,
    hypothesis_hit_at_k,
    negative_case_pass,
    retrieval_hit_rate,
)
from sift.eval.truth import Truth, load_truth
from sift.store import StoredHypothesis

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN = _REPO_ROOT / "eval" / "cases" / "memory-watermark-cascade" / "truth.yaml"


def _hyp(
    *,
    index: int = 0,
    title: str = "",
    narrative: str = "",
    confidence: str = "high",
    citations_valid: bool = True,
) -> StoredHypothesis:
    return StoredHypothesis(
        hyp_index=index,
        title=title,
        narrative=narrative,
        confidence=confidence,
        confidence_reasoning="",
        supporting_event_ids=[],
        contradicting_evidence=None,
        suggested_next_steps=[],
        citations_valid=citations_valid,
    )


# --- Truth schema: safe parse + extra=forbid --------------------------------


def test_load_truth_valid(tmp_path: Path) -> None:
    path = tmp_path / "truth.yaml"
    path.write_text(
        "root_cause: a watermark cascade\n"
        "required_evidence:\n  - watermark\n"
        "acceptable_keywords:\n  - memory\n"
        "expect_no_incident: false\n",
        encoding="utf-8",
    )
    truth = load_truth(path)
    assert isinstance(truth, Truth)
    assert truth.root_cause == "a watermark cascade"
    assert truth.required_evidence == ["watermark"]
    assert truth.acceptable_keywords == ["memory"]
    assert truth.expect_no_incident is False


def test_committed_golden_case_truth_is_schema_valid() -> None:
    truth = load_truth(_GOLDEN)
    assert truth.root_cause
    assert truth.required_evidence
    assert truth.acceptable_keywords
    assert truth.expect_no_incident is False


def test_load_truth_unknown_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "truth.yaml"
    path.write_text("root_cause: x\nbogus_key: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_truth(path)


def test_load_truth_rejects_python_tag(tmp_path: Path) -> None:
    # A custom object tag must NOT construct an arbitrary object or run code —
    # safe_load refuses it (yaml.YAMLError), never executes it.
    path = tmp_path / "truth.yaml"
    path.write_text(
        "root_cause: !!python/object/apply:os.system ['echo pwned']\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 — YAMLError; the point is: no code ran
        load_truth(path)


# --- retrieval_hit_rate -----------------------------------------------------


def test_retrieval_hit_rate_counts_regex_hits() -> None:
    texts = ["memory high-watermark exceeded", "oom-killer invoked", "all fine"]
    evidence = ["watermark.*(exceed|breach)", "OOM|oom-kill", "evict"]
    # two of three regexes match (watermark, oom); evict is absent.
    assert retrieval_hit_rate(texts, evidence) == pytest.approx(2 / 3)


def test_retrieval_hit_rate_is_case_insensitive() -> None:
    assert retrieval_hit_rate(["OOM KILLER"], ["oom"]) == 1.0


def test_retrieval_hit_rate_empty_evidence_is_one() -> None:
    assert retrieval_hit_rate([], []) == 1.0


# --- hypothesis_hit_at_k ----------------------------------------------------


def test_hypothesis_hit_at_k_matches_any_keyword() -> None:
    hyps = [_hyp(title="Disk full", narrative="the disk filled up")]
    assert hypothesis_hit_at_k(hyps, ["watermark", "memory"], 3) == 0.0
    hyps2 = [_hyp(title="Memory watermark breach", narrative="cascade to OOM")]
    assert hypothesis_hit_at_k(hyps2, ["watermark"], 3) == 1.0


def test_hypothesis_hit_at_k_respects_k() -> None:
    hyps = [
        _hyp(index=0, title="unrelated"),
        _hyp(index=1, title="memory watermark"),
    ]
    assert hypothesis_hit_at_k(hyps, ["watermark"], 1) == 0.0
    assert hypothesis_hit_at_k(hyps, ["watermark"], 2) == 1.0


# --- citation_validity_rate -------------------------------------------------


def test_citation_validity_rate_is_mean() -> None:
    hyps = [_hyp(citations_valid=True), _hyp(citations_valid=False)]
    assert citation_validity_rate(hyps) == 0.5


def test_citation_validity_rate_empty_is_one() -> None:
    assert citation_validity_rate([]) == 1.0


# --- determinism_stability --------------------------------------------------


def test_determinism_stability_identical_is_one() -> None:
    a: dict[str, object] = {"x": 1, "y": [1, 2]}
    b: dict[str, object] = {"y": [1, 2], "x": 1}  # key order must not matter
    assert determinism_stability([a, b]) == 1.0


def test_determinism_stability_different_is_zero() -> None:
    a: dict[str, object] = {"x": 1}
    b: dict[str, object] = {"x": 2}
    assert determinism_stability([a, b]) == 0.0


# --- negative_case_pass -----------------------------------------------------


def test_negative_case_pass_zero_hypotheses() -> None:
    assert negative_case_pass([]) is True


def test_negative_case_pass_all_low_confidence() -> None:
    assert negative_case_pass([_hyp(confidence="low"), _hyp(confidence="low")]) is True


def test_negative_case_pass_fails_on_confident_hypothesis() -> None:
    assert negative_case_pass([_hyp(confidence="high")]) is False
