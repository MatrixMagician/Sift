---
phase: 7
slug: evaluation-harness-golden-cases
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-18
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by plan-phase from 07-RESEARCH.md "## Validation Architecture"; the
> planner completes the Per-Task Verification Map and Wave 0 rows.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (existing) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`; `live` marker + socket-block already configured) |
| **Quick run command** | `uv run pytest tests/test_eval*.py -q` |
| **Full suite command** | `uv run ruff check && uv run pyright && uv run pytest -q` |
| **Estimated runtime** | ~3–5 seconds (offline suite; `-m live` judge test excluded by default) |

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched area.
- **After every plan wave:** Run the full suite command (ruff + pyright + pytest).
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** ~5 seconds (offline; the live judge test is manual UAT, mirrors REPT-04).

---

## Per-Task Verification Map

*Seeded — the planner fills one row per task with its Requirement, Threat Ref, secure behavior, and automated command.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 7-01-01 | 01 | 1 | EVAL-01 | T-07-xx / — | truth.yaml parsed with no code execution (safe_load) | unit | `uv run pytest tests/test_eval_truth.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_eval_harness.py` — offline harness run over a fixture golden case (EVAL-02/03)
- [ ] `tests/test_eval_truth.py` — truth.yaml schema parse + `yaml.safe_load` (EVAL-01)
- [ ] `tests/test_eval_thresholds.py` — planted-regression → non-zero exit (EVAL-03)
- [ ] `tests/_eval_fixtures.py` — shared golden-case + fake-client fixtures (reuse the EVAL-05 MockTransport seam)
- [ ] `uv add pyyaml` — PyYAML (6.0.3) is declared nowhere in pyproject.toml yet (first Wave 0 work item, per RESEARCH)

*pytest + the injectable fake-client seam already exist; only eval-specific stubs/fixtures are new.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Optional LLM-as-judge grading against the real local model | EVAL-04 | Needs the live Lemonade/llama-server model; the default suite is socket-blocked (EVAL-05) | `uv run pytest -m live tests/test_eval_judge.py` with the model up, or `sift eval --judge` on a golden case; confirm judge scores appear **alongside** (never replacing) keyword scores |

*All other phase behaviors have automated (offline) verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
