---
phase: 07-evaluation-harness-golden-cases
plan: 03
subsystem: eval
tags: [eval-harness, threshold-gate, ci-exit-code, tdd, offline, adr]
requires: [eval-package, sift-eval-command, determinism-stability-over-drift]
provides: [eval-threshold-gate, sift-eval-nonzero-exit, thresholds-toml]
affects:
  - eval/thresholds.toml
  - src/sift/eval/thresholds.py
  - src/sift/eval/report.py
  - src/sift/cli.py
  - docs/decisions/
  - tests/
tech-stack:
  added: []
  patterns:
    - stdlib-tomllib-binary-load
    - uniform-floor-direction-gate
    - anti-vacuity-gate-guards
    - command-owns-nonzero-exit
key-files:
  created:
    - eval/thresholds.toml
    - src/sift/eval/thresholds.py
    - docs/decisions/0010-eval-exit-codes.md
    - tests/test_eval_thresholds.py
  modified:
    - src/sift/eval/report.py
    - src/sift/cli.py
decisions:
  - "The gate fails on ANY run_failed case, ANY negative false-positive, OR an empty positive set (vacuous 1.0 is never a pass) — closing the Wave-2 verified finding that a crashed run could exit 0."
  - "All four floors are lower bounds (value >= floor); the fourth is gated as determinism_stability (higher-better) while the report displays drift = 1 - stability (ADR 0010)."
  - "eval_() owns typer.Exit(1) — the non-zero CI signal is not suppressible and never satisfied by an advisory judge score (D-08)."
  - "load_thresholds reads binary-mode tomllib and validates the four float floors, mirroring config.py (T-07-02); a missing/malformed floor is a usage error (exit 2)."
  - "A --thresholds override was added (default eval/thresholds.toml) — trivially cheap and lets tests pin the floors regardless of cwd."
metrics:
  duration: ~4 min
  completed: 2026-07-19
  tasks: 3
  files: 6
status: complete
---

# Phase 7 Plan 03: Eval Threshold Gate & CI Exit Summary

`sift eval` is now **CI-usable**: the printed metrics (Plan 02) become a pass/fail
gate compared against per-metric floors in `eval/thresholds.toml`, and the command
raises a non-suppressible non-zero exit on regression. A planted keyword-missing
regression fails the suite with exit 1; a clean suite exits 0; usage errors exit 2
(SPEC §8 / EVAL-03). The exit-code + determinism-direction contract is recorded in
ADR 0010.

## What Was Built

- **`eval/thresholds.toml`** — the four lower-bound floors: `retrieval_hit_rate =
  0.80`, `hypothesis_hit_at_k = 1.00` (so a keyword-missing reply breaches it),
  `citation_validity_rate = 1.00` (the anti-hallucination invariant), and
  `determinism_stability = 1.00` (offline runs are byte-identical). A
  British-English comment documents that all four are `value >= floor` and that
  stability is the gated form of "drift".
- **`src/sift/eval/thresholds.py`** — `load_thresholds` (binary-mode `tomllib`,
  mirrors `config.py`; validates the four float floors, `ValueError` → usage
  error) and `gate(SuiteResult, floors) -> GateResult`. The gate compares each
  keyword aggregate against its floor AND enforces the three **anti-vacuity
  rules** the aggregates alone do not: a `run_failed` case, a negative
  false-positive, and an empty positive set each force `passed = False`. Judge
  scores are never consulted (D-08). `GateResult.as_dict()` gives the canonical
  `--json` view.
- **`src/sift/eval/report.py`** — both renderers gained an optional `gate`
  argument that threads the per-metric floor verdict and the overall `GATE:
  PASS/FAIL` line into the text table and a `"gate"` object into `--json`.
- **`src/sift/cli.py::eval_()`** — new `--thresholds` option; loads the floors
  early (unreadable → exit 2), builds the `SuiteResult`, calls `gate`, prints the
  gated table/JSON, and **owns `typer.Exit(1)`** when the gate fails so CI sees
  the regression.
- **`docs/decisions/0010-eval-exit-codes.md`** — the `{0,1,2}` exit contract, the
  `determinism_stability` gate + drift display, the three anti-vacuity rules, and
  the judge-never-gates rule; cites SPEC §6/§8 and D-06/D-07/D-08, mirrors the
  ADR 0005/0007 format.
- **`tests/test_eval_thresholds.py`** — offline (zero sockets). CLI exit contract
  (clean → 0, planted keyword-missing regression → 1, bad `--suite` → 2, JSON
  marks the failed metric + overall) plus `gate()` invariant unit tests:
  `run_failed` forces fail, an all-`run_failed` suite is not a pass, an empty
  positive set is not a pass, and a negative false-positive fails.

## Task Commits

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 | RED — planted-regression gate tests + thresholds floors | `d541264` |
| 2 | GREEN — thresholds loader + gate + CLI non-zero exit | `cd48533` |
| 3 | ADR 0010 — exit-code + determinism-direction contract | `aad0186` |

## Verification

| Gate | Result |
| ---- | ------ |
| `uv run pytest tests/test_eval_thresholds.py` | 11 passed |
| `uv run pytest` (full suite) | 454 passed, 3 deselected |
| `uv run ruff check` | All checks passed |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| ADR 0010 present + mentions `determinism_stability` + exit `2` | PASS |

Offline gate results: the good handler (all metrics 1.0) → gate PASS, exit 0; the
regressed handler (hit@k 0.0 < 1.00 floor) → gate FAIL, exit 1 with the JSON
marking `hypothesis_hit_at_k` and overall failed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Strengthened the gate to fail on run_failed + empty
positive set, with explicit tests (closes a verified orchestrator finding)**
- **Found during:** Task 2, per the load-bearing directive carried into this
  plan. `SuiteResult` aggregate helpers exclude `run_failed`/`expect_no_incident`
  cases and an empty positive set averages to a vacuous `1.0` — so gating on the
  aggregates alone would let a total pipeline failure (all cases `run_failed`)
  exit 0 and PASS, defeating EVAL-03 and the "nothing disappears silently"
  invariant.
- **Fix:** `gate()` itself records `run_failed_cases`, `false_positive_cases`, and
  `no_positive_cases`; any of them forces `passed = False` regardless of the
  aggregates. Added `test_run_failed_case_forces_gate_fail`,
  `test_all_cases_run_failed_is_not_a_pass`, and
  `test_empty_positive_aggregate_is_not_a_pass`.
- **Files modified:** src/sift/eval/thresholds.py, tests/test_eval_thresholds.py
- **Commit:** `cd48533` (impl), `d541264` (tests)

**2. [Rule 3 - Blocking] Modified report.py (not in the plan's files_modified)**
- **Issue:** The must-have "`--json` output includes the pass/fail verdict per
  metric and the overall gate result" requires the gate to live inside the single
  JSON document; the plan listed only thresholds.toml/thresholds.py/cli.py.
- **Fix:** Added an optional `gate` argument to both `render_text_table` and
  `render_json_table` (backwards-compatible, `None` keeps Plan 02 behaviour) so
  the gate verdict is threaded through the one canonical output rather than
  duplicated in the CLI.
- **Files modified:** src/sift/eval/report.py
- **Commit:** `cd48533`

**3. [Rule 3 - Blocking] Added a `--thresholds` CLI option**
- **Issue:** The plan mentioned it "if trivially cheap". It is, and it lets the
  tests pin the floors by absolute path independent of cwd.
- **Fix:** `--thresholds` defaulting to `eval/thresholds.toml`.
- **Files modified:** src/sift/cli.py
- **Commit:** `cd48533`

## Known Stubs

None. `CaseResult.judge_score` remains a reserved advisory field (Plan 05, D-08)
and is deliberately never consulted by the gate.

## Notes for Downstream Plans

- **Plan 04 (full suite):** adding the 5 remaining cases (incl. `expect_no_incident`
  negatives) flows straight through the gate — a negative false-positive already
  fails it, and the positive aggregates now always have real cases so the
  vacuous-1.0 guard stays dormant in normal operation.
- **Plan 05 (judge):** populate `CaseResult.judge_score` advisory-only; `gate()`
  must continue to ignore it (asserted by the judge-never-gates contract in ADR
  0010).

## Self-Check: PASSED

- eval/thresholds.toml, src/sift/eval/thresholds.py,
  docs/decisions/0010-eval-exit-codes.md, tests/test_eval_thresholds.py — FOUND
- Commits d541264, cd48533, aad0186 — FOUND in git log
- Full gate (ruff + pyright + 454-test pytest) — green
