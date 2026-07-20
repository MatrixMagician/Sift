---
phase: 12-dssperfmon-adapter-pipeline-exclusion
plan: 02
subsystem: adapters
tags: [dssperfmon, pdh-csv, parse-coverage, unknown-fallback, adr-0012]
status: complete
requires:
  - sift.adapters.dssperfmon.DssperfmonAdapter (12-01)
  - sift.adapters.base.ParseStats.coverage
  - sift.adapters.dsserrors.DsserrorsAdapter
  - tests/fixtures/dssperfmon/hartford_deny_slice.csv (12-01)
  - tests/fixtures/mcm/hartford_deny_slice.log
provides:
  - sift.adapters.dssperfmon._fallback_event
  - sift.adapters.dssperfmon._bad_cells
  - Event.attrs["unparsed_columns"]
  - tests/test_dssperfmon.py::test_csv_aligns_with_paired_log
affects:
  - 12-03 (adapter registration — unchanged public surface)
  - 13-* (episode correlation consumes unknown Events and their surviving ts)
tech-stack:
  added: []
  patterns:
    - single _fallback_event funnel enforces the never-drop guarantee
    - timestamp parsed before any fallback branch so drift keeps a good ts
    - float() as a discarded validity probe; attrs keep unconverted strings
key-files:
  created: []
  modified:
    - src/sift/adapters/dssperfmon.py
    - tests/test_dssperfmon.py
decisions:
  - _parse_header returns its disclosure notes rather than taking a stats parameter, preserving 12-01's signature ownership
  - column drift keeps a recoverable ts; D-16 requires the unknown severity, not the loss of a parsed timestamp
  - unparsed_columns joins on ";" — counter names contain spaces and parentheses but never a semicolon
metrics:
  duration: ~20 min
  tasks: 2
  files: 2
  completed: 2026-07-20
---

# Phase 12 Plan 02: dssperfmon Malformed-Row Fallbacks Summary

Every malformed PDH-CSV row now degrades to a preserved `severity="unknown"` Event whose bytes
count against per-file parse coverage, and ADR 0012's cross-artefact alignment is pinned by an
executable test proven to fail when a bias shift is reintroduced.

## What Was Built

**Task 1 — fallback branches** (RED `be06a33`, GREEN `57e362f`).

`_fallback_event(...)` is the single funnel every malformed branch routes through: it builds the
unknown Event with the verbatim decoded line as `raw`, the same `byte_offset`/`byte_len` attrs
spellings, and the caller's `ts`/`ts_confidence`. No branch returns, raises, recurses or continues
past emission, so a file of entirely malformed rows costs one pass and bounded memory (T-12-06).

Branch order inside the row handler, with the read loop and offset accounting from 12-01 untouched:

- **Step 0 — timestamp first.** `strptime` is attempted before any fallback branch and the result is
  carried into whichever fires. `ValueError` → `ts=None`, `ts_confidence="missing"` (D-15), mirroring
  `dsserrors._match_ts`'s guard.
- **1. Column drift (D-16).** `len(row) != header_width` appends a `ParseStats.notes` entry naming
  the line number, observed and expected counts, and degrades the row — no realign, pad or truncate.
  The row keeps its timestamp when one parsed.
- **2. Cell validity (D-14).** `_bad_cells` probes each counter cell with `float()`; failures
  (blank, whitespace-only, non-numeric) contribute their short counter names to
  `attrs["unparsed_columns"]`. The probe's result is discarded — stored values remain unconverted
  strings, so a crafted numeric literal cannot alter stored state (D-03, T-12-07).

All three set the row's bytes into `stats.unknown_fallback_bytes`, exactly as `dsserrors.finish()`
accumulates, so the existing `ParseStats.coverage` property reflects the loss with no new counter
(PERF-02, T-12-08).

`_parse_header` now tolerates a header declaring no zone or bias: the corresponding attrs keys are
omitted rather than invented, and the disclosure travels back in the return tuple for the caller to
append to `stats.notes`. Timestamps are unaffected either way — under ADR 0012 the bias is inert.

Embedded newlines get no special handling by design. `byte_lines` splits on the newline byte, so
such a record arrives as two fragments, each hitting the column-count branch. The test pins the
split so it is deliberate rather than accidental; reassembly would require buffering across
`byte_lines` and so compromise the byte-offset contract `event_id` depends on (RESEARCH Q4).

**Task 2 — ADR 0012 alignment pin** (`98e2f5e`). `test_csv_aligns_with_paired_log` reads both halves
of the matched Hartford pair through their own adapters with no tz override, and asserts the CSV's
final sample (`12:39:39.397`) precedes the log's MCM denial (`12:39:47.146`) by a positive interval
under 10 seconds — a 7.75 s lead-in. The denial record is selected by matching the
`Contract Request Failed` marker text, not by index, so a re-sliced fixture fails loudly rather than
drifting onto the wrong record.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Lint gate] `_DRIFT_NOTE` wrapped, test imports merged**
- **Found during:** Tasks 1 and 2 (`ruff check`: E501, then I001)
- **Issue:** The drift note exceeded 88 columns as a single string; the Task 2 `timedelta` import was
  added as a second `datetime` import block.
- **Fix:** Implicit string concatenation for the note; merged into the existing
  `from datetime import UTC, datetime, timedelta`.
- **Commits:** `57e362f`, `98e2f5e`

### TDD Gate Note (not a deviation, recorded deliberately)

Task 2's test passed on first run. This is expected and not a skipped RED: the behaviour it asserts
(ADR 0012's recorded-not-applied rule) shipped in plan 12-01, so this test is a regression pin, not
new behaviour. Rather than accept a possibly-vacuous green, its load-bearing property was verified
by counterfactual: injecting the header's declared 300-minute bias into the adapter's `to_utc` call
makes the test fail (lead-in goes negative by ~5 hours) while every single-adapter perfmon test
stays green. The adapter was restored byte-identically before commit (`git diff --quiet` confirmed).
That asymmetry is exactly the defect class the test exists to catch.

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/test_dssperfmon.py` | 17 passed (9 from 12-01, 8 new) |
| `uv run pytest -k unknown_fallback` | 2 passed (blank cell, non-numeric cell) |
| `uv run pytest` (full suite) | 554 passed, 8 deselected |
| `uv run ruff check` | clean |
| `uv run pyright` | 0 errors, 0 warnings |
| `git diff --stat` scope | only `src/sift/adapters/dssperfmon.py` and `tests/test_dssperfmon.py` |
| `pyproject.toml` unchanged | confirmed — no new dependency (T-12-SC) |
| No `pytest.raises` in any synthetic test | confirmed — malformed input degrades, never raises |
| Alignment pin fails when bias applied | confirmed by counterfactual, adapter restored clean |

## Known Stubs

None. All D-14/D-15/D-16 malformed shapes are implemented and tested. Adapter registration remains
plan 12-03's scope, so `detect()` does not yet route PDH-CSV files here.

## Self-Check: PASSED

- FOUND: `src/sift/adapters/dssperfmon.py`
- FOUND: `tests/test_dssperfmon.py`
- FOUND commits: `be06a33`, `57e362f`, `98e2f5e`
