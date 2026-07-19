"""Threshold loading + the `sift eval` regression gate (EVAL-03, ADR 0010).

``load_thresholds`` reads ``eval/thresholds.toml`` with stdlib ``tomllib`` in
binary mode (mirroring ``config.py`` — no code-execution surface, T-07-02) and
coerces the four floors to ``float``. ``gate`` turns a scored ``SuiteResult``
into a pass/fail verdict: every keyword-metric aggregate must clear its floor,
AND — the load-bearing invariants the aggregates alone do NOT enforce — a
``run_failed`` case fails the gate (a crashed run is a regression, never
silently excluded), a false-positive on an ``expect_no_incident`` case fails the
gate, and an EMPTY positive set (which aggregates to a vacuous 1.0) is NOT a
pass. Judge scores never enter the gate (advisory only, D-08).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sift.eval.metrics import SuiteResult

# The four keyword floors, in the order they are displayed. Uniform direction:
# every metric is "higher is better", gated as value >= floor (ADR 0010).
METRIC_KEYS: tuple[str, ...] = (
    "retrieval_hit_rate",
    "hypothesis_hit_at_k",
    "citation_validity_rate",
    "determinism_stability",
)


def load_thresholds(path: Path) -> dict[str, float]:
    """Load the four float floors from ``path`` (binary-mode ``tomllib``).

    Raises ``ValueError`` on an unreadable/malformed file or a missing/non-float
    floor — the caller maps that to a usage error (exit 2). This is the trust
    boundary for the config file that controls the pass/fail decision (T-07-02).
    """
    try:
        with path.open("rb") as handle:  # tomllib requires binary mode
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid thresholds file {path}: {exc}") from exc
    try:
        return {key: float(raw[key]) for key in METRIC_KEYS}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"thresholds file {path} missing or non-float floor: {exc}"
        ) from exc


@dataclass(frozen=True)
class MetricVerdict:
    """One metric's aggregate value against its floor."""

    name: str
    value: float
    floor: float
    passed: bool


@dataclass(frozen=True)
class GateResult:
    """The overall gate decision plus the evidence behind it."""

    metrics: list[MetricVerdict]
    run_failed_cases: list[str]
    false_positive_cases: list[str]
    no_positive_cases: bool
    passed: bool

    def as_dict(self) -> dict[str, object]:
        """A canonical, JSON-serialisable view for ``--json`` output."""
        return {
            "passed": self.passed,
            "metrics": {
                m.name: {"value": m.value, "floor": m.floor, "passed": m.passed}
                for m in self.metrics
            },
            "run_failed_cases": self.run_failed_cases,
            "false_positive_cases": self.false_positive_cases,
            "no_positive_cases": self.no_positive_cases,
        }


def gate(suite: SuiteResult, thresholds: dict[str, float]) -> GateResult:
    """Decide pass/fail for a scored suite against ``thresholds``.

    Passing requires ALL of: every keyword-metric aggregate clears its floor;
    no ``run_failed`` case; no ``expect_no_incident`` false positive; at least
    one scorable positive case (an empty positive set aggregates to a vacuous
    1.0 and must not be reported as a pass).
    """
    values = {
        "retrieval_hit_rate": suite.mean_retrieval_hit_rate(),
        "hypothesis_hit_at_k": suite.mean_hypothesis_hit_at_k(),
        "citation_validity_rate": suite.mean_citation_validity_rate(),
        "determinism_stability": suite.mean_determinism_stability(),
    }
    metrics = [
        MetricVerdict(
            name=key,
            value=values[key],
            floor=thresholds[key],
            passed=values[key] >= thresholds[key],
        )
        for key in METRIC_KEYS
    ]
    run_failed_cases = [c.name for c in suite.cases if c.run_failed]
    false_positive_cases = [
        c.name
        for c in suite.cases
        if c.expect_no_incident
        and not c.run_failed
        and c.negative_case_pass is False
    ]
    no_positive_cases = not any(
        not c.expect_no_incident and not c.run_failed for c in suite.cases
    )
    passed = (
        all(m.passed for m in metrics)
        and not run_failed_cases
        and not false_positive_cases
        and not no_positive_cases
    )
    return GateResult(
        metrics=metrics,
        run_failed_cases=run_failed_cases,
        false_positive_cases=false_positive_cases,
        no_positive_cases=no_positive_cases,
        passed=passed,
    )
