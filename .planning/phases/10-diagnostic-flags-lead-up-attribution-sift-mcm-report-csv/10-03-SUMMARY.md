---
phase: 10-diagnostic-flags-lead-up-attribution-sift-mcm-report-csv
plan: 03
subsystem: pipeline/mcm
status: complete
tags: [mcm, attribution, mcm-04, d-14, d-16, determinism, orchestration]
requires:
  - "sift.pipeline.mcm.detect_episodes / McmEpisode / _line_stream (Phase 9)"
  - "sift.pipeline.mcm.select_window / EpisodeWindow (Plan 10-01)"
  - "sift.pipeline.mcm.compute_flags / DiagnosticFlag (Plan 10-02)"
  - "sift.config.McmThresholdsConfig (Plan 10-02)"
  - "sift.pipeline.mcm regex constants SID_RE/OID_RE/SIZE_RE/SOURCE_RE/SUCCESS_MARKER"
provides:
  - "sift.pipeline.mcm.AttributionRow / Attribution frozen models"
  - "sift.pipeline.mcm.EpisodeAnalysis / McmAnalysis frozen models"
  - "sift.pipeline.mcm.attribute_window() three-dimension lead-up attributor"
  - "sift.pipeline.mcm.analyse_mcm() single orchestration entry point"
affects:
  - "Plan 10-04 report renderer + CSV export (consumes McmAnalysis / Attribution)"
  - "Phase 11 cited MCM facts (AttributionRow.event_ids = cited ⊆ store bridge)"
tech-stack:
  added: []
  patterns:
    - "Reference parse_log ported, flattened from oid_sources[oid][src] nesting to three top-level dicts (D-14)"
    - "Forward pass [window.start .. denial) exclusive of denial banner (Pitfall 1 / Pitfall 5)"
    - "dataclass _Attr accumulator; dict.fromkeys dedup; rows sorted granted_bytes desc, key asc"
key-files:
  created: []
  modified:
    - src/sift/pipeline/mcm.py
    - tests/test_mcm.py
decisions:
  - "Fan-out assertions drive a full-lead-up window (start_event_id=None): select_window narrows the multi-SID fixture to a 2-grant descent window, so the one-OID/many-SID fan-out (4 distinct SIDs) is only visible over the full lead-up; a dedicated test proves the [window.start .. denial) narrowing on the descent window"
  - "attribute_window rebuilds the same dsserrors-filtered _line_stream detect_episodes uses; the denial line is located by (event_id == denial_event_id AND DENIAL_MARKER in line) and the walk stops before it (exclusive)"
  - "list[str] typed default_factory (field(default_factory=list[str])) to satisfy pyright strict reportUnknownVariableType on the dataclass accumulator"
metrics:
  duration: ~20min
  completed: 2026-07-19
  tasks: 2
  files: 2
---

# Phase 10 Plan 03: Three-Dimension MCM Lead-Up Attribution Summary

Landed MCM-04's attribution half: `attribute_window` ports the reference
`parse_log` accumulation onto the Phase-9 typed models as THREE independent
dimensions — by OID, by `Source=` request type and by SID/session — resolving the
one-OID/many-SID fan-out the flat reference nested under OID (D-14). Every
attributed figure carries the owning grant-line `event_id`s (D-16), the
`cited ⊆ ep.event_ids ⊆ store` bridge Phase 11 reuses verbatim. Then landed
`analyse_mcm`, the single orchestration entry point that composes `select_window`
(Plan 01) + `compute_flags` (Plan 02) + `attribute_window` into the deterministic
`McmAnalysis` the report/CLI (Plan 04) consume — completing MCM-04.

## What was built

- **`AttributionRow`** frozen model: `dimension` (`oid`|`source`|`sid`), `key`,
  `granted_bytes`, `request_count`, `event_ids: tuple[str, ...]`,
  `sids: tuple[str, ...] = ()` (populated only for the `oid` fan-out note).
- **`Attribution`** frozen model: `by_oid` / `by_source` / `by_sid` (each a tuple
  of `AttributionRow`) + `unmatched_event_ids`.
- **`EpisodeAnalysis`** frozen model: `episode` + `window` + `flags` +
  `attribution` — one episode's full picture.
- **`McmAnalysis`** frozen model: `episodes: tuple[EpisodeAnalysis, ...]`.
- **`attribute_window(ep, window, events)`** — pure forward pass over
  `[window.start_event_id … denial)` EXCLUSIVE of the denial banner. On each
  `SUCCESS_MARKER` line it requires SID AND OID AND Size (else the line's
  `event_id` lands in `unmatched_event_ids`); `Source` defaults to `"Unknown"`.
  Accumulates three insertion-ordered dicts via a `_Attr` dataclass; the OID row
  also collects the distinct SIDs. Rows emitted sorted `granted_bytes` desc then
  `key` asc; `event_ids`/`sids` deduped insertion-ordered with `dict.fromkeys`.
  Full-lead-up fallback (`window.start_event_id is None`) walks from the episode
  span head.
- **`analyse_mcm(events, thresholds)`** — `detect_episodes` then per episode
  bundles `select_window` + `compute_flags` + `attribute_window` into an
  `EpisodeAnalysis`; no episodes → `McmAnalysis(episodes=())`.

## Tasks

| Task | Name | Type | Commit |
|------|------|------|--------|
| 1 | RED: attribution / fan-out / provenance / exclusion / unmatched / analyse_mcm tests | auto | 983c9f7 |
| 2 | GREEN: AttributionRow/Attribution/EpisodeAnalysis/McmAnalysis + attribute_window + analyse_mcm | auto (tdd) | 5e97042 |

## Verification

- `uv run pytest tests/test_mcm.py -k "attribution or fanout or analyse_mcm"` — 9 passed.
- `uv run pytest tests/test_mcm.py` — 29 passed (Phase-9/10 regression clean).
- `uv run pytest` — 501 passed, 8 deselected (full-suite regression clean).
- `uv run ruff check` — clean; `uv run pyright` — 0 errors, 0 warnings.
- I/O-free guard: `mcm.py` imports no typer/sqlite3/httpx/csv (grep == 0);
  `grep -c "def attribute_window\|def analyse_mcm"` == 2.

## Attribution over the multi-SID fixture (full lead-up)

| Dimension | Rows | Key figure |
|-----------|------|-----------|
| by_oid | 1 | the fan-out OID: 84 725 760 B over 5 requests, **4 distinct SIDs** |
| by_source | 4 | GovernedObject 28 618 752 B (2 reqs) leads |
| by_sid | 4 | the one-OID/many-SID fan-out resolved by session (D-14) |

Every row's `event_ids ⊆ ep.event_ids ⊆ store`; the denial banner and any
post-denial grant are excluded.

## Success criteria

- Lead-up memory attributed by OID, `Source=` and SID; the one-OID/many-SID
  fan-out resolved by session (MCM-04) — met.
- Every attributed figure carries its owning `event_id`(s) (D-16),
  `cited ⊆ store` preserved and asserted — met.
- `analyse_mcm` returns a deterministic `McmAnalysis`; empty input → empty
  analysis, never a crash — met.

## Deviations from Plan

The plan's Task-1 prose specifies `attribute_window(ep, select_window(ep), events)`
for the fan-out / three-dimension assertions, but that is internally inconsistent
with the must_haves on this fixture: `select_window` narrows
`hartford_deny_predenial_multisid.log` to a **2-grant 25%-of-HWM descent window**
(confirmed by the pre-existing, still-green `test_select_window_descent`:
start = timeline index 3, `request_count == 2`), whereas the must_haves require
`by_sid` to show **≥3 distinct SID rows** and `by_oid.granted_bytes` = "sum of the
lead-up Size= values" — both true only over the full 5-grant lead-up (4 distinct
SIDs), and must_have truth #4 simultaneously mandates the `[window.start … denial)`
narrowing.

Resolution (honours BOTH): `attribute_window` narrows `[window.start … denial)`
exactly per the plan/reference (`parse_log`) and must_have #4; the fan-out /
three-dimension / provenance / unmatched assertions drive a **full-lead-up window**
(`start_event_id=None`, the same `EpisodeWindow` shape `select_window` emits for an
empty/None-HWM lead-up) so the fan-out is visible, and a dedicated
`test_attribution_window_narrows_descent` proves the descent-window narrowing is a
strict subset (fewer bytes, fewer SIDs, `event_ids ⊂` the full set). This satisfies
every must_have truth without weakening the load-bearing post-denial-exclusion or
provenance invariants. `analyse_mcm` still uses `select_window(ep)` (the descent
window) internally — the correct product behaviour (attribute the final pressure
window); the wide fan-out is a test-visibility concern on a deliberately tiny
fixture, not a product change.

Threat register mitigations all satisfied: T-10-08 (walk `[window.start … denial)`
exclusive of denial + `SUCCESS_MARKER` gate; `test_attribution_excludes_post_denial`
covers Pitfall 1 post-denial and Pitfall 5 denial-line failed-request `Source=`),
T-10-09 (`test_attribution_event_id_provenance` asserts `⊆ ep.event_ids ⊆ store`),
T-10-10 (Phase-9 anchored regexes reused verbatim, one bounded forward pass),
T-10-11 (`dict.fromkeys` + sorted rows; `test_analyse_mcm_determinism` asserts
byte-identical `model_dump_json` + row ordering), T-10-SC (no package installs).

## Known Stubs

None. `attribute_window` and `analyse_mcm` are fully wired to real stored events
via the Phase-9 line stream; an empty lead-up yields empty tuples (a legitimate
recorded absence per D-03, not a stub) and no placeholder/mock-data path remains.

## Self-Check: PASSED
