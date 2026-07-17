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
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from sift.llm.budget import PromptBudget
from sift.models import HypothesisSet
from sift.pipeline.salience import rank_clusters

if TYPE_CHECKING:
    from datetime import datetime as _dt

    from sift.llm.client import InferenceClient
    from sift.store import CaseStore, Cluster, TemplateGroup

_PROMPT_PACKAGE = "sift.prompts"
_PROMPT_FILE = "triage.md"

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
) -> tuple[list[dict[str, str]], set[str], str]:
    """Assemble the triage prompt breadth-first over the ranked clusters.

    Emits one ``[evt:<event_id>] <exemplar message>`` line per cluster whose
    representative exemplar message is available, in ranked order.
    ``PromptBudget.fit`` trims excerpts breadth-first (never dropping a whole
    cluster). The hint, when given, is appended verbatim — never parsed for a
    timestamp. Returns the chat ``messages``, the ``prompted_ids`` set (the
    citable universe), and the exact assembled prompt text (for hashing).
    """
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
    return [{"role": "user", "content": prompt}], set(event_ids), prompt


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
    degrades and persists it. Raises ``httpx.HTTPError`` on a transport failure
    (the caller maps that to a failed run).
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
    ctx_fallback: int = 8192,
    reserve_out: int = 1024,
) -> Outcome:
    """Produce citation-gated triage hypotheses for the case (SPEC §5.5).

    Ranks the case's clusters by salience, assembles a budgeted triage prompt
    over the top ``top_clusters`` (tracking the prompted-id universe), runs the
    constrained-decode -> validate -> repair -> degrade state machine, then the
    citation gate (cited ⊆ prompted, regenerate once, flag), and persists the
    result atomically. Never raises on malformed model output — it degrades.
    """
    clusters = store.query_clusters()
    groups = store.query_template_groups()
    ranked = rank_clusters(
        clusters, groups, incident_time=incident_time, since=since, until=until
    )[:top_clusters]
    group_index = {g.template_id: g for g in groups}
    messages_map = _gather_exemplar_messages(store, groups)
    template = _load_triage_template()

    ctx = _ctx_tokens(client, ctx_fallback)
    # InferenceClient satisfies PromptBudget's tokenizer seam at runtime; its
    # has_tokenize is a read-only property vs the protocol's plain attribute,
    # which pyright flags as a false mismatch (same as cluster.py).
    budget = PromptBudget(client, ctx, reserve_out)  # pyright: ignore[reportArgumentType]
    # prompted_ids (the citable universe) is consumed by the Task-3 gate.
    chat_messages, _prompted_ids, prompt_text = _assemble(
        ranked, group_index, messages_map, template, hint, budget
    )
    prompt_hash = _prompt_hash(prompt_text)
    rf = _schema_rf(HypothesisSet.model_json_schema())

    try:
        hset, raw = _generate(client, chat_messages, rf)
    except httpx.HTTPError:
        return Outcome(
            hypotheses=None,
            raw=None,
            degraded=False,
            failed=True,
            citations_valid=False,
            prompt_hash=prompt_hash,
        )

    if hset is None:
        return Outcome(
            hypotheses=None,
            raw=raw,
            degraded=True,
            failed=False,
            citations_valid=False,
            prompt_hash=prompt_hash,
        )

    # Citation gate + atomic persistence land in Task 3; a schema-valid set is
    # returned here so the gate can enforce cited ⊆ prompted over prompted_ids.
    return Outcome(
        hypotheses=hset,
        raw=None,
        degraded=False,
        failed=False,
        citations_valid=True,
        prompt_hash=prompt_hash,
    )


__all__ = ["Outcome", "hypothesise"]
