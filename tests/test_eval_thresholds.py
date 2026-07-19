"""Threshold-gate + CI exit-code tests for `sift eval` (EVAL-03).

Two layers, both offline (zero sockets — the autouse `_no_network` guard stays
active):

- **CLI exit contract** — drives the committed golden suite through the real
  pipeline with a fake OpenAI-compatible client. A clean run exits 0; a planted
  keyword-missing regression drops ``hypothesis_hit_at_k`` below its floor and
  exits 1; a bad ``--suite`` path is a usage error (exit 2).
- **gate() invariants** — fabricated ``SuiteResult``s prove the load-bearing
  rules the aggregates alone do NOT enforce: a ``run_failed`` case forces a
  gate failure (a crashed run is a regression, never silently excluded), a
  false-positive on a negative case fails the gate, and an EMPTY positive set
  (which aggregates to a vacuous 1.0) is NOT reported as a pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _eval_fixtures import eval_handler, patch_http, single_case_suite
from typer.testing import CliRunner

from sift.cli import app
from sift.eval.metrics import CaseResult, SuiteResult
from sift.eval.thresholds import gate, load_thresholds

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SUITE = _REPO_ROOT / "eval" / "cases"
_THRESHOLDS = _REPO_ROOT / "eval" / "thresholds.toml"
_CASE = "memory-watermark-cascade"

_METRIC_KEYS = (
    "retrieval_hit_rate",
    "hypothesis_hit_at_k",
    "citation_validity_rate",
    "determinism_stability",
)

# A HypothesisSet whose title/narrative MISS every acceptable keyword
# (memory, watermark, OOM, cascade) → hypothesis_hit_at_k = 0.0, below the 1.00
# floor → a planted regression that MUST fail the gate.
_REGRESSED_HYPSET = json.dumps(
    {
        "hypotheses": [
            {
                "title": "Scheduled configuration reload completed",
                "narrative": (
                    "A routine settings refresh ran to completion with no "
                    "anomalies observed anywhere in the pipeline."
                ),
                "confidence": "high",
                "confidence_reasoning": "Routine reload, nothing untoward.",
                "supporting_event_ids": [],
                "contradicting_evidence": None,
                "suggested_next_steps": ["No action required"],
            }
        ],
        "timeline_summary": "A routine reload, nothing untoward.",
        "unexplained_signals": [],
    }
)


# --------------------------------------------------------------------------- #
# CLI exit contract (end-to-end, offline)
# --------------------------------------------------------------------------- #


def test_clean_suite_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_http(monkeypatch, eval_handler())
    suite = single_case_suite(tmp_path)
    result = runner.invoke(
        app, ["eval", "--suite", str(suite), "--thresholds", str(_THRESHOLDS)]
    )
    assert result.exit_code == 0, result.output


def test_planted_regression_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, eval_handler(hyp_content=_REGRESSED_HYPSET))
    result = runner.invoke(
        app, ["eval", "--suite", str(_SUITE), "--thresholds", str(_THRESHOLDS)]
    )
    assert result.exit_code == 1, result.output


def test_regression_json_marks_metric_and_overall_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_http(monkeypatch, eval_handler(hyp_content=_REGRESSED_HYPSET))
    result = runner.invoke(
        app,
        ["eval", "--suite", str(_SUITE), "--thresholds", str(_THRESHOLDS), "--json"],
    )
    assert result.exit_code == 1, result.output
    gate_doc = json.loads(result.output)["gate"]
    assert gate_doc["passed"] is False
    assert gate_doc["metrics"]["hypothesis_hit_at_k"]["passed"] is False


def test_clean_json_gate_passes_per_metric(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_http(monkeypatch, eval_handler())
    suite = single_case_suite(tmp_path)
    result = runner.invoke(
        app,
        ["eval", "--suite", str(suite), "--thresholds", str(_THRESHOLDS), "--json"],
    )
    assert result.exit_code == 0, result.output
    gate_doc = json.loads(result.output)["gate"]
    assert gate_doc["passed"] is True
    for metric in _METRIC_KEYS:
        assert gate_doc["metrics"][metric]["passed"] is True, metric


def test_bad_suite_is_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, eval_handler())
    result = runner.invoke(app, ["eval", "--suite", "/no/such/suite"])
    assert result.exit_code == 2, result.output


# --------------------------------------------------------------------------- #
# gate() invariants (fabricated SuiteResults)
# --------------------------------------------------------------------------- #


def _floors() -> dict[str, float]:
    return load_thresholds(_THRESHOLDS)


def _perfect_case(name: str, **overrides: object) -> CaseResult:
    """A case that clears every floor; ``overrides`` mutate the negative/failed
    flags for the invariant tests."""
    base: dict[str, object] = {
        "name": name,
        "retrieval_hit_rate": 1.0,
        "hypothesis_hit_at_k": 1.0,
        "citation_validity_rate": 1.0,
        "determinism_stability": 1.0,
    }
    base.update(overrides)
    return CaseResult(**base)  # type: ignore[arg-type]


def test_load_thresholds_has_the_four_float_floors() -> None:
    floors = load_thresholds(_THRESHOLDS)
    assert set(floors) == set(_METRIC_KEYS)
    assert all(isinstance(value, float) for value in floors.values())


def test_all_pass_gate_passes() -> None:
    suite = SuiteResult(
        [
            _perfect_case("pos"),
            _perfect_case("neg", expect_no_incident=True, negative_case_pass=True),
        ]
    )
    assert gate(suite, _floors()).passed is True


def test_run_failed_case_forces_gate_fail() -> None:
    """A crashed/failed run is a regression — never silently excluded even
    though the metric aggregates drop it."""
    suite = SuiteResult(
        [
            _perfect_case("ok"),
            CaseResult(
                name="boom",
                retrieval_hit_rate=0.0,
                hypothesis_hit_at_k=0.0,
                citation_validity_rate=0.0,
                determinism_stability=0.0,
                run_failed=True,
                error="transport blew up",
            ),
        ]
    )
    result = gate(suite, _floors())
    assert result.passed is False
    assert "boom" in result.run_failed_cases


def test_empty_positive_aggregate_is_not_a_pass() -> None:
    """No scorable positive case → the vacuous 1.0 aggregate must NOT pass the
    gate (a total pipeline failure cannot exit 0)."""
    suite = SuiteResult(
        [_perfect_case("neg", expect_no_incident=True, negative_case_pass=True)]
    )
    result = gate(suite, _floors())
    assert result.no_positive_cases is True
    assert result.passed is False


def test_all_cases_run_failed_is_not_a_pass() -> None:
    """The exact vacuous-1.0 trap: every case run_failed → positive set empty
    AND a failed case present → must fail, not report a perfect 1.00."""
    suite = SuiteResult(
        [
            CaseResult(
                name="boom",
                retrieval_hit_rate=0.0,
                hypothesis_hit_at_k=0.0,
                citation_validity_rate=0.0,
                determinism_stability=0.0,
                run_failed=True,
                error="everything failed",
            )
        ]
    )
    result = gate(suite, _floors())
    assert result.passed is False


def test_negative_false_positive_forces_gate_fail() -> None:
    suite = SuiteResult(
        [
            _perfect_case("pos"),
            _perfect_case("neg", expect_no_incident=True, negative_case_pass=False),
        ]
    )
    result = gate(suite, _floors())
    assert result.passed is False
    assert "neg" in result.false_positive_cases
