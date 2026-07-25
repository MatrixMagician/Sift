---
phase: 16-saturation-contention-signature-collapse
plan: 01
subsystem: analysis
tags: [pydantic, eustack, config, saturation, mcm]

# Dependency graph
requires:
  - phase: 15-thread-role-taxonomy-rules-file
    provides: EustackAnalysis / SignatureGroup with required subsystem field, analyse_eustack()
provides:
  - "EustackThresholdsConfig under [eustack.thresholds] (three ThresholdPair fields)"
  - "SaturationFlag / PoolOccupancy / SaturationAnalysis frozen models in eustack.py"
  - "analyse_saturation(): per-pool occupancy grouping (EUS-03), first composition flag"
affects: [16-02-eustack-lock-convergence, 16-03-eustack-dependency-split, 17-eustack-report-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cross-module 'shared, not copied' reuse: mcm._grade imported into eustack.py with pyright: ignore[reportPrivateUsage], mirroring the existing _condense_symbol import"
    - "Plain dict accumulation (never Counter.most_common(), never set iteration) with an explicit named sort key for every new grouping"
    - "Sibling flag record (SaturationFlag) generalising perfmon.PerfmonHazard's field shape rather than forcing a raw count into mcm.DiagnosticFlag.value_pct"

key-files:
  created: []
  modified:
    - src/sift/config.py
    - src/sift/pipeline/eustack.py
    - tests/test_eustack_rules.py
    - tests/test_config.py

key-decisions:
  - "S-3: one SaturationFlag record shared by all three Phase 16 flag families (not DiagnosticFlag reuse) — value/warn/critical travel together so a renderer never re-reads config"
  - "S-2: mcm._grade imported as-is rather than promoted to a shared module — mcm.py's shipped tests stay untouched, no import cycle (mcm.py imports nothing from sift.pipeline)"
  - "Pool sort key (-total_threads, subsystem is None, subsystem or \"\"): the `subsystem is None` term both places the unclassified row last on ties and avoids a None/str TypeError in Python 3"

patterns-established:
  - "SaturationAnalysis additive-only: only pools/flags exist now; 16-02/16-03 add lock_sites/dependencies with defaults so no earlier caller ever breaks"

requirements-completed: [EUS-03]

coverage:
  - id: D1
    description: "Per-pool occupancy computed for every subsystem in EustackAnalysis.signatures (compute/lock/cube-generation on identical terms to job-queue, no allowlist), unclassified isolated as its own None row never folded into another pool's denominator"
    requirement: "EUS-03"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_pool_occupancy_splits_busy_and_parked"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_unclassified_not_pooled_and_not_in_any_denominator"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_pool_occupancy_extremes_and_empty_analysis"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_deterministic_pool_ordering"
        status: pass
    human_judgment: false
  - id: D2
    description: "The healthy reference-capture derivative's job-queue pool reads occupancy 0.0 with idle_threads == total_threads (Success Criterion 1) — parked workers read idle, not saturated"
    requirement: "EUS-03"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_reference_derivative_occupancy_reads_pools_as_idle"
        status: pass
    human_judgment: false
  - id: D3
    description: "One SaturationFlag emitted for unclassified_thread_pct carrying value, warn and critical on the same record (Success Criterion 5); no per-pool occupancy flag exists anywhere (D-07)"
    requirement: "EUS-03"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_flag_value_and_threshold_travel_together"
        status: pass
    human_judgment: false
  - id: D4
    description: "[eustack.thresholds] config: documented S-4 defaults, per-key merge on partial override, typo'd key raises ValidationError at load (V5/T-16-05)"
    requirement: "EUS-03"
    verification:
      - kind: unit
        ref: "tests/test_config.py#test_eustack_thresholds_default_to_documented_cut_points"
        status: pass
      - kind: unit
        ref: "tests/test_config.py#test_unknown_key_under_eustack_thresholds_is_a_loud_error"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-25
status: complete
---

# Phase 16 Plan 01: Pool Occupancy Tracer Summary

**Per-pool occupancy analysis (EUS-03) end to end: `[eustack.thresholds]` config, a grouping over `EustackAnalysis.signatures`, grading via the shipped `mcm._grade`, and a new frozen `SaturationAnalysis` model — proven on the real committed fixture in one vertical slice.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-25T19:02:36Z
- **Completed:** 2026-07-25T19:09:04Z
- **Tasks:** 3
- **Files modified:** 3 (`config.py`, `eustack.py`, plus tests split across two files: `test_eustack_rules.py`, `test_config.py`)

## Accomplishments

- `EustackThresholdsConfig` under `[eustack.thresholds]` with three `ThresholdPair` fields (`unclassified_thread_pct`, `no_resolvable_frame_pct`, `lock_convergence_count`), defaults calibrated against the real reference capture (1.33% unclassified, zero lock matches) and documented as such
- `SaturationFlag`, `PoolOccupancy`, `SaturationAnalysis` and `analyse_saturation()` appended to `src/sift/pipeline/eustack.py`, consuming `EustackAnalysis` read-only (D-10) with `EustackAnalysis` itself unchanged
- Per-pool occupancy groups `EustackAnalysis.signatures` on `subsystem` (D-01, no allowlist of "real" pools) with the `unclassified` population isolated in a single `subsystem is None` row that appears in no other pool's denominator (D-02)
- One `unclassified_thread_pct` `SaturationFlag` emitted, graded via the imported `mcm._grade`, carrying `value`/`warn`/`critical` together (Success Criterion 5); no per-pool occupancy flag exists (D-07/EUSV2-03 deferred)
- Reference-derivative fixture's `job-queue` pool reads `occupancy == 0.0` with `idle_threads == total_threads` — the healthy capture's parked workers read idle, not saturated (Success Criterion 1)
- Deterministic, explicit-total-order pool sort proven on a real tie, plus byte-identical `model_dump_json()` reruns
- `[eustack.thresholds]` config strictness: documented defaults pinned, a partial TOML override merges per key, a typo'd key raises `ValidationError` at load (V5, T-16-05)

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end pool occupancy tracer** - `b58c21e` (feat)
2. **Task 2: D-01/D-02 isolation and zero-valued edge cases** - `725bc11` (test)
3. **Task 3: `[eustack.thresholds]` config strictness** - `98d1147` (test)

## Files Created/Modified

- `src/sift/config.py` - `EustackThresholdsConfig` class + `EustackConfig.thresholds` field; widened `ThresholdPair`'s docstring to cover both MCM and eu-stack diagnostics
- `src/sift/pipeline/eustack.py` - `FlagSeverity`/`FlagUnit` type aliases, `SaturationFlag`, `PoolOccupancy`, `SaturationAnalysis`, `analyse_saturation()`; imports `mcm._grade` "shared, not copied"
- `tests/test_eustack_rules.py` - 6 new tests: pool occupancy split, reference-derivative occupancy, flag value/threshold pairing, unclassified isolation, occupancy extremes + empty analyses, deterministic ordering
- `tests/test_config.py` - 2 new tests: documented threshold defaults + per-key merge, typo'd key loud error

## Decisions Made

- **S-3 (confirmed at plan time, implemented as specified):** minted one `SaturationFlag` record for all three Phase 16 flag families rather than reusing `mcm.DiagnosticFlag` (whose `value_pct` is locked as a ratio) or splitting into two record types. `event_ids` deliberately omitted — resolving an aggregate figure back to a citable event set is Phase 18's open design question.
- **S-2 (confirmed):** `mcm._grade` imported as-is with a `pyright: ignore[reportPrivateUsage]` marker rather than promoted to a shared module. Verified `mcm.py` imports nothing from `sift.pipeline`, so no import cycle; `tests/test_mcm.py` stays green (29 passed).
- **Pyright caught a real typing gap not anticipated at plan time:** `mcm._grade()` returns bare `str`, but `SaturationFlag.severity` is typed `FlagSeverity` (a `Literal`), per S-3's WR-04 reasoning. Fixed with an explicit `cast("FlagSeverity", ...)` at the single call site, with a comment explaining `_grade()`'s value set is a strict subset of the three graded levels — no scope change, no widening of the Literal.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `SaturationFlag.severity` typing gap caught by pyright**
- **Found during:** Task 1 (`analyse_saturation()` implementation)
- **Issue:** `_grade()` (imported from `mcm.py`) returns plain `str`; `SaturationFlag.severity` is typed `FlagSeverity = Literal["info", "warn", "critical"]` per the plan's own S-3 design. Assigning the `str` return directly failed `pyright` (`reportArgumentType`).
- **Fix:** Added `from typing import cast` and wrapped the `_grade()` call in `cast("FlagSeverity", ...)` with an inline comment documenting that `_grade()`'s value set is a strict subset of the Literal's three levels.
- **Files modified:** `src/sift/pipeline/eustack.py`
- **Verification:** `uv run pyright` → 0 errors.
- **Committed in:** `b58c21e` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — type-safety gap surfaced by pyright, not a logic error)
**Impact on plan:** Zero scope change; the fix is exactly the cast the S-3 design already implied but the plan prose didn't spell out.

## Issues Encountered

None beyond the pyright cast above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `SaturationAnalysis` and `analyse_saturation()` are in place and additive-only — 16-02 (lock convergence, EUS-04) and 16-03 (dependency split, EUS-05) can each add a field with a default and a new flag check without touching this plan's surface.
- The `unclassified_thread_pct` flag check establishes the fixed-authored-order pattern (`mcm.compute_flags` precedent) that 16-02/16-03 extend with `no_resolvable_frame_pct` and `lock_convergence_count`.
- Full suite green: `ruff check` (0 issues), `pyright` (0 errors), `pytest` (727 passed, up from 719 at Phase 15 close — 8 new tests, all green). No blockers for 16-02.

## Self-Check: PASSED

- FOUND: b58c21e, 725bc11, 98d1147 (all three task commits present in `git log --oneline --all`)
- FOUND: `16-01-SUMMARY.md`
- FOUND: `src/sift/pipeline/eustack.py`

---
*Phase: 16-saturation-contention-signature-collapse*
*Completed: 2026-07-25*
