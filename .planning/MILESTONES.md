# Milestones

## v1.1 MCM Memory-Pressure Analysis (Shipped: 2026-07-20)

**Phases completed:** 3 phases (9–11), 9 plans

**Delivered:** a deterministic MCM memory-pressure forensics layer over the `dsserrors` adapter —
detect every denial episode, parse the denial-time memory breakdown, grade machine-independent
diagnostic flags, attribute lead-up memory by OID/Source/SID, ship a `sift mcm` report + CSV
bundle, and feed those computed facts into `sift analyze` as **cited** evidence (never
model-authored).

**Key accomplishments:**

- **Phase 9** — deterministic, non-interactive detection of every MCM denial episode (full
  lifecycle) plus the denial-time physical/virtual memory breakdown, computed model-free over the
  ingested event stream (MCM-01, MCM-02).
- **Phase 10** — graded diagnostic flags (info/warn/critical, config-tunable thresholds), an
  auto-selected lead-up window, and per-OID/Source/SID attribution — shipped as the standalone
  `sift mcm <case>` command writing a `<case>/mcm/` report + `mcm_attribution.csv` bundle
  (MCM-03, MCM-04, MCM-05).
- **Phase 11** — the same deterministic facts injected into `sift analyze` as **citable**
  evidence inside `hypothesise()` (`cited ⊆ prompted ⊆ store`); an anti-hallucination test proves
  the model cannot alter or invent the figures; the fact block is a versioned `mcm_facts.md`
  template (no numbers authored in the template) and is byte-identical-additive when no MCM data
  is present; a regression-gated `mcm-denial` golden eval case, MCM-sensitive via
  `citation_validity_rate` (MCM-06, MCM-07).

**Quality:** all 7 MCM requirements satisfied; milestone audit PASSED (7/7 reqs, integration 4/4,
flows 2/2); `ruff` clean, `pyright` 0 errors, `pytest` 537 passed. Phase 11 cleared all four
post-execution gates (verification 5/5, security SECURED/0-open, Nyquist compliant, code-review —
WR-01 fixed: MCM fact block capped at 8 episodes; 2 cosmetic INFO items tracked as a todo).

**Deferred:** SEED-001 / PERF-01 (DSSPerformanceMonitor PDH-CSV correlation) → v2.

---

## v1.0 Core Triage Engine (Shipped: 2026-07-19)

**Phases completed:** 8 phases (1–8, SPEC M1–M8), 36 plans

**Delivered:** the full offline incident-triage engine — deterministic ingest → SQLite case store
→ template dedup + local-embedding clustering → salience → RAG → citation-gated LLM hypotheses →
Markdown/JSON/PDF reports, an evaluation harness with golden cases, and `uv tool install` /
Podman Quadlet packaging. Zero network egress except the configured localhost inference endpoint;
every hypothesis cites verifiable event IDs (the load-bearing anti-hallucination mechanism).

---
