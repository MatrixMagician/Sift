---
phase: 15
slug: thread-role-taxonomy-rules-file
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-25
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `15-RESEARCH.md` §"Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥9.1.1 (already a dev dependency) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`) |
| **Quick run command** | `uv run pytest tests/test_eustack.py tests/test_eustack_rules.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5 s quick · ~90 s full suite |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_eustack.py tests/test_eustack_rules.py -x`
- **After every plan wave:** Run `uv run pytest` (full suite) + `uv run ruff check` + `uv run pyright`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds (quick run)

---

## Per-Task Verification Map

Task IDs are assigned by the planner; this table is the requirement→test contract the planner
must satisfy. Rows are keyed on requirement + success criterion, not on task ID, until PLAN.md
exists — the planner fills the Task ID and Plan/Wave columns.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | EUS-01 (SC1) | — | N/A | unit | `uv run pytest tests/test_eustack_rules.py::test_classification_partitions_all_threads -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EUS-01 (SC2) | — | N/A | integration | `uv run pytest tests/test_eustack_rules.py::test_rules_path_override_changes_classification -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EUS-01 (SC4, CI half) | — | N/A | unit | `uv run pytest tests/test_eustack_rules.py::test_reference_derivative_headline_signature -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EUS-01 (SC5) | — | N/A | unit (proxy) | `uv run pytest tests/test_eustack_rules.py::test_classification_is_per_signature_not_per_thread -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EUS-02 (SC3) | — | N/A | unit | `uv run pytest tests/test_eustack_rules.py::test_unmatched_signature_reports_count_and_example -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EUS-02 (D-07 split) | — | N/A | unit | `uv run pytest tests/test_eustack_rules.py::test_all_unresolved_frames_is_distinct_category -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-06 (load-time rejection) | T-15-01 | A malformed or un-normalised rules file fails loudly at load rather than silently classifying wrongly | unit | `uv run pytest tests/test_eustack_rules.py::test_unnormalised_pattern_rejected_at_load -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-01 (rule ordering) | — | N/A | unit (regression) | `uv run pytest tests/test_eustack_rules.py::test_running_rule_precedes_evaluation_ancestor_rule -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-05 (`@`-suffix strip) | — | N/A | unit (regression) | `uv run pytest tests/test_eustack_rules.py::test_single_at_glibc_suffix_is_stripped -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_eustack_rules.py` — new file, covers EUS-01 / EUS-02 loader and classifier behaviour (all rows above)
- [ ] `tests/fixtures/eustack/reference_capture_derivative.txt` — new signature-preserving fixture, derived per `15-RESEARCH.md` §"Building the signature-preserving fixture (D-14)"
- [ ] `tests/test_eustack.py` — additive cases for `iter_frames()` (existing file)
- [ ] `tests/test_config.py` — additive cases for `EustackConfig` / `rules_path` (existing file)
- [ ] Framework install: **none required** — pytest, Pydantic and stdlib `tomllib` are all already present

---

## Manual-Only Verifications

Both rows below exist because the figures they assert come only from the 2.4 MB out-of-repo
reference capture, which D-14 deliberately does not commit. This mirrors ADR 0013's
out-of-repo-corpus verification style: measured by hand at phase verification, recorded in the
phase summary.

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The real 1,715-thread `MSIQTask::GetNextPreferredJob` population reads `idle-parked/job-queue`, and 3,902 threads collapse to 93 signatures | EUS-01 (SC4, SC5 — full-capture half) | Source dumps are not in the repo (2.4 MB × 2, and they carry a customer environment identifier) | Run the shipped classifier against `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`; assert 3,902 threads / 93 signatures and that the 1,715-thread signature is `idle-parked/job-queue`. Record the measured numbers in `15-SUMMARY.md`. Baseline established during planning: 24-rule set gives 3,850/3,902 threads (98.67%) and 53/93 signatures classified, with `unclassified` 52 threads / 40 signatures |
| Classification wall-clock scales with signature count, not thread count | EUS-01 (SC5, full-capture half) | Needs the real 3,902-thread capture to be meaningful; the CI fixture is capped per signature | Timed run against the full capture; record elapsed time in `15-SUMMARY.md`. The CI proxy (`test_classification_is_per_signature_not_per_thread`) asserts the invocation count, not the wall clock |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
