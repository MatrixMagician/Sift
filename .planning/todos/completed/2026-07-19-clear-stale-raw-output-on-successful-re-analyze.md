---
created: 2026-07-19T16:12:15.624Z
title: Clear stale raw output on successful re-analyze
area: pipeline
files:
  - src/sift/pipeline/hypothesise.py:334  # Outcome build + persist
  - src/sift/store.py                      # hypotheses/raw persistence
  - src/sift/render/                        # report "Raw model output" block
---

## Problem

After an earlier **degraded** generation run persists raw model output, a
subsequent **successful** `sift analyze` (valid ranked hypotheses, 0 flagged)
leaves the previous run's raw output in the report. `sift report` then renders
BOTH the new valid "Ranked hypotheses" AND a stale
"Raw model output (unvalidated)" block from the old degraded run.

Observed 2026-07-19 on the DSSErrors probe case: an earlier Qwen3-0.6B run
degraded and persisted raw JSON ("Subscription Access Issue …"); re-running
`analyze` with `user.Qwen2.5-14B-Instruct` produced 3 valid hypotheses (0
flagged) but the report still showed the old raw block underneath. A fresh
case that never degraded (the eu-stack case) showed **no** raw block — which
confirms the raw output persists from the prior degraded run and is not cleared
when a later successful (non-degraded) `Outcome` is persisted.

Cosmetic but misleading — a reader could mistake the stale raw JSON for part of
the current findings.

Likely cause: the persistence path in `hypothesise.py` (the successful/non-
degraded `Outcome` branch) does not clear/overwrite the previously-stored raw
output column when it writes valid hypotheses; the renderer unconditionally
shows the raw block whenever raw is present.

Repro: `analyze` with a weak model (degrades, persists raw) → `analyze` again
with a competent model (valid, 0 flagged) → `sift report`: both the valid
hypotheses and the stale raw block appear.

## Solution

TBD — on persisting a non-degraded `Outcome` (`degraded=False`, hypotheses
present), clear the stored raw output so a later report shows only the valid
findings. Confirm the store write is atomic with the hypotheses write.

GSD gap-closure candidate: RED regression test first — degrade-then-succeed on
the same case, assert the rendered report has no "Raw model output" block — then
fix, gated on full ruff/pyright/pytest.
