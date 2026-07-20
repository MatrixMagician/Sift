# Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-20
**Phase:** 14-perfmon-facts-into-sift-analyze-golden-eval-case
**Areas discussed:** Prompt splice, Fact cap, Golden case, Disclosure todo

---

## Prompt splice — perfmon fact block placement in `triage.md`

| Option | Description | Selected |
|--------|-------------|----------|
| Separate block, MCM then perfmon | New independent `PERFMON_BLOCK` sentinel after the MCM block; each removed whole when absent → all four presence combos byte-identical | ✓ |
| Single combined correlation-facts block | One block holding both MCM + perfmon; couples the two sources' guards and caps | |
| Perfmon block before MCM | Same separate design, reversed reading order; no technical advantage | |

**User's choice:** Separate block, MCM then perfmon (Recommended)
**Notes:** Mirrors the MCM/KB sentinel pattern verbatim; independent byte-identity guards for perfmon-only / MCM-only / both / neither. → D-01, D-02.

---

## Fact cap — bounding perfmon prompt growth

| Option | Description | Selected |
|--------|-------------|----------|
| Cap groups (mirror 8) + salient counters | ≤ `_MAX_GROUPS` TrendGroups by severity; salient counter subset per group in the prompt; full 22-counter fidelity stays in `sift perfmon`; dropped ids leave the citable set | ✓ |
| Cap total counter-lines across the block | One global budget on counter lines regardless of group count | |
| No cap — render every group and counter | Max fidelity, unbounded prompt growth; contradicts roadmap bound note | |

**User's choice:** Cap groups (mirror 8) + salient counters (Recommended)
**Notes:** Prompt-growth driver is groups × counters, not the 13,596 raw samples (already summarised). Salient-counter reduction is a prompt-rendering choice only — `_counter_trends` keeps its no-allowlist behaviour. → D-03, D-04.

---

## Golden case — regression gate anchor (PERF-08)

| Option | Description | Selected |
|--------|-------------|----------|
| Hartford deny CSV+log pair | 13,596 samples, confirmed 12:39:45 denial, full lead-in trend — richest signal | ✓ |
| Snapshot CSV+logs pair | 6,803 samples, no denial banner — weaker regression signal | |
| Both as two golden cases | Broadest coverage, ~2× fixture + eval-runtime cost | |

**User's choice:** Hartford deny CSV+log pair (Recommended)
**Notes:** Snapshot pair kept as a documented future second candidate. → D-07.

---

## Disclosure todo — WR-03 episodes-present branch

| Option | Description | Selected |
|--------|-------------|----------|
| Fold in as a small correlator sub-task | Add a case-level unattributed-samples disclosure (reuse `_hazard_unplaceable_samples`) so "nothing disappears silently" holds on both branches | ✓ |
| Keep Phase 14 strictly PERF-07/08 | Leave correlator untouched; handle the todo in a separate follow-up fix | |

**User's choice:** Fold in as a small correlator sub-task (Recommended)
**Notes:** Todo tagged `resolves_phase:14`; same perfmon module. Requires a `PerfmonAnalysis` model/design change (which today forbids case-level hazards) — planner decides field-vs-group, preserving Phase 13 determinism + `_RESERVED_ATTRS`/citation invariants. Doubly-synthetic on real data, low regression risk. → D-08.

## Claude's Discretion

- Exact salient-counter selection + ordering (must be deterministic; citable = printed ids).
- Field-vs-synthetic-group form of the D-08 case-level disclosure.
- Golden-fixture construction mechanics for the eval case.

## Deferred Ideas

- Snapshot golden case (second candidate) — future.
- PERFV2-01/02/03 (recovery-trend / multi-host / perfmon-only anomalies) — beyond v1.2.
- Phase 11 code-review INFO items (IN-01/IN-03) — address opportunistically only if Phase 14 edits touch those exact lines; non-blocking.
