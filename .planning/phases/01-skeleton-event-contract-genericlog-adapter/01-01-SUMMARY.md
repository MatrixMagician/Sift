---
phase: 01-skeleton-event-contract-genericlog-adapter
plan: 01
subsystem: infra
tags: [uv, typer, pydantic, zstandard, pytest, ruff, pyright]

requires: []
provides:
  - uv-managed src-layout project with sift entry point (`uv run sift`)
  - Seven-subcommand Typer CLI surface (new, ingest, show, analyze, report, eval, doctor) — stub bodies
  - Quality gates configured and green: ruff (E,F,I,UP,B,DTZ) + pyright strict
  - Test isolation: autouse XDG redirect + SIFT_* env clearing, autouse socket guard (zero network in tests)
  - RED walking-skeleton e2e test (new -> ingest -> show events) defining the phase happy path
affects: [01-02, 01-03, 01-04, 01-05]

tech-stack:
  added: [typer 0.27.0, pydantic 2.13.4, zstandard 0.25.0, pytest 9.1.1, ruff 0.15.22, pyright 1.1.411]
  patterns:
    - "Typer Annotated option style throughout (pyright-strict friendly)"
    - "eval subcommand registered as eval_ via @app.command('eval') to avoid shadowing the builtin"
    - "Autouse conftest fixtures own suite-wide isolation; later plans add fixtures locally, never in conftest.py"

key-files:
  created:
    - pyproject.toml
    - src/sift/cli.py
    - src/sift/__init__.py
    - tests/conftest.py
    - tests/test_cli.py
    - .python-version
    - uv.lock
  modified:
    - LICENSE
    - .gitignore

key-decisions:
  - "All six PyPI packages approved at the blocking-human legitimacy checkpoint (Task 1); exact versions pinned in uv.lock"
  - "requirements-completed left empty: CLI-01 (config precedence) finishes in plan 01-04, INGST-01 finishes when plans 01-02/01-05 turn the RED e2e test green"

patterns-established:
  - "Zero-network-in-tests is mechanical: socket.socket.connect raises RuntimeError in every test"
  - "XDG_DATA_HOME/XDG_CONFIG_HOME redirected to tmp_path for every test (D-04 case paths derive from these)"

requirements-completed: []

coverage:
  - id: D1
    description: "Seven-subcommand CLI surface: `uv run sift --help` exits 0 and lists new, ingest, show, analyze, report, eval, doctor; stubs exit 1 with an arrival message"
    requirement: "CLI-01"
    verification:
      - kind: other
        ref: "uv run sift --help (exit 0, all seven commands listed); uv run sift analyze (exit 1, message contains 'Phase')"
        status: pass
    human_judgment: false
  - id: D2
    description: "Quality gates green on the scaffold: ruff check and pyright strict both exit 0"
    verification:
      - kind: other
        ref: "uv run ruff check; uv run pyright"
        status: pass
    human_judgment: false
  - id: D3
    description: "Test isolation active suite-wide: autouse XDG redirect + SIFT_* clearing and autouse socket guard"
    verification:
      - kind: manual_procedural
        ref: "Scratch test calling socket.create_connection raised RuntimeError under pytest (spot-checked then removed per plan)"
        status: pass
    human_judgment: false
  - id: D4
    description: "RED walking-skeleton e2e test committed: test_walking_skeleton_happy_path runs and fails at the first assertion (stub exit code), not at import/collection"
    requirement: "INGST-01"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_cli.py::test_walking_skeleton_happy_path (exits non-zero with AssertionError — expected RED)"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-07-16
status: complete
---

# Phase 01 Plan 01: Skeleton Bootstrap Summary

**uv src-layout scaffold with seven-subcommand Typer CLI, strict ruff/pyright gates, suite-wide XDG + socket-guard test isolation, and the deliberately RED walking-skeleton e2e test**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-16T16:01:50Z
- **Completed:** 2026-07-16T16:10:30Z
- **Tasks:** 3 (1 checkpoint resolved, 2 auto)
- **Files modified:** 9

## Accomplishments

- Installable `sift` package: `uv sync && uv run sift --help` shows the complete CLI-01 subcommand surface (new, ingest, show, analyze, report, eval, doctor)
- Both quality gates green from day one: ruff (E, F, I, UP, B, DTZ) and pyright strict
- Test isolation is mechanical for every test: XDG dirs redirected to tmp_path, SIFT_* env cleared, and socket.socket.connect patched to raise (zero-network-in-tests rule)
- RED e2e contract committed: `test_walking_skeleton_happy_path` covers `new demo` -> `ingest demo` -> `show demo events` and fails at the first assertion — plan 01-02 turns it green
- All six approved packages pinned via uv.lock at the exact checkpoint-approved versions

## Task Commits

Each task was committed atomically:

1. **Task 1: Package legitimacy checkpoint** — resolved by user ("approved"); no code commit
2. **Task 2: uv project scaffold with quality gates and 7-subcommand CLI surface** — `35e2d66` (feat)
3. **Task 3: Test isolation infrastructure and the RED walking-skeleton e2e test** — `d45e04e` (test)

## Files Created/Modified

- `pyproject.toml` — project metadata, deps, sift entry point, pytest/ruff/pyright-strict config
- `src/sift/cli.py` — Typer app with seven stub commands per SPEC §5.8; each exits 1 with an arrival message
- `src/sift/__init__.py` — `__version__ = "0.1.0"`
- `tests/conftest.py` — autouse `_isolate_dirs` and `_no_network` fixtures (owned by this plan)
- `tests/test_cli.py` — `test_walking_skeleton_happy_path` (RED)
- `.python-version` — 3.12
- `uv.lock` — exact pinned versions of all six approved packages
- `LICENSE` — canonical Apache-2.0 text
- `.gitignore` — .venv/, __pycache__/, *.pyc, .pytest_cache/, .ruff_cache/, dist/

## Decisions Made

- Left `requirements-completed` empty: CLI-01's config-precedence half lands in plan 01-04 and INGST-01 is only satisfied when the RED e2e test turns green (plans 01-02/01-05). Marking either now would falsify traceability.
- `--adapter` keeps the plan-specified `= []` default with a targeted `# noqa: B006` (Typer reads the default once at import; ruff's mutable-default rule does not apply to CLI option declarations).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ruff B006 on the plan-specified `--adapter` mutable default**
- **Found during:** Task 2 (CLI scaffold)
- **Issue:** The plan mandates `adapter: Annotated[list[str], ...] = []` and simultaneously requires `ruff check` to pass with rule set including B; B006 flags the mutable default
- **Fix:** Targeted `# noqa: B006` on the offending line with an explanatory comment (plan itself prefers per-line ignores over weakening gates)
- **Files modified:** src/sift/cli.py
- **Verification:** `uv run ruff check` exits 0
- **Committed in:** 35e2d66 (Task 2 commit)

**2. [Rule 3 - Blocking] pyright strict reportUnusedFunction on autouse fixtures**
- **Found during:** Task 3 (conftest.py)
- **Issue:** pytest discovers `_isolate_dirs`/`_no_network` dynamically; pyright strict cannot see the usage and errors
- **Fix:** Per-line `# pyright: ignore[reportUnusedFunction]` on both fixture definitions
- **Files modified:** tests/conftest.py
- **Verification:** `uv run pyright` exits 0
- **Committed in:** d45e04e (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking lint/type-gate conflicts inherent to the plan's own constraints)
**Impact on plan:** Cosmetic per-line suppressions only. No scope creep, no behaviour change.

## Known Stubs

All intentional — this plan's contract is a RED skeleton:

| Stub | File | Resolved by |
|------|------|-------------|
| `new` body prints message, exits 1 | src/sift/cli.py | plan 01-02 |
| `ingest` body prints message, exits 1 | src/sift/cli.py | plan 01-02 |
| `show` body prints message, exits 1 | src/sift/cli.py | plan 01-02 |
| `analyze` stub | src/sift/cli.py | Phase 4 (M4) |
| `report` stub | src/sift/cli.py | Phase 6 (M6) |
| `eval` stub | src/sift/cli.py | Phase 7 (M7) |
| `doctor` stub | src/sift/cli.py | Phase 3 (M3) |
| `test_walking_skeleton_happy_path` is RED | tests/test_cli.py | plan 01-02 (deliberate, per RED-commit convention) |

## Issues Encountered

None beyond the two auto-fixed gate conflicts above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 01-02 can start immediately: the RED e2e test defines its acceptance contract exactly
- conftest.py isolation is suite-wide; wave-3 plans must add fixtures in their own test files only
- No threat flags: no network code exists; both threat-register mitigations (T-01-SC checkpoint, T-01-05 socket guard) are in place

## Self-Check: PASSED

All created files exist on disk; both task commits (35e2d66, d45e04e) present in git log.

---
*Phase: 01-skeleton-event-contract-genericlog-adapter*
*Completed: 2026-07-16*
