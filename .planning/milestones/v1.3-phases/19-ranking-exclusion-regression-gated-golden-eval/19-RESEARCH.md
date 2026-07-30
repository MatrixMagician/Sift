# Phase 19: Ranking Exclusion & Regression-Gated Golden Eval - Research

**Researched:** 2026-07-27
**Domain:** Store-level ranking exclusion seam (EUS-11) + eval-harness extension for a
deterministic, LLM-free golden metric (EUS-12), in an existing deterministic-core-then-LLM
incident triage pipeline (Sift v1.3)
**Confidence:** HIGH — every claim below is verified by direct reading of the shipped v1.3
source (`store.py`, `cli.py`, `hypothesise.py`, `eval/*.py`, `pipeline/eustack*.py`,
`rules/eustack_roles.toml`, `adapters/eustack.py`, and the full existing eu-stack test suite),
not inferred from names, docstrings, or the milestone-level ARCHITECTURE.md alone.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-19-01 — One-line seam change.** `EXCLUDED_FROM_RANKING: frozenset[str] =
  frozenset({"dssperfmon", "eustack"})` at `src/sift/store.py:335`. No new machinery: no
  per-adapter attribute, no config toggle, no opt-out parameter. Exclusion stays a property of
  the source kind, never of the case or caller (D-07). The composition-dependent third option
  ("exclude only when another ranked source is present") is rejected outright, not merely
  deprioritised.
- **D-19-02 — `sift analyze` must not dead-end on an eu-stack-only case.** `analyze` proceeds to
  `hypothesise()` when the case holds events of an excluded source, so deterministic facts still
  narrate and citations still resolve. A zero-cluster `hypothesise()` run must be a supported
  path (empty `ranked`, prompted_ids sourced from the fact block alone), not a crash or a
  degraded exit.
- **D-19-03 — Byte-identity proof reuses the PERF-03 criterion-4 pattern verbatim.** A two-case
  fixture pair (identical inputs, one with the eu-stack dump ingested and one without) whose
  cluster + salience output is asserted byte-identical. Assert on the derived cluster/salience
  render, never on the two `case.db` files.
- **D-19-04 — Citation path is unchanged and pinned.** `iter_event_rows` stays unfiltered; the
  asymmetry with `iter_event_summaries` is the invariant and must not be unified into a shared
  helper. A dedicated test (separate from D-19-03) proves every eu-stack event stays individually
  retrievable and citable after exclusion.
- **D-19-05 — Detection is asserted deterministically, with no LLM.** `truth.yaml` gains an
  optional block (working name `expect_eustack`, e.g. `{hang_detected: bool, flags: 0,
  provenance: authored|observed}`) scored directly from `analyse_eustack_bundle`. `Truth` is
  `extra="forbid"` — the new key must be added to the model, not smuggled in.
- **D-19-06 — Eu-stack cases run no LLM leg.** They declare `required_evidence: []` and
  `acceptable_keywords: []` so no LLM metric is scored vacuously on them.
- **D-19-07 — A new gated floor carries the metric.** `eval/thresholds.toml` gains
  `eustack_detection_rate = 1.00`, in the same higher-is-better lower-bound shape as the existing
  four floors (ADR 0010). Rejected: reusing `hypothesis_hit_at_k`, and pytest-only gating.
- **D-19-08 — Fixture layout.** `eval/cases/eustack-healthy/` holds the real-capture derivative
  (negative); `eval/cases/eustack-hang-*/` hold the synthetic positives. Separate case
  directories, not one combined multi-dump case.
- **D-19-09 — Scenario: pool saturation + external-wait concentration.** Every worker in one pool
  parked on the same warehouse-wait signature. Derived from the documented hang scenario, never
  from `src/sift/rules/eustack_roles.toml`'s own strings. Rejected as primary: lock convergence,
  and a `??`-heavy unresolvable-frame dump.
- **D-19-10 — Provenance is a machine-checked field, not prose.** A mandatory `provenance` field
  (`authored`/`observed`) plus a README per case directory, plus a test asserting the healthy case
  is the only one marked `observed`.
- **D-19-11 — Cosmetic-mutation twins ship as fixtures.** Renumbered TIDs, reordered thread
  blocks, differing instruction addresses; one mutated twin per positive case, asserted to yield
  an identical verdict.
- **D-19-12 — Fixtures stay signature-preserving and small**, following `tests/fixtures/eustack/`'s
  existing discipline.
- **D-19-13 — Zero eu-stack cases scored forces a gate failure.** Extends ADR 0010's "empty
  positive set is never a pass" rule to the new metric.
- **D-19-14 — A sensitivity test proves the gate actually bites.** Neuter the analyser (disable a
  rule) and assert `sift eval` exits non-zero — the pattern established by
  `test_mcm_denial_citation_validity_is_mcm_sensitive`.
- **D-19-15 — The negative case gates on zero flags literally.** `flags == 0` AND
  `hang_detected == false`, both asserted; a warn-level flag on the healthy capture is a failure.
- **D-19-16 — LLM-free subset documented.** Eu-stack cases are runnable without an inference
  endpoint; the suite as a whole still requires one for the other eight cases.

### Claude's Discretion

- Exact field names and nesting of the `expect_eustack` truth block (subject to `extra="forbid"`).
- Whether the zero-cluster `hypothesise()` path (D-19-02) is reached by relaxing the
  `cli.py:880` guard, by an earlier branch, or by another equivalent seam — provided `analyze`
  neither crashes nor prints a false "run `sift ingest` first" on an eu-stack-only case, and cases
  with **no** events at all still short-circuit as they do today.
- Number of synthetic positive cases beyond the one required scenario.
- Plan/task/wave breakdown, subject to EUS-11 landing before EUS-12's fixtures are authored.

### Deferred Ideas (OUT OF SCOPE)

- Additional hang scenarios beyond pool saturation + external-wait concentration (lock
  convergence, unresolvable-frame-heavy dumps) — taxonomy supports them, authoring more than the
  one required positive is discretionary within this phase.
- DET-01 / SEED-002 embedding vector reuse — Phase 20, functionally independent.
- The `generation.context` unset todo — remains open, not addressed here.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EUS-11 | Eu-stack thread events stop competing in dedup/embed/cluster/salience while remaining individually citable | §A (zero-cluster `hypothesise()` path), §B (byte-identity proof mechanics), §E (blast radius) below map the exact seam, the exact guard to change, and prove no shipped test currently depends on eu-stack participating in ranking |
| EUS-12 | A regression-gated golden eval covers both the real healthy capture (must not report a hang) and synthetic hang fixtures (must) | §C (eval harness call chain and the load-bearing `hypothesis_hit_at_k` exclusion pitfall), §D (fixture authorship, and the critical finding that the named scenario alone produces zero graded flags under the shipped analyser) below |
</phase_requirements>

## Summary

EUS-11 is materially **safer** than the CONTEXT/ARCHITECTURE research assumed: the zero-cluster
path through `hypothesise()` already works today with no code change — `cluster_and_label` already
short-circuits on zero template groups (returns `0`, no embed call), `rank_clusters` already
returns `[]` for zero candidates, and `PromptBudget.fit([])` already returns `[]`. The **only**
blocker is `src/sift/cli.py:880`'s `if not groups: print(...); return`, which fires before
`hypothesise()` is ever reached. Fixing that one guard — while preserving the zero-client-contact
guarantee for a genuinely empty case — is the entire D-19-02 change. Separately, **no shipped test
currently asserts eu-stack events participate in clustering/ranking at all**: `test_cluster.py` has
zero eu-stack references, and every hash-comparison test in `test_eustack_analyze.py` runs through
`_ingest` only (never `cluster_and_label`), so `rank_clusters` always sees an empty `clusters`
table regardless of what `EXCLUDED_FROM_RANKING` contains. The blast radius of D-19-01 against the
*existing* suite is therefore close to zero — this phase adds new tests, it does not repair broken
ones (with one exception: `test_suite_is_exactly_the_eight_cases`' case count/set, which must grow
when EUS-12's fixtures land).

EUS-12 has one finding that is load-bearing enough to restate here: **`analyse_saturation` only
grades three dimensions today — `unclassified_thread_pct`, `no_resolvable_frame_pct`, and
`lock_convergence_count`.** Pool occupancy (`PoolOccupancy`) and external-dependency-wait
(`DependencyWait`) rows carry **no threshold and no severity at all** (Pitfall 4 / EUSV2-03 is
explicitly deferred — "no graded saturation thresholds are invented"). A synthetic fixture that is
*purely* "pool saturation + external-wait concentration," as D-19-09 names it, therefore produces
**zero `SaturationFlag` entries** under the shipped analyser — meaning a naïve `hang_detected =
any(flags)` definition would score the CONTEXT's own chosen positive scenario as "no hang," failing
success criterion 3. The recommended resolution — consistent with D-19-09's own wording (only
*lock convergence as the primary/sole scenario* is rejected, not lock convergence as a
corroborating signal) and with "no new analysis mechanism" staying out of scope — is to author the
fixture so the same backlog that saturates the pool **also** converges on `__lll_lock_wait` beneath
a resolvable enclosing frame, crossing the existing `lock_convergence_count` threshold. This lets
`hang_detected` be defined with zero new analyser code, purely as "any `SaturationFlag` present."

**Primary recommendation:** Fix `cli.py:880`'s guard to check for zero *events* (not zero groups)
before short-circuiting; reuse the PERF-03 criterion-4 test shape verbatim for the byte-identity
proof, seeded from a case that already has a non-eu-stack ranked source; add a
`truth.expect_eustack` block plus an `eval/runner.py` branch that skips the LLM leg entirely for
eu-stack cases and must **exclude** those cases from the four existing keyword-metric aggregates
(not merely score them vacuously — `hypothesis_hit_at_k` returns `0.0`, not `1.0`, for an empty
`acceptable_keywords` list, which would otherwise silently break every future `sift eval` run); and
author the positive fixture so it trips the existing `lock_convergence_count` flag alongside its
pool-saturation narrative.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Ranking exclusion (`EXCLUDED_FROM_RANKING`) | Database / Storage (`store.py` SQL seam) | — | Exclusion is a property of the persisted `source` column, enforced in the one SQL query every ranking stage reads from |
| `analyze` zero-cluster guard | API / Backend (`cli.py` orchestration) | — | Pure control-flow decision over already-computed store state, no new data path |
| Deterministic eu-stack analysis (`analyse_eustack_bundle`) | API / Backend (`pipeline/eustack*.py`) | — | Pure function over `list[Event]`, no I/O, unaffected by the ranking seam (reads `query_events()`, always unfiltered) |
| Golden-eval scoring (`eval/runner.py`, `eval/metrics.py`) | API / Backend (eval harness, in-process) | — | Orchestrates existing pipeline functions and reads rows back; the eu-stack branch adds a second, LLM-free scoring path alongside the existing LLM-driven one |
| Gate / threshold comparison (`eval/thresholds.py`) | API / Backend | — | Pure comparison of `SuiteResult` aggregates against `eval/thresholds.toml` floors |
| Fixture authorship (new `.txt` dump files) | Database / Storage (test/eval fixtures on disk) | — | Static input data consumed by the adapter + analyser, no runtime component |

## Standard Stack

No new libraries. This phase is pure first-party Python over the existing stack (Pydantic, stdlib
`sqlite3`, `tomllib`/`yaml.safe_load` already in use, pytest). No `npm view`/`pip index
versions`-style verification is applicable — every symbol referenced below was confirmed by
reading the shipped source directly.

### Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages. All work is confined to
`src/sift/store.py`, `src/sift/cli.py`, `src/sift/eval/*.py`, `eval/thresholds.toml`, new
`eval/cases/eustack-*/` fixture directories, and their paired tests.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌───────────────────────────┐
                         │  sift ingest (existing)    │
                         │  adapters -> events table  │
                         └─────────────┬─────────────┘
                                       │
                       events (source="eustack" included)
                                       │
              ┌────────────────────────┼─────────────────────────┐
              │                        │                          │
              ▼                        ▼                          ▼
  iter_event_summaries()      iter_event_rows() /        query_events()
  (RANKING seam — filters      get_events_by_ids()        (UNFILTERED —
   EXCLUDED_FROM_RANKING,      (CITATION seam — never      always sees every
   NOW incl. "eustack")         filtered, D-04 pin)         source, incl. eustack)
              │                        │                          │
              ▼                        ▼                          ▼
   dedup -> template_groups    `sift show events` /       analyse_eustack_bundle()
   -> cluster_and_label()       evidence appendix /        (deterministic, no LLM)
   -> rank_clusters()           hypothesis citations              │
              │                        ▲                          ▼
              │                        │                  render_eustack_facts()
              │                        │                  -> (block_text, ids)
              └──────────► _assemble() in hypothesise.py ◄────────┘
                           unions cluster ids | mcm ids |
                           perfmon ids | eustack ids
                           -> prompted_ids (citable universe)
                                       │
                                       ▼
                        client.chat() -> citation gate -> Outcome
                                       │
                        (this is the ONLY step needing a live LLM;
                         zero clusters means an empty excerpt list,
                         NOT an empty prompt — the fact block still
                         narrates)

  EVAL-HARNESS BRANCH (new, D-19-06/16):

  sift eval --suite eval/cases  ──►  for each case_dir: load_truth()
                                              │
                       ┌──────────────────────┴───────────────────────┐
                       │ truth.expect_eustack is None                 │ truth.expect_eustack is not None
                       ▼                                              ▼
              run_case() (existing)                     NEW eu-stack branch (no client dereferenced):
              ingest -> cluster_and_label                ingest -> query_events() -> analyse_eustack_bundle()
              -> hypothesise() -> score                  -> compare (hang_detected, flags) to truth.expect_eustack
              4 keyword metrics                          -> CaseResult(is_eustack=True, eustack_case_pass=...)
                       │                                              │
                       └──────────────────────┬───────────────────────┘
                                               ▼
                              SuiteResult(cases) -> _positive()/_scored() EXCLUDE
                              is_eustack cases from the 4 existing keyword aggregates;
                              a NEW mean_eustack_detection_rate() aggregates ONLY
                              is_eustack cases
                                               │
                                               ▼
                        gate(suite, thresholds) -> 5th floor (eustack_detection_rate)
                        + a "no eu-stack cases scored" vacuity check mirroring
                        the existing no_positive_cases check -> exit 0/1
```

### Recommended Project Structure

No new top-level modules. Touched/added files:

```
src/sift/store.py                       # EXCLUDED_FROM_RANKING gains "eustack" (D-19-01)
src/sift/cli.py                         # analyze's zero-groups guard (D-19-02)
src/sift/eval/truth.py                  # Truth gains optional expect_eustack block (D-19-05)
src/sift/eval/metrics.py                # CaseResult/SuiteResult gain eu-stack fields + aggregate
src/sift/eval/thresholds.py             # METRIC_KEYS + gate() gain the 5th floor + vacuity check
src/sift/eval/report.py                 # render_text_table/render_json_table show the new column
src/sift/eval/runner.py                 # run_case dispatches to a new LLM-free eu-stack branch
eval/thresholds.toml                    # eustack_detection_rate = 1.00
eval/cases/eustack-healthy/             # NEW: negative golden case (real capture derivative)
eval/cases/eustack-hang-pool-warehouse/ # NEW: positive golden case (synthetic, authored)
eval/cases/eustack-hang-pool-warehouse-mutated/  # NEW: cosmetic-mutation twin (D-19-11)
tests/test_store.py                     # D-19-01/04 exclusion + citation-pin tests
tests/test_cli.py                       # D-19-03 byte-identity test (mirrors test_cluster_output_identical_with_and_without_perfmon)
tests/test_analyze.py                   # D-19-02 zero-cluster-but-narrates test
tests/test_eval_cases.py                # case-count/set update + D-19-14 sensitivity test
```

### Pattern 1: The `EXCLUDED_FROM_RANKING` seam is already exactly this shape

**What:** `src/sift/store.py:335` — `EXCLUDED_FROM_RANKING: frozenset[str] =
frozenset({"dssperfmon"})`. Exactly one production reader, `iter_event_summaries`
(`store.py:641-670`), which builds `WHERE source NOT IN (...)` from
`sorted(EXCLUDED_FROM_RANKING)` with every value `?`-bound. The near-identical
`iter_event_rows` (`store.py:672-703`) is deliberately unfiltered, with an explicit paired
docstring comment on both methods forbidding unification.
**When to use:** D-19-01 is a one-line addition to the frozenset, verbatim.
**Example (verified against the shipped file, `store.py:335`):**
```python
# Sources held out of every ranking stage (PERF-03/EUS-11). ...
EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon", "eustack"})
```
Line numbers confirmed current as of this research pass (`store.py:327-335` for the constant and
its comment block; `store.py:641-670` for `iter_event_summaries`; `store.py:672-703` for
`iter_event_rows`).

### Pattern 2: The zero-cluster `hypothesise()` path needs no new handling — only the CLI guard blocks it

**What:** Traced end to end from `cli.py:876-990` through `cluster.py:310-334`,
`salience.py:126-161`, and `llm/budget.py:49-63`:

1. `store.query_template_groups()` returns `[]` for an eu-stack-only case once EUS-11 lands
   (dedup already reads the filtered `iter_event_summaries` seam).
2. `cluster_and_label(store, client, cfg, label=...)` (`cluster.py:327-329`) already has
   `groups = store.query_template_groups(); if not groups: return 0` — **zero embed call, zero
   HTTP round-trip**, before this phase touches anything.
3. `hypothesise()`'s `rank_clusters(clusters, groups, ...)` (`hypothesise.py:456`) calls
   `salience.rank_clusters`, which itself does `if not candidates: return []`
   (`salience.py:160-161`) for an empty `clusters` list.
4. `_assemble()`'s `budget.fit(excerpts)` with `excerpts=[]` returns `[]` immediately
   (`llm/budget.py:55-56`, `if not excerpts: return []`) — no truncation logic runs.
5. `_ctx_tokens()` still calls `client.props()` (`hypothesise.py:254`), which already degrades to
   `{}` on any transport error (`client.py:516-531`, `try/except httpx.HTTPError: return {}`) —
   this is unconditional today, unaffected by cluster count.
6. `mcm_analysis`/`perfmon_block`/`eustack_block` are built from `store.query_events()`
   (`hypothesise.py:472-480`), which is **never** filtered by `EXCLUDED_FROM_RANKING` — so the
   eu-stack fact block renders normally regardless of ranking exclusion.

**Conclusion:** every downstream function in the zero-cluster path already tolerates `[]` inputs.
**The only code that must change is `cli.py:876-882`:**
```python
groups = store.query_template_groups()
if not groups:
    print("Nothing to cluster; run 'sift ingest' first")
    return
```
**Recommended smallest-diff fix** (Claude's discretion per CONTEXT, but this is the shape that
satisfies every stated constraint): distinguish "genuinely no events" (must still short-circuit,
per the existing `test_analyze_empty_case_reports_nothing_to_cluster` contract, which asserts BOTH
the message AND `calls == []` — the client must never be contacted for a truly empty case) from
"events exist but zero template groups" (must proceed):
```python
groups = store.query_template_groups()
if not groups and next(iter(store.iter_event_rows()), None) is None:
    print("Nothing to cluster; run 'sift ingest' first")
    return
```
`iter_event_rows()` is a streaming generator over the unfiltered events table
(`store.py:672-703`) — `next(iter(...), None)` reads at most one row, far cheaper than
`store.query_events()` (which decompresses every `raw` BLOB via `_decode_raw`). This preserves the
zero-client-contact guarantee for the empty case (no read of `iter_event_summaries` or any client
construction happens before this check) while letting an eu-stack-only case fall through to
`cluster_and_label` (returns 0, no HTTP call) and `hypothesise()` (which DOES contact the client
for `props()` + the generation `chat()` call — this is the expected, required behaviour per
D-19-02: the deterministic facts still narrate, and narration requires a live LLM to produce the
surrounding hypothesis text). An equally valid alternative already implied by CONTEXT is a
dedicated `store.has_events() -> bool` method (`SELECT EXISTS(SELECT 1 FROM events)`) — either is
acceptable; the `next(iter(...))` form needs zero new store surface.

**Only one existing test references the guard's message:**
`tests/test_analyze.py:180-191`, `test_analyze_empty_case_reports_nothing_to_cluster` — it seeds a
store with **zero events at all** (`CaseStore(...); store.close()`, no insert), asserts
`"Nothing to cluster" in result.output` AND `calls == []`. The recommended fix above keeps this
test green unmodified, because the new second condition (`next(iter(store.iter_event_rows()), None)
is None`) is `True` for a zero-event store — the short-circuit still fires, before either condition
could touch the client.

**New tests needed (none currently exist for this path):** an eu-stack-only case reaching
`hypothesise()` — `exit_code == 0`, the eu-stack fact block present in `sift show hypotheses`/the
persisted prompt, `"Clusters: 0"` printed, and `"chat"` present in the mocked calls list (the
generation leg DID run) while `"embeddings"` is absent (no exemplars to embed).

### Pattern 3: The byte-identity proof — exact shape and its non-vacuity trap

**What PERF-03's criterion-4 test actually does** (`tests/test_cli.py:1430-1451`,
`test_cluster_output_identical_with_and_without_perfmon`): builds case A from
`hartford_deny_slice.log` alone and case B from the same log plus the perfmon CSV, both via real
`sift new`/`sift ingest` CLI invocations (**no `analyze` step — ingest-only**), then compares
`sift show clusters` stdout byte-for-byte. The non-vacuity guard is `n_b > n_a` (case B has
strictly more events) **plus** an exact delta assertion (`n_b - n_a == _PERFMON_ROWS`). It
deliberately never runs `cluster_and_label`/embeddings — `show clusters` on an ingest-only case
renders through the `query_template_groups()` fallback path, which is cheaper and, per the
research note in that test, "the stronger assertion": `_exemplar_messages` derives directly from
template groups, so identical template groups make every downstream stage identical by
construction.

**The trap named in the research focus is real and specific to eu-stack, not perfmon:**
perfmon's case A (log-only) already has non-empty clusters from the DSSErrors log — the eu-stack
equivalent must be built the same way, or **both sides could show zero clusters and the
byte-identity assertion would pass vacuously.** Concretely: an eu-stack-only case A (empty) vs. an
eu-stack-only case B is the WRONG pair — once EUS-11 lands, `iter_event_summaries` excludes
`"eustack"`, so BOTH sides yield zero template groups and the comparison proves nothing.

**Correct fixture pair (mirrors PERF-03's shape exactly):**
- Case A: an existing dsserrors/MCM log fixture alone (e.g. `tests/fixtures/mcm/hartford_deny_slice.log`
  — already committed, already known to produce non-trivial template groups per the perfmon test).
- Case B: the same log fixture **plus** `tests/fixtures/eustack/threaddump.txt` (the existing
  signature-preserving derivative, already committed at `tests/fixtures/eustack/threaddump.txt`,
  6 events per the `test_cli_eustack.py` e2e scope table).

**Test shape:**
```python
def test_cluster_output_identical_with_and_without_eustack(tmp_path: Path) -> None:
    _ingest_case(tmp_path, "logonly", with_eustack=False)
    _ingest_case(tmp_path, "logplus", with_eustack=True)

    a = runner.invoke(app, ["show", "logonly", "clusters"])
    b = runner.invoke(app, ["show", "logplus", "clusters"])
    assert a.exit_code == 0 and b.exit_code == 0
    assert a.output == b.output, "eustack dump perturbed cluster output"

    # Non-vacuity, TWO guards (stronger than PERF-03's single count delta,
    # because the eu-stack trap is that BOTH sides could be trivially empty):
    assert a.output != ""  # case A already has non-empty cluster output
    n_a = len(_read_event_ids("logonly"))
    n_b = len(_read_event_ids("logplus"))
    assert n_b > n_a, f"eustack dump was not ingested: {n_a} vs {n_b} events"
    assert n_b - n_a == _EUSTACK_THREADDUMP_EVENT_COUNT  # exact delta, per PERF-03 precedent
```
The `assert a.output != ""` (or an equivalent explicit non-empty-cluster-table assertion) is the
crux line the research focus asked to "spell out": without it, a future regression that silently
excludes the log source too (or breaks ingest entirely) would still pass `a.output == b.output`
trivially. This mirrors PERF-03's own reasoning almost exactly but needed restating because eu-stack
uniquely risks a **both-sides-empty** vacuity failure mode that perfmon's log-bearing case A never
faced.

### Anti-Patterns to Avoid
- **Comparing `case.db` files directly for the byte-identity proof** — case B legitimately holds
  the eu-stack events; only the *derived* cluster/salience render is promised identical (explicit
  in D-19-03, and the shipped PERF-03 test's own docstring: "never on the two `case.db` files").
- **Unifying `iter_event_summaries`/`iter_event_rows` into a shared helper** — the asymmetry is
  the whole feature (D-19-04), and both methods already carry paired warning comments against this
  exact refactor.
- **Deriving synthetic hang fixtures from `eustack_roles.toml`'s pattern strings** — proves only
  that the code runs (Pitfall 5, PITFALLS.md), not that the classifier generalises.
- **Defining `hang_detected` by inventing a new graded threshold in `pipeline/eustack.py`** — out
  of scope ("no new analysis mechanism"); see Pattern 4 below for the reuse-only resolution.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| "Has this case ingested anything at all?" check | A new store-wide event-count column/cache | `next(iter(store.iter_event_rows()), None) is None` (or `store.has_events()` if a named method is preferred) | Streams one row from an existing cursor-based method; avoids a new migration and avoids `query_events()`'s full zstd decompression pass |
| Empty-positive-set vacuity guard for the eu-stack metric | A bespoke boolean flag threaded through `cli.py`'s `eval_` command | `GateResult`'s existing `no_positive_cases`-shaped pattern, added as a sibling field computed the same way (`not any(c.is_eustack and not c.run_failed for c in suite.cases)`) | `gate()` already has the exact "empty positive aggregate is not a pass" logic (ADR 0010); D-19-13 explicitly extends that rule rather than inventing a new one |
| Cosmetic-mutation twin generation | A test-time mutation function that rewrites TIDs/addresses at runtime | A second, hand-authored (or scripted-once, like `tests/fixtures/eustack/derive_reference_capture_derivative.py`) fixture file committed alongside the original | D-19-11 explicitly rejects mutating at test time — "a shipped twin is auditable and keeps the mutation itself under review" |

**Key insight:** every mechanism this phase needs — the exclusion seam, the vacuity guard, the
graded-flag signal, the CSV formula guard, the byte-identity test shape — already exists in the
codebase as a proven pattern from PERF-03/MCM-07/ADR-0010/ADR-0015/17-03's CSV work. The phase is
almost entirely "wire up an existing pattern a fourth time," and the research above exists
precisely to head off the one place that temptation is dangerous (§ Pattern 4 below, where the
"obvious" fix is to invent new analyser code).

## Pattern 4 (critical): There is currently no analyser signal for "pool saturation + external-wait concentration" alone

**What goes wrong if unaddressed:** `pipeline/eustack.py:733-840`'s `analyse_saturation()` builds
exactly three `SaturationFlag` entries — `unclassified_thread_pct`, `no_resolvable_frame_pct`, and
`lock_convergence_count` (`eustack.py:486-521` for the model, `733-840` for the three
`flags.append(...)` call sites). **`PoolOccupancy` (per-pool busy/idle split) and
`DependencyWait` (per-subsystem external-wait concentration) carry no `warn`/`critical` fields at
all** — `eustack.py:524-543` and `566-594` — this is Pitfall 4's own documented decision
("EUSV2-03 ... graded saturation thresholds ... explicitly deferred; flags here report measured
composition, not authored percentages"). Consequently, a fixture built to be *purely* "every
worker in one pool parked on the same warehouse-wait signature" (D-19-09's own wording) produces
`bundle.saturation.flags == ()` — **zero flags** — under the shipped analyser, no matter how
severe the underlying saturation looks in `PoolOccupancy`/`DependencyWait` rows. If the eval
harness defines `hang_detected` as "any `SaturationFlag` present" (the simplest, safest
definition — see below), the CONTEXT's own chosen positive scenario would score as "no hang," which
directly fails success criterion 3 ("Synthetic hang fixtures ... are detected").

**Recommended resolution (reuses only existing graded signals, adds zero new analyser code):**
author the positive fixture so the SAME backlog that saturates the pool **also** produces a
threshold-crossing `lock_convergence_count` flag. Concretely: alongside the warehouse-wait
majority (classified `blocked-on-external`/`warehouse` via the shipped
`CDSSQueryEngine::WaitUntilFinished` or `SharedMemoryImpl::WaitOnSemaphore` rules,
`eustack_roles.toml:147-163`), include a subset of threads (≥20, to cross the default `critical`
cut-point of `20.0`; ≥5 crosses `warn`) whose stack contains `__lll_lock_wait`
(`eustack_roles.toml:76-79`, the single `blocked-on-lock` rule) beneath a resolvable, `::`-qualified
enclosing frame (so `enclosing_application_frame` — `eustack.py:263-` — resolves a real
`LockSite.site` rather than `UNKNOWN_LOCK_SITE`). This is a realistic composite, not a contrivance:
a connection-pool backlog piling up on a shared internal lock while waiting on the warehouse is a
plausible single incident narrative, not two unrelated scenarios stapled together. It does **not**
contradict D-19-09 — that decision rejects lock convergence as the **primary/sole** scenario, not
as a secondary corroborating signal within the pool-saturation narrative.

With that fixture shape, `hang_detected` can be defined with zero new production code:
```python
def eustack_hang_detected(bundle: EustackBundle) -> bool:
    return bool(bundle.saturation.flags)  # any graded flag present, any severity
```
This also makes D-19-15's "both `flags == 0` and `hang_detected == false`" requirement for the
negative case trivially and non-redundantly true: `flags` is the literal `len(bundle.saturation.flags)`,
and `hang_detected` is the derived boolean over the same tuple — asserting both is defense-in-depth
against a future divergence between the count and the derived predicate, not two independent
signals today. **This is the single most consequential design decision left open by CONTEXT** (it
falls under "exact field names and nesting... at Claude's discretion," but the *definition* of
`hang_detected` is not discretionary in the sense that an uninformed choice silently breaks success
criterion 3) — flag it explicitly to the user/planner rather than deciding it silently.

**Alternative considered and NOT recommended:** defining `hang_detected` via a new eval-local
threshold read directly off `PoolOccupancy.occupancy`/`DependencyWait.thread_count` (bypassing
`SaturationFlag` entirely). This technically stays out of `pipeline/eustack.py` (arguably not "new
analysis mechanism" in the production sense), but it introduces an eval-only judgment threshold
with no config surface, no display-beside-threshold discipline, and no precedent anywhere else in
the codebase — it repeats exactly the "hardcoded threshold with no config knob" anti-pattern
Pitfall 4 already warns against, just relocated to the eval harness. The lock-convergence-reuse
approach above is the lazier, more consistent, more auditable choice.

## Common Pitfalls

### Pitfall 1: Including eu-stack cases in the existing four-metric aggregate silently breaks the gate

**What goes wrong:** `hypothesis_hit_at_k(hyps, acceptable_keywords, k)` (`eval/metrics.py:39-51`)
returns **`0.0`**, not a vacuous `1.0`, when `acceptable_keywords` is empty (`if not keywords:
return 0.0`) — unlike `retrieval_hit_rate` (`if not required_evidence: return 1.0`) and
`citation_validity_rate` (`if not hyps: return 1.0`). D-19-06 requires eu-stack cases to declare
`acceptable_keywords: []`. If an eu-stack `CaseResult` is naively included in
`SuiteResult._positive()` (`metrics.py:118-119`, currently `[c for c in self.cases if not
c.expect_no_incident and not c.run_failed]`), its `hypothesis_hit_at_k` contributes a literal `0.0`
to `mean_hypothesis_hit_at_k()`, dragging the suite mean below the `1.00` floor in
`eval/thresholds.toml` — **every** `sift eval` run fails the gate the moment an eu-stack case
exists, regardless of whether eu-stack detection itself is correct.
**Why it happens:** the four existing metrics were designed around "vacuous == pass" for an
absent-evidence positive case; `hypothesis_hit_at_k` is the one exception, and it is easy to miss
because the other three metrics' vacuous values all happen to be `1.0`.
**How to avoid:** give `CaseResult` an `is_eustack: bool = False` field (or equivalent) and update
BOTH `_positive()` and `_scored()` (`metrics.py:118-122`) to exclude `is_eustack` cases from all
four existing aggregates, symmetrically with how `expect_no_incident`/`run_failed` are already
excluded. Score eu-stack cases exclusively through the new `mean_eustack_detection_rate()`.
**Warning signs:** `sift eval`'s `hypothesis_hit_at_k` aggregate drops below `1.00` the moment an
`eustack-*` case directory is added, even though every other case's hypotheses are unchanged.

### Pitfall 2: `run_case` cannot currently be reached with `client=None` — a new branch is required, not a parameter default

**What goes wrong:** `eval/runner.py:run_case` unconditionally calls `_ingest` then loops
`_run_pipeline` (`cluster_and_label` + `hypothesise`, both requiring a live `client`) for every
case; `cli.py`'s `eval_` command constructs exactly one `InferenceClient` for the whole suite
before calling `run_case` per directory (`cli.py:1505-1530`). There is no existing code path where
`run_case` is reached with `client=None`, and threading an `Optional[InferenceClient]` through
`_run_pipeline`'s existing signature would require conditionals inside `cluster_and_label`/
`hypothesise` themselves — invasive, and those functions are shared with `sift analyze`'s own
production path.
**Why it happens:** it looks like a small parameter-nullability change, but the two functions it
would touch are the citation-gated anti-hallucination core (`hypothesise.py`) — not a safe place
to add a null-client branch.
**How to avoid:** add a **sibling function** (e.g. `_run_eustack_case`) in `eval/runner.py`,
dispatched from `run_case`'s top (after `truth = load_truth(...)`) when
`truth.expect_eustack is not None`. This sibling reuses `_ingest` (still needed to get events into
a `case.db`) but calls `analyse_eustack_bundle` directly — never touching `client.chat`/
`client.embed`. The CLI's single shared `client` construction stays unconditional and harmless
(constructing `InferenceClient` performs only a local SSRF-shape check on the configured URLs, no
network I/O — confirmed at `cli.py:896-910`'s try/except around construction, which only catches a
local `ValueError`) — this is exactly what makes D-19-16's "eu-stack cases are runnable without an
inference endpoint" true even though the CLI still builds one client for the whole suite.
**Warning signs:** a code review that tries to make `run_case` itself branch mid-function on
`truth.expect_eustack` rather than dispatching early — this risks a half-run pipeline state (e.g. a
partially ingested case whose repeats loop silently no-ops).

### Pitfall 3: `test_suite_is_exactly_the_eight_cases` will fail the moment new eu-stack cases are added — this is expected, not a regression

**What goes wrong (if not anticipated):** `tests/test_eval_cases.py:33-42,86-90` hardcodes
`_EXPECTED_CASES` as a set of exactly 8 names and asserts `len(dirs) == 8`. Adding
`eval/cases/eustack-healthy/` and `eval/cases/eustack-hang-*/` (D-19-08) will fail this test
immediately unless it is updated in the same change.
**Why it happens:** the suite-shape test is intentionally strict (catches accidental case
deletion/duplication) — it has no "at least N" escape hatch by design.
**How to avoid:** update `_EXPECTED_CASES` and the count assertion in the same commit/task that
adds the new case directories; treat the CI failure as a checklist item, not a discovered
regression.
**Warning signs:** none needed — this WILL fail predictably; the risk is only in mis-attributing
the failure as a bug during execution.

### Pitfall 4: The `EustackAdapter` sniff signature requires BOTH a `TID` header AND a frame line in the head — a truncated or malformed fixture silently fails to sniff, not just to classify

**What goes wrong:** `adapters/eustack.py:57-58`'s sniff regexes (`_SNIFF_TID_RE = r"^TID
\d+:"`, `_SNIFF_FRAME_RE = r"^#\d+\s+0x"`, both `re.MULTILINE`) both must match somewhere in the
sniffed head, or the file is never even offered to the eu-stack adapter — it may fall through to
`genericlog` instead, producing a completely different (and useless, for this phase's purposes)
event shape with no `source == "eustack"` tag at all, silently defeating the whole fixture's
purpose without any visible error.
**Why it happens:** a hand-authored fixture missing the leading `TID <n>:` line (e.g. if an author
pastes only frame lines) still "looks like" a thread dump to a human reader.
**How to avoid:** author every fixture using the shipped format exactly —
`TID <n>:` header lines immediately followed by `#<N>  0x<ADDR>  <symbol>` frame lines (see Code
Examples below for the verbatim shape from `tests/fixtures/eustack/threaddump.txt`) — and add a
coverage assertion (mirroring the shipped `threaddump.txt`'s own e2e test at
`test_cli_eustack.py:1254`, which pins event count + sniff confidence) for every new fixture.
**Warning signs:** an ingested eu-stack fixture produces events with `source != "eustack"`, or a
lower-than-expected coverage percentage in the ingest coverage meta.

## Code Examples

### The exact eu-stack native-dump format (verbatim shape, from the shipped fixture)

```text
-- sanitised eu-stack capture; addresses and symbols masked --
2026-07-18T09:15:30+00:00 eu-stack backtrace of process castorserver
PID 715821 - castorserver
TID 715821:
#0  0x00007f0000000001 clock_nanosleep@@GLIBC_2.17
#1  0x00007f0000000002 __nanosleep
#2  0x00007f0000000003 castor_worker_wait - libcastor.so worker.cpp:412
#3  0x00007f0000000004 castor_thread_main
#4  0x00007f0000000005 start_thread
TID 715822:
#0  0x00007f0000000010 pthread_cond_wait@@GLIBC_2.3.2
...
```
Source: `tests/fixtures/eustack/threaddump.txt`. Regex contract confirmed against
`adapters/eustack.py:44-58`: `_TID_RE = r"^TID (\d+):"`, `_FRAME_RE = r"^#(\d+)\s+0x([0-9A-Fa-f]+)\s+(.+)$"`,
optional leading ISO-8601 dump-time header line matched by `_TS_RE`. A thread block ends at the
next `TID` line or a safety cap (`MAX_EVENT_LINES = 256`, `MAX_EVENT_BYTES = 65536`,
`adapters/eustack.py:39-40`).

### The rules whose pattern strings realise the D-19-09 scenario (verified against `src/sift/rules/eustack_roles.toml`)

```toml
# Rule 6 (line 76-79) — the ONLY graded contention signal today:
[[rule]]
role = "blocked-on-lock"
subsystem = "lock"
match = "contains"
pattern = '__lll_lock_wait'

# Idle-pool comparison signature (rules 7-8, line 82-91):
[[rule]]
role = "idle-parked"
subsystem = "job-queue"
match = "contains"
pattern = 'MSIQTask::GetNextPreferredJob'

# Warehouse external-wait rules (16, 18 — line 147-163), BOTH aggregate to
# one DependencyWait row (subsystem="warehouse") per D-06:
[[rule]]
role = "blocked-on-external"
subsystem = "warehouse"
pattern = 'CDSSQueryEngine::WaitUntilFinished'

[[rule]]
role = "blocked-on-external"
subsystem = "warehouse"
pattern = 'SharedMemoryImpl::WaitOnSemaphore'
```
Rule ordering (D-01, rule-major first-match-wins) is stable and unaffected by this phase — no
rules-file edit is needed; the fixture is authored to match EXISTING rules, per D-19-09's
provenance discipline (derive frame content from the documented scenario, not the reverse).

### `gate()`'s existing "empty positive aggregate is not a pass" pattern (the exact code to mirror for D-19-13)

```python
# eval/thresholds.py:111-127, verbatim from the shipped source:
run_failed_cases = [c.name for c in suite.cases if c.run_failed]
false_positive_cases = [
    c.name
    for c in suite.cases
    if c.expect_no_incident
    and not c.run_failed
    and c.negative_case_pass is False
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
D-19-13's "zero eu-stack cases scored forces a gate failure" is a direct sibling: add
`no_eustack_cases = not any(c.is_eustack and not c.run_failed for c in suite.cases)` and fold it
into `passed` the same way. `run_failed_cases` already forces a fail for ANY failed case
(including a failed eu-stack case) with no further change needed — this answers the research
question "confirm run_failed already forces gate fail": **yes, unconditionally, for any case type,
today.**

## Runtime State Inventory

Not applicable — this is not a rename/refactor/migration phase. No stored data, live service
config, OS-registered state, or secrets are touched. The one schema-adjacent change (`Truth` model
gains an optional field) is additive and validated at load time via Pydantic, not a migration.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `hang_detected` should be defined as `bool(bundle.saturation.flags)`, with the fixture engineered to also cross `lock_convergence_count` | Pattern 4 | If the planner instead invents a new eval-local threshold over `PoolOccupancy`/`DependencyWait`, that's a viable alternative but repeats the "hardcoded threshold, no config knob" anti-pattern Pitfall 4 warns against; either way this decision must be made explicitly, not left implicit |
| A2 | `CaseResult` gains a single `is_eustack: bool` + `eustack_case_pass: bool \| None` pair (mirroring `negative_case_pass`'s existing shape) rather than a nested sub-result object | Pitfall 1 / Code Examples | Low risk — this is a naming/shape choice within Claude's discretion (CONTEXT explicitly reserves "exact field names" as discretionary); any shape that correctly excludes eu-stack cases from the 4 existing aggregates satisfies the requirement |
| A3 | The eu-stack byte-identity fixture pair should use `tests/fixtures/mcm/hartford_deny_slice.log` as case A's non-eustack ranked source | Pattern 3 | Low risk — any already-committed fixture that is KNOWN to produce non-empty template groups works equally; this specific file is recommended only because PERF-03's own test already proves it does |
| A4 | `next(iter(store.iter_event_rows()), None) is None` is an acceptable "has any events" check for the `cli.py:880` guard, in preference to a new `store.has_events()` method | Pattern 2 | Low risk — both are correct; the discretion is purely about whether to add new store surface area |

**If this table is empty:** N/A — see rows above. None of these are compliance/security-sensitive;
all are implementation-shape choices within CONTEXT's own stated discretion.

## Open Questions

1. **What exact `hang_detected` definition ships?**
   - What we know: the only currently-graded analyser signal is `SaturationFlag` (3 dimensions);
     `PoolOccupancy`/`DependencyWait` carry no threshold.
   - What's unclear: whether the planner accepts the "also trip `lock_convergence_count`" fixture
     design (Pattern 4) or wants a different resolution.
   - Recommendation: adopt Pattern 4's resolution — it requires zero new production code and stays
     inside "no new analysis mechanism." Surface this explicitly in the plan/discuss step if not
     already implicitly accepted by CONTEXT's silence on the point.

2. **Exact shape of the `expect_eustack` Pydantic sub-model.**
   - What we know: `Truth` is `extra="forbid"`; the working field names from CONTEXT are
     `hang_detected: bool`, `flags: int`, `provenance: Literal["authored", "observed"]`.
   - What's unclear: whether `expect_eustack` nests as its own `BaseModel` (recommended, for
     `extra="forbid"` at that level too) or as three top-level optional fields on `Truth`.
   - Recommendation: a nested model — `expect_eustack: ExpectEustack | None = None` — keeps the
     eight non-eustack `truth.yaml` files (which never set it) unaffected and keeps the new
     surface's own typo-protection independent of `Truth`'s.

## Environment Availability

Not applicable — this phase has no new external dependencies (no new tools, services, runtimes, or
package managers). `sift eval`'s existing dependency on a live inference endpoint for the eight
non-eustack cases is unchanged; the eu-stack cases specifically are designed to need none (D-19-16).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing, no version change) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (unchanged) |
| Quick run command | `uv run pytest tests/test_store.py tests/test_cli.py tests/test_analyze.py tests/test_eval_cases.py -x -q` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EUS-11 | `EXCLUDED_FROM_RANKING` gains `"eustack"`; ranking excludes it, citation path does not | unit | `uv run pytest tests/test_store.py -k eustack -x` | ❌ Wave 0 (new tests, D-19-01/04) |
| EUS-11 | Cluster/salience output byte-identical with/without an eu-stack dump present | integration (CLI) | `uv run pytest tests/test_cli.py -k eustack -x` | ❌ Wave 0 (D-19-03) |
| EUS-11 | `sift analyze` on an eu-stack-only case reaches `hypothesise()`, exits 0, narrates | integration (CLI) | `uv run pytest tests/test_analyze.py -k eustack -x` | ❌ Wave 0 (D-19-02) |
| EUS-12 | `truth.expect_eustack` loads via the schema-forbidding `Truth` model | unit | `uv run pytest tests/test_eval_cases.py -k every_truth_yaml_loads -x` | ✅ existing test, extend fixture set |
| EUS-12 | Healthy capture: `flags == 0` and `hang_detected == false` | eval golden case | `uv run sift eval --suite eval/cases` (case: `eustack-healthy`) | ❌ Wave 0 (new case dir) |
| EUS-12 | Synthetic hang fixture: detected, and detected under cosmetic mutation | eval golden case | `uv run sift eval --suite eval/cases` (cases: `eustack-hang-*`, `-mutated`) | ❌ Wave 0 (new case dirs) |
| EUS-12 | `sift eval` exits non-zero on eu-stack regression; empty eu-stack positive set is never a pass | unit + CLI | `uv run pytest tests/test_eval_cases.py -k eustack_sensitive -x` (D-19-14 pattern) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the scoped `-k` command for the file(s) touched.
- **Per wave merge:** `uv run pytest tests/test_store.py tests/test_cli.py tests/test_analyze.py tests/test_cluster.py tests/test_eustack_analyze.py tests/test_eval_cases.py`.
- **Phase gate:** full `uv run pytest` green (this phase edits shipped ranking/eval behaviour —
  same "full suite is the merge gate, not a subset" rule PERF-03's own plan stated) plus
  `uv run ruff check && uv run pyright` clean, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_store.py` — D-19-01 exclusion test + D-19-04 citation-pin test (new)
- [ ] `tests/test_cli.py` — D-19-03 byte-identity test, `_ingest_case(..., with_eustack=)` helper
      addition (new, mirrors the existing `with_csv=` perfmon helper)
- [ ] `tests/test_analyze.py` — D-19-02 zero-cluster-but-narrates test (new)
- [ ] `eval/cases/eustack-healthy/`, `eval/cases/eustack-hang-pool-warehouse/`,
      `eval/cases/eustack-hang-pool-warehouse-mutated/` — new golden case directories, each with
      `input/`, `truth.yaml`, `README.md` (new)
- [ ] `tests/test_eval_cases.py` — updated `_EXPECTED_CASES`/count (Pitfall 3), D-19-14 sensitivity
      test (new)
- [ ] Framework install: none — pytest/Pydantic/PyYAML/tomllib all already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | no | No auth surface touched |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A |
| V5 Input Validation | yes | `yaml.safe_load` + Pydantic `extra="forbid"` (existing, `eval/truth.py:36-44`) already covers the new `expect_eustack` key; new eu-stack fixture `.txt` files are parsed by the same adapter that already treats thread-dump text as untrusted (bounded via `MAX_EVENT_LINES`/`MAX_EVENT_BYTES`, `adapters/eustack.py:39-40`) |
| V6 Cryptography | no | N/A — no crypto touched |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| A typo'd or injected `expect_eustack` key in `truth.yaml` | Tampering | `Truth`'s `extra="forbid"` already fails loudly at load (unchanged mechanism, new field added to the model) |
| CSV formula injection via eu-stack symbol/frame text in exported CSVs | Tampering | Already mitigated in Phase 17 — `render/eustack_report.py` imports and reuses `_csv_safe` from `perfmon_report.py` (confirmed, `eustack_report.py:31`); this phase adds no new CSV writer |
| A malicious/malformed eu-stack fixture masquerading as a legitimate golden case | Spoofing | Golden case fixtures are committed, reviewed source — same trust level as every other `eval/cases/*/input/` file today; no new trust boundary |
| `EXCLUDED_FROM_RANKING`'s SQL `WHERE source NOT IN (...)` clause | Tampering | Unaffected by this phase — same `?`-bound, module-owned frozenset discipline PERF-03 already established (`store.py:659-668`); adding a second literal string introduces no new injection surface |

## Sources

### Primary (HIGH confidence — direct source reads this session)
- `src/sift/store.py:300-703` — `EXCLUDED_FROM_RANKING`, `iter_event_summaries`, `iter_event_rows`,
  `get_events_by_ids`, `query_events`
- `src/sift/cli.py:820-1000, 1427-1543` — `analyze` command body, `eval_` command body
- `src/sift/pipeline/hypothesise.py` (full file) — `_assemble`, `hypothesise`, fact-block splice
  mechanics, `_ctx_tokens`
- `src/sift/pipeline/cluster.py:310-334` — `cluster_and_label`'s zero-groups short-circuit
- `src/sift/pipeline/salience.py:126-161` — `rank_clusters`'s zero-candidates short-circuit
- `src/sift/llm/budget.py:49-63` — `PromptBudget.fit`'s zero-excerpts short-circuit
- `src/sift/llm/client.py:516-531` — `props()`'s degrade-to-`{}` behaviour
- `src/sift/eval/runner.py`, `truth.py`, `thresholds.py`, `metrics.py`, `report.py` (full files)
- `src/sift/pipeline/eustack.py:480-840` — `SaturationFlag`, `PoolOccupancy`, `LockSite`,
  `DependencyWait`, `SaturationAnalysis`, `analyse_saturation` (the three-flags finding)
- `src/sift/pipeline/eustack_progression.py` (full file) — `analyse_eustack_bundle`, `EustackBundle`
- `src/sift/adapters/eustack.py:1-120` — sniff regexes, `_TID_RE`/`_FRAME_RE`, safety caps
- `src/sift/rules/eustack_roles.toml` (full file) — rule order, warehouse/lock/idle-pool patterns
- `src/sift/render/eustack_report.py:1-45` — confirmed `_csv_safe` reuse from Phase 17
- `src/sift/config.py:120-184` — `EustackThresholdsConfig`, `EustackConfig` defaults
- `tests/test_cli.py:1348-1486` — PERF-03's shipped criterion-4/citation tests (the pattern to mirror)
- `tests/test_analyze.py:169-198` — the single existing test on the `cli.py:880` guard's message
- `tests/test_eustack_analyze.py` (full file) — confirmed no test populates the `clusters` table,
  so ranking exclusion is orthogonal to every existing byte-identity assertion there
- `tests/test_eval_cases.py:1-120` — `_EXPECTED_CASES`, the suite-shape test that must be updated
- `.planning/phases/19-.../19-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`,
  `.planning/STATE.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`,
  `.planning/milestones/v1.2-phases/12-.../12-04-PLAN.md` — all read in full this session

### Secondary (MEDIUM confidence)
- None — no web/documentation lookups were needed; this phase touches only first-party code
  already present in the repository.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: N/A — no new dependencies
- Architecture (zero-cluster path, byte-identity mechanics, eval dispatch): HIGH — every claim
  traced to a specific file:line in the shipped source, several confirmed by reading the actual
  short-circuit/guard code rather than inferring it from docstrings
- The `hang_detected`/graded-flags finding (Pattern 4): HIGH that the analyser currently has no
  graded signal for pool/dependency rows (directly read `analyse_saturation`'s full body); MEDIUM
  on the specific resolution recommended (lock-convergence reuse) — this is a design
  recommendation, not a verified fact, and is flagged as Open Question 1 accordingly
- Pitfalls (esp. `hypothesis_hit_at_k`'s vacuous-0.0 trap): HIGH — read the exact function bodies
  in `eval/metrics.py`

**Research date:** 2026-07-27
**Valid until:** 30 days (stable, first-party-only research; no external library version drift risk)
