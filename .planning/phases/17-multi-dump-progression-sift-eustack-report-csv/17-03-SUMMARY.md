---
phase: 17-multi-dump-progression-sift-eustack-report-csv
plan: 03
subsystem: render
tags: [pydantic, markdown, csv, eustack, mcm-perfmon-pattern]

requires:
  - phase: 17-multi-dump-progression-sift-eustack-report-csv (plan 01)
    provides: "render/eustack_report.py three-function shape (markdown/json/csv), sift eustack CLI wiring, EUSTACK_CSV_BASE_HEADER"
  - phase: 17-multi-dump-progression-sift-eustack-report-csv (plan 02)
    provides: "SignatureProgression.counts/step_deltas/overall_delta/appeared/vanished, resolve_dump_order's full D-01/D-02 basis strings, compute_progression"
provides:
  - "_progression_table — the D-09 changed-only Markdown progression section, appeared/vanished status, D-10 scope_note rendered immediately above it"
  - "_eustack_csv_header/_dumps_section — D-05 per-dump CSV columns named for their source file, D-01/D-02 ordering basis and flags rendered as a dumps table"
  - "changed_signature_count — shared by the CLI stdout summary and the renderer so the two can never diverge"
  - "Two render-level honesty gates: D-13 ownership-blind vocabulary and D-10 population-only phrasing, both asserted over rendered Markdown/JSON/CSV with non-vacuity guards"
affects: []

tech-stack:
  added: []
  patterns:
    - "changed_signature_count as the single D-09 predicate shared between the renderer's own filter and the CLI summary line, closing the divergence class the CSV-header helper (_eustack_csv_header) already closed for header construction"
    - "Markdown table cells reuse the mcm/perfmon _field escaping convention, including the shipped test_cli_perfmon.py HAZARD_NON_OVERLAP.replace('_', r'\\_') technique for asserting against escaped substrings"

key-files:
  created:
    - tests/test_eustack_report.py
  modified:
    - src/sift/render/eustack_report.py
    - src/sift/cli.py
    - tests/test_cli_eustack.py

key-decisions:
  - "_signature_table (the full per-signature listing, unfiltered, last-dump counts) is kept unchanged and rendered alongside the NEW _progression_table (D-09 changed-only) rather than replaced by it — the plan's task text never asked to modify _signature_table, and the two sections answer different questions: '## Signatures' is the classification listing (D-11's last-dump-only view), '## Progression' is the multi-dump delta view"
  - "pipeline.eustack.normalise() always .strip()s a frame body (both its own tail-drop and the shared adapters.eustack._condense_symbol), so a literal leading space before a formula-injection trigger can never survive into a stored SignatureGroup frame through the real ingest path — test_csv_safe_guards_formula_trigger_symbol proves the leading-whitespace-before-a-trigger case directly against the imported _csv_safe function instead, and proves the guard is APPLIED end-to-end via a crafted frame beginning with a bare trigger"
  - "Markdown-rendered assertions in tests/test_eustack_report.py account for _field's WR-04 escaping (backslash before every underscore, HTML-entity '>' inside multi-value cells) — mirrors the shipped test_cli_perfmon.py HAZARD_NON_OVERLAP.replace('_', r'\\_') convention rather than introducing a new escaping-workaround pattern"
  - "Two atomic commits split by task exactly as planned: Task 1 (rendering + widened CSV + CLI summary, 7 tests) then Task 2 (identity projection, formula-injection proof, the two honesty gates, 5 more render tests + 2 CLI tests) — required temporarily reverting/re-applying the Task-2-only portions of tests/test_cli_eustack.py and tests/test_eustack_report.py between commits since both tasks touch the same two files"

patterns-established:
  - "changed_signature_count(progression) -> int is the D-09 predicate; any future caller needing 'how many signatures changed' imports this rather than re-deriving the overall_delta/step_deltas filter"

requirements-completed: [EUS-07, EUS-09]

coverage:
  - id: D1
    description: "The Markdown progression section lists ONLY signatures whose thread count changed, ranked by absolute delta, with appeared/vanished signatures called out; unchanged signatures stay in the CSV (D-09)"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_progression_section_lists_only_changed_signatures"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_report.py#test_csv_keeps_unchanged_signatures"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_report.py#test_progression_section_calls_out_appeared_and_vanished"
        status: pass
    human_judgment: false
  - id: D2
    description: "The report shows both consecutive-pair step deltas and the overall first-to-last delta, so a grew-then-shrank population reads correctly from the report alone (D-08)"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_progression_section_shows_step_and_overall_deltas"
        status: pass
    human_judgment: false
  - id: D3
    description: "Progression is phrased strictly as signature-population change — no per-thread continuity claim or thread-identifier value anywhere in the rendered progression section, on a genuinely non-empty section (D-10)"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_progression_section_is_population_phrased"
        status: pass
    human_judgment: false
  - id: D4
    description: "The report and CSV carry the matched frame (with its index) and the leaf frame — never the full frames tuple, and no signature hash column (D-07)"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_identity_projection_omits_full_frames_tuple"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_report.py#test_identity_projection_has_no_hash_column"
        status: pass
    human_judgment: false
  - id: D5
    description: "The CSV header is the eight base columns, one count column per dump named for that dump's source file (resolved order, never re-sorted), then step_deltas/overall_delta (D-05); the dumps table and ordering flags render the stated D-01/D-02 basis prominently (EUS-08)"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_csv_header_carries_one_column_per_dump"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_report.py#test_order_basis_and_flag_are_rendered"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_report.py#test_dumps_table_and_progression_table_preserve_resolved_order"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every CSV string cell carrying C++ symbol text passes through the imported (never reimplemented) _csv_safe guard, proven against a symbol crafted to begin with a spreadsheet formula trigger; a legitimately negative overall_delta stays a bare numeric cell (D-06, threat T-17-01)"
    requirement: EUS-09
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_csv_safe_guards_formula_trigger_symbol"
        status: pass
    human_judgment: false
  - id: D7
    description: "The forbidden lock-ownership vocabulary appears in no rendered artefact (Markdown, JSON or CSV) of a genuine multi-dump bundle with a real lock finding, and re-running on an unchanged multi-dump case produces byte-identical report and CSV in both formats (D-13)"
    requirement: EUS-09
    verification:
      - kind: unit
        ref: "tests/test_eustack_report.py#test_ownership_blind_vocabulary_absent_from_rendered_bundle"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_multi_dump_byte_identical_rerun"
        status: pass
      - kind: integration
        ref: "tests/test_cli_eustack.py#test_eustack_multi_dump_bundle_reports_progression"
        status: pass
    human_judgment: false

duration: ~50min
completed: 2026-07-26
status: complete
---

# Phase 17 Plan 3: Progression Rendering, Widened CSV & the Phase's Honesty Gates Summary

**`sift eustack` gains a D-09 changed-only Markdown progression section (step + overall deltas, appeared/vanished status) and a D-05 per-dump-column CSV, closing the phase with two render-level gates: D-13 ownership-blind vocabulary and D-10 population-only phrasing, both asserted over rendered output rather than source text.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-07-26
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- `_progression_table` renders the D-09 changed-only signature-population view — role, subsystem, matched frame with its index, leaf frame, per-dump counts, step deltas, overall delta and an appeared/vanished/changed status — with `scope_note` rendered immediately above it and a single-dump case stating plainly that no progression was computed
- `_eustack_csv_header`/widened `write_eustack_signatures_csv` give the CSV one column per dump named for its resolved source file plus the `step_deltas`/`overall_delta` pair, while the unfiltered `_signature_table` and full CSV rows keep every signature including unchanged ones
- `_dumps_section` now renders an index/source-file/timestamp/thread-count table with the D-01/D-02 ordering basis stated on its own line and every ordering flag rendered as a bold-prefixed paragraph so the D-02 unverified-ordering warning cannot be skimmed past
- Two render-level honesty gates close the phase: D-13 ownership-blind vocabulary (read from REQUIREMENTS.md at runtime, word-boundary matched, non-vacuity guarded) and D-10 population-only phrasing, both asserted against a genuine multi-dump bundle's rendered Markdown/JSON/CSV rather than source text
- `sift eustack`'s stdout summary now names the changed-signature count on multi-dump cases via the shared `changed_signature_count` helper
- 12 new tests in `tests/test_eustack_report.py` plus 2 new multi-dump integration tests in `tests/test_cli_eustack.py`; full suite (777 tests), `ruff check`, and `pyright` are all clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Progression section in Markdown and per-dump delta columns in the CSV** - `a332f88` (feat)
2. **Task 2: Identity projection, formula-injection proof, byte-identity and the two honesty gates** - `2f7f90e` (test)

## Files Created/Modified
- `src/sift/render/eustack_report.py` - `EUSTACK_CSV_DELTA_HEADER`, `_eustack_csv_header`, `_is_changed_signature`/`changed_signature_count`, `_matched_frame_with_index`, rewritten `_dumps_section` (table + prominent flags), new `_progression_table`; `write_eustack_signatures_csv` now delegates header construction to `_eustack_csv_header`; `render_eustack_markdown` renders the progression section after the existing signature table
- `src/sift/cli.py` - `eustack` command's stdout summary names the changed-signature count on multi-dump cases, routed through `_sanitise` before `print`
- `tests/test_eustack_report.py` - new module, 12 tests over the synthetic `tests/fixtures/eustack/progression/` trio plus two hand-built multi-dump scenarios (formula-injection/negative-delta, ownership-blind lock convergence)
- `tests/test_cli_eustack.py` - `_build_progression_case` helper plus `test_eustack_multi_dump_byte_identical_rerun` and `test_eustack_multi_dump_bundle_reports_progression`

## Decisions Made
- `_signature_table` (the full, unfiltered per-signature listing already shipped in 17-01) is kept as-is and rendered alongside the new `_progression_table` rather than replaced — they answer different questions (full classification listing vs. multi-dump delta view) and the plan's Task 1 action text never asked to modify it.
- `pipeline.eustack.normalise()` strips leading/trailing whitespace off every frame body on the real ingest path (both its own tail-drop and the shared `adapters.eustack._condense_symbol`), so the D-06 "leading space before a formula trigger" edge case cannot be exercised end-to-end through a parsed fixture. `test_csv_safe_guards_formula_trigger_symbol` proves that sub-case directly against the imported `_csv_safe` function and proves the guard is genuinely applied to eu-stack's own cells via a hand-built signature whose frame begins with a bare trigger.
- Markdown-rendered test assertions account for `_field`'s WR-04 escaping (backslash before underscores; HTML-entity `>`) by mirroring the shipped `test_cli_perfmon.py` `HAZARD_NON_OVERLAP.replace("_", r"\_")` convention rather than inventing a new technique.
- Task 1 and Task 2 both touch `tests/test_eustack_report.py` and (Task 2 only) `tests/test_cli_eustack.py`; committing them atomically per task required writing Task 1's test subset first, committing, then re-adding the Task 2 additions (helpers + tests) before the second commit — both intermediate states were independently verified green (`ruff`, `pyright`, `pytest`) before their commit.

## Deviations from Plan
None - plan executed as written. No auto-fixes were required; the only adjustments were test-construction choices (documented above) necessitated by already-shipped, unrelated pipeline behaviour (`normalise()`'s whitespace stripping), not bugs introduced by this plan.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
Phase 17 is complete: `sift eustack` now renders the full single-dump classification/saturation report and, on 2+ dumps, the D-08/D-09 progression section and D-05 widened CSV, with both phase-closing honesty gates (D-13, D-10) proven over rendered output. Manual verification against a real 3-dump scratch case confirmed the report reads end-to-end: order basis, per-dump thread counts, role composition, saturation tables, the full signature listing, and the changed-only progression table with step/overall deltas and appeared/vanished status. No blockers for Phase 18 (eu-stack facts into `sift analyze`).

---
*Phase: 17-multi-dump-progression-sift-eustack-report-csv*
*Completed: 2026-07-26*

## Self-Check: PASSED

All claimed files exist on disk; both task commits (`a332f88`, `2f7f90e`) present in `git log`.
