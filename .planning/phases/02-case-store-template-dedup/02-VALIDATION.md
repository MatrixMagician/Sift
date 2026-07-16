---
phase: 2
slug: case-store-template-dedup
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `[tool.pytest.ini_options]` in pyproject.toml (exists since Phase 1 Wave 0) |
| **Quick run command** | `uv run pytest -x -q` |
| **Full suite command** | `uv run pytest && uv run ruff check && uv run pyright` |
| **Estimated runtime** | ~15 seconds (108 tests from Phase 1 + Phase 2 additions; perf test may add ~10–60 s when included) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -x -q`
- **After every plan wave:** Run `uv run pytest && uv run ruff check && uv run pyright`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds (perf test excluded from quick runs via marker if it exceeds this)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _(filled from PLAN.md task lists once the planner completes — see RESEARCH.md `## Validation Architecture` for the requirement → test map)_ | | | | | | | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_dedup.py` — stubs for CLUS-01 (masking + grouping)
- [ ] `tests/test_store_migration.py` (or extension of `tests/test_store.py`) — stubs for STORE-02 (migration 2, zstd threshold)
- [ ] 100 MB synthetic log generator script (test fixture, per Phase 2 success criterion 1)

*Existing infrastructure (pytest config, conftest socket-guard fixture, CliRunner harness) carries over from Phase 1.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Progress feedback is visibly rendered during a long ingest | CLI-03 | Rich progress bars render to a live TTY; CliRunner captures only final output | Run `uv run sift ingest <case> <100MB-file>` in a real terminal and observe the progress display |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
