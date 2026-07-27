---
phase: 19-ranking-exclusion-regression-gated-golden-eval
reviewed: 2026-07-27T00:00:00Z
depth: deep
files_reviewed: 19
files_reviewed_list:
  - src/sift/store.py
  - src/sift/cli.py
  - src/sift/eval/truth.py
  - src/sift/eval/metrics.py
  - src/sift/eval/runner.py
  - src/sift/eval/thresholds.py
  - src/sift/eval/report.py
  - eval/thresholds.toml
  - eval/cases/eustack-healthy/truth.yaml
  - eval/cases/eustack-healthy/README.md
  - eval/cases/eustack-hang-pool-warehouse/truth.yaml
  - eval/cases/eustack-hang-pool-warehouse/README.md
  - eval/cases/eustack-hang-pool-warehouse-mutated/truth.yaml
  - eval/cases/eustack-hang-pool-warehouse-mutated/README.md
  - tests/fixtures/eustack/derive_reference_capture_derivative.py
  - tests/_eval_fixtures.py
  - tests/test_analyze.py
  - tests/test_cli.py
  - tests/test_eval_cases.py
  - tests/test_eval_thresholds.py
  - tests/test_eval_truth.py
  - tests/test_store.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: findings
---

# Phase 19: Code Review Report

**Reviewed:** 2026-07-27
**Depth:** deep
**Files Reviewed:** 19 source + test files (plus 3 golden-case truth/README pairs)
**Status:** issues_found (both non-blocking)

## Summary

Reviewed the full `7c7f132..HEAD` diff for EUS-11 (ranking exclusion) and EUS-12
(regression-gated eu-stack golden eval), verified every load-bearing invariant listed in the
review brief by reproduction rather than reading alone, and adjudicated both flagged concerns.

**What I reproduced, not just read:**

- Ran `analyse_eustack_bundle` directly against all three shipped eu-stack fixtures
  (`eustack-healthy`, `eustack-hang-pool-warehouse`, `eustack-hang-pool-warehouse-mutated`) plus
  the `tests/fixtures/eustack/threaddump.txt` smoke fixture used by `_eval_fixtures.py`. Every
  measured figure (`total_threads`, per-subsystem `busy_threads`, `dependencies`, flag
  severity/dimension sets) matches its `truth.yaml`/`_EUSTACK_SMOKE_TRUTH` declaration exactly.
- Read `SuiteResult._positive()`/`_scored()`/`mean_eustack_detection_rate()` in full: all four
  keyword aggregates exclude `is_eustack` cases, and the new metric reads only the inverse
  selection (`is_eustack and not run_failed`). No fifth code path re-admits an eu-stack case.
- Read `iter_event_summaries`/`iter_event_rows` in full: the asymmetry is intact, `sorted()` still
  fixes the `EXCLUDED_FROM_RANKING` parameter order, and the widened frozenset (`{"dssperfmon",
  "eustack"}`) doesn't touch that ordering seam.
- Read `_run_eustack_case` and confirmed it dispatches from `run_case` *before* any
  `InferenceClient`-touching code runs, and that `_ingest` (the only production call it makes) is
  pure local file parsing with no HTTP client construction anywhere on that path. Ran
  `test_eustack_healthy_case_scores_pass_offline` and `test_eustack_gate_is_analyser_sensitive`,
  both of which assert an *observed* empty HTTP call log rather than trusting code inspection.
- Ran `tests/test_store.py`, `tests/test_analyze.py`, `tests/test_cli.py`, `tests/test_eval_cases.py`,
  `tests/test_eval_thresholds.py`, `tests/test_eval_truth.py` together: 195 passed.
- Confirmed `eval/report.py`'s eu-stack column additions never touch CSV rendering — this module
  has no CSV writer at all (`_csv_safe` lives only in `render/perfmon_report.py` /
  `render/eustack_report.py`, both untouched by this phase), so invariant 8 ("CSV/report
  injection") does not apply to any file this phase changed.
- Confirmed the `cli.py` `analyze` guard change reads at most one row from the cheap
  `iter_event_rows()` generator (`next(iter(...), None)`), never `query_events()`, and that
  `test_analyze_eustack_only_case_still_narrates` proves the fall-through reaches `hypothesise()`
  end-to-end (generation call fires, embeddings never fire, "Nothing to cluster" never prints).

**Load-bearing invariants 1–8 in the review brief: all confirmed intact.** No merge of the
summaries/rows asymmetry, no vacuous aggregation admission, no network egress on the eu-stack
path, `yaml.safe_load`-only with `extra="forbid"` on the new `ExpectEustack` model, `sorted()`
determinism preserved, the `no_eustack_cases` vacuity guard is real (proven by
`test_zero_eustack_cases_forces_gate_fail_with_all_metrics_passing` and
`test_run_failed_only_eustack_case_also_gates_fail`), truth files are measured not guessed, and
no CSV path exists in the touched report code to bypass.

## Adjudication of the two flagged concerns

**A. `hang_detected` declared but never asserted — CONFIRMED, downgraded to WARNING (not
dismissed).** `grep -rn hang_detected src/ tests/ eval/` shows the field is read exactly once
outside `truth.py`/`runner.py`'s own docstring: `test_eustack_healthy_raises_no_graded_flag`
checks `truth.expect_eustack.hang_detected is False` against a hard-coded expectation for the
*healthy* case only. Nothing anywhere reads `hang_detected` on the two *positive* fixtures
(`eustack-hang-pool-warehouse`, `-mutated`) and compares it to anything. `_eustack_verdict`
explicitly documents why (D-19-17: no analyser judgement exists to compare it against) and the
positive case's own README states the same. This reasoning against inventing a `bool(flags)`
judgement is sound and I am not asking for one. But the gap the concern names is real: nothing
stops someone from writing `hang_detected: false` on `eustack-hang-pool-warehouse/truth.yaml`
today, and every test still passes (I did not need to mutate the file to see this — the field is
provably unreachable from any assertion on the positive cases by grep alone, and `_eustack_verdict`
never accesses `expect.hang_detected` at all per its own source). See **WR-01** below for the
recommended cheap fix, which is a self-consistency check on the frozen truth file, not a new
analyser judgement.

**B. Mutation twin's non-vacuity — CONFIRMED SOUND, no finding.** Read
`test_eustack_hang_twin_reproduces_identical_figures` in full. It asserts non-vacuity **first, and
in the right order**: raw-text inequality, then a disjoint `0x...` instruction-address set, then a
disjoint `TID \d+:` set — all three checked before any figure-equality assertion runs. This is not
merely present, it is ordered correctly (non-vacuity precedes the claim it protects) and strong
(three independent structural differences, not one weak check). I additionally reproduced the
underlying figures myself (see Summary) and confirmed both files really do differ while both
bundles really do reproduce identical `total_threads`/pool/dependency/flag figures. No finding.

## Warnings

### WR-01: `expect_eustack.hang_detected` can silently drift from its fixture with no test catching it

**File:** `src/sift/eval/truth.py:39` (field declaration), `src/sift/eval/runner.py:108-120`
(`_eustack_verdict`, which never reads `expect.hang_detected`), `eval/cases/eustack-hang-pool-warehouse/truth.yaml:27` and `eval/cases/eustack-hang-pool-warehouse-mutated/truth.yaml:19`

**Issue:** `ExpectEustack.hang_detected` is a mandatory field in a model whose entire purpose
(per this project's own `truth.yaml` header convention, repeated verbatim in all three new golden
cases) is "frozen ground truth... do not edit this file to make a run pass — a regression must
fail, not be silently accommodated." Every other field in `ExpectEustack` is checked by
`_eustack_verdict` and would fail the case if wrong. `hang_detected` is checked on exactly one of
the three cases (`eustack-healthy`, and only because a separate hand-written test happens to read
it), and never on the two positive cases. Grep confirms this:

```
$ grep -rn "hang_detected" src/sift/eval/runner.py
114:    ``hang_detected`` is deliberately NOT compared here: D-19-17 established
```

Concretely: nothing in the suite would fail if
`eval/cases/eustack-hang-pool-warehouse/truth.yaml`'s `hang_detected: true` were edited to
`hang_detected: false` today. That is exactly the "edited to make a run pass" failure mode this
file's own header disclaims, on a field that exists specifically so a human reading the fixture
knows what scenario it represents.

I agree with D-19-17 that inventing an analyser judgement (`bool(flags)` or a new threshold) to
satisfy this would be wrong and out of scope — the review brief's own framing is correct that this
must not be reintroduced. The fix below adds no such judgement; it only cross-checks the truth
file's own declared fields for self-consistency.

**Fix:** Add one cheap, analyser-free consistency test alongside
`test_only_the_healthy_case_is_marked_observed` (`tests/test_eval_cases.py`):

```python
def test_hang_detected_is_consistent_with_declared_saturation() -> None:
    """D-19-17 declarative-only field, still worth a self-consistency guard:
    hang_detected=True must correlate with at least one non-zero declared pool
    or dependency figure, and hang_detected=False (the healthy case) must not
    declare any. This reads only the frozen truth.yaml fields against each
    other -- no analyser call, no new judgement, so it does not reintroduce
    the bool(flags) verdict D-19-17 rejected."""
    for case_dir in _case_dirs():
        truth = load_truth(case_dir / "truth.yaml")
        expect = truth.expect_eustack
        if expect is None:
            continue
        saturated = any(expect.pools.values()) or any(expect.dependencies.values())
        assert expect.hang_detected == saturated, (
            f"{case_dir.name}: hang_detected={expect.hang_detected} but "
            f"declared saturation={saturated}"
        )
```

This would have caught a `hang_detected: false` typo on `eustack-hang-pool-warehouse` (declares
`warehouse: 25` busy) and a `hang_detected: true` typo on `eustack-healthy` (declares all pools
`0`) without adding any new analyser capability. If the team prefers not to carry this coupling,
the alternative is to drop `hang_detected` from `ExpectEustack` entirely and move its narrative
into `root_cause`/`README.md` prose only — but as shipped, a schema field that nothing checks is
worse than no field, because its presence implies it is verified.

## Info

### IN-01: Bare `assert` guards a documented invariant in production code (`-O` strips it)

**File:** `src/sift/eval/runner.py:171-173`

**Issue:**

```python
assert truth.expect_eustack is not None, (
    "_run_eustack_case is only ever dispatched when expect_eustack is set"
)
```

This is a bare `assert`, which is a no-op under `python -O`. In this specific case the risk is low
— the sole caller (`run_case`, line ~253) already checks `truth.expect_eustack is not None` before
dispatching, and if `-O` stripped the assert, `expect = truth.expect_eustack` would just carry a
type-checker-only `None` that is never actually `None` at runtime given the current call graph. It
is not a correctness bug today. Flagging per this project's own established review convention
(same asymmetry was called out in an earlier phase's review): prefer `raise AssertionError(...)`
or restructure so pyright doesn't need the narrowing assert at all (e.g. an `if
truth.expect_eustack is None: raise` guard, or accepting `expect: ExpectEustack` as a parameter
from the already-checked caller instead of re-deriving it inside `_run_eustack_case`).

**Fix:**

```python
if truth.expect_eustack is None:
    raise AssertionError(
        "_run_eustack_case is only ever dispatched when expect_eustack is set"
    )
expect = truth.expect_eustack
```

---

_Reviewed: 2026-07-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
