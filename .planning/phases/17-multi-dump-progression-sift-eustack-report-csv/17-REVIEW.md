---
phase: 17-multi-dump-progression-sift-eustack-report-csv
reviewed: 2026-07-26T00:00:00Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - src/sift/cli.py
  - src/sift/pipeline/eustack_progression.py
  - src/sift/render/eustack_report.py
  - tests/fixtures/eustack/progression/derive_progression_fixtures.py
  - tests/test_cli_eustack.py
  - tests/test_eustack_progression.py
  - tests/test_eustack_report.py
findings:
  critical: 2
  warning: 2
  info: 0
  total: 4
status: issues_found
---

# Phase 17: Code Review Report

**Reviewed:** 2026-07-26T00:00:00Z
**Depth:** deep
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the full `sift eustack` surface added in Phase 17: the new
`pipeline/eustack_progression.py` leaf module (dump grouping, D-01/D-02
ordering, D-08/D-09 delta computation), the new `render/eustack_report.py`
(Markdown/JSON/CSV renderers), the `eustack` CLI command in `cli.py`, and the
whole test/fixture set. Ruff and pyright are both clean on the touched files,
and the great majority of the phase's own locked decisions (D-01–D-13) are
implemented and tested correctly, including the D-02 fallback flag, the
D-07 matched/leaf-frame projection, the D-10 ownership-blind/population-only
vocabulary gates, and D-13 byte-identical re-runs.

Two BLOCKER-tier defects were found and independently reproduced against the
actual code (not just read):

1. `resolve_dump_order` crashes with an unhandled `StopIteration` for any
   2+-dump case where at least one dump has zero thread-bearing events —
   confirmed with a runnable repro. The sibling code 130 lines later handles
   exactly this same condition defensively, showing this is an oversight,
   not a design choice.
2. The CSV `step_deltas` cell bypasses the mandated `_csv_safe` formula-
   injection guard and is written to disk as a raw string that can (and, in
   the shipped test fixtures, already does) start with the project's own
   declared formula-trigger character `-`. Confirmed against the actual
   fixture set: the `departing` signature's `step_deltas` cell is literally
   `-2;0`, unguarded, in `eustack_signatures.csv` today.

Two WARNING-tier quality issues were also found: loose `tuple[object, ...]`
typing with `# type: ignore[attr-defined]` sprinkled through the saturation
sub-tables (new to this phase, not the sibling renderers' precedent), and a
demonstrated mismatch between the CLI/Role-composition "signature count"
(last-dump-only) and the row count actually rendered in the `## Signatures`
table (all-dump union), with no scope note explaining the difference.

## Critical Issues

### CR-01: `resolve_dump_order` crashes on a dump with zero thread events

**File:** `src/sift/pipeline/eustack_progression.py:193-196`
**Issue:**

```python
representatives = {
    key: next(e for e in events if e.thread is not None)
    for key, events in dumps.items()
}
```

`next()` is called here with no default. If any dump group in a case with
2+ dumps has **no** event with `.thread is not None` — e.g. a truncated or
failed eu-stack capture consisting only of preamble/header text, or any
file an operator routes to the `eustack` adapter via `--adapter glob=name`
that doesn't happen to contain a `TID <n>:` line — `next()` raises
`StopIteration`, which is **not** caught anywhere on this path (the
`analyse_eustack_bundle` → CLI `eustack` command's `try/except OSError`
block only wraps the file-write step, which runs *after* this call). The
result is an unhandled exception surfacing as a raw traceback instead of the
command's documented exit-code contract ("0 = bundle written (including an
empty case), 1 = missing case / write failure, 2 = Typer usage").

Reproduced directly:

```
$ uv run python -c "
from datetime import datetime, timezone
from sift.models import Event
from sift.pipeline.eustack_progression import resolve_dump_order

def ev(source_file, thread, ts=None, ts_conf='missing'):
    return Event(event_id='0'*16, case_id='c', ts=ts, ts_confidence=ts_conf,
        source='eustack', source_file=source_file, line_start=1, line_end=1,
        severity='unknown', component=None, thread=thread, session=None,
        message='', attrs={}, raw='')

dumps = {
    'dump_good.txt': [ev('dump_good.txt', '1', datetime(2026,1,1,tzinfo=timezone.utc), 'exact')],
    'dump_empty.txt': [ev('dump_empty.txt', None)],  # preamble-only dump
}
resolve_dump_order(dumps)
"
CRASHED: StopIteration
```

Note that `analyse_eustack_bundle`'s own `dump_slices` construction, 130
lines later in the same file, defensively handles exactly this case:
`representative = next((e for e in dump_events if e.thread is not None), None)`.
This confirms the omission in `resolve_dump_order` is an inconsistency, not
an intentional invariant ("every dump has at least one thread").

No test in `tests/test_eustack_progression.py` or `tests/test_cli_eustack.py`
constructs a threadless dump among 2+ dumps, so this path is currently
unexercised by the suite.

**Fix:** Mirror the guarded pattern already used in `analyse_eustack_bundle`:

```python
representatives = {
    key: next((e for e in events if e.thread is not None), None)
    for key, events in dumps.items()
}
if all(
    representatives[key] is not None
    and representatives[key].ts_confidence != "missing"
    for key in keys
):
    ...
```

A `None` representative should be treated the same as `ts_confidence ==
"missing"` — it forces the D-02 filename-fallback path (with its loud flag)
rather than crashing. Add a regression test with a threadless dump among
2+ dumps to `tests/test_eustack_progression.py`.

### CR-02: CSV `step_deltas` cell bypasses the formula-injection guard

**File:** `src/sift/render/eustack_report.py:376`
**Issue:** `write_eustack_signatures_csv` guards every other string cell
through `_csv_safe` (D-06), but `step_deltas` is written raw:

```python
row: list[object] = [
    _csv_safe(s.role),
    ...
    thread_count,
    *s.counts,
    ";".join(str(d) for d in s.step_deltas),   # <-- not passed through _csv_safe
    s.overall_delta,
]
```

`_FORMULA_TRIGGERS = ("=", "+", "-", "@")` (`render/perfmon_report.py:78`) is
this project's own definition of a formula-triggering leading character, and
`_csv_safe`'s whole design point (per its own docstring) is to test only the
*first significant character* of a string cell, not whether the full content
happens to parse as a valid formula. `step_deltas` is exactly the kind of
semicolon-joined string cell the perfmon precedent
(`boundaries = _csv_safe(";".join(g.boundary_event_ids))`,
`render/perfmon_report.py:257`) wraps for this reason — but the eustack
writer's equivalent field was not.

This is not a hypothetical: any signature whose first step is a population
decrease produces a cell starting with `-`, and this already happens in the
committed fixture set. Reproduced against the real `progression/` fixtures:

```
$ uv run python -c "... write_eustack_signatures_csv(bundle, p) ..."
'idle-parked,command-queue,MSICommandQTask::GetNextCommand,1,,MSICommandQTask::GetNextCommand,pthread_cond_wait,0,2,0,0,-2;0,-2'
```

The `departing` signature's `step_deltas` cell is literally `-2;0` on disk,
unguarded, sitting in the same row as `_csv_safe`-guarded cells. The
CLAUDE.md-level invariant is explicit: "CSV output must be proof against
formula injection." Although the current values can only ever be digits,
semicolons and a leading `-` (no external attacker-controlled text can
reach this specific field today), the guard's entire purpose is to be
correct regardless of what the *current* data happens to look like — the
module's own docstring already (incorrectly) claims full coverage: "Every
string cell carrying C++ symbol text goes through the existing `_csv_safe`
guard." `step_deltas` is a string cell that was missed.

**Fix:**

```python
";".join(str(d) for d in s.step_deltas)
```
→
```python
_csv_safe(";".join(str(d) for d in s.step_deltas))
```

Add a test asserting a negative-leading `step_deltas` cell is quoted (the
existing `test_csv_safe_guards_formula_trigger_symbol` only exercises
`leaf_frame`/`matched_frame`/`overall_delta`, not `step_deltas`).

## Warnings

### WR-01: Saturation sub-table renderers use `tuple[object, ...]` + blanket `type: ignore[attr-defined]` instead of the real model types

**File:** `src/sift/render/eustack_report.py:203-269` (`_pool_table`,
`_lock_table`, `_dependency_table`, `_flag_table`)
**Issue:** These four new functions type their inputs as `tuple[object,
...]` and then access `.subsystem`, `.total_threads`, `.idle_threads`,
`.busy_threads`, `.occupancy`, `.signature_count`, `.site`, `.thread_count`,
`.value`, `.warn`, `.critical`, `.message`, `.dimension`, `.severity` —
each suppressed with `# type: ignore[attr-defined]`. The real types
(`PoolOccupancy`, `LockSite`, `DependencyWait`, `SaturationFlag`) already
exist and are exported from `sift.pipeline.eustack`
(`src/sift/pipeline/eustack.py:524,546,566,486`); nothing prevented
importing them under `TYPE_CHECKING` alongside the `Role`/`SaturationAnalysis`
imports already present at the top of the file. This pattern is new to this
phase — it does not appear anywhere in the sibling `perfmon_report.py` or
`mcm_report.py` renderers these functions were explicitly modelled on, which
type their table-row parameters concretely.

Pyright is currently clean only because every attribute access is
individually silenced; a future rename or typo on any of these ~13 attribute
accesses will not be caught by the type checker (CLAUDE.md: "Type hints
everywhere... pyright... part of the 'done' gate").

**Fix:** Import the concrete types under `TYPE_CHECKING` and drop the
`object`/`type: ignore` pairs, e.g.:

```python
if TYPE_CHECKING:
    from sift.pipeline.eustack import (
        DependencyWait, LockSite, PoolOccupancy, Role, SaturationAnalysis, SaturationFlag,
    )

def _pool_table(pools: tuple[PoolOccupancy, ...]) -> list[str]:
    ...
```

### WR-02: `## Signatures` table row count silently diverges from the reported "signature" count, with no scope note

**File:** `src/sift/render/eustack_report.py:281-306,309-334`
**Issue:** `render_eustack_markdown` places `## Signatures`
(`_signature_table(progression.signatures)`) directly beneath `## Role
composition` and `## Saturation`, both of which are explicitly scoped to
the LAST dump only (D-11). `progression.signatures`, however, is the
all-dump **union** built by `compute_progression` (deliberately, for the
CSV's D-04/D-09 "no cap, keep vanished signatures" requirement) — it
includes signatures with `thread_count == 0` in the last dump. Nothing in
the "## Signatures" heading or its table distinguishes this cross-dump scope
from the last-dump scope of the two sections immediately above it, and the
CLI's own stdout summary line (`cli.py:1395-1401`,
`f"Analysed {n_dumps} eu-stack {dump_plural}, {n_signatures} {sig_plural}"`)
uses `bundle.analysis.total_signatures` — the LAST-dump-only count — which
is a different, smaller number than the row count the reader will see in
the written report's `## Signatures` table.

Reproduced against the 3-dump `progression/` fixture set: CLI would report
`total_signatures = 4`, while `## Signatures` renders **5** rows (the
vanished `departing` signature appears with `thread_count = 0`, sourced
from an earlier dump's classification per `compute_progression`'s own
documented "last dump where it appears" rule). An engineer skimming the
stdout summary and then the report has no textual cue that the table below
"Role composition"/"Saturation" is not scoped the same way those two
sections are.

**Fix:** Either (a) add a one-line scope note above `_signature_table`
analogous to `_progression_table`'s `scope_note` line, explicitly stating
the table spans every dump the case holds and may include zero-count
(vanished) signatures, or (b) scope `## Signatures` to
`bundle.analysis.signatures` (last-dump-only, matching the sections around
it) and rely on the CSV/`## Progression` section alone for the cross-dump
union, matching the "Total signatures" figure exactly.

---

_Reviewed: 2026-07-26T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
