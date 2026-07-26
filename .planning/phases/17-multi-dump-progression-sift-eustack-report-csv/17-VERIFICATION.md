---
phase: 17-multi-dump-progression-sift-eustack-report-csv
verified: 2026-07-26T12:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: No — initial verification
---

# Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV Verification Report

**Phase Goal:** One command turns a case's thread dumps into a deterministic report —
full analysis from a single dump, per-signature progression when several are present —
working with no DSSErrors log in the case.
**Verified:** 2026-07-26
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `sift eustack <case>` on a case with only eu-stack dumps and no DSSErrors log produces Markdown + CSV and exits 0 | ✓ VERIFIED | `tests/test_cli_eustack.py::test_eustack_writes_bundle`, `::test_eustack_no_dsserrors_log`, `::test_eustack_empty_case`, `::test_eustack_missing_case_exit_one`, `::test_eustack_bad_format_exit_two` all pass. Independently reproduced live: built a scratch case from `tests/fixtures/eustack/progression/*.txt` via `sift new`/`sift ingest`, ran `sift eustack prog3 --data-dir ...` → exit 0, `eustack_report.md` + `eustack_signatures.csv` written under `<case>/eustack/`. |
| 2 | Single-dump case yields full classification/saturation report; 2+-dump case additionally reports per-signature population deltas and which populations advanced | ✓ VERIFIED | Single-dump: `test_eustack_writes_bundle` (Task 1, 17-01) renders role composition + saturation tables from one dump (D-11 N=1 case). Multi-dump: `tests/test_eustack_progression.py::test_step_and_overall_deltas_disagree_on_grew_then_shrank`, `::test_appeared_and_vanished_signatures`; `tests/test_eustack_report.py::test_progression_section_lists_only_changed_signatures`, `::test_progression_section_shows_step_and_overall_deltas`, `::test_progression_section_calls_out_appeared_and_vanished`. Live reproduction rendered a `## Progression` table with 4 changed signatures (warehouse/parked/newcomer/departing) and their counts/step-deltas/overall-delta/status. |
| 3 | Dump ordering states its basis explicitly; unresolvable ordering flagged loudly, no timestamp invented | ✓ VERIFIED | `tests/test_eustack_progression.py::test_order_by_timestamp_ignores_filename_order` (D-01), `::test_order_fallback_flagged_when_any_dump_untimestamped`, `::test_order_fallback_still_renders_progression`, `::test_no_timestamp_is_invented` (D-02, ADR 0012 precedent). Live reproduction: a 4-dump case containing the untimestamped `dump_delta_nots.txt` fixture rendered `Order basis: ordered by sorted source file name (at least one dump carries no dump-time timestamp)` and a bold `**WARN** (dump_order_basis): ...` flag paragraph, with the untimestamped dump's `Timestamp` cell rendering as the em-dash absent marker (never a fabricated stamp) — progression still rendered under the flag, not suppressed. |
| 4 | Progression expressed as signature-population change; no unqualified per-TID causal claim | ✓ VERIFIED | `tests/test_eustack_progression.py::test_no_per_tid_claim_in_progression_strings`, `tests/test_eustack_report.py::test_progression_section_is_population_phrased` — word-boundary bans on continuity verbs (persisted/remained/stayed/"still blocked") and concrete `TID\s*\d+` value tokens, both non-vacuity-guarded. `PROGRESSION_SCOPE_NOTE`'s bare mention of "TID reuse" is judged in scope per the phase's own documented and tested distinction (explaining why continuity *cannot* be established is the D-10 rationale itself, not a violation) — this verifier agrees with that scoping on inspection of the actual regex (`\bTID\W{0,3}\d+\b`) and the surrounding sentence. |
| 5 | Re-running on an unchanged case produces byte-identical report + CSV; CSV string cells with C++ symbol text pass the formula-injection guard | ✓ VERIFIED | `tests/test_cli_eustack.py::test_eustack_byte_identical_rerun`, `::test_eustack_byte_identical_rerun_json`, `::test_eustack_multi_dump_byte_identical_rerun`; `tests/test_eustack_report.py::test_csv_safe_guards_formula_trigger_symbol` (extended post-CR-02 to also assert the `step_deltas` cell is quoted). Independently reproduced live: ran `sift eustack` twice on an unchanged 4-dump case — `diff` on both the Markdown report and the CSV showed zero differences (byte-identical). CR-02 (the reviewer-found gap where `step_deltas` bypassed `_csv_safe`) is confirmed fixed at `src/sift/render/eustack_report.py:400`. |

**Score:** 5/5 truths verified (0 present-but-behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/eustack_progression.py` | dump grouping, D-01/D-02 ordering, `compute_progression`, frozen models | ✓ VERIFIED | All symbols present (`group_dumps`, `resolve_dump_order`, `compute_progression`, `analyse_eustack_bundle`, `DumpSlice`, `OrderingFlag`, `SignatureProgression`, `ProgressionAnalysis`, `EustackBundle`); CR-01 fix confirmed at line 194 (`next((...), None)` with `None`-safe filtering, replacing the reviewer-reproduced bare-`next()` `StopIteration` crash) |
| `src/sift/render/eustack_report.py` | markdown/json/csv renderers, `_csv_safe` reuse, D-05/D-07/D-08/D-09 rendering | ✓ VERIFIED | `render_eustack_markdown`, `render_eustack_json`, `write_eustack_signatures_csv`, `_eustack_csv_header`, `_dumps_section`, `_progression_table` all present; `_csv_safe`/`_field` imported not reimplemented (`grep -c "def _csv_safe"` → 0); CR-02 fix confirmed — `step_deltas` cell wrapped in `_csv_safe(...)` at line 400; WR-01 fix confirmed — saturation sub-table helpers now typed against concrete `PoolOccupancy`/`LockSite`/`DependencyWait`/`SaturationFlag` under `TYPE_CHECKING`, no `type: ignore[attr-defined]` remains; WR-02 fix confirmed — `_SIGNATURES_SCOPE_NOTE` rendered above `## Signatures` |
| `sift eustack` CLI command | standalone `sift mcm`/`sift perfmon`-pattern command | ✓ VERIFIED | `src/sift/cli.py:1318` — `case`, `--format`, `--data-dir` only (`sift eustack --help` confirms no extra flag); ADR 0007 exit-code contract documented in docstring and tested |
| `tests/fixtures/eustack/progression/*` | synthetic multi-dump fixture set + provenance script | ✓ VERIFIED | 4 dump files + `derive_progression_fixtures.py`; no customer identifiers (`grep -rniE "iserver-1|hnyjbci|castorserver"` → no match, confirmed by 17-02's own acceptance gate); reversed-filename-order (D-01 discriminator) and warehouse 3→7→5 grew-then-shrank (D-08 discriminator) confirmed live in the CSV (`5,7,3,7` counts columns in resolved dump order, `step_deltas` = `2;-4;4`) |
| `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py` | full test coverage of the phase | ✓ VERIFIED | 37 tests across the three modules, all passing (`uv run pytest tests/test_eustack_progression.py tests/test_eustack_report.py tests/test_cli_eustack.py -q` → 37 passed) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `cli.eustack` | `analyse_eustack_bundle` | direct call, `store.query_events()` piped through once | ✓ WIRED | `src/sift/cli.py:1360-1362` |
| `analyse_eustack_bundle` | `analyse_eustack`/`analyse_saturation` (Phase 15/16, frozen) | leaf-module import, read-only consumption | ✓ WIRED | `eustack_progression.py` imports from `sift.pipeline.eustack` and is imported by nothing in that module (confirmed by reading both files) |
| `render.eustack_report` | `render.perfmon_report._csv_safe` | import, not copy | ✓ WIRED | `from sift.render.perfmon_report import _csv_safe`; identity-asserted in `test_csv_safe_guards_formula_trigger_symbol` (`assert eustack_report._csv_safe is _perfmon_csv_safe`) |
| `render.eustack_report` | `render.markdown._field` | import, escaping on every dynamic cell | ✓ WIRED | confirmed by reading `_dumps_section`/`_progression_table`/`_signature_table` — every dynamic cell passes through `_field` |
| `cli.eustack` | `store.case_db_path` | bundle-dir containment | ✓ WIRED | `eustack_dir = case_db_path(config.data_dir, case).parent / "eustack"` — same pattern `mcm`/`perfmon` use |
| `resolve_dump_order` | `Event.ts`/`Event.ts_confidence` | one thread event per dump, never a preamble re-scan | ✓ WIRED | confirmed by reading `resolve_dump_order` (lines 193-205) |
| `compute_progression` | `SignatureGroup.frames` | full-tuple join key | ✓ WIRED | confirmed by reading `compute_progression` (lines 251-261) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite | `uv run pytest -q` | 779 passed | ✓ PASS |
| Phase-scoped tests | `uv run pytest tests/test_eustack_progression.py tests/test_eustack_report.py tests/test_cli_eustack.py -q` | 37 passed | ✓ PASS |
| Lint | `uv run ruff check src/sift tests` | clean (`[]`) | ✓ PASS |
| Types | `uv run pyright src/sift` | 0 errors, 0 warnings, 0 informations | ✓ PASS |
| Live end-to-end run (4-dump case, includes untimestamped fixture) | `sift new` → `sift ingest` → `sift eustack` | exit 0; report + CSV written; D-02 basis + flag rendered; progression table populated | ✓ PASS |
| Byte-identical re-run | `sift eustack` run twice on unchanged case, `diff` | zero diff on both `eustack_report.md` and `eustack_signatures.csv` | ✓ PASS |
| CR-01 regression (threadless dump group) | `tests/test_eustack_progression.py::test_order_resolves_without_crash_when_a_dump_has_no_thread_events` | passes; falls back to D-02 filename ordering with a flag instead of crashing | ✓ PASS |
| CR-02 regression (unguarded `step_deltas` CSV cell) | `tests/test_eustack_report.py::test_csv_safe_guards_formula_trigger_symbol` | passes; `step_deltas` cell quoted by `_csv_safe` | ✓ PASS |
| Debt-marker scan | `grep -n -E "TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER"` over all 7 phase-touched files | no matches | ✓ PASS |
| Reviewed commit hashes exist | `git cat-file -e <hash>` for all 17 commits named in SUMMARYs/REVIEW/REVIEW-FIX | all present | ✓ PASS |

### Probe Execution

Not applicable — this phase is a rendering/CLI phase with no `scripts/*/tests/probe-*.sh` declared in any PLAN/SUMMARY, and no probe-based verification convention is referenced anywhere in the phase artifacts. Step 7c: SKIPPED (no probes declared for this phase).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| EUS-07 | 17-01 (D2), 17-02 (D2/D3/D4/D5), 17-03 (D1/D2) | Full analysis from a single dump; per-signature population deltas at 2+ dumps | ✓ SATISFIED | See truths 1-2, 4 above |
| EUS-08 | 17-02 (D1), 17-03 (D5) | Dumps ordered without invented timestamps; basis stated; unresolvable ordering flagged loudly | ✓ SATISFIED | See truth 3 above |
| EUS-09 | 17-01 (D1/D3/D4/D5), 17-03 (D6/D7) | `sift eustack <case>` — deterministic report + CSV, no DSSErrors log needed | ✓ SATISFIED | See truths 1, 5 above |

No orphaned requirements: REQUIREMENTS.md's Phase 17 traceability row lists exactly EUS-07/EUS-08/EUS-09, and all three appear in at least one plan's `requirements:` frontmatter field (`17-01`: `[EUS-09]`; `17-02`: `[EUS-07, EUS-08]`; `17-03`: `[EUS-07, EUS-09]`).

### Anti-Patterns Found

None. Debt-marker scan (`TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`, case-sensitive per the project's own convention) over all seven phase-touched files returned zero matches. No stub returns, no hardcoded empty data on an output path, no console.log-only implementations. The two Critical and two Warning findings from the deep code review (`17-REVIEW.md`) were independently re-verified as fixed by reading the current source (CR-01 at `eustack_progression.py:194`, CR-02 at `eustack_report.py:400`, WR-01's `TYPE_CHECKING` imports, WR-02's `_SIGNATURES_SCOPE_NOTE`) and by the reviewer's own regression tests passing in the current full suite (779 tests).

### Human Verification Required

None. Every must-have truth resolved to VERIFIED against direct evidence (automated tests independently re-run, source code read, plus a live end-to-end CLI reproduction of the multi-dump/D-02-fallback/byte-identity path). No behaviour-dependent truth was left unexercised — the state-transition-shaped claims in this phase (ordering fallback, population delta computation, byte-identical re-run) are all covered by passing tests that were re-run in this verification pass, not merely claimed by SUMMARY.md.

### Gaps Summary

None. All 5 ROADMAP success criteria verified against the actual codebase, not SUMMARY.md claims. The two Critical findings from the phase's own deep code review (a real `StopIteration` crash on a threadless dump group, and a real CSV formula-injection gap on the `step_deltas` cell) were independently reproducible against the pre-fix code per `17-REVIEW.md`'s own repro transcripts, and are now confirmed fixed by reading the current source and by an independent live reproduction. Full suite (779 tests), `ruff check`, and `pyright` are all clean.

---

_Verified: 2026-07-26_
_Verifier: Claude (gsd-verifier)_
