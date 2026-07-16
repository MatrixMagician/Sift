---
status: testing
phase: 02-case-store-template-dedup
source: [02-VERIFICATION.md]
started: 2026-07-16T22:34:37Z
updated: 2026-07-16T22:34:37Z
---

## Current Test

number: 1
name: Live progress bar on a real TTY
expected: |
  Transient rich progress bar (bar, bytes, elapsed) renders on stderr during
  ingest and disappears on completion; stdout carries only the
  per-file/Total/Template-groups lines (byte-identical to the scripted contract)
awaiting: user response

## Tests

### 1. Live progress bar on a real TTY
test: `uv run python tests/perf/generate_synthetic.py /tmp/big.log 100`, create a case over it, run `uv run sift ingest <case>` in a real terminal
expected: Transient progress bar (bar, bytes, elapsed) on stderr; stdout byte-identical to the scripted contract
why_human: rich disables itself off-terminal; no automated test can exercise the render path
result: [pending]

### 2. Perf gate on an idle machine
test: `uv run pytest -m perf -s`
expected: ~19-25 s for the 100 MB ingest (budget 60 s)
why_human: Verifier machines were under load in both prior runs (02-03's 66.7 s was an environmental false-red; the gated 19.3 s measurement from 02-02 stands as phase evidence)
result: [pending]

### 3. Filter UAT
test: `uv run sift show <case> events --filter severity=error --filter limit=5` and `uv run sift show <case> clusters --filter min-count=10`
expected: Behaviour matches `--help` documentation (AND-combined, literal substrings, naive timestamps as UTC)
why_human: 02-03 plan human-check item — operator-facing semantics judgment
result: [pending]

### 4. Backstop truths — migration-2 concurrency and interrupted-ingest atomicity
test: Accept the structural evidence in 02-VERIFICATION.md (behavior_unverified_items 2-3) or exercise manually (concurrent v1 open mid-migration; kill ingest mid-run on the 100 MB file)
expected: Second opener sees v1 or fully-migrated v2, never half-migrated; interrupted ingest leaves zero new events or the complete result. Note the WR-07 disk-full caveat on the interrupted-ingest item (SQLITE_FULL/IOERR auto-rollback destroys savepoints — known structural hole, weigh or plan the WR-07 fix)
why_human: Concurrency/kill behaviours unexercised by any test — backstop truths abstain without behavioural evidence
result: [pending]

### 5. Prohibition sign-off
test: Sign off on the five judgment-tier prohibitions (no network egress; dedup never loses events; stored evidence verbatim / mask only in templates / sanitise at render; progress never swallows per-file errors; filters fail loudly) against the evidence in 02-VERIFICATION.md Prohibition Status
expected: All prior caveats (CR-01, WR-01, WR-05) resolved by 02-04; evidence clean on all five
why_human: Judgment-tier prohibitions require explicit human resolution; verifier evidence is non-authoritative
result: [pending]

### 6. Partial-scope convention confirmation
test: Confirm ticking CLI-03/STORE-04 per-phase-leg with inline notes is acceptable (notes now exist in REQUIREMENTS.md lines 29, 65, 132, 134)
expected: Convention accepted (or an alternative recorded)
why_human: Both plans explicitly asked the verifier to surface this scope decision to the human
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
