"""Eu-stack facts injection into `sift analyze` (EUS-10, Plan 18-01).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` —
the autouse ``_no_network`` conftest fixture stays active (EVAL-05). Mirrors
``tests/test_mcm_analyze.py``/``tests/test_perfmon_analyze.py``: the eu-stack
figures the deterministic ``analyse_eustack_bundle`` computes ARE citable
(the KB inversion, D-01) — ids the renderer prints as ``[evt:<id>]`` tokens are
unioned into ``prompted_ids``, while a model-planted wrong figure never reaches
the assembled prompt because it is built BEFORE generation (T-14-07 pattern,
here for eu-stack).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from sift.adapters.eustack import EustackAdapter
from sift.config import EustackThresholdsConfig, McmThresholdsConfig
from sift.llm.budget import PromptBudget
from sift.llm.client import Endpoint, InferenceClient
from sift.pipeline import hypothesise
from sift.pipeline.eustack import load_rules
from sift.pipeline.eustack_facts import render_eustack_facts
from sift.pipeline.eustack_progression import analyse_eustack_bundle
from sift.pipeline.mcm import analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.perfmon import analyse_perfmon
from sift.pipeline.perfmon_facts import render_perfmon_facts
from sift.pipeline.salience import rank_clusters
from sift.store import CaseStore

Handler = Callable[[httpx.Request], httpx.Response]

_EUSTACK_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eustack"
_EUSTACK_FIXTURE = _EUSTACK_FIXTURES_DIR / "threaddump.txt"

# A minimal schema-valid empty HypothesisSet (empty citations pass the gate).
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)


def _handler(
    *, hyp_content: str | None = None, prompts: list[str] | None = None
) -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions; capture generation prompts.

    Mirrors ``test_mcm_analyze._handler`` / ``test_perfmon_analyze._handler``.
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


def _client(handler: Handler | None = None) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler or _handler()))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _seed_eustack(store: CaseStore, rel: str = "threaddump.txt") -> None:
    """Ingest the eu-stack thread-dump fixture through the real adapter."""
    adapter = EustackAdapter()
    adapter.input_root = _EUSTACK_FIXTURES_DIR
    events = list(adapter.parse(_EUSTACK_FIXTURES_DIR / rel, "case1"))
    with store.transaction():
        store.insert_events(events)


def _assemble_blocks(
    store: CaseStore,
    client: InferenceClient,
    *,
    with_mcm: bool = False,
    with_perfmon: bool = False,
    with_eustack: bool = False,
) -> tuple[set[str], str]:
    """Assemble the prompt the way ``hypothesise`` does, toggling each fact block.

    Mirrors ``test_perfmon_analyze._assemble_blocks``, extended with a
    ``with_eustack`` flag: builds the eu-stack block from the store's own
    events via the packaged default rules, exactly as ``hypothesise`` does
    when no ``eustack_rules_path``/``eustack_thresholds`` override is given.
    """
    groups = store.query_template_groups()
    ranked = rank_clusters(store.query_clusters(), groups, incident_time=None)
    group_index = {g.template_id: g for g in groups}
    messages = hypothesise._gather_exemplar_messages(store, groups)  # pyright: ignore[reportPrivateUsage]
    template = hypothesise._load_triage_template()  # pyright: ignore[reportPrivateUsage]
    budget = PromptBudget(client, 8192, 1024)  # pyright: ignore[reportArgumentType]
    events = store.query_events()
    mcm = analyse_mcm(events, McmThresholdsConfig())
    mcm_block = render_mcm_facts(mcm) if with_mcm else None
    perfmon_block = (
        render_perfmon_facts(analyse_perfmon(mcm, events)) if with_perfmon else None
    )
    eustack_block = None
    if with_eustack:
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        eustack_block = render_eustack_facts(bundle, events)
    _msgs, prompted_ids, prompt = hypothesise._assemble(  # pyright: ignore[reportPrivateUsage]
        ranked, group_index, messages, template, None, budget,
        mcm_block=mcm_block, perfmon_block=perfmon_block, eustack_block=eustack_block,
    )
    return prompted_ids, prompt


def test_eustack_block_injected_and_ids_citable(tmp_path: Path) -> None:
    """SC1: an eu-stack-carrying case splices a role-composition block into the
    assembled prompt; every id the renderer prints is citable (in
    ``prompted_ids``) and resolves to a real ``event_id`` in the store — never
    a vacuous pass (the block must carry >=1 ``[evt:`` token and >=1
    role-composition line)."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_eustack(store)
        events = store.query_events()
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        block, block_ids = render_eustack_facts(bundle, events)
        assert block, "the threaddump.txt fixture must yield a non-empty block"
        assert "[evt:" in block
        assert "cited as exemplars" in block

        ids, prompt = _assemble_blocks(store, _client(), with_eustack=True)

        # The rendered block reached the assembled prompt verbatim…
        assert block in prompt
        # …every printed id is citable…
        assert block_ids, "the block must print >=1 citable id"
        assert block_ids <= ids
        # …and every one of those ids is a real stored event_id.
        by_id = {event.event_id: event for event in events}
        for eid in block_ids:
            assert eid in by_id
    finally:
        store.close()
