---
phase: 20-seed-002-embedding-vector-reuse-det-01
plan: 01
subsystem: pipeline
tags: [embedding-reuse, determinism, sqlite-vec, cluster, cli, analyze]

# Dependency graph
requires:
  - phase: 03-semantic-clustering
    provides: "cluster_and_label, upsert_vectors/replace_chunks, the vec0 vectors table and the _vec_to_blob/_blob_to_vec confined pair"
provides:
  - "CaseStore.load_vectors_by_text() — the D-01 text-keyed reuse read (chunks JOIN vectors, deterministically ordered)"
  - "ClusterResult frozen dataclass (cluster_count/embedded_count/reused_count) — the D-05 return-type migration"
  - "the hit/miss split + order-preserving splice inside cluster_and_label"
  - "case meta keys embedding_new_count / embedding_reused_count"
  - "the D-06 `Embeddings: N new, M reused` stdout line in sift analyze"
affects: [20-02-model-invalidation-re-embed, 20-03-dimension-rebuild, 20-04-determinism-adjacency, 20-05-ctx-configured]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "reuse read happens BEFORE the transaction, while the previous run's chunks rows still exist — replace_chunks deletes them later, so a read moved inside the transaction would silently always miss"
    - "hit/miss splice by looking each text up in original `texts` order, never a hits-list + misses-list concatenation (vector_rows/rep_excerpt/HDBSCAN all index positionally)"
    - "frozen result dataclass mirroring store.TemplateGroup, so the reported split cannot be restated after the fact"

key-files:
  created: []
  modified:
    - src/sift/store.py
    - src/sift/pipeline/cluster.py
    - src/sift/cli.py
    - tests/test_cluster.py
    - tests/test_cli.py

key-decisions:
  - "D-01 reuse key is the exact exemplar text: `SELECT chunks.text, vectors.embedding FROM chunks JOIN vectors USING (chunk_id) ORDER BY chunks.chunk_id` — no schema migration, no new column"
  - "T-20-06: the ORDER BY is load-bearing, not cosmetic — it makes the duplicate-text winner deterministic (highest chunk_id) instead of leaving it to unspecified SQLite row order, inside a determinism feature"
  - "sqlite3.OperationalError from the JOIN degrades to an empty map (a fresh case has no lazily-created vec0 table yet) — reuse never raises, it falls back to a full embed"
  - "client.embed is skipped entirely when miss_texts is empty; an empty-list embed would defeat DET-01's headline zero-HTTP-call assertion"
  - "embedded_count is the DEDUPLICATED miss count (D-02 dict.fromkeys), and embedded_count + reused_count == len(texts) by construction"
  - "the split is persisted inside the SAME store.transaction() as the vectors and chunks it describes (T-20-07), never a second transaction"
  - "a `_embedding_line` test helper isolates the single `Embeddings:` line before asserting, so an unrelated `0 new` elsewhere in the output cannot satisfy a reuse assertion"

patterns-established:
  - "_blob_to_vec now has a production consumer, so its `# pyright: ignore[reportUnusedFunction]` is gone — the read half of the confined (de)serialisation pair is live"
  - "capturing cluster_and_label call sites read `.cluster_count`; the nine discarding call sites (eval/runner.py:92 + 8 tests) are untouched and green"

requirements-completed: []

coverage:
  - id: D1
    description: "A second cluster_and_label on an unchanged case makes ZERO embedding HTTP calls and returns reused_count == template-group count, assertable from the dataclass alone"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_zero_embeds_on_unchanged_case"
        status: pass
    human_judgment: false
  - id: D2
    description: "Hits and misses splice back in original group order — cluster membership after a mixed hit/miss run is identical to the all-miss first run"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_partial_cache_embeds_only_misses"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_zero_embeds_on_unchanged_case"
        status: pass
    human_judgment: false
  - id: D3
    description: "A case with no vectors table (first run) yields an empty reuse map, embeds every exemplar and raises nothing"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_empty_on_first_run_embeds_everything"
        status: pass
    human_judgment: false
  - id: D4
    description: "A partial cache left by an interrupted run reuses only the rows that join and embeds the remainder"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_partial_cache_embeds_only_misses"
        status: pass
    human_judgment: false
  - id: D5
    description: "Zero template groups short-circuits before any reuse read, embed call or write, returning a zero-valued ClusterResult"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_cluster_zero_groups_returns_zero_no_embed"
        status: pass
    human_judgment: false
  - id: D6
    description: "The split travels on the returned dataclass and is persisted to case meta inside the writes' own transaction"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_cluster_and_label_returns_result_dataclass"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_empty_on_first_run_embeds_everything"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_zero_embeds_on_unchanged_case"
        status: pass
    human_judgment: false
  - id: D7
    description: "sift analyze prints `Embeddings: N new, M reused` on EVERY run including a first run where M is 0"
    requirement: "DET-01"
    verification:
      - kind: integration
        ref: "tests/test_cli.py::test_analyze_prints_embedding_split"
        status: pass
      - kind: integration
        ref: "tests/test_cli.py::test_analyze_second_run_reports_reuse"
        status: pass
    human_judgment: false
  - id: D8
    description: "cluster.py stays print-free and Typer-free; the vector unpack stays confined to store.py"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "grep -v '^\\s*#' src/sift/pipeline/cluster.py | grep -c 'print(' == 0; grep -c 'np.frombuffer' src/sift/store.py == 1; cluster.py has 0"
        status: pass
    human_judgment: false

duration: ~18min
completed: 2026-07-30
status: complete
---

# Phase 20 Plan 01: Embedding Vector Reuse Tracer Summary

**A second `sift analyze` on an unchanged case now makes zero embedding HTTP calls, and the true embed/reuse split is visible from the return value, from `case.db` meta and on stdout.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-30
- **Completed:** 2026-07-30
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- `CaseStore.load_vectors_by_text()` reads the previous run's vectors back by exact exemplar text via `chunks JOIN vectors`, with `ORDER BY chunks.chunk_id` making the duplicate-text winner deterministic (T-20-06) and `sqlite3.OperationalError` degrading to an empty map so a first run simply embeds everything
- `cluster_and_label` gained the full reuse path: read before any write (while `chunks` rows still exist), deduplicate misses first-appearance-order (D-02), skip `client.embed` entirely when there are none, then splice hits and misses back by looking each text up in original `texts` order (D-12) so `vector_rows`/`rep_excerpt`/HDBSCAN row order stay synchronised
- Return type migrated `int` → frozen `ClusterResult(cluster_count, embedded_count, reused_count)` (D-05), with the four capturing call sites in `tests/test_cluster.py` moved to `.cluster_count` and all nine discarding call sites untouched and green
- The split is persisted as `embedding_new_count`/`embedding_reused_count` inside the same `store.transaction()` as the vectors and chunks it describes (T-20-07), so a rolled-back run cannot leave counts claiming uncommitted work
- `sift analyze` always prints `Embeddings: N new, M reused` immediately before the `Clusters:` line, matching pipeline order (D-06)
- 6 new tests: 4 in `tests/test_cluster.py` (zero-embed second run, dataclass shape, first-run full embed, partial-cache split) and 2 in `tests/test_cli.py` (the printed line across a first and second run), all reusing the shipped `_seed`/`_embed_handler`/`_client` and `_seed_analyzable`/`_patch_analyze_http`/`_analyze_handler` fixtures rather than duplicating mock boilerplate

## Task Commits

1. **Task 1 + Task 2: reuse read, ClusterResult, splice, meta counts, CLI line and all six tests** - `3b0ec4e` (feat)
2. **Pre-existing E501 fix unblocking the phase gate** - `fdf78e9` (style)

Both tasks landed in one commit: the return-type migration and its four capturing call sites cannot be split without leaving the tree red mid-sequence (`key_links` in the plan frontmatter names this explicitly), and Task 2's CLI tests assert the line Task 1 introduces.

## Files Created/Modified
- `src/sift/store.py` - `load_vectors_by_text()` added next to `upsert_vectors`; `_blob_to_vec`'s `reportUnusedFunction` suppression removed (it now has a production consumer)
- `src/sift/pipeline/cluster.py` - `ClusterResult` frozen dataclass; the reuse read / dedupe / conditional embed / order-preserving splice; the two meta writes inside the existing transaction; return type change
- `src/sift/cli.py` - call site captures `cluster_result`; the D-06 `Embeddings:` line added before `Clusters:`, which now reads `cluster_result.cluster_count`
- `tests/test_cluster.py` - 4 new DET-01 tests; 4 capturing call sites migrated to `.cluster_count`
- `tests/test_cli.py` - 2 new CLI tests plus a `_embedding_line` helper that isolates the single summary line before asserting
- `tests/test_perfmon_analyze.py` - comment rewrap only, clearing a pre-existing E501 that would otherwise fail the plan's own `uv run ruff check` gate

## Decisions Made
- The `ORDER BY chunks.chunk_id` grep acceptance criterion (`returns 1`) initially returned 2 because the method docstring quoted the clause verbatim. Reworded the docstring to describe it ("The `ORDER BY` on `chunks.chunk_id`") rather than quote it, so the grep pins the single SQL site as intended instead of being satisfied by prose.
- Added a `_embedding_line` helper in `tests/test_cli.py` rather than asserting `"0 new" in result.output` directly. The plan's wording would pass if `0 new` appeared anywhere in the output; scoping to the one `Embeddings:` line (and asserting there is exactly one) makes the assertion mean what the plan intended.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - pre-existing lint blocking the plan's own gate] E501 in `tests/test_perfmon_analyze.py`**
- **Found during:** Task 1 verification (`uv run ruff check`)
- **Issue:** An over-long comment line introduced by commit `4ba8283` (the ARCHITECTURE re-alignment) fails `uv run ruff check`, which plan 20-01's `<verification>` block requires to be clean. Confirmed pre-existing by stashing the plan's own changes and re-running.
- **Fix:** Rewrapped the comment. No assertion, hash baseline or code touched.
- **Files modified:** `tests/test_perfmon_analyze.py`
- **Verification:** `uv run ruff check` clean; `uv run pytest tests/test_perfmon_analyze.py` 4/4 pass.
- **Committed in:** `fdf78e9` (separate style commit, kept out of the feature commit)

---

**Total deviations:** 1 auto-fixed (1 pre-existing-lint unblock), plus 2 in-plan refinements recorded under Decisions Made.
**Impact on plan:** No scope change. Both refinements strengthen assertions the plan already specified.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full gate green: `uv run pytest` 841/841 passed (835 baseline + 6 new), `uv run ruff check` clean, `uv run pyright` unchanged at the pre-existing 28-error baseline confined to `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py`
- `src/sift/eval/runner.py` verified unmodified (`git diff --quiet` exits 0) — the eval harness's discarding call site keeps working
- All 8 of the plan's acceptance greps pass, including the corrected `ORDER BY` count
- Since verified against a live backend too: run 2 on an unchanged case issues zero `/v1/embeddings` requests to the operator's real Lemonade instance at dimension 1024 (`20-VERIFICATION.md` §Live-Lemonade Validation)
- DET-01 remains OPEN: plan 20-02 (model-identity invalidation + `--re-embed`), 20-03 (dimension rebuild), 20-04 (determinism adjacency) and 20-05 (ctx_configured) build directly on `ClusterResult` and the reuse path proven here

---
*Phase: 20-seed-002-embedding-vector-reuse-det-01*
*Completed: 2026-07-30*
