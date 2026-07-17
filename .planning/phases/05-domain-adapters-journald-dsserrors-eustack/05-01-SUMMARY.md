---
phase: 05-domain-adapters-journald-dsserrors-eustack
plan: 01
subsystem: api
tags: [adapters, ingest, coverage, timezone, typer, sqlite, python]

# Dependency graph
requires:
  - phase: 01-skeleton-event-contract-genericlog-adapter
    provides: "frozen Adapter Protocol, ParseStats, open_bytes/read_head, GenericLogAdapter, cli.py ingest loop, event_id determinism"
provides:
  - "base.ConfigurableAdapter — concrete base carrying input_root/tz_overrides/last_stats outside the frozen Adapter Protocol"
  - "base.to_utc + base.tz_override_for — single shared UTC/tz-override code path for every adapter"
  - "cli.py delivers config + reads REAL per-file coverage for any ConfigurableAdapter (fabricated-100% bug closed)"
  - "GenericLogAdapter retrofitted onto ConfigurableAdapter (behaviour unchanged)"
  - "ADR 0006 — ConfigurableAdapter generalisation + rotated-siblings-ordered-by-ts"
affects: [journald-adapter, dsserrors-adapter, eustack-adapter, wave-2-domain-adapters, wave-3-cli-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ConfigurableAdapter base: per-run config travels on the adapter instance, not the frozen Protocol; cli.py keys on isinstance(ConfigurableAdapter)"
    - "Shared base.to_utc/base.tz_override_for: adapters never re-implement UTC normalisation or tz-glob lookup"
    - "Non-vacuous coverage regression: a stub adapter with deliberate unknown-fallback bytes proves coverage is read, not fabricated"

key-files:
  created:
    - tests/test_configurable_adapter.py
    - docs/decisions/0006-configurable-adapter.md
  modified:
    - src/sift/adapters/base.py
    - src/sift/adapters/genericlog.py
    - src/sift/cli.py

key-decisions:
  - "ConfigurableAdapter is a concrete base class, NOT part of the frozen Adapter Protocol — isinstance narrows cleanly under pyright strict"
  - "track_offsets progress-bar guard stays keyed to GenericLogAdapter (progress accuracy is not a success criterion; avoids decompressed-offset risk)"
  - "Rotated .bak siblings ordered downstream by per-event UTC ts, never filename suffix; parse stays per-file (no cross-file stitching)"

patterns-established:
  - "Pattern 1: config-on-instance via ConfigurableAdapter base; cli.py delivers input_root/tz_overrides + reads last_stats for any adapter"
  - "Pattern 2: shared base.to_utc/tz_override_for as the single UTC/tz seam"

requirements-completed: [INGST-07, INGST-08, INGST-09]

coverage:
  - id: D1
    description: "base.ConfigurableAdapter concrete base carries input_root/tz_overrides/last_stats; GenericLogAdapter subclasses it with unchanged behaviour"
    requirement: "INGST-07"
    verification:
      - kind: unit
        ref: "tests/test_genericlog.py (full suite — genericlog regression guard, 51 tests with test_adapters_detect)"
        status: pass
      - kind: unit
        ref: "tests/test_configurable_adapter.py#test_genericlog_ingest_coverage_unchanged"
        status: pass
    human_judgment: false
  - id: D2
    description: "cli.py delivers input_root + tz_overrides to ANY ConfigurableAdapter and reads REAL coverage — fabricated-100% silent-failure bug closed"
    requirement: "INGST-08"
    verification:
      - kind: integration
        ref: "tests/test_configurable_adapter.py#test_stub_adapter_coverage_is_real_not_fabricated"
        status: pass
    human_judgment: false
  - id: D3
    description: "to_utc/tz_override_for promoted into base.py as the single shared UTC/tz code path; genericlog imports to_utc back"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_genericlog.py (timezone/multiline groups) + pyright/ruff clean on base.py+genericlog.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "ADR 0006 records the ConfigurableAdapter generalisation + rotated-siblings-ordered-by-ts / no-cross-file-stitching decision"
    verification:
      - kind: other
        ref: "test -s docs/decisions/0006-configurable-adapter.md && grep ConfigurableAdapter && grep rotat"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-17
status: complete
---

# Phase 5 Plan 01: ConfigurableAdapter Wave-0 Enabler Summary

**Shared `base.ConfigurableAdapter` base + promoted `to_utc`/`tz_override_for`, generalising cli.py so config reaches — and real parse coverage is read from — every adapter, closing the fabricated-100%-coverage silent-failure bug.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-17
- **Completed:** 2026-07-17
- **Tasks:** 3
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments
- `base.ConfigurableAdapter` concrete base holds `input_root`/`tz_overrides`/`last_stats` outside the frozen `Adapter` Protocol; `GenericLogAdapter` retrofitted to subclass it with byte-identical behaviour (existing genericlog suite stays green).
- `to_utc` promoted verbatim from genericlog into `base.py`; new `base.tz_override_for` shared tz-glob lookup — one UTC/tz code path for all future adapters.
- cli.py's two load-bearing `isinstance(GenericLogAdapter)` guards broadened to `isinstance(ConfigurableAdapter)`: config now reaches any adapter, and the real `ParseStats.coverage` is read back — the `stats=None → cov=1.0` fallback can no longer fabricate 100% for a domain adapter.
- Non-vacuous coverage regression test: a stub `ConfigurableAdapter` emitting 10% unknown-fallback bytes now makes `sift ingest` report `coverage 90.0%` (never `100.0%`), and asserts `input_root`/`tz_overrides` were delivered. It failed against the pre-fix cli.py (RED) and passes after (GREEN).
- ADR 0006 recorded (ConfigurableAdapter generalisation + rotated-siblings-ordered-by-ts / no cross-file stitching, with the accepted MCM-fragment-across-rotation limitation).

## Task Commits

Each task was committed atomically:

1. **Task 1: ConfigurableAdapter + promote to_utc/tz_override_for; retrofit GenericLogAdapter** - `da2616e` (refactor)
2. **Task 2: broaden cli.py config-set + coverage read-back; non-vacuous coverage regression test** - `2001629` (fix, TDD RED→GREEN)
3. **Task 3: ADR 0006** - `39b705a` (docs)

**Plan metadata:** _(final docs commit below)_

_Note: Task 2 was TDD (RED confirmed against pre-fix cli.py showing fabricated `coverage 100.0%`, then GREEN); test + fix committed together atomically since the test is the fix's regression guard._

## Files Created/Modified
- `src/sift/adapters/base.py` - Added `ConfigurableAdapter` class + promoted `to_utc` and new `tz_override_for`; imported `UTC/datetime/ZoneInfo/fnmatch`.
- `src/sift/adapters/genericlog.py` - `GenericLogAdapter(ConfigurableAdapter)`; dropped own `__init__`, removed local `to_utc` (imports from base), removed now-unused `ZoneInfo` import.
- `src/sift/cli.py` - Added `ConfigurableAdapter` import; broadened config-delivery + coverage read-back guards to `isinstance(ConfigurableAdapter)`; `track_offsets` guard left keyed to `GenericLogAdapter`.
- `tests/test_configurable_adapter.py` - New: self-contained stub `ConfigurableAdapter` + REGISTRY save/restore fixture; non-vacuous coverage regression + genericlog regression.
- `docs/decisions/0006-configurable-adapter.md` - New ADR.

## Decisions Made
- `ConfigurableAdapter` is a plain concrete class (not a Protocol, not a `@dataclass` with a manual `__init__` as the RESEARCH sketch showed) — matches the existing genericlog init shape and is the minimal correct form for pyright-strict `isinstance` narrowing.
- genericlog keeps its own inlined tz-glob generator (it needs both `override_glob` and `override_tz` for the D-05 disclosure note); `base.tz_override_for` is the shared helper the new adapters will use.
- `track_offsets` deliberately stays keyed to `GenericLogAdapter` per plan (progress-bar byte accuracy is not a success criterion).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. Stdlib-only; zero new dependencies.

## Next Phase Readiness
- Wave-0 plumbing complete: journald/dsserrors/eustack (Wave 2) can subclass `ConfigurableAdapter`, receive `input_root`/`tz_overrides`, reuse `base.to_utc`/`base.tz_override_for`, and have their real coverage reported by `sift ingest` with zero further cli.py changes.
- SPEC §5.2 "adding an adapter = new module + registration only" now holds for real on the config/coverage side.
- No blockers. (Reminder: dsserrors/eustack regexes still await user-confirmed sanitised fixtures before their parse bodies are frozen — out of scope for this plan.)

## Self-Check: PASSED

All claimed files exist on disk (base.py, genericlog.py, cli.py, tests/test_configurable_adapter.py, docs/decisions/0006-configurable-adapter.md, 05-01-SUMMARY.md) and all task commits (`da2616e`, `2001629`, `39b705a`) are present in `git log`. Full M5 gate: **313 passed, 2 deselected** (pre-existing live-UAT markers), ruff clean, pyright 0 errors/0 warnings.

---
*Phase: 05-domain-adapters-journald-dsserrors-eustack*
*Completed: 2026-07-17*
