# Roadmap: Sift — Local-LLM Incident Triage Engine

## Milestones

- ✅ **v1.0 — Core Triage Engine** — Phases 1–8 (SPEC M1–M8) — shipped 2026-07-19
- ✅ **v1.1 — MCM Memory-Pressure Analysis** — Phases 9–11 (MCM-01..07) — shipped 2026-07-20
- ✅ **v1.2 — DSSPerformanceMonitor Correlation** — Phases 12–14 (PERF-01..08) — shipped 2026-07-20

Full phase details, requirements, and audits for shipped milestones are archived in
`.planning/milestones/` — each `vX.Y-ROADMAP.md` carries the complete phase detail,
`vX.Y-REQUIREMENTS.md` the traceability, `vX.Y-MILESTONE-AUDIT.md` the close-out audit,
and `vX.Y-phases/` the archived phase directories.

## Phases

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

<details>
<summary>✅ v1.2 — DSSPerformanceMonitor Correlation (Phases 12–14) — SHIPPED 2026-07-20</summary>

- [x] Phase 12: `dssperfmon` Adapter & Pipeline Exclusion (PERF-01, PERF-02, PERF-03) — completed 2026-07-20
- [x] Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV (PERF-04, PERF-05, PERF-06) — completed 2026-07-20
- [x] Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case (PERF-07, PERF-08) — completed 2026-07-20

Full detail: `.planning/milestones/v1.2-ROADMAP.md`.

</details>

## Progress

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 1–8 (Core Triage Engine) | v1.0 | 36/36 | Complete | 2026-07-16 → 07-19 |
| 9. MCM Episode Detection & Breakdown | v1.1 | 3/3 | Complete | 2026-07-19 |
| 10. Flags, Attribution, `sift mcm` | v1.1 | 4/4 | Complete | 2026-07-19 |
| 11. MCM Facts into `sift analyze` | v1.1 | 3/3 | Complete | 2026-07-20 |
| 12. `dssperfmon` Adapter & Pipeline Exclusion | v1.2 | 4/4 | Complete | 2026-07-20 |
| 13. Correlation, Flags, `sift perfmon` | v1.2 | 6/6 | Complete | 2026-07-20 |
| 14. Perfmon Facts into `sift analyze` | v1.2 | 5/5 | Complete | 2026-07-20 |

## Backlog

- **PERFV2-01** — Recovery-trend analysis (counter behaviour after an episode resolves) — blocked:
  no post-denial evidence exists in current reference data.

- **PERFV2-02** — Multi-host correlation across perfmon CSVs from several cluster nodes.
- **PERFV2-03** — Perfmon-only anomaly detection independent of any MCM episode.

---
*v1.2 shipped 2026-07-20. Next: `/gsd-new-milestone`.*
