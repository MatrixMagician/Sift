---
phase: 15-thread-role-taxonomy-rules-file
plan: 02
subsystem: config
tags: [config, pydantic, tomllib, eustack, precedence]

requires:
  - phase: 15-thread-role-taxonomy-rules-file
    plan: 01
    provides: "src/sift/pipeline/eustack.py load_rules(rules_path) signature the resolved config value feeds"
provides:
  - "EustackConfig model in src/sift/config.py"
  - "SiftConfig.eustack field"
  - "SIFT_EUSTACK_RULES_PATH env mapping in _ENV_SCALARS"
affects: [17-eustack-command]

tech-stack:
  added: []
  patterns:
    - "Nested-config-wrapper shape (extra=forbid single optional scalar field), mirroring McmConfig"
    - "_ENV_SCALARS generic (section, field) mapping, no per-section load_config code needed"

key-files:
  created: []
  modified:
    - src/sift/config.py
    - tests/test_config.py

key-decisions:
  - "No path-traversal/containment guard on rules_path, matching the shipped --kb <dir> precedent (ADR 0009) — a local file read of a file the operator already has read access to"
  - "rules_path typed str | None rather than Path | None — handed straight to load_rules(rules_path=...), which constructs the Path itself"

patterns-established: []

requirements-completed: [EUS-01]

coverage:
  - id: D1
    description: "load_config().eustack.rules_path is None by default and round-trips from [eustack] rules_path in config.toml"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_eustack_rules_path_defaults_to_none"
        status: pass
      - kind: unit
        ref: "tests/test_config.py::test_eustack_rules_path_round_trips_from_toml"
        status: pass
    human_judgment: false
  - id: D2
    description: "CLI flag > SIFT_EUSTACK_RULES_PATH env > config.toml > default precedence holds for rules_path"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_env_beats_toml_for_eustack_rules_path_but_flag_wins"
        status: pass
    human_judgment: false
  - id: D3
    description: "An unknown key under [eustack] is a loud load-time ValidationError naming the key"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_config.py::test_unknown_key_under_eustack_is_a_loud_error"
        status: pass
    human_judgment: false

duration: ~10min
completed: 2026-07-25
status: complete
---

# Phase 15 Plan 2: `[eustack] rules_path` Config Surface Summary

**`EustackConfig` wired into `SiftConfig` with a single `rules_path: str | None` field, giving the
shipped CLI flag > `SIFT_EUSTACK_RULES_PATH` env > `config.toml` > default precedence for free —
three additive lines in `config.py`, zero deletions, no path-containment guard (matches the shipped
`--kb <dir>` precedent).**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-25
- **Tasks:** 2 completed
- **Files modified:** 2 (both existing, additive only)

## Accomplishments

- `class EustackConfig(BaseModel)` added to `src/sift/config.py`, mirroring `McmConfig`'s
  nested-wrapper shape (`ConfigDict(extra="forbid")`, one optional scalar field)
- `SiftConfig.eustack: EustackConfig = EustackConfig()` composed alongside `mcm`
- `"SIFT_EUSTACK_RULES_PATH": ("eustack", "rules_path")` added to `_ENV_SCALARS` — `load_config`'s
  existing generic merge logic (`_set_nested`, per-section flag deep-merge) required no other change
- Four new tests in `tests/test_config.py` mirroring the existing `mcm`/`embeddings` section test
  shapes: defaults-to-None, TOML round-trip, env-beats-toml-but-flag-wins, unknown-key loud error

## Task Commits

Each task was committed atomically:

1. **Task 1: Failing tests for the `[eustack] rules_path` config surface** - `ecdbf54` (test)
2. **Task 2: EustackConfig model, SiftConfig field and env-scalar mapping** - `ba4a11a` (feat)

## Files Created/Modified

- `src/sift/config.py` - `EustackConfig` class, `SiftConfig.eustack` field, `_ENV_SCALARS` entry
  (11 insertions, 0 deletions)
- `tests/test_config.py` - four additive tests for the `[eustack]` config surface

## Decisions Made

- No containment/path-traversal guard on `rules_path`, per the plan's explicit instruction and the
  shipped `--kb <dir>` precedent (ADR 0009) — the path is a local file read of a file the operator
  already has read access to by definition
- `rules_path` typed `str | None`, not `Path | None` — it is handed straight to
  `load_rules(rules_path=...)` (Phase 15-01), which constructs the `Path` itself; `str` keeps
  env-var coercion trivial

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `ruff` E501 line-too-long on the `rules_path` field comment**
- **Found during:** Task 2, post-implementation gate run
- **Issue:** `rules_path: str | None = None  # None -> load the packaged default via importlib.resources`
  exceeded the 88-char line limit by 6 characters
- **Fix:** Moved the explanatory comment to its own line above the field, matching the multi-line
  comment style already used elsewhere in `config.py` (e.g. `GenerationConfig.context`)
- **Files modified:** `src/sift/config.py`
- **Verification:** `uv run ruff check` exits 0
- **Committed in:** `ba4a11a` (Task 2 commit)

### Notable Non-Issue (documented, no fix needed)

**Task 1's RED confirmation initially showed 3 failed / 1 passed, not the plan's expected 4
failed.** Investigated per the TDD fail-fast rule before proceeding to Task 2:
`test_unknown_key_under_eustack_is_a_loud_error` passed during RED for a coincidental-but-legitimate
reason — `[eustack]` did not yet exist as a `SiftConfig` field, so Pydantic rejected the whole
top-level `eustack` section as "extra"; the error's `input_value={'rulez_path': 'x'}` repr happened
to contain the substring `rulez_path`, satisfying `pytest.raises(..., match="rulez_path")`. This is
the same substring-matching technique the existing `test_unknown_key_under_clustering_is_a_loud_error`
precedent uses, and the test continued to pass post-implementation (Task 2) for the *intended*
reason: the nested field itself is now what gets rejected. No test or implementation change was
needed; documented here for verifier awareness rather than treated as a defect.

---

**Total deviations:** 1 auto-fixed (Rule 3, ruff line length), 1 documented non-issue (RED-phase
coincidental pass, resolved to the intended failure mode post-GREEN with no code change).
**Impact on plan:** None — both are conventional/tooling artefacts with no behavioural change.

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `SiftConfig.eustack.rules_path` is ready for a future CLI/command layer (Phase 17,
  `sift eustack`) to pass through to `load_rules(rules_path=...)` (Phase 15-01)
- Full suite green: `uv run pytest` (689 passed), `uv run ruff check`, `uv run pyright` all clean
- `git diff --numstat src/sift/config.py` confirms 0 deletions across both task commits combined

---
*Phase: 15-thread-role-taxonomy-rules-file*
*Completed: 2026-07-25*

## Self-Check: PASSED

`src/sift/config.py` and `tests/test_config.py` both found on disk with the expected content; both
task commits (`ecdbf54`, `ba4a11a`) found in `git log`.
