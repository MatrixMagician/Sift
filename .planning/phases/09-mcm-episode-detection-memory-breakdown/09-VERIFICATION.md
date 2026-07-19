---
phase: 09-mcm-episode-detection-memory-breakdown
verified: 2026-07-19T00:00:00Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown Verification Report

**Phase Goal:** A user can run the new deterministic MCM analyser over a `dsserrors` case and see every distinct denial episode — non-interactively, all episodes, full lifecycle — each with its denial-time physical/virtual memory breakdown and MCM settings, computed with zero LLM involvement.
**Verified:** 2026-07-19
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Deterministic, non-interactive analyser runs over stored `dsserrors` events | ✓ VERIFIED | `detect_episodes(events)` is pure (no `input()`/prompt/getpass — the only `input(` grep hit is the docstring token "prompted"); `test_determinism_byte_identical` passes; my probe confirms byte-identical `model_dump_json` across two multi-episode runs |
| 2 | Every distinct denial episode is detected with correct boundaries | ✓ VERIFIED | Golden `test_hartford_single_episode` (1 episode); behavioral probe: `State=normal` recovery close → 2 episodes (ep0 recovered, ep1 open); implicit-recovery close on following denial → 2 episodes; two fully-recovered episodes → recoveries captured |
| 3 | Full lifecycle signals (memory-status-low, offload-start, offload-complete) each cite a real in-span event_id | ✓ VERIFIED | `test_lifecycle_signals` asserts the 3 kinds present and `sig.event_id in ids` AND `in ep.event_ids`; `_scan_lifecycle` classifies by tail marker |
| 4 | Open/truncated episode handled; recovery None on Hartford (D-07) | ✓ VERIFIED | `test_open_truncated_episode` (`open_truncated is True`, `recovery is None`); `_prescan` EOF-open branch; probe confirms open on unrecovered trailing denial |
| 5 | Denial-time Format-A breakdown: 23 labels incl. physical/virtual split, pinned MB values | ✓ VERIFIED | `test_breakdown_values` (cube=27923, working_set=268502, mmf=365, other=101682, iserver_virtual=410325, `len(raw_map)==23`, phys+virt labels present) |
| 6 | MCM settings parsed; `Memory Reserve = 0 (0Bytes)` not dropped; SmartHeap present | ✓ VERIFIED | `test_mcm_settings_complete`; widened `ABBREV_LINE_RE` accepts `Bytes`; fixture carries both lines |
| 7 | Zero LLM/network/subprocess/file-write egress; no schema/adapter/model/CLI change | ✓ VERIFIED | No `httpx`/`requests`/`socket`/`subprocess`/`open(`/`.write(` in `mcm.py`; no `CREATE TABLE`/`ALTER TABLE`/`user_version`; `git diff main...HEAD` shows `models.py` and `adapters/dsserrors.py` untouched; no CLI registration |
| 8 | Every episode boundary + lifecycle signal maps to a real event_id (Phase 11 citation) | ✓ VERIFIED | `denial_event_id in ids`, each signal `event_id in ids`; `_line_stream` carries event_id per line; `event_ids` deduped in stream order |
| 9 | Fragmentation guard (D-06) flags multi-node split, never silent merge | ✓ VERIFIED | `test_fragmented_flag` (empty detail block + differing `source_file` → `fragmented is True`) |

**Score:** 9/9 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/mcm.py` | `detect_episodes` + frozen models + ported parsers/constants | ✓ VERIFIED | 469 lines; `detect_episodes`, `McmEpisode`/`MemoryBreakdown`/`LifecycleSignal` (frozen, extra=forbid), `parse_detail_block`/`parse_abbrev_block`/`_get`, widened `ABBREV_LINE_RE`, lifecycle anchors |
| `tests/test_mcm.py` | 8 golden assertions + ingest helper | ✓ VERIFIED | 8 `def test_`; real adapter→store→detect round-trip; no assertion weakened |
| `tests/fixtures/mcm/hartford_deny_slice.log` | verbatim single-episode slice, no State=normal | ✓ VERIFIED | 66 lines; 1 banner, 0 State=normal, Memory Reserve 0Bytes present, offload-complete present, 8 Succeeded, phys+virt labels present |
| `docs/reference/analyze_dss8.py` | byte-verbatim vendored provenance | ✓ VERIFIED | Present; ruff-excluded; non-executed |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `detect_episodes` | `store.query_events()` output | consumes ordered events, no re-sort | ✓ WIRED | `_line_stream` preserves incoming D-06 order; test ingests via real `CaseStore` |
| episode boundaries / signals | real `event_id` | re-parse `event.raw` (D-01) | ✓ WIRED | event_id carried per stream line; asserted `⊆ store` in tests |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Golden suite | `uv run pytest tests/test_mcm.py -q` | 8 passed | ✓ PASS |
| Multi-episode + State=normal recovery | direct `detect_episodes` probe (Cases A/B/C) | 2/2/2 episodes, recoveries + open flags correct | ✓ PASS |
| Multi-episode determinism | two runs, compare `model_dump_json` | identical | ✓ PASS |
| Full gate | `uv run pytest` / `ruff check` / `pyright` | 478 passed/8 deselected, clean, 0 errors | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MCM-01 | 09-01, 09-02 | Deterministic non-interactive detection of every denial episode + full lifecycle signals | ✓ SATISFIED | Truths 1-4, 8; golden suite + multi-episode probe |
| MCM-02 | 09-01, 09-02 | Per-episode denial-time memory breakdown (phys/virt split, cube, MMF, working set, etc.) + MCM settings | ✓ SATISFIED | Truths 5-6; `test_breakdown_values` + `test_mcm_settings_complete` |

No orphaned requirements: REQUIREMENTS.md maps only MCM-01/MCM-02 to Phase 9; both are declared in both plans and satisfied.

### Prohibitions (all flagged-unverified at plan time — now independently verified)

| Prohibition | Status | Evidence |
|-------------|--------|----------|
| No modify to frozen `Event` / `models.py` | ✓ HELD | `git diff main...HEAD` shows `models.py` untouched |
| No store table/migration/user_version bump (D-05) | ✓ HELD | no schema DDL in module |
| No LLM/network/subprocess/file-write | ✓ HELD | no egress imports or I/O calls |
| No adapter enrichment (`dsserrors.py`) — re-parse raw (D-01) | ✓ HELD | adapter untouched in diff |
| No CLI surface / no prompt/report/window logic | ✓ HELD | no `sift mcm` registration |
| No `set()` / unordered iteration in ordered output | ✓ HELD | no `set(` literal; `dict.fromkeys` + tuples only |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | none | — | `breakdown` empty-when-absent is a documented D-03-compliant design (never fabricated), not a stub; no TODO/FIXME/XXX in modified files |

### Design Notes (intentional, not gaps)

- **AvailableMCM climb-back / resumed successes are lifecycle annotations, not episode-close boundaries.** MCM-01 lists these as candidate recovery signals; the implementation deliberately closes only on `State=normal` or a following denial banner (documented Q2 / D-07 timing-nuance decision, validated against the real Hartford log where the AvailableMCM climb does not indicate true recovery). Episode boundaries remain correct; this is a reasoned in-phase decision.
- **AvailableMCM headroom timeline / `hwm_bytes` / `avail_timeline` fields omitted from `McmEpisode`.** Field set was explicitly executor discretion in 09-02 ("provided golden accessors and verbatim raw_map survive"). Lead-up window / headroom attribution is Phase 10 scope (MCM-03..05), not Phase 9.

### Human Verification Required

None. All truths are grep/probe-verifiable and were exercised end-to-end (golden suite + direct multi-episode behavioral probe). No visual/UX/external-service surface in this phase.

### Gaps Summary

None. The phase goal is achieved: a deterministic, non-interactive, zero-LLM/zero-egress analyser detects denial episodes (single and multi, open/truncated and recovered) with full lifecycle signals and the denial-time Format-A memory breakdown + MCM settings, every boundary cited to a real event_id. Both requirements (MCM-01, MCM-02) satisfied; full gate green (478 passed, ruff clean, pyright 0 errors).

---

_Verified: 2026-07-19_
_Verifier: Claude (gsd-verifier)_
