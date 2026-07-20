---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
plan: 06
subsystem: cli
tags: [perfmon, cli, correlation, full-sample-range, determinism, exit-codes]
status: complete
requires:
  - "sift.pipeline.perfmon: analyse_perfmon, _counter_trends, _hazard_counter_set_drift (plans 13-02/13-04)"
  - "sift.render.perfmon_report: render_perfmon_markdown/json, write_perfmon_trend_csv (plan 13-05)"
  - "sift.cli: _case_store, case_db_path, _sanitise, the mcm command as the cloned template"
provides:
  - "sift.pipeline.perfmon.FULL_RANGE_LABEL"
  - "sift.pipeline.perfmon._file_scope_groups"
  - "sift.cli.PerfmonFormat"
  - "sift.cli.perfmon (the sift perfmon command)"
affects:
  - "Phase 14 (LLM facts consume PerfmonAnalysis; the file-scope path is now a real input shape)"
tech-stack:
  added: []
  patterns:
    - "CLI command cloned clause-for-clause from a shipped sibling rather than re-derived"
    - "Exclusive analysis paths (episode vs file) selected once, never both"
key-files:
  created: []
  modified:
    - src/sift/pipeline/perfmon.py
    - src/sift/cli.py
    - tests/test_cli_perfmon.py
decisions:
  - "The no-episode path is exclusive and taken at the top of analyse_perfmon: with no episodes there is no window, so the episode loop is not entered at all"
  - "Counter-set drift runs over file-scope groups (it is a property of the file); the always-zero denial hazard deliberately does not (there is no denial to contradict)"
  - "The plan's fail-fast counterfactual for the empty guard was unreachable from the no-events test, so a test that genuinely exercises it was added rather than reporting a vacuous pass"
metrics:
  duration: ~35 min
  tasks: 3
  files: 3
  tests_added: 14
  completed: 2026-07-20
---

# Phase 13 Plan 06: sift perfmon Command Summary

`sift perfmon <case>` ships: the D-20 whole-file trend path, the Typer command mirroring `sift mcm` clause for clause, and the integration tests proving success criteria 2 and 5.

## What was built

| Symbol | File | Role |
|--------|------|------|
| `FULL_RANGE_LABEL` | `pipeline/perfmon.py` | The window label used when there is no window — states plainly that no denial episode was detected |
| `_file_scope_groups` | `pipeline/perfmon.py` | One `TrendGroup` per `source_file` over its full sample range, computed by the SAME `_counter_trends` the episode path calls |
| `PerfmonFormat` | `cli.py` | `StrEnum` (`md`/`json`); an unknown value is a Typer usage error, exit 2 |
| `perfmon` | `cli.py` | The command: report + CSV under `<case>/perfmon/`, stdout summary, ADR 0007 exit codes |

`analyse_perfmon` now selects one of two exclusive paths: with episodes, the existing correlation loop; without, the file path. There is no second figure implementation — only the span differs.

## Key decisions

**The empty-guard fail-fast was honestly reported, not faked.** The plan's counterfactual said removing the guard before `samples[0]` should make `test_no_episodes_no_events_yields_empty_groups` fail with `IndexError`. It does not: with no events the per-file loop is never entered, so that test cannot prove the guard. Rather than report a vacuous pass, `test_no_episodes_untimestamped_file_yields_no_group` was added — a perfmon file whose every sample lost its timestamp. Removing the guard makes it fail with `IndexError: list index out of range` at `perfmon.py:520`; restoring it (byte-identically, from a copy) turns it green.

**Drift yes, denial no, in the file path.** Counter-set drift is a property of the file and is meaningful with no episode. The always-zero denial hazard is not: without a detected denial there is nothing for a zero counter to contradict, and a flag that fires on every healthy case trains the reader to ignore the one that matters (D-14).

**`query_events()` called exactly once.** `grep -c query_events src/sift/cli.py` went 1 → 2, confirming the new command calls it once and feeds the same list to both `analyse_mcm` and `analyse_perfmon`.

## Deviations from Plan

**1. [Rule 2 — Test cannot prove its guard] Added `test_no_episodes_untimestamped_file_yields_no_group`**
- **Found during:** Task 1, fail-fast step
- **Issue:** The prescribed counterfactual did not fail; the empty guard was untested.
- **Fix:** Added a test that genuinely reaches the guard, then re-ran the counterfactual and confirmed the `IndexError`.
- **Files modified:** `tests/test_cli_perfmon.py`
- **Commit:** `5bca568`

Otherwise the plan was executed as written. The integration test was NOT weakened: `test_non_overlap_end_to_end` passed asserting the critical non-overlap hazard, exactly as the fixture timestamps predict.

## Real-artefact verification (no automated equivalent)

Run against `~/Downloads/hartford/` (13,596-row CSV + the 4,501-event deny log, ingested into one case):

```
PERFMON EXIT=0
Correlated 1 span; wrote perfmon_report.md + perfmon_trend.csv to .../cases/hartreal/perfmon
  Span 1: warn — Total MCM Denial read 0 on all 1 in-span reading(s) despite a detected
  MCM denial in this window, so the counter is almost certainly not wired on this host...
```

- **The always-zero `Total MCM Denial` hazard DID fire** on the real case — the counter is not wired on that host.
- Window `AvailableMCM < 25% of HWM (437.6 GB)`, span `2026-04-07T12:39:18.794 → 12:39:47.230`, 1 sample in span.
- `Working set cache RAM usage(MB)`: at-denial `266042.0`, peak `266042.0` — the milestone figure, reproduced end to end from real artefacts.
- CSV: 23 rows (header + 22 counters).

Also run: the no-DSSErrors-log case (`sift new` → `ingest` the CSV alone → `sift perfmon`) exits **0**, correlating 1 full-range span with no hazards. `sift perfmon --help` shows the command and its `--format` option.

## Requirements

PERF-04, PERF-05 and PERF-06 are complete: the correlator, the hazard flags and the user-visible `sift perfmon` report + CSV all ship.

## Verification

- `uv run pytest tests/test_cli_perfmon.py -q` — 15 tests pass
- `uv run ruff check` — All checks passed
- `uv run pyright` — 0 errors, 0 warnings, 0 informations
- `uv run pytest` — 630 passed, 8 deselected

## Self-Check: PASSED

- `src/sift/pipeline/perfmon.py`, `src/sift/cli.py`, `tests/test_cli_perfmon.py` — FOUND
- Commits `908bdcb`, `5bca568`, `f1be042`, `63a1945`, `ef546f8` — all FOUND in `git log`
