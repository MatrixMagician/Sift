---
phase: 12
slug: dssperfmon-adapter-pipeline-exclusion
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-20
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `12-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` (markers: `live`, `perf`, `packaging`) |
| **Quick run command** | `uv run pytest tests/test_dssperfmon.py tests/test_store.py tests/test_adapters_detect.py -x` |
| **Full suite command** | `uv run pytest` |
| **Phase gate** | `uv run ruff check && uv run pyright && uv run pytest` |
| **Estimated runtime** | ~15 s quick / full suite per project norm |

---

## Sampling Rate

- **After every task commit:** Run the quick command above
- **After every plan wave:** Run `uv run pytest` — **the FULL suite, not a subset.** This phase
  edits shipped v1.0/v1.1 pipeline code (`store.py`), so a subset gate would not detect the
  regression class this phase is most at risk of. Full suite is the merge gate for *every* wave,
  not just the last.
- **Before `/gsd-verify-work`:** `ruff check` + `pyright` + `pytest` all clean
- **Max feedback latency:** ~15 s (quick), full suite per project norm

---

## Per-Task Verification Map

*Task IDs are assigned by the planner; this table is completed once PLAN.md files exist. The
criterion→test mapping below is fixed and comes from RESEARCH.md § Validation Architecture.*

| Criterion | Behaviour | Requirement | Test Type | Automated Command | File Exists | Status |
|-----------|-----------|-------------|-----------|-------------------|-------------|--------|
| 1 | One event per sample row, deterministic `event_id` | PERF-01 | unit | `pytest tests/test_dssperfmon.py::test_one_event_per_sample_row -x` | ❌ W0 | ⬜ pending |
| 1 | Re-ingest adds zero new events | PERF-01 | integration (CLI) | `pytest tests/test_cli.py::test_ingest_perfmon_idempotent -x` | ❌ W0 | ⬜ pending |
| 2 | `(PDH-CSV 4.0)` sniffed with no `--adapter` | PERF-01 | unit | `pytest tests/test_dssperfmon.py::test_sniff_pdh_header -x` | ❌ W0 | ⬜ pending |
| 2 | Existing adapter detection unchanged | PERF-01 | regression | `pytest tests/test_adapters_detect.py -x` | ✅ exists | ⬜ pending |
| 2 | Timestamps → UTC via `base.to_utc`, `ts_confidence` recorded | PERF-02 | unit | `pytest tests/test_dssperfmon.py::test_timestamp_utc_and_confidence -x` | ❌ W0 | ⬜ pending |
| 2 | **CSV/log alignment — ADR 0012 guard** | PERF-02 | integration | `pytest tests/test_dssperfmon.py::test_csv_aligns_with_paired_log -x` | ❌ W0 | ⬜ pending |
| 2 | `--tz` override still wins | PERF-02 | unit | `pytest tests/test_dssperfmon.py::test_tz_override_applies -x` | ❌ W0 | ⬜ pending |
| 3 | Blank/non-numeric cell → `severity="unknown"` | PERF-02 | unit (synthetic) | `pytest tests/test_dssperfmon.py -k unknown_fallback -x` | ❌ W0 | ⬜ pending |
| 3 | Unparseable timestamp → `ts=None`, event survives | PERF-02 | unit (synthetic) | `pytest tests/test_dssperfmon.py::test_bad_timestamp_survives -x` | ❌ W0 | ⬜ pending |
| 3 | Column-count drift → unknown + notes | PERF-02 | unit (synthetic) | `pytest tests/test_dssperfmon.py::test_column_drift_unknown -x` | ❌ W0 | ⬜ pending |
| 3 | Coverage reflects unknown bytes | PERF-02 | unit | `pytest tests/test_dssperfmon.py::test_parse_coverage -x` | ❌ W0 | ⬜ pending |
| 4 | **`sift show clusters` byte-identical ± CSV** | PERF-03 | integration (CLI) | `pytest tests/test_cli.py::test_cluster_output_identical_with_and_without_perfmon -x` | ❌ W0 | ⬜ pending |
| 4 | `template_groups` identical ± CSV | PERF-03 | unit (store) | `pytest tests/test_store.py::test_template_groups_exclude_perfmon -x` | ❌ W0 | ⬜ pending |
| 4 | Exemplars never perfmon | PERF-03 | unit (fake embed) | `pytest tests/test_cluster.py::test_exemplars_exclude_perfmon -x` | ❌ W0 | ⬜ pending |
| 5 | `iter_event_rows` still yields perfmon | PERF-03 | unit (store) | `pytest tests/test_store.py::test_iter_event_rows_unfiltered -x` | ❌ W0 | ⬜ pending |
| 5 | `get_events` by `event_id` returns perfmon | PERF-03 | unit (store) | `pytest tests/test_store.py::test_get_events_returns_perfmon -x` | ❌ W0 | ⬜ pending |
| 5 | `sift show events` lists perfmon rows | PERF-03 | integration (CLI) | `pytest tests/test_cli.py::test_show_events_includes_perfmon -x` | ❌ W0 | ⬜ pending |
| — | Whole v1.0/v1.1 suite unaffected | all | regression | `uv run pytest` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_dssperfmon.py` — new file, covers PERF-01 / PERF-02 (mirror the
      `tests/test_dsserrors.py:19` FIXTURES pattern)
- [ ] `tests/fixtures/dssperfmon/hartford_deny_slice.csv` — verbatim PDH header + ~20 real sample rows
- [ ] Synthetic malformed fixtures — the real CSV has **zero** blank/non-numeric cells (CONTEXT.md
      D-17), so criterion 3's paths cannot be exercised without them
- [ ] New cases appended to `tests/test_store.py` — the exclusion + unfiltered-citation pair (PERF-03)
- [ ] New cases appended to `tests/test_cli.py` — criterion 4 byte-identity, criterion 5 show events
- [ ] Optional case in `tests/test_cluster.py` reusing `_embed_handler` (`tests/test_cluster.py:78`)

No framework install needed. No new conftest fixtures needed — `_isolate_dirs` and `_no_network`
are autouse and sufficient.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full-scale ingest of the real 13,596-sample CSV | PERF-01 | Reference artefact lives outside the repo (`/home/oliverh/Downloads/hartford/`) and is too large to vendor as a fixture | `uv run sift ingest` a case containing `hartford_Linux_DenyDSSPerformanceMonitor16234.csv`; confirm 13,596 events, 100% parse coverage, and a second ingest adding zero |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] Criterion 4 byte-identity test present and green (the phase's primary regression gate)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
