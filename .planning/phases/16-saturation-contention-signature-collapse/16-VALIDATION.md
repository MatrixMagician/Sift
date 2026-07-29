---
phase: 16
slug: saturation-contention-signature-collapse
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-25
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `16-RESEARCH.md` § Validation Architecture. Task IDs are filled in
> once `16-*-PLAN.md` files exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (version pinned in `uv.lock`) |
| **Config file** | `pyproject.toml` (no dedicated `[tool.pytest.ini_options]` block; default rootdir discovery from `tests/`) |
| **Quick run command** | `uv run pytest tests/test_eustack_rules.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5 s quick / ~60 s full |

Existing infrastructure covers this phase — `tests/test_eustack_rules.py` already
provides the `_thread_raw()` / `_event()` / `_parse_derivative_fixture()` helpers
Phase 16's tests need, and `tests/fixtures/eustack/reference_capture_derivative.txt`
already exists.

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/test_eustack_rules.py -k <new-test-name> -x`
- **After every plan wave:** `uv run pytest` — this phase touches shared config
  (`config.py`) and a shared module (`eustack.py`), so a full-suite run is cheap
  insurance against regressing Phase 15's shipped tests
- **Before `/gsd-verify-work`:** full suite green, plus `ruff check` and `pyright`
  clean (CLAUDE.md's definition of "done")
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Task IDs are assigned when plans are written; rows below are keyed by requirement
and behaviour until then.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-T1 | 16-01 | 1 | EUS-03 | — | N/A | unit | `uv run pytest tests/test_eustack_rules.py -k pool_occupancy -x` | ❌ W0 | ⬜ pending |
| 16-01-T2 | 16-01 | 1 | EUS-03 | — | `unclassified` (subsystem `None`) never folded into a pool nor into another pool's denominator | unit | `uv run pytest tests/test_eustack_rules.py -k unclassified_not_pooled -x` | ❌ W0 | ⬜ pending |
| 16-01-T1 | 16-01 | 1 | EUS-03 | — | N/A | unit (fixture) | `uv run pytest tests/test_eustack_rules.py -k reference_derivative_occupancy -x` | ✅ fixture exists | ⬜ pending |
| 16-02-T1 | 16-02 | 2 | EUS-04 | T-16-02 | N/A | unit | `uv run pytest tests/test_eustack_rules.py -k lock_site_walk -x` | ❌ W0 | ⬜ pending |
| 16-02-T1 | 16-02 | 2 | EUS-04 | T-16-02 | Walk skips `std::` / `boost::` / `__gnu_cxx::` / `abi::` frames (D-04 amended) | unit | `uv run pytest tests/test_eustack_rules.py -k lock_site_skips_runtime_namespace -x` | ❌ W0 | ⬜ pending |
| 16-02-T1 | 16-02 | 2 | EUS-04 | T-16-02 | Denylist matches on leading namespace, never substring — a `MBase::` frame nested inside a `std::` template argument is not misjudged | unit | `uv run pytest tests/test_eustack_rules.py -k lock_site_template_arg -x` | ❌ W0 | ⬜ pending |
| 16-02-T1 | 16-02 | 2 | EUS-04 | T-16-01 | No qualifying frame above the leaf → unknown-but-counted, never dropped, never attributed to the leaf | unit | `uv run pytest tests/test_eustack_rules.py -k lock_site_unknown -x` | ❌ W0 | ⬜ pending |
| 16-02-T3 | 16-02 | 2 | EUS-04 | T-16-01 | Output vocabulary never contains "deadlock" / "owner" / "holder" (V11 business-logic invariant; extends the shipped `test_no_ownership_attributed_lock_language_in_shipped_surface` pattern) | unit | `uv run pytest tests/test_eustack_rules.py -k ownership_blind -x` | ❌ W0 | ⬜ pending |
| 16-02-T2 | 16-02 | 2 | EUS-04 | — | N/A | unit (synthetic, D-11) | `uv run pytest tests/test_eustack_rules.py -k synthetic_lock_convergence -x` | ❌ W0 | ⬜ pending |
| 16-03-T1 | 16-03 | 3 | EUS-05 | T-16-06 | N/A | unit | `uv run pytest tests/test_eustack_rules.py -k dependency_split -x` | ❌ W0 | ⬜ pending |
| 16-03-T1 | 16-03 | 3 | EUS-05 | T-16-06 | Warehouse and HTTP waits separately visible, never merged into one blocked total | unit (fixture) | `uv run pytest tests/test_eustack_rules.py -k reference_derivative_dependency -x` | ✅ fixture exists | ⬜ pending |
| 16-03-T2 | 16-03 | 3 | EUS-06 | T-16-04 | `EustackAnalysis.signatures` read directly, not re-derived; `EustackAnalysis` itself unmodified (D-10) | unit | `uv run pytest tests/test_eustack_rules.py -k signature_passthrough -x` | ❌ W0 | ⬜ pending |
| 16-01-T1 | 16-01 | 1 | SC-5 | — | Every graded flag prints raw computed value beside configured threshold | unit | `uv run pytest tests/test_eustack_rules.py -k flag_value_and_threshold -x` | ❌ W0 | ⬜ pending |
| 16-04-T1 | 16-04 | 4 | SC-5 / D-09 | T-16-09 | The derivative fixture raises zero warn/critical flags for the two families it can faithfully exercise (`no_resolvable_frame_pct`, `lock_convergence_count`) — see the D-09 gate note below | unit (fixture) | `uv run pytest tests/test_eustack_rules.py -k reference_derivative_zero_flags -x` | ✅ fixture exists | ⬜ pending |
| 16-04-T1 | 16-04 | 4 | SC-5 / D-09 | T-16-09 | **The healthy reference capture's MEASURED composition raises ZERO flags above `info`** — the real gate on the chosen defaults | unit (constructed input) | `uv run pytest tests/test_eustack_rules.py -k measured_reference_composition -x` | ❌ W0 | ⬜ pending |
| 16-04-T1 | 16-04 | 4 | SC-5 | T-16-11 | All three flag families covered, each carrying value beside both cut-points, with a non-vacuity guard | unit | `uv run pytest tests/test_eustack_rules.py -k flag_family_prints_value -x` | ❌ W0 | ⬜ pending |
| 16-01-T3 | 16-01 | 1 | SC-5 / D-08 | V5 | New `[eustack]` threshold config keys are strict Pydantic (`extra="forbid"`) — a typo'd key fails loudly at config-load time | unit | `uv run pytest tests/test_config.py -k eustack_threshold -x` | ❌ W0 | ⬜ pending |
| 16-03-T3 | 16-03 | 3 | D-12 | T-16-07 | Determinism: pools, lock sites, dependencies and flags each have an explicit total-order sort key with a named tie-break; no `Counter.most_common()`, no set iteration | unit | `uv run pytest tests/test_eustack_rules.py -k deterministic_ordering -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### D-09 gate note — why the gate is split across two tests

Measured at plan time against the committed fixture: it reads **38.10%**
unclassified thread share (40 of 105) where the real capture reads **1.33%**
(52 of 3,902) — a **28-fold inflation**. The cause is structural, not a defect:
`reference_capture_derivative.txt` preserves all 93 signatures but caps thread
counts at 1 per signature (5 for the three highest-population ones), and those
three capped signatures are all classified, so capping deflates the classified
population by roughly 3,000 threads while leaving the unclassified population
nearly intact. The fixture is faithful to signature composition and deliberately
unfaithful to thread weight.

The derivative therefore CANNOT gate the two thread-weighted ratio flags. It
does faithfully gate `no_resolvable_frame_pct` (genuinely 0.0% there) and
`lock_convergence_count` (genuinely zero sites — Rule 6 matches a healthy
capture zero times by design). The real D-09 gate is
`-k measured_reference_composition`, which constructs an `EustackAnalysis` at
the reference capture's measured composition (3,902 threads / 52 unclassified /
0 no-resolvable-frame / 0 `blocked-on-lock`, figures from ADR 0015 and
CONTEXT.md) and asserts every flag grades `info` against the SHIPPED defaults.

Raising `unclassified_thread_pct.warn` above 38.1% so the derivative passes is
an explicitly REJECTED resolution — it would ship a threshold calibrated against
a cap policy rather than a server. See `16-04-PLAN.md` § S-8 and ADR 0016.

---

## Wave 0 Requirements

- [ ] No new framework install — pytest already present.
- [ ] No new fixture file strictly required — `tests/test_eustack_rules.py`'s
      `_thread_raw()` / `_event()` helpers can synthesise D-11's lock-convergence
      scenario inline, avoiding a fixture file that must simultaneously look
      synthetic and parse like a real capture.
- [ ] If the planner places the new code in a sibling module
      (`eustack_saturation.py`) rather than extending `eustack.py`, a new
      `tests/test_eustack_saturation.py` needs the three helpers imported (not
      duplicated).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The named reference-capture figures — ~3,400 parked pool workers reading as idle, 79 warehouse waits, 78 HTTP waits, 3,902 → 93 signature collapse, and zero raised flags | EUS-03, EUS-05, EUS-06, SC-5 | The CI fixture is a signature-preserving derivative with thread counts capped low, so it cannot reproduce absolute counts. The real 2.4 MB capture is deliberately out-of-repo (carries a customer environment identifier). | At phase verification, run the analysis against `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` and confirm each figure. CI asserts the *shape* (split exists, is non-merged, ordering is stable); the real capture asserts the *numbers*. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
