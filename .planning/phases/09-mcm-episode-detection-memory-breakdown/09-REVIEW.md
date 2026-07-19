---
phase: 09-mcm-episode-detection-memory-breakdown
reviewed: 2026-07-19T00:00:00Z
depth: deep
files_reviewed: 2
files_reviewed_list:
  - src/sift/pipeline/mcm.py
  - tests/test_mcm.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: resolved
warning_resolved: 1
resolved_at: 2026-07-19
---

> **Resolution (2026-07-19):** WR-01 fixed in commit `06adef5` — `_prescan` partial-recovery
> boundary corrected to `i - 1` (disjoint episode spans) and `_build_breakdown`'s backward
> Info-Dump scan bounded to break on prior `DENIAL`/`NORMAL` markers. Regression coverage added
> in `1a430d6` (`tests/fixtures/mcm/hartford_two_episode_partial.log` + `test_two_episode_*`),
> which fails on the pre-fix code and passes post-fix. Full gate green (ruff, pyright 0, 481 pass).
> The two INFO notes (IN-01 assert-invariants, IN-02 abbrev-block cap) remain as documented
> non-actionable observations.

# Phase 9: Code Review Report

**Reviewed:** 2026-07-19
**Depth:** deep
**Files Reviewed:** 2
**Status:** needs-attention

## Summary

`src/sift/pipeline/mcm.py` is disciplined, defensible code: pure/typer-free/IO-free
(verified — no `open`, `httpx`, `subprocess`, `print`, or `sqlite` references),
frozen + `extra="forbid"` on all three models, tolerant parsing (empty-breakdown
fallback, `_get` returns `None` on absence), and deterministic ordered output
(`dict.fromkeys` dedup, insertion-ordered dicts/tuples, no `set` iteration feeding
any model field). Regexes are anchored with constrained/required terminators and no
nested quantifiers — no ReDoS on the bounded per-line inputs. No prohibition breaches:
no store schema/migration, no adapter/model change, no CLI, no HTTP. The forward
Format-A parse from the denial banner plus the backward scan for the nearest in-span
abbreviated `Current Memory Info` / `MCM Settings` dump correctly reflects the real-file
structure (denial-time Format-A block is contiguous with the banner; the periodic
abbreviated dumps are separate and reached backward) — this matches the sampled-file
nuance that the denial marker and the memory-dump blocks are structurally distinct.

One real cross-episode correctness defect survives filtering (multi-episode logs are
the actual production shape), plus two low-severity notes. The single-episode fixture
does not exercise the affected path, so the green gate does not cover it.

## Warnings

### WR-01: Partial-recovery close reaches the next episode's span back over the just-closed episode (overlapping spans)

**File:** `src/sift/pipeline/mcm.py:329` (within `_prescan`, the second denial-banner branch, lines 311-330)
**Issue:**
When a new `DENIAL_MARKER` arrives while already `in_denial` and successes have
occurred since the open denial, the current episode is closed with `span_end = i - 1`
and then:

```python
prev_recovery_idx = start_idx      # <-- the OLD denial's start index
start_idx, start_eid, start_ts = i, eid, ts
```

`prev_recovery_idx` is the boundary used to compute the *next* episode's
`span_start = prev_recovery_idx + 1`. Setting it to the **old denial start** means the
next episode's span begins at `old_start_idx + 1`, which is `<= i - 1` — i.e. it reaches
back *over* the episode that was just closed (whose span was `[..., i - 1]`). The two
episodes then share the region `[old_start_idx + 1, i - 1]`.

Consequences on real multi-episode DSSErrors logs (repeated denial cycles are the norm):
- `_scan_lifecycle` runs over each span, so a `memory-status-low` / `emergency-offload-*`
  signal in the overlap is emitted in **both** episodes (double attribution).
- `event_ids` (the citation set) for the new episode includes rows that belong to the
  prior episode.
- `_build_breakdown`'s backward scan for the new episode can pick up the *previous*
  episode's `Current Memory Info` / `MCM Settings` dump.

Determinism is preserved (still byte-identical on re-run), so `test_determinism_byte_identical`
and the single-episode fixture stay green — this defect is simply untested.

**Fix:** Close the previous episode at its own end, not at its start. The partial-recovery
boundary is the line just before the new denial:

```python
prev_recovery_idx = i - 1
start_idx, start_eid, start_ts = i, eid, ts
```

Note the design tension worth confirming: with `span_start = i` the pre-denial info-dump
for the new denial (which sits *before* the banner) falls outside the backward scan
range in `_build_breakdown` (`range(denial_idx - 1, span_start - 1, -1)` becomes empty).
If capturing that dump for a partial-recovery episode is required, widen the *backward
scan* bound in `_build_breakdown` rather than overlapping the whole span — keep episode
spans disjoint. Either way, add a two-episode partial-recovery fixture (denial → success
→ denial, no `State=normal`) so the boundary is pinned.

## Info

### IN-01: Control-flow invariants asserted with `assert` (stripped under `python -O`)

**File:** `src/sift/pipeline/mcm.py:334, 351`
**Issue:** `assert start_idx is not None and start_eid is not None` guards the episode
construction. These double as pyright type-narrowing and the invariant genuinely holds
(both are only set/cleared alongside `in_denial`), so there is no runtime defect today.
But under `-O` the asserts vanish; if the `in_denial` bookkeeping ever drifts in a future
edit, `denial_idx=None` would silently flow into `_RawEpisode`.
**Fix:** Optional — narrow via an explicit `if start_idx is None: continue` guard, or
leave as-is and treat these lines as invariant documentation. Low priority; not actionable
now.

### IN-02: `parse_abbrev_block` has no line-count safety cap (asymmetric with `parse_detail_block`)

**File:** `src/sift/pipeline/mcm.py:228-250`
**Issue:** `parse_detail_block` carries an explicit 60-line runaway cap (line 223);
`parse_abbrev_block` has none. It cannot actually spin — it breaks on the first
non-blank non-matching line and terminates at any timestamp, and the stream is finite —
so this is a robustness/symmetry note, not a hang risk. Worth a one-line comment noting
the terminator-based bound so the asymmetry does not read as an oversight.
**Fix:** None required; optionally document the termination guarantee.

## Test-suite note (non-blocking)

`tests/test_mcm.py` assertions are strong where it counts: `denial_event_id in ids`
and per-signal `event_id in ids` / `in ep.event_ids` pin the load-bearing
`cited ⊆ store` citation invariant; `test_breakdown_values` pins exact MB-native figures
and the 23-label count; `test_determinism_byte_identical` compares real
`model_dump_json`. Gap (informational, ties to WR-01): every fixture-based test exercises
a **single** open/truncated episode, so no test covers multi-episode detection, normal
(`State=normal`) recovery closing an episode, or the partial-recovery branch. The
`prev_recovery_idx` boundary and span disjointness are therefore unverified.

---

_Reviewed: 2026-07-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
