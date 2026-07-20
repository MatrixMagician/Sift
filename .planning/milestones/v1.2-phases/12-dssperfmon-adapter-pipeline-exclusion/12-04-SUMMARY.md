---
phase: 12-dssperfmon-adapter-pipeline-exclusion
plan: 04
subsystem: store
tags: [perf-03, exclusion, regression-gate, citation, criterion-4, criterion-5]
status: complete
requires:
  - sift.store.CaseStore.iter_event_summaries (the single ranking seam)
  - sift.store.CaseStore.get_events_by_ids (the citation idiom the exclusion copies)
  - REGISTRY["dssperfmon"] (12-03 — perfmon events actually reach the pipeline)
  - tests/fixtures/dssperfmon/hartford_deny_slice.csv (12-01)
  - tests/fixtures/mcm/hartford_deny_slice.log
provides:
  - sift.store.EXCLUDED_FROM_RANKING — module-owned, unconditional, uncallable-from-outside
  - tests/test_store.py — four tests, two pinning exclusion, two pinning citation
  - tests/test_cli.py::test_cluster_output_identical_with_and_without_perfmon
  - tests/test_cli.py::test_show_events_includes_perfmon
  - tests/test_cluster.py::test_exemplars_exclude_perfmon
affects:
  - 13-* (episode correlation reads perfmon events via the unfiltered citation paths)
  - any future ranking stage — it inherits the exclusion by reading the same seam
tech-stack:
  added: []
  patterns:
    - one WHERE clause on one method reaches four consumers; no per-stage filter
    - sorted(frozenset) fixes parameter order for a determinism-critical query
    - near-identical adjacent methods carry paired comments naming the asymmetry
key-files:
  created: []
  modified:
    - src/sift/store.py
    - tests/test_store.py
    - tests/test_cli.py
    - tests/test_cluster.py
decisions:
  - the exclusion is unconditional with no opt-out parameter (D-07) — a defaulted flag is exactly the mechanism by which a future caller could silently reintroduce the criterion-4 regression
  - the _seed helper in test_cluster.py was NOT given a source parameter; _ev was. _seed's would have been dead flexibility since the new test needs non-colliding offsets anyway
  - criterion 4 is asserted on derived cluster output, never on the two case.db files — case B legitimately holds the perfmon events
metrics:
  duration: ~30 min
  tasks: 3
  files: 4
  completed: 2026-07-20
---

# Phase 12 Plan 04: PERF-03 Pipeline Exclusion Summary

Perfmon events are held out of every ranking stage by a single `WHERE source NOT IN (...)` clause on
`CaseStore.iter_event_summaries`, with three independent guards proving nothing else moved and every
sample stays citable.

## What Was Built

**The seam** (`c0506ca`). `EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon"})` sits
with the other SQL module constants. `iter_event_summaries` builds its placeholder run from
`sorted(EXCLUDED_FROM_RANKING)` — sorting fixes parameter order because frozenset iteration order is
not guaranteed stable across builds and this query feeds a determinism-critical pipeline — and binds
every source value through the parameter tuple, interpolating only the placeholder count. That is the
`get_events_by_ids` idiom verbatim, so T-12-14 is closed by construction: no source string reaches SQL
text, and the set is module-owned with no parameter, env var or config key (T-12-17, D-07).

`git diff --name-only` lists nothing under `src/sift/pipeline/` and not `src/sift/eval/runner.py`.
The four consumers — `dedup.rebuild_template_groups`, `cluster._exemplar_messages`, the
hypothesis-excerpt gatherer and the eval runner — inherit the filter without edits, and
`salience.rank_clusters` inherits it transitively by consuming Cluster/TemplateGroup rows rather than
events. One clause, five stages.

**The asymmetry guard.** `iter_event_rows` sits immediately below `iter_event_summaries`, shares its
ordering expression and streaming idiom, and now differs only in its column list and this filter —
which reads like an oversight and invites a tidy-up into a shared helper. Both methods carry paired
comments naming PERF-03, stating the direction of the asymmetry explicitly, and pointing at the tests
that pin each half. `grep -c 'PERF-03' src/sift/store.py` returns 3, so the comment is itself an
enforced artifact rather than prose that can silently rot.

**The regression gate** (`ba2704a`). `test_cluster_output_identical_with_and_without_perfmon` builds
two cases from the same MCM log, adds the perfmon CSV to only one, and asserts `sift show clusters`
stdout is equal. It compares the derived output, never the two `case.db` files — case B legitimately
contains the perfmon events, and criterion 4 promises identity of ranking, not of stored state. The
non-vacuity assertion (`n_b - n_a == 20`) is in the same test, so an equality that passed because the
CSV silently failed to ingest fails loudly instead. No `analyze` step runs, so the render goes through
the template-group path with no embedding or LLM call; the autouse `_no_network` guard enforces that
no socket opens (T-12-18).

**The exemplar check** (`bfeb5a2`). `test_exemplars_exclude_perfmon` seeds both sources at
non-colliding byte offsets, runs the real clustering path against the existing `httpx.MockTransport`
fake, and asserts no perfmon message reaches a persisted chunk. Belt-and-braces: strictly weaker than
the template-group equality in Task 1, since exemplars derive from template groups.

## Deviations from Plan

**1. [Rule 3 — Scope] `_seed` in `tests/test_cluster.py` was left unchanged; `_ev` took the parameter
instead**

- **Found during:** Task 3.
- **Issue:** The plan asked for a defaulted `source` on `_seed`. `_seed` inserts events at offsets
  `0..n-1`, and `event_id = sha256(source_file, byte_offset)[:16]`, so calling it twice in one test
  collides on every id. The new test must therefore insert its perfmon events itself at shifted
  offsets — which means a `source` parameter on `_seed` would have had no caller.
- **Fix:** `_ev` (the helper that actually hardcodes `source="genericlog"`) took the defaulted
  parameter; `_seed` is byte-identical to before. Every existing caller of both is untouched and all
  17 pre-existing tests in the module stay green.
- **Why not the literal instruction:** an unused defaulted parameter on a shared test helper is dead
  flexibility, and the plan's own reasoning for allowing a defaulted parameter here ("every existing
  caller is untouched") is satisfied more cheaply by putting it where it is used.
- **Files modified:** `tests/test_cluster.py`
- **Commit:** `bfeb5a2`

No other deviations. Nothing outside the four declared `files_modified` was touched, no `must_have`
was weakened, and no architectural escalation was needed.

## Non-Vacuity Verification

Every test that passed on its first run was counterfactually verified before commit, and the source
restored byte-identically (`git diff --quiet` confirmed each time).

| Test | Counterfactual applied | Result |
|------|------------------------|--------|
| `test_iter_event_rows_unfiltered` | exclusion added to `iter_event_rows` | FAILED as intended |
| `test_get_events_returns_perfmon` | exclusion added to `get_events_by_ids` | FAILED as intended |
| `test_cluster_output_identical_with_and_without_perfmon` | `EXCLUDED_FROM_RANKING = frozenset()` | FAILED as intended |
| `test_exemplars_exclude_perfmon` | `EXCLUDED_FROM_RANKING = frozenset()` | FAILED as intended |

`test_iter_event_summaries_excludes_perfmon` and `test_template_groups_exclude_perfmon` were genuine
RED-first tests — both failed before the implementation existed, so no counterfactual was needed.

The first counterfactual attempt on `test_iter_event_rows_unfiltered` produced a
`sqlite3.OperationalError` (duplicated `FROM` clause) rather than a clean assertion failure. That is
a broken-SQL failure, not evidence the test guards anything, so it was redone with semantically valid
SQL before being accepted.

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest` (full suite) | **566 passed, 8 deselected** (baseline 559 + 7 new) |
| `uv run ruff check` | clean |
| `uv run pyright` | 0 errors, 0 warnings |
| `git diff --name-only` vs `files_modified` | exact match, all four |
| anything under `src/sift/pipeline/` in the diff | **no** |
| `src/sift/eval/runner.py` in the diff | **no** |
| `grep -c 'EXCLUDED_FROM_RANKING' src/sift/store.py` | 4 (plan required ≥3) |
| `grep -c 'PERF-03' src/sift/store.py` | 3 (plan required ≥2) |
| `grep -n 'sorted(EXCLUDED_FROM_RANKING)' src/sift/store.py` | line 659 |
| `iter_event_summaries` signature | unchanged — no parameter, no opt-out |
| `pyproject.toml` unchanged | confirmed (T-12-SC) |
| every CLI invocation in the new tests | exit 0 |

## Known Stubs

None.

## Threat Flags

None. The plan adds no network endpoint, no auth path and no schema change. The one new SQL clause is
`?`-bound from a module constant that no caller or user input can reach, which is the mitigation
T-12-14 specifies rather than new surface.

## Self-Check: PASSED

- FOUND: `src/sift/store.py`
- FOUND: `tests/test_store.py`
- FOUND: `tests/test_cli.py`
- FOUND: `tests/test_cluster.py`
- FOUND commits: `c0506ca`, `ba2704a`, `bfeb5a2`
