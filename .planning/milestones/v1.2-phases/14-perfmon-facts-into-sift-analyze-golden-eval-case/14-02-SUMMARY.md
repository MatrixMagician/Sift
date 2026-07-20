---
phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case
plan: 02
subsystem: pipeline
tags: [perfmon, correlator, hazard, disclosure, determinism, wr-03, d-08]

# Dependency graph
requires:
  - phase: 13-episode-correlation-hazard-flags
    provides: "_hazard_unplaceable_samples disclosure channel, TrendGroup zero-sample hazard-only shape, _file_scope_groups NO_PLACEABLE path"
provides:
  - "analyse_perfmon discloses untimestamped perfmon samples on the episodes-present branch via a synthetic case-wide TrendGroup (D-08)"
  - "UNATTRIBUTED_LABEL + _unattributed_group helper reusing the shipped disclosure hazard verbatim"
affects: [perfmon, correlator, 14-03-cap, sift-perfmon-report]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Add-alongside (Option B): a synthetic scope=file, sample_count=0 hazard-only TrendGroup for a case-wide disclosure that is genuinely not span-attributable, reusing the shipped zero-sample group shape so renderers need no change"

key-files:
  created: []
  modified:
    - "src/sift/pipeline/perfmon.py"
    - "tests/test_perfmon.py"

key-decisions:
  - "Option B (add-alongside) over promoting PerfmonAnalysis to a case-level hazard field: lowest blast radius, one-hazard-per-span invariant preserved, sift perfmon renderers untouched"
  - "Disclosure appended in a fixed code position after the episode loop (never severity-sorted) to keep model_dump_json byte-identical (D-21)"
  - "_unattributed_group filters source == dssperfmon before the ts is None test so a ts=None dsserrors boundary event is never miscited as an unplaceable perfmon sample"

patterns-established:
  - "Reuse an existing disclosure hazard builder verbatim across both branches rather than a second implementation, so wording and citation shape (severity, cap, sort) cannot drift"

requirements-completed: [PERF-07]

coverage:
  - id: D1
    description: "Episodes present + >=1 untimestamped perfmon sample -> one info HAZARD_UNPLACEABLE_SAMPLES disclosure group (not a silent drop), citations event_id-sorted and capped at _CITE_CAP with the true total in the message"
    requirement: "PERF-07"
    verification:
      - kind: unit
        ref: "tests/test_perfmon.py#test_unattributed_samples_disclosed_when_episodes_present"
        status: pass
    human_judgment: false
  - id: D2
    description: "Disclosure appended in a fixed position -> two runs byte-identical (D-21); all-timestamped Hartford reference emits no unattributed group so goldens are unaffected"
    requirement: "PERF-07"
    verification:
      - kind: unit
        ref: "tests/test_perfmon.py#test_unattributed_disclosure_is_deterministic_and_hartford_clean"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-20
status: complete
---

# Phase 14 Plan 02: Episodes-Present Unattributed-Sample Disclosure Summary

**Folds the deferred WR-03 fix into the correlator: on the episodes-present branch an untimestamped perfmon sample (ts is None) is now disclosed via a synthetic info-severity TrendGroup instead of vanishing silently, reusing the shipped `_hazard_unplaceable_samples` channel verbatim.**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-07-20
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Closed the "nothing disappears silently" violation on the episodes-present branch — the mirror of the WR-03 fix that Phase 13 landed only on the no-episodes branch (D-08).
- Added `UNATTRIBUTED_LABEL` and `_unattributed_group`, appended in a fixed position after the episode loop so `model_dump_json` stays byte-identical across runs (D-21 preserved).
- Reused `_hazard_unplaceable_samples` verbatim (severity=info, `_CITE_CAP` cap, event_id sort) so the disclosure's text and citation shape match the no-episodes path exactly — no second implementation.
- Proved the all-timestamped Hartford reference is unaffected (no unattributed group; existing goldens did not move).

## Task Commits

1. **Task 1: Emit the case-level unattributed-samples disclosure group** - `f92b82b` (feat)
2. **Task 2: Test the disclosure + prove the Hartford reference is unaffected** - `377bfa4` (test)

_Task 1 (source) landed before Task 2 (test) per the plan's task order; RED discipline honoured by counterfactually breaking the append to confirm both tests fail, then restoring to HEAD byte-identically before committing._

## Files Created/Modified
- `src/sift/pipeline/perfmon.py` - `UNATTRIBUTED_LABEL` + `_UNATTRIBUTED_KEY` constants, `_unattributed_group` helper, and a fixed-position append in `analyse_perfmon`'s episodes-present branch.
- `tests/test_perfmon.py` - `_untimed_perfmon` helper and two tests: the disclosure citation-shape test and the determinism + Hartford-clean regression guard.

## Decisions Made
- **Option B (add-alongside)** as recorded in the plan's `<assumption_delta_decision>`: emit a synthetic `scope="file"`, `sample_count=0`, hazard-only `TrendGroup` rather than promoting `PerfmonAnalysis` to a case-level hazard field. Lowest blast radius; the zero-sample hazard-only shape already ships, so `sift perfmon` renderers need no change and the one-hazard-per-span docstring invariant is not rewritten.
- **Source filter inside the helper**: `_unattributed_group` filters `source == "dssperfmon"` before the `ts is None` test. The caller passes the whole event list (which includes `ts=None` dsserrors boundary events, D-04), so without the filter a boundary event would be miscited as an unplaceable perfmon sample. The disclosure test asserts the true perfmon total in the message to lock this in.

## Deviations from Plan

None - plan executed exactly as written. (Ruff auto-reordered the new test import and flagged one over-length docstring line; both were mechanical formatting fixes within Task 2, not behavioural deviations.)

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The disclosure lives on a `TrendGroup` with `severity="info"`, which sorts last and is dropped first under 14-03's D-03 hazard cap — the intended interaction. No blockers.
- Accepted debt (from the plan): `scope="file"` is semantically loose for a case-wide disclosure. Only forced to a dedicated `scope="unattributed"` Literal if a downstream consumer must structurally distinguish it from a real per-file trend. Not needed this phase.

---
*Phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case*
*Completed: 2026-07-20*

## Self-Check: PASSED

- SUMMARY.md present; commits f92b82b + 377bfa4 in history; `_unattributed_group` + `UNATTRIBUTED_LABEL` present in perfmon.py.
