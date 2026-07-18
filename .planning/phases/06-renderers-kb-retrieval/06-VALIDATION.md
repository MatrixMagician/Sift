---
phase: 6
slug: renderers-kb-retrieval
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-18
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/test_render.py tests/test_report.py -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30 seconds (perf tests excluded via addopts) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the touched module
- **After every plan wave:** Run `uv run pytest` (full suite) + `uv run ruff check` + `uv run pyright`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 6-XX-XX | TBD | TBD | REPT-01/02/03/04, RAG-07 | TBD | TBD | unit | `uv run pytest` | ❌ W0 | ⬜ pending |

*Populated by validate-phase after plans exist. Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_render.py` — Markdown/JSON renderer stubs (REPT-01/02)
- [ ] `tests/test_report_determinism.py` — byte-identical JSON reproducibility (REPT-03)
- [ ] `tests/test_kb_retrieval.py` — KB context-change assertion (RAG-07)
- [ ] `tests/test_pdf.py` — PDF extra present/absent behaviour (REPT-04), marked to skip when `sift[pdf]` absent

*Existing pytest infrastructure covers the framework; new test files listed above.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Rendered PDF visual fidelity | REPT-04 | Print layout is visual; automated test asserts PDF bytes/structure only | Install `sift[pdf]`, run `sift report <case> --format pdf --out r.pdf`, open and eyeball layout |

*Automated tests cover Markdown/JSON/determinism/KB; only PDF visual fidelity is manual.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
