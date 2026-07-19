---
phase: 11
slug: mcm-facts-into-sift-analyze-golden-eval-case
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-19
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`; `perf` marker excluded via addopts) |
| **Quick run command** | `uv run pytest -k <name>` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30–60 seconds (excludes `@pytest.mark.perf`) |

Gate for "done" on every task: `uv run ruff check` + `uv run pyright` + `uv run pytest` all clean.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -k <name>` for the touched area
- **After every plan wave:** Run `uv run pytest` (full suite) + `uv run ruff check` + `uv run pyright`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Populated by the planner once PLAN.md task IDs exist; refined by `/gsd-validate-phase`.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | MCM-06 | — | MCM figures come verbatim from analyser; model cannot alter them | unit | `uv run pytest -k mcm_facts` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_mcm_analyze.py` (or equivalent) — determinism proof (criterion 2) + citation-gate union (criterion 1)
- [ ] Extend `tests/test_kb_analyze.py`-style golden hash guard with a symmetric no-MCM assertion (criterion 5)
- [ ] `eval/cases/<mcm-case>/truth.yaml` + fixture wiring — the MCM golden case (criterion 4, MCM-07)

*Existing infrastructure (pytest, respx/`httpx.MockTransport` fake-OpenAI harness, eval runner) covers the rest — no new framework.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end `sift analyze` on a real dsserrors case surfaces MCM facts as cited evidence | MCM-06 | Requires a live local LLM endpoint (zero-network in tests) | Run `sift analyze` on a case containing `hartford_deny_slice.log`; confirm a hypothesis cites an MCM `event_id` and its figures match `sift mcm` output |

*Automated coverage proves the mechanism; the manual check confirms the live integration.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
