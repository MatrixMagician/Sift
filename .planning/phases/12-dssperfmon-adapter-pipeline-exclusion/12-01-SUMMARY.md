---
phase: 12-dssperfmon-adapter-pipeline-exclusion
plan: 01
subsystem: adapters
tags: [dssperfmon, pdh-csv, adapter, timestamps, adr-0012]
status: complete
requires:
  - sift.adapters.base.ConfigurableAdapter
  - sift.adapters.base.to_utc
  - sift.adapters.base.tz_override_for
  - sift.adapters.genericlog.byte_lines
  - sift.models.event_id
provides:
  - sift.adapters.dssperfmon.DssperfmonAdapter
  - tests/test_dssperfmon.py helpers (run_parse, assert_span_partition, write, FIXTURES)
  - tests/fixtures/dssperfmon/hartford_deny_slice.csv
affects:
  - 12-02 (malformed-row paths reuse this module and test helpers)
  - 12-03 (adapter registration)
  - 13-* (episode correlation consumes these Events)
tech-stack:
  added: []
  patterns:
    - stdlib csv parses one row at a time; byte_lines owns file iteration
    - anchored literal byte-prefix sniff, zero regex in the module
key-files:
  created:
    - src/sift/adapters/dssperfmon.py
    - tests/test_dssperfmon.py
    - tests/fixtures/dssperfmon/hartford_deny_slice.csv
  modified: []
decisions:
  - assert_span_partition takes a start offset because the PDH header is not an Event
  - fixture asserts 22 counters (real artefact), not the plan's stated 23
metrics:
  duration: ~15 min
  tasks: 2
  files: 3
  completed: 2026-07-20
---

# Phase 12 Plan 01: dssperfmon Adapter Happy Path Summary

PDH-CSV adapter parsing DSSPerformanceMonitor samples into one canonical `Event` per row with
byte-offset-deterministic ids and ADR-0012 recorded-not-applied timestamps.

## What Was Built

**Task 1 — fixture** (`3d079ef`). `tests/fixtures/dssperfmon/hartford_deny_slice.csv`: the verbatim
PDH header plus the first 10 and last 10 data rows of the real Hartford artefact, 20 samples ending
at the reference `04/07/2026 12:39:39.397` sample that ADR 0012 pairs against the log denial. LF
terminators and quoting preserved byte-for-byte; no synthetic values.

**Task 2 — adapter + tests** (RED `805214c`, GREEN `ab72b35`). `src/sift/adapters/dssperfmon.py`:

- `sniff` compares `read_head(path)` against the literal `PDH_SNIFF_PREFIX` bytes — 0.95 on the
  fixture, 0.0 on plain text. No decode, no scan, no regex (T-12-01 discharged by construction;
  `grep -c '^import re'` returns 0).
- `parse` iterates `byte_lines(stream, b"\n", b"", unit=1)` and advances `offset += len(bline)`
  before any decode, so `event_id` is reproducible across re-ingest. Stdlib `csv.reader` is called
  on a one-element list per row and never owns file iteration.
- `_parse_header` derives host, declared zone name, declared bias and short counter names by
  backslash splitting and parenthesis partitioning — no regex. The bias disclosure lands once in
  `ParseStats.notes`.
- Timestamps: `datetime.strptime(row[0], TS_FORMAT)` → `to_utc(naive, override_tz)`, the identical
  call shape `dsserrors` uses. The declared bias reaches `attrs` as `tz_name`/`tz_offset_min` and
  never enters arithmetic (ADR 0012, T-12-03).
- Every well-formed row is `severity="info"` — magnitude is never read as severity (D-05).

`tests/test_dssperfmon.py`: 9 tests covering sniff pair, row count, attrs/message rendering, span
partition and coverage, id stability, UTC/confidence, tz override, and header-zone recording.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Contradictory must-haves] `assert_span_partition` gained a `start` parameter**
- **Found during:** Task 2 (GREEN run, `test_span_partition_and_coverage` failed at offset 1926)
- **Issue:** The plan required both "the PDH header line is not an Event (D-01)" and "spans
  partition the file contiguously **from 0**". For this format those cannot both hold: the header's
  1926 bytes precede the first Event, so no Event can start at byte 0.
- **Fix:** `assert_span_partition(events, total_bytes, start=0)` — the test passes the header's byte
  length. The invariant that actually matters (no gaps, no overlaps, every subsequent byte
  accounted, sum reaching `total_bytes`) is preserved intact. The alternative — folding the header's
  bytes into the first Event's `byte_offset` — was rejected because `byte_offset` must equal the
  Event's own first byte or `event_id` stops being meaningful.
- **Files modified:** `tests/test_dssperfmon.py`
- **Commit:** `ab72b35`

**2. [Rule 1 — Plan/reality mismatch] Counter count is 22, not 23**
- **Found during:** Task 1 verification
- **Issue:** The plan (via REQUIREMENTS.md § Reference Data) states 23 counters / 24 fields per row.
  The real artefact has 22 counter columns / 23 fields. The plan's own acceptance criterion (a
  single-element field-count set) passes either way.
- **Fix:** Tests assert against the real artefact. No code change; the adapter derives counter names
  from the header and is count-agnostic. Flagged here so downstream plans and REQUIREMENTS.md can be
  corrected.
- **Commit:** `3d079ef`

**3. [Rule 3 — Lint gate] `# noqa: DTZ007` on the naive `strptime`**
- **Found during:** Task 2 (`ruff check`)
- **Issue:** Ruff's DTZ007 flags `strptime` without a timezone. Complying by attaching a tzinfo would
  bypass `to_utc` and the `--tz` override — precisely what ADR 0012 forbids.
- **Fix:** Suppressed with a four-line comment naming ADR 0012 as the reason.
- **Commit:** `ab72b35`

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/test_dssperfmon.py` | 9 passed |
| `uv run pytest` (full suite) | 546 passed, 8 deselected |
| `uv run ruff check` | clean |
| `uv run pyright` | 0 errors, 0 warnings |
| `pyproject.toml` unchanged | confirmed — no new dependency (T-12-SC) |
| `grep -c '^import re'` on the adapter | 0 |

## Known Stubs

None. Malformed-row handling (blank cells, unparseable timestamps, column-count drift) is
out of scope by design and lands in plan 12-02; the adapter is not stubbed for it — the fallback
branches simply do not exist yet. Adapter registration is plan 12-03, so `detect()` does not yet
route PDH-CSV files here.

## Self-Check: PASSED

- FOUND: `src/sift/adapters/dssperfmon.py`
- FOUND: `tests/test_dssperfmon.py`
- FOUND: `tests/fixtures/dssperfmon/hartford_deny_slice.csv`
- FOUND commits: `3d079ef`, `805214c`, `ab72b35`
