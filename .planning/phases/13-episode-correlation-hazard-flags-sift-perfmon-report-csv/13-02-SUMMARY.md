---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
plan: 02
subsystem: pipeline
tags: [perfmon, correlator, trends, wave-2, PERF-04]
status: complete
requires:
  - plan 13-01 (tests/_perfmon_fixtures.py, ingest_perfmon_slice, log_boundary_event)
provides:
  - src/sift/pipeline/perfmon.py (PerfmonHazard, CounterTrend, TrendGroup, PerfmonAnalysis)
  - analyse_perfmon(analysis, events) -> PerfmonAnalysis
  - _numeric, _resolve_span, _in_span, _counter_trends, SLOPE_DP
affects:
  - plan 13-04 (correlation hazards attach to TrendGroup.hazards)
  - plan 13-05 (render_perfmon_markdown / _json consume PerfmonAnalysis)
  - plan 13-06 (scope="file" whole-file path, perfmon CLI command)
tech-stack:
  added: []
  patterns:
    - "_Span NamedTuple: resolved-or-reason, never raises — an unresolvable bound is a value the caller grades"
    - "round-at-source (SLOPE_DP=4 for slopes, 3 dp for values), mirroring mcm_report._mb_bytes"
    - "dict.fromkeys over canonically-ordered samples then sorted() emit — no set iteration on any output path"
key-files:
  created:
    - src/sift/pipeline/perfmon.py
  modified:
    - tests/test_perfmon.py
decisions:
  - "_RESERVED_ATTRS is imported from sift.adapters.dssperfmon (with a pyright reportPrivateUsage ignore and rationale) rather than re-declared locally, so the provenance-key exclusion set cannot drift from the adapter that owns it."
  - "ingest_perfmon_slice gained an optional csv_path parameter so the non-finite test drives the real adapter ingest path with a synthetic fixture instead of hand-building Events. Backward compatible; the wave-1 default is unchanged."
  - "The plan's assumed slope arithmetic (20 samples 30 s apart => 570 s) was wrong against the shipped fixture: the cut is two 10-sample blocks five days apart. The hand-computed literal was corrected to 0.6522 over 407881.161 s, with the full derivation in a test comment."
metrics:
  duration: ~35 min
  tasks: 3
  files: 2
  completed: 2026-07-20
---

# Phase 13 Plan 02: Perfmon Correlator Core Summary

The load-bearing computation for PERF-04: a frozen model layer, a finite-only numeric
gate, span resolution keyed to real `event_id`s at both ends, and the three per-counter
trend figures — each carrying the `event_id` of the sample it came from, so every figure
is reproducible by hand from two cited CSV rows.

## What Was Built

**Task 1 — model layer and `_numeric`** (`178b2b6`)

`PerfmonHazard`, `CounterTrend`, `TrendGroup`, `PerfmonAnalysis`, all
`frozen=True, extra="forbid"` with tuples throughout. `_numeric` parses a counter cell
inside a `try` and returns it only when `math.isfinite` holds — closing the gap that
`dssperfmon._bad_cells`' bare `float()` probe leaves open, since `float("nan")` and
`float("inf")` both succeed and would otherwise poison `max()`, slope and at-denial, then
serialise as the invalid-JSON token `NaN` (T-13-NONFINITE). `SLOPE_DP = 4` is the
round-at-source constant.

Each model docstring records why it exists rather than reusing an MCM sibling:
`PerfmonHazard` does not reuse `DiagnosticFlag` (whose `value_pct` is locked as a ratio),
and does not call `mcm._grade` (it grades structural conditions, not ratios against two
cut-points). `TrendGroup`'s `scope` discriminator serves D-19's per-episode and D-20's
per-file shape from one model — stated so a reviewer does not read it as speculative
generality.

**Task 2 — `_resolve_span` and `_in_span`** (`6eede29`)

Both bounds resolve through `by_id = {e.event_id: e for e in events}`, built once at the
top of `analyse_perfmon` (the `attribute_window` precedent; no store query from this
module). `McmEpisode.denial_ts` is never parsed — it appears only in a docstring warning
that the fallback is forbidden. `select_window` is consumed, never called (D-02). The
`start_event_id=None` fallback scans `episode.event_ids` for the first entry that both
resolves AND carries a `ts`, which `attribute_window`'s `event_ids[0]` does not guarantee.
An unresolvable bound yields a `TrendGroup` with a graded hazard, `counters=()` and
`start_ts=None` — the episode still appears (T-13-BOUNDARY). `_in_span` is the closed
interval in the store's canonical order, preserved rather than re-sorted.

**Task 3 — `_counter_trends`** (`6f5bdba`)

Counter names are swept from every in-span sample's `attrs` minus `_RESERVED_ATTRS`
(T-13-ATTRSWEEP), collected with `dict.fromkeys` and emitted sorted by name. Per counter:
at-denial is the last accepted sample's value and id (never interpolated); slope is
`(last - first) / seconds_elapsed` rounded to `SLOPE_DP`, with the zero-duration case
guarded *before* the divide and yielding `None` with no hazard; peak uses `max()`, whose
first-maximal-element behaviour resolves ties to the earliest sample (stated in a comment,
since `sorted(...)[-1]` would silently flip it). Rejected cells increment `excluded_samples`
per counter without dropping the row. A counter with no accepted values is reported with
all figures `None`, not omitted.

## Verification Performed

- `uv run pytest tests/test_perfmon.py -q` — 13 pass (2 wave-1 smoke + 11 new)
- `uv run ruff check` — clean; `uv run pyright` — 0 errors
- `uv run pytest` (full suite) — 583 passed, 8 deselected; no regression
- **Anti-vacuity checks** (house fail-fast convention) — every guard that passed on its
  first run was inverted in place and confirmed to fail the test, then restored:
  - `_numeric`'s `math.isfinite` gate → `test_numeric_rejects_non_finite` fails
  - `PerfmonHazard`'s `extra="forbid"` → `test_hazard_model_frozen_and_strict` fails
  - D-03's timestamped scan → `event_ids[0]` → `test_span_full_leadup_fallback` fails
  - D-04's `ts=None` guard → substitute the start event → `test_span_missing_ts_hazard` fails
  - the `elapsed == 0.0` guard removed → `test_single_sample_no_zero_division` raises
    `ZeroDivisionError`
  - `max()` → `sorted(...)[-1]` → `test_peak_tie_takes_earliest_sample` fails
- `grep -n 'denial_ts\|select_window' src/sift/pipeline/perfmon.py` — two hits, both
  docstring lines; no expression parses `denial_ts` and `select_window` is never imported.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's hand-computed slope literal was wrong**

- **Found during:** Task 3 (a genuine RED — the test failed on first run)
- **Issue:** The plan's `<behavior>` implies 20 samples 30 s apart, so the expected slope
  was derived over 570 s. The shipped fixture is actually two 10-sample blocks five days
  apart: first sample `04/02/2026 19:21:38.236`, last `04/07/2026 12:39:39.397`.
- **Fix:** Recomputed by hand from the fixture's real stamps —
  `elapsed = 432000 - 24118.839 = 407881.161 s`, `266015 / 407881.161 = 0.65218752… →
  0.6522` at 4 dp. The full derivation is in a test comment; the figure is still not
  obtained by calling `_counter_trends`.
- **Files modified:** `tests/test_perfmon.py`
- **Commit:** `6f5bdba`

**2. [Rule 3 - Blocking] `ingest_perfmon_slice` could not drive a synthetic fixture**

- **Found during:** Task 3
- **Issue:** `test_non_finite_excluded` must ingest `write_non_finite_csv(tmp_path)`, but
  the wave-1 helper hardcoded the shipped slice path and `input_root`.
- **Fix:** Added an optional `csv_path` parameter deriving `input_root` from the path's
  parent. Default behaviour is unchanged, so the wave-1 tests and plan 13-06 are unaffected.
- **Files modified:** `tests/test_perfmon.py`
- **Commit:** `6f5bdba`

**3. [Rule 3 - Blocking] pyright strict on the cross-module private import**

- **Found during:** Task 3
- **Issue:** `_RESERVED_ATTRS` lives in `sift.adapters.dssperfmon`; pyright strict raises
  `reportPrivateUsage` on a cross-module private import.
- **Fix:** Applied the existing house convention (a targeted
  `# pyright: ignore[reportPrivateUsage]` with a rationale). Re-declaring the seven keys
  locally would have been lint-clean but introduces a silent drift risk against the adapter
  that owns them — the wrong trade for a security-relevant exclusion set (T-13-ATTRSWEEP).
- **Files modified:** `src/sift/pipeline/perfmon.py`
- **Commit:** `6f5bdba`

A transient `# pyright: ignore[reportUnusedFunction]` was carried on `_numeric` in the
task-1 commit only (pyright's unused-function check is file-scoped for underscore-private
names, so the test-side import does not count). Task 3 wires `_numeric` into
`_counter_trends` in-module and the ignore was removed.

No architectural changes were needed; no package installs occurred.

## Notes for Later Plans

- `PerfmonAnalysis.hazards` is deliberately `()` and `TrendGroup.hazards` is empty except
  on the D-04 unresolvable-span path. Correlation hazards (empty window, non-overlap) are
  plan 13-04's; the comment in `analyse_perfmon` names both follow-on plans so neither
  omission reads as an oversight.
- `scope="file"` is modelled but not yet produced — plan 13-06 adds the whole-file path
  with the criterion-5 CLI test.
- Golden figures are asserted at correlator-unit level via `log_boundary_event`, per
  plan 13-01's non-overlap note. That constraint held throughout and is not negotiable for
  13-06's integration test.

## Requirements

PERF-04 is **not** marked complete. This plan delivers the correlator core, but the
user-visible capability (`sift perfmon` report + CSV) lands in plans 13-05/13-06.

## Threat Flags

None — no new network, auth or filesystem surface. The three `mitigate` dispositions in the
plan's threat register were applied and are covered by tests: T-13-NONFINITE
(`test_non_finite_excluded` asserts every non-`None` figure in the analysis is finite),
T-13-BOUNDARY (`test_span_missing_ts_hazard`), T-13-ATTRSWEEP (provenance keys excluded via
the adapter's own `_RESERVED_ATTRS`). T-13-TYPECOERCE remains `accept`: `float()` inside a
`try` degrades a non-`str` value to `None` without raising.

## Self-Check: PASSED

- `src/sift/pipeline/perfmon.py` — FOUND
- `tests/test_perfmon.py` — FOUND
- `178b2b6`, `6eede29`, `6f5bdba` — all FOUND in git history
