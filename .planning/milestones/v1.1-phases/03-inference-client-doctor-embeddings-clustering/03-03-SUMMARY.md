---
phase: 03-inference-client-doctor-embeddings-clustering
plan: 03
subsystem: store
tags: [sqlite-vec, vec0, embeddings, clustering, store-03, migration, numpy]
status: complete

# Dependency graph
requires:
  - phase: 02-case-store-template-dedup
    provides: CaseStore _MIGRATIONS/_migrate runner, BEGIN IMMEDIATE transaction(), replace_template_groups caller-owns pattern, allowlisted SQL + defensive JSON coerce
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 01
    provides: sqlite-vec / numpy runtime deps pinned in uv.lock
provides:
  - "Migration 3: chunks + clusters tables (schema now user_version 3)"
  - "ensure_vectors_table(dim): lazy sqlite-vec vec0 table at server dimension; STORE-03 hard-error dim guard"
  - "record_embedding_identity(model, dim): embedding provenance in meta, never masks the dim guard"
  - "_vec_to_blob/_blob_to_vec: the only float32 little-endian vector (de)serialisation path (confined to store.py)"
  - "upsert_vectors / replace_clusters / replace_chunks / query_clusters / set_cluster_labels (caller-owns-transaction)"
  - "Cluster frozen dataclass"
affects: [03-04-doctor, 03-05-clustering]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy vec0 table: dimension unknown until first embed, so created outside migrations (D-03)"
    - "STORE-03 dim guard raises before any extension load or write; record_embedding_identity only sets dim when absent, else raises"
    - "sqlite-vec loaded once per connection via _ensure_vec_loaded flag; enable_load_extension(True)->load->(False) in a finally"
    - "Single _vec_to_blob/_blob_to_vec pair mirrors the _encode_raw/_decode_raw SINGLE-path idiom — all vector bytes stay in store.py"
    - "vec0 has no INSERT OR REPLACE: upsert_vectors deletes-then-inserts per chunk_id"

key-files:
  created:
    - tests/test_store_vectors.py
  modified:
    - src/sift/store.py
    - tests/test_store.py

key-decisions:
  - "D-03 honoured: vectors vec0 table is lazy (ensure_vectors_table), never created in a migration nor in __init__ — a llama-free environment still opens Phase-1/2 cases"
  - "STORE-03 honoured: reload with a mismatched embedding_dim raises ValueError naming both dims BEFORE any extension load or write; never a silent re-index"
  - "record_embedding_identity records the model + sets dim only when absent; a differing dim raises, so it can never defeat the hard-error guard"
  - "clusters table carries the same six-severity CHECK vocabulary as events/template_groups"

patterns-established:
  - "Pattern: lazy native-extension load guarded by a per-connection bool flag, loaded only inside the embedding entry point (T-03-09)"
  - "Pattern: confined vector (de)serialisation pair keeps the BLOB+numpy escape hatch an afternoon's work"

requirements-completed: [STORE-03, EVAL-05]

coverage:
  - id: C1
    description: "Migration 3 adds chunks + clusters at user_version 3; llama-free open creates no vectors table; clusters enforces the severity CHECK"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py::test_migration_3_* (3 tests)"
        status: pass
    human_judgment: false
  - id: C2
    description: "Lazy vec0 table at server dim; STORE-03 hard error on mismatch before any write; float32 blob round-trip; vec_version() loads; upsert round-trip + replace"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py (ensure_vectors_table / dim-guard / blob / upsert / record_embedding_identity — 7 tests)"
        status: pass
    human_judgment: false
  - id: C3
    description: "replace_clusters/query_clusters round-trip ordered count DESC; set_cluster_labels by id; tampered template_ids coerces to list[str]; filters allowlisted; replace_chunks round-trip"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py::*cluster* + test_replace_chunks_round_trips (7 tests)"
        status: pass
    human_judgment: false
---

# Phase 3 Plan 03: Store Embeddings & Clusters Persistence Summary

Extended `CaseStore` with the embedding + cluster persistence surface: migration 3
(chunks + clusters tables), a lazily-created sqlite-vec `vec0` vectors table whose
dimension is discovered from the server's first embedding, the STORE-03 hard-error
dimension guard, the confined float32 (de)serialisation pair, and the
caller-owns-transaction `replace_clusters` / `replace_chunks` / `upsert_vectors`
methods with defensive reads. All vector bytes stay inside `store.py`.

## What was built

- **Migration 3** (`_migration_3`, registered `3: _migration_3` in `_MIGRATIONS`):
  `chunks(chunk_id, template_id, text, event_ids)` and
  `clusters(cluster_id, label, signature, severity_max CHECK(...), count, template_ids)`.
  `_CHUNK_COLUMNS` / `_CLUSTER_COLUMNS` allowlisted column constants. The vectors
  table is NOT created here (D-03 — dimension unknown until first embed).
- **Lazy vec0 + dim guard** — `ensure_vectors_table(dim)` reads `meta.embedding_dim`;
  a mismatch raises `ValueError` naming both dims *before* loading the extension or
  writing anything (STORE-03 / T-03-08). sqlite-vec is loaded once per connection
  via `_ensure_vec_loaded` (`enable_load_extension(True)->sqlite_vec.load->(False)`
  in a `finally`, T-03-09), never in `__init__`. `record_embedding_identity`
  records the model and only sets the dim when absent.
- **Confined serialisation** — `_vec_to_blob` (`np.asarray(vec, dtype="<f4").tobytes()`)
  and `_blob_to_vec` are the only vector byte path, mirroring the `_encode_raw`/`_decode_raw`
  single-path idiom. `upsert_vectors` writes `(chunk_id, blob)` pairs, caller-owns-transaction.
- **Cluster persistence** — frozen `Cluster` dataclass; `replace_clusters` / `replace_chunks`
  (DELETE + executemany), `query_clusters` (ordered count DESC, cluster_id; allowlisted
  filters; template_ids coerced defensively against a tampered case.db, T-03-10),
  `set_cluster_labels` (update label by id, D-01).

## Threat model

All three `mitigate` dispositions delivered:
- **T-03-08** (mismatched dim reload): `ensure_vectors_table` + `record_embedding_identity`
  raise before any write; test asserts `embedding_dim` is unchanged after the raise.
- **T-03-09** (native extension load): loaded lazily, only the vetted `sqlite_vec`,
  `enable_load_extension(False)` re-locked immediately in a `finally`, never in `__init__`.
- **T-03-10** (hostile JSON in clusters): `query_clusters` coerces `template_ids` to
  `list[str]` (non-array wrapped as a single element), mirroring the `exemplar_event_ids`
  guard. Test plants `'"oops"'` and asserts `["oops"]`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated 3 stale schema-version assertions in tests/test_store.py**
- **Found during:** Task 3 (full-suite regression check)
- **Issue:** `test_fresh_store_reaches_user_version_2`, `test_v1_to_v2_upgrade`, and
  `test_reopen_migrated_store_is_noop` hardcoded the latest schema as `user_version == 2`.
  Migration 3 correctly bumps the schema to 3, so these three asserts failed — a direct
  consequence of this plan's change, not a pre-existing unrelated failure.
- **Fix:** Renamed the first to `test_fresh_store_reaches_latest_user_version`, updated the
  three `== 2` version asserts to `== 3`, and refreshed the docstrings.
- **Files modified:** tests/test_store.py
- **Commit:** 49e0533

## Verification

- `uv run pytest tests/test_store_vectors.py` — 17 passed
- `uv run pytest` — 229 passed, 1 deselected (full suite green, no regressions)
- `uv run ruff check` + `uv run pyright` — clean on store.py and both test files

## Commits

- 865d2d7: feat(03-03): migration 3 — chunks + clusters tables
- 258bd19: test(03-03): failing tests for lazy vec0 + dim guard + serialisation (RED)
- b0a58d3: feat(03-03): lazy vec0 vectors table + dim guard + confined float32 path (GREEN)
- 49e0533: feat(03-03): Cluster dataclass + replace_clusters/replace_chunks + defensive reads

## Notes for downstream

- `pipeline/cluster.py` (Plan 05) calls `ensure_vectors_table(dim)` then `upsert_vectors`
  + `replace_clusters` + `replace_chunks` inside a single `store.transaction()`.
- `cli.py doctor` (Plan 04) reuses the `vec_version()` load path and compares
  `meta.embedding_dim`.
- KNN retrieval (`WHERE embedding MATCH ? AND k = ?`) is noted in an
  `ensure_vectors_table` comment for Phase 4/6; not used this phase.

## Self-Check: PASSED

- tests/test_store_vectors.py — FOUND
- 03-03-SUMMARY.md — FOUND
- Commits 865d2d7, 258bd19, b0a58d3, 49e0533 — all FOUND in git log
