---
phase: quick/260725-cxs
plan: record-embedding-batch-knobs-in-case-meta
subsystem: pipeline
tags: [embeddings, determinism, provenance, sqlite, adr]

requires:
  - phase: quick/2026-07-21-embedding-batch-composition-determinism (todo)
    provides: the settled measurement that embedding batch layout perturbs vectors above float noise
provides:
  - InferenceClient.embedding_context / embedding_batch_size / embedding_max_input_chars read-only properties
  - CaseStore.record_embedding_batch_knobs — overwrite-semantics meta write, no mismatch guard
  - cluster.py records the three knobs unconditionally on every analyze, including the D-03 model-is-None path
  - ADR 0014 (docs/decisions/0014-embedding-determinism-scope.md) qualifying the determinism claim
affects: [cluster.py, store.py, llm/client.py, CONTRIBUTING.md determinism invariant, any future v1.3 vector-reuse work (SEED-002/DET-01)]

tech-stack:
  added: []
  patterns: ["provenance meta keys with deliberate overwrite (not mismatch-guard) semantics for legitimately-reconfigurable values"]

key-files:
  created:
    - docs/decisions/0014-embedding-determinism-scope.md
  modified:
    - src/sift/llm/client.py
    - src/sift/store.py
    - src/sift/pipeline/cluster.py
    - tests/test_llm_client.py
    - tests/test_store_vectors.py
    - tests/test_cluster.py
    - CONTRIBUTING.md
    - docs/ARCHITECTURE.md

key-decisions:
  - "record_embedding_batch_knobs deliberately does NOT mirror record_embedding_identity's dim-mismatch guard — knobs legitimately change between runs, so overwrite must never raise"
  - "Knobs recorded unconditionally in cluster.py (outside the `if model is not None` guard), since they're known from the client even when embedding_model identity is not (D-03)"
  - "Vector reuse (the structural fix) stays out of scope, deferred to v1.3 as SEED-002/DET-01 — this plan only makes divergence diagnosable and documents the conditionality"

requirements-completed: []

coverage:
  - id: D1
    description: "InferenceClient exposes embedding_context/embedding_batch_size/embedding_max_input_chars as read-only properties returning the clamped (actually-used) values"
    verification:
      - kind: unit
        ref: "tests/test_llm_client.py#test_embedding_batch_knob_properties_return_constructed_values"
        status: pass
      - kind: unit
        ref: "tests/test_llm_client.py#test_embedding_batch_knob_properties_return_clamped_values"
        status: pass
    human_judgment: false
  - id: D2
    description: "CaseStore.record_embedding_batch_knobs writes all three knobs to meta and overwrites cleanly on a second call with different values, never raising"
    verification:
      - kind: unit
        ref: "tests/test_store_vectors.py#test_record_embedding_batch_knobs_overwrites_without_raising"
        status: pass
    human_judgment: false
  - id: D3
    description: "cluster_and_label records the three knobs even when embedding_model identity is unknown (D-03 model-is-None path)"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py#test_cluster_records_batch_knobs_even_without_model_identity"
        status: pass
    human_judgment: false
  - id: D4
    description: "ADR 0014 records the settled investigation figures verbatim and the CONTRIBUTING.md determinism bullet is scoped to a stable embedding-backend state, cross-referencing ADR 0008 and 0014"
    verification:
      - kind: other
        ref: "grep -c '3\\.21e-3'/'4\\.76e-3'/'1\\.76e-4' docs/decisions/0014-embedding-determinism-scope.md; grep -c '0008'/'0014' cross-refs (plan Task 2 verify gate)"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-07-25
status: complete
---

# Quick 260725-cxs: record embedding batch knobs in case meta Summary

**Case `meta` now records the three embedding batch-layout knobs (`embedding_context`, `embedding_batch_size`, `embedding_max_input_chars`) on every `analyze`, and ADR 0014 qualifies the determinism claim to a stable embedding-backend state.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2 completed
- **Files modified:** 9 (6 code/test + 3 docs, including the 1 new ADR)

## Accomplishments

- `InferenceClient` exposes `embedding_context`, `embedding_batch_size`, and `embedding_max_input_chars` as read-only properties mirroring the existing `embedding_model` idiom — they return the *clamped* (`max(1, ...)`) values actually used, not the raw constructor arguments.
- `CaseStore.record_embedding_batch_knobs` writes all three to `meta`, with deliberate overwrite semantics (no `get_meta` read, no comparison, no raise) — unlike `record_embedding_identity`'s dim-mismatch guard, because these knobs legitimately change between runs.
- `pipeline/cluster.py` records the knobs unconditionally, read off the `client` instance (never re-read from config), inside the same `store.transaction()` as the other provenance writes — including on the D-03 path where `embedding_model` is `None`.
- ADR `docs/decisions/0014-embedding-determinism-scope.md` records the settled 2026-07-25 investigation verbatim (probe A max abs component delta **3.21e-3**, probe B **4.76e-3**, near-duplicate-tail spacing floor **1.76e-4**, the layout-transition hysteresis finding, and the retracted intermediate 15/200 reading) and states the three-part decision: recorded (this plan), scoped (docs), deferred (vector reuse, v1.3/SEED-002/DET-01).
- `CONTRIBUTING.md`'s Determinism invariant bullet is now conditional on a stable embedding-backend state, cross-referencing ADR 0008 (report renderer) and ADR 0014 (embedding stage upstream of it).
- `docs/ARCHITECTURE.md`'s `meta` key enumeration includes the three new keys with a one-line note on their overwrite semantics.

## Task Commits

Each task was committed atomically:

1. **Task 1: record the batch-layout knobs actually used, as case meta provenance** - `71cfa76` (feat, TDD — RED confirmed failing on missing attribute/method before implementation)
2. **Task 2: qualify the determinism claim and record ADR 0014** - `4f72a62` (docs)

## Files Created/Modified

- `src/sift/llm/client.py` - three new read-only properties on `InferenceClient`
- `src/sift/store.py` - `record_embedding_batch_knobs` next to `record_embedding_identity`
- `src/sift/pipeline/cluster.py` - unconditional call inside the existing `store.transaction()` block
- `tests/test_llm_client.py` - property construction + clamping tests
- `tests/test_store_vectors.py` - overwrite-without-raise test
- `tests/test_cluster.py` - end-to-end recording test on the model-is-None path
- `CONTRIBUTING.md` - Determinism bullet qualified, cross-references ADR 0008/0014
- `docs/ARCHITECTURE.md` - meta key enumeration updated
- `docs/decisions/0014-embedding-determinism-scope.md` (new) - the ADR

## Decisions Made

- `record_embedding_batch_knobs` uses plain overwrite semantics, explicitly diverging from `record_embedding_identity`'s hard-fail-on-mismatch guard, because a knob change is a legitimate reconfiguration and must never wedge a re-analyze.
- The knobs are read from the `client` instance's new properties, never by re-reading config at the `cluster.py` call site, so what is recorded is provably what the embed pass actually used.
- Recording happens unconditionally (outside the `if model is not None` guard) since the knobs are known even when the model identity is not.

## Deviations from Plan

None — plan executed exactly as written. Both `<critical_correction>` figures (3.21e-3 for probe A, kept distinct from the unrelated 3.19e-4 cosine-perturbation figure) were transcribed verbatim into the ADR and independently verified via the Task 2 `grep` gate.

## Issues Encountered

None. TDD RED phase on Task 1 confirmed all three test files failed for the expected reason (`AttributeError: 'InferenceClient' object has no attribute 'embedding_context'`, `AttributeError: 'CaseStore' object has no attribute 'record_embedding_batch_knobs'`, and a `None != "123"` assertion) before any implementation code was written.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- A divergent re-run of `sift analyze` is now diagnosable: compare `embedding_context`/`embedding_batch_size`/`embedding_max_input_chars` in `case.db` `meta` between runs.
- Vector reuse (the structural fix that would close rather than document the exposure) remains open, tracked as SEED-002/DET-01 for v1.3 — explicitly not implemented here per scope.
- Full gate clean throughout: `uv run ruff check` (0 issues), `uv run pyright` (0 errors), `uv run pytest -q` (676 passed) after both tasks.

---
*Quick task: 260725-cxs*
*Completed: 2026-07-25*

## Self-Check: PASSED

All 9 files created/modified in this plan verified present on disk; both task commits (`71cfa76`, `4f72a62`) verified present in `git log --oneline --all`.
