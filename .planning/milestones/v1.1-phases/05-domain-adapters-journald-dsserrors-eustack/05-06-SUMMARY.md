---
phase: 05-domain-adapters-journald-dsserrors-eustack
plan: 06
subsystem: adapters
tags: [adapters, registry, detection, ingest, cli, e2e, journald, dsserrors, eustack, python]

# Dependency graph
requires:
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 03
    provides: "JournaldAdapter (name=journald, sniff 0.95 on a journald head)"
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 04
    provides: "DsserrorsAdapter (name=dsserrors, sniff 0.8, node tagging, rotated siblings)"
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 05
    provides: "EustackAdapter (name=eustack, sniff 0.8 on a TID+frame head)"
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 01
    provides: "cli.py real per-file coverage for any ConfigurableAdapter; input_root wiring"
  - phase: 01-skeleton-event-contract-genericlog-adapter
    provides: "generic detect() over REGISTRY.values(), SNIFF_THRESHOLD, genericlog fallback, sift new/ingest/show, _sanitise"
provides:
  - "adapters.REGISTRY now carries genericlog + journald + dsserrors + eustack"
  - "End-to-end sift ingest slice proven per domain format (new -> ingest -> show)"
  - "Detect-routing tests: each fixture routes to its own adapter, beats genericlog, no cross-collision"
affects: [phase-5-verification, milestone-M5]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Adding a domain adapter is exactly imports + REGISTRY entries — detect()/parse_adapter_overrides/SNIFF_THRESHOLD byte-unchanged (SPEC §5.2 self-containment now holds for adapters 2-4)"
    - "e2e CLI slice reads persisted parse_coverage meta AND the ingest stdout line to prove REAL sub-100% coverage on a real domain fixture (the 05-01 non-vacuous fix, not the stub)"

key-files:
  created:
    - .planning/phases/05-domain-adapters-journald-dsserrors-eustack/05-06-SUMMARY.md
  modified:
    - src/sift/adapters/__init__.py
    - tests/test_adapters_detect.py
    - tests/test_cli.py

key-decisions:
  - "Registration is the only source change — detect() dispatch is untouched, so the SPEC §5.2 'new module + registration only' invariant is now demonstrably true for all three domain adapters"
  - "e2e coverage assertion checks the persisted ParseStats.coverage (0 < cov < 1.0) on the unparseable-region file per format PLUS the ingest stdout percentage, closing the fabricated-100% regression on real fixtures"
  - "Multi-node tagging is proven via dsserrors node1/DSSErrors.log + node2/DSSErrors.log both appearing as source_files in show output"

requirements-completed: [INGST-07, INGST-08, INGST-09]

coverage:
  - id: R1
    description: "journald/dsserrors/eustack registered; detect() (byte-unchanged) routes each fixture to its own adapter, each beats genericlog's 0.1, no two domain adapters collide (unique max)"
    requirement: "INGST-07, INGST-08, INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_adapters_detect.py#test_phase5_fixture_routes_to_own_adapter + test_phase5_fixture_beats_genericlog + test_phase5_no_cross_collision"
        status: pass
    human_judgment: false
  - id: R2
    description: "sift new -> ingest -> show works end-to-end per format; canonical events land in the store and render"
    requirement: "INGST-07, INGST-08, INGST-09"
    verification:
      - kind: e2e
        ref: "tests/test_cli.py#test_phase5_e2e_ingest_show_real_coverage_idempotent"
        status: pass
    human_judgment: false
  - id: R3
    description: "ingest prints REAL per-file coverage below 100% on the deliberate-unparseable-region fixture, never a fabricated 100.0% (T-05-40)"
    requirement: "INGST-07, INGST-08, INGST-09"
    verification:
      - kind: e2e
        ref: "tests/test_cli.py#test_phase5_e2e_ingest_show_real_coverage_idempotent (coverage meta + stdout assertion)"
        status: pass
    human_judgment: false
  - id: R4
    description: "Re-running sift ingest adds zero new events for all three formats (idempotent, INGST-02 preserved)"
    requirement: "INGST-07, INGST-08, INGST-09"
    verification:
      - kind: e2e
        ref: "tests/test_cli.py#test_phase5_e2e_ingest_show_real_coverage_idempotent (second ingest '0 new')"
        status: pass
    human_judgment: false
  - id: R5
    description: "A terminal-escape byte in a domain-adapter event field is stripped by the existing whole-line _sanitise on show (T-05-41)"
    requirement: "INGST-07"
    verification:
      - kind: e2e
        ref: "tests/test_cli.py#test_phase5_show_sanitises_domain_adapter_escape_bytes"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-07-18
status: complete
---

# Phase 5 Plan 06: Adapter Registration & End-to-End Ingest Slice Summary

**Registers journald/dsserrors/eustack into `adapters.REGISTRY` with the generic `detect()` byte-unchanged (SPEC §5.2 "new module + registration only" now holds), then proves the full `sift new -> ingest -> show` vertical for each format at the CLI boundary — real sub-100% coverage on real domain fixtures (the 05-01 non-vacuous fix, not the stub), idempotent re-ingest, multi-node tagging, and `_sanitise` on domain-adapter fields (INGST-07/08/09 end-to-end).**

## Performance
- **Duration:** ~6 min
- **Started:** 2026-07-18
- **Completed:** 2026-07-18
- **Tasks:** 2
- **Files:** 3 modified (no new source files — registration only)

## Accomplishments
- **Registry wiring (the only source change):** three imports + three `REGISTRY` entries (`"journald"`/`"dsserrors"`/`"eustack"`) in `src/sift/adapters/__init__.py`. `detect()`, `parse_adapter_overrides`, and `SNIFF_THRESHOLD` are byte-unchanged — the generic dispatch over `REGISTRY.values()` from Phase 1 routes the three new adapters with zero logic edits, finally making the SPEC §5.2 self-containment claim true for adapters 2-4.
- **Detect-routing tests (`pytest -k phase5`):** for each real fixture (journald `basic.json`, dsserrors `node1/DSSErrors.log`, eustack `threaddump.txt`), `detect()` routes to the fixture's own adapter, the adapter's sniff strictly beats the genericlog fallback (0.95/0.8/0.8 vs 0.0-0.1), and exactly one domain adapter clears `SNIFF_THRESHOLD` (unique max — no cross-collision, so routing is unambiguous).
- **CliRunner e2e per format:** `sift new` → `sift ingest` → `sift show events`, driven through the CLI that wires `input_root` onto each `ConfigurableAdapter`. Asserts canonical events land and render (15 journald / 14 dsserrors / 6 eustack event ids), a known message token appears, and the unparseable file's relpath renders as a `source_file`.
- **Real coverage (T-05-40):** the persisted `parse_coverage` meta reports `0 < coverage < 1.0` on the deliberate-unparseable-region file per format (journald 0.9882, dsserrors 0.9853, eustack 0.9699), and the ingest stdout line carries the same sub-100% percentage — the pre-05-01 fabricated-100% bug cannot regress unnoticed on a real domain fixture.
- **Idempotency (INGST-02):** a second `sift ingest` on the same snapshot prints `0 new` and `show` returns the identical event-id set for all three formats.
- **Multi-node tagging:** the dsserrors case ingests `node1/DSSErrors.log` (+ rotated `.bak00/.bak01`) and `node2/DSSErrors.log`; both node relpaths appear as `source_file`s in `show` output.
- **Sanitisation (T-05-41):** a journald MESSAGE carrying a terminal-escape byte is stripped by the existing whole-line `_sanitise` on `show` — no raw ESC reaches stdout, while the visible text ("RED ALERT") survives.

## Task Commits
1. **Task 1: register adapters + detect-routing tests** — `c638a4a` (feat)
2. **Task 2: CliRunner e2e ingest slices per domain format** — `7db3e11` (test)

## Files Created/Modified
- `src/sift/adapters/__init__.py` — modified: three adapter imports + three `REGISTRY` entries. `detect()`/`parse_adapter_overrides`/`SNIFF_THRESHOLD` untouched.
- `tests/test_adapters_detect.py` — modified: `_PHASE5_CASES`/`_DOMAIN_ADAPTERS` + three parametrized `test_phase5_*` routing tests (import of `SNIFF_THRESHOLD` added).
- `tests/test_cli.py` — modified: `_PHASE5_E2E` + `_copy_fixture` + `test_phase5_e2e_ingest_show_real_coverage_idempotent` (parametrized per format) + `test_phase5_show_sanitises_domain_adapter_escape_bytes`.

## Decisions Made
- **Registration-only source change.** No edit to `detect()` — proving the generic dispatch already handles arbitrary registered adapters is the whole point of the SPEC §5.2 invariant, so touching the algorithm would defeat the test.
- **Assert coverage on the persisted meta, not just stdout.** The strongest guard against the fabricated-100% regression (T-05-40) is the real `ParseStats.coverage` in the `parse_coverage` meta; the stdout percentage is asserted too so the operator-visible number is also proven sub-100%.
- **`json.dumps` writes the escaped `\u001b` to disk.** The sanitise fixture uses `\x1b` escape notation in the Python source and `json.dumps` (ensure_ascii) persists the escaped form — no raw ESC byte enters any git-tracked file; `json.loads` decodes a real ESC into the stored MESSAGE so the render-time `_sanitise` path is genuinely exercised.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A raw ESC byte leaked into a test-file comment**
- **Found during:** Task 2 (authoring the sanitise test)
- **Issue:** While editing an explanatory comment next to the `\x1b` escape-notation MESSAGE, a raw ESC (0x1b) byte was accidentally embedded in the comment line — a git-tracked file must never carry the hazardous byte the test is about.
- **Fix:** Replaced the comment line via a small script, then scanned the file to confirm zero raw ESC bytes remain (only the intended `\x1b` escape notation in the string literal).
- **Files modified:** tests/test_cli.py
- **Commit:** 7db3e11

No architectural changes. Requirements INGST-07/08/09 were already marked complete at the enabler level (05-01); this plan lands them end-to-end.

## Issues Encountered
None beyond the ESC-byte containment fix above (resolved before the Task 2 commit).

## Known Stubs
None. All three adapters are registered and reachable through `sift ingest`; the end-to-end slice is proven at the CLI boundary for every format.

## Threat Flags
None. No new network, auth, or filesystem surface — registration plus tests only. T-05-40 (fabricated coverage) and T-05-41 (terminal-escape render) are both covered by the new e2e assertions; T-05-42 (wrong-adapter routing) by the no-cross-collision detect test.

## User Setup Required
None — zero new dependencies (stdlib only).

## Next Phase Readiness
- INGST-07/08/09 are now demonstrable end-to-end: three registered adapters, generic detect routing with no collision, and CLI round-trips with real coverage and idempotency for journald, dsserrors, and eustack.
- Phase 5 is the final plan (27 of 27); the phase is ready for verification. Per the local-branch convention, nothing merges to main until explicit user sign-off.

## Self-Check: PASSED

All three modified files exist on disk; both task commits (`c638a4a`, `7db3e11`) are present in `git log`. Full M5 gate: **374 passed, 2 deselected** (pre-existing live-UAT markers), ruff clean, pyright 0 errors/0 warnings.

---
*Phase: 05-domain-adapters-journald-dsserrors-eustack*
*Completed: 2026-07-18*
