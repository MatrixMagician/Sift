---
phase: 01-skeleton-event-contract-genericlog-adapter
plan: 03
subsystem: ingest
tags: [genericlog, timestamp-ladder, encodings, byte-offsets, coverage, gzip, zstd]

requires:
  - 01-02 (frozen Event/Adapter contracts, CaseStore, genericlog v0, open_bytes seam)
provides:
  - Full timestamp ladder — ISO 8601 (T/space, fractional, Z, ±HH:MM), syslog RFC3164 with mtime year inference, epoch seconds/millis with plausibility window, Apache CLF — with per-file format lock-in fast path
  - D-05 UTC normalisation — naive ts routed through tz_overrides glob or UTC, ts_confidence exact/inferred/missing, one disclosure note per file per assumption kind in ParseStats.notes
  - Encoding-aware byte-offset loop — BOM sniff (utf-8-sig, utf-16-le/be), per-encoding newline byte patterns, cp1252 per-record fallback, decode errors-replace only after offsets fixed
  - D-06 safety caps — MAX_EVENT_LINES 256 / MAX_EVENT_BYTES 65536, breach opens a severity-unknown continuation event; newline-less runs force-split at 64 KB
  - Span-partition invariant — byte_offset/byte_len in Event.attrs; spans contiguous from 0 and summing to total decompressed bytes on every fixture encoding
  - Compressed-input parity proven — gz/multi-member gz/zst/multi-frame zst identical offsets, line numbers, messages, coverage to plain; corrupt zstd raises loudly
affects: [01-04, 01-05, phase-2, phase-5]

tech-stack:
  added: []
  patterns:
    - "Ladder entries return possibly-naive datetimes; one caller assigns confidence (aware=exact, naive=to_utc inferred)"
    - "syslog parsed by hand, not strptime — strptime's year-1900 default rejects Feb 29"
    - "Event byte spans exposed via attrs (str->str) so invariants are testable without re-deriving offsets"

key-files:
  created:
    - tests/test_genericlog.py
  modified:
    - src/sift/adapters/genericlog.py

key-decisions:
  - "byte_offset and byte_len recorded in Event.attrs — the span-partition invariant and compressed parity are mechanically checkable, and citations later get the span for free"
  - "A2 confirmed: token-less timestamped lines keep severity 'unknown', never fabricated to 'info'"
  - "Newline-less runs force-split at MAX_EVENT_BYTES inside the byte splitter so a single monster line cannot slurp unbounded memory (T-03-01)"
  - "TDD_MODE off per orchestrator: tests and implementation land together in one commit per task"

patterns-established:
  - "Per-file format lock-in: last-matched ladder index tried first, full ladder on miss — deterministic fast path"
  - "BOM bytes belong to the first event's span, stripped from decoded text only (Pitfall 7)"

requirements-completed: [INGST-04, INGST-05, INGST-06, INGST-10, INGST-11]

coverage:
  - id: D1
    description: "ISO/syslog/epoch/CLF all parse; continuation lines group; '20260716' prefix and out-of-window epochs rejected"
    requirement: "INGST-04"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_genericlog.py -k format (8 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Leading unparseable region -> severity-unknown event, ts_confidence missing; coverage hand-computed = 1 - unknown_bytes/total; empty file = 1.0"
    requirement: "INGST-05"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_genericlog.py -k coverage (10 passed, incl. span-partition invariant across 7 encodings)"
        status: pass
    human_judgment: false
  - id: D3
    description: "12-line stack trace = one event; 300-line record splits at 256 lines; >64 KB record splits on byte cap"
    requirement: "INGST-06"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_genericlog.py -k multiline (3 passed)"
        status: pass
    human_judgment: false
  - id: D4
    description: "gz/multi-member gz/zst/multi-frame zst identical (byte_offset, line_start, message) and coverage to plain; magic-not-extension; corrupt zst raises"
    requirement: "INGST-10"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_genericlog.py -k compressed (7 passed)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Naive ts -> UTC inferred with disclosure; tz_overrides glob applies IANA zone; explicit offset stays exact"
    requirement: "INGST-11"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_genericlog.py -k timezone (3 passed)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Full quality gates green"
    verification:
      - kind: other
        ref: "uv run pytest (64 passed); uv run ruff check; uv run pyright — all exit 0"
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-07-16
status: complete
---

# Phase 01 Plan 03: genericlog Hardening Summary

**genericlog grown from ISO-only v0 into the robust fallback parser: four-entry timestamp ladder with per-file lock-in, BOM/encoding-aware byte accounting (utf-16-le/be, utf-8-sig, cp1252), D-06 256-line/64 KB caps, span-partition coverage invariant, and byte-offset-identical gzip/zstd ingest**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-07-16T16:24:45Z
- **Completed:** 2026-07-16T16:39:02Z
- **Tasks:** 3 (all auto)
- **Files modified:** 2

## Accomplishments

- Timestamp ladder per RESEARCH Pattern 5: ISO 8601 (all variants incl. comma fractions), syslog RFC3164 (year from mtime, minus one when > mtime + 1 day), epoch s/ms bounded to [946684800, 4102444800], Apache CLF (A1) — with per-file format lock-in fast path
- D-05 semantics complete: aware timestamps "exact", naive routed through the first-matching tz_overrides glob (zoneinfo) or UTC as "inferred"; disclosures (assumed zone + matching glob, syslog year inference) appended once per file per kind to ParseStats.notes
- Byte accounting is encoding-aware: BOM sniff selects encoding + newline byte pattern (utf-8 `\n`, utf-16-le `\n\x00`, utf-16-be `\x00\n`); all splitting/offsets at byte level; decode per record with cp1252/errors-replace fallback only after spans are fixed (Pitfall 1); BOM bytes in the first event's span, stripped from text only (Pitfall 7)
- D-06 caps enforced: line/byte breach closes the event and opens a severity-unknown, ts-missing continuation event; the byte splitter also force-splits newline-less runs at 64 KB so memory stays bounded on hostile input (T-03-01)
- Span-partition invariant holds on all seven fixture encodings: spans contiguous from 0, non-overlapping, summing to total decompressed bytes — byte_offset/byte_len now exposed in Event.attrs
- Compressed parity proven: gz, multi-member gz (split mid-line), zst, multi-frame zst all yield identical event fingerprints and coverage to plain text; gzip content under a `.log` name decompresses (magic bytes); corrupt zstd raises from the parse iterator — never silent truncation
- 37 genericlog tests across the six plan groups; full suite 64 passed, ruff and pyright clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Timestamp ladder + UTC normalisation with ts_confidence and tz overrides** — `7598e84` (feat)
2. **Task 2: Encoding-aware byte accounting, D-06 caps, and the coverage invariant** — `c3048d5` (feat)
3. **Task 3: Compressed inputs — gzip/zstd with decompressed-stream offsets** — `2f11263` (test)

## Files Created/Modified

- `src/sift/adapters/genericlog.py` — ladder entries (`_try_iso/_try_syslog/_try_epoch/_try_clf`), `_match_ts` with lock-in, `_detect_encoding`, `_decode`, `_byte_lines` splitter, cap logic, span attrs, disclosure notes; constants `EPOCH_MIN/EPOCH_MAX/MAX_EVENT_LINES/MAX_EVENT_BYTES`
- `tests/test_genericlog.py` — 37 tests in six `-k`-selectable groups (format 8, timezone 3, multiline 3, coverage 10, encoding 13 incl. parametrised overlap, compressed 7) with local fixture builders and the `assert_span_partition` helper (conftest.py untouched — owned by 01-01)

## Decisions Made

- **Event.attrs carries `byte_offset`/`byte_len`** (adapter-specific str→str extras, schema-compliant): Task 3's acceptance criterion compares per-event byte offsets across compressed variants, and the span-partition invariant needs real spans — attrs was the only contract-frozen-safe channel, and it doubles as citation metadata later
- **syslog parsed by hand, not strptime**: `strptime("%b %d %H:%M:%S")` defaults to year 1900 and rejects "Feb 29"; regex + `_MONTHS` lookup + explicit `datetime()` handles leap-day edges (invalid dates in the target year return no-match, never a fabricated date)
- **A2 confirmed as planned**: timestamped lines without a recognised severity token stay `severity="unknown"` — the parser never fabricates severities or timestamps
- **Cap-overflow events count as unknown-fallback for coverage** (ts None), per the plan's INGST-06 probe — coverage cannot trivially read 100%

## Deviations from Plan

None — plan executed as written. (Two ruff nits — long regex lines, an UP012 — and one intentional-naive-datetime `noqa: DTZ001` were fixed before each commit; no behavioural deviation.)

## Known Stubs

None introduced by this plan. The 01-02 stubs owned by plan 01-04 (`detect()` v0, config wiring, empty `tz_overrides` from `ingest`) are unchanged and still owned there — this plan's tz_overrides mechanism is exercised directly via the adapter instance until 01-04 wires config.

## Threat Flags

None — no new security surface beyond the plan's threat model. T-03-01 (decompression bomb) mitigated: streaming decompression, per-event caps, forced 64 KB split of newline-less runs, nothing written decompressed to disk. T-03-02 (hostile encodings) accepted as specified: errors-replace decoding happens strictly after byte offsets are fixed, so malformed bytes cannot corrupt identity or coverage.

## Issues Encountered

None. All gates were green at each task boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 01-04 can wire `tz_overrides` from config to the adapter instance — the mechanism is proven by the timezone test group
- Plan 01-05 (fixtures/README) can reuse the six test groups as the INGST validation commands from 01-VALIDATION.md
- Phase 5 adapters inherit the `open_bytes`/`ParseStats` seams unchanged; the frozen contracts were not touched

## Self-Check: PASSED

Both files exist on disk; all three task commits (7598e84, c3048d5, 2f11263) present in git log; full gate `uv run pytest && uv run ruff check && uv run pyright` green.

---
*Phase: 01-skeleton-event-contract-genericlog-adapter*
*Completed: 2026-07-16*
