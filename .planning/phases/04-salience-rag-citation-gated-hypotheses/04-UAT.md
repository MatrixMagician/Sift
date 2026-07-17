---
status: testing
phase: 04-salience-rag-citation-gated-hypotheses
source: [04-VERIFICATION.md]
started: 2026-07-17T00:00:00Z
updated: 2026-07-17T00:00:00Z
---

## Current Test

number: 1
name: Live llama-server constrained-decoding round-trip accepts the HypothesisSet schema ($defs/$ref)
expected: |
  Running `sift analyze <case>` against a real `llama-server -m <model>` (or Lemonade GGUF)
  performing schema-constrained decoding, on the first golden case: the server accepts the
  response_format `{"type":"json_schema","schema":{…$defs…}}` and returns schema-valid JSON on
  the FIRST try (no repair round-trip). If the server 400s on $defs/$ref, the run must still
  degrade gracefully (exit 3, raw output persisted) rather than crash — the automated backstop,
  which is already covered by tests.
awaiting: user response

## Tests

### 1. Live llama-server constrained-decoding round-trip accepts the HypothesisSet schema
expected: |
  Point Sift at a live constrained-decoding server and run `sift analyze` on the first golden
  case in a freshly created, isolated case directory. Confirm EITHER (a) schema-valid JSON on the
  first attempt with exit 0 and 100% citation validity, OR (b) if the build rejects local
  $defs/$ref, the run degrades to exit 3 with raw output persisted and marked degraded — never a
  crash. Either outcome passes: the load-bearing anti-hallucination pipeline (validate → one
  repair → degrade, citation gate) is the automated backstop and is fully covered by
  tests/test_hypothesise.py.
why_manual: |
  Requires a real local inference server with constrained decoding; the zero-network-in-tests
  invariant forbids automating a live HTTP round-trip. This is the single manual-only item
  declared in 04-VALIDATION.md — a confirmation that constrained decoding actively engages, NOT a
  load-bearing gap.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
