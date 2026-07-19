---
phase: 06-renderers-kb-retrieval
plan: 01
subsystem: reporting
tags: [markdown, renderer, evidence-appendix, cli, typer, sqlite, sanitisation]

# Dependency graph
requires:
  - phase: 04-inference-hypotheses
    provides: persisted hypotheses (query_hypotheses) + triage_* run-meta the report reads
  - phase: 03-clustering
    provides: clusters table (query_clusters) + eager persisted labels
  - phase: 02-case-store
    provides: CaseStore, _decode_raw single raw path, _EVENT_COLUMNS
provides:
  - "src/sift/render/ package (pure store->str renderers; no HTTP)"
  - "render_markdown: self-contained Markdown triage report with all D-05 sections"
  - "store.get_events_by_ids: confined cited-only raw+provenance reader (no whole-case decompress)"
  - "real `sift report` command (md now; json/pdf lazy dispatch for 06-02/06-05)"
  - "render._util.sanitise (shared) + PdfExtraMissing"
  - "ADR 0007 report exit-code contract (0/1/2)"
  - "tests/_report_fixtures.build_analysed_case (network-free analysed case, reused by 06-02)"
affects: [06-02-json-renderer, 06-05-pdf-renderer, 06-03-kb-retrieval, 06-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Renderer = pure function of the store (no client constructed, zero-egress obvious)"
    - "Shared render/_util.sanitise imported back into cli as _sanitise (no cli<->render cycle)"
    - "StrEnum CLI option so a bad --format is a Typer usage error (exit 2) for free"
    - "Fence-length hardening: appendix raw fenced in a backtick run longer than any it contains"

key-files:
  created:
    - src/sift/render/__init__.py
    - src/sift/render/_util.py
    - src/sift/render/markdown.py
    - docs/decisions/0007-report-exit-codes.md
    - tests/_report_fixtures.py
    - tests/test_render_markdown.py
    - tests/test_cli_report.py
  modified:
    - src/sift/store.py
    - src/sift/cli.py
    - pyproject.toml

key-decisions:
  - "Degraded case renders and exits 0 — banner + FLAGGED communicate degradation, exit 3 not propagated from report (ADR 0007, RESEARCH Open Q3)"
  - "Fixture runs the real analyze path for clusters/meta then plants hypotheses+triage-meta directly, for deterministic control over cited/FLAGGED/degraded state"
  - "Appendix raw byte cap is a public module constant RAW_BYTE_CAP (default 2048), tested at the boundary"

patterns-established:
  - "Pattern 1: renderers take an open CaseStore and return str; never touch the network"
  - "Pattern 2: [evt:id] rewritten to #evt-id anchor only for in-appendix ids (no dangling link)"

requirements-completed: [REPT-01]

coverage:
  - id: D1
    description: "sift report renders a Markdown report containing every D-05 section (exec summary, ranked hypotheses, evidence appendix, cluster inventory, timeline, unexplained signals, run metadata)"
    requirement: "REPT-01"
    verification:
      - kind: unit
        ref: "tests/test_render_markdown.py#test_report_contains_every_d05_section"
        status: pass
      - kind: unit
        ref: "tests/test_cli_report.py#test_report_md_prints_report_and_exits_zero"
        status: pass
    human_judgment: false
  - id: D2
    description: "Inline [evt:id] for a stored, cited id becomes an anchor link to an appendix entry carrying an explicit <a id=\"evt-id\"> anchor; a cited id not in the store stays plain text (no dangling link)"
    requirement: "REPT-01"
    verification:
      - kind: unit
        ref: "tests/test_render_markdown.py#test_in_appendix_cited_id_becomes_anchor_link"
        status: pass
      - kind: unit
        ref: "tests/test_render_markdown.py#test_cited_id_not_in_store_stays_plain_text"
        status: pass
    human_judgment: false
  - id: D3
    description: "Appendix entry shows source_file:line_start-line_end provenance + raw fenced in a code block, truncated to RAW_BYTE_CAP with an elision marker beyond it (verbatim at the cap)"
    requirement: "REPT-01"
    verification:
      - kind: unit
        ref: "tests/test_render_markdown.py#test_appendix_shows_provenance_and_fenced_raw"
        status: pass
      - kind: unit
        ref: "tests/test_render_markdown.py#test_appendix_raw_truncation_boundary"
        status: pass
    human_judgment: false
  - id: D4
    description: "Degraded run shows the DEGRADED banner and FLAGGED rows surfaced from persisted citations_valid (never recomputed); a FLAGGED row citing an absent id renders it plain, never a broken link"
    requirement: "REPT-01"
    verification:
      - kind: unit
        ref: "tests/test_render_markdown.py#test_degraded_run_shows_banner_and_flagged_marker"
        status: pass
    human_judgment: false
  - id: D5
    description: "store.get_events_by_ids returns only requested rows with raw decoded via _decode_raw; empty ids returns {} without a query; never hydrates the whole case"
    requirement: "REPT-01"
    verification:
      - kind: unit
        ref: "tests/test_render_markdown.py#test_appendix_truncates_oversized_raw_with_elision"
        status: pass
    human_judgment: false
  - id: D6
    description: "sift report exit-code contract: 0 (rendered incl. degraded), 1 (no hypotheses / absent case), 2 (bad --format usage); --out writes the file and prints nothing"
    requirement: "REPT-01"
    verification:
      - kind: unit
        ref: "tests/test_cli_report.py#test_report_no_hypotheses_exits_one"
        status: pass
      - kind: unit
        ref: "tests/test_cli_report.py#test_report_absent_case_exits_one"
        status: pass
      - kind: unit
        ref: "tests/test_cli_report.py#test_report_bad_format_is_usage_exit_two"
        status: pass
      - kind: unit
        ref: "tests/test_cli_report.py#test_report_out_writes_file_and_prints_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_cli_report.py#test_report_degraded_case_exits_zero"
        status: pass
    human_judgment: false

# Metrics
duration: 40min
completed: 2026-07-18
status: complete
---

# Phase 6 Plan 01: Markdown Report Core Summary

**`sift report` renders a self-contained Markdown triage report — every `[evt:…]` citation links to an evidence appendix with file:line provenance and fenced raw, degraded banner + FLAGGED rows surfaced from the persisted verdict — as a pure, network-free function of `case.db`.**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-07-18
- **Tasks:** 3 (RED → GREEN → refine/ADR)
- **Files modified:** 10 (7 created, 3 modified)

## Accomplishments
- New `src/sift/render/` package: shared `sanitise` + `PdfExtraMissing` in `_util`, and `render_markdown` — a pure `CaseStore -> str` builder with all seven D-05 sections.
- Evidence appendix: `[evt:id]` narrative tokens rewritten to `#evt-id` anchor links only for ids present in the appendix (no dangling links); each entry carries an explicit `<a id="evt-id">`, `source_file:line-line` provenance, and fence-hardened raw truncated to `RAW_BYTE_CAP` with an elision marker.
- `store.get_events_by_ids`: confined `?`-bound `IN (...)` reader decoding raw via the single `_decode_raw` path — the whole case is never decompressed for a report (Pitfall 1).
- Real `sift report` command replacing the stub: `--format` (StrEnum) md now, json/pdf via lazy import (06-02/06-05), `--out` or stdout, exits per ADR 0007; constructs no `InferenceClient` (zero-egress).
- Network-free `build_analysed_case` fixture (reused by 06-02) and 13 report tests; ADR 0007 records the report exit-code contract.

## Task Commits

1. **Task 1: RED — fixture + failing Markdown & CLI report tests** — `3ea96ad` (test)
2. **Task 2: GREEN — get_events_by_ids, render package, render_markdown, real `sift report`** — `aea4ef1` (feat)
3. **Task 3: refine citation/appendix edges + ADR 0007** — `4f63587` (docs/test)

## Files Created/Modified
- `src/sift/render/__init__.py` — package doc (renderers are pure store functions).
- `src/sift/render/_util.py` — `sanitise` (relocated verbatim from cli) + `PdfExtraMissing`.
- `src/sift/render/markdown.py` — `render_markdown`, `_link_citations`, `_fence`, `_truncate_raw`, `RAW_BYTE_CAP`.
- `src/sift/store.py` — `get_events_by_ids` confined reader; `Sequence` import.
- `src/sift/cli.py` — `_sanitise` now imported from `render._util`; `unicodedata` import dropped; real `report` command + `ReportFormat` StrEnum.
- `docs/decisions/0007-report-exit-codes.md` — 0/1/2 contract, contrasts ADR 0005.
- `tests/_report_fixtures.py` — `build_analysed_case` (+ REAL_ID/MISSING_ID/open_case helpers).
- `tests/test_render_markdown.py`, `tests/test_cli_report.py` — 13 tests.
- `pyproject.toml` — pyright execution env for `tests/` so the shared bare import resolves.

## Decisions Made
- **Degraded → exit 0** (ADR 0007): report of a degraded case still rendered; degradation is in the document, not the code. Distinct from analyze's 0/3/1/2.
- **Fixture strategy:** run the real analyze path for real clusters + embedding meta, then plant hypotheses + `triage_*` meta directly via the store API — full deterministic control of cited/FLAGGED/degraded state without fighting the citation gate. The renderer under test only ever reads the store.
- **Fence hardening:** appendix raw is fenced with a backtick run longer than any it contains, so hostile log bytes cannot break out of the code block (T-06-01).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pyright execution env for the shared test helper**
- **Found during:** Task 1 (RED)
- **Issue:** `tests/` is not a package; pytest prepend mode makes `import _report_fixtures` work at runtime, but pyright (strict, `include=["tests"]`) could not resolve the bare import.
- **Fix:** Added a `[[tool.pyright.executionEnvironments]]` block rooted at `tests` (mirrors the existing `tests/perf` one). `pyproject.toml` was not in the plan's `files_modified`, but the shared fixture the plan mandates cannot be imported without it.
- **Verification:** `uv run pyright` 0 errors; tests collect and run.
- **Committed in:** `3ea96ad`

**2. [Rule 3 - Blocking] StrEnum instead of `str, Enum`; type: ignore on lazy renderer imports**
- **Found during:** Task 2 (GREEN, gate)
- **Issue:** ruff UP042 forbids `class(str, Enum)`; and the json/pdf renderers (06-02/06-05) do not exist yet, so pyright flagged the lazy imports.
- **Fix:** Used `enum.StrEnum` (py3.12); marked the two forward lazy imports `# type: ignore` (documented as delivered in later plans).
- **Verification:** `uv run ruff check` + `uv run pyright` clean.
- **Committed in:** `aea4ef1`

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking). **Impact:** No scope creep — both were required to make the plan's own artefacts (shared fixture, lazy json/pdf dispatch) type-check and lint cleanly.

## Issues Encountered
- Fixture import path: `from tests._report_fixtures` fails (no `tests` package); resolved to the bare `from _report_fixtures import …` that pytest prepend mode and the perf-env precedent use.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `build_analysed_case` and `store.get_events_by_ids` are ready for 06-02 (JSON renderer) and 06-05 (PDF), which slot into the existing `sift report` lazy-import branches.
- `render_markdown` output is the reuse seam for the PDF path (markdown → HTML → WeasyPrint).
- Quality gate green: `uv run ruff check`, `uv run pyright` (0 errors), `uv run pytest` (391 passed, 2 deselected).

## Self-Check: PASSED

All 7 created files + SUMMARY exist on disk; all 3 task commits (`3ea96ad`, `aea4ef1`, `4f63587`) present in git log.

---
*Phase: 06-renderers-kb-retrieval*
*Completed: 2026-07-18*
