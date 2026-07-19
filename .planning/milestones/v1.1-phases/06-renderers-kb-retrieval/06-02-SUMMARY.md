---
phase: 06-renderers-kb-retrieval
plan: 02
subsystem: reporting
tags: [json, renderer, determinism, canonical-serialisation, adr, reproducibility]

# Dependency graph
requires:
  - phase: 06-renderers-kb-retrieval
    plan: 01
    provides: render/ package, sift report lazy json branch, build_analysed_case fixture
  - phase: 04-inference-hypotheses
    provides: persisted hypotheses (query_hypotheses) + triage_* run-meta
  - phase: 03-clustering
    provides: clusters table (query_clusters) + persisted labels
provides:
  - "src/sift/render/json_out.render_json: canonical key-sorted JSON report (REPT-02)"
  - "json_out.normalise_for_determinism + DETERMINISM_EXCLUDED: the SINGLE D-06 exclusion point (REPT-03)"
  - "ADR 0008 scoping the REPT-03 reproducibility claim (renderer-level, not live-backend bit-exactness)"
  - "sift report --format json now wired to a real renderer (06-01 placeholder retired)"
affects: [06-05-pdf-renderer, 07-eval]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Renderer = pure function of the store (no client, no network) — REPT-03 becomes trivial"
    - "Canonical JSON: json.dumps(sort_keys=True, ensure_ascii=False, indent=2) + trailing newline"
    - "Single-source exclusion set: DETERMINISM_EXCLUDED + normalise_for_determinism, referenced by test and ADR"
    - "dataclasses.asdict for the full StoredHypothesis object (every field, no hand-mapping)"

key-files:
  created:
    - src/sift/render/json_out.py
    - docs/decisions/0008-report-determinism-scope.md
    - tests/test_render_json.py
    - tests/test_report_determinism.py
  modified:
    - src/sift/cli.py

key-decisions:
  - "render_json emits the full hypotheses object via dataclasses.asdict (no manual field list to drift)"
  - "Exclusion is structural for paths/durations (recursive strip) but a named constant for generated_at — one helper, one place"
  - "Determinism test perturbs ONLY generated_at between two runs so it exercises the exclusion, not luck"
  - "REPT-03 scoped to the renderer given identical case.db (D-07); live-backend bit-exactness explicitly NOT claimed (ADR 0008)"

requirements-completed: [REPT-02, REPT-03]

coverage:
  - id: D1
    description: "sift report --format json emits a canonical JSON document carrying the full hypotheses object, cluster stats, timeline_summary, unexplained_signals and a run-metadata block"
    requirement: "REPT-02"
    verification:
      - kind: unit
        ref: "tests/test_render_json.py#test_render_json_carries_full_document"
        status: pass
      - kind: unit
        ref: "tests/test_render_json.py#test_render_json_degraded_run_flags_row"
        status: pass
    human_judgment: false
  - id: D2
    description: "JSON is key-sorted canonical (re-dump with sort_keys=True equals the emitted string; trailing newline)"
    requirement: "REPT-02"
    verification:
      - kind: unit
        ref: "tests/test_render_json.py#test_render_json_is_key_sorted_canonical"
        status: pass
    human_judgment: false
  - id: D3
    description: "Two independent analyze runs render byte-identical JSON after normalising ONLY the D-06 excluded fields, network-free"
    requirement: "REPT-03"
    verification:
      - kind: integration
        ref: "tests/test_report_determinism.py#test_two_runs_byte_identical_after_normalisation"
        status: pass
    human_judgment: false
  - id: D4
    description: "The single exclusion helper drops generated_at, absolute paths and durations — and nothing else (case-relative content retained); does not mutate input"
    requirement: "REPT-03"
    verification:
      - kind: unit
        ref: "tests/test_report_determinism.py#test_normalise_drops_exactly_the_d06_fields"
        status: pass
      - kind: unit
        ref: "tests/test_report_determinism.py#test_normalise_does_not_mutate_input"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-18
status: complete
---

# Phase 6 Plan 02: JSON Report + Byte-Identical Determinism Summary

**`sift report --format json` emits a canonical, key-sorted JSON document (full hypotheses object + cluster stats + run metadata), and REPT-03 reproducibility is proven network-free as a pure-renderer property — two analyze runs are byte-identical after normalising ONLY the D-06 excluded fields, with the exclusion set single-sourced and the claim honestly scoped in ADR 0008.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-18
- **Tasks:** 3 (RED → GREEN → ADR + full gate)
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments
- `src/sift/render/json_out.py::render_json` — a pure `CaseStore -> str` builder assembling `hypotheses` (full `StoredHypothesis` via `dataclasses.asdict`), `clusters` (cluster_id/label/signature/severity_max/count), `timeline_summary`, `unexplained_signals` (`json.loads` of the triage meta), and a `run` block (model/prompt_hash/embedding_model/degraded/generated_at). Serialised `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` + trailing newline. Constructs no client, makes no network call (T-06-08).
- `DETERMINISM_EXCLUDED` + `normalise_for_determinism` — the SINGLE place the D-06 excluded fields live: drops `run.generated_at`, and defensively strips any absolute-path value and any duration key anywhere in the document (T-06-06), without mutating its input.
- ADR 0008 scopes REPT-03 to the renderer given an identical `case.db` (D-07): report does zero inference, so reproducibility reduces to canonical serialisation minus D-06 — NOT a claim of live-backend bit-exactness (llama-server multi-slot; doctor LLM-03 warns).
- Retired the 06-01 forward placeholder in `cli.py` (the `# type: ignore` import + `cast("str", …)`) now that `render_json` exists and is typed.
- 6 new tests, all network-free under the autouse `_no_network` guard (analysed case via `MockTransport`).

## Task Commits

1. **Task 1: RED — JSON shape + byte-identical determinism tests** — `ea868cb` (test)
2. **Task 2: GREEN — canonical render_json + shared determinism-normalisation helper** — `4976abd` (feat)
3. **Task 3: ADR 0008 — REPT-03 determinism scope + full gate** — `33c884e` (docs)

## Files Created/Modified
- `src/sift/render/json_out.py` — `render_json`, `normalise_for_determinism`, `DETERMINISM_EXCLUDED`, `_strip_volatile`/`_is_abs_path`/`_is_duration_key`.
- `docs/decisions/0008-report-determinism-scope.md` — REPT-03 scope, D-06 excluded set, D-07 backend-seed caveat, single-helper reference, ADR 0002 lineage.
- `tests/test_render_json.py` — full-document shape, key-sorted canonical property, degraded FLAGGED row (3 tests).
- `tests/test_report_determinism.py` — two-run byte-identity after normalisation, exact-D-06 exclusion, no-mutation (3 tests).
- `src/sift/cli.py` — json report branch wired to the real `render_json` (placeholder cast + type-ignore removed).

## Decisions Made
- **Full hypotheses object via `dataclasses.asdict`:** serialise every `StoredHypothesis` field with no hand-maintained field list that could drift from the dataclass.
- **Structural path/duration exclusion, named timestamp exclusion:** `generated_at` is a named constant; absolute paths and durations are stripped recursively by shape/key-name. One helper, one place — referenced by both the determinism test and ADR 0008 (Pitfall 4).
- **Determinism test perturbs only `generated_at`:** the two runs' raw dumps are asserted to differ, then equal after normalisation — so the test exercises the exclusion mechanism rather than passing trivially.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Retire the 06-01 forward placeholder in cli.py**
- **Found during:** Task 2 (GREEN, pyright gate)
- **Issue:** 06-01 wired the json branch as `from sift.render.json_out import render_json  # type: ignore` + `cast("str", render_json(store))` because the module did not exist yet. With the real, str-typed `render_json` now present, pyright flagged `reportUnnecessaryCast`.
- **Fix:** Removed the `# type: ignore` and the `cast`; the branch now imports and calls `render_json(store)` directly. `cli.py` was not in the plan's `files_modified`, but the plan's own key_link ("cli.report --format json -> render_json(store)") cannot type-check cleanly otherwise.
- **Verification:** `uv run ruff check` + `uv run pyright` (0 errors).
- **Committed in:** `4976abd`

**2. [Rule 3 - Blocking] Explicit casts for json.loads / narrowed-dict unknowns (pyright strict)**
- **Found during:** Task 2 (GREEN, pyright gate)
- **Issue:** pyright strict reports `reportUnknownVariableType`/`reportUnknownArgumentType` on `json.loads` results and `isinstance`-narrowed `dict`/`list` in both the recursive `_strip_volatile` walk and the test's parsed document.
- **Fix:** Added `cast("dict[object, object]")` / `cast("list[object]")` in `_strip_volatile` and `normalise_for_determinism`, and typed the test's `doc`/`hyps`/`clusters`/`run` via `cast`. No behaviour change.
- **Verification:** `uv run pyright` 0 errors.
- **Committed in:** `ea868cb` (test casts), `4976abd` (helper casts)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking). **Impact:** No scope creep — both were required to make the plan's own artefacts (the json renderer, the wired CLI branch) type-check under pyright strict.

## Known Stubs
None — `render_json` is fully wired to real store rows; no placeholder/empty data paths.

## Issues Encountered
None beyond the two pyright-strict adjustments above.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- `render_json` is the reuse seam for any JSON-consuming downstream tooling and does not block the PDF path (06-05), which reuses `render_markdown`.
- The single `normalise_for_determinism` helper is the canonical exclusion point should Phase 7 eval or later renderers need to diff reports.
- Quality gate green: `uv run ruff check`, `uv run pyright` (0 errors), `uv run pytest` (397 passed, 2 deselected).

## Self-Check: PASSED

All 4 created files + SUMMARY exist on disk; all 3 task commits (`ea868cb`, `4976abd`, `33c884e`) present in git log.

---
*Phase: 06-renderers-kb-retrieval*
*Completed: 2026-07-18*
