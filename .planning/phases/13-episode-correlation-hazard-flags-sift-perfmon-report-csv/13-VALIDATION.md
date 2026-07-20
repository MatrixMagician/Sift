---
phase: 13
slug: episode-correlation-hazard-flags-sift-perfmon-report-csv
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
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

> Seeded from RESEARCH.md § Validation Architecture. Task IDs are bound by the planner —
> `validate-phase` fills the Task ID / Plan / Wave columns once PLAN.md files exist.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | PERF-04 | — | Span resolves from `start_event_id` + `denial_event_id` | unit | `uv run pytest tests/test_perfmon.py -k span_from_event_ids` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-04 | — | D-03 fallback when `start_event_id is None` | unit | `uv run pytest tests/test_perfmon.py -k span_full_leadup_fallback` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-04 | — | D-04 hazard when a boundary has `ts=None` | unit | `uv run pytest tests/test_perfmon.py -k span_missing_ts_hazard` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-04 | — | At-denial / slope / peak match hand-computed goldens | unit | `uv run pytest tests/test_perfmon.py -k golden_trend_figures` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-04 | — | Single-sample span yields `slope=None`, no `ZeroDivisionError` (A1) | unit | `uv run pytest tests/test_perfmon.py -k single_sample_no_zero_division` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-04 | T-13-NONFINITE | `nan`/`inf` cell excluded, row retained, reported (D-11) | unit | `uv run pytest tests/test_perfmon.py -k non_finite_excluded` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-05 | — | Zero in-span samples → `critical` non-overlap hazard | unit | `uv run pytest tests/test_perfmon.py -k non_overlap_hazard` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-05 | — | All-zero `Total MCM Denial` with episodes → `warn` | unit | `uv run pytest tests/test_perfmon.py -k mcm_denial_always_zero` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-05 | — | No episodes → no always-zero hazard (D-14) | unit | `uv run pytest tests/test_perfmon.py -k no_episodes_no_zero_hazard` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-05 | — | Drift marker in `attrs` → `warn` drift hazard | unit | `uv run pytest tests/test_perfmon.py -k counter_set_drift_hazard` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-06 | T-13-PATH | Bundle written: report + CSV, exit 0 | integration | `uv run pytest tests/test_cli_perfmon.py -k bundle_written` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-06 | — | `--format json` writes `perfmon_report.json` | integration | `uv run pytest tests/test_cli_perfmon.py -k json_format` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-06 | T-13-ERRLEAK | Missing case → exit 1; bad `--format` → exit 2 | integration | `uv run pytest tests/test_cli_perfmon.py -k exit_codes` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-06 | — | Perfmon CSV, **no DSSErrors log**, exit 0, no traceback (crit. 5) | integration | `uv run pytest tests/test_cli_perfmon.py -k no_dsserrors_log` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | Crit. 2 | — | Byte-identical bundle on re-run (determinism) | integration | `uv run pytest tests/test_cli_perfmon.py -k byte_identical_rerun` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PERF-06 | T-13-CSVINJ | Formula-prefixed counter name is quote-escaped in CSV (A3) | unit | `uv run pytest tests/test_perfmon.py -k csv_formula_guard` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | WR-03 | — | Colliding short names both retained | unit | `uv run pytest tests/test_dssperfmon.py -k collision_qualified` | ⚠️ file exists | ⬜ pending |
| TBD | TBD | TBD | WR-03 | — | Hartford's 22 keys unchanged (regression guard) | unit | `uv run pytest tests/test_dssperfmon.py -k hartford_keys_byte_identical` | ⚠️ file exists | ⬜ pending |
| TBD | TBD | TBD | WR-02 | T-13-DOS | Note list capped, summary line emitted | unit | `uv run pytest tests/test_dssperfmon.py -k notes_capped` | ⚠️ file exists | ⬜ pending |
| TBD | TBD | TBD | WR-05 | T-13-ATTRKEY | Drifted event carries the `attrs` marker | unit | `uv run pytest tests/test_dssperfmon.py -k drift_marker_in_attrs` | ⚠️ file exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_perfmon.py` — correlator unit tests (PERF-04, PERF-05)
- [ ] `tests/test_cli_perfmon.py` — bundle / exit-code integration tests (PERF-06)
- [ ] `tests/fixtures/dssperfmon/` synthetic fixtures — **three needed, none derivable from Hartford**:
      (a) colliding instance short names (WR-03), (b) mid-file column drift (WR-05 / hazard 3),
      (c) a `nan`/`inf` cell (D-11). VERIFIED against the real file: the Hartford deny CSV has
      22 unique short names, uniform width 23 across all 13,596 rows, and zero non-numeric cells.
- [ ] A perfmon-only case fixture (perfmon CSV, **no DSSErrors log**) for success criterion 5
- [ ] Golden-figure fixture — a cut slice of the Hartford CSV (a few dozen rows around the denial),
      not all 13,596 rows
- [ ] No framework install needed — pytest already configured

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

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
