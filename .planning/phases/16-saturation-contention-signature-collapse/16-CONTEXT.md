# Phase 16: Saturation, Contention & Signature Collapse - Context

**Gathered:** 2026-07-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Four model-free groupings over the `SignatureGroup` records Phase 15 already
produces, plus graded flags — delivering EUS-03 (per-pool occupancy), EUS-04
(ownership-blind lock convergence), EUS-05 (external-wait concentration split by
dependency) and EUS-06 (ranked signature collapse).

**Library-only.** No CLI command and no rendering — `sift eustack` and the
Markdown/CSV report land in Phase 17. Phase 16's deliverable is a new analysis
model plus fixture tests.

**Already delivered by Phase 15, not rebuilt here:** EUS-06 is substantially
satisfied already — `EustackAnalysis.signatures` is the distinct-signature
collapse, sorted thread-count descending with ties broken ascending on the
frames tuple, each `SignatureGroup` carrying `role`, `subsystem`, `pattern`,
`frame_index` and `reason`. Phase 16 consumes that tuple; it does not
re-derive it.

**Permanent non-goal (ADR 0015):** deadlock detection. eu-stack carries no
monitor-ownership edges, so a wait-for graph cannot be built at all. Every lock
finding is ownership-blind and the word "deadlock" must never appear in any
output.

</domain>

<decisions>
## Implementation Decisions

### Per-pool occupancy (EUS-03)

- **D-01:** A "pool" is the rule's `subsystem` string. Occupancy for a pool is
  `1 - (idle-parked threads in that subsystem / all threads in that subsystem)`,
  computed by grouping `EustackAnalysis.signatures` on `subsystem`. No new data
  and no new vocabulary — `subsystem` was made a *required* field in Phase 15
  (D-12/ADR 0015) precisely for this grouping.
  - Rejected: a `pool = true` marker in the TOML (costs a schema change plus
    re-validation of all 24 rules); signature-prefix clustering (a heuristic
    with a tuning knob, contradicting Phase 15's deliberate choice of
    hand-curation over inference).
  - Accepted consequence: `compute`, `lock` and `cube-generation` are
    subsystems too and will carry an occupancy figure that means little in
    isolation. This is reported uniformly rather than special-cased — the
    planner must NOT introduce a hidden allowlist of "real" pools.
  - Saturation is strictly **per-pool**, never process-wide. This is why the
    reference capture's 1,715 threads (44%) in one `MSIQTask::GetNextPreferredJob`
    frame must read as an idle pool, not as a saturated server.

- **D-02:** `unclassified` threads have `subsystem = None`. They are counted and
  reported as their own row, never silently folded into any pool and never
  dropped from the denominator of a pool they don't belong to.

### Lock convergence (EUS-04)

- **D-03:** A lock "site" is the **enclosing application frame**, not the leaf.
  The shipped rule matches `__lll_lock_wait` (a `contains` match on a glibc
  leaf), so `SignatureGroup.frame_index` points at glibc — the site must be
  found by walking *up* from that index.

- **D-04 (AMENDED 2026-07-25 after research — see note below):** The enclosing
  application frame is the first resolvable frame above `frame_index` whose
  normalised symbol contains `::` **and does not begin with a third-party
  runtime namespace**. "Above" means **increasing** frame index — `iter_frames()`
  yields `#1`, `#2`, `#3` … from leaf toward thread entry point, so the walk is
  `frame_index + 1, frame_index + 2, …`.

  The runtime-namespace denylist is exactly: `std::`, `boost::`, `__gnu_cxx::`,
  `abi::`. The first two are evidence-backed; the latter two are defensive
  entries for the same libstdc++/libgcc family.
  — **Reversibility:** reversible — the walk is one helper function over an
  existing frames tuple.

  **Why amended:** the original decision was "first `::`-qualified frame", on
  the reasoning that MicroStrategy is C++-namespaced and glibc is unqualified C.
  That reasoning holds for glibc but not for the C++ runtime. Verified in
  `tests/fixtures/eustack/reference_capture_derivative.txt`: `#1
  pthread_cond_wait@@GLIBC_2.3.2` is followed directly by `#2
  boost::asio::detail::scheduler::do_run_one(...)`, and elsewhere by `#2
  std::condition_variable::wait(...)`. An unfiltered `::` test would report
  `boost::asio::detail::scheduler::do_run_one` as the lock site on real data.

  **Why a denylist and not an allowlist:** counted over the reference capture,
  ~110 distinct top-level namespaces appear and exactly two are third-party
  (`std::` 14 frames, `boost::` 10). Every other one — `MSynch::` (155),
  `CDSSQueryEngine::` (74), `MSIThread::` (61), `MSIThreadPoolTask::` (47),
  `MCE::`, `MDb::`, `DFC*::`, `CDSS*::` … — is MicroStrategy. A denylist is two
  entries; an allowlist would be 110 and would grow with every build.
  - Still rejected: a full runtime-*prefix* denylist (`__`, `pthread_`, …) —
    unnecessary, because the `::` test already eliminates every unqualified C
    symbol; and `frame_index + 1`, which is wrong whenever more than one runtime
    frame sits between the futex wait and our code (the normal case).
  - Edge cases the planner must handle explicitly:
    1. **No qualifying frame exists above the leaf** — reported as
       unknown-but-counted, never dropped, never attributed to the leaf.
    2. **Unresolvable (`??`/bare-address) frames** — skipped and walked past,
       not treated as a stopping point (`_is_resolvable()` is the existing test).
    3. **A template argument list containing `::`** (e.g.
       `std::thread::_State_impl<std::tuple<MBase::ThreadedRepeater...>>`) —
       the denylist test must be applied to the symbol's **leading** namespace,
       not "contains `std::` anywhere", or a genuine `MBase::` frame nested in a
       template argument would be misjudged. Match on prefix, never substring.
    4. **The leaf is the last frame** — no frames above it; falls to case 1.
    5. **Multiple `__lll_lock_wait` frames in one stack** — the walk starts from
       the rule's reported `frame_index` (the matched one), not from a re-scan.

- **D-05:** Every lock output is labelled ownership-blind at the point of
  reporting, and the site is reported with its thread count. The output
  vocabulary must never contain "deadlock", "owner", or "holder".

### External-wait concentration (EUS-05)

- **D-06:** The dependency axis is the `subsystem` of `blocked-on-external`
  threads, taken verbatim (`warehouse`, `http`, `ipc`). No mapping layer and no
  second vocabulary to keep in sync.
  - Accepted consequence, stated so it is not a surprise later: the TOML curator
    owns the report's dependency axis. Adding a rule with a new `subsystem`
    silently adds a report row. That coupling is deliberate — it is the same
    single-source-of-truth property ADR 0015 chose.
  - Rejected: a `subsystem -> dependency` table in Python (a second edit site
    per rule, re-opening the coupling ADR 0015 closed); a third `dependency`
    field in the TOML (schema migration across 24 rules for precision not yet
    needed).
  - Target figures on the reference capture: 79 warehouse waits
    (`CDSSQueryEngine::WaitUntilFinished`) and 78 HTTP waits (`curl_multi_poll`)
    must be **separately** visible, never merged into one blocked total.

### Graded flags (Success Criterion 5)

- **D-07:** Flag only quantities with a non-arbitrary zero point:
  1. unclassified thread share (rules drift)
  2. no-resolvable-frame share (missing symbols)
  3. lock convergence — thread count at a single site above a configured count

  **No per-pool occupancy flag ships in this phase.** EUSV2-03 deliberately
  deferred graded saturation percentages because no authoritative source exists
  for "N% busy = warning", and a wrong default is worse than no flag. The
  planner must not invent one.
  — **Reversibility:** reversible — adding an occupancy flag later is additive;
  removing a shipped wrong threshold is not.

  **Denominators (settled 2026-07-25 after research — both flags key on
  THREADS, not signatures):** the reference capture's unclassified share is
  1.33% thread-weighted (52 / 3,902) but 43.01% signature-weighted — the two
  differ by more than an order of magnitude, so the choice is load-bearing, not
  cosmetic. Both ratio flags use the thread-weighted denominator (share of all
  threads), because a long tail of one-thread signatures is a curation backlog,
  not an operational signal, and D-09 requires zero flags on a capture that is
  operationally healthy. The signature-weighted figure is still *reported* as a
  raw figure (Phase 15 already emits the full uncapped unclassified list per
  D-15); it simply does not drive a flag.

- **D-08 (AMENDED 2026-07-25 after research):** Flags follow the shipped MCM-03
  pattern — `severity` in info/warn/critical, graded by the two-cut-point
  `_grade()` helper in `src/sift/pipeline/mcm.py`. Every flag prints its raw
  computed value beside the configured threshold. Thresholds are config keys
  under `[eustack]` in `SiftConfig` (extending the existing `EustackConfig`,
  which currently holds only `rules_path`).

  **Amendment — `DiagnosticFlag` cannot carry the lock-convergence count.** Its
  docstring states `value_pct` is "ALWAYS a ratio `part / whole * 100` — never
  an absolute", which is a milestone-locked machine-independence invariant. Two
  of D-07's three flags are true ratios and fit; the lock-convergence flag is a
  raw thread count and does not. `perfmon.py` hit this same mismatch and
  resolved it by minting `PerfmonHazard` rather than bending `DiagnosticFlag` —
  follow that precedent: reuse `_grade()` verbatim, and mint one sibling record
  type for the count flag. Do NOT widen `DiagnosticFlag`'s contract.

  `_grade()` is private to `mcm.py`. The planner decides between promoting it to
  a shared home and importing it as-is; either is acceptable provided `mcm.py`'s
  existing tests stay green and the helper is not duplicated.

- **D-09:** The healthy reference capture must raise **zero** flags. This is a
  verification gate on the chosen defaults, not an aspiration — if a default
  fires on the healthy capture, the default is wrong.

### Data model & validation

- **D-10:** Phase 16's figures live in a **new** frozen Pydantic model
  (working name `SaturationAnalysis`) that consumes `EustackAnalysis`.
  `EustackAnalysis` stays frozen and unchanged.
  — **Reversibility:** costly — `EustackAnalysis` is `frozen=True`,
  `extra="forbid"` and pinned by Phase 15's shipped tests; merging the two
  models later would churn those tests and blur "classification" with
  "analysis". Phase 17 renders both objects.

- **D-11:** EUS-04 is validated by a **hand-authored synthetic fixture** with N
  threads deliberately converging on one `__lll_lock_wait` site. The healthy
  reference capture matches the lock rule **zero** times (by design — see the
  Rule 6 comment in `eustack_roles.toml`), so no real capture can exercise this
  path. The fixture must be clearly labelled synthetic in its own provenance
  header — it is NOT a redacted real capture, and must not be mistaken for one
  in the way `tests/fixtures/eustack/` derivatives are.

- **D-12:** All figures are computed model-free. No LLM involvement anywhere in
  this phase — the deterministic-core-vs-LLM boundary holds (figures COMPUTED,
  the model only narrates, and narration is Phase 18's problem).

### Claude's Discretion

- Exact model/field names (`SaturationAnalysis`, `PoolOccupancy`, `LockSite`,
  `DependencyWait`) and the module they live in — the established precedent is
  executable code in `src/sift/pipeline/eustack.py` mirroring `mcm.py`/`perfmon.py`.
- Whether the three flag families share one `DiagnosticFlag` list or separate
  fields.
- Default threshold values, subject to D-09 (zero flags on the healthy capture).
- Plan/task decomposition and wave structure.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Governing decisions

- `docs/decisions/0015-eustack-thread-role-taxonomy.md` — the taxonomy design:
  five roles, required `subsystem`, rule-major file-order precedence, why
  deadlock detection is a permanent non-goal, and why `__lll_lock_wait` is the
  one sound single-leaf contention signal.
- `docs/decisions/0013-dsserrors-qualified-mcm-sniff.md` — the qualified-name
  anchoring precedent that D-04's `::` test follows.
- `.planning/phases/15-thread-role-taxonomy-rules-file/15-CONTEXT.md` — D-01
  (precedence), D-04 (pattern text not row index), D-05 (normalisation),
  D-07 (matched-no-rule vs no-resolvable-frame), D-12 (rule roles exclude
  `unclassified`), D-15 (unclassified never capped).

### Phase inputs

- `.planning/ROADMAP.md` § "Phase 16: Saturation, Contention & Signature
  Collapse" — goal, the five success criteria with their reference-capture
  figures, and the pattern note deferring EUSV2-03.
- `.planning/REQUIREMENTS.md` — EUS-03, EUS-04, EUS-05, EUS-06.

### Code to read before planning

- `src/sift/pipeline/eustack.py` — `Role`, `RuleRole`, `Reason`, `Rule`,
  `Classification`, `SignatureGroup`, `EustackAnalysis`, `normalise()`,
  `signature_of()`, `classify_signature()`, `analyse_eustack()`.
- `src/sift/rules/eustack_roles.toml` — the 24 shipped rules and their
  `subsystem` values; Rule 6 is the only `blocked-on-lock` rule.
- `src/sift/pipeline/mcm.py` — `DiagnosticFlag` (~line 221) and `_grade()`
  (~line 609): the graded-flag pattern D-08 reuses.
- `src/sift/config.py` — `EustackConfig` (~line 124) and `McmConfig` for the
  nested-key shape thresholds must follow.
- `src/sift/adapters/eustack.py` — `iter_frames()` (the shared frame splitter)
  and the `TID <n>:` header handling.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `EustackAnalysis.signatures` — already sorted, already classified, already
  carries `subsystem` and `thread_count`. Every Phase 16 grouping is a pass over
  this tuple. Classification is memoised per distinct signature and fanned out
  by thread count; Phase 16 must preserve that property and never classify
  per-thread.
- `mcm.py::_grade()` and `DiagnosticFlag` — the info/warn/critical grading
  helper and flag record, already shipped and tested.
- `eustack.py::normalise()` — canonical symbol form; the `::` test in D-04 runs
  against normalised symbols (version suffixes and `- <lib> <src>:<line>` tails
  already stripped, template argument lists retained).
- `eustack.py::_is_resolvable()` — the `??`/bare-address test; the frame walk in
  D-04 must skip unresolvable frames rather than stopping at them.

### Established Patterns

- Frozen Pydantic models with `extra="forbid"` throughout the eu-stack path.
- Explicit total orderings everywhere — never `Counter.most_common()` (its tie
  behaviour is unspecified), never set iteration. Phase 16's pool, site and
  dependency orderings need the same treatment: a named sort key with an
  explicit tie-break.
- Config lives in nested Pydantic models under `SiftConfig`; a typo'd key must
  fail loudly.
- Determinism is load-bearing: identical case + config + rules ⇒ identical
  output.

### Integration Points

- **Input:** `EustackAnalysis` from `analyse_eustack()`.
- **Output:** the new analysis model, consumed by Phase 17 (`sift eustack`
  report + CSV) and Phase 18 (fact injection into `sift analyze`).
- **Config:** extends `EustackConfig` in `src/sift/config.py`.
- **Not touched:** `EXCLUDED_FROM_RANKING` and the dedup/embed/cluster/salience
  path — thread-event ranking exclusion is Phase 19, and only after
  `sift eustack` plus analyze fact-injection ship.

</code_context>

<specifics>
## Specific Ideas

Reference-capture figures the phase is measured against (real, out-of-repo
2.4 MB capture; used at verification time, not in CI):

- 3,902 threads collapsing to 93 distinct signatures
- 1,715 threads (44%) in `MSIQTask::GetNextPreferredJob` — must read as an idle
  pool, not saturation
- ~3,400 parked pool workers reading as idle overall
- 79 warehouse waits via `CDSSQueryEngine::WaitUntilFinished`
- 78 HTTP waits via `curl_multi_poll`
- zero `__lll_lock_wait` matches, and zero raised flags

CI fixtures remain the signature-preserving derivative (all 93 signatures,
thread counts capped low), plus the new synthetic lock-convergence fixture from
D-11.

</specifics>

<deferred>
## Deferred Ideas

- **Graded saturation percentage thresholds (EUSV2-03)** — explicitly deferred
  by the roadmap and reaffirmed here as D-07. No authoritative source exists for
  "N% busy = warning"; inventing one would author exactly the kind of number
  this milestone avoids.
- **A `pool = true` marker in the rules file** — would suppress meaningless
  occupancy rows for `compute`/`lock`. Revisit only if the Phase 17 report
  actually reads badly with them present.
- **A separate `dependency` field per rule** — revisit only if `subsystem`
  proves too fine-grained for the dependency axis in practice.

### Reviewed Todos (not folded)

- `2026-07-21-embedding-batch-composition-determinism.md` — matched on generic
  keywords only. Already scoped as SEED-002/DET-01, which is **Phase 20**.
- `2026-07-21-generation-context-unset.md` — LLM generation config; Phase 16 is
  model-free by D-12. Out of scope.

</deferred>

---

*Phase: 16-Saturation, Contention & Signature Collapse*
*Context gathered: 2026-07-25*
