---
phase: 17-multi-dump-progression-sift-eustack-report-csv
plan: 01
subsystem: cli
tags: [pydantic, typer, csv, eustack, mcm-perfmon-pattern]

requires:
  - phase: 16-saturation-contention-signature-collapse
    provides: EustackAnalysis/SaturationAnalysis frozen models consumed read-only (analyse_eustack, analyse_saturation)
provides:
  - "sift eustack <case> command — first CLI wiring of the Phase 15/16 eu-stack pipeline"
  - "pipeline/eustack_progression.py — dump grouping/ordering (D-01 single/multi-timestamp path), frozen progression models"
  - "render/eustack_report.py — markdown/json/CSV renderer mirroring perfmon_report.py"
  - "eustack_signatures.csv — one row per signature, base D-05 columns + per-dump count + delta columns"
affects: [17-02-multi-dump-progression, 17-03-progression-rendering]

tech-stack:
  added: []
  patterns:
    - "Leaf pipeline module consuming a frozen upstream model read-only (eustack_progression.py -> eustack.py)"
    - "Three-function renderer shape (markdown/json/csv) mirrored verbatim from perfmon_report.py"
    - "Standalone bundle-dir CLI command mirroring mcm()/perfmon() exactly (D-12): report-before-CSV write, unlink-both-on-OSError, sanitised error, finally: store.close()"

key-files:
  created:
    - src/sift/pipeline/eustack_progression.py
    - src/sift/render/eustack_report.py
    - tests/test_cli_eustack.py
  modified:
    - src/sift/cli.py

key-decisions:
  - "D-01 (multi-dump, all-timestamped) ordering path is implemented in resolve_dump_order now, even though only the N=1 case is exercised by this plan's own tests — the D-02 fallback branch raises NotImplementedError explicitly rather than falling through to an undeclared order, so 17-02 has a loud, unambiguous seam to fill in"
  - "SignatureProgression carries the full frames tuple internally (the cross-dump join key 17-02 needs) while matched_frame/leaf_frame are the D-07 display projection computed once in analyse_eustack_bundle, not re-derived at render time"
  - "Zero eu-stack dumps needs no special branch in analyse_eustack_bundle: an empty resolved order falls through to analyse_eustack([], ...), whose documented zero-events contract already yields a valid zero-valued EustackAnalysis/SaturationAnalysis — the empty-case exit-0 test (Task 2) passed against Task 1's implementation unmodified"

patterns-established:
  - "Progression models (DumpSlice/OrderingFlag/SignatureProgression/ProgressionAnalysis/EustackBundle) are all frozen ConfigDict(frozen=True, extra=\"forbid\"), matching SignatureGroup's own config exactly"

requirements-completed: [EUS-09]

coverage:
  - id: D1
    description: "sift eustack <case> on a case holding eu-stack dumps and no DSSErrors log exits 0 and writes eustack_report.md plus eustack_signatures.csv"
    requirement: EUS-09
    verification:
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_writes_bundle"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_no_dsserrors_log"
        status: pass
    human_judgment: false
  - id: D2
    description: "A single-dump case yields the full classification and saturation report, computed on the last (only) dump"
    requirement: EUS-09
    verification:
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_writes_bundle"
        status: pass
    human_judgment: false
  - id: D3
    description: "Re-running on an unchanged case produces byte-identical Markdown, JSON and CSV (D-13)"
    requirement: EUS-09
    verification:
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_byte_identical_rerun"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_byte_identical_rerun_json"
        status: pass
    human_judgment: false
  - id: D4
    description: "CSV string cells carrying C++ symbol text pass through the shipped _csv_safe guard, imported not reimplemented (D-06)"
    requirement: EUS-09
    verification:
      - kind: unit
        ref: "grep: from sift.render.perfmon_report import _csv_safe in src/sift/render/eustack_report.py; def _csv_safe count 0"
        status: pass
    human_judgment: false
  - id: D5
    description: "ADR 0007 exit-code contract: 0 = bundle written (including empty case), 1 = missing case / write failure, 2 = bad --format"
    requirement: EUS-09
    verification:
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_empty_case"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_missing_case_exit_one"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_bad_format_exit_two"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_write_failure_removes_partial_bundle"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-07-25
status: complete
---

# Phase 17 Plan 1: Eu-Stack Tracer — `sift eustack` Report + CSV Summary

**First CLI wiring of the Phase 15/16 eu-stack pipeline: `sift eustack <case>` writes a deterministic Markdown/JSON report plus `eustack_signatures.csv` for a single-dump case, following the `sift mcm`/`sift perfmon` standalone contract verbatim.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-25
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- `analyse_eustack_bundle` wires dump grouping → ordering → per-dump `analyse_eustack` → last-dump `analyse_saturation` → `ProgressionAnalysis`, the first CLI-reachable path for a pipeline stage that previously had zero callers outside `tests/test_eustack_rules.py`
- `render_eustack_markdown`/`render_eustack_json`/`write_eustack_signatures_csv` mirror `perfmon_report.py`'s three-function shape exactly, reusing `_csv_safe` and `markdown._field` rather than reimplementing either guard
- `sift eustack` matches the full ADR 0007 exit-code contract (empty case, missing case, bad `--format`, partial-write cleanup) and D-13 byte-identical re-run — verified against the shipped `mcm`/`perfmon` test shapes

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end "sift eustack on a dumps-only case"** - `afd42a9` (feat)
2. **Task 2: EUS-09 standalone contract — exit codes, empty case, cleanup, byte-identity** - `ac024af` (test)

_Note: Task 2 required no production code changes — Task 1's `analyse_eustack_bundle` already fell through cleanly to `analyse_eustack([], ...)`'s zero-events contract for the empty-case path, and the report-before-CSV write ordering with unlink-on-`OSError` was already correct._

## Files Created/Modified
- `src/sift/pipeline/eustack_progression.py` - dump grouping (`group_dumps`), ordering (`resolve_dump_order`, D-01 path; D-02 fallback raises `NotImplementedError` for 17-02), frozen progression models, `analyse_eustack_bundle` orchestration
- `src/sift/render/eustack_report.py` - Markdown/JSON/CSV renderer over `EustackBundle`, reusing `_csv_safe`/`_field`
- `src/sift/cli.py` - `sift eustack` command, placed immediately after `perfmon` (~:1306), mirroring its bundle-dir/write/cleanup/summary shape
- `tests/test_cli_eustack.py` - 9 tests: happy path, no-DSSErrors-log, JSON format, empty case, missing case, bad format, partial-write cleanup, byte-identical re-run (md + json)

## Decisions Made
- Zero-dump case needed no special branch: `analyse_eustack_bundle` falls through to `analyse_eustack([], rules, rules_hash)` when the resolved dump order is empty, and that function's documented zero-events contract (a zero-valued `EustackAnalysis` with all five role keys present) already satisfies the empty-case exit-0 requirement — confirmed by `test_eustack_empty_case` passing against Task 1's code unmodified.
- `resolve_dump_order` implements the full D-01 (2+ dumps, all timestamped) sort path now rather than deferring it to 17-02, since the plan's own architecture diagram requires the function signature to support N dumps; only the D-02 fallback (any dump missing a timestamp) is explicitly out of scope and raises `NotImplementedError` with a message naming 17-02 as the owner.
- `step_deltas`/`overall_delta` CSV cells are written as plain (non-`_csv_safe`-guarded) text/int, matching perfmon's numeric-cells-bypass-the-formula-guard discipline — `_csv_safe` is reserved for cells carrying untrusted C++ symbol text (role, subsystem, matched_pattern, reason, matched_frame, leaf_frame, per-dump header names).

## Deviations from Plan
None - plan executed exactly as written. Both tasks landed with zero auto-fixes; the only lint issue (one E501 line-length violation in `eustack_progression.py`) was fixed inline before the Task 1 commit.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
`resolve_dump_order`'s D-02 fallback (`NotImplementedError`) and `SignatureProgression`'s `step_deltas`/`overall_delta`/`appeared`/`vanished` fields (currently always empty/`False`/`0` for the single-dump N=1 case) are the explicit seams 17-02 fills in for genuine multi-dump cases. No blockers.

---
*Phase: 17-multi-dump-progression-sift-eustack-report-csv*
*Completed: 2026-07-25*

## Self-Check: PASSED

All claimed files exist on disk; both task commits (`afd42a9`, `ac024af`) present in `git log`.
