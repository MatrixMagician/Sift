---
phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
verified: 2026-07-20T00:00:00Z
status: passed
score: 5/5 roadmap success criteria verified
behavior_unverified: 0
overrides_applied: 0
human_verification_resolved: 2026-07-20
human_verification:
  - test: "Confirm PERF-04's identical-span guarantee is acceptable on the full-lead-up fallback path (window.start_event_id is None)."
    resolution: "ACCEPTED as a documented D-03 limitation. The correlator cannot place an untimed event, so no code-correct alternative span exists; the Hartford reference data exercises the primary path only, where span identity was verified as genuine. No hazard added."
    expected: "attribute_window (mcm.py:903) takes ep.event_ids[0] UNCONDITIONALLY as its walk head; _resolve_span (perfmon.py:213-217) takes the first episode event that both resolves AND carries a ts. When event_ids[0] has ts=None the two heads are different events, so the trend span and the OID/Source/SID attribution span are not byte-identical, and no hazard is raised to say so. Decide whether this documented D-03 divergence satisfies PERF-04's 'identical time span' wording or needs a hazard."
    why_human: "Requirement-wording judgment, not a code defect. Both behaviours are deliberate and documented; the correlator cannot place an untimed event, so no purely-code-correct alternative exists. Needs the requirement owner to accept or reject."
  - test: "Confirm PERF-05's non-overlap hazard scope excludes host identity."
    resolution: "ACCEPTED — the parenthetical enumerates causes of time non-overlap; detecting the overlap failure satisfies PERF-05. Host identity stays PERFV2-02 backlog. PERF-05 is Complete."
    expected: "_hazard_non_overlap (perfmon.py:370-377) states in its own message that it covers time non-overlap ONLY, not host identity — a CSV from the wrong host whose clock overlaps the log will NOT trip it (deferred to PERFV2-02). REQUIREMENTS.md PERF-05 names 'wrong timezone, host, or day' as causes. Decide whether the parenthetical is a list of causes of time non-overlap (satisfied) or a requirement to detect host mismatch directly (partial)."
    why_human: "Scope-boundary judgment against requirement wording. The limitation is disclosed to the operator in the hazard text itself, so it is honest either way — but it changes whether PERF-05 is Complete or partial-scope."
---

# Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV — Verification Report

**Phase Goal:** An engineer sees each MCM denial episode corroborated by what the machine's memory counters were actually doing in the lead-up — and is warned loudly when the two artefacts cannot honestly be joined
**Verified:** 2026-07-20
**Status:** human_needed (5/5 criteria verified in code; 2 requirement-wording judgments escalated)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Each MCM episode annotated with at-denial value, slope, peak — over the **same** window MCM-04 produces | ✓ VERIFIED (see WARNING 1) | `_resolve_span` (perfmon.py:204-210) looks up `ea.window.start_event_id` — the exact field `attribute_window` uses as its head (mcm.py:903). `select_window` is never called from perfmon.py (D-02 confirmed by grep). `test_span_from_event_ids` asserts both bounds come from resolved `Event.ts`. `test_golden_trend_figures` reproduces 266042.0 at-denial and the hand-derived 0.6522 slope. |
| 2 | Same case twice on different machines → identical figures and flags; deterministic, no model | ✓ VERIFIED | No `set` iteration on any output path (`dict.fromkeys` at perfmon.py:251, 378, 390, 513); rounding at source (SLOPE_DP=4, _VALUE_DP=3); explicit `sorted()` with `event_id` tie-breakers (lines 261, 328, 474). No LLM/HTTP import in perfmon.py or perfmon_report.py. `test_hazards_deterministic_order` and `test_byte_identical_rerun` / `_json` pass. |
| 3 | Non-overlapping CSV/log gets a loud flag, not a fabricated correlation | ✓ VERIFIED (see WARNING 2) | `_hazard_non_overlap` returns `severity="critical"`; the caller (line 612-615) emits it INSTEAD of a trend table — `counters` is computed from `samples`, which is empty, so `_counter_trends` returns `()` at its guard (line 249). `test_non_overlap_hazard` asserts `group.counters == ()` and both time ranges named. `test_non_overlap_end_to_end` covers the ingested path. |
| 4 | Explicit flag for always-zero `Total MCM Denial` and mid-file counter-set drift; never correlation inputs | ✓ VERIFIED | `_hazard_denial_always_zero` (warn, numeric `!= 0.0` test, not string) and `_hazard_counter_set_drift` (warn, reads only the ingest-written `_DRIFT_ATTR`). D-16 confirmed: `MCM_DENIAL_COUNTER` appears nowhere in `_resolve_span`, `_in_span` or `_counter_trends`. `test_drift_hazard_reads_marker_not_row_widths` is a genuine counterfactual — strips the marker, keeps ragged rows, asserts the hazard goes silent. |
| 5 | `sift perfmon <case>` on a perfmon-only case (no DSSErrors log) → report + CSV, exit 0, no traceback | ✓ VERIFIED | `analyse_perfmon` takes the `_file_scope_groups` branch when `analysis.episodes` is empty (line 562), with `FULL_RANGE_LABEL` stating plainly that no correlation was performed. Empty-of-everything guarded before indexing (lines 249, 519-524). `test_no_dsserrors_log`, `test_no_episodes_no_events_yields_empty_groups`, `test_exit_codes` pass; orchestrator confirmed exit 0 on real Hartford artefacts. |

**Score:** 5/5 truths verified (0 present-but-behaviour-unverified)

### Locked Decisions from 13-CONTEXT.md

| Decision | Status | Evidence |
|----------|--------|----------|
| Span resolved by looking up BOTH `window.start_event_id` and `episode.denial_event_id` as real stored `Event.ts` — never string-parsed or fabricated | ✓ VERIFIED | perfmon.py:198-210. `McmEpisode.denial_ts` (a `str`) is never parsed anywhere in the module. `test_span_from_event_ids` asserts the decoy `1999` year from `denial_ts` appears in neither bound. |
| Missing/unresolvable timestamps get a hazard, never a guessed span | ✓ VERIFIED | perfmon.py:575-605 — `HAZARD_SPAN` warn, `start_ts=None`, `end_ts=None`, `counters=()`. No outward walk to a neighbouring timestamped event. `test_span_missing_ts_hazard` passes. |
| `PerfmonHazard` is a NEW sibling model, NOT `mcm.DiagnosticFlag` | ✓ VERIFIED | perfmon.py:84 defines its own `BaseModel` with `frozen=True, extra="forbid"`. `DiagnosticFlag` and `_grade` appear only in explanatory docstrings, never imported or called. |
| Single-sample span → `slope=None`, no `ZeroDivisionError`, no hazard | ✓ VERIFIED | Guarded before dividing (line 300-304), not via exception handler. `test_single_sample_no_zero_division` passes. |
| CSV formula-injection guard beyond `sanitise` | ✓ VERIFIED | `_csv_safe` (perfmon_report.py:203-228) prefixes `= + - @ TAB CR`. Applied to every string cell; numeric cells deliberately unguarded so a negative slope keeps its sign. Orchestrator confirmed empirically. |
| WR-03 qualified key = last two backslash segments, full path on further collision | ✓ VERIFIED | `_qualify_counter_names` (dssperfmon.py:126+), applied only to colliding names. `test_collision_qualified_keys_retain_both_counters` passes. |

### Citation Integrity

| Rendered figure | Cited id source | Status |
|-----------------|-----------------|--------|
| `at_denial` | `last_sample.event_id` — a real in-span `Event` | ✓ TRACEABLE |
| `peak` | `peak_sample.event_id` — `max()` first-maximal, earliest on tie | ✓ TRACEABLE |
| span bounds | `span.start.event_id` / `span.end.event_id` — resolved store events | ✓ TRACEABLE |
| hazard `event_ids` | resolved `Event.event_id`s, or the MCM-supplied ids the lookup failed on (with the message saying so) | ✓ TRACEABLE |

No fabricated identifier is constructible: every id emitted originates from an `Event.event_id` or from `McmEpisode`/`EpisodeWindow` fields that MCM itself derived from stored events. `_cited` caps at 10 and states the true total, so capping never silently hides evidence.

### Key Link Verification (cross-plan seams)

| From | To | Via | Status |
|------|----|-----|--------|
| `dssperfmon._DRIFT_ATTR` (13-03) | `perfmon._hazard_counter_set_drift` (13-04) | direct import, never redeclared | ✓ WIRED |
| `dssperfmon._RESERVED_ATTRS` (13-03) | `perfmon._counter_trends` sweep exclusion | direct import — single source of truth | ✓ WIRED |
| `_qualify_counter_names` (13-03) | `perfmon._find_counter_key` | handles BOTH bare and qualified spellings, returns a tuple so a non-zero instance cannot be masked | ✓ WIRED |
| `PerfmonAnalysis` (13-02) | renderer trio (13-05) | `TYPE_CHECKING` import + `model_dump` | ✓ WIRED |
| renderer trio (13-05) | `sift perfmon` (13-06) | function-local import in the command body | ✓ WIRED |
| `analyse_mcm` → `analyse_perfmon` | one `query_events()` result feeds both | cli.py — single call, verified in diff | ✓ WIRED |
| capped `stats.notes` (13-03) | `cli.py` note printing | cli.py:383/390 — **pre-existing**, unchanged | ✓ WIRED (see INFO 1) |

### Requirements Coverage

| Requirement | Source Plans | Status | Evidence |
|-------------|--------------|--------|----------|
| PERF-04 | 13-01, 13-02 | ✓ SATISFIED (primary path); see WARNING 1 for fallback | Window consumed not recomputed; both bounds event-id-resolved; golden figures reproduced |
| PERF-05 | 13-01, 13-03, 13-04 | ✓ SATISFIED for time non-overlap; see WARNING 2 for host | All three hazards implemented, graded, cited, deterministic |
| PERF-06 | 13-01, 13-05, 13-06 | ✓ SATISFIED | `sift perfmon` writes both artefacts; ADR 0007 exit codes; no-log case exits 0 |

No orphaned requirements — REQUIREMENTS.md maps exactly PERF-04/05/06 to Phase 13, and all three are claimed by plans.

### Behavioural Spot-Checks

| Behaviour | Command | Result | Status |
|-----------|---------|--------|--------|
| Full phase-13 suite | `uv run pytest tests/test_perfmon.py tests/test_perfmon_report.py tests/test_cli_perfmon.py -q` | 53 passed in 0.69s | ✓ PASS |
| Test enumeration | `pytest --collect-only -q` | 53 collected, every must_have truth mapped to a named test | ✓ PASS |
| Adapter WR-02/03/05 tests | `pytest tests/test_dssperfmon.py --collect-only` | 9 matching tests present (collision, drift marker, note cap, reserved-attr clobber) | ✓ PASS |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| all six touched files | `TODO`/`FIXME`/`XXX`/`TBD`/`HACK`/`PLACEHOLDER` | — | **NONE FOUND** — no unreferenced debt markers |
| perfmon.py, perfmon_report.py | `ponytail:` ceiling markers | — | NONE — no deliberate corners cut |

Empty-return patterns (`return ()`, `return None`) were inspected individually: each is a guarded, documented, tested branch (empty sample list, no accepted readings, no drift), not a stub.

## Findings

### WARNING 1 — PERF-04 span identity is not guaranteed on the full-lead-up fallback

`attribute_window` (mcm.py:903) uses `window.start_event_id or ep.event_ids[0]` — the fallback head is taken **unconditionally**. `_resolve_span` (perfmon.py:213-217) instead scans `ep.event_ids` for the first entry that both resolves **and** carries a non-`None` `ts`. When `event_ids[0]` has no timestamp the two heads are different events, so the trend span and the attribution span are not the identical span PERF-04's wording demands — and no hazard is raised to disclose the divergence.

This is a deliberate, documented D-03 decision (the correlator cannot place an untimed event on a time axis), and the primary path — the one Hartford exercises — is exactly identical. Escalated as a requirement-wording judgment, not a defect.

### WARNING 2 — PERF-05's non-overlap hazard is time-only, not host-aware

The hazard message itself states it covers time non-overlap only and defers multi-host correlation to PERFV2-02 (a v2 backlog id, not a later phase of this milestone). REQUIREMENTS.md PERF-05 names "wrong timezone, host, or day". If the parenthetical enumerates *causes* of time non-overlap, PERF-05 is complete; if it requires direct host-mismatch detection, PERF-05 is partial-scope. The limitation is disclosed to the operator in the rendered hazard, so the behaviour is honest either way.

### INFO 1 — 13-03 declared `src/sift/cli.py` as an artifact but made no change

Confirmed empty diff (matches the orchestrator's finding). The plan's key_link "capped `stats.notes` → `cli.py` note printing" is satisfied by pre-existing code at cli.py:383/390, which iterates `stats.notes` unchanged. Benign over-declaration in the plan, not a missing artifact.

### INFO 2 — `PerfmonAnalysis.hazards` is always `()`

No code path populates case-level hazards; every hazard is attached to a `TrendGroup`. The renderer's "Case-level correlation hazards" branch is therefore unreachable in production (it is exercised only by directly-constructed test analyses). Speculative field per YAGNI — harmless, but a candidate for deletion if v2 does not claim it.

### INFO 3 — residual reserved-prefix namespace collision

A counter literally named `counter.host` and one named `host` both map to the attrs key `counter.host` (dssperfmon.py:391-396), so one silently overwrites the other — the WR-03 class of bug in a corner `_qualify_counter_names` does not cover (it qualifies among counter paths, not against the reserved-prefix namespace). Requires attacker control of the CSV header and a contrived name pair. Not worth code now; worth knowing.

## Gaps Summary

No blockers. Every roadmap success criterion is achieved in code, not merely claimed: the window is genuinely consumed rather than recomputed, both span bounds are genuinely resolved from stored `Event.ts` with `denial_ts` string-parsing genuinely absent, all three PERF-05 hazards genuinely fire with real citations, and the perfmon-only case genuinely exits 0. The golden slope literal is hand-derived from raw fixture timestamps, and the drift test is a true counterfactual rather than a tautology.

Two items are escalated for a human requirement-owner decision (WARNINGs 1 and 2). Both concern how strictly requirement wording should be read at a documented scope boundary, not whether the implemented behaviour is correct or honest — in both cases the code discloses its own limitation to the operator rather than hiding it.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
