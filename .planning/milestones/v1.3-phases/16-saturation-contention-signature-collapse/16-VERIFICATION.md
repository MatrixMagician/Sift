---
phase: 16-saturation-contention-signature-collapse
verified: 2026-07-25T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 16: Saturation, Contention & Signature Collapse Verification Report

**Phase Goal:** An engineer sees why the server is — or demonstrably is not — saturated, from
occupancy, lock convergence, external-wait concentration and signature population, every figure
computed model-free
**Verified:** 2026-07-25
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Per-pool occupancy shows busy-vs-parked split per pool; healthy capture's ~3,400 parked pool workers read idle, not saturated | ✓ VERIFIED | `PoolOccupancy`/`analyse_saturation()` in `src/sift/pipeline/eustack.py:524-543,642-663`. Ran the real out-of-repo capture (`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/...160739...txt`, 3,902 threads/93 signatures): `job-queue` pool reads `total=1716, idle=1716, occupancy=0.0`; summed `idle_threads` across all 17 pool rows = 3,651 of 3,902 (93.6%) — in line with the roadmap's "~3,400" estimate. `test_reference_derivative_occupancy_reads_pools_as_idle` pins the same shape on the committed fixture. |
| 2 | Threads converging on a lock path reported with site+count, always ownership-blind; "deadlock" never appears in output | ✓ VERIFIED | `enclosing_application_frame()` (eustack.py:263-311), `LockSite` (eustack.py:546-564), `LOCK_FINDING_NOTE`/`UNKNOWN_LOCK_SITE` constants free of the three D-05 terms. `test_ownership_blind_vocabulary_absent_from_source_and_emitted_output` asserts word-boundary absence over real+synthetic emitted strings with a non-vacuity guard. `grep -rin "deadlock" src/` → 0 hits (confirmed independently). Real capture: `lock_sites == ()`, zero `lock_convergence_count` flags — Rule 6 matches a healthy capture zero times, exactly as ADR 0015 documents. |
| 3 | External waits split by dependency; warehouse and HTTP waits separately visible, never merged into one blocked total | ✓ VERIFIED (see note) | `DependencyWait`/dependency pass (eustack.py:566-594,696-729). Real capture: `[('http', 96), ('warehouse', 92), ('ipc', 6)]` — three distinct, non-merged rows; neither figure equals the sum of the others. Two rules (`CDSSQueryEngine::WaitUntilFinished`=79 raw matches + `MDb::Wrapper::InterpretStatus`=13 raw matches) correctly aggregate into one `warehouse`=92 row (D-06 proven). **Note:** ROADMAP.md/16-CONTEXT.md's illustrative reference figures ("79 warehouse waits… and 78 HTTP waits") do not match the measured real-capture output (92 warehouse, 96 HTTP) — see Gaps/Findings below. The split *mechanism* is proven correct; the *specific digits quoted in planning prose* are stale. |
| 4 | Thread population collapsed to distinct stack signatures ranked by thread count (3,902 → 93 on reference capture), each carrying role | ✓ VERIFIED | `EustackAnalysis.signatures` (Phase 15, read-through per EUS-06/D-10). Real capture: `total_threads=3902`, `total_signatures=93` — exact match to the roadmap's own headline figures. `test_signature_passthrough_reads_eustack_analysis_directly` mechanically pins `SaturationAnalysis.model_fields` to exclude any duplicated signature list and pins `EustackAnalysis` frozen/`extra=forbid`/field-set unchanged. |
| 5 | Every graded flag prints raw value beside configured threshold; healthy reference capture raises zero flags | ✓ VERIFIED | `SaturationFlag` carries `value`/`warn`/`critical` together (eustack.py:486-521); `test_every_flag_family_prints_value_beside_threshold` proves this + independently recomputed severity for all three families. `test_measured_reference_composition_raises_zero_flags` gates the shipped `EustackThresholdsConfig()` defaults against the measured 3,902/52-unclassified composition — every flag `info`. Ran the real capture directly: `unclassified_thread_pct info 1.3`, `no_resolvable_frame_pct info 0.0`, zero `lock_convergence_count` flags — zero flags above `info`, matching D-09 exactly. |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/config.py :: EustackThresholdsConfig` | 3 `ThresholdPair` fields under `[eustack.thresholds]` | ✓ VERIFIED | Present at lines 125-146; defaults confirmed via `load_config()` round-trip (5.0/15.0, 5.0/15.0, 5.0/20.0). |
| `src/sift/pipeline/eustack.py :: SaturationFlag/PoolOccupancy/LockSite/DependencyWait/SaturationAnalysis/analyse_saturation` | All frozen models + pure function | ✓ VERIFIED | All present, frozen, `extra="forbid"`; `analyse_saturation()` is pure over `EustackAnalysis` (D-10, D-12 — zero LLM/network calls on the path). |
| `enclosing_application_frame()` | Public, unit-testable D-04 walk | ✓ VERIFIED | Present at eustack.py:263-311; walks `frame_index+1:`, denylist is a leading-namespace prefix test (`str.startswith`), reuses `_is_resolvable()`. Directly executed against real fixture-derived shapes in this verification and in the test suite — resolves correctly in both directions on template-argument-list frames. |
| `docs/decisions/0016-eustack-saturation-analysis.md` | ADR recording S-1..S-8 + Known Limitations | ✓ VERIFIED | 214 lines; sections Context/Decision/Known limitations/Consequences/Alternatives considered present. |
| Test files (`test_eustack_rules.py`, `test_config.py`) | New tests per plan | ✓ VERIFIED | `test_eustack_rules.py -q` → 57 passed. Full suite (already confirmed by orchestrator): 742 passed, 8 deselected. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `analyse_eustack()` → `EustackAnalysis` | `analyse_saturation()` → `SaturationAnalysis` | Sole data path, `EustackAnalysis` read-only | ✓ WIRED | Confirmed by direct execution against the real capture; `EustackAnalysis` field set and frozen/`extra=forbid` contract mechanically pinned by `test_signature_passthrough_reads_eustack_analysis_directly`. |
| `SiftConfig.eustack.thresholds` | `analyse_saturation(thresholds=...)` → `_grade()` → `SaturationFlag.severity` | Config reaches grading with no module-level global | ✓ WIRED | `_grade` imported from `mcm.py` (line 48); severities independently recomputed and matched in `test_every_flag_family_prints_value_beside_threshold`. |
| Rule 6 (`__lll_lock_wait`, `frame_index`) | `enclosing_application_frame()` → `LockSite.site` | Sole attribution path | ✓ WIRED | `frame_index` structurally non-`None` for `blocked-on-lock` groups (asserted in code, eustack.py:676-678); proven on both real (zero matches) and synthetic (D-11) data. |
| `eustack_roles.toml` `subsystem` values | `PoolOccupancy`/`DependencyWait` rows | Curated rules file IS the pool/dependency axis | ✓ WIRED | Confirmed against real capture: 17 distinct pool rows including `compute` (1 thread) and `cube-generation` (4 threads) present on identical terms to `job-queue` — no allowlist (D-01). |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EUS-03 | 16-01 | Per-pool occupancy | ✓ SATISFIED | `[x]` in REQUIREMENTS.md, Traceability row `Complete`; verified above (Truth 1). |
| EUS-04 | 16-02 | Ownership-blind lock convergence | ✓ SATISFIED | `[x]`/`Complete`; verified above (Truth 2). |
| EUS-05 | 16-03 | External-wait concentration split by dependency | ✓ SATISFIED | `[x]`/`Complete`; verified above (Truth 3, with the documentation-accuracy note). |
| EUS-06 | 16-03 | Signature collapse read-through | ✓ SATISFIED | `[x]`/`Complete`; verified above (Truth 4). |

No orphaned requirements: `.planning/REQUIREMENTS.md`'s Phase 16 mapping is exactly EUS-03..EUS-06, and all four appear in at least one plan's `requirements:` frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/sift/pipeline/eustack.py` | 68-95 (`Rule.subsystem`) | No non-empty validation on `subsystem`, unlike `pattern` (WR-01, 16-REVIEW.md) | ⚠️ Warning (non-blocking) | A rules-file edit leaving `subsystem = ""` would ship a malformed, unnamed pool/dependency row instead of failing at load. Does not affect any of the five roadmap success criteria on the shipped 24 rules (all carry real subsystem strings). |
| `src/sift/config.py` | 236-249 (merge loop) | Comment says "deep-merge" but only merges one level; latent bug for 3-level-nested `EustackThresholdsConfig`/`McmThresholdsConfig` (WR-02, 16-REVIEW.md) | ⚠️ Warning (non-blocking) | Currently unreachable: no CLI flag targets `eustack.thresholds.*` yet (`grep -n "thresholds" src/sift/cli.py` → no hits). Confirmed still unreachable at verification time. |
| — | — | `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` scan | ✓ Clean | 0 hits across `eustack.py`, `config.py`, `tests/test_eustack_rules.py`, `tests/test_config.py`, ADR 0016. |

Both warnings were identified and disposed as non-blocking by `16-REVIEW.md` (0 critical / 2 warning / 2 info); independently re-confirmed here by reading the flagged code directly. Neither threatens a roadmap success criterion.

### Behavioral Spot-Checks (run directly against the real out-of-repo reference capture)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full pipeline on real capture, file 1 (`...160739...txt`) | `analyse_saturation(analyse_eustack(EustackAdapter().parse(...)), EustackThresholdsConfig())` | `total_threads=3902, total_signatures=93, unclassified=52 (1.33%)`, zero flags above `info`, `lock_sites=()` | ✓ PASS |
| Full pipeline on real capture, file 2 (`...160837...txt`, 1 min later) | same | `total_threads=3903, total_signatures=84, unclassified=52 (1.33%)`, both flags `info` | ✓ PASS (consistency check across the two-file diff pair) |
| `deadlock` absent from `src/` | `grep -rin "deadlock" src/` | 0 hits | ✓ PASS (already confirmed by orchestrator; re-confirmed here) |
| `test_eustack_rules.py` full file | `uv run pytest tests/test_eustack_rules.py -q` | 57 passed | ✓ PASS |

### Manual / Out-of-Repo Verification (16-04-PLAN.md `<human-check>`, now executed)

16-04-PLAN.md deferred one check to "after the full suite is green, run the analysis against the
out-of-repo reference capture and confirm all five reference figures." I have direct filesystem
access to that capture (`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`) and ran it
during this verification rather than leaving it open. Results against the five named figures:

1. **~3,400 parked pool workers reading as idle** — measured 3,651 of 3,902 (93.6%) idle-parked. Matches the qualitative claim; the roadmap's "~3,400" is an approximation and is not contradicted.
2. **79 warehouse waits (`CDSSQueryEngine::WaitUntilFinished`)** — the raw pattern match count is exactly 79 (`grep -c` confirms). The pipeline's aggregated `warehouse` **pool row** is 92 (79 + 13 `MDb::Wrapper::InterpretStatus` matches, correctly aggregated per D-06). The roadmap's "79" describes the single-pattern count, not the full subsystem total the shipped code reports — worth a documentation clarification, not a code defect.
3. **78 HTTP waits (`curl_multi_poll`)** — measured 96, not 78 (`grep -c "curl_multi_poll"` on the real capture file → 96, confirmed by two independent methods). This reference figure in ROADMAP.md/16-CONTEXT.md does not match the real capture. **Documentation-accuracy finding**, not a code defect: the code is correctly and deterministically computing the actual pattern-match count from the real data.
4. **3,902 threads collapsing to 93 signatures** — exact match.
5. **Zero raised flags** — confirmed: all emitted flags graded `info`, none `warn`/`critical`.

4 of 5 figures either match exactly or match within the roadmap's own stated approximation; figure 3 (and, to a lesser degree, figure 2's exact digit) diverge from the shipped code's correct output. This is recorded as a **non-blocking documentation finding** below, not a phase gap — the underlying capability (external waits split by dependency, separately visible, never merged) is verified correct against real data.

### Gaps Summary

No blocking gaps. One documentation-accuracy finding, recommended for a follow-up edit (not required to close Phase 16):

- **ROADMAP.md § Phase 16 Success Criterion 3 and 16-CONTEXT.md D-06** cite "79 warehouse waits… and 78 HTTP waits" as the real reference-capture figures. Direct execution against the actual out-of-repo capture during this verification shows the shipped code's real output is `warehouse=92` (two rules aggregating, correctly, per D-06) and `http=96`. The `79` figure is exactly right only for the single `CDSSQueryEngine::WaitUntilFinished` pattern count in isolation; the `78` figure does not match any measured quantity found (raw `curl_multi_poll` matches = 96 on both files in the two-file diff pair). Suggest updating the roadmap/context prose to the measured figures (92/96) so a future reader is not misled; no code or test changes are implied, since no CI assertion depends on the stale digits (the committed-fixture test asserts the fixture's own 8/5/2 split, and its docstring already separately, correctly notes the real capture's 92/96... actually notes 79/78 — worth correcting alongside the roadmap text).

---

_Verified: 2026-07-25_
_Verifier: Claude (gsd-verifier)_
