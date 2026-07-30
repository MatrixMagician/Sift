---
phase: 17-multi-dump-progression-sift-eustack-report-csv
fixed_at: 2026-07-26T09:06:05Z
review_path: .planning/phases/17-multi-dump-progression-sift-eustack-report-csv/17-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 17: Code Review Fix Report

**Fixed at:** 2026-07-26T09:06:05Z
**Source review:** .planning/phases/17-multi-dump-progression-sift-eustack-report-csv/17-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (2 Critical, 2 Warning; fix_scope: critical_warning)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: `resolve_dump_order` crashes on a dump with zero thread events

**Files modified:** `src/sift/pipeline/eustack_progression.py`, `tests/test_eustack_progression.py`
**Commits:** `e1dd92b` (RED regression test), `5134e9c` (GREEN fix)
**Applied fix:** Reproduced the reviewer's exact repro first (confirmed `StopIteration`
against unpatched code), then added
`test_order_resolves_without_crash_when_a_dump_has_no_thread_events` (calls
`resolve_dump_order` directly with a hand-built threadless dump, mirroring the review's own
repro shape) and committed it RED. Applied the fix: `next(...)` now takes a `None` default,
and a `timestamped` dict comprehension replaces the bare `all(representatives[key]...)` check
so a `None` representative is filtered out (and therefore treated the same as
`ts_confidence == "missing"`) without any runtime `AttributeError` on `None.ts_confidence` —
this mirrors the already-guarded pattern in `analyse_eustack_bundle`'s `dump_slices`
construction 130 lines below, per the review's own precedent citation. Confirmed the new test
was RED before the fix and GREEN after; full `tests/test_eustack_progression.py` +
`tests/test_cli_eustack.py` (24 tests) pass; ruff and pyright clean on both files.

### CR-02: CSV `step_deltas` cell bypasses the formula-injection guard

**Files modified:** `src/sift/render/eustack_report.py`, `tests/test_eustack_report.py`
**Commits:** `6e9d915` (RED regression test), `3c287ff` (GREEN fix)
**Applied fix:** Extended the existing `test_csv_safe_guards_formula_trigger_symbol` test
(rather than adding a parallel one, since it already builds the exact dumpA→dumpB(count 5→2)
scenario that produces a negative `step_deltas` cell) with an assertion that the rendered
`step_deltas` cell is quoted (`'-3`), confirmed it failed against the unpatched code (RED:
`'-3' == "'-3"` assertion mismatch, got unguarded `'-3'` without the leading quote), then wrapped
`";".join(str(d) for d in s.step_deltas)` in `_csv_safe(...)` in
`write_eustack_signatures_csv` — the same guard already applied to every other string cell in
that row, per D-06 and the `perfmon_report.py:257` precedent the review cited. `overall_delta`
stays a bare unguarded `int` (unchanged), consistent with the module's own documented
numeric-cells-never-guarded discipline. 12→13 tests in `tests/test_eustack_report.py` pass;
ruff and pyright clean.

### WR-01: Saturation sub-table renderers use `tuple[object, ...]` + blanket `type: ignore[attr-defined]`

**Files modified:** `src/sift/render/eustack_report.py`
**Commit:** `6d62bb4`
**Applied fix:** Imported `DependencyWait`, `LockSite`, `PoolOccupancy`, `SaturationFlag` from
`sift.pipeline.eustack` under the existing `TYPE_CHECKING` block (alongside `Role`/
`SaturationAnalysis`, already imported there) and retyped `_pool_table`, `_lock_table`,
`_dependency_table`, `_flag_table` from `tuple[object, ...]` to the concrete tuple types,
dropping all nine `# type: ignore[attr-defined]` suppressions across the four functions. This
is a pure type-tightening change with no behavioural difference — no regression test was added
(there is no observable runtime behaviour to regress; pyright itself is the verification tool
here). Per the verification_strategy logic-bug caveat, this is not a logic-error finding, so it
is recorded as plain `fixed`, not `fixed: requires human verification`. Confirmed `pyright
src/sift/render/eustack_report.py` reports `0 errors, 0 warnings, 0 informations` after the
change (previously clean only via the blanket suppressions), and all 12
`tests/test_eustack_report.py` tests still pass unchanged; ruff clean.

### WR-02: `## Signatures` table row count silently diverges from the reported "signature" count

**Files modified:** `src/sift/render/eustack_report.py`, `tests/test_eustack_report.py`
**Commit:** `79a5ef1`
**Applied fix:** Chose option (a) from the review's fix suggestion (a scope note, not
re-scoping the table to last-dump-only — preserves the D-04/D-09 CSV-matching union the table
was deliberately designed to carry). Added a `_SIGNATURES_SCOPE_NOTE` constant (mirroring
`ProgressionAnalysis.scope_note`'s house style) rendered immediately below the `## Signatures`
heading, stating the table spans every dump the case holds (including zero-count vanished
signatures) and is a wider scope than the last-dump-only "Total signatures" figure in
`## Role composition` above it. Added
`test_signatures_table_carries_scope_note_and_can_outnumber_total_signatures`, which
reproduces the review's own numbers on the charlie/bravo/alpha fixture trio
(`total_signatures == 4`, `## Signatures` row count `== 5`, the extra row being the vanished
`departing` signature) and asserts the scope note text is present. Confirmed RED by
`git stash`-ing the render-file fix only and re-running the new test in isolation (failed on
the scope-note assertion exactly as expected, with the row-count/figure assertions already
passing since those describe pre-existing, correct behaviour); restored the fix and confirmed
GREEN. 12→13 tests in `tests/test_eustack_report.py` pass; ruff and pyright clean. The new
scope-note text was checked against the D-10 vocabulary gate (no continuity verb, no TID value
token — 17-02-SUMMARY.md's documented scope) and contains neither.

## Skipped Issues

None — all four in-scope findings were fixed.

## Full-suite verification (after all four fixes)

- `uv run pytest` — 779 passed (baseline before this pass: 777; net +2 new tests — CR-01's and
  WR-02's regressions; CR-02's assertion was added to an existing test, not a new one)
- `uv run ruff check src/sift tests` — clean
- `uv run pyright src/sift` — 0 errors, 0 warnings, 0 informations

## Worktree isolation notes

This fix pass ran in an isolated git worktree (`gsd-reviewfix/17-1270710` branch, per #2686/
#2990/#2839) to avoid racing the foreground session's checkout of
`gsd/v1.3-eu-stack-hang-slowdown-diagnosis`. All six commits above (two RED, four GREEN/fix)
were made inside that worktree, then the cleanup tail fast-forward-merged the temp branch into
`gsd/v1.3-eu-stack-hang-slowdown-diagnosis`, removed the worktree, deleted the temp branch, and
removed the recovery sentinel — all four steps completed cleanly with no orphaned state.

---

_Fixed: 2026-07-26T09:06:05Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
