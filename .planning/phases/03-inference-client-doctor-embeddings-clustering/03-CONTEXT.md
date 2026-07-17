# Phase 3: Inference Client, Doctor, Embeddings & Semantic Clustering - Context

**Gathered:** 2026-07-17
**Status:** Ready for planning

<domain>
## Phase Boundary

The first network surface. A user can point Sift at a locally hosted OpenAI-compatible
inference endpoint (llama.cpp `llama-server` or AMD Lemonade Server), verify it with
`sift doctor`, then run the embedding + semantic-clustering stage of `sift analyze`:
one exemplar per template group is embedded (batched), vectors persist in the sqlite-vec
`vectors` table with the embedding dimension recorded in `meta`, HDBSCAN merges
synonymous template groups into `clusters`, and each cluster receives a short
LLM-generated human-readable label. Maps to SPEC.md milestone M3.

Delivers: LLM-01 (single OpenAI-compatible httpx client, per-role base_urls, timeouts,
backoff retries, batched embeddings), LLM-02 (loopback/RFC1918 refusal unless
`--i-know-what-im-doing`), LLM-03 (`sift doctor` real round-trips incl. an actual
embedding call, dimension check), LLM-04 (feature-detect `/props`, `/tokenize`, grammar
decoding, `response_format` nesting — never required), STORE-03 (embedding identity +
dimension in `meta`, mismatch = hard error), CLUS-02 (HDBSCAN semantic clustering,
agglomerative fallback, noise→singleton), CLUS-03 (LLM cluster labels from exemplars
only, strict token budget), and the embedding leg of CLI-03 (progress feedback).

Not in this phase: salience ranking, the triage/hypothesis prompt, JSON contract
enforcement, and citation validation (Phase 4); renderers/KB (Phase 6); domain adapters
(Phase 5). Cluster *labelling* is in scope; hypothesis *generation* is not.

</domain>

<decisions>
## Implementation Decisions

### Cluster label timing (SPEC §10 Open Question #3 — RESOLVED)
- **D-01:** Labels are generated **eagerly** in the clustering stage of `sift analyze` and
  persisted to `clusters.label`. `sift show clusters` displays the label once clustering has
  run (raw `signature` shown until then / when `--no-label` or no endpoint). One batched LLM
  call per run over exemplars only, under a strict token budget. Record this resolution as an
  ADR in `docs/decisions/` (SPEC §10 requires open-question decisions recorded there).
  Rationale: `sift show clusters` is the pre-AI inspection surface (STORE-04) — a human-readable
  label there is the payoff; M3 acceptance ("cluster labels generated") is demonstrable without
  needing the Phase-6 report path.

### `sift doctor` behaviour
- **D-02:** **Fail-fast** — doctor runs checks in dependency order (generation endpoint →
  embeddings endpoint → real embedding round-trip → dimension-vs-existing-index → determinism
  warnings) and **stops at the first critical failure**, exiting non-zero. The failing check must
  name the failure mode explicitly and actionably — in particular the Lemonade OGA/ONNX-recipe
  case ("embeddings unsupported on this recipe; load a llamacpp/flm-recipe model"), endpoint
  unreachable, and embedding-dimension mismatch against an existing index. Non-critical findings
  reached before the stop (e.g. multi-slot `--parallel > 1` determinism risk) print as warnings
  without failing. The embedding check is a **real** round-trip, never just `/v1/models` listing.

### Embedding model identity
- **D-03:** **Config-only, no baked-in model default.** `embeddings.model` comes from
  config.toml / `SIFT_*` / `--model`; Sift asserts nothing about which model is loaded. `doctor`
  and the embed path record whatever identity + dimension the server actually returns into `meta`
  (STORE-03). A dimension mismatch against an existing index is a hard error; identity is recorded
  for provenance. Rationale: SPEC §3 says "defaults, all configurable" and a wrong baked default
  risks silent identity mismatch the dimension check alone can't catch.

### HDBSCAN clustering configuration
- **D-04:** Clustering parameters ship as **tuned defaults in code, overridable via
  `[clustering]` in config.toml**: `min_cluster_size`, `min_samples` (remember sklearn counts the
  point itself — +1 vs standalone hdbscan semantics), `cluster_selection_epsilon`, `metric =
  "cosine"`, and the agglomerative-fallback cosine `distance_threshold`. Use
  `sklearn.cluster.HDBSCAN` (research-locked; no standalone `hdbscan` package). Noise points become
  singleton clusters. Weights/thresholds are provisional — revisit after the golden suite exists
  (Phase 7), same posture SPEC §10 #4 takes for salience.

### Claude's Discretion (planner/executor decide, guided by SPEC + research)
- httpx client internals: retry/backoff schedule, timeout values, embedding batch size default,
  connection pooling, per-role `base_url` wiring.
- Feature-detection mechanism for `/props`, `/tokenize`, grammar/JSON-schema decoding, and the
  llama.cpp `response_format.schema` nesting (send llama.cpp's shape; never require it).
- `PromptBudget` token-estimation seam (tokenize endpoint when present, else chars/4) — only the
  label-budgeting slice is needed this phase; full triage budgeting lands Phase 4.
- Progress-feedback mechanism for the embedding leg (reuse the Phase-2 ingest progress pattern).
- Exact `chunks`/`vectors`/`clusters` migration SQL and sqlite-vec `vec0` table definition.
- Fake OpenAI-compatible test server shape (respx vs tiny ASGI stub) — EVAL-05: never hit the network.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Specification (authoritative)
- `SPEC.md` §5.3 — Case Store tables (`chunks`, `vectors`, `clusters`, `meta`); embedding dim in `meta`
- `SPEC.md` §5.4 — Deduplication & Clustering (two-stage; HDBSCAN + agglomerative fallback; label generation)
- `SPEC.md` §5.6 — Inference Client contract (per-role base_url, endpoints, retries, loopback refusal, `sift doctor`)
- `SPEC.md` §8 M3 — acceptance criteria for this phase
- `SPEC.md` §3 — model assumptions ("defaults, all configurable")
- `SPEC.md` §10 #3 — cluster-label-timing open question (resolved here as D-01 → record ADR)

### Research (constraints & pitfalls — in `.claude/CLAUDE.md` Technology Stack section)
- sqlite-vec `vec0` API: `create virtual table vectors using vec0(chunk_id integer primary key, embedding float[<dim>])`; KNN `where embedding match ? and k = ?`; brute-force only (no IVF/DiskANN); ≤8192 dims; `enable_load_extension` required (verify in doctor via `vec_version()`)
- llama.cpp server: `response_format.schema` nesting (NOT OpenAI's `.json_schema.schema`); `--embeddings` flag makes a server embedding-only (per-role base_url is necessary not optional); `/v1/embeddings` needs pooling≠none, returns normalised vectors (cosine≡L2 ranking); `/props`, `/tokenize` for feature-detection
- Lemonade Server: default port 13305 (config-only, never assumed); `/v1/embeddings` works **only** for `llamacpp`/`flm`-recipe models — OGA/ONNX models fail (doctor must round-trip a real embedding and name this failure)
- `sklearn.cluster.HDBSCAN` over standalone `hdbscan` (research-locked); `min_samples` counts self (+1 vs standalone); agglomerative fallback via `AgglomerativeClustering(metric="cosine", distance_threshold=...)`
- No vendor `openai` SDK — hand-rolled httpx client (~200 lines)

### Prior phase decisions carried forward
- `.planning/phases/01-.../01-CONTEXT.md` D-03 — `store.py` owns all migrations via `PRAGMA user_version`; Phase 3 adds the sqlite-vec `vectors` table lazily at first embed
- Phase 2 store decisions (02-01/02-04): MASK_VERSION 2, template groups + exemplars (EXEMPLAR_K=5), zstd raw>4KB, savepoint-per-file ingest — clustering consumes the existing template groups
- Config precedence hand-rolled (tomllib + Pydantic, no pydantic-settings): add `[clustering]` and `[embeddings]` sections to the existing settings model
- `docs/decisions/` is the ADR home (ADRs 0001-0003 exist); D-01 label-timing resolution goes here

</canonical_refs>

<code_context>
## Reusable Assets & Integration Points

- `src/sift/store.py` (`CaseStore`) — owns migrations, `BEGIN IMMEDIATE`/savepoint transactions,
  `meta` table, zstd raw path. Extend with a migration adding `chunks`/`vectors`/`clusters`
  (or completing them) + the sqlite-vec `vec0` virtual table. Keep ALL vector access confined here
  (BLOB+numpy escape hatch stays an afternoon's work if sqlite-vec dies).
- `src/sift/pipeline/dedup.py` — produces template groups + exemplars; the clustering stage reads
  these as its input (one exemplar chunk per group → embed → HDBSCAN).
- `src/sift/config.py` — hand-rolled precedence + Pydantic settings; add `[embeddings]`,
  `[clustering]`, and inference `base_url`/timeout/retry knobs.
- `src/sift/cli.py` — Typer app; wire `sift doctor` and the embed/cluster leg of `sift analyze`;
  reuse the Phase-2 ingest progress-bar pattern for the embedding leg (CLI-03).
- **New module** `src/sift/llm/` — the ONLY module that talks HTTP (client.py; budget.py seam).
- **New module** `src/sift/pipeline/cluster.py` — HDBSCAN + agglomerative fallback + label call.
- Tests: injectable client + fake OpenAI-compatible server (respx/ASGI); zero network egress (EVAL-05).

</code_context>

<deferred>
## Noted for Later (not this phase)

- Salience scoring, triage prompt, hypothesis JSON contract + citation validation — Phase 4 (M4).
- Full `PromptBudget` breadth-first truncation for the triage prompt — Phase 4 (only label-budgeting slice here).
- KB (knowledge-base) index + retrieval — Phase 6 (M6); per-case vs global location still open (SPEC §10 #5).
- Salience weight tuning — deferred to post-golden-suite (Phase 7), same as clustering thresholds.

</deferred>
