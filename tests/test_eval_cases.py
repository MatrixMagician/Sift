"""Suite-level validation for the committed golden cases (EVAL-01).

Proves the frozen suite as a whole: every case's ``truth.yaml`` loads through the
schema-forbidding loader, the suite is exactly the eleven required cases, the
three special shapes (quiet-cause, mixed-timezone, negative) are present, and
the negative case scores a pass by the no-confident-hypothesis predicate when
run offline. Zero sockets — the negative run is served by an
``httpx.MockTransport`` so the autouse ``_no_network`` guard stays active.

Three of the eleven cases are eu-stack golden cases (EUS-12), scored entirely
offline against ``analyse_eustack_bundle`` with no inference endpoint at all
(D-19-06/D-19-16): ``eustack-healthy`` (the real, observed reference capture —
proves the analyser does not cry wolf), ``eustack-hang-pool-warehouse`` (a
synthetic, authored warehouse connection-pool exhaustion — proves the analyser
reproduces a documented hang shape's figures) and
``eustack-hang-pool-warehouse-mutated`` (that positive's cosmetic-mutation
twin — proves detection is not overfit to string equality, D-19-11).
"""

from __future__ import annotations

import json
import subprocess
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

# The complete suite: five SPEC §6 exemplars, the negative case, the MCM denial
# golden case (MCM-07, Plan 11-03), the perfmon-denial golden case (PERF-08,
# Plan 14-05), plus the three eu-stack golden cases (EUS-12): eustack-healthy
# (Plan 19-03, the real observed reference capture — proves no false alarm),
# eustack-hang-pool-warehouse (Plan 19-04, synthetic authored pool exhaustion
# — proves a documented hang shape is detected) and its cosmetic-mutation
# twin eustack-hang-pool-warehouse-mutated (Plan 19-04, D-19-11 — proves
# detection is not overfit to string equality). All three eu-stack cases are
# LLM-free (D-19-06/D-19-16).
_EXPECTED_CASES = {
    "memory-watermark-cascade",
    "smtp-rejection-storm",
    "thread-pool-exhaustion",
    "disk-full",
    "dependency-timeout-mixed-tz",
    "negative-no-incident",
    "mcm-denial",
    "perfmon-denial",
    "eustack-healthy",
    "eustack-hang-pool-warehouse",
    "eustack-hang-pool-warehouse-mutated",
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


def test_suite_is_exactly_the_eleven_cases() -> None:
    dirs = {d.name for d in _case_dirs()}
    assert dirs == _EXPECTED_CASES
    assert len(dirs) == 11
    assert "perfmon-denial" in dirs
    assert "eustack-healthy" in dirs
    assert "eustack-hang-pool-warehouse" in dirs
    assert "eustack-hang-pool-warehouse-mutated" in dirs


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

    from sift.config import McmThresholdsConfig
    from sift.pipeline.ingest import run_ingest
    from sift.pipeline.mcm import analyse_mcm

    noise = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="sift-eval-test-") as tmp:
        db = Path(tmp) / "seed.db"
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            store = CaseStore(db)
            try:
                store.set_meta("input_dir", str((case_dir / "input").resolve()))
                store.set_meta("adapter_overrides", "[]")
                run_ingest(case_dir.name, config, store)
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
    """The injection-sensitive metric for this case is citation_validity_rate, NOT
    retrieval (required_evidence is matched against raw exemplars, insensitive to
    injection). A hypothesis may cite the MCM denial event ONLY because the
    deterministic fact injection unions it into prompted_ids; strip the injection
    and the SAME citation is FLAGGED, dropping citation_validity_rate below its 1.0
    floor — the case turns red. This proves the golden case is not a vacuous gate
    (T-11-06).

    Since Phase 14 the perfmon block ALSO cites the denial boundary events (its
    D-08 zero-sample disclosure group is keyed on the same MCM denial window), so
    the denial id is now citable via EITHER injection source. Both renderers must
    therefore be stripped to demonstrate the gate — stripping only one leaves the
    id citable through the other."""
    config = load_config({})
    _texts, denial_id = _ingest_case(config, _MCM_CASE)

    # INJECTION ON: mcm (and perfmon) makes the denial id citable -> valid.
    client, http = _offline_client(config, hyp_content=_mcm_hypset([denial_id]))
    try:
        on = run_case(_MCM_CASE, client, config)
    finally:
        http.close()
    assert on.run_failed is False, on.error
    assert on.citation_validity_rate == 1.0

    # INJECTION OFF: strip BOTH deterministic fact blocks at the chokepoint. The
    # same cited denial id is no longer in prompted_ids -> the gate FLAGS it.
    from sift.pipeline import analysers

    def _no_block(_analysis: object) -> tuple[str, set[str]]:
        return "", set()

    monkeypatch.setattr(analysers, "render_mcm_facts", _no_block)
    monkeypatch.setattr(analysers, "render_perfmon_facts", _no_block)
    client2, http2 = _offline_client(config, hyp_content=_mcm_hypset([denial_id]))
    try:
        off = run_case(_MCM_CASE, client2, config)
    finally:
        http2.close()
    assert off.run_failed is False, off.error
    assert off.citation_validity_rate < 1.0


# --- Perfmon denial golden case (PERF-08, Plan 14-05) -------------------------

_PERFMON_CASE = _SUITE / "perfmon-denial"


def _citable_perfmon_id(config: SiftConfig, case_dir: Path) -> str:
    """A citable perfmon ``event_id`` printed by ``render_perfmon_facts`` for this
    case, ingested via the real sniff+ingest path.

    Returns the first ``dssperfmon`` id in the rendered block's citable set — a
    real counter sample at the denial boundary, disjoint from the MCM denial
    boundary ids (which are ``dsserrors`` events). Because the id is a pure
    function of ``(relpath, byte_offset)``, a MockTransport handler can cite it up
    front and ``run_case``'s own temp ingest resolves the same id."""
    import contextlib
    import io
    import tempfile

    from sift.config import McmThresholdsConfig
    from sift.pipeline.ingest import run_ingest
    from sift.pipeline.mcm import analyse_mcm
    from sift.pipeline.perfmon import analyse_perfmon
    from sift.pipeline.perfmon_facts import render_perfmon_facts

    noise = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="sift-eval-perfmon-") as tmp:
        db = Path(tmp) / "seed.db"
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            store = CaseStore(db)
            try:
                store.set_meta("input_dir", str((case_dir / "input").resolve()))
                store.set_meta("adapter_overrides", "[]")
                run_ingest(case_dir.name, config, store)
                events = store.query_events()
                mcm = analyse_mcm(events, McmThresholdsConfig())
                _block, pids = render_perfmon_facts(analyse_perfmon(mcm, events))
                by_id = {e.event_id: e for e in events}
            finally:
                store.close()
    perfmon_ids = sorted(i for i in pids if by_id[i].source == "dssperfmon")
    assert perfmon_ids, "perfmon-denial must print >=1 citable dssperfmon id"
    return perfmon_ids[0]


def test_perfmon_denial_case_discovered_and_scored_positive() -> None:
    """`sift eval` discovers perfmon-denial and scores it as a positive case (not
    run_failed); the required denial evidence surfaces in the exemplars (PERF-08)."""
    assert _PERFMON_CASE in _case_dirs()
    truth = load_truth(_PERFMON_CASE / "truth.yaml")
    assert truth.expect_no_incident is False

    config = load_config({})
    client, http = _offline_client(config)
    try:
        result = run_case(_PERFMON_CASE, client, config)
    finally:
        http.close()
    assert result.run_failed is False, result.error
    assert result.expect_no_incident is False
    # required_evidence is matched against the cluster exemplars fed to the model;
    # all three denial evidence regexes surface (retrieval computed, not vacuous).
    assert result.retrieval_hit_rate == 1.0


def test_perfmon_denial_citation_validity_is_perfmon_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The injection-sensitive metric for this case is citation_validity_rate, NOT
    retrieval (required_evidence is matched against raw exemplars, insensitive to
    injection). A hypothesis may cite a perfmon counter event ONLY because
    ``render_perfmon_facts`` unions it into ``prompted_ids``; strip that injection
    and the SAME citation is FLAGGED, dropping citation_validity_rate below its 1.0
    floor — the case turns red. This proves the golden case is not a vacuous gate
    (T-14-10, the PERF-08 gate teeth).

    The cited id is a ``dssperfmon`` sample disjoint from the MCM denial boundary
    ids, so it is citable via the PERFMON injection ALONE — stripping only
    ``render_perfmon_facts`` (not ``render_mcm_facts``) is sufficient to demonstrate
    the gate, isolating the perfmon-correlation path."""
    config = load_config({})
    perfmon_id = _citable_perfmon_id(config, _PERFMON_CASE)

    # INJECTION ON: render_perfmon_facts makes the perfmon id citable -> valid.
    client, http = _offline_client(config, hyp_content=_mcm_hypset([perfmon_id]))
    try:
        on = run_case(_PERFMON_CASE, client, config)
    finally:
        http.close()
    assert on.run_failed is False, on.error
    assert on.citation_validity_rate == 1.0

    # INJECTION OFF: strip ONLY the perfmon fact block at the chokepoint. The same
    # cited perfmon id is no longer in prompted_ids -> the gate FLAGS it.
    from sift.pipeline import analysers

    def _no_block(_analysis: object) -> tuple[str, set[str]]:
        return "", set()

    monkeypatch.setattr(analysers, "render_perfmon_facts", _no_block)
    client2, http2 = _offline_client(config, hyp_content=_mcm_hypset([perfmon_id]))
    try:
        off = run_case(_PERFMON_CASE, client2, config)
    finally:
        http2.close()
    assert off.run_failed is False, off.error
    assert off.citation_validity_rate < 1.0


# --- Eu-stack healthy golden case (EUS-12, Plan 19-03) -----------------------

_EUSTACK_HEALTHY_CASE = _SUITE / "eustack-healthy"


def _recording_client() -> tuple[InferenceClient, httpx.Client, list[str]]:
    """An InferenceClient whose transport RECORDS every request path — the
    D-19-16 no-endpoint claim proven by observation, not code inspection
    (mirrors ``tests/test_eval_thresholds.py``'s own helper)."""
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


def test_eustack_healthy_case_scores_pass_offline() -> None:
    """`sift eval` discovers eustack-healthy, scores it via the LLM-free path,
    and proves — by an OBSERVED empty request log — that it reached no
    inference endpoint at all (D-19-16)."""
    config = load_config({})
    client, http, calls = _recording_client()
    try:
        result = run_case(_EUSTACK_HEALTHY_CASE, client, config)
    finally:
        http.close()
    assert result.run_failed is False, result.error
    assert result.is_eustack is True
    assert result.eustack_case_pass is True
    assert calls == []


def test_eustack_healthy_raises_no_graded_flag() -> None:
    """D-19-15: hang_detected reads false AND no flag reaches warn/critical —
    two genuinely independent claims under D-19-17 (a fixture can reproduce
    hang-shaped figures without tripping a graded dimension, and vice versa),
    so a single assertion would leave half of D-19-15 unproven. The
    non-vacuity guard confirms the analyser actually graded something."""
    from sift.adapters.eustack import EustackAdapter
    from sift.pipeline.eustack import load_rules
    from sift.pipeline.eustack_progression import analyse_eustack_bundle

    config = load_config({})
    input_dir = _EUSTACK_HEALTHY_CASE / "input"
    adapter = EustackAdapter()
    adapter.input_root = input_dir
    events = list(adapter.parse(input_dir / "threaddump.txt", "eustack-healthy"))
    rules, rules_hash = load_rules(config.eustack.rules_path)
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, config.eustack.thresholds
    )
    truth = load_truth(_EUSTACK_HEALTHY_CASE / "truth.yaml")
    assert truth.expect_eustack is not None

    assert truth.expect_eustack.hang_detected is False
    assert not any(
        f.severity in ("warn", "critical") for f in bundle.saturation.flags
    )
    # Non-vacuity: the analyser really did grade the two percentage
    # dimensions and reported them info, not simply emit nothing.
    assert bundle.saturation.flags


def test_eustack_hang_twin_reproduces_identical_figures() -> None:
    """D-19-11/D-19-17: the shipped cosmetic-mutation twin reproduces the
    original's MEASURED figures exactly — proven against files that are
    demonstrably not copies (no shared TIDs, no shared addresses, differing
    bytes) BEFORE the figure-equality assertion, so the equality is not
    vacuously true of a copy-paste twin."""
    import re

    from sift.adapters.eustack import EustackAdapter
    from sift.pipeline.eustack import load_rules
    from sift.pipeline.eustack_progression import EustackBundle, analyse_eustack_bundle

    original_dir = _SUITE / "eustack-hang-pool-warehouse"
    twin_dir = _SUITE / "eustack-hang-pool-warehouse-mutated"

    original_text = (original_dir / "input" / "threaddump.txt").read_text(
        encoding="utf-8"
    )
    twin_text = (twin_dir / "input" / "threaddump.txt").read_text(encoding="utf-8")

    # Non-vacuity FIRST: the twin is demonstrably not a copy.
    assert original_text != twin_text
    original_addrs = set(re.findall(r"0x[0-9A-Fa-f]+", original_text))
    twin_addrs = set(re.findall(r"0x[0-9A-Fa-f]+", twin_text))
    assert original_addrs and twin_addrs and not (original_addrs & twin_addrs), (
        sorted(original_addrs & twin_addrs)[:5]
    )
    original_tids = set(re.findall(r"^TID (\d+):", original_text, re.M))
    twin_tids = set(re.findall(r"^TID (\d+):", twin_text, re.M))
    assert original_tids and not (original_tids & twin_tids), (
        sorted(original_tids & twin_tids)[:5]
    )

    config = load_config({})
    rules, rules_hash = load_rules(config.eustack.rules_path)

    def _bundle(case_dir: Path) -> EustackBundle:
        input_dir = case_dir / "input"
        adapter = EustackAdapter()
        adapter.input_root = input_dir
        events = list(
            adapter.parse(input_dir / "threaddump.txt", case_dir.name)
        )
        return analyse_eustack_bundle(
            events, rules, rules_hash, config.eustack.thresholds
        )

    original_bundle = _bundle(original_dir)
    twin_bundle = _bundle(twin_dir)

    assert (
        original_bundle.analysis.total_threads
        == twin_bundle.analysis.total_threads
    )

    def _pool_tuples(
        bundle: EustackBundle,
    ) -> set[tuple[str | None, int, int, int, float]]:
        return {
            (p.subsystem, p.total_threads, p.idle_threads, p.busy_threads, p.occupancy)
            for p in bundle.saturation.pools
        }

    def _dep_tuples(bundle: EustackBundle) -> set[tuple[str, int, int]]:
        return {
            (d.subsystem, d.thread_count, d.signature_count)
            for d in bundle.saturation.dependencies
        }

    assert _pool_tuples(original_bundle) == _pool_tuples(twin_bundle)
    assert _dep_tuples(original_bundle) == _dep_tuples(twin_bundle)


def test_only_the_healthy_case_is_marked_observed() -> None:
    """D-19-10: eustack-healthy is the sole case marked provenance: observed,
    so the synthetic-versus-observed evidence gap stays visible inside the
    harness rather than only in planning documents. At least one eu-stack
    case must be examined, so this guard cannot pass vacuously on a suite
    with zero eu-stack cases."""
    examined = 0
    observed: list[str] = []
    for case_dir in _case_dirs():
        truth = load_truth(case_dir / "truth.yaml")
        if truth.expect_eustack is None:
            continue
        examined += 1
        if truth.expect_eustack.provenance == "observed":
            observed.append(case_dir.name)
    assert examined >= 1
    assert observed == ["eustack-healthy"]


def test_hang_detected_is_consistent_with_declared_saturation() -> None:
    """WR-01 (19-REVIEW.md): ``hang_detected`` is read on exactly one case
    (the healthy negative, via ``test_eustack_healthy_raises_no_graded_flag``)
    and never compared against anything on either positive fixture — nothing
    stops ``eustack-hang-pool-warehouse/truth.yaml``'s ``hang_detected: true``
    drifting to ``false`` unnoticed.

    This is a declaration-vs-declaration self-consistency guard, per
    D-19-17/D-19-18: it compares the truth file's OWN ``hang_detected``
    against its OWN declared ``pools``/``dependencies`` figures. It never
    calls ``analyse_eustack_bundle`` and never reads a ``PoolOccupancy``/
    ``DependencyWait`` row, so it adds no threshold or grading to either --
    Phase 16's analyser surface stays untouched and uninvolved.

    A pool/dependency is "majority-busy" when its declared busy count is
    more than half the case's declared ``total_threads`` -- 25/35 for the
    warehouse-exhaustion fixtures versus 3/144 for the healthy capture's
    ordinary, non-exhausted waits. A bare `any(...) > 0` check (the review's
    illustrative fix) is too weak here: the healthy fixture legitimately
    declares a few non-zero waits (real threads really do wait on the
    warehouse and HTTP dependencies under normal load) without that being a
    hang, so it would misfire on the very fixture it's meant to protect.
    """
    for case_dir in _case_dirs():
        truth = load_truth(case_dir / "truth.yaml")
        expect = truth.expect_eustack
        if expect is None:
            continue
        total = expect.total_threads
        majority_busy = any(busy * 2 > total for busy in expect.pools.values()) or any(
            busy * 2 > total for busy in expect.dependencies.values()
        )
        assert expect.hang_detected == majority_busy, (
            f"{case_dir.name}: hang_detected={expect.hang_detected} but "
            f"declared majority-busy={majority_busy} (total_threads={total})"
        )


def test_eustack_gate_is_analyser_sensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-19-14: `sift eval` exits non-zero when the analyser stops
    reproducing a declared eu-stack figure — the gate is proven to bite, not
    merely to be configured. The INTACT run also proves D-19-16 (an
    eu-stack-only suite reaches a verdict with an observably empty request
    log); the NEUTERED run strips the warehouse-subsystem rule ONLY at the
    `load_rules` seam via monkeypatch, never on disk (T-19-16)."""
    import shutil

    from typer.testing import CliRunner

    from sift.cli import app

    scoped_suite = tmp_path / "eustack-suite"
    scoped_suite.mkdir()
    for name in (
        "eustack-healthy",
        "eustack-hang-pool-warehouse",
        "eustack-hang-pool-warehouse-mutated",
    ):
        shutil.copytree(_SUITE / name, scoped_suite / name)

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"data": []})

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.llm.bringup.make_http_client", _factory)
    runner = CliRunner()

    # INTACT: exit 0, and the recorded request log is observably empty — the
    # eu-stack-only subset genuinely reaches no inference endpoint (D-19-16).
    intact = runner.invoke(
        app,
        [
            "eval",
            "--suite",
            str(scoped_suite),
            "--thresholds",
            "eval/thresholds.toml",
        ],
    )
    assert intact.exit_code == 0, intact.output
    assert calls == []

    # NEUTERED: strip the warehouse-pattern rule at the load_rules SEAM only
    # (never editing src/sift/rules/eustack_roles.toml on disk) — the
    # warehouse-wait threads then classify unclassified, so the declared
    # pool/dependency figures stop reproducing.
    from sift.pipeline.eustack import load_rules as real_load_rules

    def _neutered_load_rules(
        rules_path: str | None = None,
    ) -> tuple[object, str]:
        rules, rules_hash = real_load_rules(rules_path)
        stripped = tuple(
            r
            for r in rules.rule
            if "CDSSQueryEngine::WaitUntilFinished" not in r.pattern
        )
        assert len(stripped) < len(rules.rule), (
            "the warehouse rule was not present to strip"
        )
        return rules.model_copy(update={"rule": stripped}), rules_hash

    monkeypatch.setattr("sift.pipeline.eustack.load_rules", _neutered_load_rules)

    neutered = runner.invoke(
        app,
        [
            "eval",
            "--suite",
            str(scoped_suite),
            "--thresholds",
            "eval/thresholds.toml",
        ],
    )
    assert neutered.exit_code != 0
    assert "eustack_detection_rate" in neutered.output

    # The shipped rules file on disk is untouched by the neuter above.
    diff = subprocess.run(
        ["git", "diff", "--stat", "src/sift/rules/eustack_roles.toml"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert diff.stdout == ""
