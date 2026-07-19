---
phase: 07-evaluation-harness-golden-cases
verified: 2026-07-19T00:00:00Z
status: passed
score: 12/12 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification_resolved:
  - test: "Run `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip` with Lemonade Server (127.0.0.1:13305) serving a llamacpp/flm-recipe chat model."
    expected: "The advisory judge round-trips against the real local model, returns a parseable JudgeScore in [0.0,1.0], and the score appears in the --judge report column WITHOUT altering the exit code."
    result: "PASSED 2026-07-19 — after gap plan 07-06 exempted @pytest.mark.live from the _no_network guard, the live round-trip ran green against Lemonade :13305 (real Qwen3 chat model): parseable JudgeScore surfaced in the --judge column, exit code unaffected. D-08 advisory-never-gates confirmed against a real model."
---

# Phase 7: Evaluation Harness & Golden Cases Verification Report

**Phase Goal:** ≥5 golden incidents, metric table, CI thresholds, optional LLM-as-judge — turn raw diagnostics through the real pipeline and score output against frozen ground truth, with a CI-friendly non-zero exit on regression.
**Verified:** 2026-07-19
**Status:** passed — the sole human-verification item (live judge round-trip) was confirmed green against Lemonade :13305 after gap plan 07-06 unblocked live-marked tests.
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | `sift eval --suite` runs golden cases end-to-end offline via the REAL pipeline and prints a metric row | ✓ VERIFIED | `runner.run_case` imports & calls `cli._ingest`, `cluster_and_label`, `hypothesise`, `render_json`/`normalise_for_determinism` — no reimplementation. `eval_` calls `run_case` per case. Offline harness tests green. |
| 2  | Metric row reports retrieval hit rate, hypothesis hit@k, citation validity rate, determinism drift (EVAL-02) | ✓ VERIFIED | `metrics.py` defines `retrieval_hit_rate`, `hypothesis_hit_at_k`, `citation_validity_rate`, `determinism_stability` (+ `negative_case_pass`); `report.render_text_table` renders them; drift = 1 − stability displayed. |
| 3  | `--json` emits a machine-readable metric table | ✓ VERIFIED | `report.render_json_table(suite, gate)`; `eval_` prints it under `--json`; `GateResult.as_dict` carries per-metric verdicts + overall result. |
| 4  | truth.yaml parsed with `yaml.safe_load` + Pydantic `extra="forbid"`; typo'd key fails loudly (T-07-01) | ✓ VERIFIED | `truth.py` uses `yaml.safe_load` only; `Truth` model `ConfigDict(extra="forbid")`. Repo-wide scan: no `yaml.load`/`full_load`/`unsafe_load`/`Loader=` anywhere in src or tests. |
| 5  | Offline run opens zero sockets (EVAL-05) | ✓ VERIFIED | `conftest.py` autouse `_no_network` monkeypatches `socket.socket.connect` to raise; full suite (464 passed) runs with the guard active; `_make_http_client` seam injects MockTransport. |
| 6  | Committed golden suite = exactly 6 cases, each with input/, schema-valid frozen truth.yaml, README (EVAL-01, D-01: goal ≥5, 6 present) | ✓ VERIFIED | 6 dirs; all 6 `load_truth()` OK; each has README + non-empty input/. |
| 7  | `sift eval` exits non-zero on regression below `eval/thresholds.toml` (EVAL-03) | ✓ VERIFIED | `eval/thresholds.toml` present; `thresholds.gate()` compares each aggregate ≥ floor; `eval_` owns `if not gate_result.passed: raise typer.Exit(1)` — unsuppressible. |
| 8  | run_failed case OR empty positive aggregate OR negative false-positive forces gate FAILURE (not vacuous 1.0) — load-bearing | ✓ VERIFIED | Enforced in `gate()` itself (lines 111–127): `run_failed_cases`, `false_positive_cases`, `no_positive_cases` each break `passed`. All 4 named tests pass: `test_run_failed_case_forces_gate_fail`, `test_empty_positive_aggregate_is_not_a_pass`, `test_all_cases_run_failed_is_not_a_pass`, `test_negative_false_positive_forces_gate_fail`. |
| 9  | Negative case sets `expect_no_incident: true` and passes via `negative_case_pass` offline | ✓ VERIFIED | `negative-no-incident/truth.yaml` has `expect_no_incident: true`; loads with `no_incident=True`; `negative_case_pass` predicate + gate false-positive branch wired. |
| 10 | Mixed-timezone case has ≥2 node logs at different UTC offsets | ✓ VERIFIED | `dependency-timeout-mixed-tz/input/` has node-a.log (`-05:00`) and node-b.log (`+05:30`). |
| 11 | Opt-in `--judge` is advisory only — never changes exit code, degrades to None on malformed output (EVAL-04, D-08) | ✓ VERIFIED | `judge.py` `judge_case` catches `(httpx.HTTPError, ValueError)` → None; uses sole `InferenceClient.chat` boundary; gate/exit never reads judge score. Tests pass: `test_low_judge_score_never_changes_exit`, `test_malformed_judge_reply_degrades_not_crashes`, `test_default_run_has_no_judge_column`. |
| 12 | Judge prompt is a versioned template `src/sift/prompts/judge.md` (CLI-02) | ✓ VERIFIED | `judge.md` present, loaded via `importlib.resources`; header documents advisory/never-gates contract. |

**Score:** 12/12 truths verified (0 present, behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/sift/eval/truth.py` | Truth model + safe loader | ✓ VERIFIED | safe_load + extra=forbid |
| `src/sift/eval/metrics.py` | 4 metrics + negative_case_pass + Case/SuiteResult | ✓ VERIFIED | all present, mean_* aggregators |
| `src/sift/eval/runner.py` | run_case reusing real pipeline | ✓ VERIFIED | wraps cli._ingest/cluster/hypothesise |
| `src/sift/eval/report.py` | text + JSON metric table | ✓ VERIFIED | render_text_table / render_json_table |
| `src/sift/eval/thresholds.py` | load_thresholds + gate | ✓ VERIFIED | gate enforces 3 load-bearing invariants |
| `eval/thresholds.toml` | 4 floors | ✓ VERIFIED | tomllib binary-mode load |
| `src/sift/eval/judge.py` | advisory judge | ✓ VERIFIED | degrade-to-None, sole HTTP boundary |
| `src/sift/prompts/judge.md` | versioned prompt | ✓ VERIFIED | importlib.resources |
| `eval/cases/*` (6) | input/truth/README | ✓ VERIFIED | all 6 load & structured |
| `src/sift/cli.py eval_()` | --suite/--json/--judge + {0,1,2} exit | ✓ VERIFIED | gate drives Exit(1); usage errors Exit(2) |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `cli.eval_` | `runner.run_case` | per-case call, injected client via `_make_http_client` | ✓ WIRED |
| `runner.run_case` | real pipeline | `cli._ingest` + `cluster_and_label` + `hypothesise` | ✓ WIRED |
| `cli.eval_` | `thresholds.gate` | `gate(suite_result, floors)` → `Exit(1)` if not passed | ✓ WIRED |
| `judge_case` | `InferenceClient.chat` | sole HTTP boundary, no new path | ✓ WIRED |
| determinism metric | `render_json` + `normalise_for_determinism` | ADR 0008 seam reused | ✓ WIRED |

### Behavioural Spot-Checks / Named Tests

| Behaviour | Command | Result | Status |
| --------- | ------- | ------ | ------ |
| Full suite green | `uv run pytest -q` | 464 passed, 4 deselected | ✓ PASS |
| Lint | `uv run ruff check` | All checks passed | ✓ PASS |
| Types | `uv run pyright` | 0 errors, 0 warnings, 0 informations | ✓ PASS |
| Gate load-bearing invariants | `pytest -k "run_failed_case_forces_gate_fail or empty_positive_aggregate_is_not_a_pass or all_cases_run_failed_is_not_a_pass or negative_false_positive_forces_gate_fail"` | 4 passed | ✓ PASS |
| Judge advisory contract | `pytest -k "low_judge_score_never_changes_exit or malformed_judge_reply_degrades_not_crashes"` | 2 passed | ✓ PASS |
| Judge live round-trip | `pytest -m live ...test_judge_live_round_trip` | deselected (no live server) | ? SKIP → human |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| EVAL-01 | 07-01, 07-02, 07-04 | ≥5 golden cases (input/truth/README) | ✓ SATISFIED | 6 cases, all load |
| EVAL-02 | 07-02 | 4 metrics reported | ✓ SATISFIED | metrics.py + report |
| EVAL-03 | 07-03 | non-zero exit on regression | ✓ SATISFIED | gate + Exit(1) |
| EVAL-04 | 07-05 | optional LLM-as-judge alongside keyword scores | ✓ SATISFIED | judge.py + --judge |

All four Phase-7 requirement IDs (EVAL-01..04) appear in plan frontmatter and are marked Complete in REQUIREMENTS.md traceability — none orphaned. (EVAL-05 zero-network-in-tests was Phase 3; its invariant is re-confirmed green here.)

### Anti-Patterns Found

None blocking. No `TBD`/`FIXME`/`XXX` debt markers in phase files; no stub returns feeding user-visible output; no `yaml.load`/`full_load` anywhere; determinism metric reuses the canonical serialisation seam rather than a hand-rolled field-stripper.

### Human Verification Required

**1. Live judge round-trip (EVAL-04 real-model confirmation)**

- **Test:** `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip` with Lemonade Server (127.0.0.1:13305) serving a llamacpp/flm-recipe chat model.
- **Expected:** Judge round-trips against the real local model, returns a parseable JudgeScore in [0.0,1.0], appears in the `--judge` column, and does NOT change the exit code.
- **Why human:** Deselected `@pytest.mark.live` test needing a live model the socket-blocked suite cannot run. Advisory/never-gates/degrade behaviour is fully proven offline; only the real-model parse is unobserved.

### Gaps Summary

No gaps. The phase goal is achieved in code and offline tests: the harness drives raw diagnostics through the real ingest→cluster→hypothesise pipeline, scores against 6 frozen golden cases, reports a text+JSON metric table, and enforces a CI-friendly non-zero exit on regression. Critically, the previously-flagged aggregation risk is genuinely closed inside `gate()` — a `run_failed` case, an empty positive aggregate, and a negative false-positive each force a hard failure rather than a vacuous 1.0 pass — confirmed by four named tests, not merely by CLI wiring. The optional judge is advisory-only and cannot alter the exit code. The single outstanding item is a live-model manual UAT (the deselected `@pytest.mark.live` judge test), which is non-blocking for the harness goal.

---

_Verified: 2026-07-19_
_Verifier: Claude (gsd-verifier)_
