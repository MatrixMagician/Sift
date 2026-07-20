---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
plan: 03
subsystem: adapters
tags: [dssperfmon, parse-notes, attrs-keys, security]
requires: [13-01]
provides:
  - "qualified counter keys (last two backslash segments) for colliding short names"
  - "_DRIFT_ATTR per-event drift marker in Event.attrs"
  - "_NOTE_CAP bounded, per-category ParseStats.notes"
affects: [13-04, 13-05, 13-06]
tech-stack:
  added: []
  patterns: ["hand-rolled string partitioning, no regex (T-12-01)"]
key-files:
  created: []
  modified:
    - src/sift/adapters/dssperfmon.py
    - tests/test_dssperfmon.py
decisions:
  - "Qualified key = last TWO backslash segments; full path only if that still collides."
  - "Qualification applies ONLY to colliding names, so Phase 12's 22 Hartford keys stay byte-identical."
  - "_DRIFT_ATTR = \"counter_set_drift\", added to _RESERVED_ATTRS in the same edit."
  - "_NOTE_CAP = 10, counted per category via a parse-local dict rather than widening ParseStats."
  - "cli.py left unchanged: its note path applies no separate limit, so bounding the producer suffices."
metrics:
  duration: ~25 min
  tasks: 3
  files: 2
  completed: 2026-07-20
status: complete
---

# Phase 13 Plan 03: Phase 12 Review Warnings (WR-03, WR-05, WR-02) Summary

Colliding PDH counter columns are retained under qualified `attrs` keys, column drift is recorded
per event as citable evidence, and repeated parse notes are bounded per category with an honest
suppression summary.

## What Was Built

**WR-03 — `_qualify_counter_names`** (`src/sift/adapters/dssperfmon.py`). `dict(zip(...))` silently
discarded all but the last column sharing a short name. Colliding columns are now keyed by their
last two backslash segments (`Process(MSTRSvr)\Size(MB)`), falling back to the full counter path if
two segments still collide. Non-colliding names are untouched — the reason Hartford's 22 keys and
Phase 12's golden assertions survive unchanged. A `_COLLISION_NOTE` discloses the qualification.
`_short_counter_name` is unchanged; it is the one-segment helper the new function calls.

**WR-05 — `_DRIFT_ATTR`** (`counter_set_drift`). A drifted row now carries
`attrs["counter_set_drift"] = "{seen} columns, expected {expected}"`. It is set *before* the counter
loop, so the pre-existing `_RESERVED_ATTRS` prefix logic protects it with no second guard — a
counter column named `counter_set_drift` lands under `counter.counter_set_drift`. Drift is detected
once, at ingest; the correlator never re-detects it (D-15). `severity="unknown"` and the preserved
timestamp are untouched.

**WR-02 — `_NOTE_CAP = 10`.** Both the drift note and the CSV-tokenise note sat inside the per-row
loop with unbounded appends: one header-width mismatch on the reference artefact means 13,596 notes
(~1 MB in a single `parse_coverage` meta row, 13,596 terminal lines). A parse-local `seen_notes`
dict caps each category independently; each category that overflows emits exactly one
`_NOTE_SUMMARY` line after the loop. Categories under the cap emit no summary.

## Deviations from Plan

None — plan executed as written.

The plan's Task 3 asked which of two `cli.py` outcomes applied: **outcome A**. `cli.py:376-391`
persists and prints `stats.notes` verbatim with no separate limit of its own, so bounding the
producer is sufficient and no double-truncation or contradiction is possible. `cli.py` is therefore
unmodified by this plan despite appearing in `files_modified`.

Both fail-fast checks in the acceptance criteria were satisfied naturally: neither
`test_collision_qualified_keys_retain_both_counters` nor
`test_counter_named_like_drift_marker_cannot_shadow_it` passed before its implementation landed
(the first failed on a missing key, the second on `ImportError`), so no counterfactual revert was
needed.

## Tests Added

`tests/test_dssperfmon.py`, 8 new tests (21 → 29 in the file):

| Test | Guards |
|------|--------|
| `test_collision_qualified_keys_retain_both_counters` | T-13-DROP: both columns kept, distinct values |
| `test_hartford_keys_byte_identical` | 22 literal key names, not a recomputed expectation |
| `test_drift_marker_in_attrs` | marker on drifted rows, absent on good ones |
| `test_drift_marker_survives_note_cap` | 40 drifted rows, all carry the marker |
| `test_counter_named_like_drift_marker_cannot_shadow_it` | T-13-ATTRKEY |
| `test_notes_capped` | T-13-DOS: cap + one summary + evidence intact |
| `test_note_cap_is_per_category` | one noisy category cannot starve another |
| `test_no_summary_note_below_cap` | no summary when nothing was suppressed |

## Verification

- `uv run ruff check` — clean
- `uv run pyright` — 0 errors, 0 warnings
- `uv run pytest` — 591 passed, 8 deselected

## Requirements

PERF-05 remains **In Progress**. This plan lands the drift *evidence* the hazard will cite; the
user-visible counter-set-drift hazard itself is plan 13-04's. Not marked complete.

## Notes for Downstream Plans

- Plan 13-04's `Total MCM Denial` lookup should use the short name; it only becomes qualified if a
  customer CSV carries that counter under two instances.
- The counter-set-drift hazard reads `attrs["counter_set_drift"]`, not `stats.notes` — the notes are
  capped, the marker is not.

## Self-Check: PASSED

- `src/sift/adapters/dssperfmon.py` — FOUND
- `tests/test_dssperfmon.py` — FOUND
- Commits `1a3cb5c`, `f0b88e5`, `45afdc3`, `2a4b8f9`, `c2ab765`, `9de68a3` — all present in `git log`
