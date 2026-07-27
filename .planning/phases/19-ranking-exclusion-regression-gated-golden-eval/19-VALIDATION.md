---
phase: 19
slug: ranking-exclusion-regression-gated-golden-eval
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-27
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.x (via `uv`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `addopts` excludes `@pytest.mark.perf`) |
| **Quick run command** | `uv run pytest tests/test_store.py tests/test_eval_cases.py -q` |
| **Full suite command** | `uv run ruff check && uv run pyright && uv run pytest` |
| **Estimated runtime** | ~90 seconds full; ~10 seconds quick |

---

## Sampling Rate

- **After every task commit:** Run the quick command scoped to the touched test files
- **After every plan wave:** Run `uv run ruff check && uv run pyright && uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

Note the shipped pyright baseline: 31 pre-existing errors confined to `tests/test_cli_eustack.py`,
`tests/test_eustack_progression.py` and `tests/test_eustack_report.py`. "Clean" for this phase means
**no new** pyright errors beyond that baseline; a task that reduces it is a bonus, not a requirement.

---

## Per-Task Verification Map

*Seeded at plan time; the planner fills one row per task before execution. `sift eval` cases are
scored without an inference endpoint (D-19-05/D-19-16), so every row below is runnable offline —
the zero-network-in-tests invariant is not relaxed anywhere in this phase.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| *(planner fills)* | | | EUS-11 / EUS-12 | | | | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements — pytest, ruff and pyright are configured and
green at HEAD, and both `tests/fixtures/eustack/` and `eval/cases/` already exist as the fixture
homes this phase extends.

New test files this phase is expected to add (authored inside the plans, not as a Wave-0 prerequisite):

- [ ] eu-stack ranking-exclusion assertions — extend `tests/test_store.py` and `tests/test_cluster.py`
      rather than minting a new module (the perfmon analog lives in `tests/test_perfmon.py`)
- [ ] eu-stack golden-case assertions — extend `tests/test_eval_cases.py`, which already holds the
      MCM sensitivity-test precedent

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `sift analyze` on a real eu-stack-only case still narrates the fact block after exclusion (D-19-02) | EUS-11 | Needs a live local inference endpoint, which no agent can reach | Ingest `~/Downloads/iserver1_stacks_1-minute_diff/` into a fresh case, run `uv run sift analyze <case>`, confirm it does **not** print "Nothing to cluster" and that the report cites eu-stack event ids |

Everything else — exclusion, byte-identity, citability, fixture detection, mutation invariance and
the `sift eval` gate — has automated, offline verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
