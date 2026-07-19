---
phase: 07-evaluation-harness-golden-cases
plan: 05
subsystem: eval
tags: [eval-harness, llm-as-judge, advisory, cli, offline, tdd, prompt-template]
requires: [eval-package, sift-eval-command, eval-threshold-gate, inference-client-chat]
provides: [eval-judge-advisory, sift-eval-judge-flag, judge-prompt-template]
affects:
  - src/sift/prompts/judge.md
  - src/sift/eval/judge.py
  - src/sift/eval/runner.py
  - src/sift/eval/report.py
  - src/sift/cli.py
  - tests/
tech-stack:
  added: []
  patterns:
    - versioned-prompt-template-importlib-resources
    - never-crash-on-model-output-degrade-to-none
    - sole-http-boundary-reuse-no-new-path
    - advisory-metric-never-gates
    - schema-keyed-offline-fake-distinguisher
key-files:
  created:
    - src/sift/prompts/judge.md
    - src/sift/eval/judge.py
    - tests/test_eval_judge.py
  modified:
    - src/sift/eval/runner.py
    - src/sift/eval/report.py
    - src/sift/cli.py
decisions:
  - "The judge reuses the sole HTTP boundary InferenceClient.chat (constrained decoding when honoured) — no new HTTP path, no framework (LangChain/instructor forbidden by CLAUDE.md)."
  - "judge_case degrades to None on any transport/parse/validation error (never-crash-on-model-output idiom); a malformed judge reply can neither crash the run nor alter the exit code."
  - "The judge is advisory-only (D-08): CaseResult.judge_score is populated and reported, but the gate + typer.Exit stay computed from keyword metrics ONLY — a low/None judge score on a keyword-passing suite still exits 0."
  - "The judge prompt is a versioned template (src/sift/prompts/judge.md) loaded via importlib.resources, mirroring hypothesise._load_triage_template — tuning it needs no Python change (CLI-02)."
  - "Default (no --judge) output is byte-identical to Plan 03: the text table gains a judge column only under show_judge; the JSON already carried the reserved judge_score field (null)."
  - "The live judge round-trip is @pytest.mark.live, excluded from the default socket-blocked suite (D-09); the offline judge fake recognises the judge chat call by the unique \"justification\" property in its response_format schema, not prompt wording."
metrics:
  duration: ~15 min
  completed: 2026-07-19
  tasks: 2
  files: 6
status: complete
---

# Phase 7 Plan 05: Advisory LLM-as-Judge Summary

`sift eval --judge` adds an opt-in, advisory second opinion on hypothesis
quality: the SAME local model (via the existing `InferenceClient.chat`) grades
how well a case's generated hypotheses match its frozen ground-truth
`root_cause`, and the score is reported ALONGSIDE — never instead of, never
gating — the keyword metrics. Off by default; a default run is byte-identical to
Plan 03. This closes EVAL-04 / ROADMAP SC4 and completes Phase 7.

## What Was Built

- **`src/sift/prompts/judge.md`** — a versioned, British-English judge prompt
  (CLI-02): grade hypotheses-vs-`root_cause`, return a strict
  `{score: 0.0–1.0, justification}` JSON object. Tuning it requires no Python
  change; its header states the advisory, never-gates contract.
- **`src/sift/eval/judge.py`** — `load_judge_template()` (importlib.resources,
  mirroring `hypothesise._load_triage_template`), a Pydantic frozen-dataclass
  `JudgeScore` (score constrained to `[0.0, 1.0]`), and
  `judge_case(client, truth, hypotheses) -> JudgeScore | None`. It assembles the
  prompt, calls the sole HTTP boundary `InferenceClient.chat` (llama.cpp
  `response_format.schema` constrained decoding when honoured), validates the
  reply with a `TypeAdapter`, and **degrades to `None` on any transport / parse /
  validation error** — the never-crash-on-model-output idiom. It adds no new HTTP
  path (grep-confirmed: no `httpx.Client` construction) and never imports or
  touches the threshold/gate logic.
- **`src/sift/eval/runner.py::run_case`** — new keyword-only `judge: bool = False`
  param; when set, the first run's persisted hypotheses are graded and the score
  attached to `CaseResult.judge_score`. Because `judge_case` degrades to `None`,
  the judge can never turn a scored case into a `run_failed` one.
- **`src/sift/eval/report.py::render_text_table`** — an optional `show_judge`
  advisory column (value, or `n/a` when the judge degraded) plus an explicit
  "(judge column is advisory — it never affects the gate)" note. Off, the output
  is byte-identical to Plan 03; the JSON renderer already threaded `judge_score`.
- **`src/sift/cli.py::eval_()`** — the opt-in `--judge` flag (default False). It
  passes `judge=judge` to `run_case` and `show_judge=judge` to the text
  renderer. Critically, the threshold `gate` + `typer.Exit(1)` stay computed from
  the keyword metrics + anti-vacuity predicate ONLY — the judge value never
  enters the gate (D-08).
- **`tests/test_eval_judge.py`** — offline (zero sockets, MockTransport seam)
  proving: judge OFF by default (no judge column, `judge_score` null in JSON); ON
  it reports a score alongside; a deliberately LOW judge grade on a
  keyword-passing suite still exits 0; a malformed judge reply degrades to `n/a`
  without a traceback; the `--json` per-case `judge_score` carries the value while
  `gate.passed` stays True. Plus a `@pytest.mark.live` real-model round-trip
  excluded from the default suite. The offline fake recognises the judge call by
  the unique `"justification"` property in its `response_format` schema.

## Task Commits

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 | Judge prompt template + judge module (advisory, never raises) | `b9ce6f0` |
| 2 (RED) | Failing tests for `sift eval --judge` | `81aa6bf` |
| 2 (GREEN) | Wire `--judge` into `sift eval` + tests green | `9f78c62` |

## Verification

| Gate | Result |
| ---- | ------ |
| `uv run pytest tests/test_eval_judge.py` | 6 passed, 1 deselected (live) |
| `uv run pytest` (full, socket-blocked) | 464 passed, 4 deselected |
| `uv run ruff check` | All checks passed |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| Offline `sift eval --judge` (CliRunner) | judge column shows 0.85 advisory, GATE PASS, exit 0; zero sockets |

Offline the judge grade is a property of the scripted fake, not real model
quality (RESEARCH Pitfall 1) — the load-bearing assertion is that a low/malformed
judge reply never changes the exit code.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Offline judge fake keyed on the schema's `justification`
property rather than walking nested `Any` JSON**
- **Found during:** Task 2 GREEN — the first fake distinguished the judge chat
  call by walking `payload["response_format"]["schema"]["properties"]`, which
  tripped pyright strict (`reportUnknownMemberType` on the untyped `json.loads`
  result, cascading to 60 errors).
- **Fix:** Recognise the judge call by the `"justification"` substring in the
  decoded request body — a property unique to the judge schema (the generation
  call's HypothesisSet schema has none). Type-clean (`str in str`), robust to
  judge.md edits, and still schema-based rather than prompt-wording-based.
- **Files modified:** tests/test_eval_judge.py
- **Commit:** `9f78c62`

**2. [Rule 3 - Blocking] Modified report.py (not in the plan's files_modified)**
- **Issue:** The must-have "reports a judge score ALONGSIDE the keyword scores"
  requires the text table to carry an advisory judge column; the plan listed only
  judge.md/judge.py/cli.py/tests.
- **Fix:** Added a backward-compatible `show_judge` argument to
  `render_text_table` (default False keeps Plan 03 output byte-identical) plus the
  advisory note. The JSON renderer needed no change — Plan 02 already reserved and
  threaded `judge_score`.
- **Files modified:** src/sift/eval/report.py
- **Commit:** `9f78c62`

## Known Stubs

None. `CaseResult.judge_score` — reserved as a stub in Plans 02/03 — is now
populated by the advisory judge and deliberately never consulted by the gate.

## Notes for Downstream

- Phase 7 is complete (all 5 plans executed). The judge is the only optional,
  live-dependent slice: its real-model behaviour is covered by the
  `@pytest.mark.live` test, exercised via `uv run pytest -m live
  tests/test_eval_judge.py` (or `sift eval --judge` against the local model) — a
  manual UAT item, since the default suite is socket-blocked by design (D-09).

## Self-Check: PASSED

- src/sift/prompts/judge.md, src/sift/eval/judge.py, tests/test_eval_judge.py,
  07-05-SUMMARY.md — FOUND on disk
- Commits b9ce6f0, 81aa6bf, 9f78c62 — FOUND in git log
- Full gate (ruff + pyright + 464-test pytest) — green
