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
- **eu-stack case scoring** (EUS-12) — ``run_case`` on a truth carrying
  ``expect_eustack`` is scored entirely offline via ``analyse_eustack_bundle``,
  proven by an OBSERVED empty request log rather than mere code inspection.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import pytest
from _eval_fixtures import eval_handler, patch_http, single_case_suite
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.eval.metrics import CaseResult, SuiteResult
from sift.eval.runner import run_case
from sift.eval.thresholds import gate, load_thresholds
from sift.llm.client import Endpoint, InferenceClient

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


# --------------------------------------------------------------------------- #
# eu-stack aggregate exclusion (EUS-12, D-19-06 / RESEARCH Pitfall 1)
# --------------------------------------------------------------------------- #


def _eustack_case(name: str, *, pass_: bool = True) -> CaseResult:
    """An eu-stack CaseResult with all four keyword metrics at 0.0 — the
    honest default, never a fabricated 1.0 (they are inert once excluded)."""
    return CaseResult(
        name=name,
        retrieval_hit_rate=0.0,
        hypothesis_hit_at_k=0.0,
        citation_validity_rate=0.0,
        determinism_stability=0.0,
        is_eustack=True,
        eustack_case_pass=pass_,
    )


def test_eustack_case_excluded_from_all_four_keyword_aggregates() -> None:
    # One eu-stack case with all-zero keyword metrics plus one ordinary
    # perfect positive case: every one of the four aggregates must read the
    # positive case's 1.0 only — the eu-stack case moved none of them.
    suite = SuiteResult([_perfect_case("pos"), _eustack_case("eustack-healthy")])
    assert suite.mean_retrieval_hit_rate() == 1.0
    assert suite.mean_hypothesis_hit_at_k() == 1.0
    assert suite.mean_citation_validity_rate() == 1.0
    assert suite.mean_determinism_stability() == 1.0


def test_mean_eustack_detection_rate_reads_only_eustack_cases() -> None:
    suite = SuiteResult(
        [
            _perfect_case("pos"),
            _eustack_case("eustack-healthy", pass_=True),
            _eustack_case("eustack-hang", pass_=False),
        ]
    )
    assert suite.mean_eustack_detection_rate() == 0.5


def test_mean_eustack_detection_rate_empty_suite_is_vacuous_one() -> None:
    # No eu-stack cases scored at all -> _mean([])'s vacuous 1.0 (EUS-12's own
    # gate.py vacuity flag, plan 19-03, is what makes THIS never silently pass
    # a suite that dropped its eu-stack cases entirely).
    suite = SuiteResult([_perfect_case("pos")])
    assert suite.mean_eustack_detection_rate() == 1.0


# --------------------------------------------------------------------------- #
# eu-stack case scoring (EUS-12, D-19-06/D-19-16/D-19-17) — client-free path
# --------------------------------------------------------------------------- #

_EUSTACK_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "eustack" / "threaddump.txt"

# Measured directly against the shipped analyser for this fixture (4 threads,
# all unclassified by the day-one taxonomy — none of its symbols match a
# rule): total_threads=4, the sole (unclassified) pool has busy_threads=4,
# zero dependencies, and exactly two flags — unclassified_thread_pct grades
# CRITICAL at 100.0% (default thresholds warn=5.0/critical=15.0), and
# no_resolvable_frame_pct grades info at 0.0%.
_EUSTACK_MATCHING_TRUTH = (
    "root_cause: near-idle capture, all threads unclassified by design\n"
    "expect_eustack:\n"
    "  provenance: authored\n"
    "  hang_detected: false\n"
    "  total_threads: 4\n"
    "  warn: 0\n"
    "  critical: 1\n"
    "  info_dimensions:\n"
    "    - no_resolvable_frame_pct\n"
)

_EUSTACK_MISMATCHED_TRUTH = (
    "root_cause: near-idle capture, all threads unclassified by design\n"
    "expect_eustack:\n"
    "  provenance: authored\n"
    "  hang_detected: false\n"
    "  total_threads: 999\n"  # wrong on purpose — planted mismatch
    "  warn: 0\n"
    "  critical: 1\n"
    "  info_dimensions:\n"
    "    - no_resolvable_frame_pct\n"
)


def _eustack_case_dir(tmp_path: Path, *, truth_yaml: str) -> Path:
    case_dir = tmp_path / "eustack-case"
    (case_dir / "input").mkdir(parents=True)
    shutil.copy(_EUSTACK_FIXTURE, case_dir / "input" / "threaddump.txt")
    (case_dir / "truth.yaml").write_text(truth_yaml, encoding="utf-8")
    return case_dir


def _recording_client() -> tuple[InferenceClient, httpx.Client, list[str]]:
    """An InferenceClient whose transport RECORDS every request path — the
    zero-endpoint claim must be proven by observation, not code inspection."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    config = load_config({})
    client = InferenceClient(
        generation=Endpoint(
            base_url=config.generation.base_url, model=config.generation.model
        ),
        embeddings=Endpoint(
            base_url=config.embeddings.base_url, model=config.embeddings.model
        ),
        http=http,
        allow_public=False,
    )
    return client, http, calls


def test_eustack_case_scored_with_zero_client_contact(tmp_path: Path) -> None:
    case_dir = _eustack_case_dir(tmp_path, truth_yaml=_EUSTACK_MATCHING_TRUTH)
    config = load_config({})
    client, http, calls = _recording_client()
    try:
        result = run_case(case_dir, client, config)
    finally:
        http.close()

    assert result.is_eustack is True
    assert result.run_failed is False, result.error
    assert result.eustack_case_pass is True
    assert calls == []  # the zero-endpoint claim, proven by observation
    assert result.retrieval_hit_rate == 0.0
    assert result.hypothesis_hit_at_k == 0.0
    assert result.citation_validity_rate == 0.0
    assert result.determinism_stability == 0.0


def test_eustack_case_mismatched_figure_fails_without_run_failed(
    tmp_path: Path,
) -> None:
    case_dir = _eustack_case_dir(tmp_path, truth_yaml=_EUSTACK_MISMATCHED_TRUTH)
    config = load_config({})
    client, http, calls = _recording_client()
    try:
        result = run_case(case_dir, client, config)
    finally:
        http.close()

    assert result.is_eustack is True
    assert result.eustack_case_pass is False  # a wrong figure IS a regression
    assert result.run_failed is False  # but NOT a crash
    assert calls == []


def test_eustack_case_ingest_failure_surfaces_as_run_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A genuine ingest error degrades to run_failed=True with a sanitised
    error — the same degradation the client-driven path uses — proven by
    forcing the exact failure mode rather than depending on an adapter's
    error-tolerant parsing (adapters never raise on bad content by design)."""
    case_dir = _eustack_case_dir(tmp_path, truth_yaml=_EUSTACK_MATCHING_TRUTH)
    config = load_config({})
    client, http, calls = _recording_client()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("simulated ingest failure")

    monkeypatch.setattr("sift.cli._ingest", _boom)
    try:
        result = run_case(case_dir, client, config)
    finally:
        http.close()

    assert result.is_eustack is True
    assert result.run_failed is True
    assert result.error
    assert calls == []


def test_run_eustack_case_never_reaches_cluster_or_hypothesise() -> None:
    """Static proof, per the plan's own acceptance criterion: the function
    body never mentions cluster_and_label, hypothesise, _run_pipeline or the
    client parameter."""
    import inspect

    from sift.eval import runner as runner_module

    src = inspect.getsource(
        runner_module._run_eustack_case  # pyright: ignore[reportPrivateUsage]
    )
    body = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "cluster_and_label" not in body
    assert "hypothesise" not in body
    assert "_run_pipeline" not in body
    assert "client" not in body
