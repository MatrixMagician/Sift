---
phase: 9
slug: mcm-episode-detection-memory-breakdown
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-19
reconciled: 2026-07-19
gap_closed: 2026-07-19
---

# Phase 9 — Validation Strategy

> Per-phase validation contract, reconciled against the committed test suite.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/test_mcm.py -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~0.2s (MCM suite); full suite ~478 tests |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_mcm.py -q`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~1 second (MCM suite)

---

## Per-Task Verification Map

Golden suite: `tests/test_mcm.py` (8 committed behavioural tests) over the real
fixture `tests/fixtures/mcm/hartford_deny_slice.log`, exercising
`src/sift/pipeline/mcm.py`. Confirmed green: **8 passed in 0.18s**.

| Requirement | Behaviour | Committed Test | Test Type | Command | Status |
|-------------|-----------|----------------|-----------|---------|--------|
| MCM-01 | Single episode detected non-interactively; denial anchor ⊆ store | `test_hartford_single_episode` | integration (adapter→store→detect) | `uv run pytest tests/test_mcm.py -q` | ✅ green |
| MCM-01 | Lifecycle signals (memory-status-low, offload-start, offload-complete) each cite a real in-span event_id | `test_lifecycle_signals` | integration | same | ✅ green |
| MCM-01 | Absent signal (no `State=normal`) → recovery recorded absent, never fabricated | `test_absent_signals_tolerated` | integration | same | ✅ green |
| MCM-01 | Log ending mid-episode → first-class open/truncated, flagged not dropped | `test_open_truncated_episode` | integration | same | ✅ green |
| MCM-01 | Two runs over same events → byte-identical JSON (determinism) | `test_determinism_byte_identical` | integration | same | ✅ green |
| MCM-01 | Multi-node split (empty detail + differing source_file) → fragmented, never silent merge | `test_fragmented_flag` | unit (synthetic events) | same | ✅ green |
| MCM-02 | Typed denial-time MB figures + all 23 Format-A labels incl. physical/virtual split | `test_breakdown_values` | integration | same | ✅ green |
| MCM-02 | MCM Settings parsed incl. `Memory Reserve = 0 (0Bytes)` not dropped; SmartHeap present | `test_mcm_settings_complete` | integration | same | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. `tests/test_mcm.py`,
the Hartford fixture, and the autouse conftest network/dir-isolation guards are
all committed and green. No framework install or new fixture needed.

---

## Manual-Only Verifications

*All phase behaviours have automated verification. The previously-recorded
multi-episode coverage gap is now CLOSED (see below).*

---

## Coverage Gap — CLOSED 2026-07-19 (was PARTIAL)

**Multi-episode boundary detection is now committed-tested.**

The prior PARTIAL gap (multi-episode close paths exercised only by the verifier's
ad-hoc probe) was closed while fixing code-review finding **WR-01** (cross-episode
span overlap — see `09-REVIEW.md`). A committed fixture and three regression tests
now pin the multi-episode boundary:

- **Fixture:** `tests/fixtures/mcm/hartford_two_episode_partial.log` — two denial
  episodes closed by partial recovery, no `State=normal` (episode #2 open/truncated).
- **`test_two_episode_partial_recovery_disjoint`** — asserts exactly 2 episodes and
  that lifecycle-signal and citation `event_id` sets are DISJOINT across episodes
  (`life1.isdisjoint(life2)` and `set(ep1.event_ids).isdisjoint(set(ep2.event_ids))`).
  This is the WR-01 regression guard — it fails on pre-fix code, passes post-fix.
- **`test_two_episode_own_predenial_settings`** — each episode associates its own
  pre-denial MCM Settings, not the other episode's.
- **`test_two_episode_determinism_byte_identical`** — determinism holds across ≥2 episodes.

Confirmed green: `uv run pytest tests/test_mcm.py -q` → **11 passed** (8 original +
3 new). `nyquist_compliant` is therefore set **true**.

---

## Validation Sign-Off

- [x] All requirement-critical behaviours mapped to a committed automated test (multi-episode boundary now covered — gap closed)
- [x] Sampling continuity: every task has an automated verify; no 3-task gap
- [x] Wave 0 covers all MISSING references (none — infra pre-existing)
- [x] No watch-mode flags
- [x] Feedback latency < 2s
- [x] `nyquist_compliant: true` — multi-episode close paths now committed-tested (WR-01 fix)

**Approval:** validated 2026-07-19 (PARTIAL gap closed same day via WR-01 fix)
