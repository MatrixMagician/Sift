"""Citation-gated hypothesis generation — the anti-hallucination core (SPEC §5.5).

This module mirrors ``cluster.py``'s pipeline contract: it is typer-free and
print-free; persistence flows through ``CaseStore`` only. It orchestrates the
interfaces built in Wave 1 — ``salience.rank_clusters`` (04-02), the additive
``InferenceClient.chat(response_format=)`` (04-03), and the ``HypothesisSet``
models + hypotheses store (04-01) — into one state machine:

    assemble (breadth-first, tracking the prompted-id universe)
      -> generate with constrained decoding
      -> validate (Pydantic) -> one repair round-trip -> degrade (never crash)
      -> citation gate (cited ⊆ prompted) -> one regeneration -> flag
      -> persist atomically (one store.transaction()).

``prompted_ids`` — the set of ``event_id``s actually printed into the prompt —
IS the citation gate's allowed set. Because those ids come from stored template
exemplars, ``cited ⊆ prompted`` transitively guarantees ``cited ⊆ store``: a
hypothesis cannot cite an event the model was never shown (T-04-02). Malformed
model output degrades and persists the raw text rather than crashing (T-04-04).
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from sift.config import McmThresholdsConfig
from sift.llm.budget import PromptBudget
from sift.models import HypothesisSet
from sift.pipeline.mcm import analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.salience import rank_clusters
from sift.render._util import sanitise
from sift.store import StoredHypothesis

if TYPE_CHECKING:
    from datetime import datetime as _dt

    from sift.llm.client import InferenceClient
    from sift.models import Hypothesis
    from sift.store import CaseStore, Cluster, TemplateGroup

_PROMPT_PACKAGE = "sift.prompts"
_PROMPT_FILE = "triage.md"

# The KB reference-material block in triage.md is delimited by these HTML-comment
# sentinels; all KB prose lives in the template (CLI-02). ``_apply_kb_block``
# either fills the slot and drops the marker lines (KB present) or removes the
# whole block start-through-end (no KB) so the no-KB prompt is byte-identical.
_KB_SLOT = "<<KB_CONTEXT>>"
_KB_BLOCK_RE = re.compile(
    r"<!-- KB_BLOCK_START.*?-->\n.*?<!-- KB_BLOCK_END.*?-->\n", re.DOTALL
)
_KB_MARKER_RE = re.compile(r"<!-- KB_BLOCK_(?:START|END).*?-->\n", re.DOTALL)


def _apply_kb_block(template: str, kb_context: list[str] | None) -> str:
    """Resolve the triage template's KB block against ``kb_context`` (D-02, D-01).

    No KB → the entire sentinel block (start marker through end marker) is
    removed, leaving the pre-change prompt bytes unchanged. KB present → the two
    marker lines are dropped and the ``<<KB_CONTEXT>>`` slot is replaced with the
    joined, control-char-``sanitise``d chunks (T-06-16: KB text is untrusted data
    inserted as reference material, never instructions). KB never becomes citable
    — that guarantee lives in ``_assemble``'s ``prompted_ids``, not here.
    """
    if not kb_context:
        return _KB_BLOCK_RE.sub("", template)
    joined = "\n\n".join(sanitise(chunk) for chunk in kb_context)
    return _KB_MARKER_RE.sub("", template).replace(_KB_SLOT, joined)


# The MCM fact block in triage.md is delimited by these HTML-comment sentinels,
# mirroring the KB block's shape exactly (same DOTALL regexes, same trailing-`\n`
# capture). ``_apply_mcm_block`` either fills the ``<<MCM_FACTS>>`` slot and drops
# the marker lines (MCM present) or removes the whole block start-through-end (no
# MCM) so the no-MCM prompt is byte-identical to its pre-phase form. Unlike KB,
# MCM facts ARE citable — that inversion lives in ``_assemble``'s ``prompted_ids``.
_MCM_SLOT = "<<MCM_FACTS>>"
_MCM_BLOCK_RE = re.compile(
    r"<!-- MCM_BLOCK_START.*?-->\n.*?<!-- MCM_BLOCK_END.*?-->\n", re.DOTALL
)
_MCM_MARKER_RE = re.compile(r"<!-- MCM_BLOCK_(?:START|END).*?-->\n", re.DOTALL)


def _apply_mcm_block(template: str, fact_block: str | None) -> str:
    """Resolve the triage template's MCM block against ``fact_block`` (MCM-06).

    No MCM data → the entire sentinel block (start marker through end marker,
    including the trailing newline) is removed, leaving the pre-phase prompt bytes
    unchanged. MCM present → the two marker lines are dropped and the
    ``<<MCM_FACTS>>`` slot is replaced with ``fact_block`` (already
    ``sanitise``d value-by-value by ``render_mcm_facts`` — this fn only splices,
    it does NOT re-sanitise). MCM facts become citable via ``_assemble``'s
    ``prompted_ids`` union, the inverse of the KB path.
    """
    if not fact_block:
        return _MCM_BLOCK_RE.sub("", template)
    return _MCM_MARKER_RE.sub("", template).replace(_MCM_SLOT, fact_block)

# Explicit severity rank, mirroring cluster._SEVERITY_RANK — never lexicographic
# ('unknown' > 'error' as a string would be wrong). Frozen by the clusters
# severity CHECK constraint, so a local copy cannot drift.
_SEVERITY_RANK = {
    "fatal": 5,
    "error": 4,
    "warn": 3,
    "info": 2,
    "debug": 1,
    "unknown": 0,
}


@dataclass(frozen=True)
class Outcome:
    """The result of one triage run (SPEC §5.5, exit-code mapping in CLI-04).

    ``failed`` (transport error / SSRF refusal) persists nothing and maps to
    exit 1. ``degraded`` (repair failed OR citations still invalid after
    regenerate) persists flagged output and maps to exit 3. Neither ``failed``
    nor ``degraded`` is the golden path (exit 0).
    """

    hypotheses: HypothesisSet | None
    raw: str | None
    degraded: bool
    failed: bool
    citations_valid: bool
    prompt_hash: str


def _load_triage_template() -> str:
    """Load the versioned triage prompt from package data (CLI-02)."""
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_PROMPT_FILE)
        .read_text(encoding="utf-8")
    )


def _schema_rf(schema: dict[str, object]) -> dict[str, object]:
    """The llama.cpp constrained-decoding shape (RAG-03, ./CLAUDE.md §5).

    ``{"type": "json_schema", "schema": <model_json_schema>}`` — the schema sits
    at ``response_format.schema`` top-level, NOT OpenAI's deeper nesting, and
    NEVER alongside a ``grammar`` field (llama.cpp treats both-at-once as a hard
    error). Pydantic validation is the backstop if a server ignores it.
    """
    return {"type": "json_schema", "schema": schema}


def _prompt_hash(text: str) -> str:
    """sha256(prompt)[:16], mirroring the event_id / template_id idiom.

    Identical inputs assemble an identical prompt and thus an identical hash —
    the determinism guarantee that makes a run reproducible.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _ctx_tokens(client: InferenceClient, fallback: int) -> int:
    """The generation context window: ``/props`` ``n_ctx`` else the fallback.

    Lemonade may lack ``/props`` (LLM-04); an absent endpoint or key degrades to
    the configured fallback rather than erroring.
    """
    n = client.props().get("n_ctx")
    return n if isinstance(n, int) and n > 0 else fallback


def _gather_exemplar_messages(
    store: CaseStore, groups: list[TemplateGroup]
) -> dict[str, str]:
    """Gather the message text for each group's first exemplar event.

    Mirrors ``cluster._exemplar_messages``: streams ``iter_event_summaries``
    once (no raw decompression) and keeps only the exemplar messages needed to
    render the prompt.
    """
    wanted = {g.exemplar_event_ids[0] for g in groups if g.exemplar_event_ids}
    if not wanted:
        return {}
    messages: dict[str, str] = {}
    for eid, _ts, _severity, message in store.iter_event_summaries():
        if eid in wanted:
            messages[eid] = message
            if len(messages) == len(wanted):
                break
    return messages


def _representative_exemplar(
    cluster: Cluster, group_index: dict[str, TemplateGroup]
) -> str | None:
    """The citable event id for a cluster: its highest-salience group's exemplar.

    Picks the member ``TemplateGroup`` with the greatest (severity, count) —
    mirroring the representative the cluster signature uses — and returns that
    group's first exemplar event id. ``None`` when no member group has an
    exemplar (a partial/tampered store).
    """
    best: tuple[tuple[int, int], str] | None = None
    for template_id in cluster.template_ids:
        group = group_index.get(template_id)
        if group is None or not group.exemplar_event_ids:
            continue
        key = (_SEVERITY_RANK.get(group.severity_max, 0), group.count)
        if best is None or key > best[0]:
            best = (key, group.exemplar_event_ids[0])
    return None if best is None else best[1]


def _assemble(
    ranked: list[tuple[Cluster, float]],
    group_index: dict[str, TemplateGroup],
    messages: dict[str, str],
    template: str,
    hint: str | None,
    budget: PromptBudget,
    *,
    kb_context: list[str] | None = None,
    mcm_block: tuple[str, set[str]] | None = None,
) -> tuple[list[dict[str, str]], set[str], str]:
    """Assemble the triage prompt breadth-first over the ranked clusters.

    Emits one ``[evt:<event_id>] <exemplar message>`` line per cluster whose
    representative exemplar message is available, in ranked order.
    ``PromptBudget.fit`` trims excerpts breadth-first (never dropping a whole
    cluster). The hint, when given, is appended verbatim — never parsed for a
    timestamp. ``kb_context`` (retrieved KB reference material) enriches the
    prompt via the template's delimited KB block but is NEVER added to
    ``prompted_ids`` — KB chunks stay structurally non-citable (D-01).
    ``mcm_block`` (``render_mcm_facts`` output — the fact text plus the exact set
    of ids it printed as ``[evt:]`` tokens) is the INVERSE: its text is spliced
    into the template's MCM block AND its printed ids are unioned into
    ``prompted_ids``, making the deterministic MCM facts citable evidence
    (MCM-06). Only the ids the renderer actually printed enter the set — never a
    row id the block did not surface. Returns the chat ``messages``, the
    ``prompted_ids`` set (the citable universe), and the exact assembled prompt
    text (for hashing).
    """
    template = _apply_kb_block(template, kb_context)
    template = _apply_mcm_block(template, mcm_block[0] if mcm_block else None)
    event_ids: list[str] = []
    excerpts: list[str] = []
    for cluster, _score in ranked:
        eid = _representative_exemplar(cluster, group_index)
        if eid is None:
            continue
        message = messages.get(eid)
        if message is None:
            continue
        event_ids.append(eid)
        excerpts.append(message)

    fitted = budget.fit(excerpts)
    lines = [
        f"[evt:{eid}] {excerpt}"
        for eid, excerpt in zip(event_ids, fitted, strict=True)
    ]
    prompt = template + "\n".join(lines) + "\n"
    if hint:
        prompt += f"\nOperator hint (context only, not evidence): {hint}\n"
    prompted_ids: set[str] = set(event_ids) | (mcm_block[1] if mcm_block else set())
    return [{"role": "user", "content": prompt}], prompted_ids, prompt


def _validate(raw: str) -> tuple[HypothesisSet | None, str]:
    """json.loads + ``HypothesisSet`` validation; ``(None, error)`` on failure.

    ``model_validate_json`` covers both a non-JSON body and a schema mismatch;
    both surface as ``ValueError`` (``pydantic.ValidationError`` is a subclass).
    The error string is carried into the repair turn so the model can correct.
    """
    try:
        return HypothesisSet.model_validate_json(raw), ""
    except ValueError as exc:
        return None, str(exc)


def _repair_turn(raw: str, error: str) -> dict[str, str]:
    """A user turn carrying the malformed output + validation error (RAG-03)."""
    return {
        "role": "user",
        "content": (
            "Your previous response was not valid and was rejected:\n"
            f"{error}\n\n"
            "Here is the response you gave:\n"
            f"{raw}\n\n"
            "Return the corrected JSON object only, matching the required "
            "schema. Do not include any other text."
        ),
    }


def _generate(
    client: InferenceClient,
    messages: list[dict[str, str]],
    rf: dict[str, object],
) -> tuple[HypothesisSet | None, str]:
    """Generate + validate with exactly one repair round-trip (RAG-03).

    Returns ``(HypothesisSet, raw)`` on success (first try or after repair), or
    ``(None, raw)`` where ``raw`` is the SECOND failed output — the caller
    degrades and persists it. Raises ``httpx.HTTPError`` on a transport failure,
    or ``ValueError`` when ``client.chat`` gets a malformed/empty 200 body
    (no/absent choices, absent content, empty/whitespace content) on any of the
    initial or repair calls — the caller maps both to a clean failed run (G1).
    """
    raw = client.chat(messages, response_format=rf)
    hset, error = _validate(raw)
    if hset is not None:
        return hset, raw
    raw = client.chat([*messages, _repair_turn(raw, error)], response_format=rf)
    hset, _error = _validate(raw)
    return hset, raw


def hypothesise(
    store: CaseStore,
    client: InferenceClient,
    *,
    top_clusters: int,
    incident_time: _dt | None,
    since: _dt | None = None,
    until: _dt | None = None,
    hint: str | None = None,
    kb_context: list[str] | None = None,
    mcm_thresholds: McmThresholdsConfig | None = None,
    ctx_fallback: int = 8192,
    reserve_out: int = 1024,
) -> Outcome:
    """Produce citation-gated triage hypotheses for the case (SPEC §5.5).

    Ranks the case's clusters by salience, assembles a budgeted triage prompt
    over the top ``top_clusters`` (tracking the prompted-id universe), runs the
    constrained-decode -> validate -> repair -> degrade state machine, then the
    citation gate (cited ⊆ prompted, regenerate once, flag), and persists the
    result atomically. ``kb_context`` (retrieved KB reference material, RAG-07)
    enriches the prompt via the template's delimited KB block but never enters
    ``prompted_ids`` — KB chunks stay structurally non-citable (D-01). Never
    raises on malformed model output: a schema-invalid
    body degrades (persists the raw text), while a malformed/empty 200 body — a
    ``ValueError`` from ``client.chat`` (no/absent choices, absent content,
    empty/whitespace content) — or a transport failure maps to a clean failed
    run (nothing persisted, exit 1), never a raw traceback (RAG-03; gap G1).
    """
    clusters = store.query_clusters()
    groups = store.query_template_groups()
    ranked = rank_clusters(
        clusters, groups, incident_time=incident_time, since=since, until=until
    )[:top_clusters]
    group_index = {g.template_id: g for g in groups}
    messages_map = _gather_exemplar_messages(store, groups)
    template = _load_triage_template()

    # Deterministic MCM facts, built BEFORE generation from the analyser's model
    # tree — figures are a pure function of the store, never authored by the LLM
    # (T-11-02). ``render_mcm_facts`` returns ("", set()) for a non-dsserrors case,
    # which ``_assemble`` strips residue-free. Built at this chokepoint so the eval
    # harness (which calls hypothesise directly) exercises injection too (MCM-06).
    mcm_block = render_mcm_facts(
        analyse_mcm(store.query_events(), mcm_thresholds or McmThresholdsConfig())
    )

    ctx = _ctx_tokens(client, ctx_fallback)
    # InferenceClient satisfies PromptBudget's tokenizer seam at runtime; its
    # has_tokenize is a read-only property vs the protocol's plain attribute,
    # which pyright flags as a false mismatch (same as cluster.py).
    budget = PromptBudget(client, ctx, reserve_out)  # pyright: ignore[reportArgumentType]
    chat_messages, prompted_ids, prompt_text = _assemble(
        ranked, group_index, messages_map, template, hint, budget,
        kb_context=kb_context, mcm_block=mcm_block,
    )
    prompt_hash = _prompt_hash(prompt_text)
    rf = _schema_rf(HypothesisSet.model_json_schema())

    try:
        hset, raw = _generate(client, chat_messages, rf)
        if hset is None:
            outcome = Outcome(
                hypotheses=None,
                raw=raw,
                degraded=True,
                failed=False,
                citations_valid=False,
                prompt_hash=prompt_hash,
            )
        else:
            outcome = _citation_gate(
                client, hset, chat_messages, rf, prompted_ids, prompt_hash
            )
    except (httpx.HTTPError, ValueError):
        # A transport failure OR a malformed/empty 200 body (no/absent choices,
        # absent content, empty/whitespace content — a ValueError from
        # client.chat) produced no inspectable output: nothing is persisted
        # (CLI-04 exit 1), distinct from a degraded-but-produced run (exit 3).
        # Never a raw traceback (RAG-03 never-crash invariant; gap G1).
        # The only ValueError source inside this try is client.chat on a
        # malformed response: _validate swallows its own ValueError and
        # _assemble's zip(strict=True) runs before the try, so nothing legitimate
        # is masked.
        return Outcome(
            hypotheses=None,
            raw=None,
            degraded=False,
            failed=True,
            citations_valid=False,
            prompt_hash=prompt_hash,
        )

    _persist(store, outcome, prompted_ids, prompt_hash, client.embedding_model)
    return outcome


def _row_citations_valid(hyp: Hypothesis, prompted_ids: set[str]) -> bool:
    """Whether every id this hypothesis cites was actually shown to the model."""
    return all(eid in prompted_ids for eid in hyp.supporting_event_ids)


def _all_cited_within(hset: HypothesisSet, prompted_ids: set[str]) -> bool:
    """cited ⊆ prompted for the whole set (T-04-02, the anti-hallucination gate).

    Because ``prompted_ids`` are stored exemplar ids, this transitively enforces
    cited ⊆ prompted ⊆ store: a hypothesis cannot cite an unseen or fabricated
    event.
    """
    return all(_row_citations_valid(h, prompted_ids) for h in hset.hypotheses)


def _citation_gate(
    client: InferenceClient,
    hset: HypothesisSet,
    messages: list[dict[str, str]],
    rf: dict[str, object],
    prompted_ids: set[str],
    prompt_hash: str,
) -> Outcome:
    """Enforce cited ⊆ prompted with exactly one regeneration, then flag (RAG-04).

    All cited within prompted -> success. Otherwise regenerate once (the fresh
    output must itself pass schema validation); if it now cites within prompted,
    success. Still invalid -> the offending hypotheses are FLAGGED
    (``citations_valid=False`` per row at persist, offending ids kept visible)
    and the run degrades — never silently accepted, never dropped.
    """
    if _all_cited_within(hset, prompted_ids):
        return Outcome(
            hypotheses=hset,
            raw=None,
            degraded=False,
            failed=False,
            citations_valid=True,
            prompt_hash=prompt_hash,
        )
    regen, _error = _validate(client.chat(messages, response_format=rf))
    if regen is not None and _all_cited_within(regen, prompted_ids):
        return Outcome(
            hypotheses=regen,
            raw=None,
            degraded=False,
            failed=False,
            citations_valid=True,
            prompt_hash=prompt_hash,
        )
    # A failed re-validate keeps the original set so the flagged output is still
    # the schema-valid one the operator can inspect.
    winner = regen if regen is not None else hset
    return Outcome(
        hypotheses=winner,
        raw=None,
        degraded=True,
        failed=False,
        citations_valid=False,
        prompt_hash=prompt_hash,
    )


def _persist(
    store: CaseStore,
    outcome: Outcome,
    prompted_ids: set[str],
    prompt_hash: str,
    model: str | None,
) -> None:
    """Persist hypotheses + triage run-meta inside ONE transaction (T-04-11).

    Rows are built first (pure), then written; a mid-persist failure rolls back
    to zero hypotheses — never partial state. Each row carries its own
    ``citations_valid`` verdict so the report can flag the offending ones. The
    raw output is stored only when nothing schema-valid was produced (a hard
    degrade), so an operator can still see what the model returned.
    """
    hset = outcome.hypotheses
    rows: list[StoredHypothesis] = []
    if hset is not None:
        for index, hyp in enumerate(hset.hypotheses):
            rows.append(
                StoredHypothesis(
                    hyp_index=index,
                    title=hyp.title,
                    narrative=hyp.narrative,
                    confidence=hyp.confidence,
                    confidence_reasoning=hyp.confidence_reasoning,
                    supporting_event_ids=list(hyp.supporting_event_ids),
                    contradicting_evidence=hyp.contradicting_evidence,
                    suggested_next_steps=list(hyp.suggested_next_steps),
                    citations_valid=_row_citations_valid(hyp, prompted_ids),
                )
            )

    with store.transaction():
        store.replace_hypotheses(rows)
        store.set_meta("triage_degraded", "1" if outcome.degraded else "0")
        store.set_meta("triage_prompt_hash", prompt_hash)
        store.set_meta("triage_created_at", datetime.now(UTC).isoformat())
        if model is not None:
            store.set_meta("triage_model", model)
        if hset is not None:
            store.set_meta("triage_timeline_summary", hset.timeline_summary)
            store.set_meta(
                "triage_unexplained_signals",
                json.dumps(list(hset.unexplained_signals)),
            )
            # Clear any raw output left by a PRIOR degraded run — otherwise the
            # report shows a stale "Raw model output" block under the new valid
            # hypotheses. ``if raw:`` in the renderer treats "" as absent.
            store.set_meta("triage_raw", "")
        elif outcome.raw is not None:
            store.set_meta("triage_raw", outcome.raw)


__all__ = ["Outcome", "hypothesise"]
