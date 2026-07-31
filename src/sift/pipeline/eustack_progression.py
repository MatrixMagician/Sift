"""Dump grouping, ordering and progression over ``pipeline.eustack`` (EUS-07/08).

A leaf module: imports from ``sift.pipeline.eustack`` and is imported by
nothing in that module, so ``EustackAnalysis``/``SaturationAnalysis`` stay
frozen and consumed read-only (17-CONTEXT.md domain section). This module's
own input shape is different from Phase 15/16's — multiple per-dump ``Event``
groups grouped by ``source_file``, not one flat list — which is why it lives
here rather than growing ``eustack.py`` further.

``analyse_eustack_bundle`` groups the case's eu-stack events into per-dump
populations, resolves an explicit dump order (D-01/D-02), runs
``analyse_eustack`` once per dump, and computes the classification/saturation
sections on the LAST dump only (D-11 — the state being diagnosed, never a
union of dumps). A single-dump case is the N=1 case of the same
``ProgressionAnalysis`` shape used for N dumps (see the plan's
``assumption_delta_decision``): one ``DumpSlice``, empty ``step_deltas``, a
zero ``overall_delta``. Multi-dump delta computation and the D-02 fallback
ordering flag are 17-02's work.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from sift.pipeline.eustack import (
    EustackAnalysis,
    FlagSeverity,
    Reason,
    Role,
    SaturationAnalysis,
    SignatureGroup,
    analyse_eustack,
    analyse_saturation,
)

if TYPE_CHECKING:
    from sift.config import EustackThresholdsConfig
    from sift.models import Event
    from sift.pipeline.eustack import ThreadRoleRules

# D-01/D-02: the basis strings the report states verbatim. ORDER_BASIS_FILENAME
# is unused until 17-02 wires the fallback path, but it is declared here so the
# report's vocabulary is fixed in one place from the start.
ORDER_BASIS_SINGLE: str = "single dump — no ordering was required"
ORDER_BASIS_TIMESTAMP: str = "ordered by dump-time timestamp"
ORDER_BASIS_FILENAME: str = (
    "ordered by sorted source file name (at least one dump carries no "
    "dump-time timestamp)"
)

# D-10: population-level phrasing only — no per-TID claim anywhere. Stated
# once here and carried on every ProgressionAnalysis so a renderer cannot
# omit it by construction (mirrors SaturationAnalysis.lock_finding_note).
PROGRESSION_SCOPE_NOTE: str = (
    "Progression is reported as signature-population change across dumps, "
    "never as per-thread continuity — eu-stack output carries no per-thread "
    "identity link across dumps, so TID reuse cannot be established from "
    "this data alone."
)

# D-02: the structural fact and its dimension key, stated once here so the
# report's vocabulary is fixed in one place (mirrors ORDER_BASIS_* above).
# British English throughout; states the limitation without requiring the
# reader to consult the code.
ORDERING_UNVERIFIED_DIMENSION: str = "dump_order_basis"
ORDERING_UNVERIFIED_MESSAGE: str = (
    "Dump ordering rests on sorted file names because at least one dump "
    "carries no dump-time timestamp, so the resulting order is unverified."
)


class DumpSlice(BaseModel):
    """One dump's identity in the resolved order (EUS-08)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_file: str
    # ISO-8601 string, never a datetime — model_dump(mode="json") must stay
    # stable so D-13 byte-identity holds without a serialisation round-trip.
    ts: str | None
    ts_confidence: str
    thread_count: int


class OrderingFlag(BaseModel):
    """A structural fact about dump ordering (D-02): it has no warn/critical
    cut-point pair, so it is the ``PerfmonHazard`` shape, never
    ``SaturationFlag``'s graded-threshold shape (17-PATTERNS.md Pattern 2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    severity: FlagSeverity
    message: str


class SignatureProgression(BaseModel):
    """One signature's identity (from the last dump's classification) plus
    its population history across the resolved dump order (D-07/D-08).

    ``matched_frame``/``leaf_frame`` are the D-07 display projection of the
    full ``frames`` tuple — never the full tuple itself, which stays on the
    model only as the (unused until 17-02) cross-dump join key.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    frames: tuple[str, ...]
    role: Role
    subsystem: str | None
    pattern: str | None
    frame_index: int | None
    reason: Reason | None
    matched_frame: str | None
    leaf_frame: str | None
    counts: tuple[int, ...]
    step_deltas: tuple[int, ...]
    overall_delta: int
    appeared: bool
    vanished: bool


class ProgressionAnalysis(BaseModel):
    """The dump-level and signature-population view over the ordered dump
    sequence (EUS-07/08). Consumes nothing from ``EustackAnalysis`` beyond
    the last dump's ``signatures`` (read-only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dumps: tuple[DumpSlice, ...]
    order_basis: str
    ordering_flags: tuple[OrderingFlag, ...]
    signatures: tuple[SignatureProgression, ...]
    scope_note: str = PROGRESSION_SCOPE_NOTE


class EustackBundle(BaseModel):
    """The whole ``sift eustack`` report surface: Phase 15/16's frozen
    analysis of the LAST dump (D-11), plus this module's progression view."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis: EustackAnalysis
    saturation: SaturationAnalysis
    progression: ProgressionAnalysis


def group_dumps(events: list[Event]) -> dict[str, list[Event]]:
    """Partition eu-stack events by ``source_file`` (one dump per file).

    ``by_file.setdefault(event.source_file, []).append(event)`` over events
    filtered to ``event.source == "eustack"`` — the ``perfmon.py:602-605``
    pattern verbatim: dict-insertion order preserved, never a ``set``, so
    grouping is deterministic across runs (D-13).
    """
    by_file: dict[str, list[Event]] = {}
    for event in events:
        if event.source != "eustack":
            continue
        by_file.setdefault(event.source_file, []).append(event)
    return by_file


def resolve_dump_order(
    dumps: dict[str, list[Event]],
) -> tuple[tuple[str, ...], str, tuple[OrderingFlag, ...]]:
    """Resolve the dump order and state the basis explicitly (D-01/D-02).

    Reads ``.ts``/``.ts_confidence`` off the FIRST thread event
    (``event.thread is not None``) in each group — the dump-time header
    value the adapter copies onto every thread record, never a re-scan of
    ``raw`` text (adapters/eustack.py:215-223).

    - Zero or one dump: no ordering decision to make, ``ORDER_BASIS_SINGLE``.
    - Two or more dumps, every representative timestamped
      (``ts_confidence != "missing"``): sort on ``(ts, source_file)``,
      ``ORDER_BASIS_TIMESTAMP`` (D-01).
    - Any representative untimestamped (``ts_confidence == "missing"``): sort
      on ``source_file`` alone, ``ORDER_BASIS_FILENAME``, and raise exactly
      one ``OrderingFlag`` at severity ``warn`` (D-02). No timestamp is ever
      assigned, inferred, interpolated or filesystem-derived for the
      untimestamped dump — its own ``DumpSlice.ts``/``ts_confidence`` stay
      exactly what the adapter reported (ADR 0012 record-don't-apply
      precedent). No operator-facing ordering override exists anywhere in
      this module (D-03).
    """
    keys = list(dumps.keys())
    if len(keys) <= 1:
        return tuple(keys), ORDER_BASIS_SINGLE, ()

    representatives = {
        key: next((e for e in events if e.thread is not None), None)
        for key, events in dumps.items()
    }
    # A threadless dump group (e.g. a truncated capture) is treated the same
    # as a "missing" ts_confidence — it forces the D-02 filename fallback
    # rather than crashing on the old bare next() (mirrors the guarded
    # ``dump_slices`` construction below).
    timestamped = {
        key: rep
        for key, rep in representatives.items()
        if rep is not None and rep.ts_confidence != "missing"
    }
    if len(timestamped) == len(keys):
        ordered = tuple(
            sorted(keys, key=lambda k: (timestamped[k].ts, k))
        )
        return ordered, ORDER_BASIS_TIMESTAMP, ()

    ordered = tuple(sorted(keys))
    flag = OrderingFlag(
        dimension=ORDERING_UNVERIFIED_DIMENSION,
        severity="warn",
        message=ORDERING_UNVERIFIED_MESSAGE,
    )
    return ordered, ORDER_BASIS_FILENAME, (flag,)


def compute_progression(
    ordered_analyses: tuple[EustackAnalysis, ...],
    dump_slices: tuple[DumpSlice, ...],
) -> tuple[SignatureProgression, ...]:
    """Join per-dump signature groups on the full ``frames`` tuple (D-08/D-09).

    ``dump_slices`` is read only for its length — a defensive assertion that
    the caller passed one analysis per resolved dump, never a lookup — so
    every signature's ``counts`` has exactly one entry per dump in order.

    For each signature appearing in ANY dump, ``counts`` holds its thread
    count per dump (``0`` where absent), ``step_deltas`` the consecutive-pair
    differences (D-08), and ``overall_delta`` the last count minus the first
    — always both, so a population that grew then shrank is visible rather
    than flattened to one figure. ``appeared``/``vanished`` are derived from
    ``counts`` alone (D-09), never tracked as independent state. Display and
    classification fields come from the signature's group in the LAST dump
    where it appears — not necessarily the last dump overall — so a vanished
    signature still carries a meaningful classification instead of empty
    cells.

    Ranked on the explicit total key ``(-abs(overall_delta), -counts[-1],
    frames)`` (D-09): absolute delta first, current count as a tie-break,
    the frames tuple as the final tie-break so the order is total and the
    output is byte-identical on re-run — a sort on absolute delta alone is
    not a total order over ties. No cap: D-09's changed-only filter is a
    rendering concern for 17-03, so every signature is carried here.
    """
    assert len(ordered_analyses) == len(dump_slices)

    per_dump_groups: tuple[dict[tuple[str, ...], SignatureGroup], ...] = tuple(
        {group.frames: group for group in analysis.signatures}
        for analysis in ordered_analyses
    )

    # First-appearance order across dumps, via dict-key insertion — never a
    # set — so the join is deterministic before the explicit re-sort below.
    frame_keys: dict[tuple[str, ...], None] = {}
    for groups in per_dump_groups:
        for frames in groups:
            frame_keys.setdefault(frames, None)

    progressions: list[SignatureProgression] = []
    for frames in frame_keys:
        counts = tuple(
            groups[frames].thread_count if frames in groups else 0
            for groups in per_dump_groups
        )
        step_deltas = tuple(after - before for before, after in pairwise(counts))
        overall_delta = counts[-1] - counts[0]
        appeared = counts[0] == 0 and counts[-1] != 0
        vanished = counts[0] != 0 and counts[-1] == 0

        classification = next(
            groups[frames] for groups in reversed(per_dump_groups) if frames in groups
        )
        matched_frame = (
            classification.frames[classification.frame_index]
            if classification.frame_index is not None
            else None
        )
        leaf_frame = classification.frames[0] if classification.frames else None

        progressions.append(
            SignatureProgression(
                frames=frames,
                role=classification.role,
                subsystem=classification.subsystem,
                pattern=classification.pattern,
                frame_index=classification.frame_index,
                reason=classification.reason,
                matched_frame=matched_frame,
                leaf_frame=leaf_frame,
                counts=counts,
                step_deltas=step_deltas,
                overall_delta=overall_delta,
                appeared=appeared,
                vanished=vanished,
            )
        )

    progressions.sort(key=lambda s: (-abs(s.overall_delta), -s.counts[-1], s.frames))
    return tuple(progressions)


def analyse_eustack_bundle(
    events: list[Event],
    rules: ThreadRoleRules,
    rules_hash: str,
    thresholds: EustackThresholdsConfig,
) -> EustackBundle:
    """Group, order, classify per dump, and render the last dump's
    classification/saturation plus the whole progression view (EUS-07/08/09).

    Zero dumps (no eu-stack events at all) yields the same zero-valued
    ``EustackAnalysis``/``SaturationAnalysis`` ``analyse_eustack``/
    ``analyse_saturation`` already return for zero events — never an
    exception — so the empty-case exit-0 contract (D-12) holds without a
    special branch here.
    """
    dumps = group_dumps(events)
    order, order_basis, ordering_flags = resolve_dump_order(dumps)

    ordered_analyses = tuple(
        analyse_eustack(dumps[key], rules, rules_hash) for key in order
    )
    last_analysis = (
        ordered_analyses[-1]
        if ordered_analyses
        else analyse_eustack([], rules, rules_hash)
    )

    saturation = analyse_saturation(last_analysis, thresholds)

    dump_slices: list[DumpSlice] = []
    for key in order:
        dump_events = dumps[key]
        representative = next(
            (e for e in dump_events if e.thread is not None), None
        )
        thread_count = sum(1 for e in dump_events if e.thread is not None)
        ts = (
            representative.ts.isoformat()
            if representative is not None and representative.ts is not None
            else None
        )
        ts_confidence = (
            representative.ts_confidence if representative is not None else "missing"
        )
        dump_slices.append(
            DumpSlice(
                source_file=key,
                ts=ts,
                ts_confidence=ts_confidence,
                thread_count=thread_count,
            )
        )

    signatures = compute_progression(ordered_analyses, tuple(dump_slices))

    progression = ProgressionAnalysis(
        dumps=tuple(dump_slices),
        order_basis=order_basis,
        ordering_flags=ordering_flags,
        signatures=signatures,
    )
    return EustackBundle(
        analysis=last_analysis, saturation=saturation, progression=progression
    )
