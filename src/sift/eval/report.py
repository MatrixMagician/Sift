"""Render a scored ``SuiteResult`` as a plain-text table or machine-readable JSON.

``render_text_table`` is the default human view; ``render_json_table`` mirrors
``render_json``'s canonical key-sorted shape (D-05). The determinism column
DISPLAYS drift = 1 − stability (the SPEC "determinism drift" wording) while the
gate (Plan 03) consumes stability internally — one direction, two labels
(RESEARCH gotcha). Case names are ``_sanitise``d before printing (they can carry
hostile bytes from a malicious case directory name, T-04-01).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.eval.metrics import CaseResult, SuiteResult
    from sift.eval.thresholds import GateResult


def _status(case: CaseResult) -> str:
    if case.run_failed:
        return "FAILED"
    if case.expect_no_incident:
        return "PASS" if case.negative_case_pass else "FAIL"
    return "ok"


def render_text_table(suite: SuiteResult, gate: GateResult | None = None) -> str:
    """A British-English plain-text metric table: one row per case plus a
    suite-aggregate row. Columns: retrieval hit rate, hypothesis hit@k, citation
    validity, determinism drift (= 1 − stability), and a status flag.

    When ``gate`` is supplied, a per-metric floor verdict and the overall
    pass/fail line are appended (the CI gate, Plan 03)."""
    header = (
        f"{'case':<32}  {'retrieval':>9}  {'hit@k':>6}  "
        f"{'citation':>8}  {'drift':>6}  status"
    )
    lines = [header, "-" * len(header)]
    for case in suite.cases:
        drift = 1.0 - case.determinism_stability
        lines.append(
            f"{sanitise(case.name):<32}  {case.retrieval_hit_rate:>9.2f}  "
            f"{case.hypothesis_hit_at_k:>6.2f}  {case.citation_validity_rate:>8.2f}  "
            f"{drift:>6.2f}  {_status(case)}"
        )
    agg_drift = 1.0 - suite.mean_determinism_stability()
    lines.append("-" * len(header))
    lines.append(
        f"{'SUITE (positive cases)':<32}  {suite.mean_retrieval_hit_rate():>9.2f}  "
        f"{suite.mean_hypothesis_hit_at_k():>6.2f}  "
        f"{suite.mean_citation_validity_rate():>8.2f}  {agg_drift:>6.2f}"
    )
    if gate is not None:
        lines.append("")
        lines.append("gate (floors):")
        for metric in gate.metrics:
            flag = "PASS" if metric.passed else "FAIL"
            lines.append(
                f"  {metric.name:<24} {metric.value:>5.2f} >= "
                f"{metric.floor:>5.2f}  {flag}"
            )
        if gate.run_failed_cases:
            lines.append(f"  run-failed cases: {', '.join(gate.run_failed_cases)}")
        if gate.false_positive_cases:
            lines.append(
                f"  false-positive negatives: {', '.join(gate.false_positive_cases)}"
            )
        if gate.no_positive_cases:
            lines.append("  no scorable positive case — gate cannot pass")
        lines.append(f"GATE: {'PASS' if gate.passed else 'FAIL'}")
    return "\n".join(lines) + "\n"


def _case_dict(case: CaseResult) -> dict[str, object]:
    return {
        "name": case.name,
        "retrieval_hit_rate": case.retrieval_hit_rate,
        "hypothesis_hit_at_k": case.hypothesis_hit_at_k,
        "citation_validity_rate": case.citation_validity_rate,
        "determinism_stability": case.determinism_stability,
        "determinism_drift": 1.0 - case.determinism_stability,
        "expect_no_incident": case.expect_no_incident,
        "negative_case_pass": case.negative_case_pass,
        "run_failed": case.run_failed,
        "error": case.error,
        "judge_score": case.judge_score,
    }


def render_json_table(suite: SuiteResult, gate: GateResult | None = None) -> str:
    """The machine-readable metric table (D-05): canonical key-sorted JSON with a
    trailing newline, mirroring ``render_json``.

    When ``gate`` is supplied a ``"gate"`` object carries the per-metric floor
    verdicts and the overall pass/fail bool (the CI gate result, Plan 03)."""
    doc: dict[str, object] = {
        "cases": [_case_dict(case) for case in suite.cases],
        "aggregate": {
            "retrieval_hit_rate": suite.mean_retrieval_hit_rate(),
            "hypothesis_hit_at_k": suite.mean_hypothesis_hit_at_k(),
            "citation_validity_rate": suite.mean_citation_validity_rate(),
            "determinism_stability": suite.mean_determinism_stability(),
            "determinism_drift": 1.0 - suite.mean_determinism_stability(),
        },
    }
    if gate is not None:
        doc["gate"] = gate.as_dict()
    return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"
