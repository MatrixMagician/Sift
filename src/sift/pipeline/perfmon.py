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
from typing import TYPE_CHECKING, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from sift.adapters.dssperfmon import (
    _DRIFT_ATTR,  # pyright: ignore[reportPrivateUsage] — imported, never redeclared, so the marker and its reader cannot drift apart (D-15)
    _RESERVED_ATTRS,  # pyright: ignore[reportPrivateUsage] — the adapter owns these keys; importing the single source of truth stops the exclusion set drifting
)

if TYPE_CHECKING:
    from sift.models import Event
    from sift.pipeline.mcm import EpisodeAnalysis, McmAnalysis

# Slope decimal places, rounded at source so float repr noise cannot vary the
# rendered output between runs (mirroring _mb_bytes's 3 dp at mcm_report.py:79).
SLOPE_DP = 4

# Value decimal places for at-denial and peak, same round-at-source discipline.
_VALUE_DP = 3

# Hazard dimension names (D-12). Constants rather than inline literals so the
# renderer in plan 13-05 and the tests key off one spelling.
HAZARD_SPAN = "span"
HAZARD_NON_OVERLAP = "non_overlap"
HAZARD_DENIAL_ALWAYS_ZERO = "denial_always_zero"
HAZARD_COUNTER_SET_DRIFT = "counter_set_drift"
# WR-03: info-severity disclosure that some perfmon samples carried no placeable
# timestamp, so they fell outside the sample range and every figure over it. They
# are counted and cited, never silently dropped ("nothing disappears silently").
HAZARD_UNPLACEABLE_SAMPLES = "unplaceable_samples"

# The counter whose flat zero contradicts a detected denial. REPORTED FLAG ONLY:
# no branch of span resolution, sample selection or figure computation reads it,
# so it can never steer a correlation (D-16). Grep confirms it appears nowhere in
# _resolve_span, _in_span or _counter_trends.
MCM_DENIAL_COUNTER = "Total MCM Denial"

# D-20: the window label used when there are no episodes and therefore no
# window at all. Stated plainly, because the report must never let a
# full-file trend be read as a correlation against a denial that was never
# detected. Free of Markdown metacharacters so it survives ``_field`` intact.
FULL_RANGE_LABEL = (
    "Full sample range (no MCM denial episode detected, so no correlation "
    "window was resolved)"
)

# D-20/WR-03: the label for a file whose every sample lost its timestamp. It
# still gets a group — a boundless disclosure carrying only the unplaceable-
# samples hazard — rather than vanishing, because the report must never drop a
# file the adapter went to trouble to retain. Free of Markdown metacharacters.
NO_PLACEABLE_LABEL = (
    "No perfmon sample in this file carried a placeable timestamp, so no sample "
    "range could be resolved and no trend was computed (samples disclosed as a "
    "hazard, not dropped)"
)

# Cited-id ceiling per hazard, with the true total stated in the message. A file
# where every row drifted would otherwise put one event_id per row into a single
# hazard — the unbounded-growth problem WR-02's _NOTE_CAP solved, reappearing in
# a new location (T-13-HAZDOS).
_CITE_CAP = 10


def _numeric(value: str) -> float | None:
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
    # Literal, not bare str (WR-04): Pydantic rejects a typo'd severity at
    # construction and pyright catches it at the call site, so a mistyped
    # "criticla" can never sneak through and rank below "info" in the summary.
    severity: Literal["info", "warn", "critical"]
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

    scope: Literal["episode", "file"]  # Literal, not str, so a typo can't render
    # as "File" in _group_section (WR-04)
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

    Every hazard is attributable to exactly one span, so hazards live on
    ``TrendGroup``; there is deliberately no case-level hazard collection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: tuple[TrendGroup, ...]


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
    is about. Sorted on ``(ts, event_id)`` here (WR-02): ``analyse_perfmon``
    accepts a plain list a caller may have assembled in any order, and the
    at-denial (``accepted[-1]``), slope-origin (``accepted[0]``) and peak
    tie-break all read positionally — so the figures must depend on the timeline,
    not the argument order, and a scrambled list must never yield a negative
    ``elapsed`` that inverts the slope. This mirrors ``_placeable_samples``.

    ``EXCLUDED_FROM_RANKING`` is deliberately not imported: it means "held out of
    ranking", which is a different concept from "is a perfmon sample".
    """
    assert start.ts is not None and end.ts is not None  # noqa: S101 — _Span invariant
    return sorted(
        (
            e
            for e in events
            if e.source == "dssperfmon"
            and e.ts is not None
            and start.ts <= e.ts <= end.ts
        ),
        key=lambda e: (e.ts, e.event_id),  # pyright: ignore[reportReturnType] — ts filtered non-None above
    )


def _counter_trends(samples: list[Event]) -> tuple[CounterTrend, ...]:
    """At-denial, slope and peak for every counter in the span (D-07..D-11).

    No allowlist: every key that is not adapter provenance is swept, so a counter
    set unlike Hartford's 22 is fully covered. Names are collected with
    ``dict.fromkeys`` over the canonically-ordered samples and then emitted sorted
    by name, so the sequence is explicit and stable across runs (D-21).
    """
    if not samples:
        return ()  # samples[0]/samples[-1] below would raise IndexError

    names = dict.fromkeys(
        key
        for sample in samples
        for key in sample.attrs
        # Provenance, not a counter: a crafted counter name must not be able to
        # surface byte_offset or host as a trend (T-13-ATTRSWEEP).
        if key not in _RESERVED_ATTRS
    )

    trends: list[CounterTrend] = []
    for name in sorted(names):
        present = [s for s in samples if name in s.attrs]
        accepted = [
            (v, s) for s in present if (v := _numeric(s.attrs[name])) is not None
        ]
        excluded = len(present) - len(accepted)

        if not accepted:
            # Reported as uncomputable, never omitted — nothing disappears silently.
            trends.append(
                CounterTrend(
                    counter=name,
                    at_denial=None,
                    at_denial_event_id=None,
                    slope_per_second=None,
                    peak=None,
                    peak_event_id=None,
                    sample_count=len(present),
                    excluded_samples=excluded,
                )
            )
            continue

        # D-09: the LAST accepted in-span sample, never interpolated — an
        # interpolated figure cites no real event and cannot be checked
        # against the customer's CSV.
        last_value, last_sample = accepted[-1]
        first_value, first_sample = accepted[0]

        # D-10: max() returns the FIRST maximal element, so a tie already
        # resolves to the earliest sample. Refactoring this to sorted(...)[-1]
        # would silently flip that to the latest.
        peak_value, peak_sample = max(accepted, key=lambda pair: pair[0])

        assert first_sample.ts is not None and last_sample.ts is not None  # noqa: S101
        elapsed = (last_sample.ts - first_sample.ts).total_seconds()
        # Guarded BEFORE dividing, not with an exception handler. One accepted
        # sample (or several sharing a timestamp) is normal at a 30 s interval
        # against a short MCM descent — no slope, and no hazard either.
        slope = (
            None
            if elapsed == 0.0
            else round((last_value - first_value) / elapsed, SLOPE_DP)
        )

        trends.append(
            CounterTrend(
                counter=name,
                at_denial=round(last_value, _VALUE_DP),
                at_denial_event_id=last_sample.event_id,
                slope_per_second=slope,
                peak=round(peak_value, _VALUE_DP),
                peak_event_id=peak_sample.event_id,
                sample_count=len(present),
                excluded_samples=excluded,
            )
        )
    return tuple(trends)


def _placeable_samples(events: list[Event]) -> list[Event]:
    """Every timestamped perfmon sample in the case, in explicit stable order.

    Sorted here rather than trusting input order: ``analyse_perfmon`` accepts a
    plain list, which a caller may have assembled in any order, and the
    non-overlap message names this list's first and last entries (D-21).
    """
    return sorted(
        (e for e in events if e.source == "dssperfmon" and e.ts is not None),
        key=lambda e: (e.ts, e.event_id),  # pyright: ignore[reportReturnType] — ts is filtered non-None above
    )


def _hazard_non_overlap(
    start: Event, end: Event, all_samples: list[Event]
) -> PerfmonHazard:
    """Zero in-span samples: a CRITICAL hazard, never an empty trend table (D-06).

    Zero-in-span IS the wrong-timezone, wrong-day or wrong-host symptom, so it is
    the loud flag rather than an absence of data. Presenting figures computed
    from whatever samples happen to be nearby would be a fabricated alignment
    (T-13-FALSEJOIN); emitting an empty table would be a silent one.

    ``severity="critical"`` is a categorical literal fixed in code (D-13):
    nothing here is a ratio against two cut-points, so ``mcm._grade`` has nothing
    to compare and is deliberately not called. ``value`` is ``None`` for the same
    reason — the absence of a figure is precisely why ``mcm.DiagnosticFlag`` was
    not reused (D-12).
    """
    assert start.ts is not None and end.ts is not None  # noqa: S101 — _Span invariant
    span_text = f"{start.ts.isoformat()} to {end.ts.isoformat()}"
    cited = [start.event_id, end.event_id]

    if all_samples:
        first, last = all_samples[0], all_samples[-1]
        assert first.ts is not None and last.ts is not None  # noqa: S101 — filtered
        coverage = (
            f"the case's perfmon samples cover "
            f"{first.ts.isoformat()} to {last.ts.isoformat()}"
        )
        cited += [first.event_id, last.event_id]
    else:
        # Guarded BEFORE indexing: with no perfmon events at all there is no
        # first or last sample to name, and all_samples[0] would raise.
        coverage = "the case carries no perfmon samples at all"

    return PerfmonHazard(
        dimension=HAZARD_NON_OVERLAP,
        severity="critical",
        message=(
            f"No perfmon samples fall inside the correlated span {span_text}; "
            f"{coverage}. The two artefacts do not overlap in time, so no trend "
            "is reported rather than one computed from unrelated samples. This "
            "hazard covers time non-overlap only, not host identity: a sample "
            "from the wrong host whose clock overlaps will not trip it "
            "(multi-host correlation is deferred to PERFV2-02)."
        ),
        event_ids=tuple(dict.fromkeys(cited)),
        value=None,
    )


def _cited(event_ids: list[str]) -> tuple[tuple[str, ...], int]:
    """Deduplicate, cap and report the true total of a citation list.

    ``dict.fromkeys`` rather than ``set``: insertion order is preserved, so the
    tuple cannot vary between runs (D-21). The total is returned separately so
    the message can state what the cap hid (T-13-HAZDOS).
    """
    unique = tuple(dict.fromkeys(event_ids))
    return unique[:_CITE_CAP], len(unique)


def _find_counter_key(attrs: dict[str, str]) -> tuple[str, ...]:
    """Every attrs key holding ``MCM_DENIAL_COUNTER``, in sorted order.

    Plan 13-03's ``_qualify_counter_names`` rewrites only COLLIDING short names
    to their last two backslash segments, so both the bare ``Total MCM Denial``
    and a qualified ``Object(Instance)\\Total MCM Denial`` are live spellings in
    shipped data — the bare form is not guaranteed.

    Returns a TUPLE rather than the single key the plan sketched: when a CSV
    carries the counter under two instances, checking only one would let a
    genuinely non-zero instance be masked by a zero one (T-13-EVADE). Sorted, so
    the order never depends on dict insertion.
    """
    if MCM_DENIAL_COUNTER in attrs:
        return (MCM_DENIAL_COUNTER,)
    return tuple(
        sorted(key for key in attrs if key.rsplit("\\", 1)[-1] == MCM_DENIAL_COUNTER)
    )


def _hazard_denial_always_zero(
    denial_event_id: str, samples: list[Event]
) -> PerfmonHazard | None:
    """A flat-zero denial counter contradicted by a real denial (D-14).

    Fires only against a DETECTED denial: the caller reaches this once per
    episode, so a denial always exists here, and a case with no episodes never
    reaches it at all. Without a denial to contradict, a zero counter is just a
    zero counter — and a flag that fires on every healthy case trains the reader
    to ignore the one that matters.

    ``severity="warn"`` is categorical (D-13). The counter is a REPORTED FLAG
    only and is never a correlation input (D-16).
    """
    readings: list[tuple[float, Event]] = []
    for sample in samples:
        for key in _find_counter_key(sample.attrs):
            # Numeric, never `value == "0"`: a string test gets both directions
            # wrong — "0.0" and "-0" ARE zero and would be missed, while a
            # prefix test would fire on "0.0000001", which is demonstrably live.
            value = _numeric(sample.attrs[key])
            if value is not None:
                readings.append((value, sample))

    if not readings or any(value != 0.0 for value, _ in readings):
        return None

    cited, total = _cited([denial_event_id, *(s.event_id for _, s in readings)])
    return PerfmonHazard(
        dimension=HAZARD_DENIAL_ALWAYS_ZERO,
        severity="warn",
        message=(
            f"{MCM_DENIAL_COUNTER} read 0 on all {len(readings)} in-span "
            "reading(s) despite a detected MCM denial in this window, so the "
            "counter is almost certainly not wired on this host and must not be "
            f"read as evidence that no denial occurred. Citing {len(cited)} of "
            f"{total} evidencing event(s)."
        ),
        event_ids=cited,
        value=0.0,
    )


def _hazard_counter_set_drift(samples: list[Event]) -> PerfmonHazard | None:
    """In-span samples whose counter set drifted from the header (D-15).

    Reads the ``_DRIFT_ATTR`` marker plan 13-03 writes at ingest and NOTHING
    else. Row widths, cell counts and counter-key set differences are
    deliberately not re-derived here: ingest already knew, and a second detector
    could disagree with the adapter about what drifted. The marker is also inside
    the adapter's ``_RESERVED_ATTRS``, so a crafted counter name cannot forge or
    suppress it (T-13-DRIFTTRUST) — a width recount would have no such guarantee.

    ``stats.notes`` is explicitly NOT the source: WR-02 caps notes at ten per
    category, so a file with more than ten drifted rows silently stops noting.
    The per-event marker has no such ceiling, and an Event carries an
    ``event_id`` a note never could.
    """
    # Explicit sort with an event_id tie-breaker rather than input order, so the
    # citation tuple is identical across runs even if two samples share a ts.
    drifted = sorted(
        (s for s in samples if _DRIFT_ATTR in s.attrs),
        key=lambda s: (s.ts, s.event_id),  # pyright: ignore[reportArgumentType] — _in_span guarantees ts is not None
    )
    if not drifted:
        return None

    cited, total = _cited([s.event_id for s in drifted])
    return PerfmonHazard(
        dimension=HAZARD_COUNTER_SET_DRIFT,
        severity="warn",
        message=(
            f"{total} in-span sample(s) carry a counter set that drifted from "
            "the file's header, so their counters are aligned by position "
            "against a header that no longer describes them and the trend "
            f"figures over this span may be incomplete. Citing {len(cited)} of "
            f"{total} drifted event(s)."
        ),
        event_ids=cited,
        value=float(total),
    )


def _hazard_unplaceable_samples(unplaceable: list[Event]) -> PerfmonHazard | None:
    """Perfmon samples that carried no placeable timestamp (WR-03).

    ``_in_span`` and ``_file_scope_groups`` both require ``Event.ts is not None``,
    so a degraded ``severity="unknown"`` sample with a broken stamp is excluded
    from ``sample_count``, from the trends and from every other hazard. The
    adapter went to real trouble to keep those rows (``_fallback_event``, coverage
    accounting); discarding them without a word violates "nothing disappears
    silently". This is that disclosure channel — count and cite, never drop.

    ``severity="info"`` is categorical (D-13): an unplaceable sample is a data-
    completeness note, not a correlation failure. Returns ``None`` when the list
    is empty so the caller can append it unconditionally. Sorted on ``event_id``
    before capping, so the cited tuple is identical across runs even when the
    samples arrived in any order (D-21), mirroring ``_hazard_counter_set_drift``.
    """
    if not unplaceable:
        return None
    ordered = sorted(unplaceable, key=lambda e: e.event_id)
    cited, total = _cited([e.event_id for e in ordered])
    return PerfmonHazard(
        dimension=HAZARD_UNPLACEABLE_SAMPLES,
        severity="info",
        message=(
            f"{total} perfmon sample(s) for this file carry no placeable "
            "timestamp, so they fall outside the sample range and every trend "
            "figure computed over it; they are disclosed here rather than "
            f"dropped silently. Citing {len(cited)} of {total} sample(s)."
        ),
        event_ids=cited,
        value=float(total),
    )


def _file_scope_groups(perfmon_events: list[Event]) -> tuple[TrendGroup, ...]:
    """One full-sample-range TrendGroup per source file (D-20).

    Reached only when the case has NO episodes, so there is no window to
    correlate against. The figures are identical IN KIND to the episode path —
    literally the same ``_counter_trends`` call, never a second implementation —
    but they are computed over the file's whole sample range rather than a
    denial window. That difference is why ``FULL_RANGE_LABEL`` says so plainly:
    the report must state that no correlation was performed rather than let a
    whole-file trend be silently substituted for one.

    Grouping is by ``Event.source_file`` via ``dict.fromkeys`` over the
    canonically-ordered event list, so first-appearance order is preserved and
    no ``set`` iteration can vary the output between runs (D-21). Samples within
    a file are sorted on ``(ts, event_id)`` (WR-02): ``analyse_perfmon`` accepts
    a plain list a caller may have assembled in any order, and ``_counter_trends``
    reads the first and last sample positionally.

    Samples that lost their timestamp are disclosed, never dropped (WR-03). A
    file that still has placeable samples gets its usual trend group PLUS an
    ``unplaceable_samples`` info hazard counting the untimestamped remainder; a
    file whose EVERY sample lost its timestamp gets a boundless disclosure group
    (``sample_count=0``, no counters, no boundary, ``start_ts=None``) carrying
    only that hazard — never the silent ``continue`` this replaced.
    """
    by_file: dict[str, list[Event]] = {}
    for event in perfmon_events:
        by_file.setdefault(event.source_file, []).append(event)

    groups: list[TrendGroup] = []
    for source_file, samples in by_file.items():
        placeable = sorted(
            (s for s in samples if s.ts is not None),
            key=lambda s: (s.ts, s.event_id),  # pyright: ignore[reportReturnType] — ts filtered non-None above
        )
        unplaceable_hazard = _hazard_unplaceable_samples(
            [s for s in samples if s.ts is None]
        )
        if not placeable:
            # Case B (WR-03): every sample lost its timestamp, so there is no
            # first or last sample to bound a range with — placeable[0] would
            # raise IndexError, and this branch must NOT index it (the guard is
            # load-bearing). Instead of the old silent `continue`, emit a
            # boundless disclosure group so the file still appears in the report,
            # carrying only the unplaceable-samples hazard (never None here: an
            # empty `placeable` with a non-empty file means samples are all
            # untimestamped).
            groups.append(
                TrendGroup(
                    scope="file",
                    key=source_file,
                    label=NO_PLACEABLE_LABEL,
                    start_ts=None,
                    end_ts=None,
                    boundary_event_ids=(),
                    sample_count=0,
                    counters=(),
                    hazards=()
                    if unplaceable_hazard is None
                    else (unplaceable_hazard,),
                )
            )
            continue
        first, last = placeable[0], placeable[-1]
        assert first.ts is not None and last.ts is not None  # noqa: S101 — filtered
        # Counter-set drift is a property of the FILE, so it is meaningful with
        # no episode at all. The always-zero denial hazard is deliberately not
        # run here: with no detected denial there is nothing for a zero counter
        # to contradict (D-14).
        drift = _hazard_counter_set_drift(placeable)
        groups.append(
            TrendGroup(
                scope="file",
                key=source_file,
                label=FULL_RANGE_LABEL,
                start_ts=first.ts.isoformat(),
                end_ts=last.ts.isoformat(),
                boundary_event_ids=(first.event_id, last.event_id),
                sample_count=len(placeable),
                counters=_counter_trends(placeable),
                hazards=() if drift is None else (drift,),
            )
        )
    return tuple(groups)


def analyse_perfmon(analysis: McmAnalysis, events: list[Event]) -> PerfmonAnalysis:
    """Correlate perfmon samples with every MCM episode (PERF-04).

    One ``TrendGroup`` per episode, including episodes whose span could not be
    resolved — those carry a graded hazard and no counters, so nothing disappears
    silently. Pure and deterministic: ``model_dump_json`` is byte-identical on
    re-run.

    With NO episodes there is no window at all, so D-20's ``scope="file"`` path
    is taken instead: the same figures computed over each source file's full
    sample range. The two paths are exclusive — never both — and the file path's
    ``FULL_RANGE_LABEL`` is what stops the report implying a correlation that
    was not performed.
    """
    if not analysis.episodes:
        return PerfmonAnalysis(
            groups=_file_scope_groups([e for e in events if e.source == "dssperfmon"]),
        )

    by_id = {e.event_id: e for e in events}  # mirrors the attribute_window precedent
    all_samples = _placeable_samples(events)  # once, for the non-overlap message
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
                            dimension=HAZARD_SPAN,
                            severity="warn",
                            message=(
                                f"No perfmon trend could be correlated: {span.reason}."
                            ),
                            event_ids=attempted,
                        ),
                    ),
                )
            )
            continue

        samples = _in_span(events, span.start, span.end)
        assert span.start.ts is not None and span.end.ts is not None  # noqa: S101

        # Fixed code order, so two runs produce identical hazard tuples (D-21).
        hazards: list[PerfmonHazard] = []
        if not samples:
            # D-06: no trend table alongside it — zero-in-span is the loud flag,
            # not an absence of data.
            hazards.append(_hazard_non_overlap(span.start, span.end, all_samples))
        else:
            # Fixed sequence: always-zero denial, then counter-set drift. Order
            # is set here in code, never by severity sort or set iteration, so
            # two equal-severity hazards cannot swap between runs (D-21).
            for builder in (
                _hazard_denial_always_zero(ea.episode.denial_event_id, samples),
                _hazard_counter_set_drift(samples),
            ):
                if builder is not None:
                    hazards.append(builder)

        groups.append(
            TrendGroup(
                scope="episode",
                key=ea.episode.denial_event_id,
                label=ea.window.label,
                start_ts=span.start.ts.isoformat(),
                end_ts=span.end.ts.isoformat(),
                boundary_event_ids=(span.start.event_id, span.end.event_id),
                sample_count=len(samples),
                counters=_counter_trends(samples),
                hazards=tuple(hazards),
            )
        )
    return PerfmonAnalysis(groups=tuple(groups))
