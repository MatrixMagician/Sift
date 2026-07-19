# Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-19
**Phase:** 9-mcm-episode-detection-memory-breakdown
**Areas discussed:** Data source, Lifecycle signals, Breakdown model shape, Persistence & rotation scope

---

## Data source

| Option | Description | Selected |
|--------|-------------|----------|
| Store events, parse in analyser | Analyser reads Event rows from case.db and re-applies the reference regexes to each `event.raw`. Adapter untouched; all MCM logic isolated in the new analyser; every episode signal maps to a real `event_id`. No disk re-read. | ✓ |
| Enrich adapter attrs | Extend dsserrors to emit AvailableMCM/HWM/Size/Source/SID as attrs at ingest; analyser reads attrs. Cleaner analyser but touches the near-frozen adapter and forces re-ingest. | |
| Raw-file re-parse | Port the reference script directly against files on disk (line numbers, no event_ids). Simplest port, but a citation dead-end for MCM-06 in Phase 11. | |

**User's choice:** Store events, parse in analyser
**Notes:** Preserves the `event_id` citation path that is load-bearing for Phase 11 (`cited ⊆ prompted ⊆ store`). Confirmed the store keeps full verbatim `raw` + line span + `event_id` for every dsserrors line-event, so re-parsing tokens from `raw` is viable without any adapter change.

---

## Lifecycle signals

| Option | Description | Selected |
|--------|-------------|----------|
| Research against Hartford log | Researcher/executor greps the real Hartford deny log to pin exact marker strings; all three signal types captured as episode annotations (event_id-referenced), tolerant of absence. | ✓ |
| I'll give exact strings | User provides the exact MStr wording now. | |
| Candidate strings + confirm | Claude proposes candidate anchors; researcher confirms against the log. | |

**User's choice:** Research against Hartford log
**Notes:** memory-status-low handler, emergency working-set offload, and recovery are a new extension on top of the reference `prescan` (which only tracks denial/State=normal/Succeeded). Exact strings to be pinned during research; missing signals recorded as absent, never fabricated. The Hartford deny log has no `State=normal`, so the open/truncated-episode path is exercised on real data.

---

## Breakdown model shape

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid: map + named accessors | Retain the full verbatim `label → (value_mb, unit)` map AND expose typed named accessors for the known components. Auditable + typed + tolerant of label drift. | ✓ |
| Typed named fields only | Fixed Pydantic fields; variant/unknown labels dropped or coerced. Cleanest API, brittle to MStr label changes. | |
| Verbatim map only | Faithful label→value map, no named structure. Robust but every consumer string-matches labels. | |

**User's choice:** Hybrid: map + named accessors
**Notes:** Mirrors the reference script's fuzzy `_get(substr)` lookup but as typed accessors over a faithfully-preserved map — nothing lost, typed downstream access.

---

## Persistence & rotation scope

| Option | Description | Selected |
|--------|-------------|----------|
| Pure function, no new table | Deterministic pure function over stored events, recomputed on demand (Phase 10/11 reuse it). No new table/migration/staleness surface. Events ordered by UTC ts across files; fragmented dump blocks flagged. | ✓ |
| Persist to new store table | Add mcm_episodes/breakdown tables via migration — durable, inspectable — at the cost of a write path and staleness questions now. | |
| Pure function, strictly per-file | Pure function but detect episodes within each source_file independently; multi-node UTC stitching deferred. | |

**User's choice:** Pure function, no new table
**Notes:** Determinism is inherent (no model), so criterion #5 (byte-identical re-run) holds without a persistence layer — avoids speculative complexity nothing yet needs. Cross-file ordering by UTC ts is multi-node safe; MCM dump blocks fragmented across a rotation boundary (ADR 0006 — adapter never stitches `.bak` siblings) are flagged, not merged. Open/truncated episodes (no recovery line) are first-class, distinct from implicit-recovery closes.

---

## Claude's Discretion

- Module placement/naming (expected `src/sift/pipeline/mcm.py`, mirroring `pipeline/salience.py`), the exact typed-model field set, and internal regex/parse structure — planner's/executor's call, provided D-01…D-07 hold.
- No public CLI surface required in Phase 9 (`sift mcm` is Phase 10); a thin internal entry point + tests suffices.

## Deferred Ideas

- Diagnostic flags, lead-up window, per-OID/Source/SID attribution, `sift mcm` report + CSV — Phase 10 (MCM-03/04/05).
- MCM facts into `sift analyze` as cited evidence + MCM golden eval case — Phase 11 (MCM-06/07).
- Adapter enrichment (MCM numeric tokens as attrs at ingest) — rejected for now; revisit only if `event.raw` re-parsing proves a measured bottleneck.
- Persisting episodes to a store table — rejected for now; revisit if a consumer needs durable/queryable episodes.
- DSSPerformanceMonitor CSV time-series correlation (PERF-01) — deferred to v2 (SEED-001).
