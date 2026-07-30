---
phase: 15-thread-role-taxonomy-rules-file
plan: 01
subsystem: analysis
tags: [eu-stack, thread-classification, toml, pydantic, tomllib, pattern-matching]

requires:
  - phase: 05-domain-adapters
    provides: EustackAdapter, _FRAME_RE, _condense_symbol, CONDENSED_FRAMES cap
provides:
  - "iter_frames(raw) -> Iterator[tuple[int, str]] on the shipped eustack adapter"
  - "src/sift/rules/ package: __init__.py + eustack_roles.toml (one rule)"
  - "src/sift/pipeline/eustack.py: normalise, signature_of, load_rules, classify_signature"
  - "Rule/RulesMeta/ThreadRoleRules/Classification Pydantic models"
  - "End-to-end tracer test proving the full classification path"
affects: [16-thread-role-taxonomy-expansion, 17-eustack-command, 18-eustack-facts, 19-eustack-ranking]

tech-stack:
  added: []
  patterns:
    - "Rule-major, first-match-wins classification loop (outer=rules in file order, inner=frames #0..#N)"
    - "Shared-not-copied frame regex: pipeline imports iter_frames/_condense_symbol from the adapter rather than re-declaring _FRAME_RE"
    - "Package-data rules file loaded via importlib.resources, mirroring src/sift/prompts/"

key-files:
  created:
    - src/sift/rules/__init__.py
    - src/sift/rules/eustack_roles.toml
    - src/sift/pipeline/eustack.py
    - tests/test_eustack_rules.py
  modified:
    - src/sift/adapters/eustack.py
    - tests/test_eustack.py

key-decisions:
  - "normalise() splits on the FIRST '@', not '@@' — the reference capture carries single-@ GLIBC suffixes (clock_nanosleep@GLIBC_2.2.5) alongside the double-@@ form; a literal @@ split would leave those three symbols version-suffixed and build-brittle (D-05 orchestrator-verified correction)"
  - "Classification reads Event.raw via signature_of(), never Event.message — CONDENSED_FRAMES=5 truncates message, and the classifying frame in the tracer sits at index 3 (real captures 8-19 deep)"
  - "iter_frames() added to the shipped adapter as a pure additive function; parse()/_Record/ParseStats/every Event field is byte-unchanged, so no re-ingest of existing cases is required"
  - "No pyproject.toml change needed — verified empirically with a real `uv build --wheel`, confirming src/sift/rules/__init__.py and eustack_roles.toml both ship in the wheel"

patterns-established:
  - "D-01 rule-major first-match-wins loop order: row position in the TOML file IS the precedence knob, no priority field"
  - "Classification carries the matched rule's pattern TEXT plus frame_index, never the row index, so reordering the file never changes what a previously-reported result means (D-04)"

requirements-completed: [EUS-01]

coverage:
  - id: D1
    description: "A raw eu-stack thread block travels adapter frame-split -> normalisation -> signature -> packaged TOML rules -> classifier and returns a role, with no CLI/store/network/LLM on the path"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_tracer_thread_block_classifies_via_packaged_rules"
        status: pass
    human_judgment: false
  - id: D2
    description: "normalise() strips both single-@ and double-@@ GLIBC version suffixes and the lib/source tail, while keeping template argument lists"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_single_at_glibc_suffix_is_stripped"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_double_at_glibc_suffix_is_stripped"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_lib_source_tail_is_stripped"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_template_arguments_are_kept"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_normalise_is_idempotent"
        status: pass
    human_judgment: false
  - id: D3
    description: "iter_frames() is the project's only new frame-iteration surface, shared from the shipped adapter, additive with no change to parse() output"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_iter_frames_yields_index_and_full_symbol"
        status: pass
      - kind: unit
        ref: "tests/test_eustack.py#test_iter_frames_on_capped_raw_yields_fewer_frames"
        status: pass
      - kind: unit
        ref: "tests/test_eustack.py#test_iter_frames_ignores_non_frame_lines"
        status: pass
    human_judgment: false

duration: ~9min
completed: 2026-07-25
status: complete
---

# Phase 15 Plan 1: Tracer — One Thread, End to End Summary

**One eu-stack thread block classifies `idle-parked`/`job-queue` through a packaged TOML rules
file loaded via `importlib.resources`, proving D-01's rule-major first-match-wins loop, D-05's
normalisation policy, D-08's shared frame regex, and D-16's package layout on a single path before
any expansion.**

## Performance

- **Duration:** ~9 min
- **Completed:** 2026-07-25T10:49:27Z
- **Tasks:** 2 completed
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments

- `iter_frames(raw)` added to `src/sift/adapters/eustack.py` — additive, reuses the existing
  `_FRAME_RE`, does not touch `parse()`/`_Record`/`ParseStats`/any `Event` field
- New `src/sift/rules/` package (mirrors `src/sift/prompts/`): `__init__.py` docstring marker +
  `eustack_roles.toml` carrying `[meta]` and one `idle-parked`/`job-queue` rule
- New `src/sift/pipeline/eustack.py`: `Role`/`RuleRole`/`MatchKind`/`Reason` literals; `Rule`/
  `RulesMeta`/`ThreadRoleRules`/`Classification` Pydantic models (`extra="forbid"`); `normalise()`,
  `signature_of()`, `load_rules()`, `classify_signature()`
- End-to-end tracer test (`test_tracer_thread_block_classifies_via_packaged_rules`) proves the
  whole path: a raw thread block -> `idle-parked`/`job-queue`/`MSIQTask::GetNextPreferredJob`/
  frame 3
- Per-layer regression cases for `iter_frames` (index+symbol, capped raw, non-frame lines) and
  `normalise` (single-@ / double-@@ GLIBC suffixes, lib/source tail, template args kept,
  idempotence)
- Verified with a real `uv build --wheel` that `src/sift/rules/*` ships as package data with no
  `pyproject.toml` change

## Task Commits

Each task was committed atomically:

1. **Task 1: One thread, end to end — adapter frames through packaged TOML to a role** -
   `0d06a75` (feat)
2. **Task 2: Per-layer regression cases for the shared frame splitter and the normaliser** -
   `dfa057a` (test)

_Note: Task 1 is a `type="tracer"` task; per the tracer feedback gate its `<verify>`
(`ruff check` + `pyright` + `pytest tests/test_eustack_rules.py`) was re-run and confirmed green
before expanding into Task 2 (auto mode active, `workflow.auto_advance: true`)._

## Files Created/Modified

- `src/sift/adapters/eustack.py` - additive `iter_frames()` helper (D-08)
- `src/sift/rules/__init__.py` - package-data marker, docstring only
- `src/sift/rules/eustack_roles.toml` - `[meta]` + one curated rule
- `src/sift/pipeline/eustack.py` - models, normaliser, signature builder, loader, classifier
- `tests/test_eustack_rules.py` - tracer test + normalise regression cases
- `tests/test_eustack.py` - `iter_frames` regression cases

## Decisions Made

- Split `normalise()` on the first `@` rather than `@@` — the reference capture's single-@ GLIBC
  suffixes (`clock_nanosleep@GLIBC_2.2.5`, `cnd_timedwait@GLIBC_2.28`,
  `pthread_rwlock_rdlock@GLIBC_2.2.5`) would otherwise survive normalisation and go build-brittle,
  exactly the drift D-05 exists to prevent
- Kept the normalise regression tests in the Task 1 commit rather than deferring them to Task 2 as
  originally scoped — they were needed to exercise `normalise()` beyond the tracer's single
  frame, and there was no reason to hold them back once written; Task 2 then only needed to add
  the `iter_frames` cases and a "don't revert this to `@@`" comment

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `_condense_symbol` private-import flagged by pyright strict**
- **Found during:** Task 1 (writing `pipeline/eustack.py`)
- **Issue:** `from sift.adapters.eustack import _condense_symbol, iter_frames` triggered
  `reportPrivateUsage` under `pyright --strict` — the plan explicitly calls for importing the
  private `_condense_symbol` (D-08, shared not copied)
- **Fix:** Added `# pyright: ignore[reportPrivateUsage]` on the import with an inline comment,
  matching the existing house convention already used identically in `pipeline/perfmon.py`
  (`_DRIFT_ATTR`, `_RESERVED_ATTRS`) and `render/mcm_report.py`/`render/perfmon_report.py`
  (`_field`)
- **Files modified:** `src/sift/pipeline/eustack.py`
- **Verification:** `uv run pyright` exits 0
- **Committed in:** `0d06a75` (Task 1 commit)

**2. [Rule 3 - Blocking] ruff import-sort and line-length on the new test file**
- **Found during:** Task 1 (writing `tests/test_eustack_rules.py`)
- **Issue:** `ruff check` flagged `I001` (unsorted import block) and `E501` (line too long) on the
  multi-symbol import line
- **Fix:** `uv run ruff check --fix` auto-formatted the import block
- **Files modified:** `tests/test_eustack_rules.py`
- **Verification:** `uv run ruff check` exits 0
- **Committed in:** `0d06a75` (Task 1 commit)

**3. [Deferred — acceptance-criterion tooling caveat, not a code defect] Frame-regex-count grep
collides with a pre-existing sibling regex name**
- **Found during:** Task 1 acceptance-criteria self-check
- **Issue:** The plan's acceptance check `grep -c '_FRAME_RE = re.compile' src/sift/adapters/eustack.py == 1`
  returns 2, because the grep pattern is an unanchored substring match and also matches the
  pre-existing (pre-Phase-15) `_SNIFF_FRAME_RE = re.compile(...)` sniff regex two lines below
  `_FRAME_RE`. This collision predates this plan — `iter_frames()` introduced no second
  frame-splitting regex; it reuses `_FRAME_RE` exactly as D-08 requires
- **Fix:** None needed — the underlying invariant (`iter_frames` shares the sole frame-splitting
  regex, never a copy) holds by inspection; the grep command itself is the imprecise artefact.
  Documented here rather than "fixed" since altering `_SNIFF_FRAME_RE`'s name is out of this
  plan's file scope
- **Files modified:** none
- **Verification:** manual read of `src/sift/adapters/eustack.py` lines 55-66 confirms exactly one
  frame-body-capturing regex (`_FRAME_RE`) and one distinct sniff-only regex (`_SNIFF_FRAME_RE`)
- **Committed in:** n/a (no code change)

---

**Total deviations:** 3 (2 auto-fixed via Rule 3, 1 documented tooling caveat with no code change)
**Impact on plan:** Both auto-fixes are conventional/tooling fixes with no behavioural change. The
acceptance-criterion caveat does not affect correctness — reported for the verifier's awareness.

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The architecture Phases 16-19 inherit is proven: D-01 loop order, D-05 normalisation, D-08
  frame-sharing, D-16 package layout all exercised end to end on one real path
- `src/sift/pipeline/eustack.py` public surface (`Role`, `MatchKind`, `Reason`, `Rule`,
  `RulesMeta`, `ThreadRoleRules`, `Classification`, `normalise`, `signature_of`, `load_rules`,
  `classify_signature`) is ready for 15-02 (`EustackConfig`) and 15-03 (reference-capture
  derivative fixture) to build on
- Manual-only verification against the real out-of-repo capture (3,902 threads / 93 signatures,
  the 1,715-thread `MSIQTask::GetNextPreferredJob` population reading `idle-parked/job-queue`) is
  deferred to a later plan in this phase per 15-VALIDATION.md — this plan's scope was the one-rule
  tracer only
- Full suite green: `uv run pytest` (685 passed), `uv run ruff check`, `uv run pyright` all clean

---
*Phase: 15-thread-role-taxonomy-rules-file*
*Completed: 2026-07-25*

## Self-Check: PASSED

All created files found on disk; both task commits (`0d06a75`, `dfa057a`) found in `git log`.
