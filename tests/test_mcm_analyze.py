"""MCM-facts injection into `sift analyze` (MCM-06, Plan 11-02).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` — the
autouse ``_no_network`` conftest fixture stays active (EVAL-05). The load-bearing
inversion under test (vs KB, D-01) is that MCM facts ARE citable: the ids the
deterministic ``render_mcm_facts`` prints as ``[evt:<id>]`` tokens are unioned
into ``prompted_ids``, so a hypothesis MAY validly cite an MCM denial event
(``cited ⊆ prompted ⊆ store`` preserved), while an id never printed is still
FLAGGED. Figures are a pure function of ``analyse_mcm``, built before generation,
so a model that echoes a mutated number cannot change the surfaced fact (T-11-02).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.cli import app
from sift.config import ClusteringConfig, McmThresholdsConfig, load_config
from sift.llm.budget import PromptBudget
from sift.llm.client import Endpoint, InferenceClient
from sift.pipeline import cluster, dedup, hypothesise
from sift.pipeline.mcm import analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.salience import rank_clusters
from sift.store import CaseStore, case_db_path

Handler = Callable[[httpx.Request], httpx.Response]

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"

# A 16-hex id shaped like a citation token but never printed by render_mcm_facts,
# so it must NOT be in prompted_ids (fabricated-citation guard, T-11-03).
_FABRICATED_ID = "cafefeedcafefeed"

# A minimal schema-valid empty HypothesisSet (empty citations pass the gate).
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)

# A figure the analyser would never compute for the Hartford slice — used to prove
# the model cannot inject it into the surfaced facts (T-11-02).
_MODEL_WRONG_FIGURE = "working set was 999.9% of virtual memory"

# A distinctive KB runbook chunk for the coexistence test (KB text threads into
# the prompt but never becomes citable, D-01).
_KB_RUNBOOK = (
    "RUNBOOK mcm-tier: when AvailableMCM falls to zero, raise the working-set "
    "ceiling and restart the affected report jobs before the server stalls."
)


def _hset_body(cited_ids: list[str], narrative: str) -> str:
    """A schema-valid HypothesisSet JSON string with a caller-chosen narrative."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "MCM memory exhaustion",
                    "narrative": narrative,
                    "confidence": "high",
                    "confidence_reasoning": "Denial episode corroborated.",
                    "supporting_event_ids": cited_ids,
                    "contradicting_evidence": None,
                    "suggested_next_steps": ["Raise the working-set ceiling"],
                }
            ],
            "timeline_summary": "Memory pressure built, then MCM denied a request.",
            "unexplained_signals": [],
        }
    )


def _handler(
    *, hyp_content: str | None = None, prompts: list[str] | None = None
) -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions; capture generation prompts.

    Every embedding request returns a fixed zero vector (clustering shape is
    irrelevant here — the MCM facts derive from ``query_events``, not clusters).
    The generation call carries ``response_format``; its first user message is
    appended to ``prompts`` so a test can assert the MCM block is present.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            data = [{"index": i, "embedding": [0.0] * 8} for i in range(len(inputs))]
            return httpx.Response(200, json={"data": data})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            if "response_format" in payload:
                if prompts is not None:
                    prompts.append(payload["messages"][0]["content"])
                content = hyp_content if hyp_content is not None else _VALID_HYPSET
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": content}}]}
                )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "{}"}}]}
            )
        return httpx.Response(404)

    return handler


def _client(handler: Handler) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _seed_dsserrors(store: CaseStore, rel: str = "hartford_deny_slice.log") -> None:
    """Ingest the Hartford deny slice through the real adapter + dedup + cluster."""
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, "case1"))
    with store.transaction():
        store.insert_events(events)
    dedup.rebuild_template_groups(store)
    cluster.cluster_and_label(
        store, _client(_handler()), ClusteringConfig(), label=False
    )


def _denial_id(store: CaseStore) -> str:
    analysis = analyse_mcm(store.query_events(), McmThresholdsConfig())
    assert analysis.episodes  # the Hartford slice has exactly one denial episode
    return analysis.episodes[0].episode.denial_event_id


def _assemble_mcm(
    store: CaseStore,
    client: InferenceClient,
    *,
    kb_context: list[str] | None = None,
    thresholds: McmThresholdsConfig | None = None,
) -> tuple[set[str], str]:
    """Assemble the prompt the way hypothesise would, with MCM facts spliced in.

    Mirrors hypothesise's assembly prep (rank -> exemplar messages -> template ->
    budget) and builds the MCM block from the store, returning (prompted_ids,
    prompt) so citability + injection can be asserted directly.
    """
    clusters = store.query_clusters()
    groups = store.query_template_groups()
    ranked = rank_clusters(clusters, groups, incident_time=None)
    group_index = {g.template_id: g for g in groups}
    messages = hypothesise._gather_exemplar_messages(store, groups)  # pyright: ignore[reportPrivateUsage]
    template = hypothesise._load_triage_template()  # pyright: ignore[reportPrivateUsage]
    budget = PromptBudget(client, 8192, 1024)  # pyright: ignore[reportArgumentType]
    mcm_block = render_mcm_facts(
        analyse_mcm(store.query_events(), thresholds or McmThresholdsConfig())
    )
    _msgs, prompted_ids, prompt = hypothesise._assemble(  # pyright: ignore[reportPrivateUsage]
        ranked, group_index, messages, template, None, budget,
        kb_context=kb_context, mcm_block=mcm_block,
    )
    return prompted_ids, prompt


# --- injection + citability (criterion 1) ------------------------------------


def test_mcm_block_injected_and_denial_id_citable(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_dsserrors(store)
        denial_id = _denial_id(store)
        ids, prompt = _assemble_mcm(store, _client(_handler()))
        # The MCM denial fact line reached the prompt…
        assert f"[evt:{denial_id}] MCM denial" in prompt
        # …and its id is CITABLE (in prompted_ids) — the KB inversion.
        assert denial_id in ids
    finally:
        store.close()


def test_fabricated_id_not_citable(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_dsserrors(store)
        ids, _prompt = _assemble_mcm(store, _client(_handler()))
        # An id never printed by render_mcm_facts is not in the citable universe.
        assert _FABRICATED_ID not in ids
    finally:
        store.close()


def test_eval_path_parity_default_thresholds(tmp_path: Path) -> None:
    """hypothesise called WITHOUT mcm_thresholds (as eval/runner does) still
    injects the MCM block for a dsserrors case — the golden case is non-vacuous."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_dsserrors(store)
        denial_id = _denial_id(store)
        prompts: list[str] = []
        client = _client(_handler(prompts=prompts))
        hypothesise.hypothesise(
            store, client, top_clusters=20, incident_time=None
        )
        assert prompts
        assert any(f"[evt:{denial_id}] MCM denial" in p for p in prompts)
    finally:
        store.close()


# --- anti-hallucination + determinism + coexistence (criterion 2) ------------


def test_model_cannot_alter_mcm_figures(tmp_path: Path) -> None:
    """The surfaced MCM figures are a pure function of analyse_mcm, built BEFORE
    generation: a model echoing a WRONG figure in its narrative cannot change the
    fact block spliced into the prompt (T-11-02)."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_dsserrors(store)
        denial_id = _denial_id(store)
        # The verbatim analyser block, computed independently of any model reply.
        block, _ids = render_mcm_facts(
            analyse_mcm(store.query_events(), McmThresholdsConfig())
        )
        assert block  # the Hartford slice yields a non-empty fact block
        prompts: list[str] = []
        client = _client(
            _handler(
                hyp_content=_hset_body([denial_id], _MODEL_WRONG_FIGURE),
                prompts=prompts,
            )
        )
        hypothesise.hypothesise(store, client, top_clusters=20, incident_time=None)
        assert prompts
        prompt = prompts[0]
        # The analyser's verbatim fact block reached the prompt…
        assert block in prompt
        # …and the model's wrong figure never entered it (prompt built pre-reply).
        assert _MODEL_WRONG_FIGURE not in prompt
    finally:
        store.close()


def test_mcm_block_deterministic(tmp_path: Path) -> None:
    """Assembling the same case twice yields byte-identical prompts — the MCM
    facts are model-free and re-run stable (criterion 2)."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_dsserrors(store)
        _ids1, prompt1 = _assemble_mcm(store, _client(_handler()))
        _ids2, prompt2 = _assemble_mcm(store, _client(_handler()))
        assert prompt1 == prompt2
    finally:
        store.close()


def test_mcm_and_kb_coexist(tmp_path: Path) -> None:
    """In one run MCM (citable) and KB (non-citable) behave independently: MCM ids
    enter prompted_ids, the KB text threads into the prompt but adds no id."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_dsserrors(store)
        denial_id = _denial_id(store)
        ids, prompt = _assemble_mcm(
            store, _client(_handler()), kb_context=[_KB_RUNBOOK]
        )
        # MCM facts ARE citable…
        assert denial_id in ids
        # …the KB runbook threaded into the prompt…
        assert _KB_RUNBOOK in prompt
        # …yet a KB-shaped fabricated id is NOT citable (KB stays non-citable).
        assert _FABRICATED_ID not in ids
    finally:
        store.close()


# --- CLI-level: `sift analyze` threads config.mcm.thresholds (MCM-06, D-17) ---


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Bind the analyze httpx.Client to a MockTransport (the EVAL-05 seam)."""

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.cli._make_http_client", _factory)


def _seed_cli_case(case: str) -> str:
    """Ingest the Hartford deny slice into the CLI's data dir; return denial_id.

    Mirrors the `sift ingest` write path (events + template groups) so a later
    `sift analyze` run clusters + hypothesises over a real dsserrors case. The
    denial id is threshold-independent (detection does not read thresholds), so
    it is stable regardless of any `[mcm.thresholds]` override under test.
    """
    store = CaseStore(case_db_path(load_config().data_dir, case))
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / "hartford_deny_slice.log", case))
    try:
        with store.transaction():
            store.insert_events(events)
        dedup.rebuild_template_groups(store)
        return _denial_id(store)
    finally:
        store.close()


def _write_mcm_config(body: str) -> None:
    """Write a `[mcm.thresholds]` config.toml into the isolated XDG_CONFIG_HOME."""
    cfg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(body, encoding="utf-8")


def test_analyze_surfaces_mcm_facts_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real `sift analyze` run over the dsserrors denial case surfaces the MCM
    fact block and a hypothesis citing the MCM denial event is VALID (the
    injection made the id citable) — a clean success, never a crash (D-17)."""
    denial_id = _seed_cli_case("mcmcase")
    prompts: list[str] = []
    handler = _handler(
        hyp_content=_hset_body([denial_id], "MCM denial episode"), prompts=prompts
    )
    _patch_http(monkeypatch, handler)
    result = runner.invoke(app, ["analyze", "mcmcase", "--no-label"])
    # Exit-code contract honoured (0 success / 3 degraded), never a traceback.
    assert result.exit_code in (0, 3), result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # The MCM denial fact line reached the real triage prompt…
    assert prompts
    assert any(f"[evt:{denial_id}] MCM denial" in p for p in prompts)
    # …and citing the MCM denial id is VALID (a clean exit 0), because injection
    # unioned it into prompted_ids.
    assert result.exit_code == 0, result.output
    store = CaseStore(case_db_path(load_config().data_dir, "mcmcase"))
    try:
        rows = store.query_hypotheses()
        assert rows and rows[0].citations_valid is True
        assert denial_id in rows[0].supporting_event_ids
    finally:
        store.close()


def test_analyze_threads_mcm_thresholds_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An `[mcm.thresholds]` operator override reaches the analyser THROUGH the
    CLI: lowering the other-processes critical cut-point below the slice's 18.5%
    flips that flag's tier warn→critical in the injected fact block — proving
    `cli.analyze` threads `config.mcm.thresholds`, not a hard-coded default."""
    _write_mcm_config(
        "[mcm.thresholds]\n"
        "other_processes_pct_physical = { warn = 5, critical = 15 }\n"
    )
    _seed_cli_case("mcmcfg")
    prompts: list[str] = []
    _patch_http(monkeypatch, _handler(hyp_content=_VALID_HYPSET, prompts=prompts))
    result = runner.invoke(app, ["analyze", "mcmcfg", "--no-label"])
    assert result.exit_code == 0, result.output
    assert prompts
    prompt = prompts[0]
    # The override reached the analyser: the tier is now CRITICAL, not warn.
    assert "critical flag other_processes_pct_physical" in prompt
    assert "warn flag other_processes_pct_physical" not in prompt
