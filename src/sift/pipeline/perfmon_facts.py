"""Deterministic perfmon fact renderer (PERF-07, Plan 14-03).

``render_perfmon_facts(analysis) -> (block_text, citable_ids)`` is the model-free,
byte-identical-on-re-run source of truth for every perfmon figure surfaced to the
triage prompt. A near-verbatim mirror of ``pipeline/mcm_facts.render_mcm_facts``:
it fills the versioned ``prompts/perfmon_facts.md`` fragment (labels and prose
only — D-06) with figures read **verbatim** from ``analyse_perfmon`` output — the
correlated ``TrendGroup`` spans, their graded ``PerfmonHazard``s and the salient
``CounterTrend`` figures. Numbers originate in Python; wording lives in the
template.

Every printed line begins with an ``[evt:<id>]`` citation token, and the returned
id set is **exactly** those printed ids (the exemplar contract — never expose an
id the model was not shown, D-05). An empty analysis renders to ``("", set())`` so
the Wave-2 splice (plan 14-04) strips residue-free. Every log/CSV-derived value
(counter name, hazard message, window label) is routed through
``render._util.sanitise`` before interpolation (V5 prompt-injection defence,
T-14-05) — mirroring ``mcm_facts``.

Two selections bound the block. D-03 caps the rendered group COUNT at
``_MAX_GROUPS`` (most-severe first) so a correlation storm cannot inflate the
un-budgeted prompt prefix. D-04 prints, per group, only a SALIENT counter subset
(five fixed counters + any counter a rendered hazard cites) matched on the
counter's FINAL backslash segment (Pitfall 2: ``CounterTrend.counter`` may be a
short or a collision-qualified two-segment name). Both are render-time choices:
``perfmon._counter_trends`` keeps its no-allowlist, every-counter fidelity and
``sift perfmon`` still shows all counters.

This is a leaf module: it reads the analyser's model tree and the prompt fragment
only. It must NOT import from ``sift.pipeline.hypothesise`` or ``sift.cli``
(hypothesise imports this, not the reverse).
"""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING

from sift.pipeline.perfmon import MCM_DENIAL_COUNTER
from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.pipeline.perfmon import CounterTrend, PerfmonAnalysis, TrendGroup

_PROMPT_PACKAGE = "sift.prompts"
_PERFMON_FILE = "perfmon_facts.md"
_PERFMON_LINES_SLOT = "<<PERFMON_LINES>>"

# Display order for graded hazards (mirrors mcm_facts._SEVERITY_ORDER) — critical
# first. An unknown severity sorts last rather than raising.
_SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}

# The five salient counters printed per group (D-04), keyed on the counter's
# FINAL backslash segment so a collision-qualified name (``Process(MSTRSvr)\Size(MB)``)
# still matches on ``Size(MB)`` (Pitfall 2). A fixed priority tuple: this is the
# render-time evidence subset only — the correlator keeps every counter.
_SALIENT_COUNTERS: tuple[str, ...] = (
    "Working set cache RAM usage(MB)",
    "RAM used(MB)",
    "Size(MB)",
    "Open Sessions",
    MCM_DENIAL_COUNTER,
)

# Value / slope decimal places, mirroring perfmon's round-at-source discipline
# (_VALUE_DP = 3, SLOPE_DP = 4) so float repr noise cannot vary the rendered
# output between runs — the figures are already rounded at source, this only
# fixes their printed width.
_VALUE_DP = 3
_SLOPE_DP = 4

# Max TrendGroups rendered into the fact block (D-03). A correlation storm of
# dozens of spans could otherwise inflate the un-budgeted prompt prefix past the
# model context. Most-severe-first so a truncated block keeps the worst groups;
# only rendered groups' ids enter the citable set (cited ⊆ prompted).
# ponytail: fixed group ceiling mirroring mcm_facts._MAX_EPISODES; swap for
# budget-aware trimming if real cases ever carry more than this many spans.
_MAX_GROUPS = 8


def _group_severity_rank(group: TrendGroup) -> int:
    """The group's worst hazard-severity rank (lower = more severe).

    Reuses ``_SEVERITY_ORDER`` (critical < warn < info); a group with no hazards
    sorts last. Used to keep the most severe groups when the ``_MAX_GROUPS`` cap
    drops surplus ones — a direct copy of ``mcm_facts._episode_severity_rank``.
    """
    return min(
        (_SEVERITY_ORDER.get(h.severity, len(_SEVERITY_ORDER)) for h in group.hazards),
        default=len(_SEVERITY_ORDER),
    )


def _load_perfmon_fragment() -> str:
    """Load the versioned perfmon fragment from package data (CLI-02).

    Mirrors ``mcm_facts._load_mcm_fragment`` — the same ``importlib.resources``
    idiom, so wording changes touch no path maths.
    """
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_PERFMON_FILE)
        .read_text(encoding="utf-8")
    )


def _cite_prefix(event_ids: tuple[str, ...], ids: set[str]) -> str:
    """Join ``[evt:<id>]`` tokens for ``event_ids`` and record them as citable.

    Only ids that become a printed token enter ``ids`` — the exact D-05 contract.
    """
    ids.update(event_ids)
    return "".join(f"[evt:{eid}]" for eid in event_ids)


def render_perfmon_facts(analysis: PerfmonAnalysis) -> tuple[str, set[str]]:
    """Render the perfmon fact block and the set of ids it makes citable.

    Returns ``("", set())`` when there are no groups (residue-free strip). Each id
    in the returned set corresponds to an ``[evt:<id>]`` token actually printed in
    the block — nothing more (D-05).
    """
    if not analysis.groups:
        return "", set()

    ids: set[str] = set()
    lines: list[str] = []

    # Cap the group count (D-03): keep the most severe groups, dropping surplus.
    # sorted() is stable, so equal-severity groups retain their correlator order —
    # deterministic. Only rendered groups contribute ids, so a dropped group's ids
    # stay out of the citable set (cited ⊆ prompted).
    selected = sorted(analysis.groups, key=_group_severity_rank)[:_MAX_GROUPS]

    for group in selected:
        # Span header — cite the boundary events the span was resolved from.
        prefix = _cite_prefix(group.boundary_event_ids, ids)
        head = f"{prefix} " if prefix else ""
        lines.append(
            f"{head}perfmon {sanitise(group.scope)}-scope span: "
            f"{sanitise(group.label)}."
        )

        # Graded hazards, most severe first (stable, so equal-severity hazards keep
        # their source order — deterministic).
        rendered_hazards = sorted(
            group.hazards,
            key=lambda h: _SEVERITY_ORDER.get(h.severity, len(_SEVERITY_ORDER)),
        )
        hazard_eids: set[str] = set()
        for hz in rendered_hazards:
            hazard_eids.update(hz.event_ids)
            hprefix = _cite_prefix(hz.event_ids, ids)
            hhead = f"{hprefix} " if hprefix else ""
            lines.append(
                f"{hhead}{sanitise(hz.severity)} {sanitise(hz.dimension)}: "
                f"{sanitise(hz.message)}"
            )

        # Salient counter subset (D-04): the five fixed counters (priority order,
        # matched on the final backslash segment) UNION any counter a rendered
        # hazard cites.
        for ct in _select_counters(group, hazard_eids):
            cites = tuple(
                eid
                for eid in (ct.at_denial_event_id, ct.peak_event_id)
                if eid is not None
            )
            # A counter with no event id cannot be a citation source, so it cannot
            # be printed (D-05: no line without an [evt:] token, no uncited figure).
            deduped = tuple(dict.fromkeys(cites))
            if not deduped:
                continue
            cprefix = _cite_prefix(deduped, ids)
            figs: list[str] = []
            if ct.at_denial is not None:
                figs.append(f"at-denial {ct.at_denial:.{_VALUE_DP}f}")
            if ct.peak is not None:
                figs.append(f"peak {ct.peak:.{_VALUE_DP}f}")
            if ct.slope_per_second is not None:
                figs.append(f"slope {ct.slope_per_second:.{_SLOPE_DP}f}/s")
            lines.append(f"{cprefix} {sanitise(ct.counter)}: {', '.join(figs)}")

    return _load_perfmon_fragment().replace(_PERFMON_LINES_SLOT, "\n".join(lines)), ids


def _select_counters(
    group: TrendGroup, hazard_eids: set[str]
) -> list[CounterTrend]:
    """The salient counter subset for a group (D-04), in a deterministic order.

    Salient counters first, in the fixed ``_SALIENT_COUNTERS`` priority order and
    matched on each counter's final backslash segment (Pitfall 2); then any counter
    a rendered hazard cites (event-id overlap) that is not already salient, in the
    group's own counter order. Every ordering is explicit, so the selection is
    byte-identical on re-run.
    """
    selected: list[CounterTrend] = []
    seen: set[int] = set()
    for name in _SALIENT_COUNTERS:
        for ct in group.counters:
            if ct.counter.rsplit("\\", 1)[-1] == name and id(ct) not in seen:
                selected.append(ct)
                seen.add(id(ct))
    for ct in group.counters:
        if id(ct) in seen:
            continue
        cids = {ct.at_denial_event_id, ct.peak_event_id} - {None}
        if cids & hazard_eids:
            selected.append(ct)
            seen.add(id(ct))
    return selected
