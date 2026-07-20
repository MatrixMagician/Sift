# Roadmap: Sift — Local-LLM Incident Triage Engine

## Milestones

- ✅ **v1.0 — Core Triage Engine** — Phases 1–8 (SPEC M1–M8) — shipped 2026-07-19
- ✅ **v1.1 — MCM Memory-Pressure Analysis** — Phases 9–11 (MCM-01..07) — shipped 2026-07-20
- 🔵 **v1.2 — DSSPerformanceMonitor Correlation** — Phases 12–14 (PERF-01..08) — active

Full phase details, requirements, and audits for shipped milestones are archived in
`.planning/milestones/` — `v1.1-ROADMAP.md` carries the complete Phase 1–11 detail,
`v1.1-REQUIREMENTS.md` the traceability, `v1.1-MILESTONE-AUDIT.md` the close-out audit,
and `v1.1-phases/` the archived phase directories.

## Overview — v1.2

v1.2 is v1.1's shape, one layer out: **adapter → deterministic analyser/correlator → report →
LLM facts → eval**. v1.1 built a model-free MCM denial forensics layer over the `dsserrors`
adapter; v1.2 brings a second, independent evidence source alongside it — DSSPerformanceMonitor
PDH-CSV exports — and correlates its memory counters against the MCM episodes v1.1 already
detects, turning a point-in-time snapshot into a corroborated lead-in timeline.

The **deterministic-core-vs-LLM boundary is preserved verbatim from v1.1**: every numeric figure
(counter value at denial, slope across the window, peak) is COMPUTED before generation and only
then handed to the model as citable evidence. The model may narrate the numbers; it may never
author them.

Phase numbering continues from Phase 11. Each phase inherits the project quality gate:
`ruff check`, `pyright`, and `pytest` clean is part of "done"; no phase begins while the previous
one is red.

Reference data (Hartford deny/snapshot CSVs, matching logs, and the observed lead-in counter
trend) is tabulated in `.planning/REQUIREMENTS.md` § Reference Data — phases point at it rather
than restating figures.

## Phases

**Phase Numbering:**

- Integer phases (12, 13, 14): Planned milestone work
- Decimal phases (12.1, 12.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>✅ v1.0 — Core Triage Engine (Phases 1–8, M1–M8) — SHIPPED 2026-07-19</summary>

- [x] Phase 1: Skeleton, Event Contract & genericlog Adapter (M1) — completed 2026-07-16
- [x] Phase 2: Case Store & Template Dedup (M2) — completed 2026-07-17
- [x] Phase 3: Inference Client, Doctor, Embeddings & Clustering (M3) — completed 2026-07-17
- [x] Phase 4: Salience, RAG & Citation-Gated Hypotheses (M4) — completed 2026-07-17
- [x] Phase 5: Domain Adapters (journald, dsserrors, eustack) (M5) — completed 2026-07-18
- [x] Phase 6: Renderers & KB Retrieval (M6) — completed 2026-07-18
- [x] Phase 7: Evaluation Harness & Golden Cases (M7) — completed 2026-07-19
- [x] Phase 8: Packaging & Deploy (M8) — completed 2026-07-19

</details>

<details>
<summary>✅ v1.1 — MCM Memory-Pressure Analysis (Phases 9–11) — SHIPPED 2026-07-20</summary>

- [x] Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown (MCM-01, MCM-02) — completed 2026-07-19
- [x] Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV (MCM-03, MCM-04, MCM-05) — completed 2026-07-19
- [x] Phase 11: MCM Facts into `sift analyze` + Golden Eval Case (MCM-06, MCM-07) — completed 2026-07-20

</details>

**Milestone v1.2 — DSSPerformanceMonitor Correlation (this milestone)**

- [ ] **Phase 12: `dssperfmon` Adapter & Pipeline Exclusion** - PDH-CSV ingestion as deterministic, citable, UTC-normalised time-series events, held out of dedup/embed/cluster/salience by source kind (PERF-01, PERF-02, PERF-03)
- [ ] **Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV** - Each MCM episode annotated with its corroborating counter trend over MCM-04's existing lead-up window, deterministic correlation-hazard flags, shipped as the standalone `sift perfmon <case>` report + CSV (PERF-04, PERF-05, PERF-06)
- [ ] **Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case** - Computed perfmon figures injected into `sift analyze` as cited evidence (never model-authored) plus a regression-gated perfmon golden case (PERF-07, PERF-08)

## Phase Details

### Phase 12: `dssperfmon` Adapter & Pipeline Exclusion

**Goal**: An engineer can ingest a DSSPerformanceMonitor PDH-CSV into a case and get every sample
row back as a deterministic, individually citable, UTC-normalised event — without those samples
perturbing any existing clustering output

**Depends on**: Phase 5 (adapter Protocol + `ConfigurableAdapter` base), Phase 2 (case store,
template dedup), Phase 3 (embeddings, clustering), Phase 4 (salience) — all shipped

**Requirements**: PERF-01, PERF-02, PERF-03

**Success Criteria** (what must be TRUE):

  1. Engineer runs `sift ingest` on a case containing the Hartford deny CSV and gets one event per
     sample row, each with `event_id = sha256(source_file, byte_offset)[:16]`; a second `sift ingest`
     adds zero new events
  2. Sniffing recognises the `(PDH-CSV 4.0)` header without an `--adapter` override, and sample
     timestamps are normalised through `base.to_utc` with `ts_confidence` recorded — with the header's
     declared zone/offset (e.g. `(Eastern Standard Time)(300)`) **recorded in `attrs` as evidence, not
     applied as a shift**, so a perfmon CSV and its paired DSSErrors log share one timeline
     (ADR 0012; amended 2026-07-20 after measurement showed applying the bias put the CSV 5 h after
     the denial it precedes by 6 s)
  3. Blank, malformed, or non-numeric counter values become `severity="unknown"` events rather than
     vanishing, and per-file parse coverage reflects them — nothing disappears silently
  4. Ingesting the same case with and without the perfmon CSV produces byte-identical cluster output
     (`sift show clusters`), proving perfmon events are excluded from dedup, embedding, clustering,
     and salience by source kind
  5. Every perfmon sample remains individually retrievable by `event_id` through the normal store and
     `sift show events` paths — excluded from ranking, never excluded from citation

**Notes**:

- **Cross-cutting integration risk (PERF-03):** the exclusion touches EXISTING shipped pipeline
  stages — `pipeline/dedup.py`, `pipeline/cluster.py`, `pipeline/salience.py` — not just the new
  adapter module. This is the only place in v1.2 where the "adding an adapter requires zero changes
  outside a new module" convention is deliberately broken; the exclusion predicate should live in
  one place (source-kind filter) rather than being re-implemented per stage. Regression risk to
  v1.0/v1.1 cluster output is the phase's main hazard — criterion 4 is the guard.
- No downsampling on ingest (breaks byte-offset determinism, loses slope resolution) — see
  REQUIREMENTS.md § Out of Scope.
- Reference artefacts and the 23-counter set: REQUIREMENTS.md § Reference Data.

**Plans**: TBD

---

### Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV

**Goal**: An engineer sees each MCM denial episode corroborated by what the machine's memory
counters were actually doing in the lead-up — and is warned loudly when the two artefacts cannot
honestly be joined

**Depends on**: Phase 12 (perfmon events in the store), Phase 10 (MCM-04's auto-selected lead-up
window and `analyse_mcm` orchestration — shipped)

**Requirements**: PERF-04, PERF-05, PERF-06

**Success Criteria** (what must be TRUE):

  1. Engineer runs the correlator on the Hartford deny case and sees each detected MCM episode
     annotated with counter value at denial time, slope across the window, and peak — computed over
     the **same** lead-up window MCM-04 already produces, so the trend and the OID/Source/SID
     attribution describe an identical time span
  2. Engineer running the same case twice on different machines gets identical figures and identical
     flags — the correlator is deterministic and machine-independent, with no model involvement
  3. Engineer whose CSV and log do not overlap in time (wrong timezone, wrong host, wrong day) gets a
     loud non-overlap flag instead of a silently fabricated correlation
  4. Engineer sees an explicit flag when `Total MCM Denial` reads zero across a window containing
     detected denials, and when the counter set drifts mid-file — reported as hazards, never used as
     correlation inputs
  5. Engineer can run `sift perfmon <case>` on a case containing a perfmon CSV and **no DSSErrors log
     at all** and get a counter-trend report plus CSV export, exit 0, no crash and no empty-episode
     traceback

**Notes**:

- PERF-04 **reuses** the window MCM-04 computes (v1.1, Phase 10). This is a dependency on existing
  code, not new window logic — do not re-derive a window here.
- The `Total MCM Denial` counter reads 0 across all 13,596 Hartford deny samples despite confirmed
  denials. It is a REPORTED FLAG (criterion 4), never a correlation input.
- The Hartford CSV ends 6 s before the denial banner: lead-in is fully covered, **no post-recovery
  data exists**. Recovery-trend analysis is explicitly deferred (PERFV2-01).
- Timezone is trusted from the PDH header, never inferred by maximising window overlap — that
  heuristic can invent an alignment that isn't real (REQUIREMENTS.md § Out of Scope).
- Mirrors Phase 10's shape: analyser + graded flags + standalone command with report/CSV bundle.

**Plans**: TBD

---

### Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case

**Goal**: The triage report an engineer already reads now carries corroborating counter evidence the
model can cite but cannot author — and a regression gate stops that from quietly degrading

**Depends on**: Phase 13 (computed correlation figures), Phase 11 (`mcm_facts` splice pattern,
`prompted_ids` union, golden-case harness — shipped)

**Requirements**: PERF-07, PERF-08

**Success Criteria** (what must be TRUE):

  1. Engineer running `sift analyze` on a case with perfmon data sees hypotheses that cite perfmon
     evidence by `event_id`, with `cited ⊆ prompted ⊆ store` preserved
  2. Engineer can confirm the figures in the report match the deterministic correlator's output
     exactly — the fact block is computed before generation, so an adversarial or hallucinating model
     cannot alter or invent a number (anti-hallucination test, mirroring Phase 11's)
  3. Engineer running `sift analyze` on a case with **no** perfmon data gets a byte-identical prompt
     to today's — the integration is strictly additive
  4. Engineer sees the perfmon fact block rendered from a versioned `prompts/*.md` template
     containing zero authored digits, so prompt iteration needs no Python change
  5. Engineer running `sift eval` gets a non-zero exit when correlation output regresses against the
     golden perfmon case

**Notes**:

- Directly mirrors Phase 11 (MCM-06/MCM-07). Reuse the established mechanics: figures built
  pre-generation, printed `[evt:]` ids unioned into `prompted_ids`, no-data prompt guarded by a
  golden hash, fact template holds no numbers.
- Golden-case candidates: the Hartford deny CSV+log pair (primary) and the snapshot CSV+logs pair
  (second candidate) — REQUIREMENTS.md § Reference Data.
- Note the Phase 11 precedent that the fact block is capped (8 episodes) to bound prompt growth;
  perfmon facts need an equivalent bound given 13,596 samples per file.

**Plans**: TBD

## Progress

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 1–8 (Core Triage Engine) | v1.0 | 36/36 | Complete | 2026-07-16 → 07-19 |
| 9. MCM Episode Detection & Breakdown | v1.1 | 3/3 | Complete | 2026-07-19 |
| 10. Flags, Attribution, `sift mcm` | v1.1 | 4/4 | Complete | 2026-07-19 |
| 11. MCM Facts into `sift analyze` | v1.1 | 3/3 | Complete | 2026-07-20 |
| 12. `dssperfmon` Adapter & Pipeline Exclusion | v1.2 | 0/? | Not started | - |
| 13. Correlation, Flags, `sift perfmon` | v1.2 | 0/? | Not started | - |
| 14. Perfmon Facts into `sift analyze` | v1.2 | 0/? | Not started | - |

## Backlog

- **PERFV2-01** — Recovery-trend analysis (counter behaviour after an episode resolves) — blocked:
  no post-denial evidence exists in current reference data.
- **PERFV2-02** — Multi-host correlation across perfmon CSVs from several cluster nodes.
- **PERFV2-03** — Perfmon-only anomaly detection independent of any MCM episode.

---
*v1.2 roadmap created 2026-07-20. Next: `/gsd-plan-phase 12`.*
