---
phase: 05-domain-adapters-journald-dsserrors-eustack
verified: 2026-07-18T00:00:00Z
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
requirements_verified: [INGST-07, INGST-08, INGST-09]
gate:
  ruff: clean
  pyright: "0 errors, 0 warnings, 0 informations"
  pytest: "374 passed, 2 deselected (pre-existing live-UAT markers)"
notes:
  - "dsserrors line layout + SID token shape and eustack format identity remain [ASSUMED] (RESEARCH-derived), signed off via the 05-02 'proceed-on-assumed-shapes' checkpoint (2026-07-18). Not a gap: regexes are anchored on version-stable structural tokens and flagged [ASSUMED] in-docstring, so pinning them to a real sanitised sample is a localised change. Recommended (not blocking) future validation against a real MicroStrategy sample."
  - "SPEC §5.2 self-containment: the 05-03 journald commit renamed genericlog._byte_lines -> byte_lines (promote a private helper to a shared byte-split seam). Detection dispatch (detect/SNIFF_THRESHOLD/parse_adapter_overrides) is byte-unchanged; genericlog behaviour unchanged (regression-guarded, full suite green). A one-time shared-utility promotion, in the spirit of the 05-01 enabler wave — noted, not a defect."
---

# Phase 5: Domain Adapters (journald, dsserrors, eustack) Verification Report

**Phase Goal:** Parallel-safe leaf adapters encoding MicroStrategy and systemd domain knowledge (M5) — real production diagnostics (systemd journals, MicroStrategy DSSErrors logs, EU-stack thread dumps) flow through the proven pipeline.
**Verified:** 2026-07-18
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | journald parses `journalctl -o json` at ≥95% coverage; PRIORITY→severity, _SYSTEMD_UNIT→component, _PID/_COMM→attrs | ✓ VERIFIED | `journald.py:88-213`; `test_journald.py::test_priority_full_range_maps_to_six_value_set`, `test_field_mapping`, `test_basic_fixture_coverage_bounded` (95.0 ≤ pct < 100.0) — all pass |
| 2 | dsserrors ≥95% coverage: SIDs, 0x codes, multi-node tags; multi-line MCM blocks as single events; rotated `.bak` siblings ordered by content not filename | ✓ VERIFIED | `dsserrors.py:185-352`; `test_token_extraction_error_record`, `test_mcm_full_block_is_one_event`, `test_rotation_ordered_by_ts_not_filename`, `test_node_tagging_distinct_per_subdirectory`, `test_coverage_bounded_non_vacuous` (0.95 ≤ cov < 1.0) — all pass |
| 3 | eustack yields exactly one event per thread; condensed top frames in `message`, full stack in `raw`, lock info in attrs | ✓ VERIFIED | `eustack.py:142-278`; `test_thread_count_matches_thread_headers_on_fixture` (4 threads), `test_condensed_frames_in_message_full_block_in_raw`, `test_no_lock_attrs_native_format` — lock clause satisfied by asserting ABSENCE per confirmed native eu-stack format (05-02) |
| 4 | Mixed-timezone multi-node fixture produces a correctly ordered UTC timeline (causality never silently inverted) | ✓ VERIFIED | `dsserrors.py` via shared `base.to_utc`/`tz_override_for`; `test_timezone_mixed_tz_timeline_not_causally_inverted` — node2 14:00 London (UTC) precedes node1 10:00 New York (15:00 UTC); ordering preserved, confidence `inferred` — passes |

**Score:** 4/4 truths verified (0 present, behaviour-unverified)

All four are behaviour-dependent (state/ordering/grouping invariants) and each is confirmed by a **passing behavioural test**, not symbol presence alone.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/adapters/journald.py` | JournaldAdapter (sniff+parse, _field_to_str, severity) | ✓ VERIFIED | 225 lines; registered; wired via CLI; e2e coverage 0.9882 |
| `src/sift/adapters/dsserrors.py` | DsserrorsAdapter (tokens, MCM, node, rotation, tz) | ✓ VERIFIED | 352 lines; registered; e2e coverage 0.9853 |
| `src/sift/adapters/eustack.py` | EustackAdapter (one-event-per-thread, condensed frames) | ✓ VERIFIED | 278 lines; registered; e2e coverage 0.9699 |
| `src/sift/adapters/base.py` | ConfigurableAdapter + to_utc/tz_override_for (05-01 enabler) | ✓ VERIFIED | `base.py:76-114`; subclassed by all four adapters |
| `src/sift/adapters/__init__.py` | REGISTRY carries all four; detect() byte-unchanged | ✓ VERIFIED | `__init__.py:18-23`; registration commit c638a4a = +6 lines only |
| tests/fixtures/{journald,dsserrors,eustack} | Sanitised per-format fixtures incl. multi-node + rotated | ✓ VERIFIED | 7 fixture files present incl. node1/node2 + .bak00/.bak01 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `cli.py` ingest loop | each ConfigurableAdapter | `isinstance(...ConfigurableAdapter)` sets input_root/tz_overrides | ✓ WIRED | `cli.py:272-274` — config reaches every adapter, not just genericlog |
| `cli.py` ingest loop | real per-file coverage | reads `last_stats.coverage` for any ConfigurableAdapter | ✓ WIRED | `cli.py:348-367` — stats=None→cov=1.0 fallback only for non-ConfigurableAdapter; fabricated-100% bug closed |
| `adapters.detect()` | three domain adapters | generic sniff over REGISTRY.values() | ✓ WIRED | detect() byte-unchanged; `test_phase5_fixture_routes_to_own_adapter` passes for all three |

### Behavioural Spot-Checks (named invariant tests, run individually)

| Behaviour | Test | Result |
|-----------|------|--------|
| Each fixture routes to its own adapter | `test_phase5_fixture_routes_to_own_adapter[journald/dsserrors/eustack]` | ✓ PASS |
| No cross-collision (unique max ≥ threshold) | `test_phase5_no_cross_collision[×3]` | ✓ PASS |
| MCM block = one event | `test_mcm_full_block_is_one_event` | ✓ PASS |
| Rotated siblings ordered by ts, not filename | `test_rotation_ordered_by_ts_not_filename` | ✓ PASS |
| Mixed-tz timeline not causally inverted | `test_timezone_mixed_tz_timeline_not_causally_inverted` | ✓ PASS |
| Real sub-100% coverage (not fabricated) | dsserrors/eustack/journald `test_coverage_bounded_non_vacuous` / `test_basic_fixture_coverage_bounded` | ✓ PASS |
| One event per thread | `test_thread_count_matches_thread_headers_on_fixture` | ✓ PASS |
| No fabricated lock attrs (native format) | `test_no_lock_attrs_native_format` | ✓ PASS |
| event_id determinism plain vs gzip | `test_event_id_plain_vs_gzip_identical` | ✓ PASS |
| End-to-end sift new→ingest→show, idempotent | `test_phase5_e2e_ingest_show_real_coverage_idempotent[×3]` (15/14/6 events; 2nd ingest "0 new") | ✓ PASS |
| _sanitise strips ESC in domain-adapter field | `test_phase5_show_sanitises_domain_adapter_escape_bytes` | ✓ PASS |

20/20 named tests pass individually (not merely inside the aggregate).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| INGST-07 | 05-03, 05-06 | journald adapter (PRIORITY→severity, unit→component, PID/COMM→attrs) | ✓ SATISFIED | journald.py + tests + e2e |
| INGST-08 | 05-04, 05-06 | dsserrors (ts/thread/severity/component, MCM, 0x, SIDs, OIDs, multi-node) | ✓ SATISFIED | dsserrors.py + tests + e2e |
| INGST-09 | 05-05, 05-06 | eustack (one event/thread, condensed frames, full stack in raw, lock info where present) | ✓ SATISFIED | eustack.py + tests + e2e; lock clause = ABSENCE under confirmed native format |

No orphaned requirements — REQUIREMENTS.md maps INGST-07/08/09 to Phase 5, all claimed by plans.

### Load-Bearing Invariants

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Nothing disappears silently (unparseable → severity="unknown", real coverage <100%, no fabricated 100%) | ✓ HOLDS | Every adapter byte-accounts fallback into unknown events; `assert_span_partition` proves byte spans partition the file; coverage tests assert 0.95 ≤ cov < 1.0 with unknown_fallback_bytes > 0 |
| Multi-line records = one event | ✓ HOLDS | MCM blocks (dsserrors) and thread blocks (eustack) each one event, with 256-line/64KB safety caps force-closing into unknown continuations |
| Timestamps → UTC with confidence, never invented | ✓ HOLDS | shared `to_utc` (exact/inferred); missing → ts=None/"missing"; eustack invents no per-thread times |
| Determinism / event_id unaffected | ✓ HOLDS | byte-offset event_id on raw stream; plain-vs-gzip identical test passes |
| SPEC §5.2: adding adapter = new module + registration; detection byte-unchanged | ✓ HOLDS (with note) | detect()/SNIFF_THRESHOLD/parse_adapter_overrides byte-unchanged; registration = +6 lines. Minor: 05-03 promoted genericlog._byte_lines→byte_lines (shared seam) — see frontmatter note |

### Anti-Patterns Found

None. No TBD/FIXME/XXX/HACK/placeholder markers in the three adapters. No stubs — all three registered and reachable through `sift ingest`; the SUMMARY declares "Known Stubs: None" and it holds.

### Human Verification (recommended, not blocking)

The 05-02 `blocking-human` checkpoint was resolved **"proceed-on-assumed-shapes"** (2026-07-18): the dsserrors record layout / SID token shape and the eustack format identity (native elfutils eu-stack vs JVM) are RESEARCH-derived assumptions, explicitly flagged `[ASSUMED]` in the adapter docstrings and anchored on version-stable structural tokens. This is a **signed-off deferral**, not an open gap. If a real sanitised DSSErrors.log / eustack dump later surfaces, a small gap-closure plan pins the `[ASSUMED]` regexes to ground truth — a localised regex change, no structural re-plan.

### Gaps Summary

None. All four ROADMAP success criteria are verified by passing behavioural tests; INGST-07/08/09 are satisfied end-to-end; the quality gate (ruff clean, pyright 0/0/0, pytest 374 passed) is green; the SPEC §5.2 self-containment invariant holds and the fabricated-100%-coverage regression is closed. The two `[ASSUMED]` proprietary-format shapes are a user-signed-off condition (05-02), correctly honoured in code.

---

_Verified: 2026-07-18_
_Verifier: Claude (gsd-verifier)_
