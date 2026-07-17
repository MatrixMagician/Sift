---
phase: 5
slug: domain-adapters-journald-dsserrors-eustack
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-17
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `05-RESEARCH.md` §Validation Architecture. Per-task map reconciled by `/gsd-validate-phase`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing — no install) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q` (+ `uv run ruff check` + `uv run pyright` — the "done" gate)
- **After every plan wave:** Run `uv run pytest` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Draft — populated by `/gsd-validate-phase` once PLAN.md task IDs exist. Requirement/criterion → test
> coverage is specified in `05-RESEARCH.md` §Validation Architecture (PRIORITY 0–7 mapping, MESSAGE
> int-array/null/value-array normalisation, MCM block grouping, multi-node node-tagging, reversed-chronology
> `.bak` ordering, one-event-per-thread, mixed-tz timeline ordering, sniff routing, and an e2e slice asserting
> **real** (not 1.0) per-file parse coverage).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | — | — | INGST-07 (journald) | — | reject non-loopback / cap oversized lines | unit | `uv run pytest tests/test_journald.py` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGST-08 (dsserrors) | — | parameterised SQL, `_sanitise` on show | unit | `uv run pytest tests/test_dsserrors.py` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGST-09 (eustack) | — | one event per thread, caps enforced | unit | `uv run pytest tests/test_eustack.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_journald.py`, `tests/test_dsserrors.py`, `tests/test_eustack.py` — per-adapter test files
- [ ] Fixtures: `tests/fixtures/journald/*.json` (handcrafted), `tests/fixtures/dsserrors/*`, `tests/fixtures/eustack/*` (**user-confirmed sanitised samples** — see RESEARCH Open Questions 1 & 2)
- [ ] Shared `base.ConfigurableAdapter` + promoted `to_utc`/tz-lookup helpers must exist before adapters can be tested for real coverage
- [ ] e2e test asserting **non-vacuous** parse coverage (guards the `isinstance(GenericLogAdapter)` coverage-reading bug identified in research)

*pytest itself is already installed — no framework bootstrap needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| dsserrors line layout + SID token shape match a real MSTR sample | INGST-08 | Proprietary, MSTR-version-dependent — regexes cannot be frozen without a real sanitised sample | Provide a sanitised DSSErrors.log snippet; confirm parsed SIDs/error-codes/OIDs/node tags against source |
| eustack format is elfutils `eu-stack` vs JVM-style (gates lock-info extraction) | INGST-09 | Format identity is an open question; determines whether lock/blocked-on attrs exist | Provide a sanitised thread-dump sample; confirm one-event-per-thread + lock info |

*These map to the `checkpoint:human-verify` fixture task the planner encodes before regexes freeze.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
