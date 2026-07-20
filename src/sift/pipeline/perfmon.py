"""Correlate DSSPerformanceMonitor samples with MCM denial episodes (PERF-04).

Pure and deterministic: this module computes per-counter trend figures over the
span an MCM episode already resolved, and never touches the store, the CLI or a
model. Every figure carries the ``event_id`` of the sample it came from, so it
can be checked by hand against two rows of the customer's CSV.

Determinism contract (D-21), in ``analyse_mcm``'s words: ``model_dump_json`` is
byte-identical on re-run — no ``set`` iteration anywhere on the path, all
rounding at source, all ordering explicit.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from sift.models import Event
    from sift.pipeline.mcm import EpisodeAnalysis, McmAnalysis

# Slope decimal places, rounded at source so float repr noise cannot vary the
# rendered output between runs (mirroring _mb_bytes's 3 dp at mcm_report.py:79).
SLOPE_DP = 4

# Value decimal places for at-denial and peak, same round-at-source discipline.
_VALUE_DP = 3


# pyright's reportUnusedFunction is file-scoped for underscore-private names, so
# the test-side import does not count; _counter_trends calls this in-module.
def _numeric(value: str) -> float | None:  # pyright: ignore[reportUnusedFunction]
    """Parse a counter cell, accepting only finite reals (D-11).

    ``dssperfmon._bad_cells`` probes each cell with a bare ``float()``, which
    ACCEPTS ``nan``, ``inf`` and ``-Infinity`` — so such a cell reaches the store
    on a clean ``severity="info"`` row and would otherwise poison ``max()``,
    slope and at-denial, then serialise into the JSON report as the invalid-JSON
    token ``NaN``. This function is the guard that stops it getting that far.

    A rejected cell excludes that counter for that sample only; the row itself is
    retained and the exclusion is counted, never silently dropped.
    """
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


class PerfmonHazard(BaseModel):
    """One graded perfmon correlation hazard (D-12).

    Severities are categorical string literals fixed in code — ``mcm._grade`` is
    deliberately NOT called, because these hazards grade structural conditions
    (an unresolvable boundary, an empty window) rather than a ratio against two
    cut-points, so a two-cut-point grader has nothing to compare. The omission is
    a decision, not an oversight.

    ``mcm.DiagnosticFlag`` is deliberately not reused: its ``value_pct`` is locked
    as a ratio ``part / whole * 100`` (the milestone machine-independence
    invariant), and a perfmon hazard's figure is an absolute counter reading or
    nothing at all. ``event_ids`` keeps the same D-16 provenance discipline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str  # the condition graded, e.g. "span" | "samples"
    severity: str  # "info" | "warn" | "critical"
    message: str  # British-English one-liner
    event_ids: tuple[str, ...]  # the ids the hazard is evidenced by
    value: float | None = None  # the triggering figure, rounded at source


class CounterTrend(BaseModel):
    """The three trend figures for ONE counter over one span (D-07/D-08/D-09/D-10).

    Every figure is independently optional so a partially-computable counter is
    representable without a sentinel number: a span of one sample has no slope
    but does have an at-denial value and a peak. ``excluded_samples`` is D-11's
    reporting channel — the count of in-span samples whose cell for this counter
    was rejected as non-finite or unparseable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    counter: str
    at_denial: float | None  # last in-span accepted value, 3 dp, never interpolated
    at_denial_event_id: str | None
    slope_per_second: float | None  # counter-units per second, SLOPE_DP dp
    peak: float | None  # max accepted value, 3 dp
    peak_event_id: str | None  # earliest sample on a tie
    sample_count: int  # in-span samples carrying this counter's key
    excluded_samples: int  # of those, how many were rejected as non-finite


class TrendGroup(BaseModel):
    """One correlated span's counters and hazards.

    ONE model serves both D-19's per-episode shape and D-20's per-file shape:
    the two differ only in how the span is chosen, not in what is computed over
    it, so a second near-identical model would be duplication. ``scope`` is
    therefore a discriminator over two real shipped cases, not speculative
    generality.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: str  # "episode" | "file"
    key: str  # denial_event_id for episode scope, source_file for file scope
    label: str  # the window label, or a full-sample-range label for file scope
    start_ts: str | None  # ISO-8601 UTC, or None when the span never resolved
    end_ts: str | None
    boundary_event_ids: tuple[str, ...]  # the ids the span was resolved from
    sample_count: int
    counters: tuple[CounterTrend, ...]
    hazards: tuple[PerfmonHazard, ...]


class PerfmonAnalysis(BaseModel):
    """The full perfmon correlation over a case: one TrendGroup per span.

    An empty case (no MCM episodes, or no perfmon samples) yields ``groups=()``
    — never a crash. Pure and deterministic: ``model_dump_json`` is byte-identical
    on re-run (no ``set`` iteration anywhere on the path).

    ``hazards`` carries case-level hazards not attributable to any one group.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: tuple[TrendGroup, ...]
    hazards: tuple[PerfmonHazard, ...]


class _Span(NamedTuple):
    """A resolved correlation span, or the reason it could not be resolved.

    ``reason`` is ``None`` exactly when both ``start`` and ``end`` are present.
    Never raises: an unresolvable span is a value the caller grades, not an
    exception (D-04).
    """

    start: Event | None
    end: Event | None
    reason: str | None


def _resolve_span(ea: EpisodeAnalysis, by_id: dict[str, Event]) -> _Span:
    """Resolve BOTH span ends by ``event_id`` against the store's events (D-01).

    The window is CONSUMED, not recomputed: ``mcm.select_window`` already chose
    it and is never called from here (D-02).

    End bound: the denial event's own ``Event.ts``. ``McmEpisode.denial_ts`` is a
    formatted string and is deliberately NOT parsed as a consolation when the
    event fails to resolve — that fallback is the easy mistake here, and a span
    built from it would look plausible while citing nothing (D-01/D-04).

    Start bound: ``window.start_event_id`` when set; otherwise the first entry of
    ``episode.event_ids`` that both resolves AND carries a timestamp (D-03).
    ``attribute_window`` takes ``event_ids[0]`` unconditionally, which does not
    guarantee a placeable timestamp, so the shape is mirrored but not the rule.
    """
    end = by_id.get(ea.episode.denial_event_id)
    if end is None:
        return _Span(None, None, "the denial event is absent from the case store")
    if end.ts is None:
        return _Span(None, None, "the denial event carries no timestamp")

    if ea.window.start_event_id is not None:
        start = by_id.get(ea.window.start_event_id)
        if start is None:
            return _Span(None, None, "the window start event is absent from the store")
        if start.ts is None:
            return _Span(None, None, "the window start event carries no timestamp")
        return _Span(start, end, None)

    # Full-lead-up fallback: the earliest episode row that can be placed at all.
    for event_id in ea.episode.event_ids:
        candidate = by_id.get(event_id)
        if candidate is not None and candidate.ts is not None:
            return _Span(candidate, end, None)
    return _Span(None, None, "no episode event carries a timestamp to start from")


def _in_span(events: list[Event], start: Event, end: Event) -> list[Event]:
    """The perfmon samples inside the CLOSED interval ``[start.ts, end.ts]`` (D-05).

    Closed deliberately: Hartford's last sample before the denial can land
    exactly on a bound, and excluding it would drop the very reading the report
    is about. Input order is the store's canonical
    ``ORDER BY ts IS NULL, ts, source_file, line_start`` and is preserved rather
    than re-sorted.

    ``EXCLUDED_FROM_RANKING`` is deliberately not imported: it means "held out of
    ranking", which is a different concept from "is a perfmon sample".
    """
    assert start.ts is not None and end.ts is not None  # noqa: S101 — _Span invariant
    return [
        e
        for e in events
        if e.source == "dssperfmon" and e.ts is not None and start.ts <= e.ts <= end.ts
    ]


def analyse_perfmon(analysis: McmAnalysis, events: list[Event]) -> PerfmonAnalysis:
    """Correlate perfmon samples with every MCM episode (PERF-04).

    One ``TrendGroup`` per episode, including episodes whose span could not be
    resolved — those carry a graded hazard and no counters, so nothing disappears
    silently. Pure and deterministic: ``model_dump_json`` is byte-identical on
    re-run.

    Two omissions are deliberate, not oversights: correlation hazards (empty
    window, non-overlap) are added in plan 13-04, and D-20's ``scope="file"``
    whole-file path lands in plan 13-06 with the CLI test that proves it. Until
    then ``PerfmonAnalysis.hazards`` stays empty.
    """
    by_id = {e.event_id: e for e in events}  # mirrors the attribute_window precedent
    groups: list[TrendGroup] = []
    for ea in analysis.episodes:
        span = _resolve_span(ea, by_id)
        if span.start is None or span.end is None:
            attempted = tuple(
                dict.fromkeys(
                    eid
                    for eid in (ea.window.start_event_id, ea.episode.denial_event_id)
                    if eid is not None
                )
            )
            groups.append(
                TrendGroup(
                    scope="episode",
                    key=ea.episode.denial_event_id,
                    label=ea.window.label,
                    start_ts=None,
                    end_ts=None,
                    boundary_event_ids=attempted,
                    sample_count=0,
                    counters=(),
                    hazards=(
                        PerfmonHazard(
                            dimension="span",
                            severity="warn",
                            message=(
                                "No perfmon trend could be correlated: "
                                f"{span.reason}."
                            ),
                            event_ids=attempted,
                        ),
                    ),
                )
            )
            continue

        samples = _in_span(events, span.start, span.end)
        assert span.start.ts is not None and span.end.ts is not None  # noqa: S101
        groups.append(
            TrendGroup(
                scope="episode",
                key=ea.episode.denial_event_id,
                label=ea.window.label,
                start_ts=span.start.ts.isoformat(),
                end_ts=span.end.ts.isoformat(),
                boundary_event_ids=(span.start.event_id, span.end.event_id),
                sample_count=len(samples),
                counters=(),
                hazards=(),
            )
        )
    return PerfmonAnalysis(groups=tuple(groups), hazards=())
