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

import contextlib
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx

from sift.adapters.eustack import EustackAdapter
from sift.config import (
    EustackThresholdsConfig,
    McmThresholdsConfig,
    SiftConfig,
    load_config,
)
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

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PERFMON_CASE = _REPO_ROOT / "eval" / "cases" / "perfmon-denial"
_EUSTACK_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eustack"
_EUSTACK_FIXTURE = _EUSTACK_FIXTURES_DIR / "threaddump.txt"

# A minimal schema-valid empty HypothesisSet (empty citations pass the gate).
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)

# A thread-population figure the analyser could never compute for the fixture
# — orders of magnitude beyond any real thread count, phrased as an eu-stack
# role claim (T-14-07 pattern, here for eu-stack).
_MODEL_WRONG_FIGURE = "9,999,999 threads idle-parked"


def _hset_body(cited_ids: list[str], narrative: str) -> str:
    """A schema-valid HypothesisSet JSON string with a caller-chosen narrative."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Eu-stack thread saturation",
                    "narrative": narrative,
                    "confidence": "high",
                    "confidence_reasoning": "Thread composition corroborates this.",
                    "supporting_event_ids": cited_ids,
                    "contradicting_evidence": None,
                    "suggested_next_steps": ["Inspect the flagged subsystem"],
                }
            ],
            "timeline_summary": "Thread population composition observed at capture.",
            "unexplained_signals": [],
        }
    )

# Frozen pre-eu-stack-phase byte-identity baselines (D-12), copied verbatim
# from ``tests/test_perfmon_analyze.py`` — the fourth sentinel block must not
# perturb them.
_NEITHER_PROMPT_HASH = "8c4341e77deee439"
_MCM_ONLY_PROMPT_HASH = "0e49cb2cbf6ebb27"

# The one missing baseline (D-18): PERFMON-ONLY over the perfmon-denial case,
# measured against the PRE-PHASE (pre-Task-1) ``triage.md`` — i.e. against
# ``git show HEAD~1:src/sift/prompts/triage.md`` at the commit immediately
# before this eu-stack phase's Task 1 landed — via ``hypothesise._assemble``
# with ``mcm_block=None`` and the real ``render_perfmon_facts`` block. It is
# also reproduced identically against the CURRENT ``triage.md`` with
# ``eustack_block=None`` (the residue-free strip this task's byte-identity
# tests below assert), confirming the fourth sentinel block adds no bytes
# when eu-stack data is absent.
_PERFMON_ONLY_PROMPT_HASH = "e3dc94ae1b32cd90"


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


@contextlib.contextmanager
def _ingested_store(config: SiftConfig, input_dir: Path, db: Path):
    """Ingest ``input_dir`` into a PERSISTENT store (kept open) via the real
    `sift ingest` path — mirrors ``test_perfmon_analyze._perfmon_store``."""
    from sift.cli import _ingest  # pyright: ignore[reportPrivateUsage]

    noise = io.StringIO()
    with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
        store = CaseStore(db)
        store.set_meta("input_dir", str(input_dir.resolve()))
        store.set_meta("adapter_overrides", "[]")
        _ingest(db.parent.name, config, store)
    try:
        yield store
    finally:
        store.close()


def _perfmon_store(config: SiftConfig, db: Path):
    """The perfmon-denial case (no eu-stack data) as a persistent store."""
    return _ingested_store(config, _PERFMON_CASE / "input", db)


def _eustack_carrying_store(config: SiftConfig, tmp_path: Path, db: Path):
    """The perfmon-denial input files PLUS the eu-stack fixture, ingested once
    into one store — the D-18 EUSTACK-ONLY / ALL-THREE combinations must be
    compared within this SAME store (never cross-store), since ingesting
    eu-stack events changes the cluster set and therefore the excerpt lines.
    """
    combined_input = tmp_path / "input"
    combined_input.mkdir(parents=True, exist_ok=True)
    for src in (_PERFMON_CASE / "input").iterdir():
        shutil.copy2(src, combined_input / src.name)
    shutil.copy2(_EUSTACK_FIXTURE, combined_input / _EUSTACK_FIXTURE.name)
    return _ingested_store(config, combined_input, db)


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


# --- Task 2: byte-identity gate (D-12, D-18) ---------------------------------


def test_no_eustack_data_byte_identical_to_baseline(tmp_path: Path) -> None:
    """D-12/SC2: over a store with NO eu-stack events at all (the
    perfmon-denial case), ``render_eustack_facts`` returns ``("", set())`` and
    the assembled NEITHER, MCM-ONLY and PERFMON-ONLY prompt hashes equal their
    three frozen pre-phase constants exactly — the fourth sentinel block strips
    residue-free."""
    config = load_config({})
    with _perfmon_store(config, tmp_path / "case.db") as store:
        events = store.query_events()
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        assert render_eustack_facts(bundle, events) == ("", set())

        client = _client()
        _in, p_neither = _assemble_blocks(store, client)
        _im, p_mcm = _assemble_blocks(store, client, with_mcm=True)
        _ip, p_perfmon = _assemble_blocks(store, client, with_perfmon=True)

    assert hypothesise._prompt_hash(p_neither) == _NEITHER_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]
    assert hypothesise._prompt_hash(p_mcm) == _MCM_ONLY_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]
    assert hypothesise._prompt_hash(p_perfmon) == _PERFMON_ONLY_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]


def test_five_combination_byte_identity(tmp_path: Path) -> None:
    """D-18: the minimal 5-combination subset, not the full 2x2x2 matrix.

    Combinations 1-3 on the no-eu-stack store (perfmon-denial): NEITHER,
    MCM-ONLY and PERFMON-ONLY each equal their frozen constant — unchanged by
    this phase. Combinations 4-5 on an eu-stack-carrying store (perfmon-denial
    input files plus the eu-stack fixture, ingested once): EUSTACK-ONLY must
    differ from that SAME store's NEITHER hash, and ALL-THREE must differ from
    that same store's MCM-plus-perfmon hash. Comparisons stay within one store
    each — a cross-store hash comparison would be meaningless, since ingesting
    eu-stack events changes the cluster set and therefore the excerpt lines.
    """
    config = load_config({})

    with _perfmon_store(config, tmp_path / "no_eustack" / "case.db") as store:
        client = _client()
        _in, p_neither = _assemble_blocks(store, client)
        _im, p_mcm = _assemble_blocks(store, client, with_mcm=True)
        _ip, p_perfmon = _assemble_blocks(store, client, with_perfmon=True)

    assert hypothesise._prompt_hash(p_neither) == _NEITHER_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]
    assert hypothesise._prompt_hash(p_mcm) == _MCM_ONLY_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]
    assert hypothesise._prompt_hash(p_perfmon) == _PERFMON_ONLY_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]

    with _eustack_carrying_store(
        config, tmp_path / "eustack_in", tmp_path / "eustack_in" / "case.db"
    ) as store:
        client = _client()
        events = store.query_events()
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        eustack_block_text, _ids = render_eustack_facts(bundle, events)
        assert eustack_block_text, (
            "the eu-stack-carrying store must yield a non-empty block "
            "(non-vacuity guard)"
        )

        _sne, es_neither = _assemble_blocks(store, client)
        _se, es_eustack_only = _assemble_blocks(store, client, with_eustack=True)
        _smp, es_mcm_perfmon = _assemble_blocks(
            store, client, with_mcm=True, with_perfmon=True
        )
        _sall, es_all_three = _assemble_blocks(
            store, client, with_mcm=True, with_perfmon=True, with_eustack=True
        )

    h_es_neither = hypothesise._prompt_hash(es_neither)  # pyright: ignore[reportPrivateUsage]
    h_eustack_only = hypothesise._prompt_hash(es_eustack_only)  # pyright: ignore[reportPrivateUsage]
    h_mcm_perfmon = hypothesise._prompt_hash(es_mcm_perfmon)  # pyright: ignore[reportPrivateUsage]
    h_all_three = hypothesise._prompt_hash(es_all_three)  # pyright: ignore[reportPrivateUsage]

    assert h_eustack_only != h_es_neither, (
        "eu-stack-present prompt must differ from that store's own no-data prompt"
    )
    assert h_all_three != h_mcm_perfmon, (
        "eu-stack on top of MCM+perfmon must differ from MCM+perfmon-only"
    )
    assert len({h_es_neither, h_eustack_only, h_mcm_perfmon, h_all_three}) == 4


# --- Task 3: anti-hallucination + eval-path parity (SC3, D-05, D-16) --------


def test_model_cannot_alter_eustack_figures(tmp_path: Path) -> None:
    """T-14-07 pattern, here for eu-stack: the surfaced eu-stack figures are a
    pure function of ``render_eustack_facts``, built BEFORE generation — a
    model echoing a WRONG figure in its narrative cannot change the fact block
    spliced into the prompt."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_eustack(store)
        events = store.query_events()
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        # The verbatim analyser block, computed independently of any model reply.
        block, _ids = render_eustack_facts(bundle, events)
        assert block, "the threaddump.txt fixture must yield a non-empty block"

        prompts: list[str] = []
        client = _client(
            _handler(
                hyp_content=_hset_body([], _MODEL_WRONG_FIGURE),
                prompts=prompts,
            )
        )
        hypothesise.hypothesise(store, client, top_clusters=20, incident_time=None)
        assert prompts
        prompt = prompts[0]
        # The real eu-stack figures reached the prompt…
        assert block in prompt
        # …the model's planted figure never did (prompt built pre-reply).
        assert _MODEL_WRONG_FIGURE not in prompt
    finally:
        store.close()


def test_eval_path_parity_default_eustack_config(tmp_path: Path) -> None:
    """``hypothesise`` called WITHOUT ``eustack_rules_path``/``eustack_thresholds``
    (as the eval harness does) still injects the eu-stack block for an
    eu-stack-seeded case — proving the packaged-default rules path and the
    ``or EustackThresholdsConfig()`` fallback work on the path the eval
    harness takes, exactly as the MCM/perfmon analogs prove for their own
    defaults."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_eustack(store)
        events = store.query_events()
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        block, _ids = render_eustack_facts(bundle, events)
        assert block

        prompts: list[str] = []
        client = _client(_handler(prompts=prompts))
        hypothesise.hypothesise(store, client, top_clusters=20, incident_time=None)
        assert prompts
        assert block in prompts[0]
    finally:
        store.close()
