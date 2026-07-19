---
phase: 09-mcm-episode-detection-memory-breakdown
plan: 09-03
subsystem: pipeline/mcm
tags: [bugfix, mcm, episode-detection, citation-invariant, regression-test]
requires: [09-01, 09-02]
provides: [WR-01-fix, multi-episode-partial-recovery-coverage]
affects: [src/sift/pipeline/mcm.py]
tech-stack:
  added: []
  patterns: [disjoint-episode-spans, bounded-backward-info-dump-lookup]
key-files:
  created:
    - tests/fixtures/mcm/hartford_two_episode_partial.log
  modified:
    - src/sift/pipeline/mcm.py
    - tests/test_mcm.py
decisions: []
metrics:
  duration: ~15m
  completed: 2026-07-19
status: complete
---

# Phase 9 Plan 03: WR-01 Partial-Recovery Disjoint-Span Fix Summary

Fixed the phase-09 code-review MEDIUM finding WR-01 (overlapping MCM episode
spans on partial recovery) and added the multi-episode regression coverage the
single-episode Hartford fixture never exercised. Follow-up fix on the phase-09
branch — not a new plan.

## The Bug (WR-01)

`_prescan` closed a partial-recovery episode (a fresh `DENIAL_MARKER` arriving
while already `in_denial` with intervening `Contract Request Succeeded` lines)
by setting `prev_recovery_idx = start_idx` — the OLD denial's start index. Since
the next episode's `span_start = prev_recovery_idx + 1`, episode #2's span began
at `old_denial_start + 1`, landing INSIDE the just-closed episode #1's span
`[…, i-1]`. The two spans OVERLAPPED over `[old_start+1, i-1]`.

On real multi-episode DSSErrors logs (repeated denial cycles are the production
norm) this breached the load-bearing `cited ⊆ correct-episode` citation
invariant: `_scan_lifecycle` double-emitted any `memory-status-low` /
`emergency-offload-*` signal in the overlap into BOTH episodes, and episode #2's
`event_ids` citation set included rows belonging to episode #1. `_build_breakdown`'s
backward scan could also grab the previous episode's Info Dump. Determinism was
preserved, so the single-episode fixture and `test_determinism_byte_identical`
stayed green — the defect was simply untested.

## The Fix (two parts)

**Part 1 — disjoint spans (correctness core), `_prescan`:** the partial-recovery
close branch now sets `prev_recovery_idx = i - 1` (the line just before the new
denial), mirroring the normal-recovery branch's semantics. Episode #2's
`span_start` becomes `i` (its own denial index), so no lifecycle signal and no
citation `event_id` can appear in more than one episode. The lifecycle/citation
span was NOT widened.

**Part 2 — pre-denial Info-Dump lookup, `_build_breakdown`:** with disjoint
spans a partial-recovery episode's `span_start` equals its own denial index, so
the old backward scan `range(denial_idx-1, span_start-1, -1)` became empty and
that episode would lose its MCM Settings / Current Memory Info. The backward
Info-Dump scan now reaches back past `span_start` toward the nearest
`Current Memory Info:` / `MCM Settings:` block preceding this denial banner,
bounded to STOP at the previous episode's boundary — it breaks on any prior
`DENIAL_MARKER` / `NORMAL_MARKER` line, so it never reads the previous episode's
denial-time block. Only the Info-Dump lookup window widened; the
lifecycle/citation span is unchanged. D-03 tolerate-absence is preserved: a
genuine no-dump gap leaves `mcm_settings` / `current_info` empty (never
fabricated, never raised).

## New Regression Coverage

- **Fixture** `tests/fixtures/mcm/hartford_two_episode_partial.log`: synthetic
  but realistic DSSErrors slice — denial #1 (pre-denial Info Dump with
  `Memory Reserve = 1048576`, Format-A block, `memory-status-low`) →
  `Contract Request Succeeded` → denial #2 (own Info Dump with
  `Memory Reserve = 2097152`, Format-A block, `emergency-offload-complete`),
  ending with NO `State=normal` so episode #2 is `open_truncated`. Tab-indented
  detail blocks keep each block adapter-grouped into one event.
- **Three appended tests** (existing 8 untouched):
  - `test_two_episode_partial_recovery_disjoint` — exactly 2 episodes; lifecycle
    `event_id` sets disjoint; `event_ids` citation sets disjoint; distinct denial
    anchors, both ⊆ store. **This is the WR-01 regression assertion.**
  - `test_two_episode_own_predenial_settings` — each episode carries its OWN
    pre-denial `Memory Reserve` (1048576 vs 2097152), proving Part 2 associates
    the correct in-gap dump per episode with no cross-episode contamination.
  - `test_two_episode_determinism_byte_identical` — multi-episode
    `model_dump_json` byte-identical across two runs.

## RED → GREEN Evidence

- **RED** (pre-fix): `test_two_episode_partial_recovery_disjoint` failed on
  `assert life1.isdisjoint(life2)` — episode #2's lifecycle set contained BOTH
  the `memory-status-low` id (from episode #1's overlap) and its own
  `emergency-offload-complete` id. `settings` and `determinism` tests passed
  pre-fix (the overlap happened to still reach ep#2's dump), so the disjoint
  test is the load-bearing regression.
- **GREEN** (post-fix): all 3 new tests pass; the 8 existing golden tests pass
  unchanged.

## Verification

- `uv run pytest tests/test_mcm.py -x` → 11 passed.
- `uv run pytest -q` → 481 passed, 8 deselected.
- `uv run ruff check` → All checks passed.
- `uv run pyright` → 0 errors, 0 warnings, 0 informations.
- `git grep -nE 'CREATE TABLE|user_version|ALTER TABLE|import httpx|import requests|import socket|import subprocess|\bset\(' src/sift/pipeline/mcm.py`
  → no matches (no store schema/migration, no network/subprocess, no `set()`
  in ordered output; regexes remain ^-anchored).

## Prohibitions Honoured

No change to `src/sift/models.py` or `src/sift/adapters/dsserrors.py` (D-01); no
store schema/migration (D-05); no CLI; no network/subprocess/LLM/file-write; no
`set()`/unordered iteration in ordered output (determinism, D-05); regexes stay
`^`-anchored (no ReDoS). British English, type hints, ruff/pyright clean. The 8
existing golden test assertions were not edited. STATE.md / ROADMAP.md tracking
left untouched — the orchestrator owns phase completion.

## Deviations from Plan

None — executed exactly as specified in the fix brief. No auto-fixes beyond the
required WR-01 change were needed (IN-01/IN-02 from the review are optional
low-priority notes and were left as-is per the reviewer's "not actionable now").

## Self-Check: PASSED

- `tests/fixtures/mcm/hartford_two_episode_partial.log` — FOUND
- Commit `1a430d6` (test) — FOUND
- Commit `06adef5` (fix) — FOUND
