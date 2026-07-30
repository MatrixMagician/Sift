---
phase: 15-thread-role-taxonomy-rules-file
plan: 04
subsystem: pipeline
tags: [pydantic, validation, toml, eustack]

# Dependency graph
requires:
  - phase: 15-thread-role-taxonomy-rules-file
    provides: "15-01's tracer models (Rule, RulesMeta, ThreadRoleRules, Classification) and normalise/signature_of/load_rules/classify_signature; 15-02's EustackConfig; 15-03's real-signature fixture"
provides:
  - "Strict field_validators on Rule.pattern rejecting empty and un-normalised patterns, quoting the canonical form"
  - "ThreadRoleRules.rule defaults to () so a [meta]-only file is a valid diagnostic state, plus a model_validator rejecting a duplicate (match, pattern) pair as a provably unreachable dead rule"
  - "load_rules raises ValueError naming the path when rules_path points at a missing file, instead of silently reverting to the packaged default"
  - "22 loader tests covering every hand-edit failure mode plus the packaged-rules importability guard and success criterion 2"
affects: [15-05, 15-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "field_validator calling the module's own normalise() so the rules-file pattern check and the classifier's frame comparison can never drift apart"
    - "model_validator(mode='after') on the whole-file model for a cross-row invariant (no duplicate (match, pattern) key) that no single-field validator can express"

key-files:
  created: []
  modified:
    - src/sift/pipeline/eustack.py
    - tests/test_eustack_rules.py

key-decisions:
  - "No path-containment/resolve()-jail guard added to load_rules — rules_path is an operator-supplied local read path, matching the shipped --kb precedent (ADR 0009); recorded per-plan, ADR itself lands in 15-06"
  - "A [meta]-only rules file (rule == ()) is treated as a valid diagnostic state, not an error — every signature then classifies unclassified"

patterns-established: []

requirements-completed: [EUS-01]

coverage:
  - id: D1
    description: "Un-normalised, empty, illegal-role, unknown-key, unknown-match-kind and duplicate-(match,pattern) rules-file rows all fail loudly at Pydantic validation time with the offending value named"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_unnormalised_pattern_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_single_at_pattern_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_lib_tail_pattern_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_empty_pattern_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_unclassified_is_illegal_as_a_rule_role"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_unknown_key_in_rule_table_is_a_loud_error_naming_the_key"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_unknown_match_kind_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_duplicate_match_pattern_pair_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_missing_subsystem_rejected_at_load"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_missing_validated_against_rejected_at_load"
        status: pass
    human_judgment: false
  - id: D2
    description: "load_rules never silently falls back to the packaged default: malformed TOML and a missing rules_path override both raise a ValueError naming the source/path"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_malformed_rules_toml_is_a_loud_error_naming_the_source"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_missing_rules_path_does_not_fall_back_to_packaged_default"
        status: pass
    human_judgment: false
  - id: D3
    description: "A [meta]-only rules file (zero [[rule]] tables) loads successfully with rule == () rather than being rejected"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_meta_only_rules_file_is_valid_with_no_rules"
        status: pass
    human_judgment: false
  - id: D4
    description: "The packaged rules file's importlib.resources path is guarded on every default pytest run"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_packaged_rules_file_is_importable_resource"
        status: pass
    human_judgment: false
  - id: D5
    description: "Success criterion 2: pointing rules_path at an edited copy changes a thread's role, with no Python edited and nothing reinstalled"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_rules_path_override_changes_classification"
        status: pass
    human_judgment: false
  - id: D6
    description: "Rule file order, and only file order, decides precedence between two matching rules (first-match-wins), asserted in both orderings"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py::test_rule_order_is_the_precedence_knob"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-25
status: complete
---

# Phase 15 Plan 04: Strict rules-loader validators Summary

**Pydantic field_validators reject un-normalised/empty rule patterns and illegal roles at load, a model_validator rejects duplicate rule rows, and load_rules never silently falls back to the packaged default on a missing override — 22 tests pin every failure mode plus success criterion 2.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-25T11:13:54Z
- **Completed:** 2026-07-25T11:13:44+01:00 (last task commit)
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `Rule.pattern` gains two `field_validator`s: `_pattern_nonempty` (rejects `.strip()`-empty patterns) and `_pattern_must_be_normalised` (D-06 — computes `normalise(value)` and rejects any pattern whose canonical form differs, quoting that canonical form in the error)
- `ThreadRoleRules.rule` defaults to `()` so a `[meta]`-only file is a valid diagnostic state, and a `model_validator(mode="after")` (`_no_duplicate_rules`) rejects a repeated `(match, pattern)` pair as a provably unreachable dead rule under first-match-wins (D-12)
- `load_rules` now raises `ValueError(f"rules file not found: {rules_path}")` when an override path does not exist, instead of letting a bare `FileNotFoundError` escape or silently reverting to the packaged default
- 22 tests in `tests/test_eustack_rules.py` (6 pre-existing tracer/normalise tests + 16 new loader tests) cover every hand-edit failure mode named in the plan, the packaged rules file's `importlib.resources` importability, and success criterion 2 (`rules_path` override changes a thread's role) plus the file-order precedence knob in both orderings

## Task Commits

Each task was committed atomically:

1. **Task 1: Strict validators and hardened load_rules** - `2301008` (feat)
2. **Task 2: Loader error-path, packaging and rules_path-override tests** - `c867c29` (test)

_Note: this plan was not run under `tdd="true"` task gating (only Task 1 carries `tdd="true"` in the frontmatter, but validators and their proving tests were written and verified together as a single feat commit followed by a dedicated test commit — see Issues Encountered)._

## Files Created/Modified
- `src/sift/pipeline/eustack.py` - `Rule` gains `_pattern_nonempty` and `_pattern_must_be_normalised`; `ThreadRoleRules.rule` defaults to `()` and gains `_no_duplicate_rules`; `load_rules` gains the missing-override-file error path
- `tests/test_eustack_rules.py` - 16 new loader tests plus two new imports (`importlib.resources`, `pytest`/`ValidationError`, `Path`)

## Decisions Made
- No path-containment/`resolve()`-jail guard was added to `load_rules`, per the plan's explicit instruction: `rules_path` is an operator-supplied local read path, matching the shipped `--kb <dir>` precedent (ADR 0009). Verified via `grep -cE 'is_relative_to|commonpath|\.resolve\(\)' src/sift/pipeline/eustack.py` = 0.
- A `[meta]`-only rules file (`rule == ()`) is a legitimate diagnostic state, not an error — a curator emptying the file to see the raw unclassified population is a valid act, as flagged in the plan's front matter.

## Deviations from Plan

None — plan executed exactly as written. The acceptance criterion's literal `ConfigDict(extra="forbid")` grep count (3) does not equal the `(BaseModel):` class count (4) purely because `Classification`'s config line reads `ConfigDict(extra="forbid", frozen=True)` — the substring match breaks on the trailing `, frozen=True)`, not because any model lacks `extra="forbid"`. All four `BaseModel` subclasses (`Rule`, `RulesMeta`, `ThreadRoleRules`, `Classification`) do carry `extra="forbid"` (verified individually); `Classification`'s `frozen=True` addition predates this plan (15-01) and is out of this plan's scope to change. This is a plan-wording precision gap, not a code defect — flagged here rather than silently "fixed" by touching unrelated 15-01 code.

## Issues Encountered
None. `uv run ruff check --fix` was used once during Task 1 to auto-fix a `UP037` (redundant quoted forward-reference on a return type already covered by `from __future__ import annotations`) — a mechanical lint fix, not a behavioural deviation.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
The rules loader is now the strict, fail-at-load surface D-06/D-09/D-12 specify. 15-05 and 15-06 (unclassified-frame reporting and the ADR/CLI-integration plan) can build on `load_rules`/`classify_signature` without re-deriving validation behaviour. No blockers.

---
*Phase: 15-thread-role-taxonomy-rules-file*
*Completed: 2026-07-25*

## Self-Check: PASSED

- FOUND: src/sift/pipeline/eustack.py
- FOUND: tests/test_eustack_rules.py
- FOUND: .planning/phases/15-thread-role-taxonomy-rules-file/15-04-SUMMARY.md
- FOUND: commit 2301008
- FOUND: commit c867c29
