# Roadmap: Sift — Local-LLM Incident Triage Engine

## Milestones

- ✅ **v1.0 — Core Triage Engine** — Phases 1–8 (SPEC M1–M8) — shipped 2026-07-19
- ✅ **v1.1 — MCM Memory-Pressure Analysis** — Phases 9–11 (MCM-01..07) — shipped 2026-07-20
- ✅ **v1.2 — DSSPerformanceMonitor Correlation** — Phases 12–14 (PERF-01..08) — shipped 2026-07-20
- 🔵 **v1.3 — EU-Stack Hang & Slowdown Diagnosis** — Phases 15–20 (EUS-01..12, DET-01) — in flight

Full phase details, requirements, and audits for shipped milestones are archived in
`.planning/milestones/` — each `vX.Y-ROADMAP.md` carries the complete phase detail,
`vX.Y-REQUIREMENTS.md` the traceability, `vX.Y-MILESTONE-AUDIT.md` the close-out audit,
and `vX.Y-phases/` the archived phase directories.

## Phases

### v1.3 — EU-Stack Hang & Slowdown Diagnosis (Phases 15–20)

- [x] **Phase 15: Thread-Role Taxonomy & Rules File** - Every thread carries a deterministic role from an editable versioned rules file; unknown frames are reported, never guessed (completed 2026-07-25)
- [x] **Phase 16: Saturation, Contention & Signature Collapse** - Per-pool occupancy, ownership-blind lock convergence, external-wait concentration and signature ranking, all computed model-free (completed 2026-07-25)
- [x] **Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV** - One command produces the full deterministic report from one dump or many, with no DSSErrors log required (completed 2026-07-26)
- [x] **Phase 18: Eu-Stack Facts into `sift analyze`** - Computed eu-stack figures reach the model as cited-not-authored evidence; no-eu-stack prompt stays byte-identical (completed 2026-07-27)
- [ ] **Phase 19: Ranking Exclusion & Regression-Gated Golden Eval** - Thread events leave dedup/embed/cluster/salience once the replacement ships, then the whole path is regression-gated
- [ ] **Phase 20: SEED-002 Embedding Vector Reuse (DET-01)** - Re-analysing an unchanged case reuses stored vectors instead of re-embedding, closing the ADR 0014 exposure

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

## Phase Details

### Phase 15: Thread-Role Taxonomy & Rules File

**Goal**: Every thread in an eu-stack dump carries a deterministic role label, produced by a versioned rules file an engineer can edit without touching Python
**Depends on**: Nothing new — builds on the shipped `eustack` adapter (Phase 5); first phase of v1.3
**Requirements**: EUS-01, EUS-02
**Success Criteria** (what must be TRUE):

  1. Every thread in the reference capture is labelled `idle-parked`, `blocked-on-external`, `blocked-on-lock`, `running` or `unclassified` — the five buckets partition the whole population, no thread left unlabelled
  2. An engineer adds a frame pattern to the versioned TOML rules file, re-runs, and sees the affected threads change role — with no Python edited and no reinstall
  3. Frames matching no rule are counted and reported as `unclassified` with an example frame shown — never folded into a known role, never guessed
  4. The 1,715 `MSIQTask::GetNextPreferredJob` threads in the healthy reference capture read as `idle-parked`, not as blocked or stuck — the 98.9% composition-blind false positive does not reproduce
  5. Classification work scales with distinct stack signatures (93 in the reference capture), not with thread count (3,902)

**Plans**: 6/6 plans executed

Plans:

- [x] 15-01-PLAN.md — Tracer: one thread end-to-end, adapter frames through packaged TOML to a role
- [x] 15-02-PLAN.md — `[eustack] rules_path` config key with CLI > env > TOML > default precedence
- [x] 15-03-PLAN.md — Signature-preserving CI fixture plus its role-blind derivation script
- [x] 15-04-PLAN.md — Strict rules schema, hardened loader, and the rules_path override proof (SC2)
- [x] 15-05-PLAN.md — `analyse_eustack`: role partition, ranked signatures, unclassified reporting
- [x] 15-06-PLAN.md — Curated 24-rule taxonomy, coverage gates and ADR 0015

**Research flag** (resolved at plan time — see `15-CONTEXT.md` D-01/D-05/D-09 and ADR 0015 in plan 15-06): **Needed a design pass at plan time.** Frame-matching strategy is unresolved: enclosing application frame vs leaf priority; match precedence when several rules hit one stack (research recommends first-match-wins in file order, but the schema decision is explicit and unmade); and symbol brittleness across build variants — anchor on qualified names, mirroring ADR 0013's bare-substring collision. Classification reads `Event.raw`, not `Event.message` (`CONDENSED_FRAMES = 5` caps the message; the classifying frame sits 8–19 deep).

### Phase 16: Saturation, Contention & Signature Collapse

**Goal**: An engineer sees why the server is — or demonstrably is not — saturated, from occupancy, lock convergence, external-wait concentration and signature population, every figure computed model-free
**Depends on**: Phase 15 (all four analyses are groupings over taxonomy-labelled threads)
**Requirements**: EUS-03, EUS-04, EUS-05, EUS-06
**Success Criteria** (what must be TRUE):

  1. Per-pool occupancy shows a busy-vs-parked split per pool, so the healthy reference capture's ~3,400 parked pool workers read as idle rather than saturated
  2. Threads converging on a lock-acquisition path are reported with site and count, always labelled ownership-blind — the word "deadlock" never appears in any output
  3. External waits are split by dependency, so the 79 warehouse waits (`CDSSQueryEngine::WaitUntilFinished`) and 78 HTTP waits (`curl_multi_poll`) are separately visible rather than merged into one blocked total
  4. The thread population is collapsed to distinct stack signatures ranked by thread count (3,902 → 93 on the reference capture), each signature carrying its role
  5. Every graded flag prints its raw computed value beside the configured threshold, thresholds are config keys, and the healthy reference capture raises zero flags

**Plans**: 4/4 plans executed

Plans:

- [x] 16-01-PLAN.md — Tracer: per-pool occupancy end-to-end, config key through grouping and grading to a new frozen `SaturationAnalysis` (EUS-03)
- [x] 16-02-PLAN.md — Ownership-blind lock convergence: the D-04 enclosing-frame walk, `LockSite`, the count flag and the synthetic scenario (EUS-04)
- [x] 16-03-PLAN.md — External-wait split by dependency, the no-resolvable-frame flag, signature passthrough and whole-model determinism (EUS-05, EUS-06)
- [x] 16-04-PLAN.md — The D-09 zero-flags gate against the measured reference composition, plus ADR 0016 (EUS-03..06)

**Pattern note**: Graded flags follow the shipped MCM-03 pattern (info/warn/critical, config-tunable). No graded saturation thresholds are invented — EUSV2-03 is explicitly deferred; flags here report measured composition, not authored percentages.
**Planning note**: The committed CI fixture is signature-preserving, not thread-weight-preserving — its unclassified thread share reads 38.1% against the real capture's 1.33%. Success criterion 5's "zero flags" gate therefore runs against the reference capture's measured composition, not against the fixture; loosening a default to make the fixture pass is a rejected resolution (16-04-PLAN.md § S-8).

### Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV

**Goal**: One command turns a case's thread dumps into a deterministic report — full analysis from a single dump, per-signature progression when several are present — working with no DSSErrors log in the case
**Depends on**: Phase 16
**Requirements**: EUS-07, EUS-08, EUS-09
**Success Criteria** (what must be TRUE):

  1. `sift eustack <case>` on a case containing only eu-stack dumps and no DSSErrors log produces a Markdown report plus CSV export and exits 0 — the mcm/perfmon standalone contract
  2. A single-dump case yields the full classification and saturation report; a two-dump case additionally reports per-signature population deltas and which populations advanced
  3. Dump ordering states its basis explicitly, and an ordering that cannot be resolved is flagged loudly rather than assumed — no timestamp is invented (ADR 0012 "record, don't apply" precedent)
  4. Progression is expressed as signature-population change; no unqualified per-TID causal claim appears, because TID reuse is measured (9 exited / 10 new in 60 s on an idle server)
  5. Re-running the command on an unchanged case produces a byte-identical report and CSV, and CSV string cells carrying C++ symbol text pass the formula-injection guard (`_csv_safe` pattern)

**Plans**: 3/3 plans executed

Plans:
**Wave 1**

- [x] 17-01-PLAN.md — Tracer: `sift eustack` end-to-end on a dumps-only case — report + CSV written, exit 0, byte-identical re-run (EUS-09)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 17-02-PLAN.md — Multi-dump ordering (D-01 timestamp basis, D-02 declared fallback + loud flag) and per-signature population deltas (EUS-07, EUS-08)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 17-03-PLAN.md — Progression rendering, per-dump CSV delta columns, and the byte-identity, formula-injection and ownership-blind gates (EUS-07, EUS-09)

**Planning note**: `analyse_eustack`/`analyse_saturation` have shipped since Phase 15/16 but have **zero CLI callers** — this phase is their first wiring, so the CLI integration is net-new work, not a small addition. Both committed eu-stack fixtures were run through the adapter at plan time: `threaddump.txt` carries a real header timestamp (`ts_confidence="exact"`, exercises D-01) while `reference_capture_derivative.txt` carries none (`"missing"`), and the real out-of-repo two-dump reference capture also carries none — so **D-02 is the path real data exercises**, and D-01 needs the synthetic fixture 17-02 authors.

### Phase 18: Eu-Stack Facts into `sift analyze`

**Goal**: `sift analyze` narrates the eu-stack figures the deterministic core computed, each one citable back to real events, and behaves exactly as today on cases with no eu-stack data
**Depends on**: Phase 17
**Requirements**: EUS-10
**Success Criteria** (what must be TRUE):

  1. `sift analyze` on a case with eu-stack dumps carries the computed role-composition, saturation and contention figures into the prompt as cited evidence, preserving `cited ⊆ prompted ⊆ store`
  2. A case with no eu-stack data produces a prompt byte-identical to today's — the existing prompt hash is unchanged, and eu-stack presence never perturbs the MCM or perfmon blocks
  3. The `eustack_facts.md` template contains zero authored digits, and a planted wrong figure provably never reaches the prompt (anti-hallucination test, MCM-06/PERF-07 pattern)
  4. Every aggregate figure quoted in the fact block resolves to a concrete, verifiable `event_id` set that exists in the case store

**Plans**: 3/3 plans executed

Plans:
**Wave 1**

- [x] 18-01-PLAN.md — Tracer: role composition end-to-end into the triage prompt, fourth sentinel block, byte-identity and anti-hallucination gates (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 18-02-PLAN.md — Four Phase-16 groupings as union-then-sample-3 cited aggregates, plus the capped drop-disclosing signature listing (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 18-03-PLAN.md — Multi-dump progression with unverified-order delta suppression, V5 sanitisation gate, measured D-14 headroom, ADR 0017 (wave 3)

**Research flag** (RESOLVED at discuss/plan time — D-01..D-04 in `18-CONTEXT.md` settle it; D-17 resolves the multi-signature sub-case; recorded as ADR 0017 in plan 18-03): **Was an unsolved design question.** How does an aggregate fact ("1,715 idle job-queue threads") resolve back to a citable `event_id` set? This is explicitly **not** solved by analogy to MCM or perfmon: those cite episodes and samples, which are already one-to-one with events; a signature population is one-to-many. Research recommends an ADR before the plan freezes. Fourth copy of the fact-injection pattern — `eustack_facts.py` stays a leaf module (hypothesise imports it, never the reverse) and needs its own fixed cap, matching `_MAX_EPISODES`/`_MAX_GROUPS`, since fact blocks bypass `PromptBudget.fit`.

### Phase 19: Ranking Exclusion & Regression-Gated Golden Eval

**Goal**: Eu-stack thread events stop competing in dedup/embed/cluster/salience now that the deterministic replacement has shipped, and the whole eu-stack path is locked behind golden regression gates
**Depends on**: Phase 18 (exclusion may not land until both `sift eustack` and the `sift analyze` facts have shipped — this ordering is requirement EUS-11's own wording, not a preference)
**Requirements**: EUS-11, EUS-12
**Success Criteria** (what must be TRUE):

  1. Ingesting eu-stack dumps leaves cluster and salience output byte-identical to the same case without them, while every thread event remains individually retrievable and citable
  2. The real healthy reference capture, run as the negative golden case, reports no hang and raises zero flags
  3. Synthetic hang fixtures — labelled in the harness as authored, not observed — are detected, and stay detected under cosmetic mutation (renumbered TIDs, reordered threads, differing instruction addresses)
  4. `sift eval` exits non-zero on threshold regression across both the negative and the positive eu-stack cases, and a vacuous pass (empty positive set) is impossible

**Plans**: 4 plans

Plans:
- [ ] 19-01-PLAN.md — EUS-11: `EXCLUDED_FROM_RANKING` gains `"eustack"`, `analyze` stops dead-ending an eu-stack-only case, byte-identity and citability proofs
- [ ] 19-02-PLAN.md — EUS-12 contracts: the `expect_eustack` truth block, its exclusion from the four keyword aggregates, and the LLM-free `_run_eustack_case` dispatch (opens with a blocking decision on flag semantics)
- [ ] 19-03-PLAN.md — EUS-12 gate + negative case: the `eustack_detection_rate` floor, the zero-eu-stack-cases vacuity guard, and `eval/cases/eustack-healthy/` derived from the real capture
- [ ] 19-04-PLAN.md — EUS-12 positives: the synthetic warehouse-pool-exhaustion case, its cosmetic-mutation twin, and the gate-bites sensitivity test

**Sequencing note (within phase)**: EUS-11 lands **first**, before EUS-12's fixtures are authored, so the golden fixtures reflect final ranking behaviour rather than a moving target. Exclusion stays a property of source kind through the single `EXCLUDED_FROM_RANKING` seam (`store.py`) with no opt-out flag and no composition-dependent middle option — the D-07 principle. Fixtures must derive from the documented hang scenario, never from the rules-file strings, or the eval proves only that the code runs.

### Phase 20: SEED-002 Embedding Vector Reuse (DET-01)

**Goal**: Re-running `sift analyze` on an unchanged case reuses persisted embedding vectors instead of re-embedding, closing the ADR 0014 batch-composition determinism exposure and removing the dominant cost of a re-analyse
**Depends on**: Nothing in v1.3 — **fully independent of EUS-01…EUS-12.** Touches `pipeline/cluster.py` and the vectors table, not the eu-stack analyser. Sequence it anywhere; the only coupling to Phase 19 is diff proximity in `store.py`/`cluster.py`, which is a scheduling concern, not a functional dependency.
**Requirements**: DET-01
**Success Criteria** (what must be TRUE):

  1. A second `sift analyze` on an unchanged case reports the split explicitly ("Embedded N new exemplars, reused M stored vectors") with zero new embeddings on a case whose exemplars are unchanged — assertable from the printed/returned counts, without inspecting mock call counts
  2. A mixed hit/miss run produces output byte-identical to a full re-embed of the same exemplars, because hits and misses splice back in the original group order
  3. Changing the embedding model or its dimension forces a full re-embed rather than silently reusing stale vectors under a new model's identity
  4. Changing a batch knob (`embeddings.context` / `batch_size` / `max_input_chars`) does **not** invalidate reuse, and `sift analyze --re-embed` is the explicit operator escape hatch that applies it

**Plans**: TBD
**ADR flag**: The batch-knob decision is **already settled** — a knob change does not invalidate reuse; model or dimension change does; `--re-embed` is the escape hatch. The plan-time task is to **record** it as an ADR in `docs/decisions/`, not to re-decide it. Rationale: not invalidating is precisely what makes a re-run reproducible; invalidating would re-embed under a new batch layout on the first run after any knob change, reopening the hysteresis SEED-002 exists to eliminate.
**Drop candidate**: If v1.3 runs hot, this is the natural phase to defer — it is a determinism and cost fix, not a milestone capability, and no EUS requirement depends on it. Deferring it leaves ADR 0014's exposure documented but not closed.

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
| 15. Thread-Role Taxonomy & Rules File | v1.3 | 0/6 | Complete    | 2026-07-25 |
| 16. Saturation, Contention & Signature Collapse | v1.3 | 0/? | Complete    | 2026-07-25 |
| 17. Multi-Dump Progression & `sift eustack` | v1.3 | 0/3 | Complete    | 2026-07-26 |
| 18. Eu-Stack Facts into `sift analyze` | v1.3 | 0/? | Complete    | 2026-07-27 |
| 19. Ranking Exclusion & Golden Eval | v1.3 | 0/? | Not started | - |
| 20. SEED-002 Embedding Vector Reuse | v1.3 | 0/? | Not started | - |

## Backlog

- **EUSV2-01** — Cross-reference eu-stack thread state against MCM denial episodes and perfmon
  counters — deferred: single-source analysis must prove itself first, mirroring how v1.2 followed v1.1.

- **EUSV2-02** — `/proc/<tid>/stat` state codes alongside eu-stack frames — orthogonal signal, but
  needs a capture-pipeline change outside this milestone's ingestion format.

- **EUSV2-03** — Graded saturation thresholds ("N% busy = warning") — no authoritative source for
  defensible numbers; research explicitly declined to invent them.

- **PERFV2-01** — Recovery-trend analysis (counter behaviour after an episode resolves) — blocked:
  no post-denial evidence exists in current reference data.

- **PERFV2-02** — Multi-host correlation across perfmon CSVs from several cluster nodes.
- **PERFV2-03** — Perfmon-only anomaly detection independent of any MCM episode.

---
*v1.3 roadmap created 2026-07-25 — Phases 15–20, 13 requirements (EUS-01..12, DET-01), 100% mapped.*
