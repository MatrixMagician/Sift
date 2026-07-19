# Phase 3: Inference Client, Doctor, Embeddings & Semantic Clustering - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 11 (5 new source, 3 modified source, prompt, tests, pyproject)
**Analogs found:** 10 / 11 (one genuinely new: the HTTP client boundary)

All analogs are in-tree Phase-1/2 code. The executor should mirror these exact
patterns — the codebase has strong, self-consistent conventions (whole-line
`_sanitise` at render, allowlisted SQL, `BEGIN IMMEDIATE`/savepoint transactions,
typer-free/SQL-free pipeline modules, stderr-only transient progress, layered
Pydantic config). Deviating from them will fail review.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/llm/__init__.py` | package init | — | `src/sift/pipeline/__init__.py` (empty/namespace) | exact |
| `src/sift/llm/client.py` | service (HTTP client) | request-response | *(no analog — first HTTP module)* | no-analog |
| `src/sift/llm/budget.py` | utility (token estimate seam) | transform | `src/sift/pipeline/dedup.py` (pure module, injectable client) | role-match |
| `src/sift/pipeline/cluster.py` | service (pipeline stage) | batch/transform | `src/sift/pipeline/dedup.py` | exact |
| `src/sift/prompts/cluster_label.md` | config (versioned template) | file-I/O | *(new; loaded via importlib.resources)* | no-analog (mechanism cited) |
| `src/sift/store.py` (migration 3 + vec0 + WR-07) | model (case store) | CRUD | `_migration_2` + `transaction()`/`savepoint()` in same file | exact |
| `src/sift/config.py` (`[embeddings]`,`[clustering]`,inference knobs) | config | request-response | `SiftConfig` + `load_config` in same file | exact |
| `src/sift/cli.py` (`doctor` + analyze embed/cluster leg) | controller (CLI) | request-response | `_ingest` (progress + transaction + fail-loud) in same file | exact |
| `tests/test_*` (client/doctor/store_vectors/cluster/budget) | test | — | existing `tests/` + `conftest.py` fixtures | role-match |
| fake inference server (`MockTransport` handler) | test fixture | request-response | `conftest.py` `_no_network` autouse fixture | role-match |
| `pyproject.toml` (4 deps) | config | — | existing `[project.dependencies]` block | exact |

## Pattern Assignments

### `src/sift/store.py` — migration 3, lazy vec0, WR-07 (model, CRUD)

**Analog:** same file, `_migration_2` (lines 108-146) + `transaction`/`savepoint`/`_migrate` (lines 236-300).

**Migration registration** — add `_migration_3` and register it (mirror lines 143-146):
```python
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,   # chunks + clusters tables (NOT vectors — that is lazy)
}
```
The `_migrate` runner (lines 236-258) already applies new versions inside `BEGIN IMMEDIATE`, prints the stderr migration note, and rolls back on `BaseException` with the IN-03 dead-transaction guard. New migration functions just take `conn` and issue `CREATE TABLE` — copy the `_migration_2` shape exactly, including the module-constant column-list + `# noqa: S608` convention (lines 328, 407).

**CHECK-constraint + column-list-constant idiom** (mirror lines 114-128 and 154-157): clusters/chunks tables should follow the same `CHECK (... IN (...))` severity vocabulary and a `_CLUSTER_COLUMNS`/`_CHUNK_COLUMNS` module constant used in `INSERT ... ({_X_COLUMNS}) VALUES (?, ...)` with the S608 noqa comment.

**Lazy vec0 table (D-03, dimension unknown until first embed)** — new method, NOT in a migration. The RESEARCH Pattern 3 shape is correct; guard the dim interpolation with the same "code-constant, never user data" precedent the file already documents for `PRAGMA user_version` (lines 248-249) and savepoint names (lines 283-287):
```python
def ensure_vectors_table(self, dim: int) -> None:
    existing = self.get_meta("embedding_dim")
    if existing is not None and int(existing) != dim:
        raise ValueError(f"embedding dimension mismatch: index has {existing}, server returned {dim}")
    if existing is None:
        _load_sqlite_vec(self._conn)   # enable_load_extension(True) → sqlite_vec.load → (False) immediately
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vectors "
            f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{int(dim)}])"  # noqa: S608 — dim is our int, never user text
        )
        self.set_meta("embedding_dim", str(dim))
        self.set_meta("embedding_metric", "cosine")
```
`get_meta`/`set_meta` already exist (lines 464-473) — reuse them for `embedding_model`, `embedding_dim`, `embedding_metric`, label-prompt hash (STORE-03). Keep `enable_load_extension(True)` then `(False)` immediately (Security Domain: native extension loading). Load lazily — NOT in `__init__` (Anti-Pattern: llama-free environments must still open cases).

**Vector (de)serialisation confined here** (RESEARCH Pattern 4): `np.asarray(vec, dtype="<f4").tobytes()`. Mirror the "SINGLE read/write path" idiom the file uses for zstd raw (`_encode_raw`/`_decode_raw`, lines 32-49) — one `_vec_to_blob`/`_blob_to_vec` pair, all vector bytes inside store.py (the BLOB+numpy escape hatch stays an afternoon's work).

**`replace_clusters` / caller-owns-transaction idiom** — mirror `replace_template_groups` (lines 399-421): `DELETE FROM clusters` then `executemany` insert; the CALLER (cluster.py, via `store.transaction()`) owns the transaction, exactly as `rebuild_template_groups` wraps `replace_template_groups` (dedup.py lines 129-135).

**WR-07 disk-full fix** — this is a `cli.py` change, not store.py (see below), but store.py's `transaction()`/`savepoint()` rollback catches (lines 267-271, 291-297) already tolerate a dead transaction, so no store change is needed for WR-07 beyond confirming those catches.

**Tampered-DB read guard** (mirror lines 441-461): any JSON/text read back from clusters must assume a hostile shared `case.db` — coerce with the same `cast`/`isinstance` defensive pattern used for `exemplar_event_ids`.

---

### `src/sift/cli.py` — WR-07 fix + `doctor` + analyze embed/cluster leg (controller)

**Analog:** `_ingest` (lines 149-331) — progress bar, transaction, fail-loud per-item, exit codes.

**WR-07 fatal-code reclassification** — the fix goes in the `_ingest` per-file `except Exception` at line 277. Insert a `sqlite3.Error` check BEFORE the generic handler (RESEARCH Pitfall 1). The current except swallows-and-continues; a `SQLITE_FULL`/`SQLITE_IOERR` must abort:
```python
except sqlite3.Error as exc:
    code = getattr(exc, "sqlite_errorcode", None)
    if code in (sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR) or (
        code is not None and code & 0xFF == sqlite3.SQLITE_IOERR
    ):
        raise DiskFullError(
            f"disk full / I/O error during ingest at {_sanitise(relpath)}: "
            "no events committed (transaction rolled back)"
        ) from exc
    # else fall through to existing recoverable per-file handling
except Exception as exc:
    ...  # existing lines 277-293 unchanged
```
`sqlite3` is already imported (line 10). Exit non-zero on abort; sanitise relpath (T-04-01 precedent, everywhere in this file). Note: catch order — `sqlite3.Error` before `Exception`.

**Embedding-leg progress bar** — copy the `_ingest` `Progress` block verbatim (lines 192-213), swapping the description to a STATIC `TextColumn("Embedding")` (T-02-06: never put untrusted text in rich renderables) and `DownloadColumn()` for a count column. Keep `console=Console(stderr=True)`, `transient=True`, `disable=not err_console.is_terminal` — stdout stays scriptable, non-TTY renders nothing deterministically (CLI-03).

**`doctor` fail-fast sequence (D-02)** — replace the stub at lines 512-516. Follow the RESEARCH Code-Examples order: construct client (runs SSRF guard) → `GET /v1/models` generation → `GET /v1/models` embeddings → real `POST /v1/embeddings` probe → dim-vs-index compare → `sqlite_vec.load` + `vec_version()` → `/props` determinism WARN. Stop at first CRITICAL with `raise typer.Exit(1)`; print warnings without failing. Reuse the exact fail-loud idiom this file uses everywhere: `print(f"Error: {_sanitise(str(exc))}")` then `raise typer.Exit(1) from None` (mirror `_case_store` lines 76-81 and the `show` handler lines 442-445).

**Config resolution + `--i-know-what-im-doing` flag** — every command opens with `config = load_config({"data_dir": data_dir})` (line 95, 138, 446). `doctor`/`analyze` add the `--i-know-what-im-doing` bool flag (Annotated typer.Option) threaded to the client constructor for the LLM-02 override. The `--model` flag feeds config precedence (D-03).

**analyze embed/cluster leg** — replace stub at lines 491-495. Mirror `ingest`'s structure: `_case_store(case, config)` (line 64-81) to open, `try/finally: store.close()` for WAL checkpoint (lines 142-147, Pitfall 4). Orchestration calls into `pipeline.cluster` (which is print/SQL/typer-free), exactly as `ingest` delegates to `dedup.rebuild_template_groups` (line 326).

---

### `src/sift/pipeline/cluster.py` — HDBSCAN + fallback + label (service, batch/transform)

**Analog:** `src/sift/pipeline/dedup.py` (entire file) — the pipeline-module contract.

**Module contract** (mirror dedup.py docstring lines 1-9): typer-free, print-free, SQL-free; persistence goes ONLY through `CaseStore` methods. Reads its input from the store (dedup reads `iter_event_summaries`; cluster reads `query_template_groups` for exemplars), computes, writes back inside a single `store.transaction()`.

**Orchestration + transaction wrapping** (mirror `rebuild_template_groups` lines 92-135):
```python
def cluster_and_label(store, client, cfg) -> int:
    groups = store.query_template_groups()            # existing method, line 423
    vectors = client.embed([exemplar_text(g) for g in groups])  # batched (LLM-01)
    store.ensure_vectors_table(len(vectors[0]))       # dim guard (STORE-03)
    # ... HDBSCAN on normalised vectors (RESEARCH Pattern 5) ...
    labels = client.chat(build_label_prompt(...))     # one batched call (D-01)
    with store.transaction():                          # caller owns the transaction
        store.upsert_vectors(...)
        store.replace_clusters(...)
        store.set_meta("cluster_label_prompt_hash", ...)
    return n_clusters
```

**HDBSCAN / agglomerative** — use RESEARCH Pattern 5 verbatim (`sklearn.cluster.HDBSCAN`, `AgglomerativeClustering(metric="cosine", linkage="average")`, `sklearn.preprocessing.normalize` L2, noise `-1` → singletons). Params come from `cfg` (config `[clustering]`), NOT hard-coded (D-04). Executor must confirm A2 (linkage constraint) at impl.

**Config-constant idiom** — module constants for tuned defaults mirror dedup's `MASK_VERSION`/`EXEMPLAR_K`/`_SEVERITY_RANK` (lines 16, 50-60), but the values live in config `[clustering]` per D-04; only truly-fixed constants stay in-module.

---

### `src/sift/prompts/cluster_label.md` (config, versioned template) + loader

**Analog:** none in-tree (`prompts/` is new this phase), but the loader mechanism is cited:
```python
from importlib.resources import files
TEMPLATE = files("sift.prompts").joinpath("cluster_label.md").read_text(encoding="utf-8")
```
CLI-02: changing the prompt touches no Python. Record the prompt hash in `meta` (mirror the `mask_version`/`MASK_VERSION` meta-write in dedup.py line 131). Requires `src/sift/prompts/__init__.py` for `importlib.resources` package access.

---

### `src/sift/config.py` — `[embeddings]`, `[clustering]`, inference knobs (config)

**Analog:** same file, `SiftConfig` + `load_config` (entire file, 61 lines).

**Add nested models to `SiftConfig`** (mirror lines 21-41). Keep `model_config = ConfigDict(extra="forbid")` on every model (T-04-02: typo'd key fails loud). Nested `[embeddings]`/`[clustering]` become nested `BaseModel` fields with defaults:
```python
class EmbeddingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None            # D-03: NO baked default
    base_url: str = "http://localhost:13305/v1"
    timeout: float = 60.0
    batch_size: int = 64

class ClusteringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: str = "hdbscan"
    min_cluster_size: int = 2
    min_samples: int = 1                 # sklearn counts self: +1 vs standalone
    epsilon: float = 0.0
    distance_threshold: float = 0.3
    # ...tuned defaults, overridable (D-04)

class SiftConfig(BaseModel):
    ...
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    clustering: ClusteringConfig = ClusteringConfig()
```

**`SIFT_*` env mapping** — `load_config` (lines 44-60) currently maps only `SIFT_DATA_DIR` (lines 56-57). The docstring (lines 8-10) explicitly flags: "A generalised `SIFT_*` -> key mapping arrives when later phases add scalar config keys." **This phase is that phase.** Add the scalar env keys (e.g. `SIFT_EMBEDDINGS_BASE_URL`, `SIFT_GENERATION_BASE_URL`, timeouts) into the `layers` dict before `model_validate`, preserving the precedence order (defaults → toml → env → flags, lines 47-59). Field-validator precedent for early failure is `_zones_must_exist` (lines 29-41) — add a validator that rejects a malformed `base_url` at config time if desired (the client's `_assert_local` is the real SSRF guard).

---

### `src/sift/llm/client.py` — InferenceClient (service, request-response) — NO ANALOG

**No in-tree analog: this is the first and only HTTP module.** Use RESEARCH Patterns 1 & 2 verbatim (injectable `httpx.Client`, `_assert_local` SSRF guard at construction, manual backoff loop over `ConnectError`/`TimeoutException`/5xx). Constraints that ARE cross-cutting conventions to honour:
- **Injectability** (EVAL-05): constructor takes `http: httpx.Client` so tests pass a `MockTransport`-backed client. Mirrors the pipeline-module "inject the store" seam.
- **Untrusted-response defence** (Pitfall 4, V5): validate returned embedding dimension, cap label length, explicit timeouts. Treat the local server exactly as the store treats a tampered `case.db`.
- **`_sanitise` on any server text surfaced to the terminal** — reuse `cli.py`'s `_sanitise` (lines 42-61) when doctor/analyze print model IDs or error text from the server.

---

### `src/sift/llm/budget.py` — PromptBudget seam (utility, transform)

**Analog:** `dedup.py` pure-function style (small, stateless, injectable dependency). Use RESEARCH Code-Example shape: `/tokenize` when `client.has_tokenize`, else `max(1, len(text)//4)`. Label-budget slice only this phase; full breadth-first truncation is Phase 4.

---

### Tests + fake inference server (test)

**Analog:** `tests/conftest.py` (`_no_network` autouse fixture, lines 34-50) + `_isolate_dirs` (lines 15-32).

- **Do NOT edit conftest.py** — it is 01-01-owned (docstring line 3, and RESEARCH Wave-0 note line 564). Add fake-inference fixtures in the new test modules themselves.
- **Fake server**: `httpx.Client(transport=httpx.MockTransport(_handler))` (RESEARCH Code Examples) — no socket opens, so `_no_network` needs no relaxation. Planted deterministic vectors: synonymous templates → near-identical, noise → orthogonal (CLUS-02 assertion).
- **Live path**: mark any real-server integration test `@pytest.mark.live` and register the marker in `pyproject.toml` `[tool.pytest.ini_options].markers`, mirroring the existing `perf` marker (pyproject lines 35-37) and `addopts = "-m 'not perf'"` → `"-m 'not perf and not live'"`.
- **WR-07 test**: force `SQLITE_FULL` via `PRAGMA max_page_count=<small>` on the connection (RESEARCH Pitfall 1 test tip); assert exit non-zero, zero events, disk-full message.
- Test file naming mirrors existing `tests/test_*.py`; quick-run `uv run pytest tests/test_x.py -x`.

---

### `pyproject.toml` — 4 deps (config)

**Analog:** existing `[project.dependencies]` (lines 7-14) + `[dependency-groups].dev` (lines 16-21).
```bash
uv add httpx==0.28.1 sqlite-vec==0.1.9 scikit-learn==1.9.0   # runtime; numpy transitive
uv add --dev respx                                            # 0.23.1
```
Follow the existing explicit-declaration convention (the rich comment at lines 8-9 shows the project declares direct imports explicitly even when transitively present). `uv.lock` must be committed. Confirm `PKG-01` clean-checkout install still works.

## Shared Patterns

### Fail-loud + sanitise-at-render
**Source:** `cli.py` `_sanitise` (lines 42-61); usage at 76-81, 290, 444, 464-472.
**Apply to:** every doctor/analyze print of server text, filenames, or DB-sourced strings. Whole-LINE sanitisation, not per-field (WR-01). Error → `print(f"Error: {_sanitise(str(exc))}")` + `raise typer.Exit(N) from None`.

### Atomic transaction wrapping (caller-owns)
**Source:** `store.py` `transaction()`/`savepoint()` (lines 260-300); `dedup.py` usage (lines 129-135).
**Apply to:** cluster.py persistence, all migration-3 writes. Pipeline modules never `BEGIN` themselves except via `store.transaction()`; the IN-03 dead-transaction rollback guard is already in the context managers.

### Allowlisted SQL / column-list constants
**Source:** `store.py` `_EVENT_COLUMNS`/`_TEMPLATE_GROUP_COLUMNS` + `_build_filter_clauses` (lines 148-209) with `# noqa: S608` convention.
**Apply to:** new `chunks`/`clusters` inserts and any `show clusters` filtering. Values always `?`-bound; keys never reach SQL text.

### Meta-versioned derived artefacts
**Source:** `dedup.py` `MASK_VERSION` + `set_meta("mask_version", ...)` (lines 16, 131); `store.py` `get_meta`/`set_meta` (464-473).
**Apply to:** `embedding_model`/`embedding_dim`/`embedding_metric`, cluster-label prompt hash, `template_groups_stale`-style staleness flags if clusters need one.

### stderr-only transient progress (CLI-03)
**Source:** `cli.py` `_ingest` Progress block (lines 192-213).
**Apply to:** the embedding leg. Static description string; `console=Console(stderr=True)`; `transient=True`; `disable=not err_console.is_terminal`.

### Injectable dependency for zero-network tests (EVAL-05)
**Source:** `conftest.py` `_no_network` (34-50); pipeline modules take `store` as a param.
**Apply to:** InferenceClient takes `httpx.Client`; cluster.py takes `client` + `store`. Tests inject `MockTransport`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/sift/llm/client.py` | service | request-response | First HTTP module in the codebase — no existing network code. Use RESEARCH Patterns 1 & 2; honour the shared sanitise/inject/untrusted-input conventions above. |
| `src/sift/prompts/cluster_label.md` | config | file-I/O | First prompt template. Loader mechanism (`importlib.resources.files`) is cited in RESEARCH; no code analog. |

## Metadata

**Analog search scope:** `src/sift/` (store.py, config.py, cli.py, pipeline/dedup.py), `tests/conftest.py`, `pyproject.toml`.
**Files scanned:** 6 source/config files read in full.
**Pattern extraction date:** 2026-07-17
