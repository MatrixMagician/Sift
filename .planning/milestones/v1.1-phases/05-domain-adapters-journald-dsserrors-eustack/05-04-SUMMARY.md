---
phase: 05-domain-adapters-journald-dsserrors-eustack
plan: 04
subsystem: adapters
tags: [adapters, ingest, dsserrors, microstrategy, mcm, timezone, rotation, python]

# Dependency graph
requires:
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 01
    provides: "base.ConfigurableAdapter (input_root/tz_overrides/last_stats), base.to_utc/tz_override_for, ParseStats, open_bytes/read_head"
  - phase: 01-skeleton-event-contract-genericlog-adapter
    provides: "frozen Event/event_id, byte-line discipline, ParseStats coverage metric, store severity CHECK"
provides:
  - "DsserrorsAdapter(ConfigurableAdapter) — MicroStrategy DSSErrors.log + rotated .bak siblings -> canonical Events"
  - "Anchored token extraction: [Name.cpp:NNNN]->component/source_loc, 0x->error_code, GUID->oid, SID=->session, bracketed thread/severity"
  - "MCM ***** Start/End of Info Dump ***** sentinel grouping into one event, with local 256-line/64 KB force-close caps"
  - "attrs[node] from the case-relative first path component (multi-node tagging)"
  - "Criterion-4 mixed-tz UTC timeline + rotation-ordered-by-ts proven at adapter level"
affects: [wave-3-cli-integration, adapters-registration, eustack-adapter]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Domain adapter = subclass ConfigurableAdapter; token-anchored extraction (regexes on stable structural tokens, never column order) so an [ASSUMED] layout refinement is a localised change"
    - "MCM/continuation grouping with local MAX_EVENT_LINES/MAX_EVENT_BYTES caps cloned in spirit from genericlog but NOT imported — leaf adapters stay decoupled (own byte_lines splitter)"
    - "is_fallback flag decouples 'counts against coverage' from 'ts is None': a recognised MCM block (ts=None) is covered, only genuinely-unparseable regions are unknown_fallback_bytes"

key-files:
  created:
    - src/sift/adapters/dsserrors.py
    - tests/test_dsserrors.py
    - tests/fixtures/dsserrors/node1/DSSErrors.log
    - tests/fixtures/dsserrors/node1/DSSErrors.bak00
    - tests/fixtures/dsserrors/node1/DSSErrors.bak01
    - tests/fixtures/dsserrors/node2/DSSErrors.log
  modified: []

key-decisions:
  - "SID token shape is [ASSUMED] a labelled 12+ hex run (SID=.../SID:...) — anchored on the label so it never collides with the GUID OID or a bracketed thread id; documented in the adapter docstring per the 05-02 proceed-on-assumed-shapes resolution"
  - "MCM block severity is 'unknown' (never fabricated), ts=None, but NOT counted as unknown_fallback — a recognised block is covered; only the leading unparseable region drives the <5% fallback"
  - "Local byte_lines splitter (with MAX_EVENT_BYTES force-split) rather than importing genericlog.byte_lines — the plan mandates leaf-adapter decoupling"

requirements-completed: [INGST-08]

coverage:
  - id: DS1
    description: "Token extraction: [Name.cpp:NNNN]->component+source_loc, 0x->error_code, GUID->oid, SID=->session, bracketed numeric->thread, bracketed tag->6-value severity (unknown default, never fabricated)"
    requirement: "INGST-08"
    verification:
      - kind: unit
        ref: "tests/test_dsserrors.py#test_token_extraction_error_record + test_token_severity_tags_map_to_six_value_set + test_token_no_emitted_severity_outside_check_set"
        status: pass
    human_judgment: false
  - id: DS2
    description: "MCM Start/End block = one event (component=MCM, condensed head message, verbatim raw); truncated block force-closes at the 256-line cap into a severity=unknown continuation (bounded memory)"
    requirement: "INGST-08"
    verification:
      - kind: unit
        ref: "tests/test_dsserrors.py#test_mcm_full_block_is_one_event + test_mcm_truncated_at_eof_is_one_event + test_mcm_cap_forces_unknown_continuation"
        status: pass
    human_judgment: false
  - id: DS3
    description: "attrs[node] from the case-relative first path component; node1 vs node2 distinct"
    requirement: "INGST-08"
    verification:
      - kind: unit
        ref: "tests/test_dsserrors.py#test_node_tagging_distinct_per_subdirectory"
        status: pass
    human_judgment: false
  - id: DS4
    description: "Rotated siblings ordered by per-event UTC ts, never filename: .bak00 (newer) after .bak01 (older) once ts-sorted, parse per-file with no cross-file stitching; offset-bearing -> exact"
    requirement: "INGST-08"
    verification:
      - kind: unit
        ref: "tests/test_dsserrors.py#test_rotation_ordered_by_ts_not_filename"
        status: pass
    human_judgment: false
  - id: DS5
    description: "Criterion 4: node1 naive New-York + node2 naive London normalise through base.to_utc so the merged ts-sorted timeline is not causally inverted; naive->inferred, offset->exact"
    requirement: "INGST-08"
    verification:
      - kind: unit
        ref: "tests/test_dsserrors.py#test_timezone_mixed_tz_timeline_not_causally_inverted + test_timezone_naive_inferred_offset_exact"
        status: pass
    human_judgment: false
  - id: DS6
    description: "Coverage bounded (>=95 and <100), non-vacuous; event byte spans partition the file; unparseable line -> severity=unknown ts=None counted as unknown_fallback_bytes; sniff ~0.8 on a dsserrors head, 0.0 on plain text"
    requirement: "INGST-08"
    verification:
      - kind: unit
        ref: "tests/test_dsserrors.py#test_coverage_bounded_non_vacuous + test_coverage_unparseable_line_is_unknown_ts_none + test_sniff_dsserrors_head_high + test_sniff_plain_text_zero"
        status: pass
    human_judgment: false

# Metrics
duration: 22min
completed: 2026-07-18
status: complete
---

# Phase 5 Plan 04: MicroStrategy DSSErrors Adapter Summary

**`DsserrorsAdapter` turns a multi-node MicroStrategy `DSSErrors.log` bundle — SIDs, OIDs, `0x` error codes, `[*.cpp:NNNN]` source locations, MCM `***** Start/End of Info Dump *****` blocks, rotated `.bak` siblings and mixed-timezone naive stamps — into canonical, node-tagged, UTC-ordered Events whose timeline causality is never silently inverted (INGST-08 at the adapter level).**

## Performance
- **Duration:** ~22 min
- **Started:** 2026-07-18
- **Completed:** 2026-07-18
- **Tasks:** 2
- **Files:** 6 (6 created, 0 modified)

## Accomplishments
- `DsserrorsAdapter(ConfigurableAdapter)` (`name = "dsserrors"`): anchored linear-scan token regexes (no ReDoS) extract `[Name.cpp:NNNN]`→`component`+`attrs["source_loc"]`, `0x…`→`attrs["error_code"]`, GUID→`attrs["oid"]`, `SID=…`→`session`, a bracketed numeric field→`thread`, and a bracketed tag→the six-value severity map (default `unknown`, never fabricated).
- MCM grouping: a `***** Start of Info Dump *****` … `***** End of Info Dump *****` span becomes ONE event (`component="MCM"`, condensed `Source=/Size=` head as `message`, verbatim block as `raw`). A never-terminated block force-closes at the local `MAX_EVENT_LINES` (256) / `MAX_EVENT_BYTES` (64 KB) caps into a `severity="unknown"` continuation event — bounded memory (T-05-20). A new record-start (next timestamp line or MCM Start) also force-closes an open block (Pitfall 5).
- Node tagging: `attrs["node"]` = first component of the case-relative path (needs `input_root`); `node1/…` and `node2/…` yield distinct nodes (Pitfall 3).
- Rotation by ts: `.bak00`/`.bak01` parsed independently; the merged, ts-sorted timeline is chronologically correct even though `.bak00` (07:00) is filename-earlier but time-later than `.bak01` (06:00) — the `.bakNN` suffix is never consulted (no cross-file stitching).
- Criterion 4: node1 naive New-York-local + node2 naive London-local normalise through the shared `base.to_utc`/`base.tz_override_for`; node2's 14:00 London (=14:00 UTC) correctly precedes node1's 10:00 New York (=15:00 UTC) — wall-clock-inverted, UTC-correct. Naive→`inferred`, offset-bearing→`exact`.
- Fail-soft coverage: an `is_fallback` flag decouples "counts against coverage" from "ts is None", so a recognised MCM block (ts=None) is covered while only the deliberate leading unparseable region is `unknown_fallback_bytes` — the fixture lands ~98.5% (bounded 95–100, non-vacuous). Event byte spans partition the file.
- `sniff`: `[*.cpp:NNNN]` token or an MSTR signature string in the head → `0.8` (beats genericlog's `0.1`); plain text → `0.0`.

## Task Commits
1. **Task 1: sanitised multi-node dsserrors fixtures** — `41972ea` (test)
2. **Task 2: DsserrorsAdapter sniff/parse/token-extraction/MCM/node/rotation/mixed-tz (TDD RED→GREEN)** — `d15ce59` (feat)

## Files Created/Modified
- `src/sift/adapters/dsserrors.py` — new: `DsserrorsAdapter`, `_severity_from`, `_match_ts`, `_mcm_message`, `byte_lines`, `_Record`, module-level anchored token regexes + local caps.
- `tests/test_dsserrors.py` — new: 14 grouped tests (sniff/token/mcm/node/rotation/timezone/coverage) with a local `run_parse`/`assert_span_partition` harness mirroring test_genericlog.
- `tests/fixtures/dsserrors/node1/DSSErrors.log` — naive New-York-local stamps, full + truncated MCM blocks, `0x` code, GUID OID, SID, leading unparseable region.
- `tests/fixtures/dsserrors/node1/DSSErrors.bak00`, `…/DSSErrors.bak01` — offset-bearing `-05:00` stamps, `.bak00` (07:00) chronologically newer than `.bak01` (06:00).
- `tests/fixtures/dsserrors/node2/DSSErrors.log` — naive London-local stamps for the criterion-4 mixed-tz timeline.

## Decisions Made
- **SID shape is `[ASSUMED]`** (05-02 proceed-on-assumed-shapes): a labelled 12+ hex run (`SID=`/`SID:`), anchored on the label so it never collides with the 32-hex/dashed GUID OID or the bracketed thread id. Documented in the adapter docstring; a real sanitised sample later changes only this regex.
- **MCM block is covered, not fallback.** Severity is `unknown` (never fabricated) and ts is `None`, but the block is a *recognised* event, so its bytes are not `unknown_fallback_bytes`. An `is_fallback` flag on `_Record` carries this distinction (only leading/interstitial unparseable regions and cap-overflow continuations are fallback).
- **Local `byte_lines` splitter**, not an import of `genericlog.byte_lines` — the plan mandates leaf-adapter decoupling; the local splitter keeps the `MAX_EVENT_BYTES` monster-line force-split (T-05-20).

## Deviations from Plan

### Auto-fixed Issues
**1. [Rule 3 - Blocking] pyright strict could not narrow `ts_match` under `if a is not None or b:`**
- **Found during:** Task 2 (pyright gate)
- **Issue:** The record-start branch was written `if ts_match is not None or is_mcm_start:` with the tuple unpacked in an inner `else` — pyright strict could not narrow `ts_match` away from `None`, raising `"None" is not iterable` and `reportUnknownArgumentType`.
- **Fix:** Split into sequential `if stripped == _MCM_START: … elif ts_match is not None: …` branches so pyright narrows `ts_match` cleanly at the unpack. No behavioural change.
- **Files modified:** src/sift/adapters/dsserrors.py
- **Commit:** d15ce59

No architectural changes. `adapters/__init__.py` left untouched — registration + the end-to-end `sift ingest` slice are the Wave-3 integration plan's job.

## Issues Encountered
One test-assertion bug during GREEN: the rotation test extracted a message marker via `split(" [")`, but a record's `message` correctly retains its bracketed tag prefix (consistent with genericlog), so the split returned the wrong substring. Fixed the assertion to match on the distinctive `entry A/B/C/D` markers; the adapter behaviour was correct. Resolved before the Task 2 commit.

## Known Stubs
None. The adapter is fully wired; registration and the end-to-end `sift ingest` slice are deliberately deferred to the Wave-3 integration plan per the plan's scope.

## Threat Flags
None. No new network, auth, or filesystem surface — stdlib `re`/`datetime` only, reading files already inside the case input dir. `attrs["node"]` is derived from the already-validated case-relative path and is metadata only (never used to open a file), per the threat register (T-05-21).

## User Setup Required
None — zero new dependencies (stdlib only).

## Next Phase Readiness
- INGST-08 satisfied at the adapter level: DSSErrors bytes → node-tagged, UTC-ordered, token-extracted Events with real bounded coverage; criterion-4 mixed-tz timeline and rotation-ordered-by-ts both proven.
- The `[ASSUMED]` SID/layout regexes are anchored on stable structural tokens; a later user-supplied sanitised sample is a localised regex change (small gap-closure plan), not a restructure.
- Wave-3 owns `adapters/__init__.py` registration and the CliRunner e2e ingest slice.

## Self-Check: PASSED

All six created files and the SUMMARY exist on disk; both task commits (`41972ea`, `d15ce59`) are present in `git log`. Full M5 gate: **346 passed, 2 deselected** (pre-existing live-UAT markers), ruff clean, pyright 0 errors/0 warnings.

---
*Phase: 05-domain-adapters-journald-dsserrors-eustack*
*Completed: 2026-07-18*
