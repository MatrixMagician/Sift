# Roadmap: Sift — Local-LLM Incident Triage Engine

## Milestones

- ✅ **v1.0 — Core Triage Engine** — Phases 1–8 (SPEC M1–M8) — shipped 2026-07-19
- ✅ **v1.1 — MCM Memory-Pressure Analysis** — Phases 9–11 (MCM-01..07) — shipped 2026-07-20
- ✅ **v1.2 — DSSPerformanceMonitor Correlation** — Phases 12–14 (PERF-01..08) — shipped 2026-07-20
- ✅ **v1.3 — EU-Stack Hang & Slowdown Diagnosis** — Phases 15–20 (EUS-01..12, DET-01) — shipped 2026-07-30

**No active milestone.** Run `/gsd-new-milestone` to scope the next one. Phase numbering
continues from 20.

Full phase details, requirements, and audits for shipped milestones are archived in
`.planning/milestones/` — each `vX.Y-ROADMAP.md` carries the complete phase detail,
`vX.Y-REQUIREMENTS.md` the traceability, `vX.Y-MILESTONE-AUDIT.md` the close-out audit,
and `vX.Y-phases/` the archived phase directories.

## Backlog

Carried forward, unscoped. Nothing here was dropped mid-execution — each was scoped out
at planning time.

- **EUSV2-01** — Cross-reference eu-stack thread state against MCM denial episodes and
  perfmon counters, so a hang can be correlated with memory pressure rather than read
  in isolation.
- **PERFV2-01 / -02 / -03** — perfmon recovery-trend analysis, multi-host correlation,
  and perfmon-only anomaly detection (deferred beyond v1.2).
- **SEED-003 (candidate)** — Sift cannot currently reach its own determinism guarantee:
  it promises byte-identical output "given identical case + config + model + seed" but
  sends neither `seed` nor `temperature`, and `GenerationConfig` has no such field. Filed
  with measured evidence during the v1.3 close as
  `todos/pending/2026-07-30-generation-sampling-not-controlled.md`.

See `.planning/seeds/` for the fuller seed set.
