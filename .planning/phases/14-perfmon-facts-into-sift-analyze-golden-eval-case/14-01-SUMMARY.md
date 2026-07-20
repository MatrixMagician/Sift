---
phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case
plan: "01"
subsystem: eval-fixtures
tags: [perfmon, mcm, eval, fixtures, overlap-guard, tdd, PERF-07, PERF-08]
requires:
  - analyse_mcm / analyse_perfmon episode-correlation path (Phase 13, shipped)
  - dsserrors + dssperfmon adapters, CaseStore ingest (shipped)
provides:
  - "eval case perfmon-denial (input pair only; truth.yaml lands in 14-05)"
  - "tests/test_perfmon_analyze._ingest_perfmon_case (shared ingest helper)"
  - "tests/test_perfmon_analyze.test_fixture_overlaps (anti-vacuous overlap guard)"
affects:
  - 14-04 (appends byte-identity / anti-hallucination integration tests here)
  - 14-05 (authors truth.yaml + wires the golden regression gate on this case)
tech-stack:
  added: []
  patterns:
    - "verbatim real denial slice + minimal re-timed AvailableMCM lead-up to widen the resolved window"
    - "empirical overlap verification before commit (never trust PDH timestamps by eye)"
key-files:
  created:
    - eval/cases/perfmon-denial/input/perfmon_denial.log
    - eval/cases/perfmon-denial/input/perfmon_overlap.csv
    - tests/test_perfmon_analyze.py
  modified: []
decisions:
  - "Reused the shipped hartford deny slice verbatim and prepended 3 real-format Contract-Succeeded lead-up lines (descending AvailableMCM) rather than authoring a wholly synthetic log — widens the window to ~12 s within D-07's re-timed-slice discretion."
  - "Skipped the optional write_overlapping_csv builder in tests/_perfmon_fixtures.py (YAGNI): the committed CSV is a static verbatim artifact the guard ingests directly; a tmp_path builder would serve nothing here."
metrics:
  tasks: 2
  files_changed: 3
  duration_min: 30
  completed: 2026-07-20
status: complete
---

# Phase 14 Plan 01: Overlapping Perfmon Fixture + Overlap Guard Summary

Authored the OVERLAPPING perfmon CSV + dsserrors denial-log pair (`eval/cases/perfmon-denial/input/`) and a self-verifying overlap guard, making the phase's whole downstream perfmon-citation integration non-vacuous: `analyse_perfmon` over the pair now yields an episode-scope trend with five counters each carrying a citable `at_denial_event_id`.

## What was built

- **`perfmon_denial.log`** — the shipped `hartford_deny_slice.log` verbatim, with 3 prepended real-format `Contract Request Succeeded` lead-up lines carrying descending `AvailableMCM` (200 GB → 90 GB → 30 GB, all sharing the real `HWM(PB)=469891629056`). Because the first episode's `span_start` is 0, these enter the `avail_timeline`; the 25%-of-HWM descent moves the resolved window start back from 12:39:47.142 to **12:39:35.000**, giving a ~12.2 s window `[12:39:35.000, 12:39:47.230]`.
- **`perfmon_overlap.csv`** — a 6-sample PDH-CSV (QUOTE_ALL, LF-terminated, `_HOST` = `env-325602laio1use1`) over the five D-04 salient counters (`Working set cache RAM usage(MB)`, `System\RAM used(MB)`, `Process(MSTRSvr)\Size(MB)`, `Open Sessions`, `Total MCM Denial`). All sample stamps fall strictly inside the window; values rise toward the denial (working set 180000 → 266042 MB). Naive PDH wall-clock is stamped UTC verbatim (ADR 0012), so the CSV and denial clocks are directly comparable.
- **`tests/test_perfmon_analyze.py`** — `_ingest_perfmon_case(config, case_dir) -> (events, McmAnalysis)` (mirrors `test_eval_cases._ingest_case`, returns pure values for later-wave reuse) and `test_fixture_overlaps`, which asserts ≥1 episode-scope `CounterTrend.at_denial_event_id` is non-None **and** that the id resolves to a `dssperfmon` store event (`cited ⊆ store`), not merely a non-empty groups tuple.

## Anti-vacuous proof (the load-bearing point)

- **GREEN on the authored pair:** episode group, `sample_count=6`, 5 counters with non-None `at_denial_event_id`, plus the `Total MCM Denial` always-zero PERF-05 flag — empirically confirmed via a scratch `analyse_perfmon` run before committing the files.
- **RED counterfactual (in-framework):** temporarily pointing `_PERFMON_CASE` at the non-overlapping `mcm-denial` case made `test_fixture_overlaps` fail with `assert []` (zero citable ids — `non_overlap` hazard, 0 in-span samples). The constant was restored byte-identically before commit. The shipped `tests/fixtures/{mcm,dssperfmon}/hartford_deny_slice.*` pair independently reproduces the same zero-citable RED state. This satisfies the project's TDD fail-fast / counterfactual-break rule.

## Deviations from Plan

**1. [Rule 1 — trim, not a reversal] Skipped the optional `write_overlapping_csv` builder.**
- **Where:** Task 1 `<files>` lists `tests/_perfmon_fixtures.py`; the plan marks the builder "optional... if you take the synthetic route".
- **Decision:** Not added. The committed CSV is a static verbatim eval artifact ingested directly by the guard; a `tmp_path` builder would have no consumer. `tests/_perfmon_fixtures.py` is unchanged and its 3 existing guard tests still pass (the Task 1 verify gate).
- **Impact:** None on acceptance — every acceptance criterion is met without it. If a later wave needs a programmatic builder it can add one then.

No other deviations: no bugs, no missing critical functionality, no auth gates, no architectural changes.

## Known Stubs

None. The eval case is intentionally input-only at this wave — `truth.yaml` is authored in 14-05 and a README/gate wiring follows there. `_case_dirs()` filters on `truth.yaml` existence and `_EXPECTED_CASES` does not include `perfmon-denial`, so `test_eval_cases` is unaffected (full suite still green).

## Verification

- `uv run pytest tests/test_perfmon_analyze.py tests/_perfmon_fixtures.py -q` → 4 passed.
- Full gate: `uv run ruff check` clean, `uv run pyright` 0 errors, `uv run pytest -q` → **639 passed, 8 deselected** (up from 638 — the new guard).
- CSV is 7 lines (< 100), LF-terminated; denial log auto-sniffs as dsserrors and `analyse_mcm` returns 1 episode.

## Commits

- `fd48e3a` — test(14-01): author overlapping perfmon CSV + denial-log pair
- `c61d253` — test(14-01): add perfmon overlap guard + shared ingest helper

## Self-Check: PASSED

- `eval/cases/perfmon-denial/input/perfmon_denial.log` — FOUND
- `eval/cases/perfmon-denial/input/perfmon_overlap.csv` — FOUND
- `tests/test_perfmon_analyze.py` — FOUND
- commit `fd48e3a` — FOUND; commit `c61d253` — FOUND
