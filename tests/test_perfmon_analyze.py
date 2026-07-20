"""Perfmon correlation over the ``perfmon-denial`` golden case (PERF-07/PERF-08).

This module is the anti-vacuous foundation of Phase 14. The shipped Hartford
artefacts do not overlap in time (the CSV's last sample is ~12:39:39 while the
denial is ~12:39:47 — a ~7.7 s gap with zero in-span samples), so a golden case
built on them verbatim would yield ZERO citable perfmon ``event_id``s and pass
silently. ``test_fixture_overlaps`` is the guard that fails loudly if that ever
becomes true again: it asserts ``analyse_perfmon`` over the committed
``eval/cases/perfmon-denial/input/`` pair produces an episode-scope trend whose
counters carry at least one non-None ``at_denial_event_id`` — the mechanical
proof that a real perfmon sample falls inside the denial window and is citable.

Zero sockets: this module runs only the deterministic analysers over a locally
ingested case, so the autouse ``_no_network`` conftest guard is never tripped
(EVAL-05). Later waves (14-04 integration, 14-05 ``truth.yaml``) append to this
same module and reuse ``_ingest_perfmon_case``.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from sift.config import McmThresholdsConfig, SiftConfig, load_config
from sift.llm.budget import PromptBudget
from sift.llm.client import Endpoint, InferenceClient
from sift.models import Event
from sift.pipeline import hypothesise
from sift.pipeline.mcm import McmAnalysis, analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.perfmon import analyse_perfmon
from sift.pipeline.perfmon_facts import render_perfmon_facts
from sift.pipeline.salience import rank_clusters
from sift.store import CaseStore

Handler = Callable[[httpx.Request], httpx.Response]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PERFMON_CASE = _REPO_ROOT / "eval" / "cases" / "perfmon-denial"

# Frozen pre-phase byte-identity baselines for the perfmon-denial case (D-02,
# Pitfall 4). The NEITHER (no MCM, no perfmon) and MCM-ONLY assembled prompts must
# be byte-identical to their pre-perfmon-phase form — ``_apply_perfmon_block``
# removes the whole sentinel block, restoring the original bytes. A moved baseline
# is a regression to investigate, NEVER a constant to rebaseline away.
_NEITHER_PROMPT_HASH = "8c4341e77deee439"
_MCM_ONLY_PROMPT_HASH = "0e49cb2cbf6ebb27"

# A 16-hex id shaped like a citation token but never printed by
# ``render_perfmon_facts``, so it must NOT be in ``prompted_ids`` (fabricated
# perfmon-citation guard, T-14-07).
_FABRICATED_ID = "cafefeedcafefeed"

# A minimal schema-valid empty HypothesisSet (empty citations pass the gate).
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)

# A perfmon figure the correlator would never compute for the fixture — used to
# prove the model cannot inject it into the pre-built fact block (T-14-07).
_MODEL_WRONG_FIGURE = "counter peaked at 999999.999 MB (slope 424242.4242)"


def _ingest_perfmon_case(
    config: SiftConfig, case_dir: Path
) -> tuple[list[Event], McmAnalysis]:
    """Ingest a case's ``input/`` via the real sniff+ingest path (mirrors
    ``test_eval_cases._ingest_case``).

    Returns ``(events, mcm_analysis)``: the hydrated store events and the
    deterministic ``analyse_mcm`` result, so a later-wave test can drive
    ``analyse_perfmon(mcm, events)`` without re-ingesting. Both are pure values —
    the temp ``case.db`` is closed and discarded before returning, and event
    ``id``s are a stable function of ``(relpath, byte_offset)`` regardless of
    where the case was ingested.
    """
    from sift.cli import _ingest  # pyright: ignore[reportPrivateUsage]

    noise = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="sift-perfmon-test-") as tmp:
        db = Path(tmp) / "seed.db"
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            store = CaseStore(db)
            try:
                store.set_meta("input_dir", str((case_dir / "input").resolve()))
                store.set_meta("adapter_overrides", "[]")
                _ingest(case_dir.name, config, store)
                events = store.query_events()
                mcm = analyse_mcm(events, McmThresholdsConfig())
            finally:
                store.close()
    return events, mcm


def test_fixture_overlaps() -> None:
    """The golden pair is non-vacuous: >=1 counter carries a citable at-denial id.

    This is the single load-bearing guard of Wave 0. Proven demonstrably RED on
    the shipped non-overlapping pair (and on the log-only ``mcm-denial`` case):
    both yield an episode group with a ``non_overlap`` hazard, zero in-span
    samples, and therefore zero non-None ``at_denial_event_id``. It is GREEN here
    only because the authored CSV samples genuinely fall inside the resolved
    ``[window_start, denial_ts]`` window.
    """
    config = load_config({})
    events, mcm = _ingest_perfmon_case(config, _PERFMON_CASE)

    assert mcm.episodes, (
        "the denial log must auto-sniff as dsserrors and yield >=1 episode"
    )
    perfmon = analyse_perfmon(mcm, events)

    episode_groups = [g for g in perfmon.groups if g.scope == "episode"]
    assert episode_groups, "no episode-scope trend group was produced"

    citable = [
        counter.at_denial_event_id
        for group in episode_groups
        for counter in group.counters
        if counter.at_denial_event_id is not None
    ]
    assert citable, (
        "the perfmon-denial fixture no longer overlaps its denial window: no "
        "in-span sample yields a citable at_denial_event_id, so the golden case "
        "would be silently vacuous (RESEARCH Pitfall 1)"
    )

    # Source assertion (cited ⊆ store): the id names a real perfmon sample, not a
    # bare non-empty tuple. A non-None id that did not resolve here would mean the
    # trend cited an event the store never held.
    by_id = {event.event_id: event for event in events}
    assert by_id[citable[0]].source == "dssperfmon"


# --- Wave 2 (14-04): analyze-path splice, byte-identity, anti-hallucination ---


def _hset_body(cited_ids: list[str], narrative: str) -> str:
    """A schema-valid HypothesisSet JSON string with a caller-chosen narrative."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Perfmon-corroborated memory exhaustion",
                    "narrative": narrative,
                    "confidence": "high",
                    "confidence_reasoning": "Counter trend corroborates the denial.",
                    "supporting_event_ids": cited_ids,
                    "contradicting_evidence": None,
                    "suggested_next_steps": ["Raise the working-set ceiling"],
                }
            ],
            "timeline_summary": "Counters climbed into the denial window.",
            "unexplained_signals": [],
        }
    )


def _handler(
    *, hyp_content: str | None = None, prompts: list[str] | None = None
) -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions; capture generation prompts.

    Mirrors ``test_mcm_analyze._handler``. Embeddings return a fixed zero vector;
    the generation call's first user message is appended to ``prompts`` so a test
    can assert the perfmon block is present.
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


@contextlib.contextmanager
def _perfmon_store(config: SiftConfig, case_dir: Path, db: Path):
    """Ingest a case into a PERSISTENT store (kept open) for assembly-level tests.

    Unlike ``_ingest_perfmon_case`` (which discards the temp db), this yields a
    live ``CaseStore`` so a test can rank, assemble and hypothesise over it.
    """
    from sift.cli import _ingest  # pyright: ignore[reportPrivateUsage]

    noise = io.StringIO()
    with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
        store = CaseStore(db)
        store.set_meta("input_dir", str((case_dir / "input").resolve()))
        store.set_meta("adapter_overrides", "[]")
        _ingest(case_dir.name, config, store)
    try:
        yield store
    finally:
        store.close()


def _assemble_blocks(
    store: CaseStore,
    client: InferenceClient,
    *,
    with_mcm: bool,
    with_perfmon: bool,
) -> tuple[set[str], str]:
    """Assemble the prompt the way ``hypothesise`` does, toggling each fact block.

    Mirrors ``hypothesise``'s assembly prep and builds the MCM / perfmon blocks
    from the store (each independently omitted when its flag is False), returning
    ``(prompted_ids, prompt)`` so citability + byte-identity can be asserted.
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
    _msgs, prompted_ids, prompt = hypothesise._assemble(  # pyright: ignore[reportPrivateUsage]
        ranked, group_index, messages, template, None, budget,
        mcm_block=mcm_block, perfmon_block=perfmon_block,
    )
    return prompted_ids, prompt


def _citable_perfmon_id(store: CaseStore) -> str:
    """A citable ``[evt:]`` id printed by ``render_perfmon_facts`` for a real
    dssperfmon sample (not a dsserrors boundary), so the citability test proves a
    genuine perfmon figure is citable."""
    events = store.query_events()
    mcm = analyse_mcm(events, McmThresholdsConfig())
    _block, pids = render_perfmon_facts(analyse_perfmon(mcm, events))
    by_id = {e.event_id: e for e in events}
    perfmon_ids = sorted(i for i in pids if by_id[i].source == "dssperfmon")
    assert perfmon_ids, "the fixture must print >=1 citable dssperfmon id"
    return perfmon_ids[0]


def test_four_combination_byte_identity(tmp_path: Path) -> None:
    """D-02: each sentinel block is stripped independently, so the NEITHER and
    MCM-ONLY assembled prompts are byte-identical to their frozen pre-perfmon-phase
    baselines — perfmon presence can never perturb them. All four presence combos
    (neither / MCM-only / perfmon-only / both) are distinct where a block is added,
    and the two no-new-data hashes equal frozen constants (not merely each other)."""
    config = load_config({})
    with _perfmon_store(config, _PERFMON_CASE, tmp_path / "case.db") as store:
        c = _client()
        _in, p_neither = _assemble_blocks(store, c, with_mcm=False, with_perfmon=False)
        _im, p_mcm = _assemble_blocks(store, c, with_mcm=True, with_perfmon=False)
        _ip, p_perf = _assemble_blocks(store, c, with_mcm=False, with_perfmon=True)
        _ib, p_both = _assemble_blocks(store, c, with_mcm=True, with_perfmon=True)

    h_neither = hypothesise._prompt_hash(p_neither)  # pyright: ignore[reportPrivateUsage]
    h_mcm = hypothesise._prompt_hash(p_mcm)  # pyright: ignore[reportPrivateUsage]
    h_perf = hypothesise._prompt_hash(p_perf)  # pyright: ignore[reportPrivateUsage]
    h_both = hypothesise._prompt_hash(p_both)  # pyright: ignore[reportPrivateUsage]

    # Frozen baselines (source assertion): perfmon stripping restores pre-phase bytes.
    assert h_neither == _NEITHER_PROMPT_HASH
    assert h_mcm == _MCM_ONLY_PROMPT_HASH
    # Adding a block perturbs the prompt; the four combos are all distinct.
    assert h_perf != h_neither, "perfmon-present prompt must differ from no-data"
    assert h_both != h_mcm, "perfmon on top of MCM must differ from MCM-only"
    assert len({h_neither, h_mcm, h_perf, h_both}) == 4


def test_model_cannot_alter_perfmon_figures(tmp_path: Path) -> None:
    """T-14-07: the surfaced perfmon figures are a pure function of the correlator,
    built BEFORE generation — a model echoing a WRONG figure in its narrative cannot
    change the verbatim fact block spliced into the prompt."""
    config = load_config({})
    with _perfmon_store(config, _PERFMON_CASE, tmp_path / "case.db") as store:
        events = store.query_events()
        mcm = analyse_mcm(events, McmThresholdsConfig())
        block, _ids = render_perfmon_facts(analyse_perfmon(mcm, events))
        assert block, "the overlapping fixture yields a non-empty perfmon block"
        citable = _citable_perfmon_id(store)
        prompts: list[str] = []
        client = _client(
            _handler(
                hyp_content=_hset_body([citable], _MODEL_WRONG_FIGURE),
                prompts=prompts,
            )
        )
        hypothesise.hypothesise(store, client, top_clusters=20, incident_time=None)
    assert prompts
    prompt = prompts[0]
    # The correlator's verbatim block reached the prompt…
    assert block in prompt
    # …and the model's fabricated figure never entered it (prompt built pre-reply).
    assert _MODEL_WRONG_FIGURE not in prompt


def test_perfmon_id_citable_and_fabricated_flagged(tmp_path: Path) -> None:
    """D-05 / PERF-07: a hypothesis citing a printed perfmon id passes the citation
    gate (the id is unioned into ``prompted_ids``), while a fabricated perfmon id is
    FLAGGED (``cited ⊄ prompted``) — cited ⊆ prompted ⊆ store preserved."""
    config = load_config({})
    with _perfmon_store(config, _PERFMON_CASE, tmp_path / "case.db") as store:
        citable = _citable_perfmon_id(store)

        # Assemble-level: the printed perfmon id IS citable; a fabricated one is not.
        ids, _prompt = _assemble_blocks(
            store, _client(), with_mcm=True, with_perfmon=True
        )
        assert citable in ids
        assert _FABRICATED_ID not in ids

        # End-to-end: citing the real perfmon id -> a VALID, clean run.
        good = hypothesise.hypothesise(
            store,
            _client(_handler(hyp_content=_hset_body([citable], "counter climbed"))),
            top_clusters=20,
            incident_time=None,
        )
        assert good.failed is False
        assert good.citations_valid is True
        good_rows = store.query_hypotheses()
        assert good_rows and good_rows[0].citations_valid is True
        assert citable in good_rows[0].supporting_event_ids

        # End-to-end: citing a FABRICATED perfmon id -> FLAGGED (degraded, row invalid).
        bad = hypothesise.hypothesise(
            store,
            _client(
                _handler(hyp_content=_hset_body([_FABRICATED_ID], "counter climbed"))
            ),
            top_clusters=20,
            incident_time=None,
        )
        assert bad.citations_valid is False
        bad_rows = store.query_hypotheses()
        assert bad_rows and bad_rows[0].citations_valid is False
