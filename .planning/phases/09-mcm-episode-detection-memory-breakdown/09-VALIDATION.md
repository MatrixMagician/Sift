---
phase: 9
slug: mcm-episode-detection-memory-breakdown
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: true
created: 2026-07-19
reconciled: 2026-07-19
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

*All phase behaviours have automated verification, with one PARTIAL-coverage gap
recorded below (multi-episode boundary logic).*

---

## Known Coverage Gap (PARTIAL — informational, not a blocker)

**Multi-episode boundary detection is implemented but not committed-tested.**

- **What's implemented:** `detect_episodes` handles episode close via explicit
  `State=normal` recovery and via implicit-recovery (a following denial banner),
  yielding multiple `McmEpisode`s per case with per-episode `recovery`/
  `open_truncated` flags.
- **Why it's a gap:** The committed fixture
  `tests/fixtures/mcm/hartford_deny_slice.log` is **single-episode** (one banner,
  zero `State=normal`). Every committed test therefore asserts `len(episodes) == 1`.
  The multi-episode close paths (recovery-close and implicit-recovery-close) are
  exercised only by the **verifier's ad-hoc behavioural probe** (09-VERIFICATION.md
  Truths #2/#4, Behavioural Spot-Checks: Cases A/B/C → 2/2/2 episodes), which is
  **not a committed automated test** — it does not re-run under `uv run pytest`
  and cannot regression-guard future changes.
- **Impact:** Low. The paths are verified-working today; the risk is silent
  regression, not present breakage. This is why `nyquist_compliant: false`.
- **Remediation (out of scope for this reconciliation — no new tests written per
  task constraint):** add a committed multi-episode fixture (or synthetic-event
  test mirroring `test_fragmented_flag`) asserting: (a) `State=normal` closes an
  episode and captures `recovery`; (b) a subsequent denial implicitly closes the
  prior open episode; (c) determinism holds across ≥2 episodes.

---

## Validation Sign-Off

- [x] All requirement-critical behaviours mapped to a committed automated test — **except** multi-episode boundary logic (gap above)
- [x] Sampling continuity: every task has an automated verify; no 3-task gap
- [x] Wave 0 covers all MISSING references (none — infra pre-existing)
- [x] No watch-mode flags
- [x] Feedback latency < 2s
- [ ] `nyquist_compliant: true` — **withheld**: multi-episode close paths are present-but-not-committed-tested (PARTIAL coverage)

**Approval:** validated (PARTIAL) 2026-07-19
