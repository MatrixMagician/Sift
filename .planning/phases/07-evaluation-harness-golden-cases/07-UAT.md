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
  exit code (advisory-only, D-08).
awaiting: fix (see Gaps — conftest `_no_network` blocks live-marked tests)

## Tests

### 1. Live judge round-trip against the local model
expected: |
  `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip`
  passes against Lemonade Server — real model returns a parseable JudgeScore
  in [0.0, 1.0], surfaced in the --judge column, exit code unchanged.
result: |
  ISSUE — the test is un-runnable as written. Lemonade was confirmed UP on
  127.0.0.1:13305, but the CLI run raised:
  "RuntimeError: Network access is forbidden in tests (zero-network-in-tests
  rule). Inject a fake instead." The autouse `_no_network` fixture
  (tests/conftest.py:34) monkeypatches `socket.socket.connect` for EVERY test
  with no exemption for the `live` marker, so `-m live` never reaches the real
  server. The judge feature itself is proven correct offline (6 tests:
  advisory, degrades on bad output, never changes the exit code).

## Summary

total: 1
passed: 0
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

### Gap 1: `_no_network` autouse guard blocks `@pytest.mark.live` tests
- **Symptom:** `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip`
  raises `RuntimeError: Network access is forbidden in tests` and fails on an
  empty CLI output, even with Lemonade up on :13305.
- **Root cause:** `tests/conftest.py:34` `_no_network` is `autouse=True` and
  patches `socket.socket.connect` unconditionally. The `live` marker
  (pyproject.toml:52) is meant for real-inference-server integration tests, but
  the guard has no carve-out for it, so live-marked tests can never open a
  socket. The live round-trip has therefore never actually been observed.
- **Scope:** test harness only — NOT a judge-feature defect. The zero-network
  invariant for the default suite must stay intact.
- **Fix:** make `_no_network` exempt tests carrying the `live` marker
  (`request.node.get_closest_marker("live")` -> yield without patching). Then the
  default/non-live suite stays socket-blocked exactly as before, and
  `uv run pytest -m live` can do the real round-trip. Re-run the live test to
  confirm the JudgeScore surfaces and the exit code is unaffected.
