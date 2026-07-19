"""Suite-level validation for the committed golden cases (EVAL-01).

Proves the frozen suite as a whole: every case's ``truth.yaml`` loads through the
schema-forbidding loader, the suite is exactly the six required cases, the three
special shapes (quiet-cause, mixed-timezone, negative) are present, and the
negative case scores a pass by the no-confident-hypothesis predicate when run
offline. Zero sockets — the negative run is served by an ``httpx.MockTransport``
so the autouse ``_no_network`` guard stays active.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from _eval_fixtures import eval_handler

from sift.config import SiftConfig, load_config
from sift.eval.metrics import CaseResult, SuiteResult
from sift.eval.runner import run_case
from sift.eval.truth import load_truth
from sift.llm.client import Endpoint, InferenceClient

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SUITE = _REPO_ROOT / "eval" / "cases"

# The complete D-01 suite: five SPEC §6 exemplars plus the negative case.
_EXPECTED_CASES = {
    "memory-watermark-cascade",
    "smtp-rejection-storm",
    "thread-pool-exhaustion",
    "disk-full",
    "dependency-timeout-mixed-tz",
    "negative-no-incident",
}

# The offline reply for the negative case: a HypothesisSet with no hypotheses, so
# negative_case_pass (zero confident hypotheses on healthy logs) holds.
_EMPTY_HYPSET = json.dumps(
    {
        "hypotheses": [],
        "timeline_summary": "No incident detected; steady-state operation.",
        "unexplained_signals": [],
    }
)


def _case_dirs() -> list[Path]:
    return sorted(
        d for d in _SUITE.iterdir() if d.is_dir() and (d / "truth.yaml").exists()
    )


def _offline_client(config: SiftConfig) -> tuple[InferenceClient, httpx.Client]:
    """Build an InferenceClient wired to the empty-reply MockTransport (no socket)."""
    handler = eval_handler(hyp_content=_EMPTY_HYPSET)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = InferenceClient(
        generation=Endpoint(
            base_url=config.generation.base_url, model=config.generation.model
        ),
        embeddings=Endpoint(
            base_url=config.embeddings.base_url, model=config.embeddings.model
        ),
        http=http,
        allow_public=False,
        retries=config.generation.retries,
        backoff_base=config.generation.backoff_base,
        batch_size=config.embeddings.batch_size,
    )
    return client, http


def test_suite_is_exactly_the_six_cases() -> None:
    assert {d.name for d in _case_dirs()} == _EXPECTED_CASES


def test_every_truth_yaml_loads() -> None:
    # load_truth raises on a schema violation or an extra key (T-07-01), so a
    # clean pass over every committed case is the suite's schema guarantee.
    for case in _case_dirs():
        load_truth(case / "truth.yaml")


def test_special_shapes_present() -> None:
    # Quiet-cause and mixed-tz are positive cases; only the negative case sets
    # expect_no_incident.
    quiet = load_truth(_SUITE / "memory-watermark-cascade" / "truth.yaml")
    negative = load_truth(_SUITE / "negative-no-incident" / "truth.yaml")
    assert quiet.expect_no_incident is False
    assert negative.expect_no_incident is True

    # The mixed-timezone case carries ≥2 node logs at different UTC offsets.
    tz_dir = _SUITE / "dependency-timeout-mixed-tz" / "input"
    logs = sorted(tz_dir.glob("*.log"))
    assert len(logs) >= 2
    joined = "\n".join(p.read_text(encoding="utf-8") for p in logs)
    assert "+05:30" in joined
    assert "-05:00" in joined


def test_negative_case_passes_offline_and_is_excluded_from_positive_aggregate() -> None:
    config = load_config({})
    client, http = _offline_client(config)
    try:
        result = run_case(_SUITE / "negative-no-incident", client, config)
    finally:
        http.close()

    assert result.run_failed is False, result.error
    assert result.expect_no_incident is True
    assert result.negative_case_pass is True

    # A keyword "hit" on a negative case would be a false positive; the negative
    # case must not drag the positive hit@k aggregate (Pitfall 5).
    perfect = CaseResult(
        name="pos",
        retrieval_hit_rate=1.0,
        hypothesis_hit_at_k=1.0,
        citation_validity_rate=1.0,
        determinism_stability=1.0,
    )
    suite = SuiteResult([perfect, result])
    assert suite.mean_hypothesis_hit_at_k() == 1.0
