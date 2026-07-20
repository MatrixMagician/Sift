---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
plan: 05
subsystem: render
tags: [perfmon, renderer, csv, markdown, json, csv-injection]
status: complete
requires:
  - "sift.pipeline.perfmon: PerfmonAnalysis, TrendGroup, CounterTrend, PerfmonHazard (plan 13-02/13-04)"
  - "sift.render.markdown._field (shared escaping)"
provides:
  - "sift.render.perfmon_report.render_perfmon_markdown"
  - "sift.render.perfmon_report.render_perfmon_json"
  - "sift.render.perfmon_report.write_perfmon_trend_csv"
  - "sift.render.perfmon_report.PERFMON_CSV_HEADER"
affects:
  - "plan 13-06 (the sift perfmon CLI command wires these three functions)"
tech-stack:
  added: []
  patterns:
    - "Renderer mirrors mcm_report.py structure: pure analysis -> str/-> file, no store re-read"
    - "Formula-injection guard as a separate function, deliberately NOT sanitise"
key-files:
  created:
    - src/sift/render/perfmon_report.py
    - tests/test_perfmon_report.py
  modified: []
decisions:
  - "PERFMON_CSV_HEADER carries a 12th column, boundary_event_ids, beyond the nine D-18 named; it is the only multi-id field in scope and keeps every row traceable to the span it was computed over"
  - "_csv_safe is applied to string cells only; numeric cells are written as real floats so a legitimately negative slope keeps its minus sign rather than being corrupted into text"
  - "Figures are rendered with str(), never a format spec, preserving the correlator's round-at-source discipline"
metrics:
  duration: ~25 min
  tasks: 3
  files: 2
  tests_added: 15
  completed: 2026-07-20
---

# Phase 13 Plan 05: Perfmon Report Renderer Summary

Markdown, canonical JSON and the per-counter-per-episode trend CSV for `PerfmonAnalysis`, with a formula-injection guard for the attacker-influenceable counter names.

## What was built

`src/sift/render/perfmon_report.py` — three public functions plus their private helpers:

| Symbol | Role |
|--------|------|
| `render_perfmon_markdown` | One section per `TrendGroup`: label, resolved span, counter table, hazard table (D-19). Empty analysis states the no-episode/full-sample-range fallback and returns early (D-20). |
| `render_perfmon_json` | `json.dumps(sort_keys=True, ensure_ascii=True, indent=2)` + trailing newline (D-21). |
| `write_perfmon_trend_csv` | One row per counter per span; header written before any iteration (D-18). |
| `PERFMON_CSV_HEADER` | 12-column module-level tuple. |
| `_csv_safe` | Prefixes `'` on any string cell starting `=`, `+`, `-`, `@`, TAB or CR (T-13-CSVINJ). |
| `_counter_table` / `_hazard_table` / `_figure` / `_citations` / `_group_section` | Markdown helpers. |

Every computed figure is rendered alongside the `event_id` it was derived from; `_citations` joins `at_denial_event_id` and `peak_event_id`, and each CSV row carries the span's `boundary_event_ids`. No raw sample series appears in any artefact.

## Key decisions

**The formula guard is separate from `sanitise`, deliberately.** `sanitise` keeps every character with `ord >= 0x20` outside C1 that is not category Cf — so `=`, `+`, `-` and `@` pass through untouched. `csv.writer` quoting stops delimiter injection but a quoted cell beginning `=` is still evaluated on open. `write_attribution_csv`'s "quoting is the complete mitigation" argument rests on MCM keys being structurally hex or `[\w:]+`; counter names come from the customer's CSV header, so that premise does not transfer. `_csv_safe`'s docstring records all three facts and names the divergence explicitly so it reads as deliberate.

**Only string cells are guarded.** Numeric cells go to `csv.writer` as real floats. Guarding them would prefix a quote onto every negative slope — turning a measurement into text and corrupting the data the CSV exists to carry.

**`str()` not a format spec for figures.** The correlator rounds at source (3 dp values, `SLOPE_DP` slopes). Re-rounding at render would risk the report and the CSV showing two different numbers for the same stored figure.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 2 - Missing traceability] Added `boundary_event_ids` as a CSV column**
- **Found during:** Task 3
- **Issue:** The plan named nine D-18 columns, none multi-valued, yet also required `test_csv_event_ids_semicolon_joined` to assert a `;`-joined multi-id cell. `boundary_event_ids` is the only multi-id field in scope.
- **Fix:** Added it (plus `group_scope` and `group_label`) to `PERFMON_CSV_HEADER`, `;`-joined. This satisfies the test and keeps each row traceable to the span it was computed over — the citation contract the report rests on.
- **Files modified:** `src/sift/render/perfmon_report.py`
- **Commit:** `018d383`

### Test-authoring corrections (mine, caught by RED)

- `test_markdown_renders_group_sections` initially asserted a raw `non_overlap`; `_field` correctly Markdown-escapes the underscore to `non\_overlap`. Assertion changed to the hazard message and its event_id — the escaping is right, the assertion was wrong.
- `test_markdown_empty_analysis_states_full_range` compared a mixed-case needle against a lowered haystack. Needle lowercased.
- The bidi-override constant was written as a raw byte and replaced with the ``\u202e`` escape, per the plan's requirement that hazardous characters never appear literally in test source.

## Fail-fast verification

All six CSV tests passed on first run. Per the plan's fail-fast clause, `_csv_safe` was temporarily reduced to `return value`; `test_csv_formula_guard` failed on the missing apostrophe as expected. The file was restored from a byte-identical copy and the suite re-confirmed green — `git diff --stat` showed +87 insertions only (the new code), no incidental change.

## Requirements

PERF-06 is **not** marked complete. This plan delivers the renderer half only; the user-visible `sift perfmon` capability lands in plan 13-06. PERF-04/05/06 left In Progress.

## Verification

- `uv run pytest tests/test_perfmon_report.py -q` — 15 tests pass (5 markdown, 4 JSON, 6 CSV)
- `uv run ruff check` — All checks passed
- `uv run pyright` — 0 errors, 0 warnings, 0 informations
- `uv run pytest` — 616 passed, 8 deselected

## Self-Check: PASSED

- `src/sift/render/perfmon_report.py` — FOUND
- `tests/test_perfmon_report.py` — FOUND
- Commits `5c75a8a`, `2cd69ae`, `dcb10d3`, `7becadc`, `5a88d31`, `018d383` — all FOUND in `git log`
