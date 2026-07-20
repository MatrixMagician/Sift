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

from pydantic import BaseModel, ConfigDict

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
