---
phase: 03-inference-client-doctor-embeddings-clustering
plan: 01
subsystem: infra
tags: [httpx, sqlite-vec, scikit-learn, respx, pydantic, config, sqlite, wr-07]

# Dependency graph
requires:
  - phase: 01-skeleton-event-contract-genericlog
    provides: hand-rolled layered config (SiftConfig/load_config), CLI _ingest loop, _sanitise
  - phase: 02-case-store-template-dedup
    provides: CaseStore BEGIN IMMEDIATE/savepoint transactions, template-group ingest, WR-07 deferral
provides:
  - httpx / sqlite-vec / scikit-learn (numpy) runtime deps + respx dev dep, all pinned in uv.lock
  - "[generation]/[embeddings]/[clustering] Pydantic config sections with extra=forbid"
  - generalised SIFT_* scalar env layer between config.toml and CLI flags
  - "WR-07 fix: SQLITE_FULL/IOERR mid-ingest aborts with DiskFullError + zero committed events"
  - pytest 'live' marker registered and excluded by default addopts
affects: [03-02-inference-client, 03-05-clustering, doctor, embeddings]

# Tech tracking
tech-stack:
  added: [httpx==0.28.1, sqlite-vec==0.1.9, scikit-learn==1.9.0, numpy (transitive), respx==0.23.1 (dev)]
  patterns:
    - "Nested extra=forbid BaseModels default to instances on SiftConfig"
    - "SIFT_* scalar env -> (section, field) table, deep-merged per section preserving precedence"
    - "Fatal-vs-recoverable SQLite classification via exc.sqlite_errorcode before the generic handler"

key-files:
  created:
    - tests/test_disk_full.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/sift/config.py
    - src/sift/cli.py
    - tests/test_config.py

key-decisions:
  - "D-03 honoured: embeddings.model and generation.model default None — no baked embedding-model default"
  - "D-04 honoured: clustering knobs (algorithm/min_cluster_size/min_samples/epsilon/distance_threshold) config-driven; min_samples=1 documents the sklearn +1 self-count"
  - "Non-fatal sqlite3.Error handled inline in its own except clause (a sibling except cannot catch a re-raise), fatal codes raise DiskFullError"

patterns-established:
  - "Pattern 1: _ENV_SCALARS mapping table for scalar SIFT_* env overrides; nested mappings stay TOML/flag-only"
  - "Pattern 2: catch sqlite3.Error before Exception in the ingest loop; SQLITE_FULL/SQLITE_IOERR (+ IOERR low-byte extended codes) are unrecoverable aborts"

requirements-completed: [LLM-01, CLUS-02]

coverage:
  - id: D1
    description: "Four Phase-3 deps declared + installed and importable in the venv; live marker registered and excluded by default"
    verification:
      - kind: integration
        ref: "uv run python -c \"import httpx, sqlite_vec, sklearn, numpy, respx\" (exit 0)"
        status: pass
      - kind: other
        ref: "pyproject.toml markers contains live:; addopts '-m not perf and not live'"
        status: pass
    human_judgment: false
  - id: D2
    description: "[generation]/[embeddings]/[clustering] config sections load with tuned defaults, no baked embedding-model default, and the SIFT_* scalar env layer sits between toml and flags"
    requirement: LLM-01
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_new_sections_have_tuned_defaults, ::test_env_beats_toml_for_embeddings_base_url_but_flag_wins, ::test_unknown_key_under_clustering_is_a_loud_error"
        status: pass
    human_judgment: false
  - id: D3
    description: "WR-07: a forced SQLITE_FULL mid-ingest raises DiskFullError and leaves zero events committed (transaction rolled back), not a swallowed per-file parse error"
    requirement: CLUS-02
    verification:
      - kind: unit
        ref: "tests/test_disk_full.py::test_disk_full_mid_ingest_aborts_with_zero_events"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-07-17
status: complete
---

# Phase 3 Plan 01: Inference/Clustering Foundation Summary

**httpx + sqlite-vec + scikit-learn deps pinned, three extra=forbid config sections with a generalised SIFT_* env layer, and the carried-forward WR-07 disk-full abort closed with a forced-SQLITE_FULL test.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-17T (session start)
- **Completed:** 2026-07-17
- **Tasks:** 3
- **Files modified:** 6 (5 modified, 1 created)

## Accomplishments
- Declared and installed httpx==0.28.1, sqlite-vec==0.1.9, scikit-learn==1.9.0 (numpy transitive) and dev respx==0.23.1; uv.lock regenerated; `live` pytest marker registered and excluded by default alongside `perf`.
- Added `GenerationConfig`/`EmbeddingsConfig`/`ClusteringConfig` (all `extra="forbid"`) to `SiftConfig` with tuned defaults and NO baked embedding-model default (D-03), plus a generalised `SIFT_*` scalar env layer (`_ENV_SCALARS`) deep-merged between TOML and flags to preserve `flags > SIFT_* > toml > defaults`.
- Closed WR-07: `_ingest` now catches `sqlite3.Error` before the generic handler and raises `DiskFullError` on `SQLITE_FULL`/`SQLITE_IOERR` (incl. extended IOERR low-byte codes); the `ingest` command maps it to a sanitised error + `typer.Exit(1)`. Proven by a test that forces a real `SQLITE_FULL` via `PRAGMA max_page_count` and asserts zero committed events.

## Task Commits

Each task was committed atomically:

1. **Task 1: Declare/install 4 deps + register live marker** - `006a2b7` (chore)
2. **Task 2: [generation]/[embeddings]/[clustering] config + SIFT_* env layer** - `cea785f` (feat)
3. **Task 3: WR-07 SQLITE_FULL/IOERR fatal abort** - `5eac0fb` (fix)

_Plan metadata commit follows this summary._

## Files Created/Modified
- `pyproject.toml` - 4 new deps; `live` marker; `addopts = "-m 'not perf and not live'"`.
- `uv.lock` - regenerated with the new dependency graph (httpx/httpcore/h11/anyio/certifi/idna, sqlite-vec, scikit-learn/scipy/joblib/threadpoolctl/numpy, respx).
- `src/sift/config.py` - three nested config models, `_ENV_SCALARS` mapping, `_set_nested` deep-merge helper, nested-flag deep-merge in `load_config`; docstring updated (mapping is no longer deferred).
- `src/sift/cli.py` - `DiskFullError` class; fatal-SQLite reclassification in `_ingest`; `try/except DiskFullError` in the `ingest` command.
- `tests/test_config.py` - 6 new tests (tuned defaults, embeddings toml round-trip, env-beats-toml-but-flag-wins, batch_size coercion, unknown-clustering-key loud error).
- `tests/test_disk_full.py` - new WR-07 forced-SQLITE_FULL test.

## Decisions Made
- Non-fatal `sqlite3.Error` is recorded and continued **inline** within its own `except` clause rather than "falling through" to the generic handler — a sibling `except` cannot catch a re-raise from a preceding handler. This is a mechanical correction to the plan/RESEARCH pseudocode's "fall through" comment; behaviour matches the intent exactly (recoverable per-file errors still record + continue).
- `PRAGMA max_page_count` cap is lifted in the test's `finally` before `store.close()` so the WAL checkpoint on close is unconstrained.

## Deviations from Plan

None functionally — plan executed as written. One mechanical clarification (documented above under Decisions): the plan's pseudocode implied a bare `raise` in the `sqlite3.Error` handler would fall through to the generic `except Exception`. Python does not route a re-raise to a sibling `except`, so the recoverable path (record failed file + `continue`) was duplicated inline in the `sqlite3.Error` clause. No scope change; acceptance criteria (`except sqlite3.Error` present and before `except Exception`) still met.

## Issues Encountered
- pyright strict flagged the nested `dict[str, object]` merges (`reportUnknownArgumentType`) and the private `_ingest`/`_conn` access in tests. Resolved with `typing.cast` in `config.py` and narrow `# pyright: ignore[reportPrivateUsage]` comments in the test (mirroring the existing `tests/test_store.py` convention). A docstring line-length wrap satisfied ruff.

## User Setup Required
None - no external service configuration required. (The new httpx client and sqlite-vec surface land in later Phase-3 plans; nothing to configure yet.)

## Next Phase Readiness
- Config sections `config.generation` / `config.embeddings` / `config.clustering` are ready for the Plan 02 inference client and Plan 05 clustering stage to consume.
- sqlite-vec is importable; the lazy `vec0` table + vector (de)serialisation land in a later plan (store.py), keeping vector access confined there per the escape-hatch invariant.
- WR-07 atomicity hole is closed — the Phase-2 carried-forward blocker no longer applies.

## Self-Check: PASSED

All created/modified files exist on disk; all three task commits (`006a2b7`, `cea785f`, `5eac0fb`) are present in git log. Full gate green: `ruff check` clean, `pyright` 0 errors, `pytest` 180 passed / 1 deselected.

---
*Phase: 03-inference-client-doctor-embeddings-clustering*
*Completed: 2026-07-17*
