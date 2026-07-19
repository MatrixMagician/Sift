---
phase: 06-renderers-kb-retrieval
plan: 03
subsystem: retrieval
tags: [sqlite-vec, embeddings, rag, kb, migration, vec0, knn]

# Dependency graph
requires:
  - phase: 06-01
    provides: render/ package, store.get_events_by_ids, sift report vertical
  - phase: 03-inference-client-doctor-embeddings-clustering
    provides: InferenceClient.embed, _vec_to_blob/_blob_to_vec, ensure_vectors_table, caller-owns-transaction idiom
provides:
  - Migration 5 kb_chunks table (separate, non-citable KB namespace, no event_id column)
  - Confined KB store methods (ensure_kb_vectors_table, replace_kb_chunks, upsert_kb_vectors, knn_kb_chunks)
  - pipeline/retrieve.py (index_kb, retrieve_kb) — the KB index + retrieval data path
  - ADR 0009 recording the per-case KB location
affects: [06-04, kb-context-in-prompt, analyze-kb]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Separate physical namespace (own tables, no discriminator flag) as the structural enforcement of a non-citability invariant"
    - "KB reuses the confined vector (de)serialisation pair + embedding_dim dim-guard from the case index"
    - "Deterministic paragraph-bounded, no-overlap chunking (pure function of file text)"

key-files:
  created:
    - src/sift/pipeline/retrieve.py
    - tests/test_kb_retrieval.py
    - docs/decisions/0009-kb-index-per-case.md
  modified:
    - src/sift/store.py
    - tests/test_store.py
    - tests/test_store_vectors.py

key-decisions:
  - "KB index lives per-case inside case.db in a physically separate namespace, not a global store (ADR 0009)"
  - "D-01 non-citability is structural: kb_chunks has no event_id column; a shared/flagged table is rejected"
  - "MVP chunking/k defaults are in-code constants (KB_CHUNK_CHARS=800, KB_TOP_K=5), no config surface yet"

patterns-established:
  - "Pattern: structural invariant via schema shape — an absent column makes a whole class of bug impossible"
  - "Pattern: caller-owns-transaction embed+persist so an interrupted embed rolls back to zero rows"

requirements-completed: [RAG-07]

coverage:
  - id: D1
    description: "index_kb walks a KB dir, chunks + embeds Markdown, and retrieve_kb returns the nearest chunk by similarity (RAG-07 data path)"
    requirement: "RAG-07"
    verification:
      - kind: unit
        ref: "tests/test_kb_retrieval.py#test_index_kb_then_retrieve_returns_planted_chunk"
        status: pass
    human_judgment: false
  - id: D2
    description: "KB namespace is structurally non-citable — kb_chunks has no event_id column (D-01)"
    requirement: "RAG-07"
    verification:
      - kind: unit
        ref: "tests/test_kb_retrieval.py#test_kb_chunks_table_has_no_event_id_column"
        status: pass
    human_judgment: false
  - id: D3
    description: "An interrupted embed rolls the KB index back to zero rows (atomicity)"
    requirement: "RAG-07"
    verification:
      - kind: unit
        ref: "tests/test_kb_retrieval.py#test_index_kb_interrupted_embed_rolls_back"
        status: pass
    human_judgment: false
  - id: D4
    description: "Re-indexing the same dir yields identical chunk text/ordinals (determinism)"
    requirement: "RAG-07"
    verification:
      - kind: unit
        ref: "tests/test_kb_retrieval.py#test_index_kb_is_deterministic"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-18
status: complete
---

# Phase 6 Plan 03: KB index + retrieval data path Summary

**Per-case, structurally non-citable KB namespace (migration 5 `kb_chunks`/`kb_vectors`) plus `pipeline/retrieve.py` that indexes Markdown runbooks and retrieves nearest chunks by embedding similarity — RAG-07 satisfied without weakening `cited ⊆ prompted ⊆ store`.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments
- Migration 5 adds `kb_chunks(kb_chunk_id, source_file, ordinal, text)` with NO `event_id` column — D-01 non-citability is enforced by schema shape, not prompt wording.
- Four confined KB store methods mirror the case-vector idioms: `ensure_kb_vectors_table` (lazy vec0 DDL reusing the `embedding_dim` hard-fail guard), `replace_kb_chunks`, `upsert_kb_vectors` (via `_vec_to_blob`), and `knn_kb_chunks` (vec0 `MATCH ? AND k = ?`).
- `pipeline/retrieve.py`: `index_kb` (rglob `*.md` confined to kb_dir, deterministic chunking, embed via injected client, persist chunks+vectors in one transaction) and `retrieve_kb` (embed query, average, KNN → KB texts). Typer-free, print-free; interrupted embed rolls back to zero rows.
- ADR 0009 records the per-case KB location (SPEC §10 Q5 / RESEARCH Open Q1).

## Task Commits

1. **Task 1: RED — KB tests** - `1f9b253` (test)
2. **Task 2: GREEN — migration 5 + KB store methods + retrieve.py** - `721e94c` (feat)
3. **Task 3: ADR 0009** - `509965d` (docs)

## Files Created/Modified
- `src/sift/store.py` - migration 5 + `_KB_CHUNK_COLUMNS` + four confined KB methods
- `src/sift/pipeline/retrieve.py` - `index_kb` / `retrieve_kb` + deterministic `_chunk_text`
- `tests/test_kb_retrieval.py` - index+KNN, D-01 structural, atomicity, determinism (network-free)
- `docs/decisions/0009-kb-index-per-case.md` - per-case KB ADR
- `tests/test_store.py`, `tests/test_store_vectors.py` - head-schema assertions bumped 4 → 5

## Decisions Made
- Followed plan as specified. KB lives per-case in `case.db`; separate tables (no discriminator flag); MVP chunk/k defaults in-code.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Bumped head-schema assertions from 4 to 5**
- **Found during:** Task 2 (GREEN)
- **Issue:** Adding migration 5 raised the head schema to v5, so six pre-existing assertions/comments in `test_store.py` and `test_store_vectors.py` that hard-coded the latest `PRAGMA user_version` as 4 failed.
- **Fix:** Updated the six `== 4` assertions and their comments to `== 5` (fresh-store, v1→v2, v3→v4-now-v5, reopen-noop tests). The migration is purely additive; existing tables are untouched.
- **Files modified:** tests/test_store.py, tests/test_store_vectors.py
- **Verification:** Full suite green (401 passed).
- **Committed in:** `721e94c` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary mechanical consequence of the additive migration. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Store + pipeline seam is ready for 06-04 to thread KB context into `analyze` and the `triage.md` prompt (`kb_context=` parameter, KB block before `Evidence:`), keeping `prompted_ids` event-exemplars-only.
- The D-01 end-to-end invariant test (`cited ⊆ prompted ⊆ store` holds even when the model cites a KB chunk) is planned for 06-04.

## Self-Check: PASSED

All created files exist on disk; all three task commits (`1f9b253`, `721e94c`, `509965d`) present in git log.

---
*Phase: 06-renderers-kb-retrieval*
*Completed: 2026-07-18*
