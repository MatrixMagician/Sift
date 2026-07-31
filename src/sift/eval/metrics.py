"""Pure metric functions + result records for the eval harness (EVAL-02).

Every metric here is a pure function of already-fetched rows (lists) plus a
frozen ``Truth`` — no I/O, no client, no store — so they unit-test offline with
fabricated rows. The direction convention is uniform: all four metrics are
"higher is better" in [0, 1], so a single ``value >= floor`` gate (Plan 03)
covers them. Determinism is expressed as ``determinism_stability`` (fraction that
IS byte-identical) rather than "drift"; the report DISPLAYS drift = 1 − stability
(RESEARCH direction gotcha).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sift.store import StoredHypothesis


def retrieval_hit_rate(
    exemplar_texts: list[str], required_evidence: list[str]
) -> float:
    """Fraction of ``required_evidence`` regexes present in the clusters fed to
    the model (case-insensitive). Empty evidence is a vacuous 1.0."""
    if not required_evidence:
        return 1.0
    haystack = "\n".join(exemplar_texts)
    hits = sum(
        1
        for pattern in required_evidence
        if re.search(pattern, haystack, re.IGNORECASE)
    )
    return hits / len(required_evidence)


def hypothesis_hit_at_k(
    hyps: list[StoredHypothesis], acceptable_keywords: list[str], k: int
) -> float:
    """1.0 if ANY of the top-k hypotheses' title+narrative contains ANY
    acceptable keyword (case-insensitive any-of), else 0.0."""
    keywords = [word.lower() for word in acceptable_keywords]
    if not keywords:
        return 0.0
    for hyp in hyps[:k]:
        blob = f"{hyp.title}\n{hyp.narrative}".lower()
        if any(word in blob for word in keywords):
            return 1.0
    return 0.0


def citation_validity_rate(hyps: list[StoredHypothesis]) -> float:
    """Mean of the persisted per-hypothesis citation-gate verdict
    (``StoredHypothesis.citations_valid``). Zero hypotheses is a vacuous 1.0.

    This reads the gate's own verdict — it never re-derives ``cited ⊆ store``
    (the anti-hallucination gate is the single source of truth, T-04-02)."""
    if not hyps:
        return 1.0
    return sum(1 for hyp in hyps if hyp.citations_valid) / len(hyps)


def determinism_stability(docs: list[dict[str, object]]) -> float:
    """1.0 iff every normalised document is byte-identical, else 0.0 (D-06).

    Each doc is a ``normalise_for_determinism`` output; equality is by
    canonical ``json.dumps(sort_keys=True)`` so key order does not matter. Fewer
    than two docs is a vacuous 1.0 (nothing to disagree)."""
    if len(docs) < 2:
        return 1.0
    canonical = {json.dumps(doc, sort_keys=True) for doc in docs}
    return 1.0 if len(canonical) == 1 else 0.0


def negative_case_pass(hyps: list[StoredHypothesis]) -> bool:
    """The no-confident-hypothesis predicate for ``expect_no_incident`` cases:
    a pass when zero hypotheses are emitted OR every hypothesis is low
    confidence (a confident root cause on healthy logs is a false positive)."""
    return not hyps or all(hyp.confidence == "low" for hyp in hyps)


@dataclass(frozen=True)
class CaseResult:
    """The scored outcome of one golden case.

    For ``expect_no_incident`` cases the keyword metrics are still recorded but
    excluded from the suite's positive aggregates (RESEARCH Pitfall 5); the pass
    verdict is ``negative_case_pass`` instead. ``run_failed`` marks a case whose
    pipeline could not complete (transport/parse error); its metrics default to
    0.0 and it is excluded from the aggregates. ``is_eustack`` marks an LLM-free
    eu-stack case (EUS-12/D-19-06): its four keyword-metric fields are always
    0.0 (never a fabricated vacuous 1.0) and it is excluded from all four
    keyword aggregates below, exactly like ``expect_no_incident``/``run_failed``
    — an empty ``acceptable_keywords`` scores a literal 0.0, not a vacuous 1.0
    (RESEARCH Pitfall 1), so scoring an eu-stack case unexcluded would silently
    drag every keyword mean down. ``eustack_case_pass`` is its own pass verdict,
    read only by ``mean_eustack_detection_rate``."""

    name: str
    # The four keyword metrics default to 0.0 — the honest run-failed/eu-stack
    # shape (never a fabricated vacuous 1.0), so those constructors pass only
    # the flags.
    retrieval_hit_rate: float = 0.0
    hypothesis_hit_at_k: float = 0.0
    citation_validity_rate: float = 0.0
    determinism_stability: float = 0.0
    expect_no_incident: bool = False
    negative_case_pass: bool | None = None
    run_failed: bool = False
    error: str | None = None
    is_eustack: bool = False
    eustack_case_pass: bool | None = None
    # Reserved for the advisory LLM-as-judge (Plan 05); never gates.
    judge_score: float | None = None


@dataclass(frozen=True)
class SuiteResult:
    """All scored cases plus positive-case aggregate helpers.

    Aggregates exclude ``expect_no_incident`` and ``run_failed`` cases from the
    retrieval / hit@k means (a keyword "hit" on a negative case is a false
    positive); citation validity and determinism are averaged over every
    non-failed case. An empty positive set aggregates to a vacuous 1.0.
    ``is_eustack`` cases (EUS-12) are excluded from ALL FOUR keyword aggregates
    — they declare empty ``required_evidence``/``acceptable_keywords`` and run
    no LLM leg (D-19-06), and ``hypothesis_hit_at_k`` scores an empty keyword
    list a literal 0.0, not a vacuous 1.0 (RESEARCH Pitfall 1), so an unexcluded
    eu-stack case would silently drag every keyword mean down. They are scored
    only by ``mean_eustack_detection_rate``, which reads the inverse selection."""

    cases: list[CaseResult] = field(default_factory=list["CaseResult"])

    def _positive(self) -> list[CaseResult]:
        return [
            c
            for c in self.cases
            if not c.expect_no_incident and not c.run_failed and not c.is_eustack
        ]

    def _scored(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.run_failed and not c.is_eustack]

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 1.0

    def mean_retrieval_hit_rate(self) -> float:
        return self._mean([c.retrieval_hit_rate for c in self._positive()])

    def mean_hypothesis_hit_at_k(self) -> float:
        return self._mean([c.hypothesis_hit_at_k for c in self._positive()])

    def mean_citation_validity_rate(self) -> float:
        return self._mean([c.citation_validity_rate for c in self._scored()])

    def mean_determinism_stability(self) -> float:
        return self._mean([c.determinism_stability for c in self._scored()])

    def mean_eustack_detection_rate(self) -> float:
        return self._mean(
            [
                1.0 if c.eustack_case_pass else 0.0
                for c in self.cases
                if c.is_eustack and not c.run_failed
            ]
        )
