---
phase: 05-domain-adapters-journald-dsserrors-eustack
plan: 05
subsystem: adapters
tags: [adapters, ingest, eustack, thread-dump, microstrategy, elfutils, python]

# Dependency graph
requires:
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 01
    provides: "base.ConfigurableAdapter (input_root/tz_overrides/last_stats), base.to_utc/tz_override_for, ParseStats, open_bytes/read_head"
  - phase: 05-domain-adapters-journald-dsserrors-eustack
    plan: 02
    provides: "Frozen eustack format identity — native elfutils eu-stack (TID headers, #N 0xADDR frames, NO lock info) via proceed-on-assumed-shapes"
  - phase: 01-skeleton-event-contract-genericlog-adapter
    provides: "frozen Event/event_id, byte-line discipline, ParseStats coverage metric, store severity CHECK"
provides:
  - "EustackAdapter(ConfigurableAdapter) — MicroStrategy EU-stack / native thread-dump files -> one canonical Event per thread"
  - "Per-thread grouping: a TID <n>: header starts an event, #N 0xADDR symbol frames accrue until the next header or a safety cap"
  - "Condensed top-frame symbols -> message, verbatim thread block -> raw, TID -> thread; no lock attrs (native format), absence asserted"
  - "Single dump-time header ts stamps every thread (exact/inferred via base.to_utc), absent -> ts=None/missing; local 256-line/64 KB caps"
affects: [wave-3-cli-integration, adapters-registration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Domain adapter = subclass ConfigurableAdapter; record-start trigger is a structural header (TID <n>:) instead of a timestamp — grouping rule is format-independent so a JVM-shape refinement is localised"
    - "One dump-time ts scanned from the preamble stamps ALL thread events; per-thread times are never fabricated (ts=None/missing when absent)"
    - "is_fallback flag decouples coverage from ts: covered thread events legitimately carry severity=unknown, only the preamble + cap overflow are unknown_fallback_bytes"

key-files:
  created:
    - src/sift/adapters/eustack.py
    - tests/test_eustack.py
    - tests/fixtures/eustack/threaddump.txt
  modified: []

key-decisions:
  - "Format frozen as native elfutils eu-stack (05-02 proceed-on-assumed-shapes): TID <n>: headers, #N 0xADDR symbol frames, NO lock/blocked-on info. INGST-09 'lock info in attrs' is met by asserting ABSENCE (waiting_on/locked/state never in attrs) — nothing fabricated. A later JVM-shape sample is a localised regex + attr addition, not a restructure."
  - "message = first CONDENSED_FRAMES (5) frame symbols with any ' - lib source:line' suffix stripped; raw = verbatim block (suffix intact). thread = TID number; component/session = None (native eu-stack carries neither)."
  - "Preamble/header region (before the first TID) is one severity=unknown, ts=None fallback event and is scanned in passing for the single dump-time timestamp; the cap-overflow continuation is likewise fallback — together they drive bounded (<100%) coverage."

requirements-completed: [INGST-09]

coverage:
  - id: EU1
    description: "One event per TID header: frames accrue until the next header; on the fixture the four TID headers yield exactly four thread events (preamble + cap-overflow are non-thread events)"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_one_event_per_thread_clean_dump + test_thread_count_matches_thread_headers_on_fixture"
        status: pass
    human_judgment: false
  - id: EU2
    description: "message = condensed top frame symbols (lib/source suffix stripped); raw = verbatim thread block; thread = TID"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_condensed_frames_in_message_full_block_in_raw"
        status: pass
    human_judgment: false
  - id: EU3
    description: "No lock/blocked-on attrs on native eu-stack — absence asserted (waiting_on/locked/state absent, component/session None), nothing fabricated (INGST-09 contingent-lock clause)"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_no_lock_attrs_native_format"
        status: pass
    human_judgment: false
  - id: EU4
    description: "Single dump-time header ts stamps every thread (offset-bearing -> exact, naive -> inferred via base.to_utc); absent -> ts=None/missing, never invented per-thread"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_single_dump_ts_stamps_all_threads + test_absent_dump_ts_is_missing + test_naive_dump_ts_inferred_via_to_utc"
        status: pass
    human_judgment: false
  - id: EU5
    description: "Oversized thread block force-closes at the 256-line cap into a severity=unknown continuation event (bounded memory, Pitfall 5 / T-05-30)"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_oversized_thread_caps_to_unknown_continuation + test_never_terminated_thread_is_bounded"
        status: pass
    human_judgment: false
  - id: EU6
    description: "Coverage bounded (>=95 and <100), non-vacuous (~96.99% on the fixture); event byte spans partition the file; sniff 0.8 on an eu-stack head (TID + frame), 0.0 on plain text or a TID mention without frames"
    requirement: "INGST-09"
    verification:
      - kind: unit
        ref: "tests/test_eustack.py#test_coverage_bounded_non_vacuous + test_preamble_is_unknown_ts_none + test_sniff_eustack_head_high + test_sniff_plain_text_zero + test_sniff_partial_no_frames_zero"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-18
status: complete
---

# Phase 5 Plan 05: MicroStrategy EU-stack Adapter Summary

**`EustackAdapter` turns a MicroStrategy / native elfutils `eu-stack` thread dump — `TID <n>:` headers with `#N 0xADDR symbol` frames — into one canonical Event per thread: condensed top-frame symbols as the message, the verbatim block in `raw`, the TID in `thread`, a single dump-time timestamp stamping every thread, and a 256-line/64 KB cap that force-closes a monster thread into a `severity="unknown"` continuation — with no lock info fabricated (INGST-09 at the adapter level).**

## Performance
- **Duration:** ~18 min
- **Started:** 2026-07-18
- **Completed:** 2026-07-18
- **Tasks:** 2
- **Files:** 3 (3 created, 0 modified)

## Accomplishments
- `EustackAdapter(ConfigurableAdapter)` (`name = "eustack"`): per-thread grouping where a `TID <n>:` header is the record-start trigger (mirroring the genericlog/dsserrors multi-line skeleton, but on a structural header instead of a timestamp). Frames accrue into the event until the next `TID` header or a safety cap.
- Field mapping: `message` = the first `CONDENSED_FRAMES` (5) frame symbols with any ` - lib source:line` suffix stripped (signal, not noise); `raw` = the verbatim thread block (suffix intact); `thread` = the TID; `component`/`session` = `None` (native eu-stack carries neither).
- **No lock info fabricated.** Native eu-stack has no blocked-on/lock lines, so `attrs` never gains `waiting_on`/`locked`/`state` — the contingent INGST-09 lock clause is satisfied by asserting *absence* (per the plan's W2 contingency and the 05-02 resolution).
- Single dump-time timestamp: the preamble is scanned once for a leading ISO-8601 stamp; if present it stamps **every** thread (offset-bearing → `exact`, naive → `inferred` through the shared `base.to_utc`); if absent every thread is `ts=None`/`ts_confidence="missing"` — per-thread times are never invented.
- Bounded memory: local `MAX_EVENT_LINES` (256) / `MAX_EVENT_BYTES` (64 KB) caps force-close a monster thread into a `severity="unknown"` continuation (Pitfall 5 / T-05-30); the 260-frame fixture thread and an inline 400-frame thread both stay bounded.
- Fail-soft coverage: an `is_fallback` flag lets a covered thread event legitimately carry `severity="unknown"` while only the preamble (unparseable header region) and the cap overflow count as `unknown_fallback_bytes` — the fixture lands **~96.99%** (bounded 95–100, non-vacuous). Event byte spans partition the file (contiguous from 0).
- `sniff`: **both** a `TID <n>:` header AND an eu-stack frame (`#\d+\s+0x`) must appear in the head → `0.8`; a bare "TID" mention without frames, or plain prose → `0.0`.

## Task Commits
1. **Task 1: sanitised eu-stack thread-dump fixture (4 threads, cap case)** — `fc06c5b` (test)
2. **Task 2: EustackAdapter sniff/parse/grouping/condensed-frames/dump-ts/caps (TDD RED→GREEN)** — `0eb6627` (feat)

## Files Created/Modified
- `src/sift/adapters/eustack.py` — new: `EustackAdapter`, `_condense_symbol`, `_match_ts`, `byte_lines`, `_Record`, module-level anchored `_TID_RE`/`_FRAME_RE`/`_TS_RE`/sniff regexes + local caps.
- `tests/test_eustack.py` — new: 15 tests (sniff / grouping / condensed frames / lock-absence / dump-ts exact+inferred+missing / cap / coverage) with a local `run_parse`/`assert_span_partition` harness mirroring test_dsserrors.
- `tests/fixtures/eustack/threaddump.txt` — new sanitised native eu-stack dump: small unparseable preamble, one offset-bearing dump-time ts, four thread blocks, the fourth deliberately oversized (260 frames) to breach the 256-line cap. No lock lines (native format).

## Decisions Made
- **Format frozen as native elfutils eu-stack** (05-02 proceed-on-assumed-shapes). Regexes anchor on stable structural tokens (`TID <n>:`, `#N 0xADDR symbol`), so a later JVM-shape sample is a localised regex + lock-attr addition — the grouping rule is already format-independent.
- **Lock info met by absence.** INGST-09 / ROADMAP Criterion 3 "lock info in attrs" is satisfied by `test_no_lock_attrs_native_format` asserting the attrs are absent — a downstream verifier must NOT read this as unmet: the confirmed format legitimately carries no lock info.
- **Preamble is fallback and dump-ts carrier.** The header region before the first `TID` is one `severity="unknown"`, `ts=None` fallback event, scanned in passing for the single dump-time stamp; combined with the cap overflow it drives bounded (<100%) coverage.

## Deviations from Plan

### Auto-fixed Issues
**1. [Rule 1 - Bug] Fixture dump-ts used a space before the offset, parsing as naive**
- **Found during:** Task 2 (GREEN — `test_single_dump_ts_stamps_all_threads` red)
- **Issue:** The fixture's dump-time line was `2026-07-18 09:15:30 +0000 ...`; the anchored `_TS_RE` (shared shape with dsserrors) expects the offset immediately after the seconds, so the space made only the naive `2026-07-18 09:15:30` match → `inferred`, not the intended `exact`.
- **Fix:** Regenerated the fixture with an ISO offset-bearing stamp `2026-07-18T09:15:30+00:00` (no space) so the offset is captured → `exact`. Amended into the Task-1 commit (`fc06c5b`) to keep the fixture atomic.
- **Files modified:** tests/fixtures/eustack/threaddump.txt
- **Commit:** fc06c5b

No architectural changes. `adapters/__init__.py` left untouched — registration + the end-to-end `sift ingest` slice are the Wave-3 integration plan's job (05-06).

## Issues Encountered
None beyond the fixture timestamp-format fix above. The per-thread grouping, condensed-frame stripping, dump-ts stamping, and cap logic all behaved as designed on the first adapter draft.

## Known Stubs
None. The adapter is fully wired; registration and the end-to-end `sift ingest` slice are deliberately deferred to Wave-3 (05-06) per the plan's scope.

## Threat Flags
None. No new network, auth, or filesystem surface — stdlib `re`/`datetime` only, reading files already inside the case input dir. Thread/message content rides the same parameterised-`?` store path and the existing whole-line render `_sanitise` (T-05-31/32/33); zero external packages (T-05-SC).

## User Setup Required
None — zero new dependencies (stdlib only).

## Next Phase Readiness
- INGST-09 satisfied at the adapter level: eu-stack bytes → one UTC-stamped, condensed-frame Event per thread with real bounded coverage; the DoS cap and span-partition invariants both proven.
- The native-eu-stack regexes are anchored on stable structural tokens; a later user-supplied JVM-style sample is a localised change (small gap-closure plan adding lock-attr extraction), not a restructure.
- Wave-3 (05-06) owns `adapters/__init__.py` registration, the `sift ingest` routing test (eustack beats genericlog), and the CliRunner e2e slice.

## Self-Check: PASSED

All three created files and this SUMMARY exist on disk; both task commits (`fc06c5b`, `0eb6627`) are present in `git log`. Full M5 gate: **361 passed, 2 deselected** (pre-existing live-UAT markers), ruff clean, pyright 0 errors/0 warnings.

---
*Phase: 05-domain-adapters-journald-dsserrors-eustack*
*Completed: 2026-07-18*
