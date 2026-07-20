---
phase: 13
slug: episode-correlation-hazard-flags-sift-perfmon-report-csv
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-20
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pyproject.toml:44-54`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`; `testpaths = ["tests"]` |
| **Quick run command** | `uv run pytest tests/test_perfmon.py tests/test_cli_perfmon.py tests/test_dssperfmon.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5 s quick · ~60 s full |

**Marker note:** `addopts = "-m 'not perf and not live and not packaging'"` — the default suite
excludes those three markers. Phase 13 tests must carry **no marker** so they run by default.

**Zero-network rule** [VERIFIED `tests/conftest.py:34-54`]: autouse `_no_network` fixture
monkeypatches `socket.socket.connect` to raise. Nothing in this phase needs network.

**Filesystem isolation** [VERIFIED `tests/conftest.py:15-32`]: autouse `_isolate_dirs` redirects
data/config dirs to tmp, so `load_config().data_dir` points at tmp — this is what lets the CLI
tests assert on written bundle paths.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_perfmon.py tests/test_cli_perfmon.py tests/test_dssperfmon.py -x`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** `uv run ruff check && uv run pyright && uv run pytest` all clean
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

> Filled retroactively by `validate-phase` against the executed phase. Every row is bound to
> the real test that ships the behaviour; `-k` selectors are the actual test-function names.
> Verified green: `uv run pytest tests/test_perfmon.py tests/test_cli_perfmon.py tests/test_dssperfmon.py`
> → **71 passed** (2026-07-20).

| Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-02 | W1 | PERF-04 | — | Span resolves from `start_event_id` + `denial_event_id` | unit | `uv run pytest tests/test_perfmon.py -k span_from_event_ids` | ✅ | ✅ green |
| 13-02 | W1 | PERF-04 | — | D-03 fallback when `start_event_id is None` | unit | `uv run pytest tests/test_perfmon.py -k span_full_leadup_fallback` | ✅ | ✅ green |
| 13-02 | W1 | PERF-04 | — | D-04 hazard when a boundary has `ts=None` | unit | `uv run pytest tests/test_perfmon.py -k span_missing_ts_hazard` | ✅ | ✅ green |
| 13-02 | W1 | PERF-04 | — | At-denial / slope / peak match hand-computed goldens | unit | `uv run pytest tests/test_perfmon.py -k golden_trend_figures` | ✅ | ✅ green |
| 13-02 | W1 | PERF-04 | — | Single-sample span yields `slope=None`, no `ZeroDivisionError` (A1) | unit | `uv run pytest tests/test_perfmon.py -k single_sample_no_zero_division` | ✅ | ✅ green |
| 13-02 | W1 | PERF-04 | T-13-NONFINITE | `nan`/`inf` cell excluded, row retained, reported (D-11) | unit | `uv run pytest tests/test_perfmon.py -k non_finite_excluded` | ✅ | ✅ green |
| 13-04 | W1 | PERF-05 | — | Zero in-span samples → `critical` non-overlap hazard | unit | `uv run pytest tests/test_perfmon.py -k non_overlap_hazard` | ✅ | ✅ green |
| 13-04 | W1 | PERF-05 | — | All-zero `Total MCM Denial` with episodes → `warn` | unit | `uv run pytest tests/test_perfmon.py -k mcm_denial_always_zero` | ✅ | ✅ green |
| 13-04 | W1 | PERF-05 | — | No episodes → no always-zero hazard (D-14) | unit | `uv run pytest tests/test_perfmon.py -k no_episodes_no_zero_hazard` | ✅ | ✅ green |
| 13-04 | W1 | PERF-05 | — | Drift marker in `attrs` → `warn` drift hazard | unit | `uv run pytest tests/test_perfmon.py -k counter_set_drift_hazard` | ✅ | ✅ green |
| 13-06 | W2 | PERF-06 | T-13-PATH | Bundle written: report + CSV, exit 0 | integration | `uv run pytest tests/test_cli_perfmon.py -k bundle_written` | ✅ | ✅ green |
| 13-06 | W2 | PERF-06 | — | `--format json` writes `perfmon_report.json` | integration | `uv run pytest tests/test_cli_perfmon.py -k json_format` | ✅ | ✅ green |
| 13-06 | W2 | PERF-06 | T-13-ERRLEAK | Missing case → exit 1; bad `--format` → exit 2 | integration | `uv run pytest tests/test_cli_perfmon.py -k exit_codes` | ✅ | ✅ green |
| 13-06 | W2 | PERF-06 | — | Perfmon CSV, **no DSSErrors log**, exit 0, no traceback (crit. 5) | integration | `uv run pytest tests/test_cli_perfmon.py -k no_dsserrors_log` | ✅ | ✅ green |
| 13-06 | W2 | Crit. 2 | — | Byte-identical bundle on re-run (determinism) | integration | `uv run pytest tests/test_cli_perfmon.py -k byte_identical_rerun` | ✅ | ✅ green |
| 13-05 | W2 | PERF-06 | T-13-CSVINJ | Formula-prefixed counter name is quote-escaped in CSV (A3) | unit | `uv run pytest tests/test_perfmon_report.py -k csv_formula_guard` | ✅ | ✅ green |
| 13-03 | W1 | WR-03 | — | Colliding short names both retained | unit | `uv run pytest tests/test_dssperfmon.py -k collision_qualified_keys_retain_both_counters` | ✅ | ✅ green |
| 13-03 | W1 | WR-03 | — | 22-key spelling unchanged (regression guard, folded into the collision test) | unit | `uv run pytest tests/test_dssperfmon.py -k three_identical_paths_stay_unique` | ✅ | ✅ green |
| 13-03 | W1 | WR-02 | T-13-DOS | Note list capped, summary line emitted | unit | `uv run pytest tests/test_dssperfmon.py -k notes_capped` | ✅ | ✅ green |
| 13-03 | W1 | WR-05 | T-13-ATTRKEY | Drifted event carries the `attrs` marker | unit | `uv run pytest tests/test_dssperfmon.py -k drift_marker_in_attrs` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Two seeded selectors were corrected against the shipped tests (behaviour was covered, the paths
were stale):** `csv_formula_guard` lives in `tests/test_perfmon_report.py` (not `test_perfmon.py`),
and the "Hartford 22 keys unchanged" regression guard is folded into
`test_three_identical_paths_stay_unique` (`tests/test_dssperfmon.py:398-423`, an explicit-literal
assertion of the slice's 22 counter keys) rather than a separately-named test.

---

## Wave 0 Requirements

- [x] `tests/test_perfmon.py` — correlator unit tests (PERF-04, PERF-05) — **shipped, 27 tests**
- [x] `tests/test_cli_perfmon.py` — bundle / exit-code integration tests (PERF-06) — **shipped, 16 tests**
- [x] `tests/fixtures/dssperfmon/` synthetic fixtures — colliding short names (WR-03), mid-file
      column drift (WR-05 / hazard 3), and `nan`/`inf` cell (D-11) — **shipped** (see
      `test_dssperfmon.py` collision/drift/non-numeric tests)
- [x] A perfmon-only case fixture (perfmon CSV, **no DSSErrors log**) for success criterion 5 —
      **shipped** (`test_no_dsserrors_log`, `test_perfmon_only_case_has_no_dsserrors_events`)
- [x] Golden-figure fixture — `hartford_deny_slice.csv` (a cut slice around the denial),
      not all 13,596 rows — **shipped**
- [x] No framework install needed — pytest already configured

**Existing fixture layout to follow** [VERIFIED]: `tests/fixtures/{dsserrors,dssperfmon,eustack,journald,mcm}/`.
The build-a-real-case helper idiom is at `tests/test_cli_mcm.py:28-45` — set `adapter.input_root`,
`list(adapter.parse(...))`, `CaseStore(db_path).insert_events(events)`, `store.close()` in `finally`.
Clone it with `DssperfmonAdapter`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end run on the real Hartford deny case | PERF-04/05/06 | Real customer artefact lives outside the repo (`~/Downloads/hartford/`) and is too large to ship as a fixture | `uv run sift perfmon <hartford-case>` — confirm each episode shows at-denial / slope / peak, the always-zero `Total MCM Denial` hazard fires, and the bundle writes report + CSV with exit 0 |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s (quick suite ~0.7s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-07-20 — all 20 mapped behaviours have green automated tests; 0 gaps.

---

## Validation Audit 2026-07-20

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

State A audit of a completed phase. VALIDATION.md was stale (`draft`, every map row `TBD`/pending)
while the phase shipped 90 tests (71 in the quick suite, all green). No behaviour was uncovered —
every mapped row bound to a real, passing test. Two seeded `-k` selectors pointed at the wrong file
(`csv_formula_guard` → `test_perfmon_report.py`; the "22 keys" regression guard → folded into
`test_three_identical_paths_stay_unique`); both corrected in place. No test files generated, no
auditor spawn needed.
