---
type: todo
created: 2026-07-20
source: .planning/phases/13-episode-correlation-hazard-flags-sift-perfmon-report-csv/13-REVIEW.md
resolves_phase: 14
status: pending
---

# perfmon: unplaceable samples still vanish when episodes ARE present

Raised by the Phase 13 code review (WR-03) and deliberately deferred during the
`--fix` pass. WR-03's core violation of "nothing disappears silently" was fixed
on the **no-episodes** path only: `_file_scope_groups`
(`src/sift/pipeline/perfmon.py`) now discloses untimestamped perfmon samples via
an `info` `unplaceable_samples` hazard — both when a file has some placeable
samples (hazard appended to its group) and when every sample is untimestamped
(a boundless disclosure group with `sample_count=0`, rather than the old silent
`continue`). Commits `b4d4894` → `939087d`.

## What is still uncovered

When the case **has MCM episodes**, correlation runs through the episode-span
path (`_in_span`), not `_file_scope_groups`. A perfmon sample with `ts is None`
cannot fall inside any `[start.ts, end.ts]` window, so it is filtered out of
every episode group and never disclosed anywhere — the same silent drop, just on
the other branch.

## Why it was deferred, not fixed now

- The honest disclosure channel would be **case-level**, but `PerfmonAnalysis`
  deliberately forbids a case-level hazard collection ("Every hazard is
  attributable to exactly one span, so hazards live on `TrendGroup`; there is
  deliberately no case-level hazard collection"). Fixing this properly means
  either adding that channel (a real model/design change) or attributing
  unplaceable samples to a synthetic per-file group even when episodes exist
  (changes what the episodes-present report contains). Both are design calls,
  not a cleanup pass.
- It is doubly synthetic on real data: it needs untimestamped perfmon rows AND
  detected MCM denial episodes at once. The Hartford reference CSV timestamps
  every one of its 13,596 rows, so this path is unreachable there.

## Fix shape (decide before it matters)

Add a case-level disclosure for perfmon samples that are placeable in the case
but attributable to no span — either a `PerfmonAnalysis`-level hazard field, or a
dedicated "unattributed samples" group. Reuse `_hazard_unplaceable_samples`
(already caps at `_CITE_CAP`, sorts by `event_id`) so the disclosure text and
citation shape stay consistent with the no-episodes path.

---

**Resolved 2026-07-21** — closed in plan 14-02 by `_unattributed_group`
(`src/sift/pipeline/perfmon.py`), the synthetic case-level disclosure group that reuses
`_hazard_unplaceable_samples` verbatim on the episodes-present branch. Filed before that
commit; archived without further work.
