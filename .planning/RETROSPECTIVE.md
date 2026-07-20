# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.2 — DSSPerformanceMonitor Correlation

**Shipped:** 2026-07-20
**Phases:** 3 (12–14) | **Plans:** 15

### What Was Built
- `dssperfmon` PDH-CSV adapter — deterministic, idempotent, UTC-normalised, individually citable time-series events; header zone/offset recorded as evidence not applied (ADR 0012); sniff-collision with `dsserrors` fixed by qualifying the bare `MCM` marker (ADR 0013).
- Perfmon events held out of dedup/embed/cluster/salience via one `EXCLUDED_FROM_RANKING` store seam — cluster output byte-identical with/without a perfmon CSV, every sample still citable.
- Deterministic episode correlator over MCM-04's existing lead-up window (value-at-denial/slope/peak) plus graded correlation hazards; shipped as standalone `sift perfmon <case>` report + CSV.
- Perfmon figures spliced into `sift analyze` as cited-not-authored evidence; regression-gated `perfmon-denial` golden eval case with a non-vacuous citation-sensitivity gate.

### What Worked
- **Mirroring v1.1's shape one layer out** (adapter → analyser → report → LLM facts → eval) meant every phase had a proven precedent — Phase 14 explicitly reused Phase 11's `prompted_ids`-union and byte-identity-hash mechanics rather than reinventing them.
- **Real-data-first scoping** caught two premise breaks before code: the `Total MCM Denial` counter reads 0 across all 13,596 Hartford samples (became a reported flag, not an input), and the CSV/log pair doesn't overlap (drove the re-timed golden fixture + overlap guard).
- **One exclusion predicate, no opt-out flag (D-07)** kept the cross-cutting PERF-03 change auditable and made the criterion-4 regression guard trivially expressible.

### What Was Inefficient
- The shipped Hartford CSV+log pair being non-overlapping surfaced only mid-milestone, forcing a synthetic re-timed overlapping fixture in Phase 14 (Wave 1) before the golden case could be non-vacuous — a fixture reality that could have been caught at v1.2 scoping.
- Real data had zero blank/non-numeric cells, so the adapter's `severity="unknown"` fallback needed synthetic fixtures to exercise at all.

### Patterns Established
- **Deterministic-core-vs-LLM boundary as a reusable milestone template**: figures computed pre-generation, only printed `[evt:]` ids enter the citable universe, an anti-hallucination test plants a wrong figure and proves it never reaches the prompt. Now validated across two milestones (MCM, perfmon).
- **Import the security-relevant filter, don't re-declare it**: the correlator imports the adapter's `_RESERVED_ATTRS` rather than re-listing provenance keys, preventing drift.

### Key Lessons
1. When adapting a reference script or extending an analysis layer, validate every keyed marker/counter against a real artifact before locking scope — a headline signal (`Total MCM Denial`) can be dead in the real data.
2. Fixture time-alignment is a first-class scoping question for any correlation feature; assert overlap with a self-verifying guard rather than trusting a shipped pair.
3. Keep cross-cutting exclusions to a single predicate with no defaulted opt-out — the flag is the mechanism by which a future caller silently reintroduces the regression.

### Cost Observations
- Model mix: not tracked this milestone.
- Notable: single-day milestone (2026-07-20); runtime code byte-identical from phase-14 completion through close, so the audit carried the integration verdict forward and only re-ran the quality gate.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v1.0 | 8 | Initial engine; SPEC M1–M8 one-to-one phases |
| v1.1 | 3 | Deterministic-core-vs-LLM split (numeric analyser separate from additive LLM-facts phase) |
| v1.2 | 3 | Same split reused verbatim one layer out; real-data-first scoping caught two premise breaks pre-code |

### Cumulative Quality

| Milestone | pytest | Notes |
|-----------|--------|-------|
| v1.1 | 537 passed | audit 7/7 reqs |
| v1.2 | 658 passed | audit 8/8 reqs, integration 6/6, Nyquist COMPLIANT; zero new runtime dependencies |

### Top Lessons (Verified Across Milestones)

1. The computed-figures-then-cite boundary holds up as the anti-hallucination backbone — reuse it whenever the model narrates numbers it must not author.
2. Scope against real diagnostic artifacts, not just reference scripts/docs — real data repeatedly exposes dead signals and missing fields the script never handled.
