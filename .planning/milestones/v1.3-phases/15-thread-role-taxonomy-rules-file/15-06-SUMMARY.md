---
phase: 15-thread-role-taxonomy-rules-file
plan: 06
subsystem: analysis
tags: [eu-stack, taxonomy, toml, adr, thread-classification]

requires:
  - phase: 15-thread-role-taxonomy-rules-file
    provides: "15-01's Rule/RulesMeta/ThreadRoleRules/classify_signature/load_rules; 15-03's reference_capture_derivative.txt fixture; 15-04's strict loader validators; 15-05's analyse_eustack/EustackAnalysis aggregate surface"
provides:
  - "src/sift/rules/eustack_roles.toml: the curated 24-rule day-one taxonomy across all four rule-assignable roles, in the empirically-verified file order"
  - "docs/decisions/0015-eustack-thread-role-taxonomy.md: ADR recording rule-major first-match-wins, normalisation policy, match-kind defaults, residual semantics, the shared-ancestor ordering trap, the declined rules_path containment guard and the permanent lock-ownership non-goal"
  - "5 new regression tests in tests/test_eustack_rules.py: headline-signature, D-01 bidirectional ordering, all-four-roles-reachable, coverage-not-inflated, no-ownership-language"
affects: [16-thread-role-taxonomy-expansion, 17-eustack-command, 18-eustack-facts, 19-eustack-ranking]

tech-stack:
  added: []
  patterns:
    - "Forbidden-term test sources the literal from REQUIREMENTS.md at runtime (regex over 'the word \"(\\w+)\"') rather than hardcoding it, so the test cannot itself become the only place the term is typed"
    - "Ordering regression proven bidirectionally: pin the shipped order's outcome AND the reversed order's opposite outcome in one test, so a reorder-without-consequence cannot pass by coincidence"

key-files:
  created:
    - docs/decisions/0015-eustack-thread-role-taxonomy.md
  modified:
    - src/sift/rules/eustack_roles.toml
    - tests/test_eustack_rules.py

key-decisions:
  - "Shipped exactly the 24-rule set RESEARCH.md measured and recommended, in the given file order — no additional rules chased for a rounder coverage number, per the plan's own prohibition against catch-all/generic-ancestor rules"
  - "Removed the word 'deadlock' from the TOML header comment during Task 2: the first draft used it in prose describing the permanent non-goal, which is itself the exact surface test_no_ownership_attributed_lock_language_in_shipped_surface checks — reworded to state the non-goal without naming the forbidden term, closing the gap the test caught rather than weakening the test"
  - "D-02's running-rule list stays locked at five frames; the one disclosed single-thread mis-ordering case (a feature-flag check under a shared MSIEvaluationTask::Run ancestor) is documented in the TOML header, this SUMMARY and ADR 0015 rather than silently fixed by expanding a locked decision"

patterns-established: []

requirements-completed: [EUS-01, EUS-02]
# Both already marked [x] in REQUIREMENTS.md by 15-01/15-05; this plan does not
# change their completion status, it ships the day-one rules content and the
# ADR REQUIREMENTS.md's own "Decisions folded into these requirements" table
# requires for each folded decision.

coverage:
  - id: D1
    description: "The 24-rule taxonomy ships across all four rule-assignable roles (running x5, blocked-on-lock x1, idle-parked x14, blocked-on-external x4), in the file order that places running rules before the shared-ancestor evaluation rule"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "test \"$(grep -c '^\\[\\[rule\\]\\]' src/sift/rules/eustack_roles.toml)\" -eq 24"
        status: pass
      - kind: unit
        ref: "uv run python -c \"from sift.pipeline.eustack import load_rules; ...\" (order assertion, see Task 1 verify)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The MSIQTask::GetNextPreferredJob population (headline criterion 4) reads idle-parked/job-queue at frame index 3, asserted against both the CI derivative fixture and the real 3,902-thread capture"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_reference_derivative_headline_signature"
        status: pass
      - kind: manual_procedural
        ref: "manual run against /home/oliverh/Downloads/iserver1_stacks_1-minute_diff/ — see Manual Verification section below"
        status: pass
    human_judgment: false
  - id: D3
    description: "The shared-ancestor ordering trap is pinned bidirectionally: the packaged order classifies the busy thread running, the reversed order classifies it idle-parked"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_running_rule_precedes_evaluation_ancestor_rule"
        status: pass
    human_judgment: false
  - id: D4
    description: "All four rule-assignable roles are individually reachable, including blocked-on-lock which matches zero threads in the healthy reference capture"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_all_four_rule_roles_are_reachable"
        status: pass
    human_judgment: false
  - id: D5
    description: "The unclassified residual is proven non-empty and disjoint from classified signatures — a future catch-all rule that drives it to zero fails this test"
    requirement: EUS-02
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_derivative_coverage_is_disclosed_not_inflated"
        status: pass
    human_judgment: false
  - id: D6
    description: "The permanent lock-ownership non-goal's forbidden term (read from REQUIREMENTS.md at runtime) appears nowhere in the shipped rules file or classifier module"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_no_ownership_attributed_lock_language_in_shipped_surface"
        status: pass
    human_judgment: false
  - id: D7
    description: "ADR 0015 records the loop order, normalisation policy, match-kind defaults, residual semantics, the shared-ancestor ordering rule, the declined containment guard and the permanent lock-ownership non-goal, satisfying REQUIREMENTS.md's ADR obligation"
    verification:
      - kind: unit
        ref: "test -s docs/decisions/0015-eustack-thread-role-taxonomy.md && grep -ci 'first-match-wins' ... -ge 1"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-07-25
status: complete
---

# Phase 15 Plan 6: 24-Rule Day-One Taxonomy + ADR 0015 Summary

**Expanded `eustack_roles.toml` from the tracer's one rule to the empirically-verified 24-rule day-one taxonomy (98.67% thread / 56.99% signature coverage on the reference capture), pinned the shared-ancestor rule-ordering trap bidirectionally in CI, and recorded the phase's full architectural contract as ADR 0015.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-25T12:05:00Z
- **Tasks:** 3 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- `src/sift/rules/eustack_roles.toml` — 24 curated rules across `running` (5), `blocked-on-lock` (1),
  `idle-parked` (14), `blocked-on-external` (4), in the file order RESEARCH.md verified empirically:
  running rules placed first so they win before the shared-ancestor `MSIEvaluationTask::Run` idle
  rule is ever tested. `[meta].version` bumped to 2. Header comment documents the precedence knob,
  the shared-ancestor ordering review rule, the `match`-defaults-to-`exact` contract, and the
  catch-all-rule prohibition — all without naming the forbidden lock-ownership term.
- 5 new regression tests in `tests/test_eustack_rules.py`: the headline criterion-4 signature check
  (asserting both the positive role and the negative — not blocked), the D-01 ordering trap pinned in
  both directions, all-four-roles-reachable (closing the blocked-on-lock unexercised-role gap), the
  coverage-not-inflated guard, and the runtime-sourced forbidden-term absence check.
- `docs/decisions/0015-eustack-thread-role-taxonomy.md` — records D-01 (rule-major first-match-wins)
  and the shared-ancestor ordering trap it surfaced, D-05's single-`@` normalisation refinement, D-09
  (exact-by-default match kinds, tied to ADR 0013's collision class at honestly smaller scale), D-02/
  D-12 (unclassified as the sole, illegal-as-rule residual), D-07 (no-resolvable-frame as a reason,
  not a sixth role), the declined `rules_path` containment guard (matching ADR 0009's `--kb`
  precedent), and the permanent lock-ownership non-goal. Records measured day-one coverage and the
  curator checklist for future rule additions.

## Task Commits

Each task was committed atomically:

1. **Task 1: The curated 24-rule day-one taxonomy** - `6fdf493` (feat)
2. **Task 2: Coverage, headline-signature and rule-ordering regression tests** - `1eefab8` (test)
3. **Task 3: ADR 0015** - `5da7028` (docs)

## Files Created/Modified

- `src/sift/rules/eustack_roles.toml` - expanded from 1 to 24 rules (Task 1); header reworded to
  drop the word "deadlock" (Task 2, see Deviations)
- `tests/test_eustack_rules.py` - 5 new tests (Task 2)
- `docs/decisions/0015-eustack-thread-role-taxonomy.md` - new ADR (Task 3)

## Decisions Made

- Shipped exactly the 24-rule set RESEARCH.md measured, in the given order — treated as a floor, not
  chased further for a rounder coverage number, per the plan's own prohibition against catch-all or
  generic-ancestor rules diluting the `unclassified` drift signal.
- D-02's running-rule list stays locked at five frames. The one disclosed single-thread mis-ordering
  case (`pthread_rwlock_rdlock` → `IsFeatureEnabled` → deep cube-join chain →
  `MSIEvaluationTask::Run`, falling through to `idle-parked`) is documented in the TOML header, this
  summary, and ADR 0015 rather than silently "fixed" by relitigating the locked decision.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TOML header comment used the forbidden lock-ownership term it was written to avoid**
- **Found during:** Task 2, running the new
  `test_no_ownership_attributed_lock_language_in_shipped_surface`
- **Issue:** Task 1's header comment (Task 1 acceptance criteria required stating the ownership-blind
  policy) used the word "deadlock" in prose describing the permanent non-goal — the exact term
  REQUIREMENTS.md's Out of Scope table forbids Sift from ever emitting, and the exact surface Task 2's
  new test checks.
- **Fix:** Reworded the header comment to state the non-goal ("contention can be observed but never
  attributed to a holder") without naming the forbidden term.
- **Files modified:** `src/sift/rules/eustack_roles.toml`
- **Verification:** `uv run pytest tests/test_eustack_rules.py -q` (36 passed);
  `grep -c deadlock src/sift/rules/eustack_roles.toml` → 0
- **Committed in:** `1eefab8` (Task 2 commit, alongside the new tests)

---

**Total deviations:** 1 auto-fixed (Rule 1 — self-caught by the plan's own new test before commit).
**Impact on plan:** None on scope. The fix landed in the same commit as the test that caught it,
consistent with the plan's own two-commit split (rules file in Task 1, tests in Task 2).

## Issues Encountered

None beyond the deviation above.

## Manual Verification (D-14 full-capture measurement, EUS-01 criterion 4/5 full-capture halves)

Run against the real out-of-repo reference capture
(`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`, dump A — the earlier "160739" capture, 2.4 MB,
not committed), using the shipped 24-rule `eustack_roles.toml`:

| Metric | Measured | Planning baseline | Match |
|---|---|---|---|
| `total_threads` | 3,902 | 3,902 | ✓ |
| `total_signatures` | 93 | 93 | ✓ |
| Classified threads | 3,850 (98.67%) | 3,850 (98.67%) | ✓ |
| Classified signatures | 53/93 (56.99%) | 53/93 (56.99%) | ✓ |
| `threads_by_role` | idle-parked=3651, blocked-on-external=194, blocked-on-lock=0, running=5, unclassified=52 | idle-parked=3651, blocked-on-external=194, blocked-on-lock=0, running=5, unclassified=52 | ✓ |
| `signatures_by_role` | idle-parked=33, blocked-on-external=15, blocked-on-lock=0, running=5, unclassified=40 | idle-parked=33, blocked-on-external=15, blocked-on-lock=0, running=5, unclassified=40 | ✓ |
| Headline signature | `thread_count=1715 role=idle-parked subsystem=job-queue pattern='MSIQTask::GetNextPreferredJob' frame_index=3` | 1,715, idle-parked/job-queue, frame_index=3 | ✓ |
| Parse time | 0.0775 s | — | — |
| `analyse_eustack` time | 0.0339 s | — | sub-second, scales with 93 signatures not 3,902 threads |

**No divergence from the measured-baseline task's own <measured_baseline> block or RESEARCH.md's
figures.** The headline criterion-4 check holds exactly: the 1,715-thread `MSIQTask::GetNextPreferredJob`
population — the exact composition-blind false positive v1.3 exists to eliminate — reads
`idle-parked/job-queue` at frame index 3, not blocked. Compared against the SUMMARY's own
`<measured_baseline>` snapshot of the *pre-this-plan* state (only the tracer's single rule packaged:
unclassified 56.0% of threads / 92 of 93 signatures), this plan's 24-rule set drives unclassified down
to 1.33% of threads / 43.0% of signatures — the measurable improvement the plan exists to deliver.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `eustack_roles.toml` and its ADR are the stable day-one contract Phase 16 groups over — every
  `SignatureGroup`'s `(role, subsystem)` pairing and the file's precedence-by-position discipline are
  now both shipped and documented, with no further Python change needed to expand the rules file.
- The disclosed single-thread mis-ordering case and the 40 remaining unclassified signatures (Kafka
  internals, index-manager background threads, session-backup sub-tasks, and the bare-`MSIThread::Run`
  singleton) are named in ADR 0015 and this summary as expected, by-design `unclassified` — a future
  phase or a direct rules-file edit can add rules for any of them without re-deriving the ordering
  contract.
- Full suite green: `uv run pytest` (719 passed, 8 deselected), `uv run ruff check`, `uv run pyright`
  all clean.

---
*Phase: 15-thread-role-taxonomy-rules-file*
*Completed: 2026-07-25*

## Self-Check: PASSED

- FOUND: src/sift/rules/eustack_roles.toml
- FOUND: docs/decisions/0015-eustack-thread-role-taxonomy.md
- FOUND: tests/test_eustack_rules.py
- FOUND: commit 6fdf493
- FOUND: commit 1eefab8
- FOUND: commit 5da7028
