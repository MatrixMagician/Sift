---
phase: 19-ranking-exclusion-regression-gated-golden-eval
plan: 01
subsystem: pipeline
tags: [ranking-exclusion, eu-stack, sqlite, cli, analyze]

# Dependency graph
requires:
  - phase: 17-eu-stack-analyser-cli-integration
    provides: "sift eustack deterministic analyser (analyse_eustack_bundle)"
  - phase: 18-eu-stack-facts-into-analyze
    provides: "render_eustack_facts / eu-stack fact block spliced into hypothesise()"
provides:
  - "EXCLUDED_FROM_RANKING widened to {dssperfmon, eustack} (D-19-01)"
  - "sift analyze's zero-groups guard distinguishes zero-events from zero-groups-with-events (D-19-02)"
  - "store-level and CLI-level regression tests pinning D-19-01/02/03/04"
affects: [19-02-golden-eval-integration, 19-03-eustack-healthy-fixture, 19-04-eustack-hang-fixtures]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EXCLUDED_FROM_RANKING frozenset seam extended by adding a second member, never a new mechanism (D-07 principle: exclusion is a property of source kind)"
    - "Zero-groups CLI guard now ANDs a cheap unfiltered streaming probe (next(iter(store.iter_event_rows()), None) is None) rather than adding a new CaseStore method"

key-files:
  created: []
  modified:
    - src/sift/store.py
    - src/sift/cli.py
    - tests/test_analyze.py
    - tests/test_store.py
    - tests/test_cli.py

key-decisions:
  - "D-19-01: EXCLUDED_FROM_RANKING = frozenset({dssperfmon, eustack}) — no per-adapter attribute, no config toggle, no opt-out parameter"
  - "D-19-02: analyze falls through to hypothesise() when groups is empty but events exist (an excluded-source-only case); a genuinely empty case (zero events at all) still short-circuits with the unchanged 'Nothing to cluster' message and zero client contact"
  - "Test-1's generation-leg assertion checks calls contains 'generate' (the citation-gated hypothesise call), not 'chat' as the plan prose said — the plan's wording was based on a mistaken assumption about the shared test _handler's tagging; cluster_and_label's label call ('chat') never fires because it short-circuits on zero template groups before any embed/label round-trip"

patterns-established:
  - "PERF-03's _seed_mixed_sources store-test helper now seeds dsserrors+dssperfmon+eustack together and returns a 3-tuple, reused by both the PERF-03 and new EUS-11 test pairs"
  - "_ingest_case in test_cli.py gained a keyword-only with_eustack flag mirroring with_csv, default False so every existing caller is unaffected"

requirements-completed: [EUS-11]

coverage:
  - id: D1
    description: "EXCLUDED_FROM_RANKING holds eu-stack out of dedup/embed/cluster/salience while it stays fully retrievable by id"
    requirement: "EUS-11"
    verification:
      - kind: unit
        ref: "tests/test_store.py::test_iter_event_summaries_excludes_eustack"
        status: pass
      - kind: unit
        ref: "tests/test_store.py::test_get_events_returns_eustack"
        status: pass
      - kind: unit
        ref: "tests/test_store.py::test_iter_event_rows_includes_eustack"
        status: pass
      - kind: unit
        ref: "tests/test_store.py::test_template_groups_exclude_eustack"
        status: pass
    human_judgment: false
  - id: D2
    description: "sift analyze on an eu-stack-only case reaches hypothesise() and narrates instead of printing the false ingest message; a genuinely empty case still short-circuits before any client contact"
    requirement: "EUS-11"
    verification:
      - kind: integration
        ref: "tests/test_analyze.py::test_analyze_eustack_only_case_still_narrates"
        status: pass
      - kind: integration
        ref: "tests/test_analyze.py::test_analyze_empty_case_reports_nothing_to_cluster"
        status: pass
    human_judgment: false
  - id: D3
    description: "Cluster output is byte-identical with and without an eu-stack dump ingested (proven non-vacuously on a case whose cluster output is non-empty), and every eu-stack event is citable/renderable while none reach the ranking seam"
    requirement: "EUS-11"
    verification:
      - kind: integration
        ref: "tests/test_cli.py::test_cluster_output_identical_with_and_without_eustack"
        status: pass
      - kind: integration
        ref: "tests/test_cli.py::test_every_eustack_event_citable_and_none_ranked"
        status: pass
      - kind: integration
        ref: "tests/test_cli.py::test_show_events_includes_eustack"
        status: pass
    human_judgment: false

duration: ~35min
completed: 2026-07-27
status: complete
---

# Phase 19 Plan 01: Ranking Exclusion Seam Summary

**Eu-stack events join `EXCLUDED_FROM_RANKING` and `sift analyze` stops dead-ending on eu-stack-only cases, pinned by 10 new regression tests across store/CLI/analyze layers.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-27
- **Completed:** 2026-07-27
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- `EXCLUDED_FROM_RANKING` widened from `{"dssperfmon"}` to `{"dssperfmon", "eustack"}` (D-19-01) — one-line seam change, comment block extended to name EUS-11 alongside PERF-03; `iter_event_summaries`/`iter_event_rows` bodies untouched (asserted via `git diff` in Task 1's acceptance criteria)
- `sift analyze`'s zero-groups guard now distinguishes "no events at all" (unchanged short-circuit, zero client contact) from "zero groups but events present" (falls through to `hypothesise()` so the deterministic MCM/perfmon/eu-stack fact blocks still narrate) — D-19-02, closing the verified defect where an eu-stack-only case would print a factually wrong "run sift ingest first"
- 8 new regression tests: 1 end-to-end tracer (`test_analyze_eustack_only_case_still_narrates`, seeded via the real `EustackAdapter` against the shipped `threaddump.txt` fixture, not hand-built events), 4 store-level (exclusion + citation-path asymmetry pinned directly at the method level), 3 CLI-level (byte-identity with a non-vacuity triple-guard, whole-population citability, `show events` rendering)

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end "eu-stack-only case still narrates after exclusion"** - `440d65e` (feat)
2. **Task 2: Pin exclusion and citability at the store seam** - `deba652` (test)
3. **Task 3: Byte-identity proof and CLI citability, with the both-sides-empty vacuity guard** - `a0ed375` (test)

## Files Created/Modified
- `src/sift/store.py` - `EXCLUDED_FROM_RANKING` widened to include `"eustack"`; comment extended to name EUS-11
- `src/sift/cli.py` - `analyze`'s zero-groups guard ANDs an unfiltered zero-events probe, distinguishing empty-case from excluded-source-only-case
- `tests/test_analyze.py` - new `test_analyze_eustack_only_case_still_narrates`, seeded via `EustackAdapter.parse` on the real fixture
- `tests/test_store.py` - `_seed_mixed_sources` extended to a 3-tuple (dsserrors/dssperfmon/eustack ids); 4 new eu-stack sibling tests mirroring the shipped PERF-03 quartet
- `tests/test_cli.py` - `_ingest_case` gained `with_eustack: bool = False`; 3 new eu-stack sibling tests mirroring the shipped PERF-03 criterion-4 block, plus D-19-03's extra vacuity guard the perfmon precedent never needed

## Decisions Made
- D-19-01/D-19-02 implemented exactly as CONTEXT specified — no architectural deviation
- Task 1's `"chat"` vs `"generate"` assertion: the plan's prose said to assert `"chat"` is present in the mocked-transport `calls` list as proof the generation leg ran, but the shared `_handler` in `tests/test_analyze.py` tags the citation-gated generation call `"generate"` and reserves `"chat"` for the (here, never-fired) cluster-label call. Asserted `"generate" in calls` instead — verified against the actual handler code before writing the test — which is the assertion that genuinely proves what the plan intended (Rule 1: plan prose based on a stale/mistaken assumption about test infrastructure, not a behavioural bug)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug in plan prose] Task 1's generation-leg assertion corrected from "chat" to "generate"**
- **Found during:** Task 1 (writing `test_analyze_eustack_only_case_still_narrates`)
- **Issue:** Plan text said to assert `"chat" in calls` as proof the generation leg ran. Reading `tests/test_analyze.py`'s shared `_handler` showed the citation-gated generation call (the one `hypothesise()` makes) is tagged `"generate"`; `"chat"` is reserved for the cluster-label call, which never fires here because `cluster_and_label` short-circuits to 0 on zero template groups before any embed/label round-trip.
- **Fix:** Asserted `"generate" in calls` and `"embeddings" not in calls`, matching the plan's actual intent ("the generation leg genuinely ran" / "zero exemplars to embed").
- **Files modified:** `tests/test_analyze.py`
- **Verification:** `uv run pytest tests/test_analyze.py -k eustack_only -q` passes.
- **Committed in:** `440d65e` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule-1 plan-prose correction)
**Impact on plan:** No scope creep; the fix makes the test assert what the plan actually intended rather than a string that would never appear in `calls`.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- EUS-11 fully closed at library + CLI level: exclusion is live, the analyze dead-end is fixed, and all four `must_haves.truths` are pinned by automated tests
- Full gate green: `uv run ruff check` clean, `uv run pytest` 809/809 passed (801 baseline + 8 new tests), `uv run pyright` unchanged at the pre-existing 31-error baseline confined to `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py`
- `tests/test_cluster.py` and `tests/test_eustack_analyze.py` (the two "must stay green" regression files named in the plan's `<verification>`) pass unchanged (25/25)
- Plan 19-02 (golden-eval integration shape) can now proceed: ranking behaviour is final, so EUS-12's fixtures will be authored against the real post-exclusion behaviour rather than a moving target
- One manual-only verification remains open per `19-VALIDATION.md`: confirming `sift analyze` on the real eu-stack-only capture narrates correctly against a live local inference endpoint — no agent has access to one; deferred to end-of-phase human UAT

---
*Phase: 19-ranking-exclusion-regression-gated-golden-eval*
*Completed: 2026-07-27*

## Self-Check: PASSED

All claimed files exist on disk (`src/sift/store.py`, `src/sift/cli.py`,
`tests/test_analyze.py`, `tests/test_store.py`, `tests/test_cli.py`) and all
three task commit hashes (`440d65e`, `deba652`, `a0ed375`) are present in
`git log --oneline --all`.
