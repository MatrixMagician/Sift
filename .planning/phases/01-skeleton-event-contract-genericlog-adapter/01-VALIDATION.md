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
| 01-01-T1 | 01-01 | 1 | — (supply chain gate) | T-01-SC | six [SUS] PyPI packages human-approved before install | checkpoint | — (blocking-human) | — | ⬜ pending |
| 01-01-T2 | 01-01 | 1 | CLI-01 | T-01-05 | no HTTP dependency installed | smoke + gates | `uv run sift --help && uv run ruff check && uv run pyright` | ❌ W0 | ⬜ pending |
| 01-01-T3 | 01-01 | 1 | INGST-01 (RED contract) | T-01-05 | socket-guard autouse fixture active | integration (CliRunner, RED) | `! uv run pytest tests/test_cli.py::test_walking_skeleton_happy_path -x -q` | ❌ W0 | ⬜ pending |
| 01-02-T1 | 01-02 | 2 | INGST-01 | — | — | unit | `uv run pytest tests/test_models.py -x -q` | ❌ W0 | ⬜ pending |
| 01-02-T2 | 01-02 | 2 | INGST-02 | T-02-01, T-02-02 | case-name allowlist; parameterised SQL only | unit | `uv run pytest tests/test_store.py::test_reingest_idempotent -x` | ❌ W0 | ⬜ pending |
| 01-02-T3 | 01-02 | 2 | INGST-01, INGST-02 | T-02-03 | streaming parse, no slurp | integration (CliRunner, GREEN) | `uv run pytest tests/test_cli.py -x -q` | ❌ W0 | ⬜ pending |
| 01-03-T1 | 01-03 | 3 | INGST-04, INGST-11 | — | no fabricated severities/timestamps | unit | `uv run pytest tests/test_genericlog.py -k "timezone or format" -x -q` | ❌ W0 | ⬜ pending |
| 01-03-T2 | 01-03 | 3 | INGST-05, INGST-06 | T-03-01, T-03-02 | 256-line/64 KB caps bound memory; decode after offsets fixed | unit | `uv run pytest tests/test_genericlog.py -k "multiline or coverage or encoding" -x -q` | ❌ W0 | ⬜ pending |
| 01-03-T3 | 01-03 | 3 | INGST-10 | T-03-01 | streaming decompression; corrupt input errors loudly | unit | `uv run pytest tests/test_genericlog.py -k compressed -x -q` | ❌ W0 | ⬜ pending |
| 01-04-T1 | 01-04 | 3 | CLI-01 | T-04-02 | tz names validated at config time | unit | `uv run pytest tests/test_config.py -x -q` | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 3 | INGST-03 | — | deterministic detection order | unit | `uv run pytest tests/test_adapters_detect.py -x -q` | ❌ W0 | ⬜ pending |
| 01-04-T3 | 01-04 | 3 | CLI-01, INGST-03 | T-04-01 | control chars stripped from show output | integration | `uv run pytest tests/test_cli.py -x -q` | ❌ W0 | ⬜ pending |
| 01-05-T1 | 01-05 | 4 | — (D-02 ADRs) | T-05-01 | decisions auditable in-repo | smoke | `uv run sift ingest --help \| grep -i snapshot` | ❌ W0 | ⬜ pending |
| 01-05-T2 | 01-05 | 4 | INGST-01, INGST-02, INGST-05 | — | — | acceptance (M1 gate) | `uv run pytest tests/test_acceptance.py -x -q && uv run pytest -q && uv run ruff check && uv run pyright` | ❌ W0 | ⬜ pending |

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
- [ ] `tests/conftest.py` — isolation fixtures ONLY (tmp XDG dirs + autouse socket guard); owned by plan 01-01
- [ ] Fixture logs (plain, gzip, zstd, multi-line, mixed-timezone, unparseable-region) are built in-file by each test module — no shared `tests/fixtures/` directory (keeps wave-3 plans 01-03/01-04 conflict-free)
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
