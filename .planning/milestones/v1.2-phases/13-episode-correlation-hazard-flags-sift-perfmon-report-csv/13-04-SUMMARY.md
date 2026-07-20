---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
plan: 04
subsystem: pipeline
tags: [perfmon, hazards, correlation, determinism, PERF-05]
status: complete
requires:
  - "13-02: PerfmonHazard, TrendGroup, _resolve_span, _in_span, _counter_trends, _numeric"
  - "13-03: _DRIFT_ATTR marker in _RESERVED_ATTRS, _qualify_counter_names key format"
provides:
  - "HAZARD_NON_OVERLAP / HAZARD_DENIAL_ALWAYS_ZERO / HAZARD_COUNTER_SET_DRIFT dimension constants"
  - "TrendGroup.hazards populated with the three PERF-05 hazards"
  - "_cited: the order-preserving, capped citation builder"
affects:
  - "13-05: the renderer's hazard table reads TrendGroup.hazards and the dimension constants"
  - "13-06: the CLI surfaces hazards and closes PERF-05"
tech-stack:
  added: []
  patterns:
    - "Hazard builders return PerfmonHazard | None; the caller appends in a fixed code sequence"
    - "Evidence markers are imported from the producing module, never redeclared as string literals"
key-files:
  created: []
  modified:
    - src/sift/pipeline/perfmon.py
    - tests/test_perfmon.py
decisions:
  - "_find_counter_key returns a tuple of every matching key, not the single key the plan sketched — a single-key lookup cannot satisfy the plan's own 'EVERY matching key must read zero' requirement (T-13-EVADE)"
  - "One _CITE_CAP constant caps citations on both the drift and always-zero hazards, not only drift — the always-zero hazard cites one id per in-span sample and has the same unbounded-growth shape"
  - "test_hazards_deterministic_order asserts _cited's order preservation directly; comparing two in-process runs provably cannot detect set iteration because hash order is fixed for a process lifetime"
metrics:
  duration: ~35 min
  tasks: 3
  commits: 6
  tests_added: 9
  completed: 2026-07-20
---

# Phase 13 Plan 04: PERF-05 Hazard Flags Summary

The three PERF-05 hazards now populate `TrendGroup.hazards`: a `critical` time
non-overlap flag naming both ranges, a `warn` always-zero `Total MCM Denial` flag
that fires only against a detected denial, and a `warn` counter-set-drift flag
read from the adapter's ingest-time marker.

## What was built

| Symbol | Kind | Purpose |
|--------|------|---------|
| `HAZARD_SPAN`, `HAZARD_NON_OVERLAP`, `HAZARD_DENIAL_ALWAYS_ZERO`, `HAZARD_COUNTER_SET_DRIFT` | constants | dimension names the renderer keys off |
| `MCM_DENIAL_COUNTER` | constant | `"Total MCM Denial"` — reported flag only |
| `_CITE_CAP` | constant | citation ceiling per hazard (10) |
| `_placeable_samples` | function | case-wide timestamped perfmon samples, explicitly sorted |
| `_cited` | function | dedupe + cap + true total, `dict.fromkeys` never `set` |
| `_hazard_non_overlap` | function | `critical`; names span range and CSV coverage side by side |
| `_find_counter_key` | function | resolves the bare short name AND every qualified key |
| `_hazard_denial_always_zero` | function | `warn`; numeric zero test, cites the denial |
| `_hazard_counter_set_drift` | function | `warn`; reads `_DRIFT_ATTR` only |

`analyse_perfmon` emits them in a fixed code sequence: non-overlap (when the span
is empty), otherwise always-zero then drift. Severities are categorical literals —
`mcm._grade` is called nowhere in the module (D-13).

## Decisions

**`_find_counter_key` returns a tuple, not a single key.** The plan's `<action>`
asked for "the matching key or `None`" but the same paragraph required the hazard
to fire "only if EVERY matching key reads zero". Those are incompatible: a
single-key return cannot check every match, and a CSV carrying the counter under
two instances would let a genuinely non-zero instance be masked by a zero one
(T-13-EVADE). The tuple shape satisfies the stated security requirement; the
sketched signature would not.

**Both hazards cap citations, not just drift.** The plan applied the WR-02 cap
reasoning to drift alone, but the always-zero hazard cites one event id per
in-span sample — the same unbounded shape on a 13,596-row file. One `_CITE_CAP`
covers both, with the true total stated in each message.

**The determinism test was rewritten, not merely added.** As specified,
`test_hazards_deterministic_order` compares two `analyse_perfmon` runs in one
process. That cannot detect `set` iteration: `PYTHONHASHSEED` is fixed for a
process lifetime, so both runs agree on the same wrong order. The plan's own
fail-fast clause caught this — the injected `set` counterfactual passed under six
different hash seeds. The test now asserts `_cited`'s order-preservation contract
directly, which fails under `set` deterministically on every seed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `test_single_sample_no_zero_division` asserted `hazards == ()`**
- **Found during:** Task 2
- **Issue:** The Hartford cut reads `Total MCM Denial == 0` on all 20 samples, so
  the new always-zero hazard legitimately fires on that test's one-sample span.
  The blanket empty-tuple assertion was written before the hazard existed.
- **Fix:** Narrowed to assert no hazard of any dimension OTHER than
  `HAZARD_DENIAL_ALWAYS_ZERO`, preserving the test's actual intent (a narrow
  window is not a correlation failure) without weakening it to a tautology.
- **Files modified:** `tests/test_perfmon.py`
- **Commit:** 94410ac

**2. [Rule 2 - Missing critical functionality] Vacuous determinism test**
- **Found during:** Task 3
- **Issue:** The specified test could not fail under the exact defect it exists to
  prevent (see Decisions above).
- **Fix:** Added a direct `_cited` order assertion; verified the `set`
  counterfactual now fails under seeds 1, 2 and 3, then restored the file.
- **Files modified:** `tests/test_perfmon.py`
- **Commit:** 0cc1f31

### Also added beyond the plan

`test_find_counter_key_survives_qualification` — the plan required the
`_find_counter_key` qualification assertion but named no test; it is its own test
rather than folded into another, so the `-k "mcm_denial or no_episodes_no_zero"`
filter still collects exactly 3 as the acceptance criteria specify.

## Fail-fast verification

Every task's counterfactual was run explicitly, because each RED run failed on
`ImportError` rather than on logic — a weak signal.

| Task | Counterfactual injected | Result |
|------|------------------------|--------|
| 1 | non-overlap hazard suppressed on the empty-sample branch | both tests failed |
| 2 | `_numeric` swapped for `value.startswith("0")` | numeric test failed |
| 3 | `_cited` swapped for `tuple(set(...))` | passed 6/6 seeds → test strengthened → then failed 3/3 |

Each file was restored from a byte-identical backup before committing.

## Threat mitigations verified

| Threat | Verified by |
|--------|-------------|
| T-13-FALSEJOIN | `test_non_overlap_hazard` — zero in-span samples yields a critical hazard and `counters == ()`, never figures from nearby samples |
| T-13-EVADE | `test_find_counter_key_survives_qualification` — every qualified key resolves; all must read zero to fire |
| T-13-DRIFTTRUST | `test_drift_hazard_reads_marker_not_row_widths` — ragged rows with the marker stripped raise nothing |
| T-13-HAZDOS | `_CITE_CAP` on both citing hazards, true total in the message |
| T-13-HAZTEXT | transferred to the renderer (13-05) and CLI (13-06) as planned; the pipeline stays print-free |

## Requirements

PERF-05 left **In Progress** — this plan delivers the hazard computation, but the
user-visible capability (hazards rendered in a report, surfaced by `sift perfmon`)
lands in 13-05 and 13-06. `REQUIREMENTS.md` untouched.

## Verification

- `uv run pytest tests/test_perfmon.py -x -q -k non_overlap` — 2 passed
- `uv run pytest tests/test_perfmon.py -x -q -k "mcm_denial or no_episodes_no_zero"` — 3 passed
- `uv run pytest tests/test_perfmon.py -x -q -k "drift or hazards_deterministic"` — 4 passed
- `uv run ruff check` — clean
- `uv run pyright` — 0 errors, 0 warnings
- `uv run pytest` — 601 passed, 8 deselected
- `uv run pytest tests/_perfmon_fixtures.py` — 3 passed (fixture guards still honest)
- `grep -n 'Total MCM Denial' src/sift/pipeline/perfmon.py` — constant, docstring and
  hazard code only; no occurrence in `_resolve_span`, `_in_span` or `_counter_trends` (D-16)
- No call to `mcm._grade` anywhere in the module (D-13)

## Known Stubs

None.

## Self-Check: PASSED

- `src/sift/pipeline/perfmon.py` — FOUND
- `tests/test_perfmon.py` — FOUND
- Commits 030bbb1, 5ccd7ef, 94410ac, aba9842, f116b95, 0cc1f31 — all FOUND in `git log`
