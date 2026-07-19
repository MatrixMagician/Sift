---
status: testing
phase: 07-evaluation-harness-golden-cases
source: [07-VERIFICATION.md]
started: "2026-07-19T10:25:35Z"
updated: "2026-07-19T10:25:35Z"
---

## Current Test

number: 1
name: Live judge round-trip against the local model
expected: |
  With Lemonade Server running (127.0.0.1:13305, a llamacpp/flm-recipe chat
  model loaded), the real model returns a parseable JudgeScore in [0.0, 1.0]
  that appears in the `sift eval --judge` column and does NOT change the
  exit code (advisory-only, D-08). The advisory/never-gates/degrade-on-bad-
  output contract is already fully proven offline; only the real-model parse
  is unobserved because the default suite is socket-blocked by design (D-09).
awaiting: user response

## Tests

### 1. Live judge round-trip against the local model
expected: |
  `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip`
  passes against Lemonade Server — real model returns a parseable JudgeScore
  in [0.0, 1.0], surfaced in the --judge column, exit code unchanged.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
