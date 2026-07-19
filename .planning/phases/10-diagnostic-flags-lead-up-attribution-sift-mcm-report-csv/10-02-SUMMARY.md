---
phase: 10-diagnostic-flags-lead-up-attribution-sift-mcm-report-csv
plan: 02
subsystem: pipeline/mcm + config
status: complete
tags: [mcm, flags, mcm-03, d-12, thresholds, machine-independence, determinism]
requires:
  - "sift.pipeline.mcm.McmEpisode / MemoryBreakdown typed accessors (Phase 9)"
  - "sift.pipeline.mcm.select_window (Plan 10-01)"
  - "sift.config layered-dict loader + extra='forbid' idiom (Phase 3)"
provides:
  - "sift.config.ThresholdPair / McmThresholdsConfig / McmConfig ([mcm.thresholds])"
  - "SiftConfig.mcm field"
  - "sift.pipeline.mcm.DiagnosticFlag frozen model"
  - "sift.pipeline.mcm.compute_flags() pure five-flag grader"
  - "sift.pipeline.mcm._grade(warn, crit, *, invert) direction-aware helper"
  - "tests/fixtures/mcm/hartford_deny_double.log (x2 scaled machine-independence fixture)"
affects:
  - "Plan 10-04 report renderer (flags section + severity verdict)"
  - "Phase 11 cited MCM facts (flags carry denial_event_id provenance)"
tech-stack:
  added: []
  patterns:
    - "Graded info/warn/critical flags as part/whole*100 ratios vs config cut-points (D-12)"
    - "Inverted-metric grading via _grade(invert=True) (headroom: lower free-% is worse)"
    - "x2 (power-of-two) scaled fixture proves machine-independence bit-exactly"
key-files:
  created:
    - tests/fixtures/mcm/hartford_deny_double.log
  modified:
    - src/sift/config.py
    - src/sift/pipeline/mcm.py
    - tests/test_config.py
    - tests/test_mcm.py
decisions:
  - "value_pct rounded to 1 dp at source; the machine-independence test's round(,3) is then a no-op — x2 scaling is bit-exact under IEEE division (2a/2b == a/b for power-of-two factors), so no rounding tolerance is needed"
  - "cube/MMF flag reports cube-share-of-virtual as value_pct (the gating ratio) with MMF coverage appended to the message; grading gates on both cube_pct >= cut-point AND MMF coverage < mmf_pct_of_cube_low"
  - "config import in mcm.py kept under TYPE_CHECKING — pipeline stays runtime-decoupled from config; thresholds are read attribute-wise, no runtime import"
metrics:
  duration: ~18min
  completed: 2026-07-19
  tasks: 3
  files: 5
---

# Phase 10 Plan 02: MCM Graded Diagnostic Flags Summary

Landed MCM-03: five deterministic info/warn/critical diagnostic flags computed as
pure `part/whole*100` ratios (never absolute GB), plus the config-only
`[mcm.thresholds]` section (D-12) whose calibrated defaults make the real Hartford
episode read **CRITICAL** on the correct driver — working-set = 65.4% of IServer
virtual. Proved success criterion #5 (machine-independence) with a ×2-scaled
fixture that yields byte-identical flag tiers, percentages and window thresholds.

## What was built

- **`ThresholdPair` / `McmThresholdsConfig` / `McmConfig`** (`config.py`): frozen
  `extra="forbid"` models; defaults are the RESEARCH Deliverable-1 table
  (`working_set_pct_virtual=(20,40)`, `other_processes_pct_physical=(10,20)`,
  `cube_pct_virtual=(25,40)`, `mmf_pct_of_cube_low=10`,
  `smartheap_pool_pct_virtual=(5,15)`, `system_free_headroom_pct=(20,5)`). The TOML
  table is literally `[mcm.thresholds]`; `SiftConfig` gains `mcm: McmConfig`. Not
  added to `_ENV_SCALARS` — nested threshold mappings stay TOML/flag-only (D-12).
- **`DiagnosticFlag`** frozen model (`mcm.py`): `dimension`, `severity`,
  `value_pct`, British-English `message` with the % inline, `event_ids`.
- **`_grade(value_pct, warn, crit, *, invert=False)`**: upward by default;
  `invert=True` flips the comparison so a LOW system-free-headroom grades worst
  (the inverted-metric special case, Pitfall 2 / T-10-04).
- **`compute_flags(ep, thresholds)`**: pure, I/O-free. Five flags — working-set %
  virtual, other-processes % physical, cube/MMF coverage, SmartHeap releasability,
  system-free headroom (inverted). Every `None`/zero-denominator is guarded before
  dividing, so a missing input emits no flag (D-03); all flags cite
  `denial_event_id` (D-16).
- **`hartford_deny_double.log`**: every absolute memory/byte figure that feeds a
  flag ratio or the window doubled (×2 stays integral, Pitfall 3); 23 Format-A
  labels preserved, working-set ratio invariant at 65.436%.

## Tasks

| Task | Name | Type | Commit |
|------|------|------|--------|
| 1 | RED: scaled fixture + flag/config/calibration/headroom/machine-independence tests | auto | f4ed712 |
| 2 | GREEN: McmThresholdsConfig + [mcm.thresholds] section | auto (tdd) | a4c4a8b |
| 3 | GREEN: DiagnosticFlag + compute_flags (five flags, inverted headroom) | auto (tdd) | 268f20f |

## Verification

- `uv run pytest tests/test_mcm.py tests/test_config.py` — flags, calibration,
  inverted headroom, machine-independence, thresholds all green.
- `uv run pytest` — 492 passed, 8 deselected (full-suite regression clean).
- `uv run ruff check` — clean; `uv run pyright` — 0 errors, 0 warnings.
- I/O-free guard: `mcm.py` imports no typer/sqlite3/httpx/csv (grep == 0).
- Manual: no per-run CLI threshold flag; no absolute-GB value in any flag
  `message`/`value_pct` (all percentages).

## Hartford calibration (the anchor)

| Flag | value_pct | Severity |
|------|-----------|----------|
| working_set_pct_virtual | 65.4% | **critical** (the driver) |
| other_processes_pct_physical | 18.5% | warn |
| system_free_headroom_pct | 9.8% | warn (inverted) |
| cube_mmf_coverage | 6.8% | info |
| smartheap_releasable | 1.3% (releasable) | info |

Episode overall = max tier = **CRITICAL**.

## Success criteria

- Five deterministic %-based flags graded info/warn/critical (MCM-03); Hartford
  reads CRITICAL on the correct driver — met.
- Thresholds config-only (`[mcm.thresholds]`, D-12) with calibrated defaults, loud
  on typo, no per-run CLI knob — met.
- ×2 scaled fixture proves machine-independence (criterion #5): identical
  `(dimension, severity, round(value_pct,3))` tuples + window threshold_pct /
  request_count — met.

## Deviations from Plan

None — plan executed as written. Threat register mitigations all satisfied:
T-10-04 (inverted-headroom test), T-10-05 (machine-independence test),
T-10-06 (None/zero guards), T-10-07 (`extra='forbid'` typo-loud), T-10-SC (no
package installs). One clarifying decision (not a deviation): the cube/MMF flag
reports cube-share-of-virtual as `value_pct` with MMF coverage in the message,
grading on both the cube share and the MMF-coverage floor per the reference gate.

## Known Stubs

None. `compute_flags` reads only real parsed `MemoryBreakdown` accessors +
`mcm_settings`/`current_memory_info`; a `None` input is a legitimate recorded
absence (D-03), not a stub. No placeholder/empty-data paths.

## Self-Check: PASSED
