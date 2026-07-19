# Roadmap: Sift — Local-LLM Incident Triage Engine

## Overview

Sift is built write-path-first: the deterministic ingest → store → dedup funnel (Phases 1–2) is fully testable with zero LLM infrastructure. The first network surface arrives in Phase 3 (inference client, doctor, embeddings, clustering), the core value lands in Phase 4 (salience → RAG → citation-gated hypotheses), and the domain adapters follow in Phase 5 once the end-to-end pipeline is proven on the cheapest adapter. Phases 6–8 add reviewable reports + KB retrieval, the evaluation harness with golden cases, and packaging. Phase numbering follows SPEC.md milestones M1–M8 one-to-one; each phase inherits its milestone's acceptance criteria, and no phase begins while the previous one is red (`ruff`, `pyright`, `pytest` clean).

**Milestone v1.1 (Phases 9–11) — MCM Memory-Pressure Analysis** continues the numbering. It adds a deterministic quantitative layer over the existing `dsserrors` adapter, integrating and extending the reference script `analyze_dss8.py`: detect every MCM denial episode, parse the denial-time memory breakdown, emit machine-independent diagnostic flags, attribute lead-up memory by OID/Source/SID, ship a `sift mcm` report + CSV, and feed those deterministic facts into `sift analyze` as cited evidence. The numeric core is strictly separate from the LLM — figures are computed, never authored by the model (citation integrity is load-bearing). Validated against the real Hartford deny log. DSSPerformanceMonitor CSV time-series correlation (PERF-01) is deferred to v2 (SEED-001).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

**Milestone v1.0 — Core Triage Engine (M1–M8, complete)**

- [x] **Phase 1: Skeleton, Event Contract & genericlog Adapter** - CLI skeleton, frozen Event schema, format auto-detection, robust fallback parser with idempotent ingest (M1) (completed 2026-07-16)
- [x] **Phase 2: Case Store & Template Dedup** - Portable SQLite case store with migrations, zstd compression, and no-ML template deduplication at 100 MB scale (M2) (completed 2026-07-17)
- [x] **Phase 3: Inference Client, Doctor, Embeddings & Clustering** - Loopback-guarded OpenAI-compatible client, `sift doctor`, batched embeddings, HDBSCAN semantic clustering, LLM cluster labels (M3) (completed 2026-07-17)
- [x] **Phase 4: Salience, RAG & Citation-Gated Hypotheses** - Salience ranking, budgeted triage prompt, enforced JSON contract, "cited ⊆ prompted" citation validation (M4) (completed 2026-07-17)
- [x] **Phase 5: Domain Adapters (journald, dsserrors, eustack)** - Parallel-safe leaf adapters encoding MicroStrategy and systemd domain knowledge (M5) (completed 2026-07-18)
- [x] **Phase 6: Renderers & KB Retrieval** - Markdown/JSON/PDF reports with evidence appendix, reproducibility contract, knowledge-base retrieval (M6) (completed 2026-07-18)
- [x] **Phase 7: Evaluation Harness & Golden Cases** - ≥5 golden incidents, metric table, CI thresholds, optional LLM-as-judge (M7) (completed 2026-07-19)
- [x] **Phase 8: Packaging & Deploy** - `uv tool install` distribution and optional Podman Quadlet deployment (M8) (completed 2026-07-19)

**Milestone v1.1 — MCM Memory-Pressure Analysis (this milestone)**

- [x] **Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown** - Deterministic, non-interactive detection of every MCM denial episode (full lifecycle) plus the denial-time physical/virtual memory breakdown and MCM settings (MCM-01, MCM-02) (completed 2026-07-19)
- [ ] **Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV** - Machine-independent diagnostic flags, an auto-selected lead-up window, per-OID/Source/SID attribution, shipped as the `sift mcm <case>` report + CSV export (MCM-03, MCM-04, MCM-05)
- [ ] **Phase 11: MCM Facts into `sift analyze` + Golden Eval Case** - Deterministic MCM facts fed into `sift analyze` as cited evidence (never model-authored) plus a regression-gated MCM golden case (MCM-06, MCM-07)

## Phase Details

### Phase 1: Skeleton, Event Contract & genericlog Adapter

**Goal**: A user can turn a directory of ordinary logs into a queryable case of canonical, deterministic events — nothing dropped silently
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: INGST-01, INGST-02, INGST-03, INGST-04, INGST-05, INGST-06, INGST-10, INGST-11, CLI-01
**Success Criteria** (what must be TRUE):

  1. User can run `sift new <case> --input <dir>` then `sift ingest <case>` on a fixture log and get canonical events with deterministic IDs and a per-file parse-coverage report ≥ 99% on the fixture
  2. Re-running `sift ingest` on the same case adds zero new events
  3. Unknown or low-confidence files fall back to genericlog automatically, and `--adapter glob=name` overrides detection; unparseable regions surface as `severity="unknown"` events rather than vanishing
  4. Multi-line records (stack traces, continuation lines) ingest as single events, and gzip/zstd-compressed inputs work without manual decompression
  5. Timestamps normalise to UTC with `ts_confidence` recorded (per-node timezone override supported), and CLI config resolves flags > `SIFT_*` env > `~/.config/sift/config.toml` > defaults

**Plans:** 5/5 plans complete

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Package legitimacy checkpoint, uv/Typer scaffold, quality gates, RED walking-skeleton e2e test (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Frozen Event/Adapter contracts, CaseStore, genericlog v0, e2e GREEN (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03-PLAN.md — genericlog depth: timestamp ladder, encodings, caps, coverage, gzip/zstd, UTC/tz (wave 3)
- [x] 01-04-PLAN.md — Config precedence, sniff auto-detection + `--adapter` override, CLI hardening (wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-05-PLAN.md — docs/decisions ADRs + M1 acceptance suite (≥99% coverage, idempotency, determinism) (wave 4)

### Phase 2: Case Store & Template Dedup

**Goal**: The full write path works at production scale with zero LLM dependency — a 100 MB log collapses into inspectable template groups in a single portable file
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: STORE-01, STORE-02, STORE-04, CLUS-01, CLI-03
**Success Criteria** (what must be TRUE):

  1. A 100 MB synthetic log (generator script included in tests) ingests in < 60 s on CPU, and each case is one portable `case.db` — deleting the file deletes the case
  2. Template dedup (masking numbers, hex, UUIDs, SIDs, paths, timestamps) reduces distinct groups by ≥ 90% on the repetitive fixture, with count, first/last seen, and exemplars per group
  3. User can inspect stored data via `sift show <case> events|clusters [--filter …]` before any AI is involved
  4. Schema migrations run via `PRAGMA user_version`, and `raw` text > 4 KB is zstd-compressed transparently
  5. Long-running ingest shows progress feedback instead of a silent hang

**Plans:** 4/4 plans complete

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Store v2 (migration 2, transparent zstd) + pipeline/dedup masking + `show clusters` end-to-end slice (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — Batched streaming ingest + stderr progress, 100 MB generator + < 60 s perf gate, STORE-01 portability (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md — Allowlisted `--filter` on `show events|clusters` + column-scoped streaming show (wave 3)

**Gap closure** *(from 02-VERIFICATION.md, status gaps_found 20/24)*

- [x] 02-04-PLAN.md — Close verifier gaps: CR-01 per-file savepoint accounting, WR-01 whole-line show sanitisation, WR-05 duplicate --filter rejection, REQUIREMENTS.md partial-scope notes (+ WR-02/03/04, IN-03/04 ride-alongs) (wave 1)

### Phase 3: Inference Client, Doctor, Embeddings & Clustering

**Goal**: Sift talks to local inference safely and verifiably — endpoints health-checked, embeddings dimension-guarded, synonymous template groups merged into labelled clusters
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04, STORE-03, CLUS-02, CLUS-03, RAG-05, CLI-02, EVAL-05
**Success Criteria** (what must be TRUE):

  1. `sift doctor` passes against a live llama-server: verifies both endpoints with real round-trips (including an actual embedding call), reports model IDs, checks embedding dimension against any existing index, and warns on determinism-breaking server configs (e.g. multi-slot)
  2. Embeddings persist with model identity and dimension recorded in `meta`; a mismatch on reload is a hard error, and llama.cpp-specific features are feature-detected so Lemonade Server works unmodified
  3. HDBSCAN (L2-normalised, `min_cluster_size=2`) merges the planted synonymous template groups in the fixture; noise points become singleton clusters, and the config-driven agglomerative fallback works
  4. Each cluster gets a short LLM-generated label from exemplars only, under a strict token budget, using versioned prompt template files — changing a prompt touches no Python
  5. A non-loopback/non-RFC1918 endpoint is refused without `--i-know-what-im-doing`, and the entire test suite passes with zero network access via the injectable client and fake OpenAI-compatible server

**Carried forward from Phase 2**: WR-07 — a disk-full error (SQLITE_FULL/IOERR) mid-ingest triggers SQLite auto-rollback that destroys the per-file SAVEPOINTs, leaving the interrupted-ingest atomicity guarantee with a known hole. Plan a fix in this phase (signed off as a deferred follow-up in 02-UAT.md, 2026-07-17).

**Plans:** 6/6 plans complete

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Framework install (httpx/sqlite-vec/scikit-learn/respx) + [embeddings]/[clustering] config + SIFT_* env layer + WR-07 disk-full fix (wave 1)

**Wave 2** *(blocked on Wave 1)*

- [x] 03-02-PLAN.md — InferenceClient (SSRF guard, per-role endpoints, backoff, feature-detect) + PromptBudget seam (wave 2)
- [x] 03-03-PLAN.md — Store migration 3 (chunks+clusters) + lazy vec0 vectors + dimension guard + replace_clusters (wave 2)

**Wave 3** *(blocked on Wave 2)*

- [x] 03-04-PLAN.md — `sift doctor` fail-fast sequence (real embedding round-trip, dim + vec_version checks, determinism warn) (wave 3)
- [x] 03-05-PLAN.md — HDBSCAN + agglomerative fallback + one batched LLM label from versioned prompt + ADR 0004 (wave 3)

**Wave 4** *(blocked on Wave 3)*

- [x] 03-06-PLAN.md — `sift analyze` embed→cluster→label wiring + `show clusters` label display + embedding progress (wave 4)

### Phase 4: Salience, RAG & Citation-Gated Hypotheses

**Goal**: The core value ships — `sift analyze` turns clusters into ranked, evidence-cited root-cause hypotheses that cannot cite what the model was never shown
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: RAG-01, RAG-02, RAG-03, RAG-04, RAG-06, CLI-04
**Success Criteria** (what must be TRUE):

  1. On the first golden case, `sift analyze` produces schema-valid JSON hypotheses (title, narrative, confidence + reasoning, supporting_event_ids, contradicting_evidence, next steps, timeline_summary, unexplained_signals) with 100% citation validity after the permitted retry
  2. Every cited event ID exists in the case store AND was present in the prompt ("cited ⊆ prompted"); the invalid-citation regeneration path is covered by a test with a mocked model returning bad IDs, and still-invalid hypotheses are flagged, never silently accepted
  3. JSON failures degrade gracefully: constrained decoding where available, Pydantic validation, one repair round-trip carrying the validation errors, then raw output persisted with the run marked degraded — never a crash, and exit codes distinguish success / degraded / failure for CI scripting
  4. Clusters are ranked by salience combining severity, count, burstiness, novelty, and temporal proximity to a user-supplied incident time, budgeted breadth-first to fit the model's context
  5. User can scope analysis with `--hint` free text and `--since/--until` time-window filters

**Plans:** 6/6 plans complete

Plans:
**Wave 1** *(parallel — no shared files)*

- [x] 04-01-PLAN.md — Hypothesis/HypothesisSet Pydantic models + store migration 4 (hypotheses table + run meta) (wave 1)
- [x] 04-02-PLAN.md — Deterministic salience ranking (severity/count/burstiness/novelty/proximity) (wave 1)
- [x] 04-03-PLAN.md — Additive `chat(response_format=…)` constrained-decoding param (llama.cpp nesting) (wave 1)

**Wave 2** *(blocked on Wave 1)*

- [x] 04-04-PLAN.md — Triage prompt + enforcement state machine (validate/repair/degrade) + citation gate (cited ⊆ prompted ⊆ store) + atomic persist (wave 2)

**Wave 3** *(blocked on Wave 2)*

- [x] 04-05-PLAN.md — `sift analyze` `--hint/--since/--until/--top-clusters` + 0/3/1 exit-code contract + `sift show hypotheses` + ADR (wave 3)

**Gap closure** *(from live-server UAT — G1)*

- [x] 04-06-PLAN.md — Map a malformed/empty 200 inference response (no `choices` / empty `content`, reasoning-model budget exhaustion) to a clean failed run — never crash (G1, RAG-03) (wave 1)

### Phase 5: Domain Adapters (journald, dsserrors, eustack)

**Goal**: Real production diagnostics — systemd journals, MicroStrategy DSSErrors logs, and EU-stack thread dumps — flow through the proven pipeline
**Mode:** mvp
**Depends on**: Phase 1 (adapter Protocol frozen at M1; can execute in parallel with Phase 4 — gate acceptance sequentially)
**Requirements**: INGST-07, INGST-08, INGST-09
**Success Criteria** (what must be TRUE):

  1. journald adapter parses `journalctl -o json` export files with ≥ 95% parse coverage on its fixture, mapping PRIORITY→severity, _SYSTEMD_UNIT→component, _PID/_COMM→attrs
  2. dsserrors adapter achieves ≥ 95% parse coverage on its fixture: extracts SIDs, 0x error codes, and multi-node tags; captures multi-line MCM blocks as single events; orders rotated `.bak` siblings by content, not filename
  3. eustack adapter yields exactly one event per thread on a fixture dump, with condensed top frames in `message`, full stack in `raw`, and lock info in attrs
  4. A mixed-timezone multi-node fixture produces a correctly ordered UTC timeline (causality never silently inverted)

**Plans:** 6/6 plans executed

Plans:
**Wave 1** *(shared enabler + format checkpoint)*

- [x] 05-01-PLAN.md — ConfigurableAdapter generalisation (base.py + cli.py + genericlog retrofit) + non-vacuous coverage regression test + ADR 0006 (wave 1)
- [x] 05-02-PLAN.md — checkpoint:human-verify — confirm dsserrors line layout/SID shape + eustack format identity (eu-stack vs JVM) before regexes freeze (wave 1)

**Wave 2** *(parallel — three disjoint adapter modules; blocked on 05-01, dsserrors/eustack also on 05-02)*

- [x] 05-03-PLAN.md — journald adapter (INGST-07): JSONL, µs-epoch UTC, PRIORITY→severity, _field_to_str normaliser, non-vacuous coverage (wave 2)
- [x] 05-04-PLAN.md — dsserrors adapter (INGST-08): SID/OID/0x/[*.cpp:N] tokens, MCM block grouping+caps, node tagging, rotation-by-ts, mixed-tz timeline (criterion 4) (wave 2)
- [x] 05-05-PLAN.md — eustack adapter (INGST-09): one event per thread, condensed frames→message, full stack→raw, lock info where format carries it (wave 2)

**Wave 3** *(integration — shared registry + CLI e2e; blocked on 05-03/04/05)*

- [x] 05-06-PLAN.md — register all three adapters + detect-routing tests + CliRunner e2e slices (real coverage not 1.0, idempotent re-ingest) (wave 3)

### Phase 6: Renderers & KB Retrieval

**Goal**: A user can hand a colleague a self-contained, reproducible triage report where every claim is one click from its raw evidence
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: REPT-01, REPT-02, REPT-03, REPT-04, RAG-07
**Success Criteria** (what must be TRUE):

  1. `sift report` renders Markdown with executive summary, ranked hypotheses, working `[evt:…]` links into an evidence appendix showing raw text with file:line provenance, cluster inventory, timeline, unexplained signals, and run metadata (degraded runs banner included)
  2. JSON report carries the full hypotheses object plus cluster stats, and the reproducibility test passes: identical case + config + model + seed produces byte-identical JSON apart from timestamps, with the determinism claim scoped and documented against known llama-server caveats
  3. Pointing analysis at a knowledge-base directory of Markdown runbooks/RCAs demonstrably changes the retrieved context in a test
  4. Installing the `sift[pdf]` extra enables PDF report rendering (URL fetching disabled)

**Plans:** 5/5 plans complete

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — Markdown report core (REPT-01): render/ package, get_events_by_ids, evidence appendix + anchors + degraded banner, real `sift report` command, ADR 0007 exit codes (wave 1)

**Wave 2** *(parallel — no shared files; blocked on 06-01)*

- [x] 06-02-PLAN.md — JSON report + reproducibility (REPT-02/03): canonical render_json, byte-identical determinism test, ADR 0008 determinism scope (wave 2)
- [x] 06-03-PLAN.md — KB index + retrieval data path (RAG-07): migration 5 separate kb namespace, confined KB store methods, pipeline/retrieve.py, ADR 0009 per-case KB (wave 2)
- [x] 06-05-PLAN.md — PDF extra (REPT-04): import-guarded render/pdf.py, egress-blocked url_fetcher, `sift[pdf]` optional-dependency (wave 2)

**Wave 3** *(blocked on 06-03)*

- [x] 06-04-PLAN.md — KB into analyze (RAG-07): triage.md reference block, `kb_context` threading, `sift analyze --kb`, D-01 non-citability preserved (wave 3)

### Phase 7: Evaluation Harness & Golden Cases

**Goal**: Hypothesis quality is measurable and regression-gated, not vibes-based
**Mode:** mvp
**Depends on**: Phase 5, Phase 6
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04
**Success Criteria** (what must be TRUE):

  1. A golden suite of ≥ 5 synthetic-but-realistic cases exists, each with `input/`, `truth.yaml` (committed before any prompt tuning), and README — including a quiet-cause case, a mixed-timezone case, and a negative (no-incident) case
  2. `sift eval` runs the suite and prints the metric table: retrieval hit rate, hypothesis hit@k, citation validity rate, and determinism drift across repeated runs
  3. `sift eval` exits non-zero when a planted regression drops scores below `eval/thresholds.toml` thresholds
  4. Optional LLM-as-judge grading via the same local model is reported alongside (never instead of) keyword scores

**Plans**: 6/6 plans executed

Plans:

- [x] 07-06-PLAN.md

- [x] 07-01-PLAN.md — PyYAML legitimacy checkpoint + pinned install (unblocks truth.yaml parsing)
- [x] 07-02-PLAN.md — Harness skeleton: one golden case runs end-to-end offline through `sift eval` and prints its metric row (truth loader + 4 metrics + runner + table)
- [x] 07-03-PLAN.md — Threshold gate + non-zero exit on planted regression + ADR 0010
- [x] 07-04-PLAN.md — Full 6-case golden suite (all SPEC exemplars + quiet-cause, mixed-tz, negative) + suite validation
- [x] 07-05-PLAN.md — Optional LLM-as-judge grading (advisory, `--judge`, never gates)

### Phase 8: Packaging & Deploy

**Goal**: A stranger on Fedora can go from clean checkout to first triage report using only the README
**Mode:** mvp
**Depends on**: Phase 7
**Requirements**: PKG-01, PKG-02
**Success Criteria** (what must be TRUE):

  1. `uv tool install` from a clean checkout yields a working `sift` (pipx-compatible)
  2. Podman Quadlet files ship with a llama-server example, validate per `podman quadlet` dry-run docs, and document the `host.containers.internal` interaction with the loopback guard
  3. README quickstart covers llama.cpp setup (Vulkan and ROCm notes for gfx1151) and Lemonade Server

**Plans:** 3/3 plans complete

Plans:

**Wave 1**

- [x] 08-01-PLAN.md — PKG-01 install slice: `packaging` marker + addopts, offline install smoke test, `sift --version` (wave 1)

**Wave 2** *(blocked on 08-01)*

- [x] 08-02-PLAN.md — PKG-02 deploy slice: `deploy/*.container` (guard-clean loopback), ADR 0011, guard-acceptability + graceful-skip Quadlet dry-run tests (wave 2)
- [x] 08-03-PLAN.md — README quickstart (D-09): install → backend (two-instance, Vulkan/ROCm, Lemonade caveat) → doctor → analyse → report → pdf extra + human-verify (wave 2)

### Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown

**Goal**: A user can run the new deterministic MCM analyser over a `dsserrors` case and see every distinct denial episode — non-interactively, all episodes, full lifecycle — each with its denial-time physical/virtual memory breakdown and MCM settings, computed with zero LLM involvement
**Depends on**: Phase 5 (dsserrors adapter already ingests the MCM/contract events this stage reads; the adapter may gain a few structured attrs but the quantitative logic is a new pipeline/analyser stage)
**Requirements**: MCM-01, MCM-02
**Success Criteria** (what must be TRUE):

  1. Running the analyser on the Hartford deny case detects every distinct denial episode non-interactively (no prompts, all episodes), each bounded by its denial banner (`IServer enters MCM denial state`) and its recovery (`State=normal`, resumed contract activity, or `AvailableMCM` climbing back)
  2. Each episode captures its full lifecycle signals — `memory-status-low` handler, emergency working-set offload, and recovery — as episode context, not just the denial banner
  3. For each episode the denial-time memory breakdown parses into a structured model: physical/virtual split, cube caches, cube growth/index, MMF, SmartHeap pool, working set, other memory, plus the MCM Settings block
  4. A log that ends mid-episode with no recovery line (as the Hartford deny log does — it contains no `State=normal`) is reported as an open/truncated episode rather than dropped or crashed
  5. Re-running on the same case yields byte-identical episodes and numbers — determinism holds because no model is involved

**Plans:** 3/2 plans complete

Plans:
**Wave 1**

- [x] 09-01-PLAN.md — Vendor `analyze_dss8.py` + verbatim Hartford deny slice fixture + RED golden `tests/test_mcm.py` (8 assertions) (wave 1)

**Wave 2** *(blocked on Wave 1)*

- [x] 09-02-PLAN.md — Port `prescan`/block parsers into `pipeline/mcm.py` over the event-id line stream + lifecycle capture + open/truncated + in-span MCM Settings; suite GREEN (wave 2)

### Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV

**Goal**: The MCM analyser becomes a complete deterministic forensics command — `sift mcm <case>` emits machine-independent diagnostic flags, an auto-selected lead-up window, per-OID/per-Source/per-SID memory attribution, and both a human-readable report and a CSV export
**Depends on**: Phase 9
**Requirements**: MCM-03, MCM-04, MCM-05
**Success Criteria** (what must be TRUE):

  1. For each episode the analyser emits deterministic diagnostic flags — working-set % of IServer virtual, other-processes % of physical, cube-cache/MMF coverage, SmartHeap releasability, system-free headroom — with every threshold expressed as % of HWM/total, never absolute GB
  2. Each episode's lead-up window is auto-selected from `AvailableMCM`-descent thresholds (as % of HWM), non-interactively — no manual start-line picking
  3. Memory granted in the window is attributed by OID, by `Source=` request type, and by SID (session), so the one-OID/many-SID fan-out in the Hartford case is resolved by session
  4. `sift mcm <case>` writes a deterministic human-readable report and a CSV export of the per-OID/per-Source/per-SID attribution table
  5. Two differently-sized machines under the same relative pressure produce identical flags — verified against a scaled fixture (thresholds are % based, machine-independent)

**Plans**: TBD

### Phase 11: MCM Facts into `sift analyze` + Golden Eval Case

**Goal**: The deterministic MCM facts feed the LLM hypothesis pipeline as cited evidence — never authored by the model — and an MCM golden case regression-gates the whole feature
**Depends on**: Phase 10, Phase 7 (evaluation harness)
**Requirements**: MCM-06, MCM-07
**Success Criteria** (what must be TRUE):

  1. Structured MCM facts (episode summary, memory breakdown, flags, top attributions) are injected into `sift analyze` as cited evidence, preserving the cited ⊆ prompted ⊆ store invariant
  2. Every MCM figure surfaced in a hypothesis comes verbatim from the deterministic analyser — a test proves the model cannot alter or invent the numbers (figures are computed, not generated)
  3. The MCM fact block is supplied via a versioned prompt template file (`sift/prompts/*.md`) — changing its wording touches no Python
  4. An MCM golden case (denial episode with a known breakdown) is added to the eval suite with `truth.yaml`, and `sift eval` exits non-zero when its scores regress
  5. With no dsserrors/MCM data present, `sift analyze` output is byte-identical to before — the MCM block is purely additive

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 (Phase 5 may run in parallel with Phase 4; acceptance gated sequentially). v1.1 continues: 9 → 10 → 11.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Skeleton, Event Contract & genericlog Adapter | 5/5 | Complete    | 2026-07-16 |
| 2. Case Store & Template Dedup | 4/4 | Complete    | 2026-07-17 |
| 3. Inference Client, Doctor, Embeddings & Clustering | 6/6 | Complete    | 2026-07-17 |
| 4. Salience, RAG & Citation-Gated Hypotheses | 6/6 | Complete    | 2026-07-17 |
| 5. Domain Adapters (journald, dsserrors, eustack) | 6/6 | Complete    | 2026-07-18 |
| 6. Renderers & KB Retrieval | 5/5 | Complete    | 2026-07-18 |
| 7. Evaluation Harness & Golden Cases | 6/6 | Complete    | 2026-07-19 |
| 8. Packaging & Deploy | 3/3 | Complete    | 2026-07-19 |
| 9. MCM Episode Detection & Denial-Time Memory Breakdown | 3/2 | Complete    | 2026-07-19 |
| 10. Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV | 0/— | Not started |  |
| 11. MCM Facts into `sift analyze` + Golden Eval Case | 0/— | Not started |  |

---
*Roadmap created: 2026-07-16 — Phases 1–8 map 1:1 to SPEC.md milestones M1–M8*
*Updated: 2026-07-19 — v1.1 milestone appended (Phases 9–11, MCM Memory-Pressure Analysis); numbering continues from Phase 8*
