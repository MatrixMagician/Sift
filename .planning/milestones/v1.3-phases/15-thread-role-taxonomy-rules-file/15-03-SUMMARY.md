---
phase: 15-thread-role-taxonomy-rules-file
plan: 03
subsystem: test-fixtures
tags: [eu-stack, fixture, provenance, sanitisation, signature-preserving]

requires:
  - phase: 15-thread-role-taxonomy-rules-file
    plan: 01
    provides: "sift.pipeline.eustack.signature_of() — the signature identity the fixture preserves"
  - phase: 05-domain-adapters
    provides: "sift.adapters.eustack._TID_RE — the thread-header grouping rule the derivation script reuses"
provides:
  - "tests/fixtures/eustack/derive_reference_capture_derivative.py: manual, offline, role-blind derivation tool"
  - "tests/fixtures/eustack/reference_capture_derivative.txt: committed, signature-preserving fixture (93/93 signatures, 105 threads, 150,475 bytes)"
affects: [15-05-eustack-rules-expansion, 15-06-eustack-classifier-tests, 19-eustack-ranking]

tech-stack:
  added: []
  patterns:
    - "Manual/offline provenance script pattern: never collected by pytest, never run in CI, input is deliberately out-of-repo"
    - "Output-only sanitisation: synthetic sequential TIDs, synthetic PID header, no invented timestamp, no environment identifier"
    - "Role-blind mechanical extraction: grouping/capping logic contains zero role, rule, subsystem or classification vocabulary — provable via grep, not just asserted"

key-files:
  created:
    - tests/fixtures/eustack/derive_reference_capture_derivative.py
    - tests/fixtures/eustack/reference_capture_derivative.txt
  modified:
    - tests/test_cli.py

key-decisions:
  - "Cap policy: 1 thread per signature (all 93), 5 threads for the 3 highest-population signatures — the exact hybrid RESEARCH.md recommended, selected mechanically (sorted by raw thread count, no role awareness) rather than by naming specific signatures"
  - "Original-capture totals (93 signatures, 3,902 threads) are computed at runtime from the actual input file, never hardcoded — keeps the script re-runnable and truthful against a future replacement capture"
  - "The 'exact invocation' recorded in both the script's module docstring and the fixture's own preamble uses a redacted placeholder for the out-of-repo input path, never the real customer-environment filename — satisfies the plan's provenance requirement without violating its own sanitisation requirement (the two were in tension in the plan's own action text; sanitisation wins)"
  - "Deviation: tests/test_cli.py's pre-existing phase-5 e2e test copied the WHOLE tests/fixtures/eustack/ directory into the ingest input, so adding this fixture inflated its expected event count from 6 to 113 — fixed by scoping that one parametrised case to threaddump.txt only via a new optional `only` parameter on `_copy_fixture`, leaving journald/dsserrors untouched"

patterns-established:
  - "tests/fixtures/eustack/ now holds more than the single e2e-bundle fixture — any future addition to that directory must check tests/test_cli.py's _copy_fixture `only=` scoping, not assume whole-directory copytree semantics"

requirements-completed: [EUS-01]
# Note: this plan's frontmatter listed [EUS-01, EUS-02] because the fixture
# supports both requirements' future verification, but EUS-02's actual
# behavior (unclassified reporting) is delivered by plan 15-05, not here.

coverage:
  - id: D1
    description: "The derivation script contains zero role/rule/subsystem/classification vocabulary and defines no regex of its own, so the fixture it produces cannot have been shaped to agree with the detector (EUS-12's named failure mode)"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "grep -icE 'idle-parked|blocked-on|subsystem|classify' tests/fixtures/eustack/derive_reference_capture_derivative.py == 0"
        status: pass
      - kind: unit
        ref: "grep -c 're\\.compile' tests/fixtures/eustack/derive_reference_capture_derivative.py == 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "The committed fixture carries no customer environment identifier, real PID, real hostname or real capture timestamp"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "grep -cE 'env-[a-z0-9]{8,}|1363967|20260410|2026-04-10|iserver-1' tests/fixtures/eustack/reference_capture_derivative.txt == 0"
        status: pass
    human_judgment: false
  - id: D3
    description: "All 93 distinct stack signatures from the reference capture reproduce exactly in CI from the committed derivative, parsed through the shipped EustackAdapter"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "EustackAdapter().sniff() == 0.8; len({signature_of(e.raw) for e in parsed events}) == 93"
        status: pass
    human_judgment: false
  - id: D4
    description: "The highest-population signatures (the 3 selected by raw thread count) carry more than one thread in the fixture, exercising the broadcast-one-classification-to-N-threads path"
    requirement: EUS-02
    verification:
      - kind: unit
        ref: "grep -c '^TID ' tests/fixtures/eustack/reference_capture_derivative.txt == 105 (93 base + 3*4 broadcast extras)"
        status: pass
    human_judgment: false

duration: ~9min
completed: 2026-07-25
status: complete
---

# Phase 15 Plan 3: Signature-Preserving Reference Fixture Summary

**A mechanical, role-blind derivation script turns the 2.4 MB out-of-repo eu-stack reference capture into a 150,475-byte committed fixture reproducing all 93 distinct stack signatures — provenance is a committed script provably free of classification vocabulary, not an assertion.**

## Performance

- **Duration:** ~9 min
- **Completed:** 2026-07-25T11:06:01Z
- **Tasks:** 2 completed
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- `tests/fixtures/eustack/derive_reference_capture_derivative.py` — a manual, offline, argparse-driven
  tool that groups a raw eu-stack capture into thread blocks (reusing the shipped adapter's own
  `_TID_RE` grouping rule), groups blocks by `signature_of()` (imported, never re-derived), caps
  threads per signature, renumbers TIDs to a synthetic sequence starting at 100001, and redacts the
  process header. Contains zero role/rule/subsystem/classification vocabulary and defines no regex
  of its own — mechanically provable, not asserted.
- `tests/fixtures/eustack/reference_capture_derivative.txt` — the committed fixture, derived from
  dump A (the chronologically earlier "160739" capture, matching RESEARCH.md's own 93-signature /
  3,902-thread baseline measurement).
- Measured figures (recorded here per D-14's split between CI-fixture assertions and phase-verification
  measurement):
  - **Derivative:** 93/93 distinct signatures, 105 threads (93 base + 12 broadcast extras from the
    3 highest-population signatures at cap=5), 150,475 bytes — inside RESEARCH.md's measured
    140–165 KB band for this cap hybrid.
  - **Original capture (dump A, computed by the script at generation time, not hardcoded):** 3,902
    threads, 93 signatures — matches RESEARCH.md's and 15-CONTEXT.md's own figures exactly.
  - The three highest-population signatures selected mechanically (by raw thread count) were 1,715,
    1,110 and 247 threads — the same three RESEARCH.md's independent measurement names, confirming
    the mechanical selection lands on the same real signatures without any role-aware logic choosing
    them.
- `EustackAdapter().sniff()` on the fixture returns `0.8`; parsing it and grouping by
  `signature_of(event.raw)` yields exactly 93 distinct signatures — verified directly, not inferred.

## Task Commits

Each task was committed atomically:

1. **Task 1: Mechanical, role-blind derivation script** - `0ca93b8` (feat)
2. **Task 2: Generate, verify and commit the signature-preserving fixture** - `78bfcf2` (feat, includes
   a Rule-3 test fix — see Deviations)

## Files Created/Modified

- `tests/fixtures/eustack/derive_reference_capture_derivative.py` - derivation tool (created)
- `tests/fixtures/eustack/reference_capture_derivative.txt` - committed fixture (created)
- `tests/test_cli.py` - `_copy_fixture` gained an optional `only=` parameter; the eustack e2e case
  now copies only `threaddump.txt` instead of the whole `tests/fixtures/eustack/` directory (modified)

## Decisions Made

- Cap policy implemented exactly as RESEARCH.md recommended: 1 thread per signature for all 93,
  5 threads for the 3 highest-population signatures, selected by a mechanical sort on raw thread
  count (no signature names hardcoded anywhere in the script).
- Original-capture totals in the preamble and stdout are computed from the actual input file at
  run time, never hardcoded as `3902`/`93` — keeps the script honest and re-runnable if the
  reference capture is ever replaced.
- The plan's action text asked the script to "record the exact invocation used" while also
  forbidding any hardcoded capture path, PID or environment slug in both the script and the fixture
  — these two requirements are in direct tension for a real invocation (the real input path *is* the
  identifying artefact). Resolved in favour of sanitisation: both the script's module docstring and
  the fixture's own preamble record the invocation *shape* (script name, output path, "the earlier
  '160739' dump") with the real input path replaced by an explicit `<out-of-repo capture, redacted>`
  placeholder. This satisfies every acceptance-criteria grep while still documenting how to
  reproduce the fixture.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-existing phase-5 e2e test inflated by the new fixture sharing its directory**
- **Found during:** Task 2, full-suite verification (`uv run pytest`)
- **Issue:** `tests/test_cli.py::test_phase5_e2e_ingest_show_real_coverage_idempotent[eustack-...]`
  copies the *entire* `tests/fixtures/eustack/` directory into a throwaway ingest input directory
  (`shutil.copytree`) and asserts an exact expected event count (6, from `threaddump.txt` alone).
  Adding `reference_capture_derivative.txt` (105 threads) into that same directory made the test see
  113 total events instead of 6 — a blocking regression this plan's own change directly caused, not
  a pre-existing bug.
- **Fix:** Gave the test's `_copy_fixture` helper an optional `only: str | None` parameter. For the
  `eustack` parametrised case only, `_PHASE5_E2E` now names `only="threaddump.txt"`, so that case
  copies just the one curated file instead of the whole directory. `journald` and `dsserrors` are
  unaffected (still `only=None`, whole-directory copies, matching their existing multi-file bundle
  intent).
- **Files modified:** `tests/test_cli.py`
- **Verification:** `uv run pytest` — 689 passed (same count as the 15-02 baseline), 8 deselected
- **Committed in:** `78bfcf2` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3, blocking test-scope fix). No architectural changes, no
Rule 4 escalations.
**Impact on plan:** None on the fixture or script themselves — both match the plan's acceptance
criteria exactly. The test-scope fix is additive and narrows an existing test's blast radius rather
than changing its intent.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None — no external service configuration required. The derivation script itself requires the
out-of-repo reference capture at `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` to
re-run, but re-running it is a manual, occasional provenance operation, not part of any user setup
flow.

## Next Phase Readiness

- `tests/fixtures/eustack/reference_capture_derivative.txt` is ready for plans 15-05/15-06's
  classifier and rules-expansion tests to assert against directly — no new test module was added
  here per the plan's own instruction ("the fixture's parse-ability is asserted for real by the
  tests plans 15-05 and 15-06 add").
- Any future addition to `tests/fixtures/eustack/` should check `tests/test_cli.py`'s
  `_copy_fixture(..., only=...)` scoping before assuming whole-directory copytree semantics still
  hold for that format.
- Full suite green: `uv run pytest` (689 passed, 8 deselected), `uv run ruff check`, `uv run pyright`
  all clean.

---
*Phase: 15-thread-role-taxonomy-rules-file*
*Completed: 2026-07-25*

## Self-Check: PASSED

Both created files found on disk (`tests/fixtures/eustack/derive_reference_capture_derivative.py`,
`tests/fixtures/eustack/reference_capture_derivative.txt`); both task commits (`0ca93b8`, `78bfcf2`)
found in `git log`.
