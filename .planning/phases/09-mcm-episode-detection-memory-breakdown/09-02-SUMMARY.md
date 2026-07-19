---
phase: 09-mcm-episode-detection-memory-breakdown
plan: 02
subsystem: pipeline
tags: [mcm, episode-detection, memory-breakdown, deterministic, tdd-green]
status: complete
requires:
  - "09-01: tests/test_mcm.py golden contract, hartford_deny_slice.log fixture, docs/reference/analyze_dss8.py"
  - "src/sift/models.py: frozen Event, ConfigDict(extra=forbid) convention"
  - "src/sift/store.py: query_events D-06 canonical order"
  - "src/sift/adapters/dsserrors.py: MCM-block-as-one-event grouping"
provides:
  - "sift.pipeline.mcm.detect_episodes(events) -> list[McmEpisode]"
  - "sift.pipeline.mcm.McmEpisode / MemoryBreakdown / LifecycleSignal (frozen, extra=forbid)"
  - "ported constants + parse_detail_block / parse_abbrev_block / _get helpers"
affects:
  - "Phase 10 (sift mcm report + CSV): consumes McmEpisode"
  - "Phase 11 (cited evidence into sift analyze): every signal keeps its event_id"
tech-stack:
  added: []
  patterns:
    - "Pure pipeline module (typer/print/SQL/I-O/LLM-free), salience.py analog"
    - "Ported reference over event-id line stream rebuilt from event.raw (D-01)"
    - "Frozen Pydantic models + @property fuzzy accessors for verbatim map (D-04)"
key-files:
  created:
    - src/sift/pipeline/mcm.py
  modified:
    - pyproject.toml
    - tests/test_mcm.py
decisions:
  - "breakdown is non-Optional: an absent block is the EMPTY MemoryBreakdown (accessors -> None) not None — satisfies D-03 (None/empty) and the fixed test's unguarded .breakdown access under pyright strict"
  - "mcm_settings / current_memory_info are dict[str, str] (label -> raw value) — the test asserts settings.get('SmartHeap Cache Releasable') == 'true', so parse_abbrev_block returns raw strings, not (raw, human, unit) tuples"
  - "vendored docs/reference excluded from ruff (byte-verbatim port source); pyright already excludes via include=[src,tests]"
metrics:
  duration: ~35m
  completed: 2026-07-19
  tasks: 2
  files: 3
  commits: 2
---

# Phase 9 Plan 2: MCM Episode Detection + Denial-Time Memory Breakdown Summary

Deterministic, no-LLM MCM analyser `sift.pipeline.mcm.detect_episodes` that turns
stored `dsserrors` events into typed `McmEpisode` models — event-id-cited denial
episodes, denial-lifecycle signals, and the Format-A denial-time memory breakdown
— turning the 09-01 golden suite GREEN.

## What was built

- **`src/sift/pipeline/mcm.py`** — pure module mirroring `salience.py`'s contract
  (typer/print/SQL/I-O/LLM-free, zero network/subprocess/file-write).
  - Ported regex/marker constants from `docs/reference/analyze_dss8.py:38-66`,
    with a **widened `ABBREV_LINE_RE`** whose optional unit group accepts `Bytes`
    and tolerates a missing space, so `Memory Reserve = 0 (0Bytes)` is not dropped.
  - Frozen `extra="forbid"` models `LifecycleSignal`, `MemoryBreakdown`
    (verbatim `raw_map` + fuzzy `_get` accessors, D-04), `McmEpisode`.
  - Ported `parse_detail_block`, `parse_abbrev_block`, `_get`.
  - `detect_episodes`: rebuilds the event-id-carrying line stream from
    `event.raw` (D-01) in the store's D-06 order **without re-sorting**, runs the
    ported `prescan` (same-burst collapse / implicit recovery / EOF-open), scans
    the episode span for the pinned lifecycle anchors (D-02), associates the
    nearest in-span Info Dump backward from the denial banner (Q1), and sets
    `open_truncated` (D-07) and multi-node `fragmented` (D-06).

## Verification

- `uv run pytest tests/test_mcm.py -x` — **8/8 golden assertions pass** (single
  episode, lifecycle signals with in-span event_ids, absent-signal tolerance,
  breakdown values incl. physical/virtual split, MCM Settings incl. Memory
  Reserve, open/truncated, byte-identical determinism, fragmentation guard).
- `uv run pytest` — **478 passed, 8 deselected** (no regression).
- `uv run ruff check` — clean; `uv run pyright` — **0 errors** (strict).
- Prohibition guards: `git grep` finds no `CREATE TABLE|user_version|ALTER TABLE`
  (D-05), no `httpx|requests|socket|subprocess` (zero egress), no `set(` literal
  (determinism). No `sift mcm` CLI registration added.

## Deviations from Plan

### [Rule 3 - Blocking] breakdown made non-Optional (empty when absent)

- **Found during:** Task 2 (full-gate pyright pass).
- **Issue:** The plan describes `McmEpisode.breakdown | None`, but the fixed test
  contract accesses `episodes[0].breakdown.mcm_settings` with no None-guard
  (`tests/test_mcm.py:157`). Under pyright strict (which includes `tests/`) an
  Optional `breakdown` fails with `reportOptionalMemberAccess`.
- **Fix:** `McmEpisode.breakdown: MemoryBreakdown` (non-Optional); an absent or
  garbled block yields the **EMPTY** `MemoryBreakdown` (all maps empty, every
  accessor returns None) rather than `None`. D-03 explicitly permits
  "recorded absent (None / **empty**)", so this is compliant, honours the fixed
  contract, and never fabricates. Field-set was executor discretion per the plan.
- **Files modified:** `src/sift/pipeline/mcm.py`.
- **Commit:** ac8076f.

### [Rule 3 - Blocking] mcm_settings / current_memory_info are dict[str, str]

- **Found during:** Task 1/2.
- **Issue:** The reference `parse_abbrev_block` returns `(raw, human, unit)`
  tuples, but the test asserts `settings.get("SmartHeap Cache Releasable") == "true"`.
- **Fix:** `parse_abbrev_block` returns `label -> raw_value` strings. The widened
  regex still keeps `Memory Reserve` (with `0Bytes`) so nothing disappears.
- **Commit:** ac8076f.

### [Rule 3 - Blocking] ruff gate on vendored reference + test import order

- **Found during:** Task 2 full-gate.
- **Issue:** `uv run ruff check` flagged 35 errors in the vendored, byte-verbatim
  `docs/reference/analyze_dss8.py` (the port source, must not be modified) and one
  `I001` import-ordering error in `tests/test_mcm.py`.
- **Fix:** Added `extend-exclude = ["docs/reference"]` to `[tool.ruff]` (pyright
  already excludes it via `include=[src,tests]`). Applied the isort-only autofix
  to the test import block — a pure re-order; **no assertion changed** (verified
  by diff: 2 insertions / 3 deletions, import lines only).
- **Files modified:** `pyproject.toml`, `tests/test_mcm.py`.
- **Commit:** ac8076f.

## Known Stubs

None — `detect_episodes` is fully wired against the real adapter + store round-trip.

## Threat Flags

None — the module adds no new network/auth/file/schema surface; input is the
already-bounded stored `event.raw`, parsed with anchored regexes and a 60-line
block cap (threat register T-09-02-01..SC all mitigated/accepted, no egress path).

## Self-Check: PASSED

- `src/sift/pipeline/mcm.py` exists (FOUND).
- Commits 2d96f43 (constants+models+parsers) and ac8076f (detect_episodes) FOUND.
- All 8 golden tests + full suite green; ruff + pyright clean.
