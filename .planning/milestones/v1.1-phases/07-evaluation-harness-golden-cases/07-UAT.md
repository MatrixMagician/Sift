---
status: passed
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
  exit code (advisory-only, D-08).
awaiting: none — passed

## Tests

### 1. Live judge round-trip against the local model
expected: |
  `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip`
  passes against Lemonade Server — real model returns a parseable JudgeScore
  in [0.0, 1.0], surfaced in the --judge column, exit code unchanged.
result: |
  PASSED 2026-07-19. Gap plan 07-06 fixed the blocker (the autouse `_no_network`
  guard now exempts `@pytest.mark.live` tests; the default suite stays fully
  socket-blocked). `sift doctor` confirmed the generation endpoint live, then
  `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip`
  ran GREEN against Lemonade :13305 (real Qwen3 chat model): a parseable
  JudgeScore surfaced in the --judge column and the exit code was unaffected.
  D-08 (advisory / never-gates) confirmed against a real model, not just mocks.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

### Gap 1: `_no_network` autouse guard blocks `@pytest.mark.live` tests — RESOLVED
- **Resolution:** Closed by gap plan 07-06 (commits d4075d7 RED, 1861e8c GREEN,
  3c6f77c lock-in). `_no_network` now early-returns without patching
  `socket.connect` when a test carries the `live` marker; every unmarked test
  still raises the network-forbidden RuntimeError, so the default suite is
  byte-for-byte as socket-blocked as before (466 passed, ruff clean, pyright
  0/0/0). The live round-trip is now runnable and passes.
