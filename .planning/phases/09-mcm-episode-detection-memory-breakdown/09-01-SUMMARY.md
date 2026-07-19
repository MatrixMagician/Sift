---
phase: 09-mcm-episode-detection-memory-breakdown
plan: 01
subsystem: testing
tags: [mcm, dsserrors, pytest, tdd, fixtures, pydantic, hartford]

# Dependency graph
requires:
  - phase: 05-domain-adapters
    provides: DsserrorsAdapter (parse), Event dataclass, CaseStore (insert_events/query_events)
  - phase: 04-salience-retrieval
    provides: pure-function-over-stored-rows analog (pipeline/salience.py)
provides:
  - "tests/test_mcm.py — 8 golden assertions (RED) pinning the sift.pipeline.mcm acceptance contract"
  - "tests/fixtures/mcm/hartford_deny_slice.log — verbatim single-episode Hartford deny slice (open/truncated, no State=normal)"
  - "docs/reference/analyze_dss8.py — byte-verbatim vendored provenance copy of the port basis"
affects: [09-02, phase-10-mcm-report-csv, phase-11-analyze-feed]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED-first: failing golden suite committed before the module it tests exists"
    - "Fixture-ingest helper reuses DsserrorsAdapter.parse -> CaseStore.insert_events -> query_events (no new ingest machinery)"
    - "Anticipated public API pinned by tests: detect_episodes(events) -> list[McmEpisode]; McmEpisode(denial_event_id, event_ids, recovery|None, open_truncated, fragmented, lifecycle, breakdown); LifecycleSignal(kind, event_id); MemoryBreakdown(raw_map, current_memory_info, mcm_settings + typed MB accessors)"

key-files:
  created:
    - "tests/test_mcm.py"
    - "tests/fixtures/mcm/hartford_deny_slice.log"
    - "docs/reference/analyze_dss8.py"
  modified: []

key-decisions:
  - "Vendored analyze_dss8.py byte-verbatim (cmp-clean, no provenance header) — provenance recorded here instead, to guarantee the byte-match acceptance criterion"
  - "Fixture is source lines 5816-5881 (a verbatim contiguous slice), not the plan's ~5790-5885 estimate — chosen against the real log so the Info Dump, denial detail block, and offload lifecycle tail are all contiguous"
  - "Pinned the anticipated MemoryBreakdown accessors as MB-native floats and mcm_settings as dict[str,str] (value == raw token), matching RESEARCH Pattern 2 and the reference parse_abbrev_block shape"
  - "Left requirements-completed empty: MCM-01/MCM-02 are delivered by the GREEN half (09-02); the RED contract alone does not satisfy them"

patterns-established:
  - "RED-for-the-right-reason gate: suite fails ONLY at collection with 'No module named sift.pipeline.mcm'; assertions are not weakened to pass early"
  - "Real-data validation: fixture asserts values/structure against a real customer log, and the no-State=normal tail exercises the D-07 open/truncated path on real data"

requirements-completed: []  # MCM-01/MCM-02 complete at 09-02 (GREEN); this plan ships only the failing contract

coverage:
  - id: D1
    description: "8-assertion golden MCM suite present and RED solely because sift.pipeline.mcm is absent (not an assertion authored to pass early)"
    requirement: "MCM-01"
    verification:
      - kind: other
        ref: "grep -c 'def test_' tests/test_mcm.py == 8 && uv run pytest tests/test_mcm.py -q => ModuleNotFoundError: No module named 'sift.pipeline.mcm'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Hartford deny slice fixture: verbatim single episode — 1 denial banner, 0 State=normal, Memory Reserve = 0 (0Bytes) present, offload-complete present, Info Dump markers present, >=3 Contract Request Succeeded"
    requirement: "MCM-02"
    verification:
      - kind: other
        ref: "banner==1, State=normal==0, 'Memory Reserve = 0 (0Bytes)' present, 'Working set emergency offload completed' present, 'Contract Request Succeeded' count==8 (>=3)"
        status: pass
    human_judgment: false
  - id: D3
    description: "docs/reference/analyze_dss8.py vendored byte-verbatim (non-executed provenance copy)"
    verification:
      - kind: other
        ref: "cmp /home/oliverh/Downloads/analyze_dss8.py docs/reference/analyze_dss8.py => byte-identical"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-07-19
status: complete
---

# Phase 9 Plan 01: MCM RED Golden Contract Summary

**8 failing golden assertions plus a verbatim single-episode Hartford deny slice and the byte-verbatim vendored reference — the executable RED acceptance contract that Wave 2 (09-02) turns GREEN.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-19T18:25:54Z
- **Completed:** 2026-07-19T18:31:56Z
- **Tasks:** 2
- **Files modified:** 3 (all created)

## Accomplishments
- Authored `tests/test_mcm.py` — 8 named golden assertions (single-episode detection, lifecycle signals, absent-signal tolerance, denial-time breakdown values, MCM-settings completeness incl. `Memory Reserve`, open/truncated flag, determinism, D-06 fragmentation guard) plus a fixture-ingest helper reusing the established DsserrorsAdapter + CaseStore pattern.
- Cut `tests/fixtures/mcm/hartford_deny_slice.log` — a 66-line verbatim contiguous slice (source lines 5816-5881) holding one denial episode: lead-up Succeeded line, pre-denial Info Dump (incl. `Memory Reserve = 0 (0Bytes)` and `SmartHeap Cache Releasable = true`), the denial banner + 23-label Format-A detail block, the `AvailableMCM` climb-back, and the memory-status-low / offload-start / offload-complete tail. No `State=normal` — the D-07 open/truncated path on real data.
- Vendored `docs/reference/analyze_dss8.py` byte-verbatim (cmp-clean) as durable, citable provenance for the port.
- Suite confirmed RED for the right reason: fails at collection with `ModuleNotFoundError: No module named 'sift.pipeline.mcm'`, ruff-clean, exactly 8 `def test_` functions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Vendor reference + cut Hartford deny slice fixture** - `e6f4fcd` (test)
2. **Task 2: RED golden test suite tests/test_mcm.py** - `1de5f03` (test)

_This is the RED half of a TDD RED->GREEN phase; the single `test(...)` gate commit per task is the RED marker. The GREEN `feat(...)` commit lands in 09-02._

## Files Created/Modified
- `tests/test_mcm.py` - 8 golden assertions + `_episodes_from_fixture` ingest helper + `_ev` synthetic-event builder for the fragmentation guard.
- `tests/fixtures/mcm/hartford_deny_slice.log` - verbatim single-episode Hartford deny slice (lines 5816-5881), no State=normal.
- `docs/reference/analyze_dss8.py` - byte-verbatim provenance copy of `/home/oliverh/Downloads/analyze_dss8.py`.

## Decisions Made
- **Vendored the reference byte-verbatim with no header edit.** The plan permitted a one-line provenance header only if it did not alter the body; the safest way to satisfy the byte-match acceptance criterion was to copy verbatim (`cmp`-clean) and record provenance in this SUMMARY instead. Source: `/home/oliverh/Downloads/analyze_dss8.py`.
- **Pinned the anticipated public API in the tests.** `detect_episodes` returns `list[McmEpisode]`; `McmEpisode` exposes `denial_event_id`, `event_ids`, `recovery` (`None` when open), `open_truncated`, `fragmented`, `lifecycle: list[LifecycleSignal]`, `breakdown: MemoryBreakdown | None`; `LifecycleSignal` has `kind` + `event_id`; `MemoryBreakdown` has `raw_map: dict[str, tuple[float, str]]`, `current_memory_info`/`mcm_settings: dict[str, str]`, and MB-native accessors (`cube_caches_mb`, `working_set_mb`, `mmf_mb`, `other_memory_mb`, `iserver_virtual_mb`). 09-02 must implement to this contract.
- **Lifecycle kind vocabulary fixed** as `memory-status-low`, `emergency-offload-start`, `emergency-offload-complete` (the strings the GREEN detector must emit).
- **`requirements-completed` left empty.** MCM-01/MCM-02 are only satisfied once the analyser exists (09-02); marking them complete off the RED contract would be false.

## Deviations from Plan

### Fixture line range (validate-against-real-data)

**1. [Real-data adjustment] Slice is source lines 5816-5881, and only 1 Contract Request Succeeded line precedes the banner (not >=3 "before")**
- **Found during:** Task 1 (fixture cut)
- **Issue:** The plan's action text estimated ~5790-5885 and "at least 3 Contract Request Succeeded lines BEFORE the denial banner". In the real Hartford log only one Succeeded line (5816) sits in the pre-denial lead-up; the remaining Succeeded lines are the post-denial `AvailableMCM` climb-back (5870-5876).
- **Fix:** Cut the verbatim contiguous slice 5816-5881, which contains 8 total `Contract Request Succeeded` lines (1 lead-up + 7 climb-back). This satisfies the plan's binding acceptance grep (`>= 3` total) and keeps the byte-verbatim, single-contiguous-episode requirement; forcing 3 lead-up Succeeded lines would have required starting ~line 5434, ballooning the slice past the ~150-line target and no longer a tight single episode.
- **Files modified:** tests/fixtures/mcm/hartford_deny_slice.log
- **Verification:** All Task 1 acceptance greps pass (banner==1, State=normal==0, Memory Reserve present, offload-complete present, Current Memory Info + MCM Settings present, Succeeded==8).
- **Committed in:** e6f4fcd

### Ruff import-ordering auto-fix

**2. [Rule 3 - Blocking hygiene] ruff I001 on tests/test_mcm.py**
- **Found during:** Task 2 (post-write hygiene check)
- **Issue:** ruff flagged import organisation (I001) on the new test file.
- **Fix:** `uv run ruff check --fix tests/test_mcm.py` (import reorder only); re-verified 8 tests and the RED collection failure still hold.
- **Files modified:** tests/test_mcm.py
- **Verification:** `ruff check` clean; `grep -c 'def test_'` == 8; pytest still RED with `No module named 'sift.pipeline.mcm'`.
- **Committed in:** 1de5f03

---

**Total deviations:** 2 (1 real-data fixture adjustment, 1 lint auto-fix)
**Impact on plan:** Both keep the plan's binding acceptance criteria intact. No scope creep; no production code written.

## Issues Encountered
None. Both `<verify>` automated blocks passed on first run after each artifact was authored.

## Known Stubs
None. The RED suite is intentionally failing on the absent `sift.pipeline.mcm` module — this is the required Wave-1 end state, not a stub. No production module, store schema, or CLI was created (per the plan's explicit prohibitions).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 09-02 (GREEN) can now port `prescan` / `parse_detail_block` / `parse_abbrev_block` / `_get` from `docs/reference/analyze_dss8.py` into `src/sift/pipeline/mcm.py` and implement the pinned public API until all 8 assertions pass.
- Gate reminder: full green (`ruff check` + `pyright` + `pytest`) is met at the END of 09-02, not here. `uv run pytest` is currently RED by design (the new suite only).
- Prohibitions honoured: no `src/sift/pipeline/mcm.py`, no edits to `src/sift/models.py` or `src/sift/adapters/dsserrors.py`.

## Self-Check: PASSED
- Files present: tests/test_mcm.py, tests/fixtures/mcm/hartford_deny_slice.log, docs/reference/analyze_dss8.py, 09-01-SUMMARY.md — all FOUND.
- Commits present: e6f4fcd (Task 1), 1de5f03 (Task 2) — both FOUND in git log.

---
*Phase: 09-mcm-episode-detection-memory-breakdown*
*Completed: 2026-07-19*
