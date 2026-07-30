---
status: complete
phase: 19-ranking-exclusion-regression-gated-golden-eval
source:
  - 19-01-SUMMARY.md
  - 19-02-SUMMARY.md
  - 19-03-SUMMARY.md
  - 19-04-SUMMARY.md
started: 2026-07-28
updated: 2026-07-28
---

## Current Test

[testing complete]

## Tests

### 1. EXCLUDED_FROM_RANKING holds eu-stack out of dedup/embed/cluster/salience while it stays fully retrievable by id
expected: EXCLUDED_FROM_RANKING holds eu-stack out of dedup/embed/cluster/salience while it stays fully retrievable by id
result: pass
source: automated
coverage_id: 19-01/D1

### 2. sift analyze on an eu-stack-only case reaches hypothesise() and narrates instead of printing the false ingest message; a genuinely empty case still short-circuits before any client contact
expected: sift analyze on an eu-stack-only case reaches hypothesise() and narrates instead of printing the false ingest message; a genuinely empty case still short-circuits before any client contact
result: pass
source: automated
coverage_id: 19-01/D2

### 3. Cluster output is byte-identical with and without an eu-stack dump ingested (proven non-vacuously), and every eu-stack event is citable/renderable while none reach the ranking seam
expected: Cluster output is byte-identical with and without an eu-stack dump ingested (proven non-vacuously on a case whose cluster output is non-empty), and every eu-stack event is citable/renderable while none reach the ranking seam
result: pass
source: automated
coverage_id: 19-01/D3

### 4. A truth.yaml can declare an optional expect_eustack block that validates strictly, and a typo'd key inside it fails loudly
expected: A truth.yaml can declare an optional expect_eustack block that validates strictly (own extra=forbid, mandatory provenance/hang_detected/total_threads), and a typo'd key inside it fails loudly
result: pass
source: automated
coverage_id: 19-02/D1

### 5. An eu-stack case moves none of the four existing keyword aggregates, and mean_eustack_detection_rate reads only eu-stack cases
expected: An eu-stack case moves none of the four existing keyword aggregates (retrieval_hit_rate, hypothesis_hit_at_k, citation_validity_rate, determinism_stability), and mean_eustack_detection_rate reads only eu-stack cases
result: pass
source: automated
coverage_id: 19-02/D2

### 6. run_case scores an eu-stack case entirely offline via figure reproduction; a wrong declared figure turns the case red without marking it run_failed; a genuine ingest error degrades to run_failed
expected: run_case scores an eu-stack case entirely offline (observed-empty request log) via figure reproduction against analyse_eustack_bundle; a wrong declared figure turns the case red without marking it run_failed; a genuine ingest error degrades to run_failed
result: pass
source: automated
coverage_id: 19-02/D3

### 7. sift eval gates a fifth floor, eustack_detection_rate = 1.00, in the same higher-is-better lower-bound shape as the existing four
expected: sift eval gates a fifth floor, eustack_detection_rate = 1.00, in the same higher-is-better lower-bound shape as the existing four
result: pass
source: automated
coverage_id: 19-03/D1

### 8. A suite containing zero scorable eu-stack cases can never report a pass, even though the new aggregate reads a vacuous 1.00 on an empty list
expected: A suite containing zero scorable eu-stack cases can never report a pass, even though the new aggregate reads a vacuous 1.00 on an empty list
result: pass
source: automated
coverage_id: 19-03/D2

### 9. The real healthy reference capture, run as a golden case, reports hang_detected false and raises zero graded flags, both asserted independently
expected: The real healthy reference capture, run as a golden case, reports hang_detected false and raises zero graded flags, both asserted independently
result: pass
source: automated
coverage_id: 19-03/D3

### 10. The healthy case is machine-marked provenance observed and is the only case in the suite so marked
expected: The healthy case is machine-marked provenance observed and is the only case in the suite so marked
result: pass
source: automated
coverage_id: 19-03/D4

### 11. The healthy case lives in its own eval/cases/eustack-healthy/ directory, signature-derived and small
expected: The healthy case lives in its own eval/cases/eustack-healthy/ directory, signature-derived and small (88,701 bytes, 144 threads), discipline mirrored from tests/fixtures/eustack/
result: pass
source: automated
coverage_id: 19-03/D5

### 12. The eu-stack column and its floor verdict appear in both the text and JSON metric tables
expected: The eu-stack column and its floor verdict appear in both the text and JSON metric tables
result: pass
source: automated
coverage_id: 19-03/D6

### 13. A synthetic hang fixture built from the documented warehouse connection-pool exhaustion scenario is detected — analyse_eustack_bundle reproduces its declared pool-saturation and dependency-wait figures exactly
expected: total_threads=35, pools[warehouse]=busy 25/idle 0, dependencies[warehouse]=25, both percentage flags info/0.0%
result: pass
source: automated
coverage_id: 19-04/D1

### 14. The same fixture stays detected under cosmetic mutation — renumbered TIDs, reordered thread blocks and different instruction addresses yield the SAME measured figures
expected: The same fixture stays detected under cosmetic mutation — renumbered TIDs, reordered thread blocks and different instruction addresses yield the SAME measured figures
result: pass
source: automated
coverage_id: 19-04/D2

### 15. Every synthetic positive is machine-marked provenance authored, and the healthy capture remains the only case marked observed
expected: Every synthetic positive is machine-marked provenance authored, and the healthy capture remains the only case marked observed
result: pass
source: automated
coverage_id: 19-04/D3

### 16. The positive and its twin each occupy their own eval/cases/eustack-hang-*/ directory; both stay signature-preserving and small
expected: eustack-hang-pool-warehouse 38,460 bytes; eustack-hang-pool-warehouse-mutated 38,463 bytes (both <= 64KB cap)
result: pass
source: automated
coverage_id: 19-04/D4

### 17. sift eval exits non-zero when the analyser is neutered so an eu-stack case stops reproducing its declared figures — the gate is proven to bite, not merely to be configured
expected: sift eval exits non-zero when the analyser is neutered so an eu-stack case stops reproducing its declared figures — the gate is proven to bite, not merely to be configured
result: pass
source: automated
coverage_id: 19-04/D5

### 18. A suite containing only the eu-stack cases runs to a verdict with an observably empty request log, and the split is stated in sift eval's own help text
expected: A suite containing only the eu-stack cases runs to a verdict with an observably empty request log (exit 0, calls == []), and the split is stated in sift eval's own help text
result: pass
source: automated
coverage_id: 19-04/D6

### 19. Confirm the auto-covered deliverable set
expected: |
  All 18 deliverables above are deterministically covered by passing tests.
  Independently re-run this session: uv run pytest -> 834 passed.
  Confirm the covered set matches what Phase 19 was meant to deliver.
result: pass

### 20. sift analyze on the real eu-stack-only capture narrates the fact block (D-19-02)
expected: |
  Ingest ~/Downloads/iserver1_stacks_1-minute_diff/ into a fresh case, then run
  uv run sift analyze <case> against a live local inference endpoint
  (llama-server / Lemonade). It does NOT print "Nothing to cluster; run sift
  ingest first", it reaches hypothesise(), and the resulting report narrates and
  cites eu-stack event ids.
result: pass
manual_only: true
why_human: Requires a live local inference endpoint. Executed 2026-07-30 against the operator's live Lemonade instance rather than left deferred.
evidence: |
  Case p19uat, real capture ingested (7807 events, 2 dumps, 100% coverage,
  template groups 0 -> exclusion confirmed). `sift analyze p19uat` exit 0,
  printed "Clusters: 0 (0 labelled)" + "Hypotheses: 2", and did NOT print
  "Nothing to cluster; run sift ingest first". Both hypotheses narrate eu-stack
  findings; all 14 cited ids resolve, all source='eustack', both
  citations_valid=True. Narrated claims match `sift eustack` COMPUTED figures
  (http 97/97 busy occupancy 1.0, warehouse 94/94 busy occupancy 1.0, 3652
  idle-parked) -- model narrates, does not author.

## Summary

total: 20
passed: 20
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
