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

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from sift.pipeline.eustack import (
    EustackAnalysis,
    FlagSeverity,
    Reason,
    Role,
    SaturationAnalysis,
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
    - Any representative untimestamped: the D-02 fallback and its loud flag
      are 17-02's work — raise loudly here rather than silently falling
      through to an undeclared order.
    """
    keys = list(dumps.keys())
    if len(keys) <= 1:
        return tuple(keys), ORDER_BASIS_SINGLE, ()

    representatives = {
        key: next(e for e in events if e.thread is not None)
        for key, events in dumps.items()
    }
    if all(representatives[key].ts_confidence != "missing" for key in keys):
        ordered = tuple(
            sorted(keys, key=lambda k: (representatives[k].ts, k))
        )
        return ordered, ORDER_BASIS_TIMESTAMP, ()

    raise NotImplementedError(
        "dump ordering fallback for an untimestamped dump (D-02) is 17-02's "
        "work; this case's ordering cannot be resolved yet"
    )


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

    if order:
        analyses = {
            key: analyse_eustack(dumps[key], rules, rules_hash) for key in order
        }
        last_analysis = analyses[order[-1]]
    else:
        last_analysis = analyse_eustack([], rules, rules_hash)

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

    signatures: list[SignatureProgression] = []
    for group in last_analysis.signatures:
        matched_frame = (
            group.frames[group.frame_index] if group.frame_index is not None else None
        )
        leaf_frame = group.frames[0] if group.frames else None
        signatures.append(
            SignatureProgression(
                frames=group.frames,
                role=group.role,
                subsystem=group.subsystem,
                pattern=group.pattern,
                frame_index=group.frame_index,
                reason=group.reason,
                matched_frame=matched_frame,
                leaf_frame=leaf_frame,
                counts=(group.thread_count,),
                step_deltas=(),
                overall_delta=0,
                appeared=False,
                vanished=False,
            )
        )
    # Explicit total order, mirroring analyse_eustack()'s own
    # "-thread_count, frames" discipline: descending on the LAST (current)
    # count, ties broken ascending on the frames tuple. Never
    # Counter.most_common(), never a set iteration.
    signatures.sort(key=lambda s: (-s.counts[-1], s.frames))

    progression = ProgressionAnalysis(
        dumps=tuple(dump_slices),
        order_basis=order_basis,
        ordering_flags=ordering_flags,
        signatures=tuple(signatures),
    )
    return EustackBundle(
        analysis=last_analysis, saturation=saturation, progression=progression
    )
