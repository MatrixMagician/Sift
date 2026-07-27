# Phase 19: Ranking Exclusion & Regression-Gated Golden Eval - Pattern Map

**Mapped:** 2026-07-27
**Files analyzed:** 12 (7 touched, 5 new — plus 3 new eval case dirs, each with 3 sub-files)
**Analogs found:** 12 / 12 (RESEARCH.md already resolved every analog to file:line; this document
adds concrete excerpts)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/sift/store.py` (`EXCLUDED_FROM_RANKING`) | config/constant (SQL seam) | CRUD (filter) | same file, `dssperfmon` entry (PERF-03) | exact — literally the same frozenset, one more string |
| `src/sift/cli.py` (`analyze` guard, ~880) | controller (CLI command) | request-response | same function, same guard | exact — modify in place |
| `src/sift/eval/truth.py` (`Truth` model) | model (Pydantic, config-shaped) | CRUD (load/validate) | same file/class; sibling nested models `EustackConfig`/`McmThresholdsConfig` in `src/sift/config.py` | exact for `extra="forbid"` idiom; role-match for nesting style |
| `src/sift/eval/metrics.py` (`CaseResult`/`SuiteResult`) | model + aggregation service | batch/transform | same file, `expect_no_incident`/`run_failed` exclusion idiom | exact |
| `src/sift/eval/thresholds.py` (`gate()`, `METRIC_KEYS`) | service (pure comparison) | batch | same file, `no_positive_cases` pattern | exact |
| `src/sift/eval/report.py` | render/util | transform | existing per-metric column rendering (not yet read in full — locate the loop over `METRIC_KEYS`/`GateResult.metrics`) | role-match |
| `src/sift/eval/runner.py` (new `_run_eustack_case` sibling) | service (orchestrator) | event-driven / batch (no HTTP) | `run_case` in same file | role-match, new sibling function, not a rewrite |
| `eval/thresholds.toml` | config | — | existing 4 floors, same file | exact |
| `eval/cases/eustack-healthy/{truth.yaml,README.md,input/}` | fixture/config | file-I/O | `eval/cases/perfmon-denial/` (most recent case dir added) | exact — same 3-file shape |
| `eval/cases/eustack-hang-pool-warehouse/{...}` | fixture/config | file-I/O | `eval/cases/perfmon-denial/` + `tests/fixtures/eustack/threaddump.txt` for dump format | exact |
| `eval/cases/eustack-hang-pool-warehouse-mutated/{...}` | fixture/config | file-I/O | the above, mutated per D-19-11 | exact |
| `tests/test_store.py` (new eustack tests) | test | — | `test_iter_event_summaries_excludes_perfmon`, `test_show_events_includes_perfmon` | exact |
| `tests/test_cli.py` (byte-identity test) | test | — | `test_cluster_output_identical_with_and_without_perfmon` (lines 1430-1451) | exact |
| `tests/test_analyze.py` (zero-cluster-narrates test) | test | — | `test_analyze_empty_case_reports_nothing_to_cluster` (lines ~180-191) | exact (inverse case) |
| `tests/test_eval_cases.py` (`_EXPECTED_CASES`, sensitivity test) | test | — | `_EXPECTED_CASES`/count assert; `test_mcm_denial_citation_validity_is_mcm_sensitive` | exact |

## Pattern Assignments

### `src/sift/store.py` — `EXCLUDED_FROM_RANKING` (config/constant, CRUD-filter)

**Analog:** same file, current state (`store.py:326-335`)

**Exact current code:**
```python
# Sources held out of every ranking stage (PERF-03). Perfmon samples are
# periodic observations, not diagnostics: they carry no incident signal to
# dedup, cluster, salience or hypothesis excerpts, and thousands of near-
# identical rows would dominate template counts. They stay FULLY retrievable
# by identifier, so citation and `show events` are unaffected — see the
# paired comments on iter_event_summaries / iter_event_rows below.
# Owned here, never caller-supplied: exclusion is a property of the source
# kind, not of the caller (D-07).
EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon"})
```

**Pattern to copy (D-19-01):** widen the frozenset to `frozenset({"dssperfmon", "eustack"})` and
extend the comment to name both PERF-03 and EUS-11 as the two seams sharing this constant. No other
change — `iter_event_summaries` (`store.py:641-670`, builds `WHERE source NOT IN (...)` from
`sorted(EXCLUDED_FROM_RANKING)`, `?`-bound) and `iter_event_rows` (`store.py:672-703`, deliberately
unfiltered) both already key off this one frozenset with zero further edits required.

---

### `src/sift/cli.py` — `analyze`'s zero-groups guard (controller, request-response)

**Analog:** same function, current guard (`cli.py:876-882`)

**Exact current code:**
```python
# CLUS-01: zero template groups means ingest has not run (or produced
# nothing) — there is nothing to embed, so skip the client entirely and
# exit cleanly. groups > 0 always yields >= 1 cluster (auto-singleton).
groups = store.query_template_groups()
if not groups:
    print("Nothing to cluster; run 'sift ingest' first")
    return
```

**Only test currently pinning the message** (`tests/test_analyze.py`,
`test_analyze_empty_case_reports_nothing_to_cluster`): seeds a store with **zero events at all**
and asserts `"Nothing to cluster" in result.output` **and** `calls == []` — the client must never
be constructed/contacted for a genuinely empty case.

**Pattern to copy (D-19-02):** distinguish "no events at all" (must still short-circuit before any
client work) from "events exist, zero groups because everything is ranking-excluded" (must fall
through to `hypothesise()`):
```python
groups = store.query_template_groups()
if not groups and next(iter(store.iter_event_rows()), None) is None:
    print("Nothing to cluster; run 'sift ingest' first")
    return
```
`iter_event_rows()` is the cheap unfiltered streaming generator (`store.py:672-703`); `next(iter(...),
None)` reads at most one row — cheaper than `store.query_events()`, which decompresses every `raw`
zstd blob. This keeps the shipped empty-case test green unmodified while letting an eu-stack-only
case proceed into `cluster_and_label` (already returns `0` on zero groups, no HTTP) and
`hypothesise()` (already tolerates zero clusters at every downstream stage per RESEARCH.md Pattern
2 — no code changes needed there).

---

### `src/sift/eval/truth.py` — `Truth` model (model, CRUD/validate)

**Analog:** same file, current model (`eval/truth.py` full, ~44 lines)

**Exact current code:**
```python
class Truth(BaseModel):
    """A golden case's frozen ground truth (D-03/D-04). ..."""

    model_config = ConfigDict(extra="forbid")

    root_cause: str
    required_evidence: list[str] = []
    acceptable_keywords: list[str] = []
    expect_no_incident: bool = False
```

**Pattern to copy (D-19-05, Open Question 2 resolved as "nested model"):** add a nested
`ExpectEustack` sub-model with its own `extra="forbid"`, mirroring how `config.py` nests
`EustackConfig`/`McmThresholdsConfig` under the top-level `Config` model — keeps the eight
non-eustack `truth.yaml` files (which never set the field) unaffected, and keeps this new surface's
typo-protection independent of `Truth`'s own:
```python
class ExpectEustack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hang_detected: bool
    flags: int
    provenance: Literal["authored", "observed"]
    # + whatever measured-figure fields D-19-17 requires (named pool occupancy,
    #   named dependency wait thread count) — Claude's discretion on exact names.


class Truth(BaseModel):
    ...
    expect_eustack: ExpectEustack | None = None
```
`load_truth` itself needs **no change** — `yaml.safe_load` + `Truth.model_validate(data or {})`
already validates nested models recursively.

---

### `src/sift/eval/metrics.py` — `CaseResult`/`SuiteResult` (model + aggregation, batch)

**Analog:** same file, current `expect_no_incident`/`run_failed` exclusion idiom
(`eval/metrics.py:78-138`)

**Exact current code (the two aggregation gates every new field must join):**
```python
def _positive(self) -> list[CaseResult]:
    return [c for c in self.cases if not c.expect_no_incident and not c.run_failed]

def _scored(self) -> list[CaseResult]:
    return [c for c in self.cases if not c.run_failed]

def mean_retrieval_hit_rate(self) -> float:
    return self._mean([c.retrieval_hit_rate for c in self._positive()])

def mean_hypothesis_hit_at_k(self) -> float:
    return self._mean([c.hypothesis_hit_at_k for c in self._positive()])

def mean_citation_validity_rate(self) -> float:
    return self._mean([c.citation_validity_rate for c in self._scored()])

def mean_determinism_stability(self) -> float:
    return self._mean([c.determinism_stability for c in self._scored()])
```

**Load-bearing gotcha (Pitfall 1 from RESEARCH.md):**
```python
def hypothesis_hit_at_k(...) -> float:
    """1.0 if ANY of the top-k hypotheses' ... else 0.0."""
    keywords = [word.lower() for word in acceptable_keywords]
    if not keywords:
        return 0.0          # <-- NOT 1.0, unlike the other three metrics' vacuous case
    ...
```

**Pattern to copy (D-19-06/Pitfall 1):** add `is_eustack: bool = False` and
`eustack_case_pass: bool | None = None` to `CaseResult` (mirrors `negative_case_pass`'s existing
shape/type exactly — a per-case tri-state verdict field). Update **both** `_positive()` and
`_scored()` to add `and not c.is_eustack`, symmetrically with the existing two exclusions — do not
add a third, differently-shaped exclusion helper. Add a new `mean_eustack_detection_rate()` that
aggregates **only** `is_eustack` cases, in the same `self._mean([...])` shape as the four existing
methods.

---

### `src/sift/eval/thresholds.py` — `gate()` (service, batch comparison)

**Analog:** same file, `no_positive_cases` pattern (`eval/thresholds.py:111-127`, verbatim quoted
in RESEARCH.md)

**Exact current code:**
```python
METRIC_KEYS: tuple[str, ...] = (
    "retrieval_hit_rate",
    "hypothesis_hit_at_k",
    "citation_validity_rate",
    "determinism_stability",
)
...
run_failed_cases = [c.name for c in suite.cases if c.run_failed]
false_positive_cases = [
    c.name for c in suite.cases
    if c.expect_no_incident and not c.run_failed and c.negative_case_pass is False
]
no_positive_cases = not any(
    not c.expect_no_incident and not c.run_failed for c in suite.cases
)
passed = (
    all(m.passed for m in metrics)
    and not run_failed_cases
    and not false_positive_cases
    and not no_positive_cases
)
```

**Pattern to copy (D-19-07/D-19-13):**
1. Add `"eustack_detection_rate"` as a 5th entry in `METRIC_KEYS` (order = display order) — this
   automatically makes `load_thresholds` require the new float floor in `eval/thresholds.toml` and
   folds the 5th metric into the existing `values{}`/`MetricVerdict` loop with zero other changes.
2. Add a sibling vacuity flag, same shape as `no_positive_cases`:
   ```python
   no_eustack_cases = not any(
       c.is_eustack and not c.run_failed for c in suite.cases
   )
   ```
3. Fold `no_eustack_cases` into `passed` alongside the existing three `not ...` terms, and add it
   as a field on `GateResult` (plus its own key in `as_dict()`), mirroring `no_positive_cases`
   exactly.
`run_failed_cases` already fails the gate unconditionally for ANY case type today (confirmed by
RESEARCH.md) — no change needed there for a failed eu-stack case.

**Add to `eval/thresholds.toml`:** `eustack_detection_rate = 1.00`, same bare-float-per-line shape
as the existing four entries.

---

### `src/sift/eval/runner.py` — new `_run_eustack_case` sibling (service, event-driven/no-HTTP)

**Analog:** `run_case` in the same file (RESEARCH.md Pitfall 2 — do not thread `Optional[client]`
into `run_case`/`hypothesise`; add a dispatched sibling instead)

**Pattern to copy (D-19-06/D-19-16):** at the top of `run_case`, right after `truth = load_truth(...)`,
branch:
```python
truth = load_truth(case_dir / "truth.yaml")
if truth.expect_eustack is not None:
    return _run_eustack_case(case_dir, truth)
# ... existing client-driven path, unchanged ...
```
`_run_eustack_case` reuses `_ingest` (still needed to populate `case.db`) but calls
`analyse_eustack_bundle` directly on `store.query_events()` — **never** touches
`client.chat`/`client.embed`. It compares the bundle's measured figures (D-19-17: exact figures,
not `bool(flags)`) against `truth.expect_eustack`, and returns a `CaseResult(is_eustack=True,
eustack_case_pass=..., name=..., run_failed=...)` — leaving all four keyword-metric fields at
whatever harmless default `CaseResult` already uses (they are excluded from aggregation by the
`is_eustack` guard added to `_positive()`/`_scored()` above, so their exact default value is inert,
but `0.0` is the honest/consistent choice — do not fabricate a `1.0`).

The CLI's single shared `InferenceClient` construction for the whole suite (`cli.py:1505-1530`
area) stays unconditional — it performs only a local SSRF-shape URL check, no network I/O — so
`_run_eustack_case` simply never uses the `client` parameter it's handed (or is not handed one at
all, if the dispatch happens before the client is passed down).

---

### `eval/cases/eustack-healthy/` and `eval/cases/eustack-hang-*/` (fixture/config, file-I/O)

**Analog:** `eval/cases/perfmon-denial/` — 3-file shape (`truth.yaml`, `README.md`, `input/`), the
most recently added golden case directory.

**Dump format to copy verbatim (from `tests/fixtures/eustack/threaddump.txt`, confirmed against
`adapters/eustack.py:44-58`):**
```text
-- sanitised eu-stack capture; addresses and symbols masked --
2026-07-18T09:15:30+00:00 eu-stack backtrace of process castorserver
PID 715821 - castorserver
TID 715821:
#0  0x00007f0000000001 clock_nanosleep@@GLIBC_2.17
#1  0x00007f0000000002 __nanosleep
...
```
Sniff contract: `_SNIFF_TID_RE = r"^TID \d+:"` and `_SNIFF_FRAME_RE = r"^#\d+\s+0x"` (both
`re.MULTILINE`) must BOTH match in the sniffed head, or the file silently falls through to
`genericlog` (RESEARCH.md Pitfall 4) — author every fixture with the `TID <n>:` header line
immediately followed by `#<N>  0x<ADDR>  <symbol>` frame lines, never frame-lines-only.

**Rules to target (verified against `src/sift/rules/eustack_roles.toml`, D-19-09 + Pattern 4
resolution — pool saturation + external-wait concentration, PLUS a lock-convergence corroborating
signal so `analyse_saturation` actually raises a graded flag):**
```toml
[[rule]]  # line 76-79 — the ONLY graded contention signal today
role = "blocked-on-lock"
subsystem = "lock"
pattern = '__lll_lock_wait'

[[rule]]  # line 147-163 — both aggregate into one DependencyWait row, subsystem="warehouse"
role = "blocked-on-external"
subsystem = "warehouse"
pattern = 'CDSSQueryEngine::WaitUntilFinished'  # or 'SharedMemoryImpl::WaitOnSemaphore'
```
**D-19-17 constraint on the positive truth block:** grade against the exact figures
`analyse_eustack_bundle` reproduces (a named pool's occupancy row, a named dependency's wait
thread count) — `PoolOccupancy`/`DependencyWait` carry no threshold/severity at all
(`eustack.py:524-543`, `566-594`), so the positive-case assertion is a **figure-comparison test**,
not a flag-presence test. No shipped test in `tests/test_eustack_progression.py` currently asserts
on `PoolOccupancy`/`DependencyWait` field values directly (only `bundle.progression.*` and
`bundle.analysis.total_threads`, e.g. `assert bundle.analysis.total_threads == 17` at line 265) —
that `assert bundle.<field> == <exact value>` shape (pinned int/str against a fixture) is the
closest existing analog for the new figure-pinning assertions this phase needs; no dedicated
`PoolOccupancy`/`DependencyWait` value-pinning test exists yet to copy verbatim, so author the new
one directly against `analyse_eustack_bundle`'s return shape following that same "assert exact
field value" idiom.

**Cosmetic-mutation twin (D-19-11):** a second, hand-authored fixture file (renumbered TIDs,
reordered thread blocks, differing addresses) committed alongside the original — never generated
at test time. Assert it reproduces the **same measured figures**, not merely "still raises a flag."

---

## Shared Patterns

### The `EXCLUDED_FROM_RANKING` seam
**Source:** `src/sift/store.py:326-335`, `641-670`, `672-703`
**Apply to:** `store.py` only — the one-line frozenset change; `iter_event_summaries` and
`iter_event_rows` need zero edits, their paired "do not unify" docstring comments stay authoritative
(D-19-04).

### "Empty positive/scored set is not a pass" vacuity gating
**Source:** `src/sift/eval/thresholds.py:111-127` (`no_positive_cases`)
**Apply to:** the new `no_eustack_cases` flag in `gate()` — same boolean-any() shape, same fold into
`passed`, same new field on `GateResult`/`as_dict()`.

### Golden-case aggregate exclusion (`_positive()`/`_scored()`)
**Source:** `src/sift/eval/metrics.py:118-122`
**Apply to:** `CaseResult.is_eustack` must be added to both filters symmetrically with the existing
`expect_no_incident`/`run_failed` exclusions — this is the single fix for RESEARCH.md Pitfall 1
(`hypothesis_hit_at_k` returning `0.0`, not a vacuous `1.0`, for empty `acceptable_keywords`).

### Byte-identity / non-vacuity proof shape
**Source:** `tests/test_cli.py:1430-1451`, `test_cluster_output_identical_with_and_without_perfmon`
**Apply to:** the new `test_cluster_output_identical_with_and_without_eustack` — same
`_ingest_case(..., with_X=)` helper shape, same "assert derived `show clusters` output equal, never
compare `case.db` files," same non-vacuity double-guard (`n_b > n_a` exact delta assertion). Eu-stack
needs ONE extra guard beyond perfmon's precedent: `assert a.output != ""` — because (unlike
perfmon's case A, which already has a non-eu-stack ranked log source) both sides of an eu-stack-only
comparison would otherwise trivially both be empty and pass vacuously.

### Sensitivity test proving a gate genuinely bites
**Source:** `tests/test_eval_cases.py`, `test_mcm_denial_citation_validity_is_mcm_sensitive`
(~line 238)
**Apply to:** D-19-14's new eu-stack sensitivity test — neuter the analyser (e.g. monkeypatch a rule
match to no-op, or strip a `SaturationFlag` append) and assert `sift eval` now exits non-zero /
`eustack_case_pass` flips to `False`, proving the metric is not vacuously green.

### Suite-shape hard-count test
**Source:** `tests/test_eval_cases.py`, `_EXPECTED_CASES` + `len(dirs) == 8` assertion
**Apply to:** update the hardcoded set/count in the SAME commit that adds the 3 new
`eval/cases/eustack-*/` directories (RESEARCH.md Pitfall 3) — this WILL fail predictably until
updated; not a discovered regression.

## No Analog Found

None — every file in scope has a direct, verified analog already shipped in the codebase (PERF-03
for the exclusion seam and byte-identity proof, MCM's sensitivity test for the gate-bites proof,
`config.py`'s nested-model idiom for `Truth`'s new sub-model, and the existing four-metric
aggregation machinery for the fifth metric). This phase is "wire up an existing pattern a fourth
time" per RESEARCH.md's own summary — the one place with no direct precedent
(`_run_eustack_case` as a client-free sibling to `run_case`) is still a role-match dispatch shape,
not a from-scratch design.

## Metadata

**Analog search scope:** `src/sift/store.py`, `src/sift/cli.py`, `src/sift/eval/*.py`,
`eval/thresholds.toml`, `eval/cases/perfmon-denial/`, `tests/test_cli.py`, `tests/test_analyze.py`,
`tests/test_eval_cases.py`, `tests/test_eustack_progression.py`, `src/sift/rules/eustack_roles.toml`,
`tests/fixtures/eustack/threaddump.txt`, `src/sift/adapters/eustack.py`
**Files scanned:** 14 read directly this session (all excerpts above verified against live source,
not RESEARCH.md's quotes alone, except where RESEARCH.md's own quoted line ranges were already
verbatim-confirmed)
**Pattern extraction date:** 2026-07-27
