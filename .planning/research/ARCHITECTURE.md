# Architecture Research

**Domain:** Local-first, LLM-powered incident/log triage CLI (batch RAG over diagnostic artefacts)
**Researched:** 2026-07-16
**Confidence:** MEDIUM (web findings cross-verified across multiple independent sources; sqlite-vec behaviour from curated official docs; SPEC.md architecture validated against ecosystem norms rather than invented here)

## Verdict on the SPEC.md Architecture

The structure prescribed in SPEC.md §4–5 (CLI → adapters → canonical Event schema → per-case SQLite+sqlite-vec → template dedup → embed → HDBSCAN → salience → retrieve → hypothesise → renderers, OpenAI-compatible HTTP as the only network surface) **matches how this class of system is built in practice**. No structural changes recommended. Evidence:

- **"Filter before analysis" is the consensus pattern.** Every serious LLM log-analysis system (k8sgpt's deterministic analyzers, academic security-log RAG pipelines, LogPAI-lineage tooling) performs cheap deterministic reduction *before* any LLM call, because LLMs cannot process raw log volume and perform poorly on noisy input. Sift's template-dedup-first, embed-exemplars-only design is exactly this pattern.
- **Template mining before semantic clustering is standard.** Drain/Drain3 is the de-facto approach: mask volatile tokens, group by template, carry count/first-last-seen/exemplars. Sift's own masking approach is a simplified Drain and is sufficient; Drain3 itself is an optional dependency swap, not an architectural change.
- **Batch pipeline (not agentic loop) is the right shape here.** HolmesGPT-style agentic tool-calling loops suit *live* observability with queryable backends. Sift analyses static collected artefacts offline — the deterministic reduce → single budgeted hypothesis call shape (k8sgpt-like) is correct, more reproducible, and cheaper. Do not drift toward an agent loop in v1.
- **Mechanical citation verification is the strongest known anti-hallucination mechanism.** Research on citation grounding converges on: constrained/schema decoding for shape, then *post-hoc mechanical validation of cited IDs against the store* (never trust the model's own citations), bounded repair loop, graceful degradation. SPEC §5.5 already prescribes precisely this. One refinement noted below (relevance spot-check).

## Standard Architecture

### System Overview (validated data flow)

```
 raw artefact dir
      │  sift ingest (write path — no LLM needed)
      ▼
 ┌───────────┐  sniff/parse  ┌──────────────┐
 │ Adapters   │─────────────▶│ Event rows    │  deterministic event_id
 └───────────┘               └──────┬───────┘
                                    ▼
                             ┌──────────────┐
                             │ Template     │  no ML; collapses 95%+
                             │ dedup groups │
                             └──────┬───────┘
      sift analyze (read path — LLM required from here)
                                    ▼
        /v1/embeddings  ◀──── exemplar chunks (batched)
                                    ▼
                             ┌──────────────┐
                             │ vectors +    │  vec0 table created lazily
                             │ HDBSCAN      │  (dimension known only now)
                             │ clusters     │
                             └──────┬───────┘
                                    ▼
                             salience ranking ──▶ PromptBudget packs
                                    ▼               top-N + timeline
        /v1/chat/completions ◀── triage prompt      + optional KB hits
                                    ▼
                             JSON contract ─▶ Pydantic validate
                                    ▼            │ fail: 1 repair round
                             citation check ◀────┘
                             (IDs exist in store; reject/regen; degrade)
                                    ▼
                             hypotheses rows
      sift report (pure read — no LLM)
                                    ▼
                             renderers (md/json/pdf)
```

Two properties of this flow are load-bearing and match ecosystem practice:

1. **Write path vs read path separation.** Ingest + template dedup need *no* inference server. Embedding/clustering and hypothesis generation do. Production local-RAG guidance separates the embed/index path from the retrieve/generate path; in Sift this falls out naturally as `ingest` (offline-capable even without llama-server running) vs `analyze` (requires endpoints). Keep that boundary hard — it also gives M1–M2 a fully testable system before any LLM code exists.
2. **Everything between CLI and inference server flows through the case store.** Pipeline stages communicate via SQLite tables, not in-memory hand-offs. This is what makes stages independently re-runnable, testable, and the case portable.

### Component Responsibilities

| Component | Responsibility | Boundary rule |
|-----------|----------------|---------------|
| `adapters/` | Raw bytes → `Event` records; parse-coverage metric | Only code that reads raw artefacts. Zero knowledge of store, LLM, pipeline. Output is the frozen `Event` contract. |
| `models.py` | `Event`, `Cluster`, `Hypothesis` types | The contract layer; adapters, pipeline, store, renderers all import from here; it imports nothing from them. |
| `store.py` | SQLite + sqlite-vec, migrations, zstd of large `raw` | Only code that writes SQL. Owns `user_version` migrations. Pipeline stages call store APIs, never raw SQL elsewhere. |
| `pipeline/dedup.py` | Volatile-token masking, template grouping | No ML, no LLM, no network. Must run standalone (M2 gate). |
| `pipeline/cluster.py` | Embed exemplars (via llm client), HDBSCAN merge, cluster labels | Only consumer of `/v1/embeddings`. Owns dimension discovery + vec0 table creation. |
| `pipeline/salience.py` | Rank clusters `f(severity, count, burstiness, recency/hint proximity)` | Pure function over cluster stats — trivially unit-testable, no I/O. |
| `pipeline/retrieve.py` | KB index build + similarity retrieval | Separate index from case vectors (KB is cross-case; leaning global per SPEC §10.5). |
| `pipeline/hypothesise.py` | Prompt assembly (via budget), JSON contract, repair loop, citation validation | Only consumer of `/v1/chat/completions` for triage. Citation check queries the store — never trusts model output. |
| `llm/client.py` | OpenAI-compatible HTTP, retries, batching, loopback/RFC1918 guard | The *only* module allowed to open a socket. Injectable for tests (fake ASGI server). |
| `llm/budget.py` | Token estimation (`/tokenize` when detected, chars/4 heuristic else), headroom reservation, breadth-first truncation | Pure logic over strings + a token-count callable; no HTTP of its own. |
| `render/` | Case store → md/json/pdf | Read-only over the store. Reproducibility contract lives here (stable ordering, timestamps isolated). |
| `cli.py` + `config.py` | Command wiring, config precedence | Thin; no business logic. |

The SPEC's repo layout (§7) maps 1:1 onto these boundaries — keep it.

## Architectural Patterns (validated against ecosystem)

### Pattern 1: Cheap-first reduction funnel (Drain-style dedup before embeddings)

**What:** Mask volatile tokens (numbers, hex, UUIDs, SIDs, paths, timestamps) → group by template → embed only one exemplar per group.
**Ecosystem evidence:** Drain3 pipelines universally strip structured header fields first and mine only the free-text message body; template groups then feed any downstream ML. ClickHouse, OpenTelemetry, and IBM production pipelines all use this shape.
**Refinement for Sift:** mask the `message` field only (severity/component/thread already extracted by adapters) — masking the whole raw line degrades template quality. Template signature should be `(source, component, masked_message)` so identical messages from different components stay distinct.

### Pattern 2: Lazy vector-table creation keyed to discovered dimension

**What:** sqlite-vec `vec0` virtual tables bake the dimension into DDL (`float[768]`). Dimension is only knowable after the first `/v1/embeddings` call.
**Implication:** the `vectors` table cannot be created in the initial migration. Create it at first embed, record `(embedding_model, dimension)` in `meta`, and hard-error on mismatch at reload — SPEC already requires the mismatch error; the *lazy creation* consequence should be explicit in the store design.
**Trade-off:** store module gains one dynamic DDL path; alternative (pre-creating at a guessed dimension) is strictly worse.

### Pattern 3: PRAGMA `user_version` migrations, destructive for vector tables

**What:** Ordered numbered migrations run in a transaction on DB open; `PRAGMA user_version` tracks position. ~30 lines of stdlib code; the standard pattern for embedded per-case databases — Alembic is overkill here.
**sqlite-vec caveat:** `vec0` virtual tables cannot be `ALTER`ed; any vector schema change is drop-and-rebuild (re-embed). This is acceptable *because* cases are per-file and re-ingest is idempotent — migrations may declare "vectors invalidated, re-run analyze". Document that contract in `store.py`.

### Pattern 4: Mechanical citation gate + bounded repair loop

**What:** (1) request JSON via server grammar/schema-constrained decoding when available; (2) Pydantic-validate; on failure one repair round-trip carrying the validation errors; (3) *independently* verify every `supporting_event_ids` entry exists in the case store; reject/regenerate once; persist raw + mark run degraded on second failure.
**Ecosystem evidence:** citation-grounding research converges on exactly this: mechanical post-hoc verification (ID/interval checks against the retrieved store) beats trusting model self-citation; constrained decoding fixes shape but not grounding — you need both.
**Known residual gap:** ID-existence validation catches fabricated IDs but not *irrelevant-but-real* IDs (models retrofit citations onto parametric claims). SPEC's eval-harness "citation validity spot-check by pattern" (§6) is the right mitigation — treat it as the second half of this pattern, not an optional metric.

### Pattern 5: Explicit per-component token budget with breadth-first degradation

**What:** Assign each prompt zone (system, case stats, timeline, cluster exemplars, KB, hint) an explicit budget; reserve output headroom up-front; on overflow shrink exemplars breadth-first (more clusters, shorter excerpts) rather than dropping whole clusters.
**Ecosystem evidence:** hierarchical/zoned budgeting with explicit generation reserve is the documented best practice for limited-context local models; llama.cpp's `/tokenize` endpoint gives exact counts (feature-detect; chars/4 heuristic fallback — chars/2 for JSON-heavy text is a known refinement worth adopting for exemplars containing stack traces/JSON).
**Boundary note:** `budget.py` should take a `count_tokens: Callable[[str], int]` — the client supplies either the `/tokenize`-backed counter or the heuristic. Keeps budget pure and network-free in tests.

### Pattern 6: Chunking = template groups, not fixed-size windows

**What:** Generic RAG chunking (fixed token windows with overlap) is wrong for logs. The natural embedding unit is the template-group exemplar (SPEC's `chunks` with `event_ids` array). Multi-line events (stack traces, MCM blocks) are one event and one chunk; condense to top frames for the embedded `text` while keeping full `raw` for citation display — the eustack adapter already does this per SPEC.
**Guard:** cap chunk `text` length (e.g. first ~1–2 KB of a masked exemplar) so pathological events don't blow embedding-server batch limits.

## Data Flow — key details the roadmap should encode

1. **Batch embedding:** `/v1/embeddings` accepts an input array; llama-server processes it subject to `--ubatch-size`. Client batches configurable (SPEC §5.6) — keep batches modest (e.g. 32–64) and retry-per-batch, since a failed mega-batch loses everything. Embedding model typically runs as a *second* llama-server instance with `--embeddings`; per-role `base_url` in config is therefore essential, and `sift doctor` must probe both.
2. **HDBSCAN metric gotcha (design-relevant):** neither scikit-learn's `HDBSCAN` nor the `hdbscan` package supports cosine directly. Normalise embeddings to unit length and cluster with euclidean (rank-equivalent to cosine), or precompute a cosine-distance matrix (fine at exemplar counts — hundreds, not millions). Noise points (`-1`) must become singleton clusters, never dropped — SPEC's "nothing disappears from the evidence trail" rule extends to clustering.
3. **Cluster labelling is a separate, deferrable LLM pass** (SPEC open question 3). Architecturally it only feeds the renderer and the `unexplained_signals` field — it can run lazily at report time without touching the hypothesis path. Lean lazy: saves tokens on `analyze` re-runs.
4. **KB index is a second, independent vector store** (global under `~/.local/share/sift/kb` per SPEC's lean). It shares the embedding model+dimension constraint with case stores — record model/dimension in KB meta too, and have `doctor` cross-check.

## Suggested Build Order (confirms SPEC M1–M8 with two notes)

The SPEC milestone order is dependency-correct:

| Order | Milestone | Depends on | Why here |
|-------|-----------|-----------|----------|
| 1 | M1 skeleton + Event + genericlog | — | Contract layer (`models.py`) + one adapter proves the schema; everything downstream consumes `Event`. |
| 2 | M2 store + template dedup | M1 | Full write path with zero LLM dependency; testable at 100 MB scale before any network code exists. |
| 3 | M3 client + doctor + embeddings + HDBSCAN | M2 (chunks exist) | First network surface; dimension discovery + lazy vec0 creation land here. |
| 4 | M4 salience + RAG + citations | M3 (clusters exist) | The core value; budget.py and the citation gate land here. |
| 5 | M5 remaining adapters | M1 contract only | Deliberately *after* M4: adapters are parallel-safe leaf modules; proving the end-to-end pipeline on genericlog first de-risks the whole system before investing in domain parsers. |
| 6 | M6 renderers + KB | M4 (hypotheses exist) | Renderers are read-only consumers; KB extends retrieve. |
| 7 | M7 eval harness + golden cases | M4–M6 (full pipeline) | Metrics need the pipeline; thresholds gate regressions thereafter. |
| 8 | M8 packaging + deploy | all | Leaf. |

**Note A — pull a minimal eval skeleton earlier.** SPEC §6 says "quality must be measurable from day one" but the harness lands at M7. Resolve the tension cheaply: M4's acceptance already requires one golden case — structure it as `eval/cases/<name>/` with a `truth.yaml` from the start, so M7 formalises metrics over an existing corpus rather than retrofitting. This is a file-layout decision, not extra work.

**Note B — M5 can overlap M4.** The adapter Protocol is frozen at M1; journald/dsserrors/eustack touch nothing outside `adapters/`. If parallel execution is available, M5 plans can run alongside M4 without conflict. (Respect the milestone red/green gate — overlap the *planning/implementation*, gate the *acceptance* sequentially.)

## Anti-Patterns (domain-specific)

### Anti-Pattern 1: Feeding raw or lightly-filtered logs to the LLM
**What people do:** dump grep'd log excerpts into the prompt and ask "what went wrong".
**Why it's wrong:** LLMs degrade sharply on noisy high-volume input; context budgets make it impossible past trivial sizes; results are non-reproducible.
**Do this instead:** the deterministic funnel — parse → dedup → cluster → salience — so the LLM sees a few dozen curated exemplars. (Already Sift's core design; the anti-pattern to police is *bypassing* the funnel in later features, e.g. a tempting `--raw-context` flag.)

### Anti-Pattern 2: Trusting model self-citations
**What people do:** treat the model's `supporting_event_ids` as ground truth because "we asked for citations".
**Why it's wrong:** models fabricate IDs and retrofit real-but-irrelevant citations onto parametric claims.
**Do this instead:** mechanical store lookup for existence (hard gate) + eval-suite relevance spot-checks (soft gate). Never render an unvalidated citation.

### Anti-Pattern 3: Generic RAG chunking of log files
**What people do:** fixed-size token windows with overlap, à la document RAG.
**Why it's wrong:** splits multi-line events mid-stack-trace, embeds millions of near-duplicate windows, destroys the event_id ↔ evidence mapping citations depend on.
**Do this instead:** event-aligned chunks = template-group exemplars (SPEC §5.3 `chunks`).

### Anti-Pattern 4: Cosine metric passed straight to HDBSCAN
**What people do:** `HDBSCAN(metric="cosine")` — fails or silently misbehaves depending on library/version.
**Do this instead:** L2-normalise embeddings + euclidean, or precomputed cosine-distance matrix.

### Anti-Pattern 5: Vendor SDK creep
**What people do:** adopt `openai`-the-package "because it's the compatible client", inheriting auth assumptions, telemetry, and version churn.
**Do this instead:** thin httpx wrapper (SPEC §5.6). llama-server and Lemonade both work by base-URL swap; the raw HTTP surface is small and stable.

## Scaling Considerations

| Scale | Adjustment |
|-------|-----------|
| Typical case (≤ 2 GB logs → tens of thousands of chunks) | SPEC architecture as-is; sqlite-vec brute-force KNN is fine at this size. |
| First bottleneck: ingest parse throughput on 100 MB+ files | Stream line-by-line, batch inserts in transactions (~10k rows), compile adapter regexes once. Hits at M2's <60 s gate. |
| Second bottleneck: embedding round-trips | Batched `/v1/embeddings` (32–64/req); template dedup already caps exemplar count in the hundreds–low thousands. |
| ~1M+ chunks/case | Revisit sqlite-vec (SPEC's stated trade-off boundary) — out of v1 scope. |

## Integration Points

### External Services

| Service | Integration Pattern | Gotchas |
|---------|---------------------|---------|
| llama-server (generation) | httpx → `/v1/chat/completions`; feature-detect `/props`, `/tokenize`, JSON-schema/GBNF constrained decoding | Grammar support varies by version — always keep the Pydantic-validate + repair path even when constrained decoding is on. |
| llama-server (embeddings) | second instance with `--embeddings`; httpx → `/v1/embeddings` with input arrays | Pooling mode/`--ubatch-size` are server-side; dimension discovered from first response. |
| Lemonade Server | same OpenAI surface; no llama.cpp-specific endpoints guaranteed | Feature-detect, never require `/props`/`/tokenize`. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| adapters ↔ pipeline | `Event` iterator only | Adding adapter #5 must touch only `adapters/` + registration (SPEC hard rule). |
| pipeline stages ↔ each other | via case-store tables, not in-memory hand-off | Enables re-running any stage; `analyze` resumable after embed failure. |
| pipeline ↔ network | exclusively through `llm/client.py` | Injectable; enforces loopback/RFC1918 refusal; the only socket in the codebase. |
| budget ↔ client | `count_tokens` callable injected into budget | Keeps budget pure/offline-testable. |
| store ↔ everything | typed store API, no raw SQL outside `store.py` | Migrations (`user_version`) owned here; vec0 lazy-create here. |

## Sources

- Drain3 template mining: [logpai/Drain3](https://github.com/logpai/Drain3), [Drain algorithm walkthrough](https://deepwiki.com/logpai/Drain3/3-drain-algorithm), [IBM log-template mining in production](https://medium.com/swlh/how-mining-log-templates-can-be-leveraged-for-early-identification-of-network-issues-in-b7da22915e07), [ClickHouse log clustering](https://clickhouse.com/blog/improve-compression-log-clustering) — MEDIUM (multi-source)
- Local RAG with llama-server: [MachineLearningMastery RAG with llama.cpp](https://machinelearningmastery.com/building-a-rag-pipeline-with-llama-cpp-in-python/), [llama-server embeddings usage](https://github.com/fabiomatricardi/llama-server-embeddings), [RAG production pitfalls](https://markaicode.com/architecture/rag-architecture-with-llamacpp/) — MEDIUM
- sqlite-vec vec0 tables, KNN, dimension-in-DDL: [asg017/sqlite-vec docs via Context7](https://github.com/asg017/sqlite-vec) — MEDIUM (curated official docs)
- HDBSCAN parameters and cosine limitation: [scikit-learn issue #28631](https://github.com/scikit-learn/scikit-learn/issues/28631), [hdbscan docs](https://hdbscan.readthedocs.io/en/latest/basic_hdbscan.html), [HDBSCAN text-clustering guide](https://www.cognitivetoday.com/2026/07/clustering-unstructured-text-hdbscan/) — MEDIUM
- Citation grounding / mechanical verification: [Citation grounding via citation graphs (arXiv 2606.00898)](https://arxiv.org/html/2606.00898), [citation-grounded code comprehension (arXiv 2512.12117)](https://arxiv.org/html/2512.12117v1), [why citation RAG still hallucinates](https://yaihq.com/research/citation-based-rag-still-hallucinates) — MEDIUM
- Token budgeting: [token budget zones](https://dev.to/swapnanilsaha/llm-context-window-token-budget-why-your-window-fills-up-fast-4c05), [managing token budgets](https://apxml.com/courses/getting-started-with-llm-toolkit/chapter-3-context-and-token-management/managing-token-budgets), [llama.cpp /tokenize usage](https://strandsagents.com/docs/user-guide/concepts/model-providers/llamacpp/) — MEDIUM
- SQLite migrations via user_version: [levlaz](https://levlaz.org/sqlite-db-migrations-with-pragma-user_version/), [eskerda suckless migrations](https://eskerda.com/sqlite-schema-migrations-python/), [SQLite forum](https://sqlite.org/forum/forumpost/0f9dd8806f) — MEDIUM
- Comparable tools: [k8sgpt](https://github.com/k8sgpt-ai/k8sgpt), [HolmesGPT architecture (CNCF)](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/), [RAG for security incident analysis (arXiv 2603.18196)](https://arxiv.org/pdf/2603.18196) — MEDIUM

---
*Architecture research for: local-first LLM log-triage CLI (Sift)*
*Researched: 2026-07-16*
