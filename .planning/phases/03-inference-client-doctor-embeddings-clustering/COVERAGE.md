# Phase 3 — External API Coverage Matrix

**API:** OpenAI-compatible local inference server (llama.cpp `llama-server` / AMD Lemonade Server)
**Generated:** 2026-07-17 (planning)
**Rule:** INTEGRATE is the default; every OPT-OUT carries a one-line reason. A malformed/partial
matrix blocks the phase seal at verify:pre.

## Endpoint / Capability Matrix

| Endpoint / Capability | Disposition | Reason |
|-----------------------|-------------|--------|
| `GET /v1/models` | INTEGRATE | `doctor` reports model IDs on both roles (LLM-03) |
| `POST /v1/embeddings` | INTEGRATE | batched exemplar embeddings (LLM-01, CLUS-02) + `doctor` real round-trip (LLM-03) |
| `POST /v1/chat/completions` | INTEGRATE | one batched cluster-label call (CLUS-03) |
| `GET /props` | INTEGRATE (feature-detected) | context length + determinism check (`n_parallel`/seed) in `doctor` (LLM-03/LLM-04); absent → graceful |
| `POST /tokenize` | INTEGRATE (feature-detected) | PromptBudget token estimation (RAG-05); absent → chars/4 fallback (LLM-04) |
| `response_format.schema` (llama.cpp nesting) | OPT-OUT | labels are freeform this phase; the llama.cpp shape is feature-detected and noted for Phase 4, not required now |
| Grammar / GBNF constrained decoding | OPT-OUT | not needed for freeform labels; JSON-contract enforcement is Phase 4 (M4) |
| `tools` / function-calling | OPT-OUT | agentic tool-calling is explicitly out of scope (REQUIREMENTS.md Out of Scope) |
| Streaming (SSE) responses | OPT-OUT | batch determinism is the product identity; not needed this phase |
| `POST /v1/completions` (legacy, non-chat) | OPT-OUT | chat + embeddings cover Sift's needs; legacy completion unused |
| KNN `MATCH ... AND k = ?` (sqlite-vec query) | OPT-OUT | clustering reads the whole vector matrix; KNN retrieval arrives in Phase 4/6 (shape noted in store.py) |
| Remote / cloud OpenAI endpoints | OPT-OUT | hard loopback/RFC1918 refusal (LLM-02); cloud LLM is out of scope by design |

## Artifacts this phase produces

> Read by the convergence source-grounding pass to exclude newly-created symbols from drift
> verification. The intel `API-SURFACE.md` is regex-derived and empty — treat this list as the
> authoritative record of Phase-3-created symbols.

### New modules & packages
- `src/sift/llm/__init__.py` — new package (the only HTTP module namespace)
- `src/sift/llm/client.py` — `Endpoint` (frozen dataclass), `_assert_local(base_url, allow_public)`, `InferenceClient` (`__init__`, `embed`, `chat`, `tokenize`, `props`, `has_tokenize`, `has_props`, `_request`)
- `src/sift/llm/budget.py` — `PromptBudget` (`estimate`, `fit`)
- `src/sift/pipeline/cluster.py` — `cluster_and_label(store, client, cfg)`, `exemplar_text(group)`, `build_label_prompt(clusters, budget)`
- `src/sift/prompts/__init__.py` — new package (importlib.resources access)
- `src/sift/prompts/cluster_label.md` — versioned label prompt template (CLI-02)

### Store additions (`src/sift/store.py`)
- migration `_migration_3` registered as `3` in `_MIGRATIONS`
- new tables: `chunks`, `clusters` (via migration 3); `vectors` sqlite-vec `vec0` table (lazy, at first embed)
- `Cluster` dataclass; `_CHUNK_COLUMNS` / `_CLUSTER_COLUMNS` constants
- methods: `ensure_vectors_table(dim)`, `record_embedding_identity(model, dim)`, `_load_sqlite_vec(conn)`, `_vec_to_blob(vec)`, `_blob_to_vec(blob)`, `upsert_vectors(rows)`, `replace_chunks(chunks)`, `replace_clusters(clusters)`, `query_clusters(filters)`, `set_cluster_labels(labels)`
- new `meta` keys: `embedding_model`, `embedding_dim`, `embedding_metric`, `cluster_label_prompt_hash`

### Config additions (`src/sift/config.py`)
- `GenerationConfig`, `EmbeddingsConfig`, `ClusteringConfig` nested models; `SiftConfig.embeddings` / `.clustering` / generation fields
- generalised `SIFT_*` scalar env mapping (e.g. `SIFT_EMBEDDINGS_BASE_URL`, `SIFT_GENERATION_BASE_URL`, `SIFT_EMBEDDINGS_MODEL`, `SIFT_GENERATION_MODEL`, `SIFT_EMBEDDINGS_BATCH_SIZE`)

### CLI additions (`src/sift/cli.py`)
- `DiskFullError` (WR-07); fatal-SQLite-code reclassification in `_ingest`
- `doctor` command (real implementation) + `--i-know-what-im-doing` / `--model` flags
- `analyze` command (embed→cluster→label leg) + `--no-label` flag + embedding progress bar
- `show clusters` renders `clusters.label` (signature fallback)

### Tests & config
- `tests/test_disk_full.py`, `tests/test_llm_client.py`, `tests/test_budget.py`, `tests/test_store_vectors.py`, `tests/test_cluster.py`, `tests/test_doctor.py`, `tests/test_analyze.py`
- new pytest marker `live` (registered in `pyproject.toml`, excluded by default addopts)
- 4 new deps: `httpx`, `sqlite-vec`, `scikit-learn` (→ numpy), `respx` (dev)

### Docs
- `docs/decisions/0004-cluster-label-timing.md` (ADR — D-01)
