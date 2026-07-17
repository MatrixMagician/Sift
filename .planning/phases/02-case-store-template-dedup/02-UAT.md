---
status: complete
phase: 02-case-store-template-dedup
source: [02-VERIFICATION.md]
started: 2026-07-16T22:34:37Z
updated: 2026-07-17T00:30:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live progress bar on a real TTY
test: `uv run python tests/perf/generate_synthetic.py /tmp/big.log 100`, create a case over it, run `uv run sift ingest <case>` in a real terminal
expected: Transient progress bar (bar, bytes, elapsed) on stderr; stdout byte-identical to the scripted contract
why_human: rich disables itself off-terminal; no automated test can exercise the render path
result: pass
note: 2026-07-17 — user ran `sift ingest` on a real TTY and confirmed ("Saw the bar"): the transient progress bar rendered during ingest and vanished on completion; stdout carried the scripted per-file/Total/Template-groups contract. Render path (cli.py:202-213) exercised and confirmed.

### 2. Perf gate on an idle machine
test: `uv run pytest -m perf -s`
expected: ~19-25 s for the 100 MB ingest (budget 60 s)
why_human: Verifier machines were under load in both prior runs (02-03's 66.7 s was an environmental false-red; the gated 19.3 s measurement from 02-02 stands as phase evidence)
result: pass
note: 2026-07-17 — `uv run pytest -m perf -s` measured 19.7 s (budget 60 s) on this machine. Well inside budget.

### 3. Filter UAT
test: `uv run sift show <case> events --filter severity=error --filter limit=5` and `uv run sift show <case> clusters --filter min-count=10`
expected: Behaviour matches `--help` documentation (AND-combined, literal substrings, naive timestamps as UTC)
why_human: 02-03 plan human-check item — operator-facing semantics judgment
result: pass
note: 2026-07-17 — drove the real CLI. `events --filter severity=error --filter limit=5` → exactly 5 error rows, AND-combined, limit honoured, naive ts rendered as UTC (+00:00). `clusters --filter min-count=1` lists template groups (masking in templates, exemplars verbatim); `min-count=10` correctly empty (100 groups / 200 events). Duplicate `--filter severity=…` exits loudly ("duplicate filter key 'severity'"). Behaviour matches --help.

### 4. Backstop truths — migration-2 concurrency and interrupted-ingest atomicity
test: Accept the structural evidence in 02-VERIFICATION.md (behavior_unverified_items 2-3) or exercise manually (concurrent v1 open mid-migration; kill ingest mid-run on the 100 MB file)
expected: Second opener sees v1 or fully-migrated v2, never half-migrated; interrupted ingest leaves zero new events or the complete result. Note the WR-07 disk-full caveat on the interrupted-ingest item (SQLITE_FULL/IOERR auto-rollback destroys savepoints — known structural hole, weigh or plan the WR-07 fix)
why_human: Concurrency/kill behaviours unexercised by any test — backstop truths abstain without behavioural evidence
result: pass
note: 2026-07-17 — user accepted the structural evidence in 02-VERIFICATION.md (behavior_unverified_items 2-3). WR-07 disk-full rollback hole (SQLITE_FULL/IOERR auto-rollback destroys savepoints) is NOT fixed here — user elected to carry it forward as a gap for Phase 3 (see ## Deferred Follow-Ups / ROADMAP Phase 3).

### 5. Prohibition sign-off
test: Sign off on the five judgment-tier prohibitions (no network egress; dedup never loses events; stored evidence verbatim / mask only in templates / sanitise at render; progress never swallows per-file errors; filters fail loudly) against the evidence in 02-VERIFICATION.md Prohibition Status
expected: All prior caveats (CR-01, WR-01, WR-05) resolved by 02-04; evidence clean on all five
why_human: Judgment-tier prohibitions require explicit human resolution; verifier evidence is non-authoritative
result: pass
note: 2026-07-17 — evidence gathered/accepted on all five. No network egress: zero httpx/socket/urllib in src/ (LLM client is Phase 3). Dedup verbatim/mask-in-template/sanitise-at-render: confirmed live (exemplars keep raw IDs, templates carry <NUM>). Filters fail loudly: duplicate-key exits non-zero. Progress swallows no per-file errors and dedup-never-loses: CR-01 SAVEPOINT accounting + prior 02-04 evidence accepted.

### 6. Partial-scope convention confirmation
test: Confirm ticking CLI-03/STORE-04 per-phase-leg with inline notes is acceptable (notes now exist in REQUIREMENTS.md lines 29, 65, 132, 134)
expected: Convention accepted (or an alternative recorded)
why_human: Both plans explicitly asked the verifier to surface this scope decision to the human
result: pass
note: 2026-07-17 — user accepted the inline '(partial scope: X delivered Phase N; remainder Phase M)' annotation convention for CLI-03/STORE-04.

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0
blocked: 0

## Deferred Follow-Ups

- test: 4
  idea: "WR-07 — disk-full (SQLITE_FULL/IOERR) mid-ingest triggers SQLite auto-rollback that destroys the per-file SAVEPOINTs, so the interrupted-ingest atomicity guarantee has a known hole. User elected to carry forward and fix in Phase 3."
  deferred_at: 2026-07-17

## Gaps
