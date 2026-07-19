---
phase: 07-evaluation-harness-golden-cases
plan: 04
subsystem: eval
tags: [eval-harness, golden-case, offline, tdd, mixed-timezone, negative-case]
requires: [eval-package, sift-eval-command, truth-schema, golden-case-memory-watermark]
provides: [golden-suite-complete, golden-case-smtp, golden-case-thread-pool, golden-case-disk-full, golden-case-dependency-timeout-mixed-tz, golden-case-negative-no-incident]
affects:
  - eval/cases/
  - tests/
tech-stack:
  added: []
  patterns:
    - frozen-truth-yaml-ground-truth
    - isolated-single-case-suite-for-machinery-tests
    - offline-mocktransport-seam
    - negative-case-no-confident-hypothesis-predicate
key-files:
  created:
    - eval/cases/smtp-rejection-storm/input/mail.log
    - eval/cases/smtp-rejection-storm/truth.yaml
    - eval/cases/smtp-rejection-storm/README.md
    - eval/cases/thread-pool-exhaustion/input/app.log
    - eval/cases/thread-pool-exhaustion/truth.yaml
    - eval/cases/thread-pool-exhaustion/README.md
    - eval/cases/disk-full/input/system.log
    - eval/cases/disk-full/truth.yaml
    - eval/cases/disk-full/README.md
    - eval/cases/dependency-timeout-mixed-tz/input/node-a.log
    - eval/cases/dependency-timeout-mixed-tz/input/node-b.log
    - eval/cases/dependency-timeout-mixed-tz/truth.yaml
    - eval/cases/dependency-timeout-mixed-tz/README.md
    - eval/cases/negative-no-incident/input/app.log
    - eval/cases/negative-no-incident/truth.yaml
    - eval/cases/negative-no-incident/README.md
    - tests/test_eval_cases.py
  modified:
    - tests/_eval_fixtures.py
    - tests/test_eval_harness.py
    - tests/test_eval_thresholds.py
decisions:
  - "The committed golden suite is exactly six cases (D-01): five SPEC §6 exemplars plus the negative case, with quiet-cause and mixed-timezone layered onto two of the exemplars rather than a seventh case."
  - "Each truth.yaml is authored to the planted scenario BEFORE any prompt tuning (D-02) — frozen ground truth; a real regression must fail rather than be accommodated."
  - "The offline machinery/gate tests were decoupled onto an isolated single-case temp suite (single_case_suite helper) so growing eval/cases from one to six cases does not break exit-code assertions that depend on the memory-watermark-only good handler."
  - "The negative case sets expect_no_incident: true with empty required_evidence/acceptable_keywords and is scored by negative_case_pass (zero or all-low-confidence hypotheses), excluded from the positive retrieval/hit@k aggregates (Pitfall 5)."
metrics:
  duration: ~9 min
  completed: 2026-07-19
  tasks: 2
  files: 20
status: complete
---

# Phase 7 Plan 04: Complete the Golden-Case Suite Summary

Authored the remaining five golden cases so the committed suite is the complete
six required by D-01 — every SPEC §6 exemplar plus the three ROADMAP-mandated
shapes (quiet-cause, mixed-timezone, negative) — and added a suite-validation
test proving each `truth.yaml` is schema-valid and frozen and that the negative
case scores correctly offline by its no-confident-hypothesis predicate.
EVAL-01 / ROADMAP SC1 satisfied in full.

## What Was Built

- **Four positive golden cases** — `smtp-rejection-storm` (relay 554/550 5.7.1
  rejection storm backing up the outbound queue), `thread-pool-exhaustion`
  (fixed 32-thread pool saturating into `RejectedExecutionException`),
  `disk-full` (a `/data` volume filling to `ENOSPC` and `507`s), and
  `dependency-timeout-mixed-tz` (upstream payment-gateway outage causing
  order-service timeouts). Each ships `input/` synthetic genericlog artefacts,
  a frozen `truth.yaml` (`root_cause` + `required_evidence` regexes +
  `acceptable_keywords` + `expect_no_incident: false`), and a British-English
  README, mirroring the existing `memory-watermark-cascade` case.
- **`dependency-timeout-mixed-tz` (mixed-timezone shape, D-01)** — two node
  logs at different UTC offsets: `node-b` (payment-gateway) at `+05:30` and
  `node-a` (order-service) at `-05:00`. The gateway outage
  (`17:30:02+05:30` = `12:00:02Z`) precedes the order-service timeout
  (`07:00:28-05:00` = `12:00:28Z`) **only after** INGST-11 UTC normalisation;
  by naïve wall-clock the effect (`07:00`) would appear before the cause
  (`17:30`), inverting causality. Verified the normalised ordering directly.
- **`negative-no-incident` (negative shape, D-04)** — a healthy steady-state
  log (200s, passing health checks, routine cache refreshes across two nodes)
  with `expect_no_incident: true` and empty evidence/keywords; a confident
  root cause here is a false positive.
- **`tests/test_eval_cases.py`** — suite-level validation: the suite is exactly
  the six D-01 cases, every `truth.yaml` loads through `load_truth` (T-07-01
  schema guarantee), the three special shapes are present (quiet-cause,
  mixed-tz asserted via the two differing offsets, negative), and the negative
  case run offline (empty-reply `MockTransport`, zero sockets) yields
  `negative_case_pass is True` and does not drag the positive hit@k aggregate.

## Task Commits

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 | Author the four positive golden cases | `6cfc713` |
| 2 (RED) | Failing suite-validation test | `2bff524` |
| 2 (GREEN) | negative-no-incident case + passing test | `f90cbf3` |

## Verification

| Gate | Result |
| ---- | ------ |
| `uv run pytest` | 458 passed, 3 deselected |
| `uv run pytest tests/test_eval_cases.py` | 4 passed |
| `uv run ruff check` | All checks passed |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| `ls -d eval/cases/*/` | exactly 6 directories |
| Mixed-tz UTC ordering | cause `12:00:02Z` before effect `12:00:28Z` (would invert by wall-clock) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Decoupled the offline machinery/gate tests from suite growth**
- **Found during:** Task 1 — after adding the four positive cases, four
  existing tests (`test_eval_harness::test_eval_offline_prints_metric_row`,
  `::test_eval_offline_json_is_parseable`,
  `test_eval_thresholds::test_clean_suite_exits_zero`,
  `::test_clean_json_gate_passes_per_metric`) failed. They invoke
  `sift eval --suite eval/cases` with the memory-watermark-only good handler,
  which returns the same memory hypothesis for every case; with five positive
  cases the aggregate `hypothesis_hit_at_k` dropped to 0.4 (< 1.00 floor) so
  the gate exited 1 instead of 0.
- **Fix:** Added a `single_case_suite(tmp_path)` helper to
  `tests/_eval_fixtures.py` that copies one case into an isolated temp suite,
  and pointed those four machinery/gate tests at it. They assert machinery
  (metric row, parseable JSON, exit-code contract) — not real-model quality
  over the whole suite (Plan 02's stated intent) — so a one-case copy is the
  correct scope and keeps them independent of the suite's breadth. The harness,
  metrics, gate and CLI were **not** touched (scope guard respected); only the
  offline test wiring changed.
- **Files modified:** tests/_eval_fixtures.py, tests/test_eval_harness.py, tests/test_eval_thresholds.py
- **Commit:** `6cfc713`

## Notes for Downstream Plans

- **Plan 05 (judge):** the advisory LLM-as-judge now has six committed cases to
  score; `CaseResult.judge_score` remains reserved and never gates.
- **Live UAT:** the frozen thresholds intend real regressions to surface when
  `sift eval` runs against the weak local model. If a case cannot clear a floor
  live, that is the intended signal — do not weaken `truth.yaml` or the
  thresholds; investigate prompt/pipeline quality instead.

## Self-Check: PASSED

- All 17 created files + 3 modified files — FOUND on disk
- All 3 task commits (6cfc713, 2bff524, f90cbf3) — FOUND in git log
- Full gate (ruff + pyright + 458-test pytest) — green
- Suite is exactly six cases; mixed-tz UTC ordering verified non-inverting
