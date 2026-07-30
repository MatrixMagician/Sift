---
phase: 16-saturation-contention-signature-collapse
plan: 02
subsystem: analysis
tags: [pydantic, eustack, config, saturation, lock-convergence]

# Dependency graph
requires:
  - phase: 16-01
    provides: "SaturationAnalysis/analyse_saturation() tracer (pools+flags), EustackThresholdsConfig.lock_convergence_count"
provides:
  - "enclosing_application_frame(): the D-04 lock-site walk, publicly unit-testable"
  - "LockSite grouping + SaturationAnalysis.lock_sites/lock_finding_note (EUS-04)"
  - "lock_convergence_count SaturationFlag, third check in the fixed flag order"
  - "Ownership-blind guard extended over emitted output (all three D-05 terms), not just source text"
affects: [16-03-eustack-dependency-split, 17-eustack-report-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Public helper for subtle correctness: enclosing_application_frame has no leading underscore (unlike _is_resolvable) so its six D-04 edge cases are directly unit-tested, not only exercised through the full aggregation"
    - "Sentinel substitution over Optional in a sort key: UNKNOWN_LOCK_SITE keeps LockSite.site typed str (never str | None) so (-thread_count, site) stays a total order — the same Pitfall 4 fix 16-01 used for PoolOccupancy.subsystem"
    - "Behaviour assertion over source grep: the ownership-blind guard's second half runs analyse_saturation() over real+synthetic scenarios and greps the OUTPUT strings, word-boundary matched, rather than only the source text"

key-files:
  created: []
  modified:
    - src/sift/pipeline/eustack.py
    - tests/test_eustack_rules.py

key-decisions:
  - "D-04 denylist implemented as str.startswith(tuple) on the LEADING namespace only — a prefix test, never substring — proven against both directions with hand-built template-argument-list frames (MBase<std::...> kept, std::<...MBase...> skipped)"
  - "lock_finding_note lives on SaturationAnalysis, not per-LockSite row, so the ownership-blind label (D-05) appears exactly once per report and a renderer cannot omit it by construction"
  - "S-7 (plan's own instruction): the shipped whole-source ownership grep is left byte-for-byte unchanged (eustack_roles.toml's 'holder' in a non-goal comment is documentation, not output); the three-term prohibition is enforced as a SECOND assertion over emitted SaturationFlag.message/LockSite.site strings instead of widening the source grep"

patterns-established:
  - "Lock pass sits after the pool pass and before the flag-emission block in analyse_saturation() — 16-03's no-resolvable-frame check and dependency split land between the unclassified-share flag and the lock-convergence flag, per the plan's authored order (unclassified, no-resolvable-frame, lock convergence)"

requirements-completed: [EUS-04]

coverage:
  - id: D1
    description: "enclosing_application_frame() walks toward increasing frame index from the classification's own frame_index, skipping unresolvable frames and the four runtime namespaces (std::/boost::/__gnu_cxx::/abi::) by leading-namespace prefix; all six D-04 edge cases pinned by name against real fixture-derived stack shapes"
    requirement: "EUS-04"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_lock_site_walk_finds_enclosing_application_frame"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_lock_site_skips_runtime_namespace"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_lock_site_template_arg_not_misjudged"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_lock_site_unknown_but_counted"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_lock_site_walk_starts_at_reported_frame_index"
        status: pass
    human_judgment: false
  - id: D2
    description: "Threads converging on a lock-acquisition path are reported as LockSite rows (site + thread_count + signature_count), graded via a lock_convergence_count SaturationFlag at three severity tiers, exercised on a hand-authored D-11 synthetic scenario since the healthy capture matches Rule 6 zero times by design; unknown-but-counted case never dropped, never attributed to the leaf"
    requirement: "EUS-04"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_synthetic_lock_convergence"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_reference_derivative_yields_no_lock_sites"
        status: pass
    human_judgment: false
  - id: D3
    description: "The three D-05-prohibited terms (the REQUIREMENTS.md-named term, 'owner', 'holder') are absent from every string analyse_saturation() actually emits, word-boundary matched, over both the committed derivative fixture and a synthetic lock scenario — a non-vacuity guard prevents this from passing trivially"
    requirement: "EUS-04"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_ownership_blind_vocabulary_absent_from_source_and_emitted_output"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-25
status: complete
---

# Phase 16 Plan 02: Lock-Site Enclosing-Frame Walk & Convergence Flag Summary

**`enclosing_application_frame()` — the D-04 walk that turns a glibc `__lll_lock_wait` leaf into a citable MicroStrategy call site — plus `LockSite` grouping, a `lock_convergence_count` flag, and the D-11 hand-authored synthetic scenario proving it, all ownership-blind by construction and by a mechanical output-string check.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-07-25T19:09Z (immediately after 16-01)
- **Completed:** 2026-07-25T19:23Z
- **Tasks:** 3
- **Files modified:** 2 (`src/sift/pipeline/eustack.py`, `tests/test_eustack_rules.py`)

## Accomplishments

- `enclosing_application_frame(frames, frame_index)` — the D-03/D-04 walk toward increasing frame index, skipping unresolvable frames and the four runtime namespaces by leading-namespace prefix (never substring); exported (no leading underscore) so all six D-04 edge cases are directly unit-tested against real fixture-derived stack shapes (`std::condition_variable::wait`, `boost::asio::detail::scheduler::do_run_one`)
- `_RUNTIME_NAMESPACES`, `UNKNOWN_LOCK_SITE`, `LOCK_FINDING_NOTE` constants — the unknown-but-counted sentinel and the ownership-blind label, both free of the three D-05-prohibited terms
- `LockSite` (site/thread_count/signature_count) and `SaturationAnalysis.lock_sites`/`lock_finding_note`, additive over 16-01's tracer with defaults so no earlier caller breaks
- `analyse_saturation()` extended with the lock pass: groups `blocked-on-lock` signatures by resolved site, explicit `(-thread_count, site)` total order, one `lock_convergence_count` `SaturationFlag` per over-threshold site graded via the imported `mcm._grade`
- `test_synthetic_lock_convergence` — the D-11 hand-authored scenario proving several distinct signatures converge on one site at three severity tiers (info/warn/critical) plus the unknown-but-counted case, clearly labelled synthetic since the healthy reference capture matches Rule 6 zero times by design
- The shipped ownership-blind test renamed and extended (S-7): the original whole-source grep stays byte-for-byte unchanged; a second half asserts the full three-term D-05 prohibition, word-boundary matched, against strings `analyse_saturation()` actually emits over both the real derivative fixture and the synthetic lock scenario, with a non-vacuity guard

## Task Commits

Each task was committed atomically:

1. **Task 1: `enclosing_application_frame()` — the D-04 walk and its six edge cases** - `94e1519` (feat)
2. **Task 2: `LockSite` grouping, the count flag, and the D-11 synthetic scenario** - `2707c63` (feat)
3. **Task 3: Extend the ownership-blind guard over emitted output (D-05, V11)** - `a16f325` (test)

## Files Created/Modified

- `src/sift/pipeline/eustack.py` — `_RUNTIME_NAMESPACES`, `UNKNOWN_LOCK_SITE`, `LOCK_FINDING_NOTE`, `enclosing_application_frame()`, `LockSite`, `SaturationAnalysis.lock_sites`/`lock_finding_note`, the lock pass and flag emission inside `analyse_saturation()`
- `tests/test_eustack_rules.py` — 7 new tests (5 for the frame walk, 1 synthetic lock-convergence scenario, 1 reference-derivative zero-lock-sites check) plus the renamed/extended ownership-blind test

## Decisions Made

- **D-04 denylist as prefix test:** `str.startswith(_RUNTIME_NAMESPACES)` gives the leading-namespace-only test for free — verified in both directions with hand-built frames containing template argument lists (`MBase::ThreadedRepeater<std::chrono::...>` kept; `std::thread::_State_impl<std::tuple<MBase::...>>` skipped).
- **`lock_finding_note` on `SaturationAnalysis`, not per-`LockSite`:** the ownership-blind label (D-05) appears exactly once per report, and Phase 17 cannot render the lock table without importing it alongside the rows.
- **S-7 (plan-specified):** the shipped whole-source ownership grep (`eustack_roles.toml` + `eustack.py`) is left untouched — it already covers this phase's additions since Phase 16 extends `eustack.py` in place, and rewriting `eustack_roles.toml`'s non-goal comment (which legitimately contains "holder" as documentation) would be the tail wagging the dog. The three-term prohibition is instead a second assertion over real emitted output.

## Deviations from Plan

None - plan executed exactly as written. All commit hashes, sort keys, sentinel values, and test names match the plan's `<action>`/`<acceptance_criteria>` blocks.

## Issues Encountered

None. One self-caught slip during drafting: the `LockSite` docstring's first phrasing used the word "deadlock" (describing the permanent non-goal) — this tripped the phase's own ownership-blind test on the first run and was reworded before any commit landed, so no forbidden term ever reached a committed state.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `SaturationAnalysis.lock_sites`/`lock_finding_note` are in place and additive — 16-03 (dependency split, EUS-05) adds `dependencies` and the `no_resolvable_frame_pct` flag with the same pattern, landing its flag check between the unclassified-share and lock-convergence checks per the plan's authored order.
- `enclosing_application_frame()` is public and independently tested — Phase 17's report renderer can call it directly if a future report needs to re-derive a site without re-running the full analysis.
- Full suite green: `ruff check` (0 issues), `pyright` (0 errors), `pytest` (734 passed, up from 727 at 16-01 close — 7 new tests, all green). No blockers for 16-03.

## Self-Check: PASSED

- FOUND: 94e1519, 2707c63, a16f325 (all three task commits present in `git log --oneline --all`)
- FOUND: `src/sift/pipeline/eustack.py` (contains `def enclosing_application_frame(`, `class LockSite(`)
- FOUND: `tests/test_eustack_rules.py` (contains `test_synthetic_lock_convergence`, `test_ownership_blind_vocabulary_absent_from_source_and_emitted_output`)

---
*Phase: 16-saturation-contention-signature-collapse*
*Completed: 2026-07-25*
