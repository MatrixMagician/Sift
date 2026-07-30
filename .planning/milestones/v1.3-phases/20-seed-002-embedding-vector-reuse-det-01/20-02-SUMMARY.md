---
phase: 20-seed-002-embedding-vector-reuse-det-01
plan: 02
subsystem: pipeline
tags: [embedding-reuse, determinism, model-identity, cli, analyze, disclosure]

# Dependency graph
requires:
  - phase: 20-seed-002-embedding-vector-reuse-det-01
    provides: "plan 20-01's reuse read, ClusterResult and hit/miss splice"
provides:
  - "the D-03 proven-model-change invalidation and the D-04 unverifiable-identity disclosure"
  - "cluster_and_label keyword parameters re_embed: bool = False and announce: Callable[[str], None] | None = None"
  - "sift analyze --re-embed — the cache bypass at unchanged dimension (D-07)"
  - "the T-20-08 stored-width discard guard preserving the clean STORE-03 error"
  - "the announce seam plan 20-03's destructive dimension announcement depends on"
affects: [20-03-dimension-rebuild, 20-04-determinism-adjacency, 20-05-ctx-configured]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "reuse resolution extracted into a module-private `_embed_with_reuse` helper returning (vectors, embedded_count, reused_count), keeping cluster_and_label readable as orchestration"
    - "operator-facing output leaves the pipeline through an injected callback only — the print-free/typer-free contract survives a feature that must talk to the operator"
    - "the disclosure string is a module constant emitted from the single decision site, so the message and the decision cannot drift apart"

key-files:
  created: []
  modified:
    - src/sift/pipeline/cluster.py
    - src/sift/cli.py
    - tests/test_cluster.py
    - tests/test_cli.py

key-decisions:
  - "D-03: invalidation fires ONLY on a proven change (both sides non-None and different) and emits no message — no operator action is required and the `N new, 0 reused` line already makes the re-embed visible"
  - "D-04: an unprovable identity reuses and discloses rather than invalidating; treating unknown as changed would permanently disable the feature against any endpoint that names no embedding model, and would make the feature appear to work while never firing"
  - "The D-04 warning is suppressed when the reuse map is empty (a first run, or a --re-embed run) — there is nothing reused to warn about, so the message never cries wolf"
  - "client.embedding_model is read BEFORE the embed call so it resolves to the CONFIGURED model with no network round-trip (RESEARCH Pitfall 1); read after, it would prefer the server-reported name and the decision would no longer precede the reuse read"
  - "The stored-width discard compares reused widths against the FRESH embedding's width, so it needs at least one miss to fire — the residual all-hit blind spot is the risk D-04 explicitly accepts, recorded in a code comment rather than silently left"
  - "announce is bound to err_console.print(..., soft_wrap=True, markup=False, highlight=False): the same Console that owns the transient Progress live region, so rich relocates the bar instead of a redraw erasing the line"

patterns-established:
  - "_client_with_model test helper added alongside the shipped _client rather than parameterising it — _client's model=None IS the unknown-client-side case D-04 covers, and every existing test depends on it"
  - "_tables(store) inlines the sqlite_master query rather than importing tests/test_store_vectors.py's helper, which plan 20-03 owns"

requirements-completed: []

coverage:
  - id: D1
    description: "A proven embedding-model change discards the whole reuse map and re-embeds every exemplar"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_invalidated_on_model_change"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_proceeds_silently_when_model_unchanged"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unknown identity on either side still reuses, and a warning naming the unverifiable identity reaches the announce seam"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_proceeds_with_warning_on_unknown_identity[None]"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_proceeds_with_warning_on_unknown_identity[model-a]"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_no_warning_on_first_run_with_unknown_identity"
        status: pass
    human_judgment: false
  - id: D3
    description: "The warning is emitted from the single decision site through the injected callback, never recomputed at the CLI"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "_UNVERIFIED_IDENTITY_WARNING referenced once in cluster.py; cli.py contains no identity comparison (grep -c 'embedding_model' src/sift/cli.py == 0)"
        status: pass
    human_judgment: false
  - id: D4
    description: "The warning is written through the same rich stderr Console that owns the transient progress bar, with wrapping disabled"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "grep -c 'soft_wrap=True' src/sift/cli.py == 1; grep -c 'err_console.print' src/sift/cli.py == 1"
        status: pass
    human_judgment: false
  - id: D5
    description: "--re-embed at unchanged dimension bypasses the cache, reports 0 reused, and performs no DDL"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_re_embed_bypasses_cache_without_ddl"
        status: pass
      - kind: unit
        ref: "tests/test_cluster.py::test_re_embed_on_empty_cache_embeds_everything"
        status: pass
      - kind: integration
        ref: "tests/test_cli.py::test_analyze_accepts_re_embed_flag"
        status: pass
    human_judgment: false
  - id: D6
    description: "A changed stored-vector width discards the reuse map and surfaces the clean STORE-03 error, not a numpy ragged-array failure"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_discarded_when_stored_vector_width_differs"
        status: pass
      - kind: manual
        ref: "guard temporarily disabled in-tree — the test fails with numpy's 'inhomogeneous shape' error, proving the assertion is non-vacuous"
        status: pass
    human_judgment: false
  - id: D7
    description: "cluster.py still contains no direct standard-output call and no Typer import"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "grep -v '^\\s*#' src/sift/pipeline/cluster.py | grep -c 'print(' == 0 and typer import count == 0"
        status: pass
    human_judgment: false

duration: ~14min
completed: 2026-07-30
status: complete
---

# Phase 20 Plan 02: Reuse Safety — Identity Gate, Disclosure and `--re-embed` Summary

**Reuse now invalidates on a proven model change, discloses on an unprovable one, refuses to splice stale-width vectors, and can be bypassed outright with `sift analyze --re-embed`.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-07-30
- **Completed:** 2026-07-30
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Reuse resolution extracted into `_embed_with_reuse`, which owns the whole decision chain in one place: `--re-embed` override → identity gate → dedupe/embed misses → width discard → order-preserving splice. `cluster_and_label` reads as orchestration again.
- D-03 gate: both sides known and different discards the map and re-embeds everything, silently (the `N new, 0 reused` line is the disclosure). Both known and equal reuses silently.
- D-04 disclosure: either side unknown still reuses, and emits `_UNVERIFIED_IDENTITY_WARNING` through the injected `announce` callback — containing the pinned fragment `without a verifiable model identity` — but only when something was actually reused, so a first run and a `--re-embed` run stay quiet.
- T-20-08 width guard: any reused vector whose length differs from the fresh embedding's width discards the entire map and re-embeds, so `normalize()`/HDBSCAN never sees a ragged list and the operator still receives the shipped STORE-03 `embedding dimension mismatch` error naming both dimensions.
- `sift analyze --re-embed` added in the `no_label` flag style, threaded to `re_embed=`, documented in the command docstring with the ADR 0005 exit-code block untouched. Table set in `case.db` asserted identical across a `--re-embed` run (no DDL).
- 9 new tests in `tests/test_cluster.py` (including a parametrised pair covering both unknown identity sides) and 1 in `tests/test_cli.py`.

## Task Commits

1. **Task 1 + Task 2: identity gate, disclosure seam, width guard, `--re-embed` and all 10 tests** - `b2cae40` (feat)

Landed as one commit: Task 1 adds the `re_embed` parameter that Task 2's flag threads to, and both tasks modify the same `cluster_and_label` call site, so splitting them would leave an unreachable parameter in the intermediate state.

## Files Created/Modified
- `src/sift/pipeline/cluster.py` - `_UNVERIFIED_IDENTITY_WARNING` constant; new `_embed_with_reuse` helper carrying the identity gate, the conditional embed and the width discard; `re_embed`/`announce` keyword parameters on `cluster_and_label`; `Callable` imported from `collections.abc`
- `src/sift/cli.py` - `--re-embed` option on `analyze`; docstring sentence describing reuse and the flag; `announce` bound to `err_console.print(..., highlight=False, markup=False, soft_wrap=True)`
- `tests/test_cluster.py` - `_client_with_model` and `_tables` helpers; 9 new tests spanning invalidation, both unknown-identity sides, the no-warning-on-first-run case, the width discard, and three `--re-embed` behaviours
- `tests/test_cli.py` - `test_analyze_accepts_re_embed_flag`

## Decisions Made
- Added three tests beyond the plan's named set, each closing a hole a reader would otherwise have to take on trust: `test_reuse_proceeds_silently_when_model_unchanged` (proves the gate does not fire on an unchanged model, so the invalidation test is not passing for the wrong reason), `test_reuse_no_warning_on_first_run_with_unknown_identity` and `test_re_embed_suppresses_the_unverified_identity_warning` (both pin the "only warn when something was actually reused" condition, without which the disclosure would cry wolf on every first run).
- Parametrised `test_reuse_proceeds_with_warning_on_unknown_identity` over `stored_model in (None, "model-a")` rather than writing two near-identical tests, covering both unknown sides D-04 names.
- The width guard compares against the fresh embedding's width, which means it requires at least one miss to fire. The plan anticipated this residual all-hit blind spot; it is recorded as a code comment at the guard so a later reader does not mistake it for an oversight, and the width test seeds an extra unseen message precisely to create that miss.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - pyright strict] Bare `{}` in a conditional expression inferred as `dict[Unknown, Unknown]`**
- **Found during:** Task 1 verification (`uv run pyright src/sift/pipeline/cluster.py`)
- **Issue:** `reuse_map = {} if re_embed else store.load_vectors_by_text()` left pyright unable to infer the empty branch's type, producing a `reportUnknownArgumentType` error at the `_embed_misses(reuse_map)` call. The plan's own acceptance criterion requires 0 pyright errors on this file.
- **Fix:** Annotated the binding as `reuse_map: dict[str, list[float]]`.
- **Files modified:** `src/sift/pipeline/cluster.py`
- **Verification:** `uv run pyright src/sift/pipeline/cluster.py src/sift/cli.py` → 0 errors.
- **Committed in:** `b2cae40`

---

**Total deviations:** 1 auto-fixed (type annotation), plus 3 additional tests recorded under Decisions Made.
**Impact on plan:** No scope change; the extra tests strengthen conditions the plan specified in prose but named no test for.

## Issues Encountered
None. The plan's flagged concern — that `client.embed`'s own per-response length check might pre-empt the width guard — did not materialise: that check validates consistency *within* one batch, so a uniformly 4-wide response passes it and the guard is genuinely the first thing to notice the change.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full gate green: `uv run pytest` 851/851 passed (841 after 20-01 + 10 new), `uv run ruff check` clean, `uv run pyright` unchanged at the pre-existing 28-error baseline confined to `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py`
- All 8 of the plan's acceptance criteria pass, including `grep -c "re_embed" src/sift/store.py` returning 0 and `tests/test_store_vectors.py` verified unmodified
- The width guard's non-vacuity was verified destructively (guard disabled in-tree → numpy inhomogeneous-shape failure → guard restored → green), so the STORE-03 assertion is known to be testing the guard rather than incidental behaviour
- The `announce` seam plan 20-03 needs for its destructive dimension announcement is live and covered
- DET-01 remains OPEN: plans 20-03 (dimension rebuild via `drop_vector_tables`), 20-04 (determinism adjacency + ADR 0018) and 20-05 (ctx_configured) remain

---
*Phase: 20-seed-002-embedding-vector-reuse-det-01*
*Completed: 2026-07-30*
