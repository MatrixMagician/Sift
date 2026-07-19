# Phase 11 code-review INFO follow-ups (non-blocking)

**Filed:** 2026-07-20
**Source:** Phase 11 code review (`.planning/phases/11-mcm-facts-into-sift-analyze-golden-eval-case/11-REVIEW.md`) — WR-01 already fixed (commit `9efab09`); these two INFO items were deferred as cosmetic.

## IN-01 — share one granted-MB formatting helper
`src/sift/pipeline/mcm_facts.py:107` derives the granted-MB figure directly (`:,.1f`), while the MCM report renderer rounds first (`round(..., 3)` then `:,.1f`). They agree on real data, but the two code paths can drift. Extract a single shared formatting helper so both call it.

## IN-03 — cosmetic regex/whitespace tidy in the MCM splice
`src/sift/pipeline/hypothesise.py:90,106` — the MCM block regex uses a redundant `re.DOTALL`, and the MCM-present path emits a cosmetic double newline. Neither affects behaviour (the no-MCM byte-identity hash is guarded); tidy when next touching the file.

**Priority:** low — cosmetic/consistency only; no correctness or invariant impact.
