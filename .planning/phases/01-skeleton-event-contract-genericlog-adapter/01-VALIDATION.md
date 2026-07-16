---
phase: 1
slug: skeleton-event-contract-genericlog-adapter
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | none yet — `[tool.pytest.ini_options]` in pyproject.toml, created in Wave 0 |
| **Quick run command** | `uv run pytest -x -q` |
| **Full suite command** | `uv run pytest && uv run ruff check && uv run pyright` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -x -q`
- **After every plan wave:** Run `uv run pytest && uv run ruff check && uv run pyright`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (populated by planner) | | | INGST-01..06, 10, 11, CLI-01 | — | | | | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Requirement → test map from RESEARCH.md `## Validation Architecture`:

| Req ID | Behaviour | Test Type | Automated Command |
|--------|-----------|-----------|-------------------|
| INGST-01 | new+ingest fixture → events with expected deterministic IDs | integration (CliRunner) | `uv run pytest tests/test_cli.py -x -q` |
| INGST-02 | second ingest adds zero events | integration | `uv run pytest tests/test_store.py::test_reingest_idempotent -x` |
| INGST-03 | sniff auto-detect, ≥0.5 threshold, fallback, `--adapter` override | unit | `uv run pytest tests/test_adapters_detect.py -x` |
| INGST-04 | ISO/syslog/epoch parsing + continuation grouping | unit | `uv run pytest tests/test_genericlog.py -x` |
| INGST-05 | unknown events for unparseable regions; coverage formula; ≥99% on fixture | unit | `uv run pytest tests/test_genericlog.py -k coverage -x` |
| INGST-06 | stack-trace fixture → one event; 256-line/64 KB caps | unit | `uv run pytest tests/test_genericlog.py -k multiline -x` |
| INGST-10 | gzip/zstd fixtures (incl. multi-member gz, multi-frame zst) yield identical events & offsets to plain variant | unit | `uv run pytest tests/test_genericlog.py -k compressed -x` |
| INGST-11 | naive→UTC inferred, offset→exact, glob tz override applied | unit | `uv run pytest tests/test_genericlog.py -k timezone -x` |
| CLI-01 | flags > `SIFT_*` env > config.toml > defaults precedence | unit | `uv run pytest tests/test_config.py -x` |

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — uv project with pytest/ruff/pyright configured
- [ ] `tests/conftest.py` — shared fixtures (fixture logs, tmp XDG dirs)
- [ ] `tests/fixtures/` — plain, gzip, zstd, multi-line, mixed-timezone, unparseable-region fixture logs
- [ ] Test stubs per the requirement map above

---

## Manual-Only Verifications

All phase behaviours have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
