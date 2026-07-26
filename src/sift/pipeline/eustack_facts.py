"""Deterministic eu-stack fact renderer (EUS-10, Plan 18-01).

``render_eustack_facts(bundle, events) -> (block_text, citable_ids)`` is the
model-free, byte-identical-on-re-run source of truth for every eu-stack figure
surfaced to the triage prompt. It fills the versioned
``prompts/eustack_facts.md`` fragment (labels and prose only — D-16) with
figures read from ``EustackBundle`` (Phases 15-17's frozen analysis of the LAST
dump, D-11) — this plan renders only the role-composition grouping; the other
three Phase-16 groupings and the per-signature listing land in Plan 18-02.
Numbers originate in Python; wording lives in the template.

Aggregate -> citable ``event_id`` set (the ROADMAP's flagged design question,
resolved in ``CONTEXT.md``): none of ``EustackAnalysis``/``SaturationAnalysis``/
``ProgressionAnalysis`` carries an ``event_id`` (an aggregate is one-to-many,
unlike an MCM episode or a perfmon sample), so this module independently
re-derives a ``signature -> event_id`` map from ``events`` via
``sift.pipeline.eustack.signature_of`` (D-15 leaf-module boundary: it does the
re-grouping, never widens the frozen analysis models). A population figure
cites a **bounded exemplar sample**, not the full population (D-01): the lowest
``_EXEMPLAR_K`` event_ids in sort order (D-02), reusing the existing
``[evt:<id>]`` citation token unchanged. The block states in words that it is
sampling — both the exemplar count and the true population size (D-03) — so an
aggregate figure is never presented as if the population had been enumerated.
For a multi-signature aggregate the contributing signatures' event pools are
unioned FIRST, then the lowest ``_EXEMPLAR_K`` are taken (D-17), keeping the
"N of M cited as exemplars" sentence honest for the aggregate's own M.

Every emitted line begins with an ``[evt:<id>]`` citation token, and the
returned id set is **exactly** those printed ids (the D-05 exemplar contract —
never expose an id the model was not shown). Emptiness gate:
``bundle.analysis.total_threads == 0`` — the true absence of ingested eu-stack
data — never ``bundle.saturation.flags`` being empty, since a healthy,
zero-flag capture is the common case and must still render a useful block
("nothing is flagged" is itself a finding, CONTEXT.md ``<specifics>``). Every
role string is routed through ``render._util.sanitise`` before interpolation
(V5 prompt-injection defence), mirroring ``mcm_facts``/``perfmon_facts``.

This is a leaf module: it reads the analyser's model tree and the prompt
fragment only. It must NOT import from ``sift.pipeline.hypothesise`` or
``sift.cli`` (hypothesise imports this, not the reverse).
"""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING

from sift.pipeline.eustack import signature_of
from sift.pipeline.eustack_progression import group_dumps
from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.models import Event
    from sift.pipeline.eustack_progression import DumpSlice, EustackBundle

_PROMPT_PACKAGE = "sift.prompts"
_EUSTACK_FILE = "eustack_facts.md"
_EUSTACK_LINES_SLOT = "<<EUSTACK_LINES>>"

# D-02: the lowest K event_ids (sort order) cited per aggregate. event_id is
# sha256(source_file, byte_offset)[:16], so this selection is stable by
# construction and needs no tie-break rule.
_EXEMPLAR_K = 3


def _load_eustack_fragment() -> str:
    """Load the versioned eu-stack fragment from package data (CLI-02).

    Mirrors ``perfmon_facts._load_perfmon_fragment`` — the same
    ``importlib.resources`` idiom, so wording changes touch no path maths.
    """
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_EUSTACK_FILE)
        .read_text(encoding="utf-8")
    )


def _cite_prefix(event_ids: tuple[str, ...], ids: set[str]) -> str:
    """Join ``[evt:<id>]`` tokens for ``event_ids`` and record them as citable.

    Only ids that become a printed token enter ``ids`` — the exact D-05
    contract. Copied verbatim from ``perfmon_facts._cite_prefix``.
    """
    ids.update(event_ids)
    return "".join(f"[evt:{eid}]" for eid in event_ids)


def _signature_event_ids(dump_events: list[Event]) -> dict[tuple[str, ...], list[str]]:
    """One dump's signature -> ALL its event_ids, sorted ascending (D-02).

    Feeds ``signature_of`` the event's ``raw`` field, never ``message`` — the
    adapter caps ``message`` at ``CONDENSED_FRAMES = 5``, so a message-derived
    signature would not match the analyser's. Events with ``thread is None``
    (preamble/fallback records) are skipped, mirroring ``analyse_eustack``'s
    own thread-event selection.
    """
    acc: dict[tuple[str, ...], list[str]] = {}
    for event in dump_events:
        if event.thread is None:
            continue
        acc.setdefault(signature_of(event.raw), []).append(event.event_id)
    for event_ids in acc.values():
        event_ids.sort()
    return acc


def _events_by_dump_in_order(
    events: list[Event], dumps: tuple[DumpSlice, ...]
) -> list[list[Event]]:
    """Per-dump event lists in the SAME resolved order as ``dumps``.

    ``group_dumps`` is reused rather than re-implemented (D-08 precedent) —
    this only indexes its result by each ``DumpSlice.source_file``.
    """
    by_file = group_dumps(events)
    return [by_file.get(d.source_file, []) for d in dumps]


def _union_exemplars(
    frame_tuples: list[tuple[str, ...]],
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
) -> tuple[str, ...]:
    """D-17: union every contributing signature's full id list, then sample.

    Each signature's ids are resolved by the most-recent-dump-where-present
    rule — walking ``reversed(per_dump_sig_ids)`` and taking the first dump
    whose map holds that frames tuple — the identical idiom
    ``eustack_progression.compute_progression`` already uses to resolve
    display fields, so citation and classification can never disagree about
    which dump a signature means. Returns an empty tuple when none of
    ``frame_tuples`` is present in any dump.
    """
    union: set[str] = set()
    for frames in frame_tuples:
        for sig_ids in reversed(per_dump_sig_ids):
            if frames in sig_ids:
                union.update(sig_ids[frames])
                break
    return tuple(sorted(union)[:_EXEMPLAR_K])


def render_eustack_facts(
    bundle: EustackBundle, events: list[Event]
) -> tuple[str, set[str]]:
    """Render the eu-stack fact block and the set of ids it makes citable.

    Returns ``("", set())`` when ``bundle.analysis.total_threads == 0`` — the
    true absence of ingested eu-stack data (residue-free strip). A healthy,
    zero-flag capture still renders: emptiness is never gated on
    ``bundle.saturation.flags``. Each id in the returned set corresponds to an
    ``[evt:<id>]`` token actually printed in the block — nothing more (D-05).

    This plan renders the role-composition grouping only; the remaining three
    Phase-16 groupings and the capped per-signature listing land in Plan
    18-02.
    """
    if bundle.analysis.total_threads == 0:
        return "", set()

    ids: set[str] = set()
    lines: list[str] = []

    per_dump_sig_ids = [
        _signature_event_ids(dump_events)
        for dump_events in _events_by_dump_in_order(events, bundle.progression.dumps)
    ]

    signatures_by_role: dict[str, list[tuple[str, ...]]] = {}
    for group in bundle.analysis.signatures:
        signatures_by_role.setdefault(group.role, []).append(group.frames)

    # Iterate threads_by_role in its own key order — the dict is built
    # zero-filled in a fixed role order by analyse_eustack, so this needs no
    # import of any private role tuple and is deterministic.
    for role, threads in bundle.analysis.threads_by_role.items():
        if threads == 0:
            continue
        frame_tuples = signatures_by_role.get(role, [])
        exemplars = _union_exemplars(frame_tuples, per_dump_sig_ids)
        if not exemplars:
            # A line with no [evt:] token would be an uncited figure, which
            # the D-05 contract forbids.
            continue
        prefix = _cite_prefix(exemplars, ids)
        signature_count = bundle.analysis.signatures_by_role[role]
        lines.append(
            f"{prefix} eu-stack {sanitise(role)} threads: {threads:,} of "
            f"{bundle.analysis.total_threads:,} total threads across "
            f"{signature_count:,} signatures. ({len(exemplars):,} of "
            f"{threads:,} thread events cited as exemplars)"
        )

    return _load_eustack_fragment().replace(_EUSTACK_LINES_SLOT, "\n".join(lines)), ids


__all__ = ["render_eustack_facts"]
