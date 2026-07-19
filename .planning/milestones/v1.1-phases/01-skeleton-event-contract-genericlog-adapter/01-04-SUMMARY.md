---
phase: 01-skeleton-event-contract-genericlog-adapter
plan: 04
subsystem: cli
tags: [config-precedence, auto-detection, adapter-overrides, terminal-sanitisation, timezone-wiring]

requires:
  - 01-02 (frozen contracts, CaseStore, CLI walking skeleton, v0 config/detect)
  - 01-03 (tz_overrides consumed by genericlog to_utc; ladder proven)
provides:
  - Full D-08 config precedence — flags > SIFT_DATA_DIR env > $XDG_CONFIG_HOME/sift/config.toml > defaults — layered dicts, one SiftConfig.model_validate
  - SiftConfig.timezones (glob -> IANA, ZoneInfo-validated at load) and SiftConfig.adapters (glob -> adapter name) mappings
  - INGST-03 detection — override glob first-match wins unconditionally; else all adapters sniff decompressed head; unique max >= 0.5 wins; tie or below-threshold falls back to genericlog; deterministic via REGISTRY insertion order
  - parse_adapter_overrides — last-'=' split so globs containing '=' survive; unknown names raise ValueError listing registered adapters; typer-free
  - CLI hardening — --data-dir flags layer on new/ingest/show, _sanitise render-time control-char stripping (T-04-01), empty-input semantics, config.timezones -> adapter.tz_overrides D-05 wiring
affects: [01-05, phase-2, phase-5]

tech-stack:
  added: []
  patterns:
    - "Config resolution: layered plain dicts merged later-wins, validated once with plain Pydantic (no pydantic-settings, D-08)"
    - "--adapter specs persist raw in meta at new time; ingest re-parses and merges over config.adapters (flags win per glob)"
    - "Sanitise at render only — stored raw/message stay verbatim for citation fidelity"

key-files:
  created:
    - tests/test_config.py
    - tests/test_adapters_detect.py
  modified:
    - src/sift/config.py
    - src/sift/adapters/__init__.py
    - src/sift/cli.py
    - tests/test_cli.py

key-decisions:
  - "parse_adapter_overrides splits each spec on the LAST '=' (rpartition), not the first: adapter names are registry identifiers that never contain '=', so last-split is the only way the plan's own acceptance criterion (glob containing '=' survives) holds"
  - "_sanitise also strips C1 controls (0x80-0x9f, e.g. single-byte CSI) beyond the plan's C0+DEL spec — same threat class T-04-01, one extra range check"
  - "Malformed config.toml raises ValueError naming the file — never a silent fall-back to defaults (T-04-02)"
  - "TDD_MODE off per orchestrator: tests and implementation land together in one commit per task"

patterns-established:
  - "Every implemented CLI command resolves config through load_config({'data_dir': flag}) — the flags layer is uniform"
  - "Per-run adapter configuration set conditionally via isinstance narrowing; Phase 5 adapters follow the same instance-config convention"

requirements-completed: [INGST-03, CLI-01]

coverage:
  - id: D1
    description: "Precedence matrix proven pairwise: default<toml, toml<env, env<flag; timezones/adapters round-trip; Not/AZone rejected naming the zone; malformed toml loud"
    requirement: "CLI-01"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_config.py (10 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Detection: 0.9 dummy wins; tie at max -> genericlog; all <0.5 -> genericlog; override beats losing sniff; first glob in insertion order; unknown name ValueError listing registered; empty file -> genericlog; glob containing '=' survives parse"
    requirement: "INGST-03"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_adapters_detect.py (13 passed)"
        status: pass
    human_judgment: false
  - id: D3
    description: "--data-dir beats SIFT_DATA_DIR through CliRunner end-to-end (new/ingest/show); ESC byte absent from show output while message text renders; empty-dir new warns exit 0, ingest reports 0 files exit 0; unknown --adapter fails listing genericlog; Berlin tz override turns naive 10:00 into 09:00+00:00 in show output and REGISTRY genericlog carries the mapping"
    requirement: "CLI-01, INGST-03"
    verification:
      - kind: e2e
        ref: "uv run pytest tests/test_cli.py (9 passed, incl. 7 new hardening tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Full quality gates green"
    verification:
      - kind: other
        ref: "uv run pytest (94 passed); uv run ruff check; uv run pyright — all exit 0"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-16
status: complete
---

# Phase 01 Plan 04: Config Precedence, Auto-Detection & CLI Hardening Summary

**Full D-08 config chain (flags > SIFT_* env > config.toml > defaults) with ZoneInfo-validated timezone/adapter mappings, the INGST-03 sniff-threshold-tie-fallback detection algorithm with `--adapter glob=name` overrides, and a hardened CLI: render-time control-char sanitisation, sane empty-input semantics, and config.timezones wired to the adapter and observable in event UTC values**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-07-16T16:43:03Z
- **Completed:** 2026-07-16T16:53:00Z
- **Tasks:** 3 (all auto)
- **Files modified:** 6

## Accomplishments

- `load_config` now layers defaults → `$XDG_CONFIG_HOME/sift/config.toml` (stdlib tomllib) → `SIFT_DATA_DIR` → non-None flag overrides, validated once by plain Pydantic; each adjacent precedence pair proven by its own test
- `SiftConfig.timezones` values construct `zoneinfo.ZoneInfo` at load time — a bad zone name fails at config time naming the zone, never mid-ingest; `SiftConfig.adapters` carries glob → adapter-name mappings with the same semantics as `--adapter`
- `detect()` implements INGST-03 in full: override globs first-match-wins unconditionally (unknown name → ValueError listing registered adapters), then every registered adapter sniffs its own decompressed head (capped at SNIFF_BYTES via `base.read_head`), unique max ≥ 0.5 wins, tie-at-max or all-below-threshold falls back to genericlog; determinism documented as REGISTRY insertion order
- `parse_adapter_overrides` splits on the last `=` so globs containing `=` survive; stays typer-free — the CLI converts ValueError to exit 2
- CLI: `--data-dir` on new/ingest/show makes the flags layer observable end-to-end; `new` validates `--adapter` specs early and persists them raw to meta `adapter_overrides`; `ingest` merges `dict(config.adapters)` updated by those specs, rejects unknown names upfront, and sets `adapter.tz_overrides = config.timezones` (D-05 wiring proven end-to-end: naive Berlin 10:00 renders as `09:00:00+00:00`)
- `show` routes all message text through `_sanitise` (strips C0 except `\n`/`\t`, DEL, and C1 controls) at render only — a planted ESC byte never reaches the terminal while the message text still renders
- Empty-input semantics per RESEARCH Open Q3: `sift new` warns but creates on an empty dir (exit 0), missing dir exits 1, `sift ingest` with zero files prints "0 files found" and exits 0

## Task Commits

Each task was committed atomically:

1. **Task 1: Full config precedence — flags > SIFT_* env > config.toml > defaults** — `de18787` (feat)
2. **Task 2: Sniff-based auto-detection with threshold, fallback, and --adapter override** — `f842d7a` (feat)
3. **Task 3: CLI wiring and hardening — config consumption, tz wiring, sanitised output, empty-input semantics** — `07100c5` (feat)

## Files Created/Modified

- `src/sift/config.py` — full D-08 `load_config` layering; `timezones`/`adapters` fields with ZoneInfo field validator; loud malformed-toml error
- `src/sift/adapters/__init__.py` — real `detect()` (override → sniff → threshold → tie/fallback), `parse_adapter_overrides()`, `SNIFF_THRESHOLD`
- `src/sift/cli.py` — `--data-dir` on new/ingest/show, `_sanitise` (replaces `_printable`), adapter_overrides meta persistence + merge, tz wiring, empty-input handling
- `tests/test_config.py` — 10 tests: precedence matrix (all four layers, pairwise), tz validation, adapters round-trip, missing/malformed toml
- `tests/test_adapters_detect.py` — 13 tests: DummyAdapter registry fixture with restore; threshold/tie/fallback/override/insertion-order/empty-file; parse edge cases
- `tests/test_cli.py` — 7 new hardening tests appended (conftest.py untouched, owned by 01-01)

## Decisions Made

- **Last-`=` split in `parse_adapter_overrides`**: the plan's action text said first-`=`, but its own behaviour/acceptance criterion ("a glob containing an equals sign survives") is only satisfiable by splitting on the last `=`; adapter names are registry identifiers that can never contain `=`, so last-split is strictly correct (see Deviations)
- **C1 control stripping added to `_sanitise`**: 0x80–0x9f includes the single-byte CSI (0x9b) that drives some terminals — same threat class as the plan's C0+DEL spec, one extra range check
- **Malformed config.toml is a loud ValueError naming the file** — T-04-02's "never silent defaults" made explicit
- **Overrides merge order follows the plan literally**: `dict(config.adapters) | flag_overrides` — flag values win per identical glob; config globs keep insertion priority for distinct globs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] parse_adapter_overrides splits on the LAST '=' instead of the first**
- **Found during:** Task 2
- **Issue:** The plan's action text ("split on the first equals sign, Pitfall 8") contradicts its own behaviour spec and acceptance criterion ("a glob containing an equals sign survives" / "a test proves a glob containing an equals sign parses correctly") — first-split makes everything before the first `=` the glob, so a glob containing `=` can never survive
- **Fix:** `spec.rpartition("=")` — adapter names are registry identifiers and never contain `=`, so last-split preserves `=`-bearing globs and is identical to first-split for all normal specs
- **Files modified:** src/sift/adapters/__init__.py
- **Verification:** `test_parse_adapter_overrides_glob_with_equals_survives` proves `key=value*.log=genericlog` → `{"key=value*.log": "genericlog"}`
- **Commit:** f842d7a

**2. [Rule 2 - Missing critical] _sanitise also strips C1 controls (0x80–0x9f)**
- **Found during:** Task 3
- **Issue:** The plan specified stripping controls below 0x20 (except `\n`/`\t`) plus 0x7f, but C1 controls include the single-byte CSI (0x9b) which some terminals honour — an incomplete mitigation for T-04-01
- **Fix:** One extra range condition in `_sanitise`
- **Files modified:** src/sift/cli.py
- **Verification:** covered by the ESC-byte test and full suite; pure function
- **Commit:** 07100c5

---

**Total deviations:** 2 auto-fixed (1 × Rule 1 spec-contradiction, 1 × Rule 2 security). No scope creep; no architectural changes.

## Known Stubs

The 01-02 stubs owned by this plan (`detect()` v0, `SiftConfig` data_dir-only, `ingest` empty overrides) are all resolved. Remaining intentional stubs:

| Stub | File | Resolved by |
|------|------|-------------|
| analyze/report/eval/doctor exit 1 with arrival message | src/sift/cli.py | Phases 3–7 |
| Per-run adapter config set via `isinstance(…, GenericLogAdapter)` narrowing | src/sift/cli.py | Phase 5 (generalise the instance-config convention when adapter #2 lands) |

## Threat Flags

None — no new security surface beyond the plan's threat model. T-04-01 mitigated (render-time `_sanitise`, extended to C1 controls); T-04-02 mitigated (ZoneInfo validation at config load; malformed toml raises naming the file, never silent defaults).

## Issues Encountered

None. All gates were green at each task boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 01-05 (fixtures/README) can document the full CLI contract: precedence chain, `--adapter` semantics, empty-input behaviour, snapshot re-ingest semantics (noted in `sift ingest` help)
- Phase 5 adapters plug into `detect()` with one registration line; their sniff scores compete under the proven threshold/tie rules
- D-05 timezone mechanism is wired config → adapter and observable in event UTC values — Phase 5 multi-node dsserrors cases use it unchanged

## Self-Check: PASSED

All four source/test files exist on disk; all three task commits (de18787, f842d7a, 07100c5) present in git log; full gate `uv run pytest && uv run ruff check && uv run pyright` green (94 passed).

---
*Phase: 01-skeleton-event-contract-genericlog-adapter*
*Completed: 2026-07-16*
