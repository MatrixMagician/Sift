"""Shared verdict service: the single verdict-recording code path (D003/D004).

Both ``sift validate`` (headless CLI, T03) and the S03 TUI land here; neither
builds target snapshots or provenance itself. The service parses a target
spec, resolves it against the case, snapshots the judged target's context
(hypothesis text + masked evidence templates + sources, or the cluster or
template shape) and provenance (run marker, model, prompt hash), then appends
one row via :meth:`CaseStore.record_verdict` — the store's only write path.

The snapshot field vocabulary lives HERE, not in store.py: the store persists
``context``/``provenance`` opaquely and M002 harvests these JSON columns
cross-case (D005), so field names in the ``_snapshot_*`` builders are part of
the M002 learning contract — extend them, never rename them.

Error classes map one-to-one onto the CLI exit-code convention (ADR 0005/0007)
so T03 can branch on class alone: :class:`TargetSpecError` is a usage error
(exit 2), :class:`UnknownTargetError` a semantic failure (exit 1). Storage
failures (``sqlite3.Error`` — a busy lock, a corrupt page, a rejected
constraint, an already-closed store) bubble unswallowed for each caller to map:
``run_validate`` returns exit 1, the TUI modal shows an inline message. The
service swallows none of them, so neither mapping can be bypassed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sift.pipeline.dedup import mask
from sift.store import VERDICT_STATES, VERDICT_TARGET_TYPES, CaseStore


class VerdictError(Exception):
    """Base class for verdict-service failures."""


class TargetSpecError(VerdictError):
    """Malformed target spec — a usage error (CLI exit 2)."""


class UnknownTargetError(VerdictError):
    """Well-formed target absent from this case — semantic failure (exit 1)."""


@dataclass(frozen=True)
class TargetSpec:
    """A parsed ``<type>:<id>`` verdict target."""

    target_type: str  # 'hypothesis' | 'cluster' | 'template'
    target_id: str  # canonical decimal for hypothesis/cluster, hex for template


@dataclass(frozen=True)
class RecordedVerdict:
    """What the caller shows after a verdict lands (verdict_id + target)."""

    verdict_id: str
    target_type: str
    target_id: str
    verdict: str
    created_at: str  # ISO 8601, UTC — equals the row stamp


_SPEC_HINT = "expected <type>:<id> with type one of " + ", ".join(
    sorted(VERDICT_TARGET_TYPES)
)


def parse_target(spec: str) -> TargetSpec:
    """Parse ``hypothesis:0`` / ``cluster:3`` / ``template:<hex>`` specs.

    The type prefix is REQUIRED: hypothesis indexes and cluster ids are both
    small integers, so inferring the type from a bare id would be permanently
    ambiguous, not an edge case. Numeric ids normalise to their canonical
    decimal spelling (``007`` → ``7``) so stored ``target_id`` values always
    filter and compare cleanly. Raises :class:`TargetSpecError` on any
    malformed spec — existence in the case is checked at record time, not here.
    """
    text = spec.strip()
    target_type, sep, target_id = text.partition(":")
    if not sep or not target_type:
        raise TargetSpecError(f"malformed target {spec!r}; {_SPEC_HINT}")
    if target_type not in VERDICT_TARGET_TYPES:
        raise TargetSpecError(
            f"unknown target type {target_type!r}; {_SPEC_HINT}"
        )
    if not target_id:
        raise TargetSpecError(f"target {spec!r} is missing an id; {_SPEC_HINT}")
    if target_type in ("hypothesis", "cluster"):
        if not target_id.isdecimal():
            raise TargetSpecError(
                f"{target_type} id must be a non-negative integer, "
                f"got {target_id!r}"
            )
        target_id = str(int(target_id))
    return TargetSpec(target_type=target_type, target_id=target_id)


def _snapshot_hypothesis(store: CaseStore, target_id: str) -> dict[str, object]:
    """Hypothesis text plus masked evidence templates and sources (D003).

    Evidence templates come from masking each cited event's message with the
    same :func:`sift.pipeline.dedup.mask` that built the template groups, so
    the snapshot is volatile-token-free and directly comparable cross-case.
    A cited id absent from the events table (an invalid citation flagged
    upstream by the citation gate) is skipped for templates/sources but stays
    listed in ``supporting_event_ids`` — the gap remains auditable.
    """
    idx = int(target_id)
    hyp = next((h for h in store.query_hypotheses() if h.hyp_index == idx), None)
    if hyp is None:
        raise UnknownTargetError(f"no hypothesis {target_id} in this case")
    events = store.get_events_by_ids(hyp.supporting_event_ids)
    templates: list[str] = []
    sources: set[str] = set()
    for eid in hyp.supporting_event_ids:
        event = events.get(eid)
        if event is None:
            continue
        template = mask(event.message)
        if template not in templates:
            templates.append(template)
        sources.add(event.source_file)
    return {
        "hyp_index": hyp.hyp_index,
        "title": hyp.title,
        "narrative": hyp.narrative,
        "confidence": hyp.confidence,
        "citations_valid": hyp.citations_valid,
        "supporting_event_ids": hyp.supporting_event_ids,
        "evidence_templates": templates,
        "sources": sorted(sources),
    }


def _snapshot_cluster(store: CaseStore, target_id: str) -> dict[str, object]:
    """Cluster shape: label/signature plus the member templates' masked text."""
    cid = int(target_id)
    cluster = next(
        (c for c in store.query_clusters() if c.cluster_id == cid), None
    )
    if cluster is None:
        raise UnknownTargetError(f"no cluster {target_id} in this case")
    text_by_id = {g.template_id: g.template for g in store.query_template_groups()}
    return {
        "cluster_id": cluster.cluster_id,
        "label": cluster.label,
        "signature": cluster.signature,
        "severity_max": cluster.severity_max,
        "count": cluster.count,
        "template_ids": cluster.template_ids,
        "templates": [
            text_by_id[tid] for tid in cluster.template_ids if tid in text_by_id
        ],
    }


def _snapshot_template(store: CaseStore, target_id: str) -> dict[str, object]:
    """Template shape: the masked message itself plus its group statistics."""
    group = next(
        (
            g
            for g in store.query_template_groups()
            if g.template_id == target_id
        ),
        None,
    )
    if group is None:
        raise UnknownTargetError(f"no template {target_id} in this case")
    return {
        "template_id": group.template_id,
        "template": group.template,
        "count": group.count,
        "severity_max": group.severity_max,
        "first_ts": group.first_ts,
        "last_ts": group.last_ts,
        "exemplar_event_ids": group.exemplar_event_ids,
    }


_SNAPSHOT_BUILDERS: dict[str, Callable[[CaseStore, str], dict[str, object]]] = {
    "hypothesis": _snapshot_hypothesis,
    "cluster": _snapshot_cluster,
    "template": _snapshot_template,
}


def _provenance(store: CaseStore, recorded_at: str) -> dict[str, object]:
    """Run marker, model, prompt hash and mask version from case meta (D003).

    A key whose meta value is absent (e.g. a template verdict recorded before
    any analyze run) is kept with a null value rather than dropped — M002 sees
    an explicit gap, never a missing field.
    """
    return {
        "recorded_at": recorded_at,
        "triage_created_at": store.get_meta("triage_created_at"),
        "model": store.get_meta("triage_model"),
        "prompt_hash": store.get_meta("triage_prompt_hash"),
        "mask_version": store.get_meta("mask_version"),
    }


def record_validation(
    store: CaseStore,
    target: TargetSpec | str,
    verdict: str,
    *,
    note: str = "",
) -> RecordedVerdict:
    """Resolve a target, snapshot it, and append ONE verdict row (D004).

    Accepts either a raw ``<type>:<id>`` spec (the CLI passes user input
    straight through) or an already-built :class:`TargetSpec` (the TUI knows
    which row it is on). Vocabulary and spec problems raise before any DB
    read; a single INSERT lands via :meth:`CaseStore.record_verdict`, joining
    a caller-owned transaction when one is open (TUI batching). The returned
    :class:`RecordedVerdict` carries the verdict_id and target for display.
    """
    spec = parse_target(target) if isinstance(target, str) else target
    if spec.target_type not in _SNAPSHOT_BUILDERS:
        raise TargetSpecError(
            f"unknown target type {spec.target_type!r}; {_SPEC_HINT}"
        )
    if verdict not in VERDICT_STATES:
        valid = ", ".join(sorted(VERDICT_STATES))
        raise ValueError(f"unknown verdict state {verdict!r}; valid: {valid}")
    context = _SNAPSHOT_BUILDERS[spec.target_type](store, spec.target_id)
    stamp = datetime.now(UTC).isoformat()
    verdict_id = store.record_verdict(
        target_type=spec.target_type,
        target_id=spec.target_id,
        verdict=verdict,
        context=context,
        provenance=_provenance(store, stamp),
        note=note,
        created_at=stamp,
    )
    return RecordedVerdict(
        verdict_id=verdict_id,
        target_type=spec.target_type,
        target_id=spec.target_id,
        verdict=verdict,
        created_at=stamp,
    )
