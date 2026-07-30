---
phase: 16-saturation-contention-signature-collapse
plan: 04
subsystem: analysis
tags: [pydantic, eustack, saturation, verification-gate, adr]

# Dependency graph
requires:
  - phase: 16-01
    provides: "EustackThresholdsConfig, SaturationFlag, PoolOccupancy, analyse_saturation() tracer"
  - phase: 16-02
    provides: "LockSite, enclosing_application_frame(), lock_convergence_count flag"
  - phase: 16-03
    provides: "DependencyWait, no_resolvable_frame_pct flag, whole-model determinism"
provides:
  - "D-09 verification gate proven against the reference capture's MEASURED composition, using the SHIPPED EustackThresholdsConfig() defaults"
  - "Success Criterion 5 (value beside threshold) proven across all three flag families independently of analyse_saturation()'s own grading"
  - "docs/decisions/0016-eustack-saturation-analysis.md — the phase's eight settled decisions plus known limitations"
affects: [17-eustack-report-cli, 18-eustack-facts-into-analyze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "D-09 gate constructed directly against EustackAnalysis (analyse_saturation()'s public frozen input contract) rather than synthesising thousands of raw thread blocks — the input model IS the right unit-test level"
    - "Independent re-derivation as a test discipline: severity re-verified via a second mcm._grade() call in the test itself, not read back off the flag under test"

key-files:
  created:
    - docs/decisions/0016-eustack-saturation-analysis.md
  modified:
    - tests/test_eustack_rules.py

key-decisions:
  - "S-8: D-09's gate split across two tests — the committed derivative fixture (signature-faithful, thread-weight-unfaithful, 38.1% cap-policy-inflated unclassified share) covers no_resolvable_frame_pct/lock_convergence_count only; the real gate is a directly-constructed EustackAnalysis at the reference capture's measured 3,902-thread/52-unclassified composition, asserting every flag grades info against the SHIPPED defaults"
  - "Raising unclassified_thread_pct.warn above 38.1% to make the fixture pass was considered and explicitly rejected, in both the test docstring and ADR 0016 — a threshold calibrated against a fixture's cap policy rather than a server"
  - "ADR 0016 records S-1 through S-8 (module placement, _grade reuse, the shared SaturationFlag record, calibration honesty, the thread-weighted denominator, info-severity emission, the emitted-output ownership-blind guard, the D-09 split) plus two Known Limitations (the four-entry lock-site denylist, the deferred per-pool occupancy flag)"

requirements-completed: [EUS-03, EUS-04, EUS-05, EUS-06]

coverage:
  - id: D1
    description: "The reference capture's measured composition (3,902 threads, 52 unclassified, zero no-resolvable-frame, zero blocked-on-lock) raises zero flags above info against the shipped EustackThresholdsConfig() defaults — D-09's gate, Roadmap Success Criterion 5"
    requirement: "EUS-03, EUS-04, EUS-05, EUS-06"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_measured_reference_composition_raises_zero_flags"
        status: pass
    human_judgment: false
  - id: D2
    description: "The committed derivative fixture's no_resolvable_frame_pct and lock_convergence_count families read info/absent; its cap-policy-inflated unclassified_thread_pct (38.1%) is documented and excluded from this half of the gate, with the rejected-threshold-relaxation alternative recorded in the test itself"
    requirement: "EUS-03"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_reference_derivative_zero_flags"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every graded flag's value travels beside its own warn/critical cut-points with the correct unit, and severity matches an independently recomputed mcm._grade() call, across all three flag families in one input"
    requirement: "EUS-03, EUS-04, EUS-05"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_every_flag_family_prints_value_beside_threshold"
        status: pass
    human_judgment: false
  - id: D4
    description: "ADR 0016 records the phase's eight settled decisions and two known limitations in docs/decisions/, where a future maintainer will look for them"
    requirement: "EUS-03, EUS-04, EUS-05, EUS-06"
    verification:
      - kind: manual
        ref: "docs/decisions/0016-eustack-saturation-analysis.md"
        status: pass
    human_judgment: false

duration: ~15min
completed: 2026-07-25
status: complete
---

# Phase 16 Plan 04: D-09 Zero-Flags Gate, Success Criterion 5 Coverage & ADR 0016 Summary

**The real D-09 verification gate — the reference capture's measured composition proves the shipped defaults raise zero flags — split honestly across two tests around the derivative fixture's 28-fold cap-policy-inflated unclassified share, plus ADR 0016 recording all eight of Phase 16's settled decisions.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-25 (immediately after 16-03)
- **Completed:** 2026-07-25T19:42Z
- **Tasks:** 2
- **Files modified:** 2 (`tests/test_eustack_rules.py`, new `docs/decisions/0016-eustack-saturation-analysis.md`)

## Accomplishments

- `test_measured_reference_composition_raises_zero_flags` — the real D-09 gate: constructs an `EustackAnalysis` directly at the reference capture's MEASURED composition (3,902 threads, 52 unclassified with `reason="matched-no-rule"`, zero no-resolvable-frame threads, zero `blocked-on-lock` signatures, ~3,400 of 3,850 classified threads in the headline idle job-queue pool) and asserts every flag grades `info` against `EustackThresholdsConfig()` constructed with NO arguments — the shipped defaults, not a test-local override. Figures cite ADR 0015 and 16-CONTEXT.md, measured upstream of the code under test.
- `test_reference_derivative_zero_flags` — runs the committed derivative fixture and asserts `no_resolvable_frame_pct` reads `info` and `lock_convergence_count` has no flag at all (both genuinely faithful on this fixture); asserts `unclassified_thread_pct`'s value is exactly 38.1 and documents in its own docstring, with the full arithmetic (40/105 vs 52/3,902, a 28-fold inflation from the fixture's 1-thread-per-signature cap policy), why this flag is deliberately excluded from this half of the gate — and that raising the shipped default to accommodate the fixture was considered and rejected.
- `test_every_flag_family_prints_value_beside_threshold` — one input (idle-parked, no-resolvable-frame, matched-no-rule and lock-convergence threads together) exercising all three `dimension` values at once; for every emitted flag, asserts `value` is a `float`, `warn`/`critical` equal the corresponding `EustackThresholdsConfig` pair, `unit` matches (`"percent"` for the two ratios, `"threads"` for the count), and `severity` equals an independently recomputed `mcm._grade(value, warn, critical)` call — a flag whose own severity disagrees with its own printed figures fails.
- `docs/decisions/0016-eustack-saturation-analysis.md` — records S-1 through S-8 (module placement inside `eustack.py` and why that keeps the ownership-blind source guard single-edit-site; `mcm._grade` reuse; the one shared `SaturationFlag` record and why `DiagnosticFlag`'s locked ratio contract ruled it out for the count flag; default cut-points with their honest calibration status — two ratios rest on one real capture, the count pair has zero calibration data; the thread-weighted denominator choice with the 1.33%-vs-43.01% divergence that makes it load-bearing; info-severity flag emission so "zero flags" means "zero above info"; the emitted-output extension of the ownership-blind guard; and the D-09 two-test split) plus a Known Limitations section (the four-entry lock-site denylist's residual imprecision, the deferred EUSV2-03 per-pool occupancy flag).
- EUS-03, EUS-04, EUS-05 and EUS-06 were already ticked `[x]` and marked `Complete` in `.planning/REQUIREMENTS.md`'s Traceability table by the per-plan `state.record-metric`/requirements-mark-complete step in 16-01, 16-02 and 16-03 — verified present (`grep -c '^- \[x\] \*\*EUS-0[3456]\*\*'` returns 4) rather than re-edited.

## Task Commits

Each task was committed atomically:

1. **Task 1: The D-09 zero-flags gate and Success Criterion 5 coverage** - `8dede60` (test)
2. **Task 2: ADR 0016 and requirement closure** - `052f833` (docs)

## Files Created/Modified

- `tests/test_eustack_rules.py` — 3 new tests: `test_reference_derivative_zero_flags`, `test_measured_reference_composition_raises_zero_flags`, `test_every_flag_family_prints_value_beside_threshold`; imports `SignatureGroup` and `mcm._grade` (the latter for independent-recompute assertions only)
- `docs/decisions/0016-eustack-saturation-analysis.md` — new ADR recording S-1 through S-8 and Known Limitations

## Decisions Made

- **S-8 (this plan's own, confirmed as specified):** the D-09 gate cannot run at its true absolute value on the committed derivative fixture, because the fixture's 1-thread-per-signature cap policy inflates the unclassified thread share 28-fold (38.10% vs the real capture's 1.33%). Split the gate across two tests rather than loosening the shipped default or attempting to reconstruct a thread-weight-faithful fixture from unrecoverable data (only 3 of 93 raw per-signature thread counts are recorded anywhere in the repo).
- **`EustackAnalysis` constructed directly, not synthesised from raw thread text:** `EustackAnalysis` is `analyse_saturation()`'s public, frozen input contract (D-10) — building it at the real capture's measured shape exercises the unit under test at the correct level without a multi-thousand-line synthetic fixture needing its own provenance labelling.
- **REQUIREMENTS.md left untouched:** confirmed EUS-03..EUS-06 were already ticked and marked Complete by the prior three plans' own state-update steps; re-editing an already-correct file would have been unnecessary churn with collision risk against 16-01/02/03's commits.

## Deviations from Plan

None — plan executed exactly as written. One ruff import-sort auto-fix (`ruff check --fix`) on the new imports in `tests/test_eustack_rules.py`, folded into the Task 1 commit before it landed; no behavioural change.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 16 is complete: EUS-03, EUS-04, EUS-05 and EUS-06 all closed at the library level (`SaturationAnalysis`/`analyse_saturation()` in `src/sift/pipeline/eustack.py`), no CLI command, no rendering and no LLM call added (D-12).
- `sift eustack` rendering (Phase 17) and eu-stack fact injection into `sift analyze` (Phase 18) both consume `EustackAnalysis` and `SaturationAnalysis` directly — nothing in this plan changes either model's shape.
- Full suite green: `ruff check` (0 issues), `pyright` (0 errors), `pytest` (742 passed, up from 739 at 16-03 close — 3 new tests, all green). Sift never emits the forbidden ownership-attribution term anywhere in `src/` or in anything `analyse_saturation()` emits (mechanically guarded). No blockers for Phase 17.
- **Manual, out-of-repo verification remaining (16-VALIDATION.md § Manual-Only Verifications):** run the analysis against the real capture at `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` and confirm the five reference figures (~3,400 parked pool workers idle, 79 warehouse waits, 78 HTTP waits, 3,902 threads collapsing to 93 signatures, zero raised flags) — CI asserts the shape, only the real capture can assert the absolute numbers.

## Self-Check: PASSED

- FOUND: 8dede60, 052f833 (both task commits present in `git log --oneline --all`)
- FOUND: `docs/decisions/0016-eustack-saturation-analysis.md`
- FOUND: `tests/test_eustack_rules.py` (contains `test_reference_derivative_zero_flags`, `test_measured_reference_composition_raises_zero_flags`, `test_every_flag_family_prints_value_beside_threshold`)

---
*Phase: 16-saturation-contention-signature-collapse*
*Completed: 2026-07-25*
