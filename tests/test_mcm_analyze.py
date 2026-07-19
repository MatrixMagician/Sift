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
from collections.abc import Callable
from pathlib import Path

import httpx

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.config import ClusteringConfig, McmThresholdsConfig
from sift.llm.budget import PromptBudget
from sift.llm.client import Endpoint, InferenceClient
from sift.pipeline import cluster, dedup, hypothesise
from sift.pipeline.mcm import analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.salience import rank_clusters
from sift.store import CaseStore

Handler = Callable[[httpx.Request], httpx.Response]

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"

# A 16-hex id shaped like a citation token but never printed by render_mcm_facts,
# so it must NOT be in prompted_ids (fabricated-citation guard, T-11-03).
_FABRICATED_ID = "cafefeedcafefeed"

# A minimal schema-valid empty HypothesisSet (empty citations pass the gate).
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
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
