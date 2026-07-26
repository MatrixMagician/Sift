---
status: testing
phase: 18-eu-stack-facts-into-sift-analyze
source: [18-VERIFICATION.md]
started: 2026-07-26T16:30:00Z
updated: 2026-07-26T16:30:00Z
---

## Current Test

number: 1
name: End-to-end narration quality on the real capture
expected: |
  Ingest `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` into a case and run
  `uv run sift analyze <case>` against a live local inference endpoint. Then confirm:

  (a) the eu-stack fact block appears in the generated report's evidence;
  (b) its figures match `uv run sift eustack <case>` output for the same case;
  (c) the D-10 suppression statement is present — this capture carries no header timestamp,
      so it is a multi-dump case on the unverified filename-sort ordering path, and no
      progression delta figure may appear anywhere;
  (d) every `[evt:]` id cited in the resulting hypotheses resolves via `uv run sift show events`.
awaiting: user response

## Tests

### 1. End-to-end narration quality on the real capture

expected: |
  (a) eu-stack fact block present in the report evidence;
  (b) figures match `sift eustack` output for the same case;
  (c) D-10 suppression statement present, no delta figure anywhere (capture has no header
      timestamp → unverified dump order);
  (d) every cited `[evt:]` id resolves via `sift show events`.
why_human: |
  Requires a live local inference endpoint (llama.cpp `llama-server` or Lemonade Server).
  The default test suite is socket-blocked per ADR 0002, and LLM prose/narration quality is not
  assertable by automated means. This is the sole Manual-Only Verification row in
  18-VALIDATION.md; no executor or verifier had an endpoint available.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
