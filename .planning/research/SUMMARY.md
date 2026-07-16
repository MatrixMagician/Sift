# Project Research Summary

**Project:** Sift
**Domain:** Local-first, privacy-preserving LLM-powered incident/log triage CLI (Python)
**Researched:** 2026-07-16
**Confidence:** MEDIUM

## Executive Summary

Sift sits in a nearly empty niche: fully offline, backend-agnostic LLM log triage. The four surveyed ecosystems (CLI log viewers like lnav, log-mining libraries like Drain3/LogAI, LLM triage agents like k8sgpt/HolmesGPT, and commercial AIOps) each define a slice of user expectations, and SPEC.md v0.1 already covers almost all of them. Existing "local LLM log analysis" tools are single-file Ollama prompt wrappers with no event schema, no dedup, no citations, no eval — Sift's SPEC targets the actual gap. The research verdict across all four files is unanimous: **the SPEC survives pressure-testing intact.** The stack (Python 3.12+, uv, httpx, Pydantic, SQLite+sqlite-vec, sklearn HDBSCAN, zstandard), the architecture (deterministic reduce funnel → single budgeted RAG call → mechanical citation gate), and the M1–M8 milestone order all match ecosystem best practice.

The recommended approach is a batch pipeline, never an agentic loop: parse → template-dedup → embed exemplars only → HDBSCAN → salience → one constrained generation → Pydantic validation → mechanical citation verification. The load-bearing differentiators are hard citation validation (no surveyed tool enforces it — it answers the domain's #1 adoption blocker, hallucination distrust), the `unexplained_signals` honesty section, strict offline/loopback enforcement, determinism, and the eval harness. Open SPEC questions are resolved: Typer over argparse, WeasyPrint behind a `sift[pdf]` extra over ReportLab, hand-rolled masking over drain3 (dormant since 2022), and `sklearn.cluster.HDBSCAN` over the standalone package.

The key risks are semantic, not syntactic: citations that exist but don't support the claim (enforce "cited ⊆ prompted", not "cited ⊆ store"); salience functions that bury quiet root causes under symptom storms (add novelty/temporal-precedence terms, gate on retrieval hit rate); llama-server non-determinism voiding the reproducibility contract (scope the claim, send explicit sampling params, warn on multi-slot); and timezone ambiguity inverting causality in multi-node timelines. All have concrete phase-mapped preventions. Three cheap table-stakes gaps in the SPEC should be folded into existing milestones: gzip/zstd input handling, `--since/--until` time filters, and progress reporting.

## Key Findings

### Recommended Stack

The SPEC-prescribed stack was validated rather than re-proposed; every choice is current and fit for purpose. Full detail in [STACK.md](STACK.md).

**Core technologies:**
- Python 3.12+ / uv — SPEC constraints; `uv tool install` is the M8 packaging target
- httpx 0.28.x — hand-rolled OpenAI-compatible client (~200 lines); never the `openai` SDK (vendor coupling hides llama.cpp's non-standard `response_format.schema` nesting)
- Pydantic 2.13.x — hypothesis JSON contract; `model_json_schema()` feeds llama.cpp schema-constrained decoding
- SQLite + sqlite-vec 0.1.9 — one `case.db` per case; pre-v1 but Sift uses only the stable brute-force KNN path; documented escape hatch is BLOB+numpy behind the same store interface
- scikit-learn 1.9 — `sklearn.cluster.HDBSCAN` plus the agglomerative fallback in one dependency; do NOT add standalone `hdbscan`
- Typer 0.27 — resolves SPEC open question #1 (typed params, seven subcommands justify it)
- zstandard 0.25 — raw-text compression >4 KB; swap to stdlib when floor reaches 3.14
- WeasyPrint behind optional `sift[pdf]` extra — resolves open question #2; ReportLab would mean hand-writing all layout

**Key server facts confirmed:** llama.cpp expects `{"type":"json_schema","schema":{...}}` (not OpenAI's nesting); `--embeddings` makes a server embedding-only so generation and embeddings need two instances (validates per-role `base_url`); Lemonade defaults to port 13305 and embeddings only work for llamacpp/flm-recipe models — `sift doctor` must round-trip an actual embedding.

### Expected Features

Full detail in [FEATURES.md](FEATURES.md). SPEC v0.1 already covers nearly all table stakes.

**Must have (table stakes):**
- Canonical event schema + adapters with format auto-detection and a robust fallback parser (nothing dropped silently)
- Template dedup with counts (70–85% compression is the AIOps norm) + semantic clustering
- Ranked, human-readable root-cause findings with next steps and timeline
- JSON output + stable exit codes; inspection commands (`sift show`); `sift doctor`; no daemon
- **Gaps to fold in:** gzip/zstd input handling, `--since/--until` time filters, progress reporting (M1–M2); exit-code contract for degraded runs (M4); event-volume histogram (M6, render-only)

**Should have (differentiators — Sift's edge):**
- Hard citation validation — the load-bearing differentiator; keep hard-fail
- `unexplained_signals` honesty section; evidence appendix with file:line provenance
- Fully offline, loopback-enforced; determinism + reproducible reports
- Eval harness with golden incidents + CI thresholds; deep domain adapters (dsserrors, eustack); local KB retrieval

**Defer (v1.x/v2):**
- Report redaction pass (v1.x — build alongside golden-case sanitisation in M7 if natural)
- Case baseline diff (v2); TUI/web view (v2)

**Anti-features (never build):** agentic ReAct loops, chat interface, cloud LLM fallback, auto-remediation, live tail mode, DL anomaly suites, alerting integrations, model management, telemetry.

### Architecture Approach

The SPEC §4–5 structure matches how this class of system is built in practice — no structural changes. "Filter before analysis" is the consensus pattern; batch pipeline (not agentic) is correct for static artefacts; mechanical citation verification is the strongest known anti-hallucination mechanism. Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

**Major components (boundaries are hard rules):**
1. `adapters/` — raw bytes → `Event`; zero knowledge of store/LLM/pipeline
2. `models.py` — frozen contract layer; imports nothing from the others
3. `store.py` — only SQL in the codebase; `user_version` migrations; lazy vec0 creation (dimension known only at first embed)
4. `pipeline/` — dedup (no ML/network), cluster, salience (pure function), retrieve, hypothesise
5. `llm/client.py` — the ONLY module allowed to open a socket; loopback/RFC1918 guard; injectable
6. `llm/budget.py` — pure token budgeting with injected `count_tokens` callable
7. `render/` — read-only over the store; reproducibility contract lives here

**Load-bearing properties:** write path (ingest+dedup, no LLM) vs read path (analyze, LLM required) separation; all stages communicate via SQLite tables, not in-memory hand-offs (re-runnable, resumable, portable). Chunking = template-group exemplars, never fixed-size windows. L2-normalise embeddings + euclidean for HDBSCAN (cosine metric not supported directly); noise points become singleton clusters, never dropped.

### Critical Pitfalls

Top 5 of 10 from [PITFALLS.md](PITFALLS.md):

1. **Existing-but-irrelevant citations pass validation** — enforce "cited ⊆ prompted-ID-set" (not just store existence), add a lexical-overlap relevance heuristic, make relevance a scored eval metric (M4/M7)
2. **Salience buries quiet root causes** — add novelty and temporal-precedence terms; gate eval on retrieval hit rate; seed a golden case with a low-count/low-severity cause (M4/M7)
3. **llama-server non-determinism voids reproducibility** — scope the claim (single slot, no cache, explicit sampling params every request); `doctor` warns on `--parallel > 1`; drift metric is semantic-first, byte-identity optional (M3/M7)
4. **JSON contract fails three ways, repair fixes one** — order schema fields reasoning-before-conclusion; distinguish finish_reason `length` from invalid JSON; repair prompt carries Pydantic errors verbatim (M4)
5. **Same-dimension embedding swap / missing task prefixes silently corrupt retrieval** — `meta` records model ID + dimension + prefix convention; one prefixing code path; `doctor` cross-checks (M3)

Also critical: timezone ambiguity inverting causality (M1/M5 — mixed-tz fixtures mandatory); HDBSCAN small-N defaults all-noise (`min_cluster_size=2`, build agglomerative fallback in M3, not later); token budget maths (calibrate heuristic on log text ~chars/2.8, per-slot context); eval overfitting (truth.yaml committed before prompt tuning, negative golden case); rotation/encoding/huge files (byte-offset on raw bytes, streaming, UTF-16LE fixtures). Security: resolve-then-check loopback IPs, `trust_env=False`, socket-guard pytest fixture, disable WeasyPrint URL fetching.

## Implications for Roadmap

The SPEC's M1–M8 ordering is dependency-correct and confirmed by architecture research. Recommended phase structure follows it directly, with research-derived amendments folded in.

### Phase 1 (M1): Skeleton + Event contract + genericlog adapter
**Rationale:** `models.py` is the contract everything consumes; one adapter proves the schema.
**Delivers:** CLI skeleton, frozen `Event` type, genericlog adapter, config.
**Addresses:** format auto-detection, fallback parser; fold in gzip/zstd input handling.
**Avoids:** Pitfall 6 (timezone semantics + `ts_confidence` from day one), Pitfall 10 (streaming byte-offset parsing, encoding fixtures), socket-guard pytest fixture from the start.

### Phase 2 (M2): Case store + template dedup
**Rationale:** Full write path with zero LLM dependency — testable at 100 MB scale before any network code exists.
**Delivers:** SQLite store, `user_version` migrations, zstd compression, masking + template grouping.
**Uses:** sqlite3 + zstandard; hand-rolled masking (NOT drain3).
**Avoids:** hex-masking of MSTR error codes (extract to attrs before masking); transaction-batched inserts + WAL for the <60 s gate; explicit memory-bound ingest test. Fold in `--since/--until` and progress reporting here.

### Phase 3 (M3): Inference client + doctor + embeddings + clustering
**Rationale:** First network surface; dimension discovery and lazy vec0 creation land here.
**Delivers:** httpx client with loopback guard, `sift doctor`, batched embeddings, HDBSCAN + agglomerative fallback, token budget utility.
**Avoids:** Pitfalls 3, 5, 7, 8 all land here — explicit sampling params, model-ID+prefix recording, `min_cluster_size=2` + fallback built now, calibrated token heuristic, per-slot context reporting. `doctor` must round-trip an actual embedding (Lemonade recipe caveat).

### Phase 4 (M4): Salience + RAG + hypothesis generation + citation gate
**Rationale:** The core value; depends on clusters existing.
**Delivers:** salience ranking (with novelty/precedence terms), prompt budgeting, JSON contract + repair loop, "cited ⊆ prompted" citation validator.
**Avoids:** Pitfalls 1, 2, 4. Seed the first golden case as `eval/cases/<name>/truth.yaml` NOW (file-layout decision, enables truth-before-tuning discipline for M7). Define the exit-code contract for degraded runs.

### Phase 5 (M5): Remaining adapters (journald, dsserrors, eustack)
**Rationale:** Deliberately after M4 — adapters are parallel-safe leaf modules; end-to-end pipeline proven on genericlog first. **Can overlap M4 planning/implementation** (Protocol frozen at M1); gate acceptance sequentially.
**Delivers:** domain adapters with rotation ordering (content-sorted, not filename), mixed-timezone multi-node fixtures, UTF-16LE fixtures.

### Phase 6 (M6): Renderers + KB retrieval
**Rationale:** Read-only consumers of hypotheses; KB extends retrieve.
**Delivers:** Markdown/JSON renderers with reproducibility contract, evidence appendix, DEGRADED banner, event-volume histogram (cheap add), KB index (global, model/dim recorded in meta). PDF via `sift[pdf]` extra — implement here or defer post-M8; disable WeasyPrint URL fetching.

### Phase 7 (M7): Eval harness + golden cases
**Rationale:** Metrics need the full pipeline; thresholds gate regressions thereafter.
**Delivers:** golden suite including quiet-cause, mixed-timezone, high-noise, and negative (no-incident) cases; retrieval hit rate as gating metric; citation-relevance spot-checks as thresholds; semantic-stability determinism metric; grammar on/off A/B.
**Avoids:** Pitfall 9 — truth.yaml predates prompt-tuning commits; keyword gates, judge advisory; cross-model judging where possible.

### Phase 8 (M8): Packaging + deploy
**Rationale:** Leaf. `uv tool install sift`; Quadlet container (document `host.containers.internal` vs loopback guard); Fedora `dnf install pango` for the pdf extra.

### Phase Ordering Rationale

- Write-path-before-read-path means M1–M2 are fully testable with zero LLM infrastructure — de-risks the whole system early.
- Domain adapters after the end-to-end pipeline (M5 after M4) proves the architecture on the cheapest adapter before investing in expensive parsers; M5 can execute in parallel with M4.
- Every critical pitfall has an explicit prevention phase (see PITFALLS.md, Pitfall-to-Phase Mapping) — the roadmap should carry those as acceptance criteria, not notes.
- Eval skeleton seeds in M4 so M7 formalises metrics over an existing corpus rather than retrofitting.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (M4):** prompt/schema design for small local models (reasoning-first field ordering, two-stage generation trade-off) is model-class-dependent; verify Pydantic `$defs` handling against the target llama.cpp build.
- **Phase 7 (M7):** eval metric design against nondeterministic backends is thinly documented; expect iteration on drift-metric definition.

Phases with standard patterns (skip research-phase):
- **Phases 1–2 (M1–M2):** parsing, SQLite, migrations, masking — all well-documented; pitfall fixtures are the spec.
- **Phase 3 (M3):** the gotchas are already enumerated (sqlite-vec KNN syntax, HDBSCAN params, prefixes); implementation is direct.
- **Phases 5, 6, 8:** leaf modules with frozen contracts / standard packaging.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Versions verified against PyPI + official docs; llama.cpp/Lemonade behaviour from official READMEs cross-checked with issue trackers |
| Features | MEDIUM | Multi-source web verification; the "empty niche" claim is LOW→MEDIUM (absence hard to prove) |
| Architecture | MEDIUM | SPEC validated against ecosystem norms, multi-source convergence; sqlite-vec from curated official docs |
| Pitfalls | MEDIUM | llama.cpp/sqlite-vec from primary issue trackers; clustering/eval from convergent community sources; MSTR-specific claims HIGH (author domain expertise) |

**Overall confidence:** MEDIUM

### Gaps to Address

- **sqlite-vec maintenance risk (pre-v1, single maintainer):** keep vector access confined to `store.py`; BLOB+numpy escape hatch documented — verify seam holds during M3 planning.
- **Pydantic schema → llama.cpp converter (`$defs`/`$ref`):** verify against the actual target server build in M4; flatten schemas if needed.
- **Grammar-on quality collapse for small models:** unknowable until measured — A/B in M7, keep the prompt-based fallback path always tested.
- **Salience weights (SPEC open Q4):** deliberately deferred to M7 metrics; freeze truth files first.
- **Cluster labelling eager vs lazy (SPEC open Q3):** lean lazy (report-time); decide with measured cost in M6.
- **Report redaction:** v1.x candidate; revisit during M7 if golden-case sanitisation needs it anyway.

## Sources

### Primary (HIGH confidence)
- Author's MicroStrategy diagnostics domain expertise (PROJECT.md) — DSSErrors timestamps, rotation ordering, MCM blocks, encodings

### Secondary (MEDIUM confidence)
- /asg017/sqlite-vec (Context7) + issues #116, #165, #196, #226 — vec0 API, KNN constraints, maintenance history
- llama.cpp server README + issues #7052, #10732, #11847, #19981 — response_format nesting, --embeddings, determinism, slots
- Lemonade Server docs — port 13305, embeddings recipe restriction
- PyPI JSON API — exact versions/dates for all core packages
- scikit-learn issues #27829, #28631 — HDBSCAN semantics and cosine limitation
- Drain3/LogPAI, lnav, k8sgpt, HolmesGPT (CNCF), AIOps vendor docs — feature landscape and pipeline shape
- Citation grounding, LLM-as-judge bias, RCA reasoning preprints (arXiv 2606.00898, 2604.22891, 2601.22208, et al.)
- WeasyPrint / ReportLab official install docs — PDF path system deps

### Tertiary (LOW confidence)
- Local LLM log-analysis prototypes (llm-rca-assistant, llm-log-analyzer) — niche-emptiness evidence
- Structured-output failure-pattern write-ups, HDBSCAN embedding guides — convergent but community-sourced

---
*Research completed: 2026-07-16*
*Ready for roadmap: yes*
