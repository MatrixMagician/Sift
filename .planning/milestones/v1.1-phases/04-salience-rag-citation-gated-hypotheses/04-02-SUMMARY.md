---
phase: 04-salience-rag-citation-gated-hypotheses
plan: 02
subsystem: pipeline
tags: [salience, ranking, determinism, rag]
requires:
  - store.Cluster (04-01, pre-existing)
  - store.TemplateGroup (Phase 2/3)
provides:
  - salience.rank_clusters — deterministic cluster ranking for the triage prompt
affects:
  - hypothesise.py (04-04) consumes rank_clusters to order retrieval
tech-stack:
  added: []  # stdlib math + datetime only — no new dependency (T-04-SC)
  patterns:
    - pure pipeline module (typer-free, print-free, SQL-free) mirroring cluster.py
    - aggregate temporal features from member TemplateGroups (clusters carry none)
    - stable sort by (-score, cluster_id) for reproducible ordering
key-files:
  created:
    - src/sift/pipeline/salience.py
    - tests/test_salience.py
  modified: []
decisions:
  - "Window filter drops no-timestamp clusters when since/until is set — a cluster with unknown time cannot be confirmed in-window (conservative scoping)."
  - "All datetimes normalised to aware UTC via _as_utc before subtraction (caller convention: naive == UTC) — avoids naive/aware TypeError."
  - "tau (novelty/proximity decay) = case span / 4, or _TAU_FALLBACK (3600s) when the span is degenerate."
metrics:
  duration: ~8m
  completed: 2026-07-17
  tasks: 1
  files: 2
  tests_added: 7
status: complete
---

# Phase 4 Plan 02: Deterministic Salience Ranking Summary

`rank_clusters` — a pure, deterministic salience ranker that orders clusters by a five-feature score (severity, count, burstiness, novelty, temporal proximity), aggregating timestamps from member template groups because the cluster row has none.

## What was built

`src/sift/pipeline/salience.py` implements `rank_clusters(clusters, groups, *, incident_time, since=None, until=None) -> list[tuple[Cluster, float]]`:

- **Pure module** — typer-free, print-free, SQL-free; the caller passes already-queried clusters and groups. Mirrors `cluster.py`'s header discipline.
- **Aggregate-from-groups** — a `{template_id: TemplateGroup}` index joins each cluster to its members via `cluster.template_ids`; `first_ts`/`last_ts` are parsed with `datetime.fromisoformat`. The cluster row carries no timestamps (migration 3 dropped them — Pitfall 1).
- **Five features** — `severity = _SEVERITY_RANK[...]/5` (frozen dict copied verbatim from `cluster.py`, never lexicographic); `count = log1p(count)/log1p(max_count)` (log-damped); `burstiness = count/max(span, _SPAN_FLOOR)` then min-max normalised; `novelty`/`proximity` = `exp(-|first|last − incident|/tau)`.
- **Weights** — `_W_SEVERITY 0.35`, `_W_COUNT 0.20`, `_W_BURST 0.15`, `_W_NOVELTY 0.10`, `_W_PROXIMITY 0.20` (sum 1.0, SPEC OQ4 hand-tuned start).
- **Incident time** — derived from the max member `last_ts` (case end) when the caller passes `None`; all temporal features go neutral if no member has any timestamp.
- **Window filter** — `since`/`until` scope candidates at cluster granularity *before* scoring; a cluster whose member span misses the window is dropped, not re-clustered.
- **Determinism** — sorted by `(-score, cluster_id)`; identical inputs yield an identical list.

## Verification

| Gate | Result |
|------|--------|
| `uv run pytest tests/test_salience.py` | 7 passed |
| `uv run pytest` (full suite) | 283 passed, 2 deselected |
| `uv run ruff check` | clean |
| `uv run pyright` (full include set) | 0 errors, 0 warnings |

Tests cover: `_SEVERITY_RANK` frozen-dict drift-guard; higher-severity/higher-count outranks lower; equal-score tie-break by `cluster_id` + call-twice determinism; all-None-timestamp cluster ranked without raising (scores on severity+count only); since/until window excludes a non-intersecting cluster; window drops a no-timestamp cluster; naive `incident_time` treated as UTC without raising.

## Threat mitigations applied

- **T-04-07 (DoS)** — spans clamped with `max(span, _SPAN_FLOOR)`; missing/degenerate timestamps give neutral features. No unbounded or divide-by-zero maths on adversarial timestamps.
- **T-04-09 (Tampering)** — frozen `_SEVERITY_RANK`; an out-of-vocab severity defaults to rank 0, never reordering the ranking spuriously.
- **T-04-SC** — no package installs; stdlib `math`/`datetime` only.

## Deviations from Plan

None — plan executed as written. One design detail the plan left open (behaviour of a no-timestamp cluster under an active window) resolved conservatively: such a cluster is dropped when `since`/`until` is set, since its time cannot be confirmed in-window. Covered by `test_window_drops_cluster_without_timestamps`.

## Requirements

- **RAG-01** — deterministic salience ranking. Complete.
- **RAG-06** — since/until window scoping at cluster granularity. Complete.

## Self-Check: PASSED

- `src/sift/pipeline/salience.py` — FOUND
- `tests/test_salience.py` — FOUND
- Commit `045b576` — present in git log
