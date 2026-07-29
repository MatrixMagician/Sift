---
phase: 17
slug: multi-dump-progression-sift-eustack-report-csv
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-25
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `17-RESEARCH.md` § Validation Architecture. Task IDs are filled in
> once `17-*-PLAN.md` files exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (version pinned in `uv.lock`) |
| **Config file** | `pyproject.toml` (existing) |
| **Quick run command** | `uv run pytest tests/test_eustack_progression.py tests/test_eustack_report.py tests/test_cli_eustack.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5 s quick / ~60 s full |

All three test modules are **new** for this phase — Wave 0 must create them.
`analyse_eustack` / `analyse_saturation` currently have zero CLI callers; only
`tests/test_eustack_rules.py` exercises them, so the CLI wiring is net-new.

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/test_eustack_progression.py tests/test_eustack_report.py tests/test_cli_eustack.py -x`
- **After every plan wave:** `uv run pytest` — this phase adds a CLI subcommand
  and a renderer module; a full-suite run guards against regressing the shipped
  `mcm` / `perfmon` command surfaces
- **Before `/gsd-verify-work`:** full suite green, plus `ruff check` and `pyright`
  clean (CLAUDE.md's definition of "done")
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Task IDs assigned 2026-07-25 from the committed `17-0*-PLAN.md` files.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01 T1 (tracer) | 17-01 | 1 | EUS-09 | T-17-03, T-17-04 | Bundle dir derived only from `case_db_path`; no user-supplied path segment | integration (CliRunner) | `uv run pytest tests/test_cli_eustack.py::test_eustack_writes_bundle -x` | ❌ W0 | ⬜ pending |
| 17-01 T2 | 17-01 | 1 | EUS-09 | T-17-04 | Write failure exits 1 with a sanitised message, no traceback, no partial bundle | integration | `uv run pytest tests/test_cli_eustack.py -k "empty_case or missing_case or bad_format or write_failure" -x` | ❌ W0 | ⬜ pending |
| 17-01 T2 | 17-01 | 1 | EUS-09 | — | Byte-identical re-run of report and CSV on an unchanged single-dump case (D-13) | integration | `uv run pytest tests/test_cli_eustack.py -k byte_identical -x` | ❌ W0 | ⬜ pending |
| 17-02 T1 | 17-02 | 2 | EUS-07 | T-17-07 | Fixtures authored, reproducible from the script, free of customer identifiers | unit | `uv run pytest tests/test_cli.py -k phase5_e2e -q` | ✅ exists | ⬜ pending |
| 17-02 T2 | 17-02 | 2 | EUS-08 | T-17-08 | D-01 path: all dumps timestamped → basis stated, no flag, order differs from filename order | unit | `uv run pytest tests/test_eustack_progression.py -k order_by_timestamp -x` | ❌ W0 | ⬜ pending |
| 17-02 T2 | 17-02 | 2 | EUS-08 | T-17-08 | D-02 path: any dump untimestamped → filename basis stated **and** loud unverified-ordering flag raised; progression still renders; no timestamp invented | unit | `uv run pytest tests/test_eustack_progression.py -k "order_fallback_flagged or no_timestamp_is_invented" -x` | ❌ W0 | ⬜ pending |
| 17-02 T3 | 17-02 | 2 | EUS-07 | — | Step deltas and overall delta disagree on the grew-then-shrank case (D-08); ranking is a total order | unit | `uv run pytest tests/test_eustack_progression.py -k "grew_then_shrank or total_order or appeared or vanished" -x` | ❌ W0 | ⬜ pending |
| 17-02 T3 | 17-02 | 2 | EUS-07 | T-17-09 | Progression text carries no per-TID claim (D-10), non-vacuity guarded | unit | `uv run pytest tests/test_eustack_progression.py -k no_per_tid_claim -x` | ❌ W0 | ⬜ pending |
| 17-03 T1 | 17-03 | 3 | EUS-07 | — | Changed-only progression section (D-09) with both delta kinds; unchanged signatures retained in the CSV | unit | `uv run pytest tests/test_eustack_report.py -k "only_changed or keeps_unchanged or csv_header or step_and_overall" -x` | ❌ W0 | ⬜ pending |
| 17-03 T2 | 17-03 | 3 | EUS-09 | T-17-01 | C++ symbol text routed through `_csv_safe`; formula-injection guard holds on a leading-space trigger | unit | `uv run pytest tests/test_eustack_report.py -k csv_safe -x` | ❌ W0 | ⬜ pending |
| 17-03 T2 | 17-03 | 3 | EUS-09 | T-17-14 | D-07 identity projection: matched frame + leaf only, never the full frames tuple, no hash column | unit | `uv run pytest tests/test_eustack_report.py -k identity_projection -x` | ❌ W0 | ⬜ pending |
| 17-03 T2 | 17-03 | 3 | EUS-09 | T-17-12, T-17-13 | No forbidden ownership vocabulary and no per-thread claim in any rendered artefact (D-13/D-10) | unit | `uv run pytest tests/test_eustack_report.py -k "ownership_blind or population_phrased" -x` | ❌ W0 | ⬜ pending |
| 17-03 T2 | 17-03 | 3 | EUS-07/09 | — | Byte-identical re-run of report, JSON and CSV on an unchanged multi-dump case (D-13) | integration | `uv run pytest tests/test_cli_eustack.py -k multi_dump -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_eustack_progression.py` — EUS-07 / EUS-08: dump grouping, D-01 and
      D-02 ordering paths, delta computation, changed-only filter, chain + overall
      deltas, population-level phrasing
- [ ] `tests/test_eustack_report.py` — Markdown / JSON / CSV rendering, `_csv_safe`
      reuse, D-07 identity projection
- [ ] `tests/test_cli_eustack.py` — EUS-09 standalone contract; mirrors the
      `test_cli_mcm.py` / `test_cli_perfmon.py` shape (`writes_bundle`, `empty_case`,
      `no_dsserrors_log`, `byte_identical_rerun`, `missing_case`)
- [ ] A synthetic **two-dump** fixture pair under `tests/fixtures/eustack/` —
      neither existing fixture is a second dump of the same population. Needs (a) a
      pair where both dumps carry a header timestamp (exercises D-01) and (b) a pair
      where at least one lacks one (exercises D-02). Authored deliberately, the same
      way `derive_reference_capture_derivative.py` built the existing fixture, and
      labelled as authored-not-observed. The real reference capture at
      `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` demonstrates case (b)
      empirically but must not be committed (size + customer environment identifiers).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `sift eustack` against the real two-dump reference capture | EUS-07, EUS-08 | The capture is 2.4 MB per file and carries customer environment identifiers — it cannot be committed as a fixture | Ingest `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` into a scratch case, run `sift eustack <case>`, confirm the D-02 fallback basis is stated with the unverified-ordering flag, and confirm the progression section reads at population level |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
