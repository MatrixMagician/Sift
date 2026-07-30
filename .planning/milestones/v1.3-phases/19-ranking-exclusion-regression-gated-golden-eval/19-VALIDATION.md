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
| T1 (tracer) | 19-01 | 1 | EUS-11 | T-19-01, T-19-02, T-19-04 | Exclusion literal is module-owned, never caller-supplied; the `?`-bound SQL construction is untouched | integration (CLI) | `uv run pytest tests/test_analyze.py -q` | ✅ extends `tests/test_analyze.py` | ⬜ pending |
| T2 | 19-01 | 1 | EUS-11 | T-19-01 | Ranking seam filters eu-stack; citation seam provably does not | unit | `uv run pytest tests/test_store.py -q` | ✅ extends `tests/test_store.py` | ⬜ pending |
| T3 | 19-01 | 1 | EUS-11 | T-19-03 | Rendered event text still routes through the shipped `sanitise` path | integration (CLI) | `uv run pytest tests/test_cli.py -q` | ✅ extends `tests/test_cli.py` | ⬜ pending |
| T1 (checkpoint) | 19-02 | 2 | EUS-12 | — | Frozen Phase-16 analyser stays unmodified whichever option is chosen | checkpoint:decision | `git diff --stat src/sift/pipeline/ \| wc -l` returns 0 | n/a — decision + CONTEXT amendment | ⬜ pending |
| T2 | 19-02 | 2 | EUS-12 | T-19-05, T-19-06 | `yaml.safe_load` path unchanged; nested `extra="forbid"`; `provenance` a mandatory Literal | unit | `uv run pytest tests/test_eval_truth.py tests/test_eval_thresholds.py tests/test_eval_cases.py -q` | ✅ extends `tests/test_eval_truth.py`, `tests/test_eval_thresholds.py` | ⬜ pending |
| T3 | 19-02 | 2 | EUS-12 | T-19-08 | Zero endpoint contact proven by an empty recorded request log; failure text `sanitise`d | unit + integration | `uv run pytest tests/test_eval_thresholds.py tests/test_eval_cases.py -q` | ✅ extends `tests/test_eval_thresholds.py` | ⬜ pending |
| T1 | 19-03 | 3 | EUS-12 | T-19-10 | Missing floor raises rather than silently gating on four metrics; vacuity guard cannot be starved green | unit | `uv run pytest tests/test_eval_thresholds.py tests/test_eval_cases.py -q` | ✅ extends `tests/test_eval_thresholds.py` | ⬜ pending |
| T2 | 19-03 | 3 | EUS-12 | T-19-09, T-19-11, T-19-12 | Redaction path regression-tested via byte-identical reproduction of the existing fixture; 250 KB cap | fixture + measured assertion | `uv run pytest tests/test_eval_truth.py -q` | ❌ new — `eval/cases/eustack-healthy/` | ⬜ pending |
| T3 | 19-03 | 3 | EUS-12 | T-19-11 | Declared figures proven to match measurement; single-`observed` invariant pinned | integration (offline) | `uv run pytest tests/test_eval_cases.py -q` | ✅ extends `tests/test_eval_cases.py` | ⬜ pending |
| T1 | 19-04 | 4 | EUS-12 | T-19-13, T-19-14, T-19-15, T-19-17 | Identifiers redacted; every fixture symbol traced to the source capture; 64 KB cap | fixture + measured assertion | `uv run pytest tests/test_eval_truth.py -q` | ❌ new — `eval/cases/eustack-hang-pool-warehouse/` | ⬜ pending |
| T2 | 19-04 | 4 | EUS-12 | T-19-15, T-19-17 | Twin proven not a copy (no shared TIDs, no shared addresses) before figure equality is asserted | fixture + unit | `uv run pytest tests/test_eval_cases.py -q` | ❌ new — `eval/cases/eustack-hang-pool-warehouse-mutated/` | ⬜ pending |
| T3 | 19-04 | 4 | EUS-12 | T-19-14, T-19-16 | Neuter applied at the `load_rules` seam only; shipped rules file proven untouched | integration (CLI, offline) | `uv run pytest tests/test_eval_cases.py -q` | ✅ extends `tests/test_eval_cases.py` | ⬜ pending |

Sampling continuity: every task above carries an `<automated>` verify; no run of three consecutive tasks
lacks one. The 19-02 checkpoint is the only non-test row and it carries a runnable `git diff` assertion.

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
