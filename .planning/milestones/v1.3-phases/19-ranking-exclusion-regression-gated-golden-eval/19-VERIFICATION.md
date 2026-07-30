---
phase: 19-ranking-exclusion-regression-gated-golden-eval
verified: 2026-07-27T00:00:00Z
status: passed
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:

  - test: "sift analyze on the real eu-stack-only capture narrates the fact block (D-19-02)"
    expected: "Running `uv run sift analyze <case>` against a case ingested from ~/Downloads/iserver1_stacks_1-minute_diff/ does NOT print 'Nothing to cluster; run sift ingest first', reaches hypothesise(), and the resulting report narrates/cites eu-stack event ids."
    why_human: "Requires a live local inference endpoint (llama-server/Lemonade) that no agent in this environment can reach. This is the single item recorded in 19-VALIDATION.md's Manual-Only table; every other behaviour in this phase (exclusion, byte-identity + non-vacuity, citability, fixture detection, mutation invariance, and the sift eval gate) is verified automated and offline."
    result: passed
    signed_off: "2026-07-30 — executed against the operator's live Lemonade instance (127.0.0.1:13305, user.Qwen2.5-14B-Instruct). Ingested the real capture (7807 events across 2 dumps, 100% coverage) into case p19uat; template groups 0, confirming exclusion. `sift analyze p19uat` exited 0, printed `Clusters: 0 (0 labelled)` and `Hypotheses: 2` and did NOT print 'Nothing to cluster; run sift ingest first'. Both hypotheses narrate eu-stack findings ('HTTP and Warehouse Pools Are Fully Occupied', 'High Number of Idle-Parked Threads in Other Pools'); all 14 cited ids resolve in the store, every one source='eustack', and both carry citations_valid=True. The narrated claims match `sift eustack p19uat`'s COMPUTED figures exactly (http occupancy 1.0 at 97/97 busy, warehouse 1.0 at 94/94 busy, 3652 idle-parked), so the model narrated the deterministic core's numbers rather than authoring them."
---

# Phase 19: Ranking Exclusion & Regression-Gated Golden Eval Verification Report

**Phase Goal:** Eu-stack thread events stop competing in dedup/embed/cluster/salience now that the
deterministic replacement has shipped, and the whole eu-stack path is locked behind golden
regression gates.

**Verified:** 2026-07-27
**Status:** passed (human item signed off 2026-07-28 — see `19-UAT.md` test 20)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria, goal-backward)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1a | Ingesting eu-stack dumps leaves cluster/salience output byte-identical to the same case without them, non-vacuously | ✓ VERIFIED | `tests/test_cli.py::test_cluster_output_identical_with_and_without_eustack` (line 1501) asserts `a.output == b.output` on `sift show clusters`, with THREE explicit non-vacuity guards: (1) `a.output.strip() != ""` — case A genuinely renders clusters, ruling out a both-sides-empty pass; (2) `n_b > n_a` — the eu-stack dump was genuinely ingested, not silently dropped; (3) `n_b - n_a == _EUSTACK_THREADDUMP_EVENTS` — the exact measured delta. Case A carries a non-eu-stack ranked source (`with_csv=False` but a shared MCM log), so this is not an eu-stack-only comparison. Ran green: `uv run pytest tests/test_cli.py -k eustack -q` |
| 1b | Every eu-stack thread event remains individually retrievable/citable after exclusion | ✓ VERIFIED | `tests/test_store.py::test_get_events_returns_eustack`/`test_iter_event_rows_includes_eustack` and `tests/test_cli.py::test_every_eustack_event_citable_and_none_ranked` (line 1533, whole-population check, not one seeded event) and `test_show_events_includes_eustack` (line 1560). `src/sift/store.py:672-703` `iter_event_rows` is confirmed unfiltered (docstring: "Deliberately does NOT apply EXCLUDED_FROM_RANKING"), asymmetric with `iter_event_summaries` (line 645-670, `WHERE source NOT IN (...)` over `sorted(EXCLUDED_FROM_RANKING)`). All green. |
| 2 | The real healthy reference capture, run as the negative golden case, reports no hang and raises zero warn-or-critical flags with the expected info set declared (D-19-18 reading, not literal `flags==0`) | ✓ VERIFIED | `eval/cases/eustack-healthy/truth.yaml` declares `warn: 0, critical: 0, info_dimensions: [unclassified_thread_pct, no_resolvable_frame_pct]`, `hang_detected: false`, `provenance: observed`. `src/sift/eval/runner.py::_eustack_verdict` (lines 108-148) computes `warn_count`/`critical_count`/`info_dimensions` from `bundle.saturation.flags` by severity and compares exactly — this is the D-19-18/amendment reading, confirmed byte-for-byte against 19-CONTEXT.md's ratified decision text. `hang_detected` is explicitly NOT mechanically compared (docstring lines 114-119), matching D-19-17's rejection of `bool(flags)`. |
| 3 | Synthetic hang fixtures (authored, not observed) are detected, and stay detected under cosmetic mutation | ✓ VERIFIED | `eval/cases/eustack-hang-pool-warehouse/truth.yaml` declares `provenance: authored`; figures scored via the same `_eustack_verdict` figure-reproduction path (never `bool(flags)`, per D-19-17). `tests/test_eval_cases.py::test_eustack_hang_twin_reproduces_identical_figures` (line 491) proves the twin is NOT a copy first (disjoint addresses, disjoint TIDs, differing bytes) before asserting figure equality — mutation-invariance is a real, non-vacuous check. |
| 4a | `sift eval` exits non-zero on eu-stack regression | ✓ VERIFIED | `tests/test_eval_cases.py::test_eustack_gate_is_analyser_sensitive` (line 621): INTACT run exits 0 with an empty recorded HTTP call log; NEUTERED run (warehouse rule stripped at the `sift.pipeline.eustack.load_rules` import seam via monkeypatch — never on disk) exits non-zero and names `eustack_detection_rate` in output; a `git diff --stat` on the shipped `src/sift/rules/eustack_roles.toml` is asserted empty, proving the neuter never touched the frozen rules file. |
| 4b | A vacuous pass (empty positive eu-stack set) is impossible | ✓ VERIFIED | `src/sift/eval/thresholds.py`: `no_eustack_cases = not any(c.is_eustack and not c.run_failed for c in results)` (line 134) folded into `passed` via `and not no_eustack_cases` (line 142) — mirrors the existing `no_positive_cases` vacuity term exactly. `mean_eustack_detection_rate()` would read a vacuous `1.00` on an empty list, but the gate independently forces failure regardless. |

**Score:** 8/8 truths verified (0 present-but-behavior-unverified)

### D-19-02 payoff: eu-stack-only case reaches hypothesise()

✓ VERIFIED. `src/sift/cli.py:876-889`: the zero-groups guard now ANDs a cheap unfiltered probe
(`next(iter(store.iter_event_rows()), None) is None`) so a case with zero *template groups* but
non-zero *events* (an excluded-source-only case) falls through to `hypothesise()` instead of
printing the false "Nothing to cluster; run 'sift ingest' first". A genuinely empty case (zero
events at all) still short-circuits, unchanged. Pinned by
`tests/test_analyze.py::test_analyze_eustack_only_case_still_narrates` (line 198). Code matches
D-19-02's decision text in `19-CONTEXT.md` exactly.

### Decision honouring

- **D-19-17** ("detected" = measured figures match, never `bool(flags)`): confirmed —
  `_eustack_verdict` never reads a boolean flag presence; `hang_detected` is declarative-only.

- **D-19-18 / D-19-15 amendment** (severity-bucketed flag declaration, not `flags == 0`): confirmed
  in both `eustack-healthy/truth.yaml` (`warn: 0, critical: 0, info_dimensions: [...]`) and
  `_eustack_verdict`'s comparison logic.

- **RESEARCH.md's superseded "Pattern 4"** (engineering the fixture to also trip
  `lock_convergence_count` so `bool(flags)` would work): confirmed ABSENT —
  `grep lock_convergence_count eval/cases/eustack-hang-*/truth.yaml` returns nothing; the SUMMARY
  explicitly records this was declined per D-19-17/D-19-18 supersession.

- **D-19-16** (LLM-free split documented in the harness's own description): confirmed —
  `uv run sift eval --help` prints "The eu-stack golden cases (`eustack-*`) are scored
  deterministically against `analyse_eustack_bundle` and run without an inference endpoint at all
  (D-19-16); every other case in the suite still requires one."

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/store.py` | `EXCLUDED_FROM_RANKING` carries `dssperfmon` + `eustack` | ✓ VERIFIED | line 339: `frozenset({"dssperfmon", "eustack"})` |
| `src/sift/cli.py` | zero-groups guard distinguishes zero-events from zero-groups-with-events | ✓ VERIFIED | lines 876-889 |
| `src/sift/eval/truth.py` | `ExpectEustack` nested model, `extra=forbid` | ✓ VERIFIED | `tests/test_eval_truth.py::test_load_truth_eustack_unknown_key_raises` passes |
| `src/sift/eval/metrics.py` | `CaseResult.is_eustack`, exclusion from `_positive()`/`_scored()`, `mean_eustack_detection_rate` | ✓ VERIFIED | confirmed present by orchestrator pre-check; re-confirmed via passing test suite |
| `src/sift/eval/runner.py` | `_run_eustack_case` client-free sibling | ✓ VERIFIED | lines 151-218, dispatched before any HTTP client construction |
| `src/sift/eval/thresholds.py` | fifth `eustack_detection_rate` floor + `no_eustack_cases` vacuity guard | ✓ VERIFIED | lines 36, 78, 134, 142, 149 |
| `eval/cases/eustack-healthy/` | real-capture negative golden case, provenance observed | ✓ VERIFIED | `truth.yaml` present, `provenance: observed` |
| `eval/cases/eustack-hang-pool-warehouse/` + `-mutated/` | synthetic positive + cosmetic-mutation twin | ✓ VERIFIED | both present, `provenance: authored` in both |
| `tests/test_eval_cases.py` | sensitivity gate + mutation-invariance test | ✓ VERIFIED | lines 491, 621 |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `store.py::iter_event_summaries` | `EXCLUDED_FROM_RANKING` | `WHERE source NOT IN (...)` over `sorted()` values | ✓ WIRED |
| `cli.py::analyze` | `pipeline/hypothesise.py::hypothesise` | zero-groups guard falls through when events exist | ✓ WIRED |
| `eval/runner.py::run_case` | `_run_eustack_case` | early dispatch on `truth.expect_eustack is not None`, before client use | ✓ WIRED |
| `eval/thresholds.py::gate` | `metrics.py::SuiteResult.mean_eustack_detection_rate` | fifth entry in values map | ✓ WIRED |
| `eval/thresholds.py::gate` | `metrics.py::CaseResult.is_eustack` | `no_eustack_cases` folded into `passed` | ✓ WIRED |

### Behavioral Spot-Checks / Test Execution

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All eu-stack-tagged tests | `uv run pytest tests/test_cli.py tests/test_store.py tests/test_analyze.py tests/test_eval_cases.py tests/test_eval_thresholds.py tests/test_eval_truth.py -k eustack -q` | 32 passed | ✓ PASS |
| `sift eval --help` documents D-19-16 | `uv run sift eval --help` | prints the LLM-free eu-stack split sentence verbatim | ✓ PASS |
| Sensitivity gate genuinely bites | `test_eustack_gate_is_analyser_sensitive` (single named test, includes an internal `git diff --stat` check on the shipped rules file) | neutered run exits non-zero, names the metric, rules file untouched | ✓ PASS |

Already-verified-by-orchestrator (not re-run): `ruff check` clean, `pyright` at the pre-existing
31-error baseline (unrelated three test files), full `pytest` 834 passed, working tree clean.

### Requirements Coverage

| Requirement | Source Plans | Status | Evidence |
|-------------|-------------|--------|----------|
| EUS-11 | 19-01 | ✓ SATISFIED | `EXCLUDED_FROM_RANKING`, citation-path pin, byte-identity non-vacuous proof, `analyze` fall-through |
| EUS-12 | 19-02, 19-03, 19-04 | ✓ SATISFIED | `ExpectEustack`, `eustack_detection_rate` gate + vacuity guard, healthy negative case, synthetic positive + mutation twin, sensitivity gate |

REQUIREMENTS.md itself marks both `[x]` complete and lists Phase 19 as their sole source — no
orphaned requirements found.

### Anti-Patterns Found

None found in the phase's modified files that flow to rendered/citable output. `19-REVIEW.md`
(deep review, 19 files) reports `critical: 0, warning: 1, info: 1`, `status: fixed` — both findings
resolved via commits `6a62971`/`d464a2c` per project memory, prior to this verification pass.

### Human Verification Required

1. **`sift analyze` on the real eu-stack-only capture narrates the fact block (D-19-02)**
   **Test:** Ingest `~/Downloads/iserver1_stacks_1-minute_diff/` into a fresh case, run
   `uv run sift analyze <case>` against a live local inference endpoint.
   **Expected:** Does NOT print "Nothing to cluster; run 'sift ingest' first"; reaches
   `hypothesise()`; the report narrates and cites eu-stack event ids.
   **Why human:** Needs a live local inference endpoint (llama-server/Lemonade) that no agent in
   this sandboxed environment can reach. This is the sole item in 19-VALIDATION.md's Manual-Only
   table — everything else in the phase (exclusion, byte-identity with a real non-vacuity guard,
   citability, fixture detection, mutation invariance, and the `sift eval` regression gate) is
   automated, offline, and independently re-run green above.

### Gaps Summary

No gaps. All eight goal-backward truths (four ROADMAP success criteria, split where each criterion
carries two independently-testable halves) are verified against the shipped code, not against
SUMMARY.md prose — including the single most important check (criterion 1's non-vacuity guard,
which is a real three-part guard, not a bare equality assertion) and the D-19-18/D-19-15-amendment
reading of criterion 2, applied exactly as ratified in 19-CONTEXT.md. The phase's only open item is
the one the phase's own VALIDATION.md already flagged as requiring a live inference endpoint no
agent can reach — status is `human_needed`, not `gaps_found`.

---

_Verified: 2026-07-27_
_Verifier: Claude (gsd-verifier)_
