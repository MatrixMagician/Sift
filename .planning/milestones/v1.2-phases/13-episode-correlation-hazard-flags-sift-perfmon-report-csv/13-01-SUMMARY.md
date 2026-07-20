---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
plan: 01
subsystem: tests
tags: [test-infrastructure, perfmon, fixtures, wave-0]
status: complete
requires: []
provides:
  - tests/_perfmon_fixtures.py (write_collision_csv, write_drift_csv, write_non_finite_csv)
  - tests/test_perfmon.py (ingest_perfmon_slice, log_boundary_event)
  - tests/test_cli_perfmon.py (_build_perfmon_case)
affects:
  - plan 13-02 (D-11 non-finite test, D-04 boundary-without-ts test)
  - plan 13-03 (WR-03 collision, WR-05 drift tests)
  - plan 13-06 (criterion-5 no-DSSErrors bundle test)
tech-stack:
  added: []
  patterns:
    - "csv.writer(quoting=QUOTE_ALL, lineterminator='\\n') to imitate the shipped PDH-CSV shape"
    - "fixture guard tests: every synthetic builder paired with an assertion that it carries its claimed property"
key-files:
  created:
    - tests/_perfmon_fixtures.py
    - tests/test_perfmon.py
    - tests/test_cli_perfmon.py
  modified: []
decisions:
  - "Synthetic PDH-CSV builders write via csv.writer with LF terminators, matching the shipped hartford_deny_slice.csv (verified LF, not CRLF)."
  - "log_boundary_event keeps the plan's parameter name `event_id`, so sift.models.event_id is deliberately not imported into tests/test_perfmon.py; the boundary test uses a literal 16-char id."
  - "The MCM/CSV fixture non-overlap (12:39:47.142-12:39:47.356 vs last sample 12:39:39.397) is recorded in tests/test_perfmon.py's module docstring as load-bearing guidance for plans 13-02 and 13-06."
metrics:
  duration: ~20 min
  tasks: 3
  files: 3
  completed: 2026-07-20
---

# Phase 13 Plan 01: Perfmon Test Infrastructure Summary

Three synthetic PDH-CSV builders for the collision/drift/non-finite paths the real
Hartford artefacts cannot reach, plus the two new test modules that hold the Phase 13
correlator and CLI suites — each builder guarded by a test proving the fixture really
carries its defect.

## What Was Built

**Task 1 — `tests/_perfmon_fixtures.py`** (`d61d87e` RED, `fa98a69` GREEN)

`PDH_HEADER_PREFIX` plus `write_collision_csv`, `write_drift_csv` and
`write_non_finite_csv`, each `(tmp_path: Path) -> Path`:

- **Collision (WR-03)** — `Process(MSTRSvr)\Size(MB)` and `Process(other)\Size(MB)`:
  the same counter under two *instances*, so `_short_counter_name` maps both to
  `Size(MB)`. Varying the instance axis (not the counter axis) matters: Hartford's
  `Size(MB)`/`RSS(MB)` pair does NOT collide, so a counter-axis fixture would exercise
  nothing.
- **Drift (WR-05)** — a 3-cell data row inside a 4-column file, with well-formed rows
  both before and after it.
- **Non-finite (D-11)** — `nan` and `inf` cells on otherwise healthy, correctly-sized
  rows. The adapter's `_bad_cells` probe is a bare `float()`, which accepts both — this
  is precisely the gap D-11 closes.

Three guard tests assert the properties. All writes are confined beneath the
pytest-supplied `tmp_path` (T-13-FIXPATH).

**Task 2 — `tests/test_perfmon.py`** (`1a715e0`)

`ingest_perfmon_slice()` builds a real `case.db` from the shipped CSV cut via
`DssperfmonAdapter` and returns `store.query_events()` (canonical ts order).
`log_boundary_event(event_id, ts, source_file)` returns a frozen `dsserrors` Event
standing in for a resolved span boundary; `ts=None` is deliberately permitted for
plan 13-02's D-04 test. Two smoke tests pin the 20-sample count and the milestone
figures (`27`/`186503` first, `266042`/`463915`/`401603`/`1488`/`0` last).

**Task 3 — `tests/test_cli_perfmon.py`** (`5cdc20a`)

`_build_perfmon_case()` instantiates exactly one adapter, ingesting the CSV and no
DSSErrors log, then returns the case directory. The single test asserts 20 events, all
`dssperfmon`, zero `dsserrors` — success criterion 5's precondition. No `sift perfmon`
invocation: that command lands in plan 13-06.

## Verification Performed

- `uv run pytest tests/_perfmon_fixtures.py tests/test_perfmon.py tests/test_cli_perfmon.py` — 6 pass (3 + 2 + 1)
- `uv run ruff check` (whole repo) — clean
- `uv run pyright` (whole repo) — 0 errors
- `uv run pytest` (full suite) — 572 passed, 8 deselected; no regression
- **Anti-vacuity check** (house fail-fast convention): each builder was broken in a
  scratch copy (collision → two counters of one instance; drift → row padded to full
  width; non-finite → `nan` replaced with a number) and all three guards failed. The
  guards are not vacuous.
- **Non-overlap claim verified against the fixtures directly**, not assumed:
  `tests/fixtures/mcm/hartford_deny_slice.log` spans 12:39:47.142–12:39:47.356;
  the CSV's last sample is 12:39:39.397 — a real 7.7 s gap.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pyright strict rejected the private-symbol import**

- **Found during:** Task 1
- **Issue:** The plan requires asserting against
  `sift.adapters.dssperfmon._short_counter_name`, but pyright strict raises
  `reportPrivateUsage` for a private symbol imported across modules.
- **Fix:** Applied the existing house convention (`tests/test_disk_full.py`,
  `tests/test_salience.py`): a targeted `# pyright: ignore[reportPrivateUsage]` with a
  rationale comment on the import.
- **Files modified:** `tests/_perfmon_fixtures.py`
- **Commit:** `fa98a69`

**2. [Rule 1 - Bug] `log_boundary_event` parameter rename left a stale body reference**

- **Found during:** Task 2
- **Issue:** The parameter was initially named `event_id_` to avoid shadowing the
  imported `sift.models.event_id`; renaming it back to the plan's `event_id` left
  `event_id=event_id_` in the body (caught by ruff F821 and the test run).
- **Fix:** Updated the body and dropped the now-unused `event_id` import, using a
  literal `"0" * 16` id in the boundary test instead.
- **Files modified:** `tests/test_perfmon.py`
- **Commit:** `1a715e0`

No architectural changes were needed; no package installs occurred (Rule 3 exclusion not
triggered).

## Notes for Later Plans

- **Do not build the golden-figure test through ingest.** The MCM and CSV fixtures do not
  overlap in time, so an MCM-resolved window contains zero samples from this CSV. Use
  `log_boundary_event` to hand-build the span at correlator-unit level. That non-overlap
  is real customer data and is itself the natural integration test for the D-06 hazard.
- `tests/_perfmon_fixtures.py` is not `test_`-prefixed, so its three guard tests run only
  when the file is named explicitly. This is intentional (it is a helper module) and does
  not affect the default suite.
- `tests/test_cli_perfmon.py` imports `FIXTURES` and `SLICE` from `test_perfmon` (the
  house bare-import idiom, as `tests/test_cli_report.py` does with `_report_fixtures`),
  so there is exactly one adapter-wiring definition to keep in step.

## Threat Flags

None — no new security surface. The two mitigate dispositions in the plan's threat
register were applied: T-13-FIXPATH (all writes beneath `tmp_path`, no caller-chosen
destination) and T-13-VACUOUS (guard tests, verified non-vacuous by counterfactual).

## Self-Check: PASSED

- `tests/_perfmon_fixtures.py` — FOUND
- `tests/test_perfmon.py` — FOUND
- `tests/test_cli_perfmon.py` — FOUND
- `d61d87e`, `fa98a69`, `1a715e0`, `5cdc20a` — all FOUND in git history
