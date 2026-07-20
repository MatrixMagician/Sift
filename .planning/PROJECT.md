# Sift — Local-LLM Incident Triage Engine

## What This Is

Sift is a fully local, privacy-preserving incident triage engine. It ingests diagnostic artefacts from production systems — MicroStrategy DSSErrors logs, EU-stack thread dumps, journald exports, generic application logs — and uses a locally hosted LLM (OpenAI-compatible endpoint from llama.cpp `llama-server` or AMD Lemonade Server) to cluster related events, summarise incident timelines, and generate ranked root-cause hypotheses with citations back to source evidence. It is a CLI tool for engineers who cannot ship customer diagnostic data to cloud APIs.

## Core Value

Turn a directory of raw diagnostics into a structured, evidence-cited triage report — entirely offline, with every claim citing verifiable event IDs (the anti-hallucination mechanism is load-bearing, not polish).

## Current State

**Shipped:** v1.2 DSSPerformanceMonitor Correlation (2026-07-20) — Phases 12–14, all 8 PERF
requirements satisfied, milestone audit PASSED (integration 6/6, flows 3/3, Nyquist COMPLIANT).
Sift now ingests DSSPerformanceMonitor PDH-CSV exports as deterministic, citable time-series
events and correlates their memory counters against MCM denial episodes — turning v1.1's
point-in-time snapshot into a corroborated lead-in timeline, with `sift perfmon` as a standalone
report and perfmon figures fed into `sift analyze` as computed-never-authored cited evidence.

**Codebase:** ~10,800 LOC Python across `src/sift`; five adapters (genericlog, journald,
dsserrors, eustack, dssperfmon); `sift` CLI subcommands new/ingest/analyze/report/show/mcm/perfmon/
eval/doctor. Quality gate green: `ruff` clean, `pyright` 0 errors, `pytest` 658 passed.

**Next milestone goals:** none defined yet. `/gsd-new-milestone` to scope the next cycle.
Backlog carries PERFV2-01 (recovery-trend), PERFV2-02 (multi-host correlation), and PERFV2-03
(perfmon-only anomaly detection), all deferred beyond v1.2.

<details>
<summary>Archived — v1.2 milestone goal & context (shipped 2026-07-20)</summary>

**Goal:** Ingest DSSPerformanceMonitor PDH-CSV exports as citable time-series events and correlate their memory counters against MCM denial episodes — turning v1.1's point-in-time forensic snapshot into a corroborated lead-in timeline.

**Delivered features:**
- New `dssperfmon` adapter: PDH-CSV header → counter set, rows → timestamped Events (`event_id = sha256(file, byte_offset)`, idempotent re-ingest); declared zone/offset recorded in `attrs` as evidence, not applied as a shift (ADR 0012)
- Perfmon events excluded from dedup/embed/cluster/salience by source-kind via one `EXCLUDED_FROM_RANKING` seam — citable, but never competing with error clusters
- Episode lead-in annotation: each MCM episode gains a corroborating perfmon trend (values at denial time, slope, peak) over the **same auto-selected lead-up window MCM-04 already computes**
- Standalone `sift perfmon <case>` trend report + CSV export, usable without a DSSErrors log present
- Perfmon figures fed into `sift analyze` as cited evidence (MCM-06 pattern: computed, never model-authored)
- Deterministic diagnostic flags — CSV/log window non-overlap, always-zero `Total MCM Denial`, counter-set drift
- Golden `perfmon-denial` eval case, regression-gated (MCM-07 pattern)

**Key context:** Consumed SEED-001 / PERF-01, planted during v1.1. The seed's premise was partly invalidated by the real data: the `Total MCM Denial` counter reads 0 across all 13,596 Hartford samples despite confirmed denials, so correlation keys off the memory counters (`Working set cache RAM usage(MB)` 27 → 266,042; `RAM used(MB)` 186,503 → 463,915; `Open Sessions` 3 → 1,488) and the dead counter became a reported flag, not an input. The Hartford CSV ends 6 s before the denial banner — lead-in fully covered, **no post-recovery data exists**, so recovery-trend analysis is out of scope. Time join trusts the declared PDH timezone recorded in `attrs`, flagging non-overlapping windows loudly.

</details>

## Requirements

### Validated

- ✓ Deterministic ingestion pipeline via genericlog: canonical frozen Event schema, sniff-based auto-detection with `--adapter` override, idempotent re-ingest, per-file parse coverage, gzip/zstd streaming, UTC normalisation with `ts_confidence`, CLI config precedence — Phase 1 (M1, 2026-07-16; 108 tests, human-verified prohibitions incl. loud symlink skip)

**v1.1 — MCM Memory-Pressure Analysis (✓ shipped 2026-07-20)**

- ✓ Deterministic detection of every distinct MCM denial episode with full lifecycle signals (MCM-01) — v1.1
- ✓ Parse denial-time memory breakdown + MCM settings from the log's memory-dump block (MCM-02) — v1.1
- ✓ Deterministic, machine-independent memory-pressure diagnostic flags (MCM-03) — v1.1
- ✓ Auto-selected lead-up window with per-OID / per-Source / per-SID memory attribution (MCM-04) — v1.1
- ✓ Deterministic MCM report + CSV export (MCM-05) — v1.1
- ✓ Structured MCM facts fed into `sift analyze` as cited evidence (MCM-06) — v1.1
- ✓ Golden MCM eval case, regression-gated (MCM-07) — v1.1

**v1.2 — DSSPerformanceMonitor Correlation (✓ shipped 2026-07-20)**

- ✓ `dssperfmon` PDH-CSV adapter — sniffed, deterministic `event_id`, idempotent re-ingest, header zone/offset recorded as evidence not applied (PERF-01, PERF-02) — v1.2
- ✓ Perfmon events excluded from dedup/embed/cluster/salience by source-kind, cluster output byte-identical, samples still citable (PERF-03) — v1.2
- ✓ Each MCM episode annotated with corroborating counter trend over MCM-04's lead-up window (PERF-04) — v1.2
- ✓ Deterministic correlation-hazard flags — non-overlap, always-zero `Total MCM Denial`, counter-set drift (PERF-05) — v1.2
- ✓ Standalone `sift perfmon <case>` report + CSV, works with no DSSErrors log present (PERF-06) — v1.2
- ✓ Perfmon figures into `sift analyze` as cited-not-authored evidence, no-perfmon prompt byte-identical (PERF-07) — v1.2
- ✓ Regression-gated `perfmon-denial` golden eval case (PERF-08) — v1.2

### Active

_No milestone in flight. `/gsd-new-milestone` scopes the next cycle; backlog carries PERFV2-01/02/03._

**Carried from v1.0 (validated, listed for continuity)**

- [ ] Ingest heterogeneous diagnostic inputs through the remaining domain adapters (journald, dsserrors, eustack) — Phase 5
- [ ] Deduplicate and cluster events (template masking + local embeddings + HDBSCAN) so a 2 GB log becomes a few dozen signal groups
- [ ] Generate root-cause hypotheses via RAG with enforced JSON output contract and hard citation validation against the case store
- [ ] Produce deterministic, reviewable output: Markdown report (primary), JSON (machine-readable), optional PDF
- [ ] Remain inference-backend agnostic: any OpenAI-compatible `/v1/chat/completions` + `/v1/embeddings` endpoint
- [ ] Ship an evaluation harness with golden incidents (retrieval hit rate, hypothesis hit@k, citation validity, determinism drift)
- [ ] Run fully offline — zero network egress except configured localhost inference endpoint
- [ ] `sift doctor` health-check for inference endpoints
- [ ] Optional knowledge-base retrieval (Markdown runbooks/prior RCAs) into triage context
- [ ] Packaging: `uv tool install` / pipx; optional Podman Quadlet deployment

### Out of Scope

- Live/streaming ingestion (tail -f mode) — v1 is batch analysis of collected artefacts only
- Web UI / TUI — CLI + generated reports only; v2 candidate
- Model management (download, quantise, serve) — that is llama.cpp's / Lemonade's job
- Auto-remediation — Sift diagnoses; humans act
- Fine-tuning — prompting + RAG only
- Remote/cloud inference endpoints — privacy is the reason this exists; refuse non-loopback/RFC1918 unless explicitly overridden

## Context

- Full specification exists at `SPEC.md` (v0.1) — authoritative for component design, schemas, milestones M1–M8, and acceptance criteria. CLAUDE.md already points to it.
- Reference environment: Fedora Workstation, AMD Strix Halo (gfx1151) with 128 GB unified memory; must degrade gracefully to CPU-only. Sift itself never touches the GPU — only the inference server does.
- Model assumptions: ~30B-class instruct GGUF at Q4/Q5 (8B fallback) for generation; nomic/bge-class GGUF for embeddings. Context length is queried/configured, never assumed. Embedding dimension discovered at runtime; mismatch on reload is a hard error.
- Author has deep MicroStrategy diagnostics domain expertise (DSSErrors, MCM, EU-stacks) — the dsserrors/eustack adapters encode that knowledge.
- Open questions to decide during M1 (record in `docs/decisions/`): Typer vs argparse; reportlab vs weasyprint vs defer PDF; eager vs lazy cluster labelling; salience weights; per-case vs global KB index.

## Constraints

- **Tech stack**: Python 3.12+, `uv`-managed; boring technology only (stdlib, httpx, Pydantic, sqlite-vec, scikit-learn/hdbscan, Typer, zstandard) — additions must be justified
- **Privacy**: No telemetry, no network calls except configured localhost inference endpoint; never call the network in tests (injectable LLM client, fake OpenAI-compatible server)
- **Storage**: SQLite + sqlite-vec, one `case.db` per case — zero-daemon, portable, deletable; revisit only past ~1M chunks/case
- **Determinism**: `event_id = sha256(source_file, byte_offset)[:16]`; idempotent re-ingest; identical case+config+model+seed → byte-identical JSON modulo timestamps
- **Quality gates**: `ruff check`, `pyright`, `pytest` clean is part of "done" for every milestone; no M(n+1) while M(n) is red
- **Language/docs**: British English in docs and user-facing strings; type hints everywhere; Apache-2.0
- **Prompts**: All prompts are versioned template files (`sift/prompts/*.md`) — changing a prompt must not require touching Python

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| OpenAI-compatible HTTP API only, no vendor SDK | Backend-agnostic: llama-server and Lemonade both expose it; avoids lock-in | — Pending |
| SQLite + sqlite-vec over Qdrant/Chroma | Dependency-light, zero-daemon, case-portable; v1 scale is tens of thousands of chunks | — Pending |
| Template dedup before semantic clustering | Cheap-first: masking volatile tokens collapses 95%+ of high-volume logs before any ML | — Pending |
| Citation validation as hard requirement | Core anti-hallucination mechanism; hypotheses citing nonexistent events are rejected/regenerated | ✓ Good — v1.2 extended it to perfmon facts (cited ⊆ prompted ⊆ store, anti-hallucination test) |
| Prompts as versioned files, not inline strings | Prompt iteration without code changes; auditable | ✓ Good — `perfmon_facts.md` holds zero authored digits |
| PDH header timezone recorded as evidence, not applied as a shift (ADR 0012) | Applying the +300 min bias put the CSV 5 h after the denial it precedes by 6 s, breaking correlation; all shipped adapters stamp naive-local as UTC via `base.to_utc` | ✓ Good — v1.2 |
| `dsserrors` sniff markers qualified `AvailableMCM`/`MCM Settings` (ADR 0013) | Bare `MCM` substring collided with the `Total MCM Denial` PDH counter in every real perfmon CSV | ✓ Good — v1.2 |
| Perfmon exclusion via one `EXCLUDED_FROM_RANKING` store seam, no opt-out flag (D-07) | Single predicate over per-stage re-implementation; a defaulted flag is how a future caller could silently reintroduce the criterion-4 regression | ✓ Good — v1.2 (cluster output byte-identical guard) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-20 after v1.2 milestone (DSSPerformanceMonitor Correlation) shipped. v1.0 + v1.1 + v1.2 complete and archived under `.planning/milestones/`.*
