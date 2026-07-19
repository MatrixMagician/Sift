---
phase: 10-diagnostic-flags-lead-up-attribution-sift-mcm-report-csv
plan: 01
subsystem: pipeline/mcm
status: complete
tags: [mcm, window, avail-timeline, mcm-04, d-13, d-16, determinism]
requires:
  - "sift.pipeline.mcm.detect_episodes / McmEpisode (Phase 9)"
  - "sift.pipeline.mcm regex constants AVAIL_MCM_RE / HWM_RE / SUCCESS_MARKER"
provides:
  - "McmEpisode.hwm_bytes + McmEpisode.avail_timeline (window inputs)"
  - "EpisodeWindow frozen model"
  - "select_window() pure non-interactive window selector"
  - "WINDOW_WIDEST_PCT = 25 constant"
  - "tests/fixtures/mcm/hartford_deny_predenial_multisid.log"
affects:
  - "Plan 10-03 attribution (walks window.start_event_id .. denial)"
  - "Plan 10-04 report window header"
tech-stack:
  added: []
  patterns:
    - "Reference prompt_window ported minus input() (D-13 fully automatic)"
    - "last-crossing-downward window over event_id-keyed timeline (D-16)"
key-files:
  created:
    - tests/fixtures/mcm/hartford_deny_predenial_multisid.log
  modified:
    - src/sift/pipeline/mcm.py
    - tests/test_mcm.py
decisions:
  - "select_window clamps the last_above-with-no-below edge to last_above (a real event_id, D-16) rather than the reference's line+1 which has no event_id in our model"
  - "McmEpisode.hwm_bytes / avail_timeline are required (no defaults) — detect_episodes must always populate them"
metrics:
  duration: ~14min
  completed: 2026-07-19
  tasks: 2
  files: 3
---

# Phase 10 Plan 01: MCM Lead-Up Window Selector Summary

Landed the two Phase-9-deferred window-input fields (`hwm_bytes`, `avail_timeline`)
on `McmEpisode` and the non-interactive `select_window` selector — the auto-window
half of MCM-04 (D-13), a faithful port of the reference `prompt_window` restricted
to the widest 25%-of-HWM descent threshold with the `input()` prompt dropped.

## What was built

- **`McmEpisode.hwm_bytes: int | None`** and **`McmEpisode.avail_timeline:
  tuple[tuple[str, int, int], ...]`** — each timeline entry is
  `(event_id, available_mcm_bytes, hwm_bytes)` over the lead-up succeeded grants,
  keyed to the owning `event_id` (D-16). `hwm_bytes` is the last lead-up sample's
  HWM or `None` for an empty lead-up.
- **`_avail_timeline(stream, ep)`** — private helper walking
  `range(span_start, denial_idx)` (lead-up, exclusive of the denial banner —
  Pitfall 1), reusing `SUCCESS_MARKER` / `AVAIL_MCM_RE` / `HWM_RE` verbatim.
- **`EpisodeWindow`** frozen Pydantic model (`threshold_pct`, `start_event_id`,
  `hwm_bytes`, `request_count`, `label`).
- **`select_window(ep) -> EpisodeWindow`** — pure, I/O-free, non-interactive:
  25%-of-HWM last-crossing-downward start; always-below → first entry; empty
  lead-up / `None` HWM → full-lead-up fallback (`threshold_pct=0`,
  `start_event_id=None`).
- **`WINDOW_WIDEST_PCT = 25`** — documents it is the reference
  `WINDOW_THRESHOLDS_PCT[0]` (Enter-default).
- **`hartford_deny_predenial_multisid.log`** — new fixture: one denial episode,
  5 lead-up succeeded grants across 5 SIDs, AvailableMCM descending 300e9→40e9
  across 25% of `HWM(PB)=400e9` (exercises the last-crossing-downward branch,
  not just the always-below fallback).

## Tasks

| Task | Name | Type | Commit |
|------|------|------|--------|
| 1 | RED: multi-SID fixture + failing window/avail_timeline tests | auto | a5b1da1 |
| 2 | GREEN: McmEpisode window fields + EpisodeWindow + select_window | auto (tdd) | f8f69f0 |

## Verification

- `uv run pytest tests/test_mcm.py` — 15 passed (Phase-9 + 4 new window/avail cases).
- `uv run pytest` — 485 passed, 8 deselected (full-suite regression clean).
- `uv run ruff check` — clean; `uv run pyright src/sift/pipeline/mcm.py` — 0 errors.
- Manual I/O guard: `mcm.py` imports no typer/sqlite3/httpx/csv.

## Success criteria

- `McmEpisode.hwm_bytes` / `avail_timeline` populated deterministically by
  `detect_episodes` — met.
- `select_window` selects the 25%-of-HWM descent window non-interactively (D-13),
  always-below → first entry, empty lead-up → full-lead-up fallback, every start
  keyed to a real `event_id` (D-16) — met.
- New pre-denial multi-SID descending fixture committed; MCM-04 window portion
  satisfied — met.

## Deviations from Plan

None — plan executed as written. One documented edge decision (not a plan
deviation): the reference `prompt_window` points one line past `last_above` when
no sample descends below threshold afterwards; that lineno has no `event_id` in
our event-keyed model, so `select_window` clamps to `last_above` to preserve the
D-16 real-`event_id` invariant. Marked with a `ponytail:` comment; the branch only
fires when AvailableMCM never descends below 25% before denial (not present in any
fixture).

## Known Stubs

None. `select_window` and `_avail_timeline` are fully wired to real stored events;
no placeholder/empty-data paths remain (an empty timeline is a legitimate recorded
absence per D-03, not a stub).

## Self-Check: PASSED
