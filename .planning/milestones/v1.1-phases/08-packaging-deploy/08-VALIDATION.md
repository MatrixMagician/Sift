---
phase: 8
slug: packaging-deploy
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-19
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `08-RESEARCH.md` § Validation Architecture. Reconciled by `/gsd-validate-phase` after plans exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest` (default suite; excludes `perf`/`live`/`packaging`) |
| **Full suite command** | `uv run pytest` + `uv run pytest -m packaging` (opt-in gates) |
| **Estimated runtime** | ~default suite unchanged; packaging smoke adds a wheel build + isolated install |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest` (fast default suite stays green)
- **After every plan wave:** Run `uv run pytest -m packaging` (offline install smoke + Quadlet dry-run)
- **Before `/gsd-verify-work`:** `ruff check` + `pyright` + full `pytest` (incl. `-m packaging`) green; README quickstart walked on a clean checkout
- **Max feedback latency:** default-suite duration (packaging gate is opt-in, run at wave/phase boundaries)

---

## Per-Task Verification Map

> Placeholder — validate-phase reconciles this against the committed PLAN.md task IDs.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-XX-XX | XX | X | PKG-01 | — | offline install yields working `sift` | integration | `uv run pytest -m packaging` | ❌ W0 | ⬜ pending |
| 08-XX-XX | XX | X | PKG-02 | — | shipped `deploy/sift.container` base_url passes `_assert_local` with no override | unit | `uv run pytest -m packaging -k guard` | ❌ W0 | ⬜ pending |
| 08-XX-XX | XX | X | PKG-02 | — | `deploy/*.container` parse via generator dry-run (graceful-skip) | integration | `uv run pytest -m packaging -k quadlet` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_packaging.py` — offline install smoke (PKG-01) + generator dry-run (graceful-skip) + guard-acceptability assertion on the shipped `deploy/sift.container`
- [ ] New `packaging` pytest marker in `pyproject.toml` **and** extend `addopts` to `-m 'not perf and not live and not packaging'` (else the marker runs in the default fast suite — regression risk)
- [ ] `deploy/sift.container` + `deploy/llama-server.container.example` must exist before the dry-run test targets them

*The offline smoke test must force offline (`--no-index --find-links dist/` / `--offline`): the conftest socket guard only covers the pytest process, not `uv`/`sift` subprocesses.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| README prose accuracy (Vulkan/ROCm gfx1151, Lemonade recipe caveat, two-instance embeddings, `sift[pdf]`/pango) | PKG-01/PKG-02 | Prose correctness is not machine-checkable | Review README quickstart against SPEC §1/§8 |
| True clean-checkout `uv tool install .` → first triage report | PKG-01 | End-to-end install on a real Fedora box, outside CI | Fresh checkout → `uv tool install .` → `sift doctor` → `new/ingest/analyze/report` |
| Quadlet dry-run on a host with podman present | PKG-02 | CI runner may lack podman (test skips gracefully) | Run the systemd generator `--dryrun` against `deploy/sift.container` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency acceptable (packaging gate opt-in at wave/phase boundaries)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
