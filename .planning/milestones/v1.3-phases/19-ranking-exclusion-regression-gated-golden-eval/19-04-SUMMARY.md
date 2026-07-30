---
phase: 19-ranking-exclusion-regression-gated-golden-eval
plan: 04
subsystem: eval
tags: [eval-harness, eu-stack, golden-fixture, fixture-authorship, regression-gate]

# Dependency graph
requires:
  - phase: 19-ranking-exclusion-regression-gated-golden-eval
    provides: "19-02: ExpectEustack truth block, CaseResult.is_eustack exclusion, _run_eustack_case client-free scoring"
  - phase: 19-ranking-exclusion-regression-gated-golden-eval
    provides: "19-03: eustack_detection_rate gate floor, no_eustack_cases vacuity guard, eustack-healthy case-directory precedent"
provides:
  - "eval/cases/eustack-hang-pool-warehouse/ — the synthetic positive golden case: observed warehouse-wait/idle-parked frames copied from the real reference capture, an authored population (25 saturated + 10 idle noise), figures measured not guessed"
  - "eval/cases/eustack-hang-pool-warehouse-mutated/ — its shipped, hand-authored cosmetic-mutation twin (renumbered TIDs, interleaved block order, offset addresses), proven to reproduce identical figures"
  - "test_eustack_hang_twin_reproduces_identical_figures — non-vacuity-guarded figure-equality proof between the positive and its twin"
  - "test_eustack_gate_is_analyser_sensitive — D-19-14 sensitivity gate: sift eval exits non-zero when load_rules is neutered at the seam, shipped rules file proven untouched"
  - "_EXPECTED_CASES/count -> 11; sift eval --help documents the D-19-16 LLM-free eu-stack split"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fixture authorship discipline: frames OBSERVED (copied byte-for-byte from the real reference capture, only TIDs renumbered), population AUTHORED (thread counts chosen to make saturation unambiguous against noise) — never derived from src/sift/rules/eustack_roles.toml's own pattern strings"
    - "Cosmetic-mutation twin ships as a second committed fixture (never generated at test time): renumbered TID range, interleaved block order, every 0x address offset by a fixed constant, frame symbols byte-identical"
    - "Sensitivity-gate neuter applied at the load_rules import SEAM via monkeypatch (sift.pipeline.eustack.load_rules), never by editing the shipped TOML rules file on disk"

key-files:
  created:
    - eval/cases/eustack-hang-pool-warehouse/README.md
    - eval/cases/eustack-hang-pool-warehouse/truth.yaml
    - eval/cases/eustack-hang-pool-warehouse/input/threaddump.txt
    - eval/cases/eustack-hang-pool-warehouse-mutated/README.md
    - eval/cases/eustack-hang-pool-warehouse-mutated/truth.yaml
    - eval/cases/eustack-hang-pool-warehouse-mutated/input/threaddump.txt
  modified:
    - tests/test_eval_cases.py
    - src/sift/cli.py

key-decisions:
  - "Fixture composition: 25 warehouse-wait threads (CDSSQueryEngine::WaitUntilFinished, the majority of 2 observed frame-chain variants among the real capture's 79 genuinely-waiting threads) + 10 idle-parked job-queue noise threads (MSIQTask::GetNextPreferredJob) — population sizes chosen so the saturated pool is clearly larger than the noise population and the noise population is clearly more than a token handful (PITFALLS.md Pitfall 5 point 3), all real observed frames, all resolvable, so unclassified_thread_pct and no_resolvable_frame_pct both measure 0.0% (info) with zero lock sites — RESEARCH.md's Pattern 4 recommendation to also trip lock_convergence_count was explicitly NOT implemented per the plan's supersession warning (D-19-17/D-19-18 override RESEARCH.md here)"
  - "hang_detected: true stays declarative-only in truth.yaml (per _eustack_verdict's own docstring, D-19-17) — detection is proven exclusively by total_threads/pools/dependencies figure reproduction, never by bool(flags) or a new threshold"
  - "The sensitivity-test neuter strips the single rule whose pattern contains 'CDSSQueryEngine::WaitUntilFinished' at the load_rules import seam (sift.pipeline.eustack.load_rules, patched via monkeypatch since _run_eustack_case re-imports it locally on every call) rather than filtering by subsystem — this is the exact mechanism the positive case's figures depend on, so the neuter is proven to bite the specific detection path, not just any rule"

requirements-completed: [EUS-12]

coverage:
  - id: D1
    description: "A synthetic hang fixture built from the documented warehouse connection-pool exhaustion scenario is detected — analyse_eustack_bundle reproduces its declared pool-saturation and dependency-wait figures exactly"
    requirement: "EUS-12"
    verification:
      - kind: unit
        ref: "tests/test_eval_cases.py::test_eustack_healthy_case_scores_pass_offline (analog pattern) — figure comparison performed directly in truth.yaml via _eustack_verdict, exercised through run_case in test_eustack_gate_is_analyser_sensitive's INTACT branch"
        status: pass
      - kind: manual_procedural
        ref: "measured directly: total_threads=35, pools[warehouse]=busy 25/idle 0, dependencies[warehouse]=25, both percentage flags info/0.0%"
        status: pass
    human_judgment: false
  - id: D2
    description: "The same fixture stays detected under cosmetic mutation — renumbered TIDs, reordered thread blocks and different instruction addresses yield the SAME measured figures"
    requirement: "EUS-12"
    verification:
      - kind: unit
        ref: "tests/test_eval_cases.py::test_eustack_hang_twin_reproduces_identical_figures"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every synthetic positive is machine-marked provenance authored, and the healthy capture remains the only case marked observed"
    requirement: "EUS-12"
    verification:
      - kind: unit
        ref: "tests/test_eval_cases.py::test_only_the_healthy_case_is_marked_observed (now examines 3 eu-stack cases, still asserts observed == ['eustack-healthy'])"
        status: pass
    human_judgment: false
  - id: D4
    description: "The positive and its twin each occupy their own eval/cases/eustack-hang-*/ directory; both stay signature-preserving and small"
    requirement: "EUS-12"
    verification:
      - kind: unit
        ref: "tests/test_eval_cases.py::test_suite_is_exactly_the_eleven_cases"
        status: pass
      - kind: manual_procedural
        ref: "eustack-hang-pool-warehouse/input/threaddump.txt is 38,460 bytes; eustack-hang-pool-warehouse-mutated/input/threaddump.txt is 38,463 bytes (both <= 64KB cap)"
        status: pass
    human_judgment: false
  - id: D5
    description: "sift eval exits non-zero when the analyser is neutered so an eu-stack case stops reproducing its declared figures — the gate is proven to bite, not merely to be configured"
    requirement: "EUS-12"
    verification:
      - kind: integration
        ref: "tests/test_eval_cases.py::test_eustack_gate_is_analyser_sensitive"
        status: pass
    human_judgment: false
  - id: D6
    description: "A suite containing only the eu-stack cases runs to a verdict with an observably empty request log, and the split is stated in sift eval's own help text"
    requirement: "EUS-12"
    verification:
      - kind: integration
        ref: "tests/test_eval_cases.py::test_eustack_gate_is_analyser_sensitive (INTACT branch: exit 0, calls == [])"
        status: pass
      - kind: manual_procedural
        ref: "uv run sift eval --help | grep -ci 'no inference endpoint\\|without an inference endpoint' returns 1"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-07-27
status: complete
---

# Phase 19 Plan 04: Synthetic Hang Fixture, Mutation Twin & Sensitivity Gate Summary

**EUS-12's positive half lands: `eustack-hang-pool-warehouse` (25 observed-frame warehouse-wait threads + 10 idle noise threads, authored population) is detected via exact figure reproduction, its shipped cosmetic-mutation twin reproduces identical figures, and `sift eval` is proven — not merely configured — to exit non-zero when the analyser stops reproducing a declared figure.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-27
- **Completed:** 2026-07-27
- **Tasks:** 3 (all committed)
- **Files modified:** 8 (6 created, 2 modified)

## Accomplishments

- `eval/cases/eustack-hang-pool-warehouse/`: a synthetic warehouse connection-pool exhaustion, composed of real thread blocks copied byte-for-byte from the reference capture at `~/Downloads/iserver1_stacks_1-minute_diff/` (21 distinct normalised symbols, all verified present in the source capture) with an authored population (25 saturated + 10 idle) — `src/sift/rules/eustack_roles.toml` never opened while authoring. Measured figures: `total_threads=35`, `pools[warehouse]` busy 25/idle 0 (occupancy 1.0), `dependencies[warehouse]` thread_count 25, both percentage flags info/0.0%, zero lock sites.
- `eval/cases/eustack-hang-pool-warehouse-mutated/`: the shipped, hand-authored cosmetic-mutation twin — renumbered TID range (`800xxx` vs `900xxx`/`901xxx`), interleaved thread-block order, every `0x` instruction address offset by `+0x1000000000000`. Frame symbols stay byte-identical; measured figures are identical to the original's.
- `test_eustack_hang_twin_reproduces_identical_figures`: asserts non-vacuity (files differ, zero shared TIDs, zero shared addresses) BEFORE asserting the pool/dependency/total_threads tuples are equal between the two fixtures.
- `test_eustack_gate_is_analyser_sensitive`: a scoped 3-case eu-stack-only suite run through the real `sift eval` CLI. INTACT run: exit 0 and an observably empty recorded request log (proves D-19-16). NEUTERED run: `sift.pipeline.eustack.load_rules` monkeypatched to strip the `CDSSQueryEngine::WaitUntilFinished` rule — exit non-zero, `eustack_detection_rate` named in the output; `git diff --stat` on the shipped rules file confirmed empty afterwards.
- `_EXPECTED_CASES`/count updated to 11; `sift eval`'s command docstring gained one sentence recording the D-19-16 LLM-free eu-stack split, consistent with `runner.py`'s module docstring from 19-02.

## Task Commits

Each task was committed atomically:

1. **Task 1: Author the synthetic warehouse-pool-exhaustion golden case** - `d691c5b` (feat)
2. **Task 2: Ship the cosmetic-mutation twin and pin identical figures** - `5530da0` (test)
3. **Task 3: Register the positives, prove the gate bites, and document the LLM-free subset** - `2cf7aca` (test)

## Files Created/Modified

- `eval/cases/eustack-hang-pool-warehouse/README.md` - provenance (which frames observed vs authored, symbol-traceability check), measured figures, synthetic/weaker-evidence disclosure
- `eval/cases/eustack-hang-pool-warehouse/truth.yaml` - frozen `expect_eustack` block, every figure measured
- `eval/cases/eustack-hang-pool-warehouse/input/threaddump.txt` - the 35-thread synthetic dump (38,460 bytes)
- `eval/cases/eustack-hang-pool-warehouse-mutated/README.md` - the three mutations, non-vacuity proof, identical measured figures
- `eval/cases/eustack-hang-pool-warehouse-mutated/truth.yaml` - identical frozen `expect_eustack` block
- `eval/cases/eustack-hang-pool-warehouse-mutated/input/threaddump.txt` - the mutated dump (38,463 bytes)
- `tests/test_eval_cases.py` - `_EXPECTED_CASES`/count -> 11, module docstring updated, `test_eustack_hang_twin_reproduces_identical_figures`, `test_eustack_gate_is_analyser_sensitive`
- `src/sift/cli.py` - `eval_`'s docstring gains the D-19-16 LLM-free split sentence

## Decisions Made

- **Fixture composition measured empirically against the real capture, not guessed.** Grepped the reference capture directly: 79 threads carry `CDSSQueryEngine::WaitUntilFinished` (2 distinct frame-chain variants, 76/3 split — the majority variant was used), 1,715 threads carry `MSIQTask::GetNextPreferredJob` (a single frame-chain shape). Both are real, observed thread shapes; only the population counts (25 and 10) and TIDs are authored.
- **RESEARCH.md's Pattern 4 recommendation (trip `lock_convergence_count` so `bool(flags)` works) was explicitly NOT implemented**, per the plan's own supersession warning: D-19-17/D-19-18 establish detection as figure reproduction, and `_eustack_verdict`'s shipped implementation (landed in 19-02) already confirms `hang_detected` is never mechanically compared. Building the fixture to also trip lock convergence would have made the eval key on a scenario D-19-09 explicitly rejected as primary.
- **Neuter target for the sensitivity gate.** Chose to strip the rule whose pattern is `CDSSQueryEngine::WaitUntilFinished` (the exact rule the positive fixture's figures depend on) rather than a broader subsystem-based filter — this proves the gate is sensitive to the specific mechanism under test, following the pattern set by `test_mcm_denial_citation_validity_is_mcm_sensitive`'s targeted-strip approach.

## Deviations from Plan

None - plan executed exactly as written, including the supersession-warning constraint (RESEARCH.md's lock-convergence recommendation correctly not applied).

## Known Stubs

None.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. `sift eval`'s live, end-to-end gate verdict against the full 11-case suite still requires a running local inference endpoint for the eight non-eustack cases (unchanged from every prior phase's live-gate note); the eu-stack subset itself is fully proven offline by this plan's own tests.

## Next Phase Readiness

- EUS-12 fully closed: both halves (the real healthy capture from 19-03, and the synthetic hang fixtures from this plan) are landed, tested and machine-marked by provenance.
- Full gate green: `uv run ruff check` clean, `uv run pyright` unchanged at the pre-existing 31-error baseline (confined to `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py`), `uv run pytest` 833 passed / 8 deselected (831 baseline + 2 new: the twin-figure-equality test and the gate-sensitivity test).
- This is the final plan of Phase 19 (Ranking Exclusion & Regression-Gated Golden Eval) — both EUS-11 and EUS-12 are now complete, closing v1.3's eu-stack requirement set apart from DET-01 (Phase 20).

---
*Phase: 19-ranking-exclusion-regression-gated-golden-eval*
*Completed: 2026-07-27*

## Self-Check: PASSED

All 9 claimed files exist on disk (`eval/cases/eustack-hang-pool-warehouse/{README.md,truth.yaml,input/threaddump.txt}`,
`eval/cases/eustack-hang-pool-warehouse-mutated/{README.md,truth.yaml,input/threaddump.txt}`,
`tests/test_eval_cases.py`, `src/sift/cli.py`, this SUMMARY.md) and all three
task commit hashes (`d691c5b`, `5530da0`, `2cf7aca`) are present in
`git log --oneline --all`.
