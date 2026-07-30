---
phase: 20-seed-002-embedding-vector-reuse-det-01
plan: 03
subsystem: store
tags: [embedding-reuse, sqlite-vec, ddl, destructive, transaction, recovery]

# Dependency graph
requires:
  - phase: 20-seed-002-embedding-vector-reuse-det-01
    provides: "plan 20-01's reuse read + ClusterResult; plan 20-02's re_embed flag and announce seam"
provides:
  - "CaseStore.drop_vector_tables() -> tuple[int, int] — the paired vec0 drop, kb_chunks clear and shared-dim meta clear"
  - "the dimension-change branch of --re-embed inside cluster_and_label's single transaction"
  - "the D-09 blast-radius announcement with real counted totals"
affects: [20-04-determinism-adjacency]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "a destructive operation whose two halves cannot be separated is exposed as ONE method, so the corruption path is structurally impossible rather than merely tested"
    - "recovery from a hard guard works by clearing the state the guard reads BEFORE it runs, never by adding a bypass parameter to the guard"
    - "the operator-facing count comes from the destructive call's own return value, so the announced number and the deletion are provably the same event"

key-files:
  created: []
  modified:
    - src/sift/store.py
    - src/sift/pipeline/cluster.py
    - tests/test_store_vectors.py
    - tests/test_cluster.py

key-decisions:
  - "Deviated from RESEARCH.md Open Question 1's two-method recommendation: ONE drop_vector_tables() rather than drop_vectors_table() + drop_kb_vectors_table(). The pairing is a corruption path (the two tables share meta.embedding_dim, so dropping one leaves the other at a stale declared width that CREATE VIRTUAL TABLE IF NOT EXISTS silently no-ops against), the shared meta clear belongs to neither table alone, and the single method leaves the phase with no new dimension-interpolating DDL at all — deleting T-20-04 by construction rather than by convention"
  - "ensure_vectors_table is byte-for-byte untouched: no bypass parameter, no force flag, no reordering. The rebuild clears meta before the guard runs (RESEARCH Pitfall 4), so weakening it for the recovery path could never weaken it for the default path"
  - "Recreation deliberately stays out of the method: `vectors` is recreated by the ensure_vectors_table(dim) call the caller already makes, and `kb_vectors` lazily on the next --kb run. Eagerly recreating kb_vectors would create it on cases that never use --kb"
  - "kb_chunks is cleared alongside the dropped kb_vectors — index_kb replaces the whole table on every --kb run anyway, so nothing is lost that would not have been replaced, and the half-surviving-pair inconsistency D-08 targets becomes impossible"
  - "The announcement fires after the in-transaction drop but before the commit, which is what makes D-09's 'before doing it' true: nothing is lost until COMMIT, and the rollback test proves a pre-commit failure restores both tables at their original widths"

patterns-established:
  - "_seed_both_vector_tables test helper populates both vec0 tables at a given width so a drop has something real to count"
  - "the rollback test proves the undo with an insert shaped for the ORIGINAL width — an insert at the new width against a genuinely restored table would fail, so success is the discriminating evidence"
  - "_width_handler(width) test helper returns arbitrary-width embeddings without touching the shared _embed_handler's planted 8-dim _VECTORS"

requirements-completed: []

coverage:
  - id: D1
    description: "A dimension change WITHOUT --re-embed still hard-raises the shipped STORE-03 error and drops nothing"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_dimension_change_without_re_embed_still_hard_raises"
        status: pass
      - kind: unit
        ref: "tests/test_store_vectors.py::test_ensure_vectors_table_dim_mismatch_is_hard_error (shipped, unmodified)"
        status: pass
    human_judgment: false
  - id: D2
    description: "A dimension change WITH --re-embed drops both vec0 tables in the same transaction and rebuilds at the new width"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_re_embed_rebuilds_at_new_dimension_and_announces"
        status: pass
      - kind: unit
        ref: "tests/test_store_vectors.py::test_drop_vector_tables_clears_dim_and_allows_new_width"
        status: pass
    human_judgment: false
  - id: D3
    description: "The drop announces its blast radius with the real counted row totals, before the commit"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_re_embed_rebuilds_at_new_dimension_and_announces"
        status: pass
    human_judgment: false
  - id: D4
    description: "A failure anywhere in the rebuild transaction rolls back to the ORIGINAL tables at their ORIGINAL declared widths"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py::test_drop_vector_tables_rollback_restores_original_width"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_failure_mid_transaction_does_not_lock_dimension (shipped, unmodified)"
        status: pass
    human_judgment: false
  - id: D5
    description: "After a rebuild, ensure_kb_vectors_table(new_dim) creates kb_vectors at the NEW width rather than no-opping against a survivor"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py::test_drop_vector_tables_clears_dim_and_allows_new_width"
        status: pass
    human_judgment: false
  - id: D6
    description: "No new dimension-interpolating DDL: FLOAT[ sites stay at 2 and the noqa: S608 suppression count is unchanged"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "grep -c 'FLOAT\\[' src/sift/store.py == 2; grep -c 'noqa: S608' src/sift/store.py == 16 (unchanged from HEAD~)"
        status: pass
    human_judgment: false
  - id: D7
    description: "kb_chunks rows are cleared alongside the dropped kb_vectors"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py::test_drop_vector_tables_clears_dim_and_allows_new_width"
        status: pass
    human_judgment: false

duration: ~12min
completed: 2026-07-30
status: complete
---

# Phase 20 Plan 03: Dimension-Change Recovery Summary

**An embedding-dimension change is no longer an unrecoverable wedge: `sift analyze --re-embed` drops both vec0 tables in one transaction, announces exactly what it is discarding, and rebuilds at the new width.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-30
- **Completed:** 2026-07-30
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `CaseStore.drop_vector_tables()` drops `vectors` and `kb_vectors` together, clears the orphaned `kb_chunks` rows and the shared `embedding_dim`/`embedding_metric` meta keys, and returns the real counted row totals. Caller-owns-transaction, documented as such.
- The dimension branch of `--re-embed` runs as the first statements of the one transaction `cluster_and_label` already owns, so a partial drop can never commit. Any other combination (no flag, or no dimension change) leaves the transaction body exactly as plans 20-01/20-02 left it.
- D-09 announcement: `dimension changed 8 -> 4; dropping 5 stored vectors and 0 KB vectors`, emitted after the in-transaction drop and before the commit, with counts taken from the drop's own return value.
- The STORE-03 guard is untouched, so a dimension change without `--re-embed` still raises `embedding dimension mismatch` naming both dimensions and drops nothing (asserted by comparing the `sqlite_master` table set across the failed run).
- 6 new tests: 3 in `tests/test_store_vectors.py` (rebuild-at-new-width including the `kb_vectors` width pin, the rollback, the empty case) and 3 in `tests/test_cluster.py` (hard-raise without the flag, announce-and-rebuild with it, no announcement at an unchanged dimension).

## Task Commits

1. **Task 1 + Task 2: `drop_vector_tables`, the dimension branch, the announcement and all 6 tests** - `cf6a9cc` (feat)

Landed together: Task 2's only caller is Task 1's method, and Task 1's method is unreachable until Task 2 calls it, so splitting would commit dead code.

## Files Created/Modified
- `src/sift/store.py` - `drop_vector_tables()` added immediately after `ensure_kb_vectors_table` so the create/drop pair reads together
- `src/sift/pipeline/cluster.py` - `stored_dim` read and `rebuild_dim` condition before the transaction; the drop plus D-09 announcement as the first statements inside it
- `tests/test_store_vectors.py` - `_seed_both_vector_tables` helper and 3 new tests (append-only; the shipped `_tables(db)` helper reused verbatim)
- `tests/test_cluster.py` - `_width_handler(width)` helper and 3 new tests

## Decisions Made
- Took **one** `drop_vector_tables()` rather than RESEARCH.md's recommended two single-table methods. Full reasoning is in the plan's `<design_deviation_from_research>` block and repeated in `key-decisions` above; the decisive point is that the single method removes T-20-04 (SQL injection via an interpolated `dim` in new DDL) by construction, because there is no new CREATE site at all.
- Added `test_re_embed_at_unchanged_dimension_announces_nothing` beyond the plan's named tests, pinning that the plan 20-02 behaviour is genuinely untouched. Without it, an over-broad rebuild condition would announce and drop on every `--re-embed` run and no test would notice.
- `test_dimension_change_without_re_embed_still_hard_raises` seeds an extra unseen message so the run has a real cache miss. Without a miss, the 20-02 width guard has no fresh vector to compare against and the dimension change would never be exercised — the test would pass for the wrong reason.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - stale acceptance criterion] The `S608 == 3` grep was wrong about the baseline**
- **Found during:** Task 1 verification
- **Issue:** The plan asserts `grep -c "S608" src/sift/store.py` returns 3 "the three pre-existing justified sites". The real pre-existing count is 20 occurrences / 16 `noqa: S608` suppressions — the criterion was written against a much older state of the file.
- **Fix:** Verified the criterion's actual intent instead: that the new method adds no suppressed site. First implementation interpolated the table name into `SELECT count(*) FROM {table}` and needed a suppression, so it was rewritten to pass fully literal SQL strings. `grep -c "noqa: S608"` is now 16, byte-identical to `HEAD~`.
- **Files modified:** `src/sift/store.py`
- **Verification:** `grep -c "noqa: S608" src/sift/store.py` = 16 = `git show HEAD~:src/sift/store.py | grep -c "noqa: S608"`; `grep -c "FLOAT\[" src/sift/store.py` = 2.
- **Committed in:** `cf6a9cc`

**2. [Rule 1 - imprecise acceptance criterion] `grep -c "store.transaction()"` counts docstrings**
- **Found during:** Task 2 verification
- **Issue:** The criterion expects 1, but the literal string appears 4 times in `cluster.py` — three of them in docstrings that legitimately describe the caller-owns-transaction idiom. The criterion's intent is "no second transaction and no savepoint was introduced".
- **Fix:** Verified the intent directly: exactly one `with store.transaction():` statement (line 501), and the total count is unchanged from `HEAD~` at 4, so nothing was added.
- **Files modified:** None (verification method corrected).
- **Verification:** `grep -n "store.transaction()" src/sift/pipeline/cluster.py` shows one statement and three docstring mentions; count matches `HEAD~`.
- **Committed in:** `cf6a9cc`

---

**Total deviations:** 2 auto-fixed (both stale/imprecise acceptance criteria, verified by intent), plus 2 additional test decisions recorded above.
**Impact on plan:** No scope or behaviour change. Deviation 1 strengthened the implementation (removed an interpolated-SQL site that would otherwise have needed a suppression).

## Issues Encountered
None. The empirically verified sqlite-vec behaviour the plan relied on held: dropping the primary vec0 name removed all four shadow tables, and a mid-transaction rollback restored the original table at its original declared width (proven by a successful 8-wide insert afterwards).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full gate green: `uv run pytest` 857/857 passed, `uv run ruff check` clean, `uv run pyright` unchanged at the pre-existing 28-error baseline
- `tests/test_store_vectors.py` is append-only (the only `^-` line in its diff is the `---` header)
- `ensure_vectors_table` verified untouched (`git diff src/sift/store.py | grep -c "def ensure_vectors_table"` = 0)
- T-20-03 (rated **high**) is mitigated with all three controls individually tested: announced blast radius, single-transaction atomicity with a proven rollback, and unreachability without an explicit `--re-embed`
- DET-01 remains OPEN: plan 20-04 (determinism adjacency + ADR 0018) is the last one

---
*Phase: 20-seed-002-embedding-vector-reuse-det-01*
*Completed: 2026-07-30*
