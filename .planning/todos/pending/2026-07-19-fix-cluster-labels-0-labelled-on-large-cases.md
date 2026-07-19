---
created: 2026-07-19T16:12:15.624Z
title: Fix cluster labels "0 labelled" on large cases
area: pipeline
files:
  - src/sift/pipeline/cluster.py:249  # cluster_and_label / _label_clusters
  - src/sift/pipeline/cluster.py:49   # _LABEL_CTX_TOKENS = 4096
  - src/sift/llm/budget.py            # PromptBudget.fit (breadth-first)
---

## Problem

When `sift analyze` runs against a competent generation model, cluster
labelling returns **0 labels** on cases with many clusters, so every cluster
degrades to its `signature` instead of a human-readable name.

Observed 2026-07-19 during the real-data walkthrough (milestone v1.0 complete),
generation model `user.Qwen2.5-14B-Instruct`:
- DSSErrors_0626.log → `Clusters: 524 (0 labelled)`
- eu-stacks (iserver1_stacks_1-minute_diff) → `Clusters: 46 (0 labelled)`

Cosmetic only — hypotheses are unaffected and 0-flagged — but reports lack named
clusters, which hurts readability. Hypotheses generate fine on the same run, so
the generation endpoint itself is healthy; the issue is specific to the batched
label call.

Likely cause: the single batched label chat call (`cluster_and_label` →
`_label_clusters`, `cluster.py`) fitted to the 4096-token label budget
(`_LABEL_CTX_TOKENS`) either admits no exemplar excerpts once N is large (so
`PromptBudget.fit` returns empty and it short-circuits to no labels), or the
`{index: label}` JSON parse returns nothing / mis-indexes for large N. Labels
are designed to degrade to `signature` on any failure (never crash), which is
masking the miss.

Repro: `sift analyze` any case with dozens+ of clusters against a working gen
model; observe `Clusters: N (0 labelled)`.

## Solution

TBD — investigate:
1. Whether `PromptBudget.fit` returns empty for large cluster counts under the
   4096 budget (breadth-first per-cluster share collapses to ~0), and whether the
   label budget/pagination needs raising or the call needs batching across
   multiple chats.
2. Whether the `{index: label}` lenient parse drops everything for large N.

GSD gap-closure candidate: RED regression test first — assert a multi-cluster
case (dozens of clusters) produces >0 named labels — then fix, gated on full
ruff/pyright/pytest.
