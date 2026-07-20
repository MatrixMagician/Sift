---
finding: WR-03
title: perfmon samples that lost their timestamp vanish from the report with no hazard
severity: warning
status: fixed
review_path: 13-REVIEW.md
fixed_at: 2026-07-20
renderer_changed: false
gate: green
tests_before: 636
tests_after: 638
commits:
  - b4d4894  # test(13): WR-03 RED — untimestamped file must disclose, not vanish
  - c729912  # fix(13): WR-03 GREEN — disclose all-untimestamped perfmon files
  - e5b7528  # test(13): WR-03 RED — mixed-file group must disclose unplaceable samples
  - 939087d  # fix(13): WR-03 GREEN — mixed-file group discloses unplaceable samples + renderer test
---

# WR-03 Fix Report

**Finding:** perfmon samples that lost their timestamp vanish from the report
with no hazard, violating the load-bearing "nothing disappears silently"
invariant. Scoped (per orchestrator decision) to `_file_scope_groups` — the D-20
no-episodes path — in `src/sift/pipeline/perfmon.py`. Fix strategy: **disclose,
don't drop**.

## What changed

`src/sift/pipeline/perfmon.py`
- New info-severity dimension constant `HAZARD_UNPLACEABLE_SAMPLES = "unplaceable_samples"`.
- New label constant `NO_PLACEABLE_LABEL` for the all-untimestamped file case.
- New helper `_hazard_unplaceable_samples(unplaceable: list[Event]) -> PerfmonHazard | None`:
  returns `None` on an empty list, else an `info` hazard naming the count of
  samples with no placeable timestamp and citing up to `_CITE_CAP` of their
  `event_id`s, sorted deterministically by `event_id` (mirrors the
  `_hazard_counter_set_drift` / `_cited` citation pattern).
- `_file_scope_groups`:
  - Computes `unplaceable = [s for s in samples if s.ts is None]` per file.
  - **Case A (some placeable):** the file's normal full-range group now carries
    the unplaceable-samples hazard (after drift, fixed code order for D-21)
    alongside the existing counter-set-drift hazard.
  - **Case B (all unplaceable):** the old silent `continue` is replaced with a
    boundless disclosure group — `scope="file"`, `key=source_file`,
    `label=NO_PLACEABLE_LABEL`, `start_ts=None`, `end_ts=None`,
    `boundary_event_ids=()`, `sample_count=0`, `counters=()`,
    `hazards=(the unplaceable hazard,)`.
  - The empty-`placeable` guard stays **load-bearing**: the Case-B branch never
    indexes `placeable[0]`/`[-1]`, so removing `if not placeable` still raises
    IndexError on an all-untimestamped file.
  - Docstring updated to state the disclosure behaviour and cite WR-03.

## No model changes

`TrendGroup.start_ts`/`end_ts` were already `str | None` and
`boundary_event_ids` a variable-length tuple, so no schema change was needed.
`PerfmonHazard` carries no `scope` field — scope lives on `TrendGroup`; the
brief's "(scope=file)" describes the group context, not a hazard field.

## Renderer

**No change required.** `render_perfmon_report._group_section` already tolerates
`start_ts is None` (renders the absent marker `—`, line 159), empty counters
(`_counter_table` prints "_No counters carried samples in this span._"), and an
empty `boundary_event_ids` (`', '.join(())` → `''`). A characterisation test
(`test_markdown_renders_unplaceable_disclosure_group`) locks this in: the Case-B
group renders cleanly with no literal `None`.

## Tests

- Rewrote the frozen `test_no_episodes_untimestamped_file_yields_no_group` →
  `test_no_episodes_untimestamped_file_yields_disclosure_group`: asserts the file
  yields exactly ONE group with `sample_count == 0`, `start_ts is None`,
  `counters == ()`, `boundary_event_ids == ()`, and one `unplaceable_samples`
  info hazard citing the sample. Docstring documents the empty-guard is still
  load-bearing.
- Added `test_no_episodes_mixed_file_group_discloses_unplaceable` (Case A): a
  no-episodes file with 20 placeable samples plus one untimestamped sample →
  group keeps `sample_count == 20` and carries the `unplaceable_samples` hazard
  with `value == 1.0` citing the undated event.
- Added `test_markdown_renders_unplaceable_disclosure_group` (renderer, Case B).

## Verification

TDD strict RED→GREEN atomic pairs. After each pair the full gate ran clean:
`uv run ruff check` (All checks passed), `uv run pyright` (0 errors),
`uv run pytest` (638 passed, 8 deselected — up from 636). Both RED commits were
confirmed failing before their GREEN fix (pair 1: ImportError on the missing
constant; pair 2: `assert 0 == 1` on the absent Case-A hazard).

## Out of scope (deliberately not implemented)

Unplaceable samples when MCM episodes ARE present — there is no window to
attribute them to, and a case-level channel is something `PerfmonAnalysis`
deliberately forbids (every hazard attributable to exactly one span). Left for
the orchestrator to file as a todo.
