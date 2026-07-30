---
status: complete
phase: 18-eu-stack-facts-into-sift-analyze
source: [18-VERIFICATION.md]
started: 2026-07-26T16:30:00Z
updated: 2026-07-27T00:00:00Z
case: p18uat
---

## Current Test

_None — all tests passed._

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
result: [passed]
evidence: |
  Case `p18uat`, built at HEAD 9f55706 (post-CR-fix): 100.0% parse coverage on both dumps,
  7807 events, 84 template groups.

  (a) USER-CONFIRMED 2026-07-27 — fact block present in the report evidence, narration
      sensible, no invented progression figure. 2 hypotheses, both citation-status OK.
  (b) MACHINE-VERIFIED — every block figure matches eustack_report.md: 3652/199/52 of 3903
      across 84 signatures; all 15 pool occupancies; dependency waits 97/94/8;
      unclassified_thread_pct 1.3 (info).
  (c) MACHINE-VERIFIED — D-10 suppression statement present, zero delta figures in the block,
      even though the deterministic report prints 30 changed signatures (e.g. 1715 -> 1713).
  (d) MACHINE-VERIFIED — 9 distinct cited ids; 0 absent from the store; 0 from outside the
      block's 49-id citable set.

### 2. Signature cap, dropped-count sentence and lock-site vocabulary (18-02 D3)

expected: |
  The per-signature listing is capped at 8, most-populous-first with no re-sort; an explicit
  dropped-count sentence appears only when signatures were actually dropped; lock-site lines
  never use ownership/possession vocabulary.
why_human: |
  Surfaced by `uat classify-coverage` as `reason: validation_failed` — the D3 entry in
  18-02-SUMMARY.md omits the required `human_judgment` flag that all its sibling entries carry.
  This is a SUMMARY metadata omission, not a coverage gap: the deliverable's three declared
  verification refs all pass on re-run. Presented as a checkpoint under the fail-safe rule
  (never drop a deliverable) rather than auto-passed.
result: [passed]
evidence: |
  Confirmed empirically on the real capture (case `p18uat`), not just by re-running the refs:
  exactly 8 signature lines, most-populous-first with no re-sort (1713, 1120, 244, 213, 110,
  80, 79, 78); dropped-count sentence reads "76 further signatures not shown (of 84 total
  signatures)" — 8 + 76 = 84; no ownership/possession vocabulary emitted (the only matches in
  eustack_facts.py are docstrings stating ownership is NOT claimed). Note this capture has zero
  lock sites, so the lock-site line itself is unexercised on real data — a pre-existing coverage
  limit carried forward, not a Phase 18 gap.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
