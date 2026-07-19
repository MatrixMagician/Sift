---
phase: 4
slug: salience-rag-citation-gated-hypotheses
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-17
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/test_salience.py tests/test_hypothesise.py -q` |
| **Full suite command** | `uv run pytest && uv run ruff check && uv run pyright` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the touched module
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

*Seeded as draft — validate-phase (§6) reconciles rows against the finalised PLAN.md task IDs.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | RAG-01..06, CLI-04 | — | citation gate: cited ⊆ prompted | unit | `uv run pytest` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_salience.py` — salience ranking determinism (severity/count/burstiness/novelty/temporal proximity)
- [ ] `tests/test_hypothesise.py` — hypothesis generation, citation gate, degrade/repair round-trip, exit codes
- [ ] Fake OpenAI-compatible LLM server fixture (respx / ASGI stub) returning good AND bad citation IDs — zero network egress

*Existing pytest infrastructure covers the framework; new test files above stub the phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| llama.cpp `$defs`/`$ref` acceptance of `HypothesisSet.model_json_schema()` | RAG-03 | Needs a live `llama-server -m` round-trip; the validate→repair→degrade pipeline is the automated backstop regardless | Run `sift analyze` against a live constrained-decoding server on the first golden case; confirm schema-valid JSON without falling back to repair |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
