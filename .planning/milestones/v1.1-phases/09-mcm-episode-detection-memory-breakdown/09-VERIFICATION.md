---
phase: 09-mcm-episode-detection-memory-breakdown
verified: 2026-07-19T00:00:00Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 9/9
  trigger: "Source changed after the prior PASS — code-review fix WR-01 landed in 06adef5 (disjoint episode spans) + regression coverage in 1a430d6. Prior VERIFICATION.md predated the fix and was stale."
  gaps_closed:
    - "WR-01 (code-review MEDIUM): overlapping partial-recovery episode spans double-attributed lifecycle signals and citation event_ids across episodes — now fixed and pinned by a genuine regression test"
  gaps_remaining: []
  regressions: []
---

# Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown Verification Report

**Phase Goal:** A user can run the new deterministic MCM analyser over a `dsserrors` case and see every distinct denial episode — non-interactively, all episodes, full lifecycle — each with its denial-time physical/virtual memory breakdown and MCM settings, computed with zero LLM involvement.
**Verified:** 2026-07-19 (against HEAD `70924a4`)
**Status:** passed
**Re-verification:** Yes — after the WR-01 disjoint-span fix (`06adef5`) + regression coverage (`1a430d6`). The prior 9/9 PASS predated these commits and was stale; this report reflects the post-fix codebase.

## Re-verification Context

The earlier verification passed 9/9 but was authored before three commits landed on the phase branch:

- `06adef5` fix(09): `_prescan` partial-recovery close now sets `prev_recovery_idx = i - 1` (was `start_idx`) so episode spans are **disjoint**; `_build_breakdown`'s backward Info-Dump scan widened but bounded to break on any prior `DENIAL_MARKER`/`NORMAL_MARKER` so each episode keeps its own pre-denial dump without reading the previous episode's block. (Confirmed touching only `src/sift/pipeline/mcm.py`, +19/-2.)
- `1a430d6` test(09): `tests/fixtures/mcm/hartford_two_episode_partial.log` + 3 multi-episode tests (`tests/test_mcm.py` 8 → 11). Diff is **pure addition** — no `-` line touches the original 8 test bodies.
- `70924a4` docs(09): gate-doc reconciliation (09-REVIEW status `resolved`, VALIDATION `nyquist_compliant: true`).

The full authoritative gate was re-run independently at HEAD (not trusted from any SUMMARY).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Deterministic, non-interactive analyser runs over stored `dsserrors` events, zero LLM involvement | ✓ VERIFIED | `detect_episodes(events)` is pure — no `input()`/prompt; purity grep on `mcm.py` for `httpx\|requests\|socket\|subprocess\|open(\|print(\|sqlite3\|CREATE TABLE\|user_version\|ALTER TABLE\|set(` → **no matches**. `test_determinism_byte_identical` + `test_two_episode_determinism_byte_identical` both pass (byte-identical `model_dump_json` across two runs, single- and multi-episode) |
| 2 | Every distinct denial episode is detected with **correct, disjoint boundaries** (WR-01 area) | ✓ VERIFIED | `test_hartford_single_episode` (1 episode); `test_two_episode_partial_recovery_disjoint` asserts exactly 2 episodes with lifecycle `event_id` sets **and** citation `event_ids` sets disjoint, distinct denial anchors both ⊆ store. **Independently proven genuine:** swapped in the pre-fix `mcm.py` (`prev_recovery_idx = start_idx`) → the test FAILS (`life1.isdisjoint(life2)` False; `memory-status-low` id `f1551627e2482c31` in BOTH episodes); post-fix it passes. The test is a real pin, not a rubber stamp |
| 3 | Each episode associates its OWN pre-denial MCM Settings dump (no cross-episode contamination) | ✓ VERIFIED | `test_two_episode_own_predenial_settings`: ep1 `Memory Reserve == 1048576`, ep2 `== 2097152`, distinct. `_build_breakdown` backward scan (mcm.py:423-432) breaks on prior `DENIAL_MARKER`/`NORMAL_MARKER`, so it never reaches the previous episode's block |
| 4 | Full lifecycle signals (memory-status-low, offload-start, offload-complete) each cite a real in-span event_id | ✓ VERIFIED | `test_lifecycle_signals` asserts the 3 kinds present, `sig.event_id in ids` AND `in ep.event_ids`; multi-episode test additionally asserts ep1 kinds `== {memory-status-low}`, ep2 `== {emergency-offload-complete}` (disjoint). `_scan_lifecycle` classifies by tail marker over the span only |
| 5 | Open/truncated episode handled; recovery None when no `State=normal` (D-07) | ✓ VERIFIED | `test_open_truncated_episode` + multi-episode test's ep2 (`open_truncated is True`, `recovery is None`); `_prescan` EOF-open branch (mcm.py:358-370) |
| 6 | Denial-time Format-A breakdown: 23 labels incl. physical/virtual split, pinned MB values | ✓ VERIFIED | `test_breakdown_values` (cube=27923, working_set=268502, mmf=365, other=101682, iserver_virtual=410325, `len(raw_map)==23`, physical+virtual labels present) |
| 7 | MCM settings parsed; `Memory Reserve = 0 (0Bytes)` not dropped; SmartHeap Releasable present | ✓ VERIFIED | `test_mcm_settings_complete`; widened `ABBREV_LINE_RE` (mcm.py:64-67) accepts `Bytes`; fixture carries both lines |
| 8 | Zero network/subprocess/file-write egress; no schema/adapter/model/CLI change | ✓ VERIFIED | Purity grep clean (truth #1). `mcm.py` imports only `re`, `dataclasses`, `typing`, `pydantic`. No store schema/migration/`user_version`. No CLI registration; not yet imported anywhere in `src/` (Phase 10/11 territory) |
| 9 | Fragmentation guard (D-06) flags multi-node split, never silent merge | ✓ VERIFIED | `test_fragmented_flag` (empty detail block + differing `source_file` → `fragmented is True`) |

**Score:** 9/9 truths verified (0 present, behavior-unverified). Truth #2 is behaviour-dependent (a cross-episode boundary/citation invariant); it is VERIFIED on behavioural evidence — the regression test was independently shown to fail on pre-fix code and pass on the fixed code, not on symbol presence alone.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/mcm.py` | `detect_episodes` + frozen models + ported parsers/constants + WR-01 disjoint-span fix | ✓ VERIFIED | 486 lines. `detect_episodes`, frozen `extra="forbid"` models `McmEpisode`/`MemoryBreakdown`/`LifecycleSignal`, `parse_detail_block`/`parse_abbrev_block`/`_get`, widened `ABBREV_LINE_RE`, lifecycle anchors. `_prescan:337` = `prev_recovery_idx = i - 1`; `_build_breakdown:423-432` bounded backward scan |
| `tests/test_mcm.py` | 8 golden assertions + 3 multi-episode regression tests + ingest helper | ✓ VERIFIED | 11 `def test_`; the original 8 untouched (diff of `1a430d6` is pure addition); real adapter→store→detect round-trip; no assertion weakened |
| `tests/fixtures/mcm/hartford_two_episode_partial.log` | two partial-recovery episodes, no `State=normal`, distinct pre-denial dumps | ✓ VERIFIED | 28 lines: denial#1 (Info Dump `Memory Reserve=1048576`, Format-A, memory-status-low) → Contract Request Succeeded → denial#2 (Info Dump `Memory Reserve=2097152`, Format-A, offload-complete), EOF open |
| `docs/reference/analyze_dss8.py` | vendored provenance copy | ✓ VERIFIED | Present (from 09-01) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `detect_episodes` | `store.query_events()` output | consumes canonical order, NO re-sort | ✓ WIRED | `_line_stream` iterates `dss` in incoming order (mcm.py:272-284); tests feed real `CaseStore.query_events()` |
| every episode boundary + lifecycle signal | a real `event_id` re-parsed from `event.raw` (D-01) | `_line_stream` carries `event_id` per line | ✓ WIRED | `cited ⊆ store` asserted: `denial_event_id in ids`, per-signal `event_id in ids`/`in ep.event_ids`; multi-episode test adds cross-episode disjointness |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full MCM suite passes | `uv run pytest tests/test_mcm.py -v` | 11 passed in 0.19s | ✓ PASS |
| WR-01 test genuinely pins the invariant | pre-fix `mcm.py` swapped in, run `test_two_episode_*` | `test_two_episode_partial_recovery_disjoint` FAILED on `life1.isdisjoint(life2)` (id in both episodes); restored, passes | ✓ PASS |
| Original 8 tests unmodified | `git show 1a430d6 -- tests/test_mcm.py \| grep '^-'` | no removal lines (pure addition) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MCM-01 | 09-01, 09-02 | Deterministic MCM analysis over a `dsserrors` case detecting every distinct denial episode non-interactively, with full lifecycle signals | ✓ SATISFIED | Truths 1,2,4,5,9; `detect_episodes`; single- and multi-episode detection with disjoint spans; lifecycle capture |
| MCM-02 | 09-01, 09-02 | Per-episode denial-time memory breakdown (physical/virtual split, cube caches, growth/index, MMF, SmartHeap pool, working set, other) + MCM settings from the memory-dump block | ✓ SATISFIED | Truths 3,6,7; `MemoryBreakdown` typed accessors; 23-label verbatim map; per-episode own settings |

### Anti-Patterns Found

None. No `TODO`/`FIXME`/`XXX`/`HACK`/`PLACEHOLDER` in `mcm.py` or `test_mcm.py`. No stub returns feeding user output — the empty-breakdown fallback (D-03) is a deliberate tolerate-absence path, not a stub. `assert` on control-flow invariants (IN-01) and abbrev-block terminator-bound (IN-02) remain documented non-actionable review notes.

### Authoritative Gate (re-run independently at HEAD)

| Gate | Command | Result |
|------|---------|--------|
| Lint | `uv run ruff check` | All checks passed! (exit 0) |
| Types | `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| MCM suite | `uv run pytest tests/test_mcm.py` | 11 passed |
| Full suite | `uv run pytest -q` | 481 passed, 8 deselected |

## Gaps Summary

None. The phase goal is achieved at HEAD. The WR-01 cross-episode correctness defect that existed under the prior (stale) PASS is now fixed in `06adef5` and pinned by a regression test independently proven to catch it (fails on the pre-fix boundary, passes on the fix). Episode spans are genuinely disjoint — no lifecycle signal or citation `event_id` appears in more than one episode — and each episode associates its own pre-denial MCM Settings without crossing into the previous episode. The analyser is pure/deterministic/LLM-free, every boundary cites a real store `event_id` (the load-bearing `cited ⊆ store` invariant), and MCM-01/MCM-02 are both satisfied. All four gate commands are clean. No wiring into `sift analyze`/CLI is present or expected — that is Phase 10/11 scope.

---

_Re-verified: 2026-07-19 against HEAD 70924a4 (post-WR-01-fix)_
_Verifier: Claude (gsd-verifier)_
