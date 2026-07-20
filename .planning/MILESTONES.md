# Milestones

## v1.2 DSSPerformanceMonitor Correlation (Shipped: 2026-07-20)

**Phases completed:** 3 phases (12–14), 15 plans

**Delivered:** a second, independent evidence source — DSSPerformanceMonitor PDH-CSV exports —
ingested as deterministic, citable time-series events and correlated against the MCM denial
episodes v1.1 already detects, turning a point-in-time snapshot into a corroborated lead-in
timeline. The deterministic-core-vs-LLM boundary is preserved verbatim from v1.1: every counter
figure is COMPUTED before generation and only then handed to the model as citable evidence — the
model narrates the numbers, it never authors them.

**Key accomplishments:**

- **Phase 12** — new `dssperfmon` adapter ingesting PDH-CSV rows as deterministic
  (`event_id = sha256(file, byte_offset)`), idempotent, UTC-normalised, individually citable
  events; the header zone/offset recorded in `attrs` as evidence, not applied as a shift
  (ADR 0012, amended after measurement); a sniff-collision with `dsserrors` fixed by qualifying the
  bare `MCM` marker to `AvailableMCM`/`MCM Settings` (ADR 0013); and perfmon events held out of
  dedup/embed/cluster/salience through a single `EXCLUDED_FROM_RANKING` store seam, so cluster
  output is byte-identical with or without a perfmon CSV while every sample stays citable
  (PERF-01, PERF-02, PERF-03).

- **Phase 13** — a deterministic, machine-independent correlator annotating each MCM episode with
  its counter value at denial, slope, and peak over MCM-04's existing lead-up window (no new window
  logic); graded correlation hazards — CSV/log non-overlap, always-zero `Total MCM Denial`, and
  counter-set drift — reported, never used as inputs; shipped as the standalone `sift perfmon
  <case>` report + trend CSV, working on a case with a perfmon CSV and no DSSErrors log at all
  (PERF-04, PERF-05, PERF-06).

- **Phase 14** — the computed perfmon figures spliced into `sift analyze` as **citable** evidence
  (`cited ⊆ prompted ⊆ store`, printed `[evt:]` ids unioned into `prompted_ids`); an
  anti-hallucination test proves a planted wrong figure never reaches the prompt; the fact block is
  a versioned zero-digit `perfmon_facts.md` template, byte-identical-additive when no perfmon data
  is present; and a regression-gated `perfmon-denial` golden eval case with a non-vacuous
  citation-sensitivity gate (PERF-07, PERF-08).

**Quality:** all 8 PERF requirements satisfied; milestone audit PASSED (8/8 reqs, integration 6/6,
flows 3/3, Nyquist COMPLIANT on all three phases); `ruff` clean, `pyright` 0 errors, `pytest`
658 passed. Runtime code byte-identical from phase-14 completion through close.

**Deferred:** PERFV2-01 recovery-trend (no post-denial evidence exists), PERFV2-02 multi-host
correlation, PERFV2-03 perfmon-only anomaly detection → v2. Three non-blocking code-review
tech-debt todos acknowledged at close (see STATE.md Deferred Items).

---

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
