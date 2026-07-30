# Milestones

## v1.3 EU-Stack Hang & Slowdown Diagnosis (Shipped: 2026-07-30)

**Phases completed:** 6 phases (15–20), 25 plans

**Delivered:** a third evidence source — native `eu-stack` thread dumps — turned into a
deterministic hang/slowdown diagnosis, plus the embedding-reuse fix that closes ADR 0014's
determinism exposure for every re-analysis. The intuitive mechanism was killed **before**
scoping: "identical stack after 60 s = stuck" flags 98.9% of threads (3,849 of 3,893 common
TIDs) on a *healthy* server, so composition — not motion — is the signal (3,902 threads
collapse to 93 signatures). Any future phase reintroducing a motion-based check reopens a
falsified mechanism. The deterministic-core-vs-LLM boundary is preserved verbatim from v1.1/v1.2:
every figure is COMPUTED before generation and only then handed to the model as citable
evidence — confirmed end to end on the real 7,807-event capture against a live model.

**Key accomplishments:**

- **Phase 15** — the load-bearing foundation: a 24-rule, operator-editable thread-role taxonomy
  in a versioned TOML rules file, rule-major first-match-wins, with 98.67% thread / 56.99%
  signature coverage measured on the real 3,902-thread capture. Unresolvable frames are
  *reported*, never guessed, and the unclassified residual splits into matched-no-rule vs
  no-resolvable-frame. Lock **ownership** is a permanent non-goal, asserted by a test that bans
  the vocabulary (EUS-01, EUS-02; ADR 0015).

- **Phase 16** — per-pool occupancy, ownership-blind lock convergence, external-dependency wait
  concentration and signature ranking, all computed model-free. One `SaturationFlag` record
  carries value/warn/critical together so a threshold can never travel apart from the figure it
  grades (EUS-03…EUS-06; ADR 0016).

- **Phase 17** — multi-dump progression and the standalone `sift eustack` report + CSV, working
  from one dump or many with no DSSErrors log at all. Thread-identity continuity across dumps is
  explicitly *not* claimed (TID reuse makes it unsound), and the scope note says so in the
  output (EUS-07, EUS-08, EUS-09; ADR 0017).

- **Phase 18** — computed eu-stack figures spliced into `sift analyze` as cited-not-authored
  evidence, with the no-eu-stack prompt proven byte-identical by a frozen hash (EUS-10).

- **Phase 19** — eu-stack events join `EXCLUDED_FROM_RANKING` now that the deterministic
  replacement ships, and `sift analyze` stops dead-ending on eu-stack-only cases. Sequenced
  deliberately *after* the replacement existed, so no regression window opened. Gated by a fifth
  eval floor, `eustack_detection_rate = 1.00`, scored entirely LLM-free (EUS-11, EUS-12).

- **Phase 20** — embedding vector reuse: a second `sift analyze` on an unchanged case makes
  **zero** embedding HTTP calls, verified against a live Lemonade endpoint by server-side request
  counting. Model or dimension changes invalidate; batch-knob changes deliberately do not
  (invalidating would re-embed under a *new* batch layout on the first run after any
  reconfiguration, reopening the exact hysteresis the phase exists to eliminate). A dimension
  change is now recoverable via `--re-embed` instead of wedging the case. Also fixes a
  precedence inversion where a server-reported `n_ctx` silently overrode a configured
  `generation.context` (DET-01; ADR 0018).

**Verification:** 879 tests pass, ruff clean, pyright at its pre-existing baseline. Both
previously-deferred human-verification items were **executed** against the operator's live
Lemonade instance rather than carried forward, including Phase 19's real-capture narration check
(7,807 events, 0 template groups, 2 hypotheses, all 14 cited ids resolving to `eustack` events,
narrated figures matching `sift eustack` exactly).

**Known deferred items at close:** 2 (see STATE.md Deferred Items) — one new-scope todo filed
during the audit, one `audit-open` false positive over already-shipped work. Neither is a v1.3
defect.

**Audit finding:** `sift eval` fails live on three of five floors, traced to the endpoint's
sampling configuration (`seed=4294967295` random, `temperature=0.8`), not to any v1.3 change —
the three eu-stack floors v1.3 added all pass, LLM-free. Diagnosing it exposed two real bugs that
made `sift doctor`'s random-seed determinism warning **dead code** on every real llama.cpp build
(wrong nesting, and a `seed < 0` test against a UINT32_MAX sentinel); both fixed with six
regression tests, four of which fail against the previous code. A temperature warning was added
alongside. The archive step surfaced a third defect: three eu-stack vocabulary tests parsed the
forbidden lock-ownership term out of `.planning/REQUIREMENTS.md` at runtime, so archiving that
document broke the suite — the D-05 invariant now lives in the product as
`eustack_vocabulary.PROHIBITED_OWNERSHIP_TERMS`. See
`milestones/v1.3-MILESTONE-AUDIT.md`.

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
