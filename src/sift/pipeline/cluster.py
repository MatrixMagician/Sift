"""Semantic clustering of template groups (CLUS-02, D-04).

This module mirrors ``dedup.py``'s contract: it is typer-free, print-free and
SQL-free — persistence goes exclusively through ``CaseStore`` methods, and all
vector bytes stay confined to ``store.py``. It reads the existing template
groups, embeds one representative exemplar *message* per group (Open Question 1
/ A3 — the message, not the masked template), clusters the L2-normalised
vectors with ``sklearn.cluster.HDBSCAN`` (euclidean == cosine on normalised
input) or the config-selected agglomerative fallback, turns HDBSCAN noise
(label ``-1``) into its own singleton cluster so nothing is dropped, and
persists vectors + chunks + clusters inside a single ``store.transaction()``.

Clustering parameters come from ``ClusteringConfig`` (D-04), never hard-coded.
The A2 linkage constraint is honoured: cosine distance requires
``linkage="average"`` — ``ward`` demands euclidean and would raise at fit.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

import numpy as np
from sklearn.cluster import (  # pyright: ignore[reportMissingTypeStubs] — sklearn ships no stubs
    HDBSCAN,
    AgglomerativeClustering,
)
from sklearn.preprocessing import (  # pyright: ignore[reportMissingTypeStubs]
    normalize,  # pyright: ignore[reportUnknownVariableType]
)

from sift.llm.budget import PromptBudget
from sift.store import CaseStore, Cluster, TemplateGroup

if TYPE_CHECKING:
    from sift.config import ClusteringConfig
    from sift.llm.client import InferenceClient

# The versioned label prompt (CLI-02): editing the .md changes label output with
# no Python change. Loaded via importlib.resources so it ships as package data.
_PROMPT_PACKAGE = "sift.prompts"
_PROMPT_FILE = "cluster_label.md"

# Label-slice budget (RAG-05). Constants, not config: labels are short and the
# full triage budget is Phase 4. PromptBudget truncates exemplars breadth-first.
_LABEL_CTX_TOKENS = 4096
_LABEL_RESERVE_OUT = 512

# CLUS-03 / Pitfall 4: cap each label by Unicode code points (str slicing is
# code-point based), never bytes — British/non-ASCII spelling survives intact.
_MAX_LABEL_CHARS = 80

# Explicit severity rank, mirroring dedup._SEVERITY_RANK — never lexicographic
# ('unknown' > 'error' as a string would be wrong). The vocabulary is frozen by
# the clusters/severity CHECK constraint, so a local copy cannot drift.
_SEVERITY_RANK = {
    "fatal": 5,
    "error": 4,
    "warn": 3,
    "info": 2,
    "debug": 1,
    "unknown": 0,
}


def exemplar_text(group: TemplateGroup, messages: dict[str, str]) -> str:
    """Return the text embedded for ``group`` — its first exemplar message.

    Open Question 1 / A3: embed the exemplar event *message* (richer semantics)
    rather than the masked template. ``messages`` maps event id → message for
    the exemplar ids gathered from the store. Degrades to the masked template
    when a group has no exemplars or the message is missing (a tampered or
    partial store), so clustering never crashes on incomplete data.
    """
    for event_id in group.exemplar_event_ids:
        message = messages.get(event_id)
        if message is not None:
            return message
    return group.template


def _exemplar_messages(
    store: CaseStore, groups: list[TemplateGroup]
) -> dict[str, str]:
    """Gather the message text for each group's first exemplar event.

    Streams ``iter_event_summaries`` once (no raw decompression) and keeps only
    the messages actually needed for embedding.
    """
    wanted = {g.exemplar_event_ids[0] for g in groups if g.exemplar_event_ids}
    if not wanted:
        return {}
    messages: dict[str, str] = {}
    for event_id, _ts, _severity, message in store.iter_event_summaries():
        if event_id in wanted:
            messages[event_id] = message
            if len(messages) == len(wanted):
                break
    return messages


def _cluster_labels(x: np.ndarray, cfg: ClusteringConfig) -> list[int]:
    """Assign each group a raw cluster label (HDBSCAN ``-1`` == noise).

    Fewer points than ``min_cluster_size`` cannot form a density cluster, so
    each group becomes its own singleton (Open Question 2 auto-singleton path).
    ``cfg.algorithm == "agglomerative"`` routes through the cosine-average
    fallback; otherwise HDBSCAN runs on the normalised vectors.
    """
    n = int(x.shape[0])
    if n < cfg.min_cluster_size:
        return list(range(n))  # auto-singleton: too few points to cluster
    if cfg.algorithm == "agglomerative":
        model = AgglomerativeClustering(
            n_clusters=None,  # pyright: ignore[reportArgumentType] — sklearn stub types this int
            metric="cosine",
            linkage="average",  # A2: cosine forbids ward — average is required
            distance_threshold=cfg.distance_threshold,
        )
    else:
        model = HDBSCAN(
            min_cluster_size=cfg.min_cluster_size,
            min_samples=cfg.min_samples,  # sklearn counts self: +1 vs standalone
            cluster_selection_epsilon=cfg.epsilon,
            metric="euclidean",  # == cosine on L2-normalised vectors
            copy=True,  # pyright: ignore[reportArgumentType] — sklearn stub types this str
        )
    raw = model.fit_predict(x)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return [int(label) for label in raw]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def _assign_cluster_ids(raw_labels: list[int]) -> list[int]:
    """Map raw cluster labels to stable ids in canonical group order.

    Groups arrive in ``query_template_groups`` canonical order (count DESC,
    template ASC), so first-appearance assignment is deterministic across runs.
    HDBSCAN noise (``-1``) never merges: each noise point gets a fresh id.
    """
    next_id = 0
    label_to_id: dict[int, int] = {}
    assignment: list[int] = []
    for label in raw_labels:
        if label == -1:
            assignment.append(next_id)
            next_id += 1
        else:
            if label not in label_to_id:
                label_to_id[label] = next_id
                next_id += 1
            assignment.append(label_to_id[label])
    return assignment


def _build_clusters(
    groups: list[TemplateGroup], assignment: list[int]
) -> list[Cluster]:
    """Aggregate member template groups into Cluster rows (label NULL for now).

    The representative group (highest severity, then count, first in canonical
    order) supplies the signature shown until an LLM label exists.
    """
    members: dict[int, list[TemplateGroup]] = {}
    for group, cluster_id in zip(groups, assignment, strict=True):
        members.setdefault(cluster_id, []).append(group)
    clusters: list[Cluster] = []
    for cluster_id, group_members in members.items():
        representative = max(
            group_members,
            key=lambda g: (_SEVERITY_RANK.get(g.severity_max, 0), g.count),
        )
        severity_max = max(
            group_members,
            key=lambda g: _SEVERITY_RANK.get(g.severity_max, 0),
        ).severity_max
        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                label=None,  # D-01: filled by the label call (Task 2)
                signature=representative.template,
                severity_max=severity_max,
                count=sum(g.count for g in group_members),
                template_ids=[g.template_id for g in group_members],
            )
        )
    return clusters


def _load_template() -> str:
    """Load the versioned label prompt from package data (CLI-02)."""
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_PROMPT_FILE)
        .read_text(encoding="utf-8")
    )


def _template_hash(template: str) -> str:
    """sha256(template)[:16], mirroring the event_id / template_id idiom."""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]


def build_label_prompt(excerpts: Sequence[str], template: str) -> str:
    """Assemble ONE label prompt: the template plus numbered exemplar excerpts.

    The template text is included verbatim, so editing ``cluster_label.md``
    changes the prompt the client receives with no Python change (CLI-02). Each
    excerpt is untrusted log data; the template instructs the model to treat it
    as data, never as instructions (T-03-16).
    """
    lines = [f"{index}. {excerpt}" for index, excerpt in enumerate(excerpts)]
    return template + "\n".join(lines) + "\n"


def _parse_labels(content: str) -> dict[int, str]:
    """Leniently parse a ``{index: label}`` JSON object (Open Question 3).

    Defensive by contract: any parse failure (not JSON, not an object, odd
    types) returns an empty mapping so clusters degrade to their signature — a
    label response never crashes the run (T-03-19). Only string values keyed by
    an integer-parseable key survive.
    """
    try:
        data: object = json.loads(content)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    labels: dict[int, str] = {}
    for key, value in cast("dict[object, object]", data).items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        try:
            index = int(key)
        except ValueError:
            continue
        labels[index] = value
    return labels


def _label_clusters(
    client: InferenceClient | None,
    cluster_ids: list[int],
    excerpts: Sequence[str],
    template: str,
) -> dict[int, str]:
    """Return one budget-bounded label per cluster from ONE batched chat call.

    Skips labelling (returns ``{}``) when there is no client (``--no-label`` /
    no endpoint, D-01) or the budget admits no exemplar (RAG-05 empty). Any chat
    or parse failure degrades to ``{}`` — labels stay NULL and the signature is
    shown (T-03-19). Each label is capped by Unicode code points (CLUS-03).
    """
    if client is None:
        return {}
    # InferenceClient satisfies PromptBudget's tokenizer seam at runtime; its
    # has_tokenize is a read-only property vs the protocol's plain (invariant)
    # attribute, which pyright flags as a false mismatch.
    budget = PromptBudget(client, _LABEL_CTX_TOKENS, _LABEL_RESERVE_OUT)  # pyright: ignore[reportArgumentType]
    fitted = budget.fit(excerpts)
    if not fitted:
        return {}
    prompt = build_label_prompt(fitted, template)
    try:
        content = client.chat([{"role": "user", "content": prompt}])
    except Exception:  # noqa: BLE001 — degrade to signature, never crash (T-03-19)
        return {}
    labels: dict[int, str] = {}
    for index, text in _parse_labels(content).items():
        if 0 <= index < len(cluster_ids):
            labels[cluster_ids[index]] = text[:_MAX_LABEL_CHARS]
    return labels


def cluster_and_label(
    store: CaseStore,
    client: InferenceClient,
    cfg: ClusteringConfig,
    *,
    label: bool = True,
) -> int:
    """Embed exemplars, cluster template groups, label them, and persist.

    Returns the number of clusters written. Zero template groups short-circuit
    to 0 with no embedding call and no writes. When ``label`` is ``True`` a
    single batched chat call labels every cluster eagerly (D-01); ``label=False``
    is the ``--no-label`` / no-endpoint path (clusters keep their signature).
    Persistence (vectors, chunks, clusters, labels, prompt hash) happens inside
    one ``store.transaction()`` — the caller-owns-transaction idiom mirrored
    from ``rebuild_template_groups``.
    """
    groups = store.query_template_groups()
    if not groups:
        return 0

    messages = _exemplar_messages(store, groups)
    texts = [exemplar_text(group, messages) for group in groups]
    vectors = client.embed(texts)
    dim = len(vectors[0])
    store.ensure_vectors_table(dim)

    # np.asarray re-types normalize's partially-typed sklearn output as a
    # concrete float64 ndarray so the clustering boundary stays type-checked.
    normalized = normalize(np.asarray(vectors, dtype=np.float64), norm="l2")  # pyright: ignore[reportUnknownVariableType]
    x: np.ndarray = np.asarray(normalized, dtype=np.float64)  # pyright: ignore[reportUnknownArgumentType]
    assignment = _assign_cluster_ids(_cluster_labels(x, cfg))
    clusters = _build_clusters(groups, assignment)

    # One representative exemplar excerpt per cluster (same representative the
    # signature uses: highest severity then count, first in canonical order).
    rep_excerpt: dict[int, tuple[tuple[int, int], str]] = {}
    for index, (group, cluster_id) in enumerate(
        zip(groups, assignment, strict=True)
    ):
        key = (_SEVERITY_RANK.get(group.severity_max, 0), group.count)
        if cluster_id not in rep_excerpt or key > rep_excerpt[cluster_id][0]:
            rep_excerpt[cluster_id] = (key, texts[index])

    cluster_ids = [c.cluster_id for c in clusters]
    excerpts = [rep_excerpt[cluster_id][1] for cluster_id in cluster_ids]
    template = _load_template()
    label_map = _label_clusters(
        client if label else None, cluster_ids, excerpts, template
    )

    chunks = [
        (index, group.template_id, texts[index], group.exemplar_event_ids)
        for index, group in enumerate(groups)
    ]
    vector_rows = list(enumerate(vectors))

    with store.transaction():
        store.upsert_vectors(vector_rows)
        store.replace_chunks(chunks)
        store.replace_clusters(clusters)
        if label_map:
            store.set_cluster_labels(label_map)
        if label:
            store.set_meta("cluster_label_prompt_hash", _template_hash(template))
    return len(clusters)
