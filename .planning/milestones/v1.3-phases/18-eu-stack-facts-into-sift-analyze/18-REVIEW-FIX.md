---
phase: 18-eu-stack-facts-into-sift-analyze
fixed_at: 2026-07-26T16:15:50Z
review_path: .planning/phases/18-eu-stack-facts-into-sift-analyze/18-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 18: Code Review Fix Report

**Fixed at:** 2026-07-26T16:15:50Z
**Source review:** .planning/phases/18-eu-stack-facts-into-sift-analyze/18-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 3 (CR-01, WR-01, WR-02 — critical_warning scope, no Info findings exist)
- Fixed: 3
- Skipped: 0

All three findings are resolved by the same contiguous edit to `_flag_lines` in
`src/sift/pipeline/eustack_facts.py` — the three issues (missing D-03 disclosure sentence,
unenforced lock-site positional invariant, silent-drop fallback) live on overlapping lines of
one ~35-line function, so they were fixed and committed together in a single atomic commit
rather than split into three commits that would each touch the same lines.

## Fixed Issues

### CR-01: `_flag_lines` omits the mandatory D-03 sampling-disclosure sentence

**Files modified:** `src/sift/pipeline/eustack_facts.py`, `tests/test_eustack_facts.py`
**Commit:** `2a64b81`
**Applied fix:** Each of the three `SaturationFlag` branches in `_flag_lines` now threads its
own aggregate's true population alongside its exemplar tuple (never `flag.value`), and appends
`_sampling_sentence(len(exemplars), population)` to the emitted line, routed through the
existing single-definition-site helper (no second sampling routine, per ADR 0017 D-03/D-17):

- `unclassified_thread_pct` -> `population = bundle.analysis.threads_by_role["unclassified"]`
  (the same pool `pool_exemplars.get(None, ())` draws its exemplars from)
- `no_resolvable_frame_pct` -> `population` is the summed `thread_count` of the
  `unclassified`/`no-resolvable-frame` signature groups whose frames fed
  `no_resolvable_exemplars` (a new local computation mirroring the existing
  `no_resolvable_frame_tuples` derivation)
- `lock_convergence_count` -> `population = site.thread_count` for the matched site consumed
  from the same `lock_sites_in_order` iterator the exemplars come from

Verified live against the committed `reference_capture_derivative.txt` fixture: the previously
undisclosed line now reads `...unclassified_thread_pct: 38.1 percent... (3 of 40 thread events
cited as exemplars)`.

Added `test_every_cited_line_carries_sampling_sentence` — a whole-block invariant (not another
per-grouping spot check) asserting every line in a rendered block carrying an `[evt:...]` token
also carries the `_SAMPLING_RE` disclosure sentence. Confirmed RED against the pre-fix
`_flag_lines` (`git stash` of the source-only change reproduced the original failure:
`AssertionError: every line carrying an [evt:] citation must also carry the '(N of M thread
ev...'`) and GREEN after the fix.

### WR-01: `_flag_lines`'s lock-site attribution relies on an unenforced positional invariant

**Files modified:** `src/sift/pipeline/eustack_facts.py`
**Commit:** `2a64b81`
**Applied fix:** Added `assert next(lock_sites_in_order, None) is None, "lock_convergence_count
flag count must equal len(lock_sites)"` after the loop, so a future `analyse_saturation` change
that breaks the 1:1 `flags`/`lock_sites` correspondence fails loudly instead of silently
mis-attributing citations to the wrong lock site. Left the match keyed on positional order (not
`flag.value`) per the fix guidance — the existing docstring's reasoning that value-matching is
ambiguous under a thread-count tie still holds.

### WR-02: Unknown `SaturationFlag.dimension` silently drops the flag from the block

**Files modified:** `src/sift/pipeline/eustack_facts.py`
**Commit:** `2a64b81`
**Applied fix:** Replaced the silent `else: exemplars = ()` fallback with
`raise AssertionError(f"unhandled SaturationFlag.dimension {flag.dimension!r}")`, so an
unrecognised future flag dimension fails loudly (CLAUDE.md "nothing disappears silently")
instead of vanishing from the prompt with no signal that anything was omitted.

## Skipped Issues

None — all in-scope findings were fixed.

## Verification

- `uv run ruff check` — clean (`[]`), matching the pre-fix baseline.
- `uv run pytest` — 801 passed, 8 deselected (800 baseline + 1 new regression test
  `test_every_cited_line_carries_sampling_sentence`; no regressions).
- `uv run pyright` — 31 errors, all `reportPrivateUsage`/`reportUnknownMemberType`/
  `reportAttributeAccessIssue` confined to the same three pre-existing Phase-17 test files
  (`test_cli_eustack.py`, `test_eustack_progression.py`, `test_eustack_report.py`) as the
  pre-fix baseline — 0 errors in any file touched by this fix.
- New test confirmed RED (against pre-fix `_flag_lines`, via `git stash`) then GREEN (against
  the fix), demonstrating it actually catches the CR-01 regression class rather than passing
  vacuously.

---

_Fixed: 2026-07-26T16:15:50Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
