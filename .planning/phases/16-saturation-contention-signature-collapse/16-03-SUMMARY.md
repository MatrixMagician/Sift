---
phase: 16-saturation-contention-signature-collapse
plan: 03
subsystem: analysis
tags: [pydantic, eustack, saturation, dependency-split, determinism]

# Dependency graph
requires:
  - phase: 16-02
    provides: "SaturationAnalysis/analyse_saturation() with pools + lock_sites + first two flags"
provides:
  - "DependencyWait / SaturationAnalysis.dependencies (EUS-05 external-wait split by verbatim subsystem)"
  - "no_resolvable_frame_pct SaturationFlag, second of the three D-07 flags, total-thread denominator"
  - "Mechanical proof that EustackAnalysis.signatures is read directly, never re-derived (EUS-06, D-10)"
  - "Whole-model determinism proven across all four groupings with deliberate ties"
affects: [17-eustack-report-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Plain dict accumulation (never Counter.most_common(), never set iteration) with an explicit named sort key, same discipline as the pool/lock passes from 16-01/16-02"
    - "Fixed authored flag order (mcm.compute_flags precedent) extended with a second insertion point between existing checks, not appended at the end"

key-files:
  created: []
  modified:
    - src/sift/pipeline/eustack.py
    - tests/test_eustack_rules.py

key-decisions:
  - "DependencyWait groups on Rule.subsystem verbatim, not matched pattern text — Rules 16/19 both carry subsystem=\"warehouse\" and must aggregate into one row (D-06); proven directly by a test asserting two DIFFERENT patterns collapse to one row"
  - "no_resolvable_frame_pct divides by analysis.total_threads (S-5/D-07 amended), the SAME denominator as unclassified_thread_pct — proven by a test that recomputes both candidate denominators and asserts they diverge, so the choice is testable rather than incidental"
  - "SaturationAnalysis carries no signature list of its own; EUS-06 is closed by pinning SaturationAnalysis.model_fields' exact set and EustackAnalysis's frozen/extra=forbid/field-set contract mechanically, not by convention"

patterns-established:
  - "Every Phase 16 grouping (pools, lock sites, dependencies) now shares one discipline: dict accumulate -> list -> explicit sort(key=...) with a named tie-break — proven jointly, with deliberate ties in all three plus the fixed flag order, in one whole-model determinism test"

requirements-completed: [EUS-05, EUS-06]

coverage:
  - id: D1
    description: "External waits are split by the verbatim subsystem of blocked-on-external threads, warehouse and HTTP separately visible, never merged into one blocked total (D-06); two rules sharing a subsystem aggregate into one row"
    requirement: "EUS-05"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_dependency_split_by_subsystem"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_reference_derivative_dependency_split_not_merged"
        status: pass
    human_judgment: false
  - id: D2
    description: "The no-resolvable-frame flag divides by ALL threads, the same thread-weighted denominator the unclassified-share flag uses, never by unclassified threads only (D-07 amended, S-5)"
    requirement: "EUS-06"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_no_resolvable_frame_flag_uses_total_thread_denominator"
        status: pass
    human_judgment: false
  - id: D3
    description: "EustackAnalysis.signatures is read directly and never re-derived: SaturationAnalysis carries no signature list of its own, and EustackAnalysis stays frozen, extra=\"forbid\" and unmodified"
    requirement: "EUS-06"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_signature_passthrough_reads_eustack_analysis_directly"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every one of pools, lock sites, dependencies and flags has an explicit total-order sort key with a named tie-break, proven with deliberate ties in one whole-model test; two analyse_saturation() runs over identical input produce byte-identical model_dump_json()"
    requirement: "EUS-05, EUS-06"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_deterministic_ordering_across_every_grouping"
        status: pass
    human_judgment: false

duration: ~15min
completed: 2026-07-25
status: complete
---

# Phase 16 Plan 03: External-Wait Dependency Split & Signature Passthrough Summary

**`DependencyWait` — the external-wait split by verbatim `subsystem` (EUS-05) — plus the `no_resolvable_frame_pct` flag closing D-07's three-flag set, a mechanical EUS-06 passthrough proof, and a whole-model determinism test exercising all four Phase 16 groupings with deliberate ties in one pass.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-25T19:29Z (immediately after 16-02)
- **Completed:** 2026-07-25T19:33Z
- **Tasks:** 3
- **Files modified:** 2 (`src/sift/pipeline/eustack.py`, `tests/test_eustack_rules.py`)

## Accomplishments

- `DependencyWait` (subsystem/thread_count/signature_count) and `SaturationAnalysis.dependencies` (defaulted, additive over 16-01/16-02); the `analyse_saturation()` dependency pass filters to `blocked-on-external` signatures and groups by verbatim `subsystem` — never by matched pattern text — so Rules 16 and 19 (`CDSSQueryEngine::WaitUntilFinished`, `MDb::Wrapper::InterpretStatus`), both `subsystem="warehouse"`, aggregate into one row
- On the committed derivative fixture, the split reads exactly `warehouse` 8, `http` 5, `ipc` 2 threads — three distinct, non-merged rows in the declared `(-thread_count, subsystem)` order — confirmed both by a targeted unit test and by the plan's own one-liner acceptance check
- `no_resolvable_frame_pct`, the second of D-07's three flags, inserted between the unclassified-share and lock-convergence checks per the fixed authored order; divides by `analysis.total_threads` (S-5), the same thread-weighted denominator flag 1 uses — a test recomputes both candidate denominators (total-threads vs unclassified-only) on a population where they diverge by more than 10x and asserts the flag matches the former, not the latter
- EUS-06 closed mechanically: `test_signature_passthrough_reads_eustack_analysis_directly` pins `SaturationAnalysis.model_fields` to its exact five-field set (no duplicated signature list) and pins `EustackAnalysis`'s `frozen=True`/`extra="forbid"`/unchanged nine-field set, then confirms the ranked collapse (93 signatures, sorted thread-count descending, ties ascending on frames) is read straight off `EustackAnalysis.signatures`
- `test_deterministic_ordering_across_every_grouping`: one synthetic input exercising pools, lock sites and dependencies simultaneously, each carrying a deliberate tie (job-queue/cube-generation at 4 threads; two lock sites at 3 threads; warehouse/http at 2 threads), asserting every ordering against its named sort key directly and the declared tie-break direction — plus confirming `flags` stays in fixed authored order (never severity-sorted) and two `analyse_saturation()` calls produce byte-identical `model_dump_json()`

## Task Commits

Each task was committed atomically:

1. **Task 1: `DependencyWait` — the external-wait split by verbatim subsystem (EUS-05)** - `1b61bed` (feat)
2. **Task 2: The `no_resolvable_frame_pct` flag and the EUS-06 passthrough contract** - `0169985` (test)
3. **Task 3: Whole-model determinism across every grouping** - `c778c55` (test)

## Files Created/Modified

- `src/sift/pipeline/eustack.py` — `DependencyWait`, `SaturationAnalysis.dependencies`; the dependency pass and the `no_resolvable_frame_pct` flag check inside `analyse_saturation()`
- `tests/test_eustack_rules.py` — 5 new tests: dependency split by subsystem (incl. shared-subsystem aggregation), derivative-fixture dependency split (warehouse 8/http 5/ipc 2), no-resolvable-frame flag denominator, signature passthrough contract, whole-model deterministic ordering

## Decisions Made

- **D-06 grouping key confirmed as `subsystem`, never matched pattern text** — proven directly rather than assumed: `test_dependency_split_by_subsystem` builds two DIFFERENT patterns both mapped to `warehouse` and asserts they land in one row with `signature_count == 2`.
- **S-5 denominator choice made testable, not incidental** — `test_no_resolvable_frame_flag_uses_total_thread_denominator` deliberately constructs a population where `total_threads` and `threads_by_role["unclassified"]` diverge by more than 10x, so a wrong-denominator regression would fail loudly rather than silently passing on a coincidentally-equal figure.
- **EUS-06 asserted mechanically, not by convention** — the field-set pin (`set(SaturationAnalysis.model_fields)`) means a future field addition duplicating `EustackAnalysis.signatures` fails this test immediately, rather than depending on a reviewer noticing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `zip()` without `strict=` (ruff B905) in the EUS-06 passthrough test**
- **Found during:** Task 2 (`test_signature_passthrough_reads_eustack_analysis_directly`)
- **Issue:** The pairwise-order check `zip(analysis.signatures, analysis.signatures[1:])` triggered ruff's B905 (missing explicit `strict=` parameter).
- **Fix:** Added `strict=False` explicitly — correct here since the two sequences are deliberately one element apart by construction (a pairwise-adjacent comparison), so `strict=True` would raise.
- **Files modified:** `tests/test_eustack_rules.py`
- **Verification:** `uv run ruff check` → 0 issues.
- **Committed in:** `0169985` (Task 2 commit)

**2. [Rule 1 - Bug] Three E501 line-length violations in the new determinism test**
- **Found during:** Task 3 (`test_deterministic_ordering_across_every_grouping`)
- **Issue:** Three lines building sort-key tuples for the pool/lock-site assertions exceeded the 88-character limit.
- **Fix:** Wrapped the tuple literals across multiple lines.
- **Files modified:** `tests/test_eustack_rules.py`
- **Verification:** `uv run ruff check` → 0 issues.
- **Committed in:** `c778c55` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both lint-only, no logic change)
**Impact on plan:** Zero scope change.

## Issues Encountered

None beyond the two lint fixes above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `SaturationAnalysis` now carries all four Phase 16 groupings (`pools`, `lock_sites`, `dependencies`, `flags`) plus `lock_finding_note` — the complete library surface Phase 17's `sift eustack` report + CSV renders. `EustackAnalysis.signatures` remains the single source for the ranked signature collapse (EUS-06); Phase 17 reads both objects, never re-derives either.
- Every ordering (pools, lock sites, dependencies) carries an explicit total-order sort key with a named tie-break, proven with deliberate ties in one whole-model test — Phase 17's renderer can iterate any of the four tuples directly with no re-sort.
- Full suite green: `ruff check` (0 issues), `pyright` (0 errors), `pytest` (739 passed, up from 734 at 16-02 close — 5 new tests, all green). Sift never emits the word "deadlock" anywhere in `src/` (mechanically guarded). No blockers for 16-04 or Phase 17.

## Self-Check: PASSED

- FOUND: 1b61bed, 0169985, c778c55 (all three task commits present in `git log --oneline --all`)
- FOUND: `src/sift/pipeline/eustack.py` (contains `class DependencyWait(`, `dimension="no_resolvable_frame_pct"`)
- FOUND: `tests/test_eustack_rules.py` (contains `test_dependency_split_by_subsystem`, `test_signature_passthrough_reads_eustack_analysis_directly`, `test_deterministic_ordering_across_every_grouping`)

---
*Phase: 16-saturation-contention-signature-collapse*
*Completed: 2026-07-25*
