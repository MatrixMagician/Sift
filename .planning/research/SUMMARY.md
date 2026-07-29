# Research Summary — Sift v1.3: EU-Stack Hang & Slowdown Diagnosis

**Researched:** 2026-07-25  
**Domain:** Thread-state classification and saturation analysis added to an existing deterministic, citation-gated incident-triage pipeline  
**Status:** Ready for phase planning  

---

## Executive Summary

Sift v1.3 adds deterministic eu-stack thread-state classification and saturation analysis to supplement (and eventually replace) the existing embedding-based clustering for cases with thread dumps. The core architectural finding—that composition, not motion, is the signal—fundamentally changes how hang detection works: instead of the falsified "identical stack after N seconds = stuck" heuristic (which flags 98.9% of threads on a demonstrably healthy server as false positives), v1.3 clusters threads by their role (idle-parked, blocked-on-external, blocked-on-lock, running, unclassified) and reports saturation/contention as ratios within each role population.

**Technology is aggressively conservative:** no new runtime dependencies, no ML clustering for exact frame-sequence grouping (stdlib `collections.Counter` replaces that), hand-curated rules as a TOML file sibling to existing prompts. The implementation replicates v1.2's proven MCM/perfmon pattern (deterministic compute → standalone report + CSV → facts into `sift analyze`) rather than inventing new architecture.

**Two critical integration risks are well-documented:** SEED-002 vector reuse can silently corrupt determinism if the cache key or batch-knob invalidation logic is wrong; and the `EXCLUDED_FROM_RANKING` decision (should eu-stack events flow through clustering or not?) must land *after* the deterministic replacement analysis ships, not before, or users lose signal in a regression window.

---

## Key Findings

### From STACK Research

| Finding | Confidence | Notes |
|---------|------------|-------|
| No new runtime dependency for any four capability asks | HIGH | All covered by stdlib (tomllib, collections) or already-pinned dependencies (sqlite-vec) |
| TOML `tomllib` for rules file (not YAML, not Markdown) | HIGH | Literal strings avoid escaping hazards for C++ symbols; already the project config format |
| Plain string methods over regex or trie | MEDIUM | 93 signatures × ≤19 frames × ~200 rules runs in single-digit ms; no throughput problem |
| `collections.Counter` for signature grouping, not sklearn | HIGH | Exact-match equality is free; ML clustering to exact-equality problem is worse |
| sqlite-vec read-back for SEED-002 vector reuse | HIGH | Empirically verified; `_blob_to_vec` already exists in codebase |
| **Classifier must read `Event.raw`, not `Event.message`** | HIGH | `CONDENSED_FRAMES=5` caps message; self-labelling frames sit 8–19 deep |

### From FEATURES Research

| Finding | Confidence | Notes |
|---------|------------|-------|
| Frame→role taxonomy is load-bearing foundation | HIGH | Everything else depends on it existing first |
| Per-signature composition + per-pool occupancy is core | HIGH | Directly addresses measured finding: 3,902 threads → 93 signatures |
| Unclassified-frame surfacing (count + example, never guessed) | HIGH | Anti-hallucination discipline, not optional |
| `sift eustack` standalone report + CSV | MEDIUM | Mirrors v1.2's mcm/perfmon UX contract |
| Identical-stack-after-60s heuristic is inverted | HIGH | Measured on healthy server; mechanism falsified |
| Deadlock detection is permanent non-goal | HIGH | No lock-ownership edges in eu-stack; structurally impossible |
| Multi-dump signals must be taxonomy-gated | MEDIUM | Gate prevents re-introducing falsified mechanism |

### From ARCHITECTURE Research

| Finding | Confidence | Notes |
|---------|------------|-------|
| Sibling module, not shared abstraction | HIGH | Two instances share contract, not code; three value semantics → bar fails |
| Rules file: `src/sift/rules/eustack_roles.toml` via `importlib.resources` | HIGH | Mirrors `src/sift/prompts/*.md` packaging |
| User override via config key `[eustack] rules_path` | HIGH | Reuses existing override mechanism |
| `EXCLUDED_FROM_RANKING` gain "eustack" after replacement ships | HIGH | Landing before creates regression window |
| Multi-dump grouping by `source_file`, timestamp advisory-only | HIGH | Follows ADR 0012 precedent on ambiguous bias |
| **Rules file format: TOML, not Markdown** | HIGH | STACK + ARCHITECTURE independently converge |
| Fact injection is 4th copy of MCM/perfmon pattern | HIGH | Three functions already; consistency argues continuation |
| Vector reuse in `cluster.py`, keyed on `template_id` | MEDIUM | Exemplar-text logic is clustering concern |

### From PITFALLS Research

| Pitfall | Severity | Mitigation |
|---------|----------|-----------|
| Composition-blind heuristics reproduce 98.9% false positives | CRITICAL | Taxonomy + role-population verdicts are gate |
| TID reuse fabricates identity continuity | CRITICAL | Phrase as signature-population deltas, never per-TID causal stories |
| Symbol brittleness & bare-substring matching | CRITICAL | Anchor on qualified names; mirrors ADR 0013 |
| Hand-picked thresholds unfalsifiable | HIGH | Config-tunable graded flags (MCM-03 pattern) |
| Synthetic fixtures written to match detector | HIGH | Derive from documented scenario, mutate cosmetically |
| Per-thread work ignores 40x signature reduction | HIGH | O(signatures × rules), not O(threads × rules) from start |
| SEED-002 vector-reuse cache reopens determinism | CRITICAL | Exact-text hash + model identity; index-preserving splice |
| Integration regressions against load-bearing invariants | MEDIUM | Four separate acceptance criteria |

---

## Roadmap Implications

### Suggested Phase Structure (within v1.3)

**Phase 1: Rules File + Thread-Role Classifier**
- **Rationale:** Foundation for all downstream analysis
- **Delivers:** Versioned TOML rules file, deterministic classifier, unclassified-frame surfacing
- **Features:** Frame→role taxonomy (5 buckets: idle-parked, blocked-on-external, blocked-on-lock, running, unclassified)
- **Research flags:** MEDIUM confidence on frame-matching strategy; recommend reference-capture validation pass
- **Gate:** Healthy-capture negative fixture produces zero flags; unclassified rate measured and low

**Phase 2: Saturation & Contention Analysis**
- **Rationale:** Builds on Phase 1 to compute occupancy and contention metrics
- **Delivers:** Per-pool occupancy table, lock-site convergence with confidence labels
- **Features:** Occupancy = 1 - idle/total per pool; contention = N threads at same lock-site frame
- **Research flags:** None; pattern established; thresholds are MCM-style config-tunable graded flags
- **Gate:** No flags on healthy-capture; raw computed values shown beside thresholds

**Phase 3: `EXCLUDED_FROM_RANKING` Decision + Multi-Dump Grouping**
- **Rationale:** Sequencing constraint; exclusion must land after Phase 2, before eval fixtures
- **Delivers:** One-line store change; multi-dump grouping by `source_file` with ambiguity disclosure
- **Features:** Per-dump classifications, progression deltas, taxonomy-gated per-TID tracking
- **Research flags:** **Open:** How aggregate facts resolve to concrete event_ids for citation (Phase 5 design question)
- **Gate:** Two-dump case reports deltas without claiming unqualified TID continuity

**Phase 4: `sift eustack` Report + CSV**
- **Rationale:** User-facing output; mirrors mcm/perfmon commands
- **Delivers:** `sift eustack <case>` command, Markdown report + CSV export
- **Features:** Composition summary, per-pool occupancy, external-wait concentration, lock sites, unclassified list, multi-dump section
- **Research flags:** None; replicate mcm_report/perfmon_report structure
- **Gate:** CSV passes formula-guard test on symbol text (use perfmon's `_csv_safe` pattern)

**Phase 5: Eu-Stack Facts into `sift analyze`**
- **Rationale:** Integrate computed facts into RAG hypothesis pipeline
- **Delivers:** `eustack_facts.md` (zero authored digits), `triage.md` block, splice in `hypothesise.py`
- **Features:** Role-composition summary, saturation/contention key findings, multi-dump deltas as cited evidence
- **Research flags:** **Open:** Event_id resolution for aggregates (e.g., "1,715 idle threads"); needs design before detailed planning
- **Gate:** Zero authored digits; anti-hallucination test; byte-identical-additive test for no-eustack cases

**Phase 6: SEED-002 Vector Reuse Integration** *(parallel, independent of Phases 1–5)*
- **Rationale:** Performance/determinism fix; fully independent; sequences separately to avoid diff conflicts
- **Delivers:** Per-exemplar vector cache, model/dimension guards, batch-knob handling, observability
- **Features:** Incremental embed (hit/miss split), index-preserving splice, CLI observability ("Embedded N, reused M")
- **Research flags:** **Open:** Batch-knob-change invalidation (ARCHITECTURE recommends "no, with --re-embed"; PITFALLS says record ADR)
- **Gate:** Mixed hit/miss produces byte-identical output to full-embed; model/dim mismatch hard-guarded

**Phase 7: Regression-Gated Golden Eval**
- **Rationale:** All features (1–6) complete; exercises full pipeline end-to-end
- **Delivers:** Negative case (real healthy capture), positive cases (synthetic scenarios), eval integration
- **Features:** Healthy-capture proves no false positives; synthetic cases prove known hangs detected
- **Research flags:** Fixtures must derive from documented scenarios, not rule strings; cosmetic mutations must not break classification
- **Gate:** Healthy-capture produces zero flags; synthetic positives pass with cosmetic mutations; confidence distinction surfaced

---

### Phases with Deeper Research Needed

- **Phase 1:** Frame-matching strategy (enclosing-vs-leaf, build-variant handling)
- **Phase 5:** Event-id resolution design for aggregate facts
- **Phase 6:** Batch-knob invalidation explicit decision

### Phases with Well-Established Patterns

- **Phase 2:** Measured formulas + MCM-03 grading pattern
- **Phase 3:** Mechanical store change + proven perfmon precedent
- **Phase 4:** Direct mcm/perfmon replication
- **Phase 7:** Standard golden-case eval pattern

---

## Confidence Assessment

| Area | Confidence | Basis & Gaps |
|------|------------|-------------|
| **Stack** | HIGH | No new deps; stdlib/already-pinned only. sqlite-vec empirically verified. |
| **Features** | HIGH | Measured reference capture foundation. Anti-features clearly scoped. |
| **Architecture** | HIGH | Verified against v1.2 source. Patterns proven or mechanical. |
| **Pitfalls** | MEDIUM | Healthy-capture validates negative case. No real hung-server capture for recall validation. Fixtures must avoid self-deception. |

### Unresolved Questions (for Phase Planning)

1. **Phase 5 — Event-id resolution:** How does "1,715 idle job-queue threads" resolve to concrete `event_id` set when cited? Not solved by MCM analogy (episodes vs signatures). Recommend ADR before detailed planning.

2. **Phase 6 — Batch-knob invalidation:** Should `embeddings.context`/`batch_size` changes invalidate vectors? ARCHITECTURE: "no, with --re-embed escape hatch"; PITFALLS: "record as ADR". Needs explicit decision.

3. **Phase 1 — Match precedence:** Multiple rules match one frame—which wins? Recommendation: first-match-wins (file order). Needs explicit schema decision.

---

## Sources & Provenance

Research files authored 2026-07-25:

- **MILESTONE-CONTEXT-v1.3.md** — Measured reference-capture facts (thread/signature counts, TID churn, identical-stack %). HIGH confidence.
- **STACK.md** — Technology validation with empirical verification. HIGH confidence.
- **FEATURES.md (Part A)** — Feature landscape cross-checked against mature tools. MEDIUM confidence.
- **ARCHITECTURE.md** — Integration design verified against v1.2 source code. HIGH confidence.
- **PITFALLS.md** — Grounded in project measurements + Linux domain facts. MEDIUM confidence.

---

## Ready for Phase Planning

This synthesis provides:
- ✅ Clear phase structure with explicit dependencies and build order
- ✅ Load-bearing architectural decisions (rules format, module placement, exclusion sequencing)
- ✅ Explicit open questions flagged for design before detailed planning
- ✅ Pitfalls mapped to phases with acceptance criteria
- ✅ Honest confidence assessment and information gaps
- ✅ No new runtime dependencies; all choices conservative and proven

**Next:** `/gsd-plan-phase` for Phase 1 with research flag for frame-matching brittleness validation.
