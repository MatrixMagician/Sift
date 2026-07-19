---
phase: 07-evaluation-harness-golden-cases
plan: 02
subsystem: eval
tags: [eval-harness, metrics, golden-case, cli, offline, tdd]
requires: [pyyaml-runtime-dependency]
provides: [eval-package, sift-eval-command, truth-schema, golden-case-memory-watermark]
affects:
  - src/sift/eval/
  - src/sift/cli.py
  - eval/cases/
  - tests/
tech-stack:
  added: []
  patterns:
    - pure-metric-functions
    - reuse-analyze-pipeline-seams
    - safe-yaml-load-plus-pydantic
    - offline-mocktransport-seam
    - determinism-stability-over-drift
key-files:
  created:
    - src/sift/eval/__init__.py
    - src/sift/eval/truth.py
    - src/sift/eval/metrics.py
    - src/sift/eval/runner.py
    - src/sift/eval/report.py
    - eval/cases/memory-watermark-cascade/input/app.log
    - eval/cases/memory-watermark-cascade/truth.yaml
    - eval/cases/memory-watermark-cascade/README.md
    - tests/_eval_fixtures.py
    - tests/test_eval_truth.py
    - tests/test_eval_harness.py
  modified:
    - src/sift/cli.py
decisions:
  - "truth.yaml is parsed with yaml.safe_load only (never yaml.load) then validated by a Pydantic Truth model with extra=forbid (T-07-01)."
  - "The fourth metric is expressed as determinism_stability (higher-better); the report DISPLAYS drift = 1 - stability so a single value>=floor gate covers all four (Plan 03)."
  - "Negative (expect_no_incident) cases are scored by the no-confident-hypothesis predicate and excluded from the retrieval/hit@k aggregates (Pitfall 5)."
  - "run_case reuses cli._ingest + the analyze triage constants verbatim (the sanctioned seams); the private-symbol imports carry narrow pyright ignores + a lazy import to break the cli<->eval cycle."
  - "Pipeline stdout (ingest coverage) and stderr (store migration notes) are contained inside run_case so the metric table / --json is the only thing sift eval emits."
metrics:
  duration: ~11 min
  completed: 2026-07-19
  tasks: 3
  files: 12
status: complete
---

# Phase 7 Plan 02: Eval Harness Walking Skeleton Summary

The first vertical slice of the golden-case harness: `sift eval` now runs one
committed golden case end-to-end **entirely offline** (fake OpenAI-compatible
client via MockTransport) through the real ingest → cluster → hypothesise
pipeline, scores the four quality metrics against a frozen `truth.yaml`, and
prints a plain-text table (or `--json`). Exit is 0 for now — the threshold gate
and non-zero regression exit arrive in Plan 03.

## What Was Built

- **`src/sift/eval/truth.py`** — the `Truth` Pydantic model (`extra="forbid"`)
  plus `load_truth`, which parses with `yaml.safe_load` ONLY (a custom-tag
  payload is refused, never executed — the T-07-01 anti-RCE guarantee).
- **`src/sift/eval/metrics.py`** — the four pure metrics
  (`retrieval_hit_rate`, `hypothesis_hit_at_k`, `citation_validity_rate`,
  `determinism_stability`) plus `negative_case_pass`, and the frozen
  `CaseResult` / `SuiteResult` records with positive-case aggregate helpers.
  `citation_validity_rate` reads the persisted gate verdict
  (`StoredHypothesis.citations_valid`) — it never re-derives the citation gate.
- **`src/sift/eval/runner.py`** — `run_case` drives one golden case through a
  temp `case.db` (tempfile-managed, never the user data dir — T-07-06), reusing
  `cli._ingest` + `cluster_and_label` + `hypothesise`. Determinism (D-06, N=2)
  runs the pipeline on fresh copies of the post-ingest db and compares
  `render_json` + `normalise_for_determinism` output (the M6 seam, never a
  hand-rolled field-stripper). A transport/parse failure surfaces as a
  `run_failed` `CaseResult` rather than crashing the suite.
- **`src/sift/eval/report.py`** — `render_text_table` (British-English, one row
  per case + a suite-aggregate row, determinism column displays drift) and
  `render_json_table` (canonical key-sorted JSON, mirrors `render_json`).
- **`src/sift/cli.py::eval_()`** — filled the stub: `sift eval [--suite <dir>]
  [--json] [--i-know-what-im-doing] [--model]`. Builds the client through the
  `_make_http_client` seam (EVAL-05), iterates the cases, prints the table. A
  missing/invalid `--suite` is a usage error (exit 2).
- **Golden case `eval/cases/memory-watermark-cascade/`** — a synthetic
  quiet-cause scenario (loud OOM-killer symptom, quiet early high-watermark
  cause), with `input/app.log`, a frozen `truth.yaml`, and a README.
- **Tests** — `tests/_eval_fixtures.py` (offline MockTransport handler +
  `patch_http`), `tests/test_eval_truth.py` (schema safe-parse + metric units),
  `tests/test_eval_harness.py` (offline E2E: exit 0, metric row, parseable JSON,
  bad-suite exit 2). Zero sockets — the autouse `_no_network` guard stays green.

## Task Commits

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 | RED — offline harness tests + golden case | `c3ecb87` |
| 2 | GREEN — Truth loader + pure metric functions | `e1a0f1a` |
| 3 | GREEN — runner + report + fill `sift eval` CLI | `1e12d76` |

## Verification

| Gate | Result |
| ---- | ------ |
| `uv run pytest` | 443 passed, 3 deselected |
| `uv run pytest tests/test_eval_truth.py tests/test_eval_harness.py` | 19 passed |
| `uv run ruff check` | All checks passed |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| Offline `sift eval --suite eval/cases` (via CliRunner) | exit 0, metric row for memory-watermark-cascade, `--json` parses; zero sockets |

Offline metrics for the good handler: retrieval_hit_rate = 1.0,
hypothesis_hit_at_k = 1.0, citation_validity_rate = 1.0,
determinism_stability = 1.0 — as intended for a keyword-hitting, empty-citation,
byte-identical fixture (this validates the *machinery*, not real model quality,
per RESEARCH Pitfall 1).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Contained pipeline stdout/stderr inside run_case**
- **Found during:** Task 3 (the `--json` test failed — `_ingest` coverage lines
  and store migration notes leaked into `result.output`, breaking `json.loads`).
- **Fix:** Wrapped all per-case pipeline work in `redirect_stdout` +
  `redirect_stderr` so the metric table / JSON is the only thing `sift eval`
  emits. In real use only stdout is piped, but containing both keeps the harness
  output clean regardless of the caller.
- **Files modified:** src/sift/eval/runner.py
- **Commit:** `1e12d76`

**2. [Rule 3 - Blocking] Narrow pyright ignores on the sanctioned cli seams**
- **Issue:** Reusing `cli._ingest` and the analyze triage constants
  (`_DEFAULT_TOP_CLUSTERS`, `_TRIAGE_CTX_FALLBACK`, `_TRIAGE_RESERVE_OUT`) — the
  exact reuse the plan mandates — trips pyright `reportPrivateUsage`.
- **Fix:** Lazy imports (also breaks a cli↔eval import cycle) with narrow
  `# pyright: ignore[reportPrivateUsage]` comments and a rationale, rather than
  renaming cli internals (out of scope).
- **Files modified:** src/sift/eval/runner.py
- **Commit:** `1e12d76`

## Known Stubs

`CaseResult.judge_score` is `None` and unused — a reserved field for the
advisory LLM-as-judge added in Plan 05 (D-08). Not a blocking stub: it never
enters any metric or gate, and the plan's goal (four keyword metrics printed
offline) is fully achieved without it.

## Notes for Downstream Plans

- **Plan 03 (gate):** consume `SuiteResult.mean_*` aggregates and gate on
  `determinism_stability >= floor` (not drift); the exit-code contract belongs
  in the `eval_()` CLI command (currently exit 0). Add `eval/thresholds.toml` +
  a new ADR for the exit codes.
- **Plan 04 (full suite):** add the remaining 5 cases under `eval/cases/`;
  `run_case` and the aggregates already handle `expect_no_incident` negatives.
- **Plan 05 (judge):** populate `CaseResult.judge_score` advisory-only;
  `render_*_table` already carry the field through.

## Self-Check: PASSED

- All 11 created files — FOUND on disk
- All 3 task commits (c3ecb87, e1a0f1a, 1e12d76) — FOUND in git log
- Full gate (ruff + pyright + 443-test pytest) — green
