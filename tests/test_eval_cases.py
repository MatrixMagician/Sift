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
import pytest
from _eval_fixtures import eval_handler

from sift.config import SiftConfig, load_config
from sift.eval.metrics import CaseResult, SuiteResult
from sift.eval.runner import run_case
from sift.eval.truth import load_truth
from sift.llm.client import Endpoint, InferenceClient
from sift.store import CaseStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SUITE = _REPO_ROOT / "eval" / "cases"

# The complete suite: five SPEC §6 exemplars, the negative case, plus the MCM
# denial golden case (MCM-07, Plan 11-03).
_EXPECTED_CASES = {
    "memory-watermark-cascade",
    "smtp-rejection-storm",
    "thread-pool-exhaustion",
    "disk-full",
    "dependency-timeout-mixed-tz",
    "negative-no-incident",
    "mcm-denial",
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


def _offline_client(
    config: SiftConfig, *, hyp_content: str = _EMPTY_HYPSET
) -> tuple[InferenceClient, httpx.Client]:
    """Build an InferenceClient wired to a MockTransport (no socket).

    ``hyp_content`` overrides the generation reply so a test can drive a specific
    citation set (default: the empty HypothesisSet the negative case expects)."""
    handler = eval_handler(hyp_content=hyp_content)
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


def test_suite_is_exactly_the_seven_cases() -> None:
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


# --- MCM denial golden case (MCM-07, Plan 11-03) -----------------------------

_MCM_CASE = _SUITE / "mcm-denial"


def _ingest_case(
    config: SiftConfig, case_dir: Path
) -> tuple[list[str], str]:
    """Ingest a case's ``input/`` via the real sniff+ingest path.

    Returns ``(event_message_texts, denial_event_id)`` where the denial id is a
    pure function of the (relpath, byte_offset) of the denial record — stable
    across ingest locations — so a MockTransport handler can cite it up front."""
    import contextlib
    import io
    import tempfile

    from sift.cli import _ingest  # pyright: ignore[reportPrivateUsage]
    from sift.config import McmThresholdsConfig
    from sift.pipeline.mcm import analyse_mcm

    noise = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="sift-eval-test-") as tmp:
        db = Path(tmp) / "seed.db"
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            store = CaseStore(db)
            try:
                store.set_meta("input_dir", str((case_dir / "input").resolve()))
                store.set_meta("adapter_overrides", "[]")
                _ingest(case_dir.name, config, store)
                texts = [m for _e, _t, _s, m in store.iter_event_summaries()]
                analysis = analyse_mcm(store.query_events(), McmThresholdsConfig())
            finally:
                store.close()
    denial_id = analysis.episodes[0].episode.denial_event_id
    return texts, denial_id


def _mcm_hypset(cited_ids: list[str]) -> str:
    """A schema-valid HypothesisSet citing ``cited_ids`` with an MCM narrative
    that also hits the case's acceptable_keywords (memory / MCM)."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "MCM memory exhaustion denial",
                    "narrative": (
                        "AvailableMCM fell to zero while the working set dominated "
                        "IServer virtual memory, so a memory contract request was "
                        "denied."
                    ),
                    "confidence": "high",
                    "confidence_reasoning": "Denial episode corroborated by MCM facts.",
                    "supporting_event_ids": cited_ids,
                    "contradicting_evidence": None,
                    "suggested_next_steps": ["Raise the working-set ceiling"],
                }
            ],
            "timeline_summary": "Memory pressure built, then MCM denied a request.",
            "unexplained_signals": [],
        }
    )


def test_mcm_denial_case_discovered_and_scored_positive() -> None:
    """`sift eval` discovers mcm-denial and scores it as a positive case (not
    run_failed); the required MCM evidence surfaces in the exemplars (MCM-07)."""
    assert _MCM_CASE in _case_dirs()
    truth = load_truth(_MCM_CASE / "truth.yaml")
    assert truth.expect_no_incident is False

    config = load_config({})
    client, http = _offline_client(config)
    try:
        result = run_case(_MCM_CASE, client, config)
    finally:
        http.close()
    assert result.run_failed is False, result.error
    assert result.expect_no_incident is False
    # required_evidence is matched against the cluster exemplars fed to the model;
    # all three MCM evidence regexes surface (retrieval computed, not vacuous).
    assert result.retrieval_hit_rate == 1.0


def test_mcm_denial_ingests_via_dsserrors_autosniff() -> None:
    """The case ingests via dsserrors auto-sniff (no --adapter override): the
    denial banner and the AvailableMCM grant lines are captured, and analyse_mcm
    finds the episode — proof the multi-line MCM block parsed as dsserrors."""
    config = load_config({})
    texts, denial_id = _ingest_case(config, _MCM_CASE)
    blob = "\n".join(texts)
    assert "IServer enters MCM denial state" in blob  # the denial banner
    assert "AvailableMCM" in blob  # the contract grant lines
    assert denial_id  # analyse_mcm found the episode -> dsserrors-quality parse


def test_mcm_denial_citation_validity_is_mcm_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MCM-sensitive metric for this case is citation_validity_rate, NOT
    retrieval (required_evidence is matched against raw exemplars, insensitive to
    injection). A hypothesis may cite the MCM denial event ONLY because injection
    unions it into prompted_ids; strip the injection and the SAME citation is
    FLAGGED, dropping citation_validity_rate below its 1.0 floor — the case turns
    red. This proves the golden case is not a vacuous gate (T-11-06)."""
    config = load_config({})
    _texts, denial_id = _ingest_case(config, _MCM_CASE)

    # MCM ON: injection makes the denial id citable -> citation is valid.
    client, http = _offline_client(config, hyp_content=_mcm_hypset([denial_id]))
    try:
        on = run_case(_MCM_CASE, client, config)
    finally:
        http.close()
    assert on.run_failed is False, on.error
    assert on.citation_validity_rate == 1.0

    # MCM OFF: strip the injected fact block at the chokepoint. The same cited
    # denial id is no longer in prompted_ids -> the citation gate FLAGS it.
    from sift.pipeline import hypothesise

    def _no_mcm_block(_analysis: object) -> tuple[str, set[str]]:
        return "", set()

    monkeypatch.setattr(hypothesise, "render_mcm_facts", _no_mcm_block)
    client2, http2 = _offline_client(config, hyp_content=_mcm_hypset([denial_id]))
    try:
        off = run_case(_MCM_CASE, client2, config)
    finally:
        http2.close()
    assert off.run_failed is False, off.error
    assert off.citation_validity_rate < 1.0
