---
phase: 10-diagnostic-flags-lead-up-attribution-sift-mcm-report-csv
verified: 2026-07-19T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
reconciliation_required:
  - item: "MCM-05 traceability markers are stale in REQUIREMENTS.md"
    detail: >-
      MCM-05 is fully delivered by the shipped code (sift mcm writes a
      deterministic report + CSV; verified live), yet REQUIREMENTS.md line 93
      still shows `- [ ] **MCM-05**` (unchecked) and line 186 shows
      `| MCM-05 | Phase 10 | Pending |`. MCM-03 and MCM-04 are already marked
      Complete. This is a bookkeeping discrepancy, not a code gap — flip the
      MCM-05 checkbox to `[x]` and the table row to `Complete` on phase closure.
---

# Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV — Verification Report

**Phase Goal:** The MCM analyser becomes a complete deterministic forensics command — `sift mcm <case>` emits machine-independent diagnostic flags, an auto-selected lead-up window, per-OID/per-Source/per-SID memory attribution, and both a human-readable report and a CSV export. Still zero-LLM and deterministic — figures are computed, never model-authored.
**Verified:** 2026-07-19
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Five deterministic %-of-HWM/total diagnostic flags per episode (working-set/other-processes/cube-MMF/SmartHeap/system-free-headroom), graded info/warn/critical, never absolute GB | ✓ VERIFIED | `compute_flags` (mcm.py:627-755) computes each flag as `part/whole*100`; `DiagnosticFlag.value_pct` is always a ratio (docstring + code); headroom inverted via `_grade(invert=True)`. Live run printed `critical — Working set is 65.4% of IServer virtual memory` (Hartford calibration anchor). Tests: `test_headroom_inverted_grading`, `test_flags_empty_breakdown_no_crash`, config default table matches RESEARCH |
| 2 | Lead-up window auto-selected from AvailableMCM-descent (% of HWM), non-interactive, no `input()` | ✓ VERIFIED | `select_window` (mcm.py:541-603) ports `prompt_window` minus the prompt; `WINDOW_WIDEST_PCT=25`. No `input()` in module (grep: only docstring negations). Tests: `test_select_window_descent`, `test_select_window_always_below_hartford`, `test_select_window_empty_leadup` |
| 3 | Memory in the window attributed by OID / Source / SID, resolving the one-OID/many-SID fan-out | ✓ VERIFIED | `attribute_window` (mcm.py:866-953) builds three top-level tables; fan-out sids recorded on OID row. Tests: `test_attribution_three_dimensions` (≥3 sids on fan-out OID), `test_sid_fanout_resolved` (per-SID sums == OID total; `set(oid.sids)==by_sid keys`). Live CSV: OID `A3EDD9C7…` = 2 SID rows summing to the OID total (fan-out resolved by session) |
| 4 | `sift mcm <case>` writes a deterministic report (MD/JSON) + CSV into `<case>/mcm/` | ✓ VERIFIED | `mcm` command (cli.py:1002-1069) always writes `mcm_report.md`/`.json` + `mcm_attribution.csv` under the resolved `<case>/mcm/`. Live run wrote both, printed summary, exit 0; re-run byte-identical (report + CSV `diff -q` clean). Tests: `test_mcm_writes_bundle`, `test_mcm_format_json`, `test_mcm_determinism`, `test_mcm_empty_case` |
| 5 | Two differently-sized machines under the same relative pressure produce identical flags (×2 scaled fixture → identical tuples) | ✓ VERIFIED | `test_machine_independence_scaled`: `hartford_deny_double.log` (every byte ×2) yields byte-identical `(dimension, severity, round(value_pct,3))` tuples AND identical window `threshold_pct`/`request_count` vs the original slice |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Load-Bearing Invariants

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Determinism (byte-identical re-run) | ✓ VERIFIED | Live `sift mcm` re-run produced byte-identical report + CSV; insertion-ordered dicts / `dict.fromkeys` throughout, no `set` iteration in ordered output; tests `test_analyse_mcm_determinism`, `test_two_episode_determinism_byte_identical`, `render_mcm_json` sort_keys+newline |
| Zero-LLM / zero-network | ✓ VERIFIED | `grep` for httpx/sqlite3/typer imports in `mcm.py` + `mcm_report.py` → NONE. Pure `list[Event] → models` / `McmAnalysis → str`; only I/O is the CLI-tier file write. 515 tests pass under autouse network guard |
| D-16 event_id provenance (`row.event_ids ⊆ episode ⊆ store`) | ✓ VERIFIED | `test_attribution_event_id_provenance` asserts every row's ids ⊆ `ep.event_ids` ⊆ store. Live CSV `event_ids` column populated (`;`-joined) on every row; `avail_timeline`/flags/attribution all carry real event_ids, never line numbers |
| Thresholds/window config-only (no per-run CLI knob) | ✓ VERIFIED | `McmThresholdsConfig`/`McmConfig` (config.py:67-103) `extra="forbid"`, `[mcm.thresholds]` block; `mcm` command exposes only `--format`/`--data-dir`. Test `test_mcm_no_threshold_or_window_flag` |
| Security: untrusted log → report/CSV sanitised | ✓ VERIFIED | `mcm_report.py` routes every log-sourced field through `markdown._field` (sanitise+escape); JSON `ensure_ascii=True`; CSV via stdlib `csv.writer(newline="")`; CLI stdout echoes through `_sanitise`. Renderer tests cover sanitisation goldens |

### Required Artifacts

| Artifact | Provides | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/mcm.py` | window/flags/attribution + models + `analyse_mcm` | ✓ VERIFIED | `McmEpisode.hwm_bytes`/`avail_timeline`, `EpisodeWindow`, `DiagnosticFlag`, `AttributionRow`/`Attribution`, `EpisodeAnalysis`/`McmAnalysis`, `select_window`/`compute_flags`/`attribute_window`/`analyse_mcm` all present, wired, exercised |
| `src/sift/render/mcm_report.py` | timeline-first MD + JSON report + CSV writer | ✓ VERIFIED | `render_mcm_markdown` (D-11 order), `render_mcm_json`, `write_attribution_csv` (7-col dimension-tagged) — all pure, sanitised, deterministic |
| `src/sift/config.py` | `[mcm.thresholds]` config | ✓ VERIFIED | `ThresholdPair`/`McmThresholdsConfig`/`McmConfig`, `SiftConfig.mcm`, defaults == RESEARCH table, `extra="forbid"` |
| `src/sift/cli.py` | `sift mcm` command | ✓ VERIFIED | `mcm(...)` + `McmFormat` StrEnum; writes bundle to `<case>/mcm/`, stdout summary, ADR-0007 exit codes |
| fixtures (`hartford_deny_predenial_multisid.log`, `hartford_deny_double.log`) | fan-out + scaled machine-independence | ✓ VERIFIED | Present under `tests/fixtures/mcm/`; drive the fan-out and ×2 tests |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `select_window` | `McmEpisode.avail_timeline`/`hwm_bytes` | window inputs populated by `detect_episodes` | ✓ WIRED |
| `analyse_mcm` | `select_window`+`compute_flags`+`attribute_window` | composed per episode into `McmAnalysis` | ✓ WIRED |
| `sift mcm` command | `analyse_mcm(store.query_events(), config.mcm.thresholds)` | CLI is the only I/O tier | ✓ WIRED (verified live) |
| `mcm_report.py` | `render/markdown._field` | reuse of sanitise/escape, no cli↔render cycle | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Bundle written + summary | `sift mcm hart` (dsserrors fixture ingested) | `Analysed 1 MCM denial episode; … Episode 1: critical — Working set is 65.4% of IServer virtual memory` | ✓ PASS |
| Determinism | re-run + `diff -q` report & CSV | both byte-identical | ✓ PASS |
| CSV schema + provenance | `cat mcm_attribution.csv` | 7 cols; oid/source/sid rows; `event_ids` `;`-joined; per-SID sums == OID total (33427456) | ✓ PASS |
| Gate: pytest | `uv run pytest -q` | 515 passed, 8 deselected (live) | ✓ PASS |
| Gate: pyright | `uv run pyright` | 0 errors, 0 warnings | ✓ PASS |
| Gate: ruff | `uv run ruff check` | All checks passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MCM-03 | 10-02 | Deterministic %-based diagnostic flags | ✓ SATISFIED | `compute_flags`; machine-independence + inverted-headroom tests; REQUIREMENTS.md already `Complete` |
| MCM-04 | 10-01, 10-03 | Auto lead-up window + OID/Source/SID attribution, fan-out by session | ✓ SATISFIED | `select_window` + `attribute_window`; fan-out + narrows + provenance tests; REQUIREMENTS.md already `Complete` |
| MCM-05 | 10-04 | Deterministic report + CSV via `sift mcm` | ✓ SATISFIED (code) — ⚠️ tracking marker stale | Command verified live; `test_mcm_*` green. REQUIREMENTS.md still marks MCM-05 `[ ]` / `Pending` — reconcile on closure (see frontmatter) |

No orphaned requirements: REQUIREMENTS.md maps exactly MCM-03/04/05 to Phase 10, all claimed by plans.

### Scrutiny Items

**1. MCM-05 tracking gap (flagged for reconciliation, NOT a code gap).** The code fully delivers MCM-05: `sift mcm <case>` writes a deterministic `mcm_report.md`/`.json` + `mcm_attribution.csv` with the per-OID/Source/SID attribution table — confirmed live (bundle written, exit 0, byte-identical re-run, CSV carries all three dimensions with event_id provenance). But REQUIREMENTS.md line 93 still shows `- [ ] **MCM-05**` and line 186 shows `| MCM-05 | Phase 10 | Pending |`, while its siblings MCM-03/04 read `Complete`. This is a stale traceability marker, not a missing capability. Action: flip both markers to Complete/`[x]` at phase closure. Does not block the goal.

**2. 10-03 descent-window deviation (resolved correctly).** The plan's Task-1 prose (attribute narrows to `[window.start … denial)`) initially conflicted with the by-SID fan-out must_have (≥3 SID rows over the full lead-up). The shipped resolution is sound and both windows are legitimate `EpisodeWindow`s that `select_window` itself emits:
- The fan-out / three-dimension / provenance assertions drive a **full-lead-up** window (`start_event_id=None`), where all distinct SIDs are visible — `test_sid_fanout_resolved` proves ≥3 by_sid rows summing to the fan-out OID total.
- `test_attribution_window_narrows_descent` separately proves the **descent** window is a *strict subset* of the full lead-up (`narrow_oid.granted_bytes < full_oid.granted_bytes`, event_ids ⊂, fewer SID rows).
- The shipped `analyse_mcm`/`sift mcm` uses the descent window; on the multi-SID fixture it narrows to the final 2 grants (live CSV shows the OID resolved into 2 SID rows). The fan-out-resolution *mechanism* (attribution split by SID) is genuinely exercised in both tests and the live run. MCM-04 success criterion #3 is met.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/sift/pipeline/mcm.py | 589 | `ponytail:` clamp-to-last edge annotation | ℹ️ Info | Properly-annotated edge ceiling for the (untested-rarity) never-descended case; anchors to a real event_id, not debt |

No `TBD`/`FIXME`/`XXX` debt markers in any modified file. No stub returns, no hardcoded-empty renders, no `input()` in the pipeline path.

### Human Verification Required

None — the goal is fully machine-verifiable and was verified end-to-end (gate green + live `sift mcm` run). No visual/UX/external-service or behavior-dependent-unexercised items.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria are verified in code and exercised by tests + a live end-to-end run; all load-bearing invariants (determinism, zero-LLM/zero-network, D-16 provenance, config-only thresholds, sanitisation) hold. The single follow-up is a non-blocking documentation reconciliation: flip the stale MCM-05 markers in REQUIREMENTS.md to Complete on phase closure to match the delivered code.

---

_Verified: 2026-07-19_
_Verifier: Claude (gsd-verifier)_
