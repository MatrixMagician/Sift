# Phase 19: Ranking Exclusion & Regression-Gated Golden Eval - Context

**Gathered:** 2026-07-27
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 4 grey areas, 16 questions, all recommendations accepted

<domain>
## Phase Boundary

Eu-stack thread events stop competing in dedup/embed/cluster/salience now that the deterministic
replacement (`sift eustack`, Phase 17; eu-stack facts into `sift analyze`, Phase 18) has shipped,
and the whole eu-stack path is locked behind golden regression gates.

**In scope:** the `EXCLUDED_FROM_RANKING` seam gaining `"eustack"` (EUS-11); the `sift analyze`
path staying useful on an eu-stack-only case after that exclusion; byte-identity and citability
proofs; a regression-gated golden eval covering the real healthy capture (negative) and synthetic
hang fixtures (positive) with a vacuity guard (EUS-12).

**Out of scope:** any change to the taxonomy rules file, the saturation analyser, the `sift eustack`
report or the Phase-18 fact renderer — those are shipped and frozen. No new analysis mechanism.
DET-01 / SEED-002 vector reuse is Phase 20.

**Sequencing within the phase:** EUS-11 lands **first**, before EUS-12's fixtures are authored, so
the golden fixtures reflect final ranking behaviour rather than a moving target.

</domain>

<decisions>
## Implementation Decisions

### Ranking exclusion mechanics (EUS-11)

- **D-19-01 — One-line seam change.** Exclusion lands as
  `EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon", "eustack"})` at
  `src/sift/store.py:335`. No new machinery: no per-adapter attribute on the Adapter protocol,
  no config toggle, no opt-out parameter. Exclusion stays a property of the **source kind**, never
  of the case or the caller — the D-07 principle the existing seam comment already states. The
  composition-dependent third option ("exclude only when another ranked source is present") is
  **rejected**, per REQUIREMENTS.md's folded decision, not merely deprioritised.

- **D-19-02 — `sift analyze` must not dead-end on an eu-stack-only case.** Verified defect, not a
  hypothetical: `src/sift/cli.py:876-882` short-circuits on `if not groups:` with
  `print("Nothing to cluster; run 'sift ingest' first"); return`. Because dedup reads
  `iter_event_summaries` (the filtered seam), an eu-stack-only case has **zero template groups**
  once `"eustack"` is excluded — so `analyze` returns *before* `hypothesise()` is ever called, and
  the Phase-18 eu-stack fact block (built at `src/sift/pipeline/hypothesise.py:472-480`) never
  reaches the model. The message is also factually wrong: ingest *did* run.

  **Decision:** `analyze` proceeds to `hypothesise()` when the case holds events of an excluded
  source, so the deterministic facts still narrate and citations still resolve. This is what makes
  EUS-11 a **replacement** rather than a deletion — precisely the property EUS-11's
  "lands only after EUS-09 and EUS-10 ship" sequencing rule exists to protect. A zero-cluster
  `hypothesise()` run must be a supported path (empty `ranked`, prompted_ids sourced from the fact
  block alone), not a crash or a degraded exit. Message-only fixes and leave-as-is were both
  considered and rejected.

- **D-19-03 — Byte-identity proof reuses the PERF-03 criterion-4 pattern verbatim.** A two-case
  fixture pair (identical inputs, one with the eu-stack dump ingested and one without) whose
  cluster + salience output is asserted **byte-identical**. Assert on the derived cluster/salience
  render, never on the two `case.db` files — case B legitimately holds the eu-stack events. Rejected:
  asserting template-group counts only (too weak), snapshotting the whole rendered report (too broad,
  couples the proof to unrelated report churn).

- **D-19-04 — Citation path is unchanged and pinned.** `iter_event_rows` stays unfiltered; the
  asymmetry with `iter_event_summaries` is the invariant and must not be unified into a shared
  helper. Add a dedicated test that every eu-stack event stays individually retrievable and citable
  after exclusion, mirroring the shipped `test_show_events_includes_perfmon`. This is a separate
  test from D-19-03's byte-identity pair, not folded into it.

### Golden-eval integration shape (EUS-12)

- **D-19-05 — Detection is asserted deterministically, with no LLM.** `truth.yaml` gains an
  **optional** block (working name `expect_eustack`, e.g.
  `{hang_detected: bool, flags: 0, provenance: authored|observed}`) scored directly from
  `analyse_eustack_bundle`. Rationale, established during discuss: `eval/runner.py:run_case`
  requires a live `InferenceClient` and matches `required_evidence` against **cluster exemplars** —
  which an excluded eu-stack case no longer has. The existing harness shape therefore cannot score
  an eu-stack case unchanged, and the roadmap's own success criteria ("reports no hang and raises
  zero flags", "synthetic hang fixtures are detected") are deterministic-analyser assertions, not
  LLM ones. `Truth` is `extra="forbid"`, so the new key must be added to the model, not smuggled in.

- **D-19-06 — Eu-stack cases run no LLM leg.** They declare `required_evidence: []` and
  `acceptable_keywords: []` so no LLM metric is scored vacuously on them. The eu-stack cases are the
  LLM-free subset of the suite; the other eight cases are unaffected and still need a client.

- **D-19-07 — A new gated floor carries the metric.** `eval/thresholds.toml` gains
  `eustack_detection_rate = 1.00`, in the same higher-is-better lower-bound shape as the existing
  four floors, so one comparison direction still covers every metric (ADR 0010). Rejected: reusing
  `hypothesis_hit_at_k` (wrong semantics — it is an LLM metric), and pytest-only gating (EUS-12
  explicitly requires `sift eval` to exit non-zero on regression).

- **D-19-08 — Fixture layout.** `eval/cases/eustack-healthy/` holds the real-capture derivative
  (negative); `eval/cases/eustack-hang-*/` hold the synthetic positives. Separate case directories,
  not one combined multi-dump case, so the suite table shows each verdict independently and a
  single regression names its own case.

### Synthetic hang fixture authorship

- **D-19-09 — Scenario: pool saturation + external-wait concentration.** Every worker in one pool
  parked on the same warehouse-wait signature. Derived from the documented hang scenario in
  REQUIREMENTS.md / `.planning/research/PITFALLS.md` — **never** authored from the strings in
  `src/sift/rules/eustack_roles.toml`, or the eval proves only that the code runs (the named risk
  in PITFALLS.md and in the Phase-19 blocker already recorded in STATE.md). Rejected as the primary
  scenario: lock convergence, and a `??`-heavy unresolvable-frame dump.

- **D-19-10 — Provenance is a machine-checked field, not prose.** A mandatory `provenance` field in
  the eu-stack truth block (`authored` for every synthetic positive, `observed` for the healthy
  capture) plus a README in each case directory, plus a test asserting the healthy case is the only
  one marked `observed`. The evidence gap — the reference capture is a healthy, near-idle server, so
  it proves the analyser does not cry wolf but cannot prove hang-detection recall — must stay
  visible in the harness, not only in planning docs.

- **D-19-11 — Cosmetic-mutation twins ship as fixtures.** Renumbered TIDs, reordered thread blocks
  and differing instruction addresses; one mutated twin fixture per positive case, asserted to yield
  an identical verdict. Rejected: mutating at test time in code — a shipped twin is auditable and
  keeps the mutation itself under review.

- **D-19-12 — Fixtures stay signature-preserving and small**, following the discipline already used
  for `tests/fixtures/eustack/` (all signatures present, thread counts capped). Not full-size
  realistic dumps.

### Gate wiring & vacuity

- **D-19-13 — Zero eu-stack cases scored forces a gate failure.** Extends ADR 0010's existing
  "empty positive set is never a pass" rule to the new metric, so deleting or skipping the eu-stack
  cases cannot silently turn the gate green.

- **D-19-14 — A sensitivity test proves the gate actually bites.** Neuter the analyser (e.g. disable
  a rule) and assert `sift eval` exits non-zero — the pattern established by
  `test_mcm_denial_citation_validity_is_mcm_sensitive` in `tests/test_eval_cases.py`. Rejected:
  trusting the threshold comparison alone.

- **D-19-15 — The negative case gates on zero flags literally.** `flags == 0` **and**
  `hang_detected == false`, both asserted; a warn-level flag on the healthy capture is a failure.
  The looser "allow info-level flags" option was considered and rejected — success criterion 2 says
  "raises zero flags".

- **D-19-16 — LLM-free subset documented.** `sift eval`'s eu-stack cases are runnable without an
  inference endpoint; the suite as a whole still requires one for the other cases. Document this
  split where the harness is described rather than silently relying on it.

### Claude's Discretion

- Exact field names and nesting of the `expect_eustack` truth block (subject to `extra="forbid"`).
- Whether the zero-cluster `hypothesise()` path (D-19-02) is reached by relaxing the `cli.py:880`
  guard, by an earlier branch, or by another equivalent seam — provided `analyze` neither crashes
  nor prints a false "run `sift ingest` first" on an eu-stack-only case, and cases with **no**
  events at all still short-circuit as they do today.
- Number of synthetic positive cases beyond the one required scenario.
- Plan/task/wave breakdown, subject to EUS-11 landing before EUS-12's fixtures are authored.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/sift/store.py:335` — `EXCLUDED_FROM_RANKING` frozenset, currently `{"dssperfmon"}`. Exactly
  one production reader: `iter_event_summaries` (`store.py:641-670`), whose `SELECT` carries
  `WHERE source NOT IN (...)` with `sorted()`-ordered `?`-bound values for determinism.
- `src/sift/store.py:672-703` — `iter_event_rows`, the deliberately **unfiltered** twin backing
  `show events`, citation hydration and evidence display. Its docstring forbids unifying the two.
- `src/sift/eval/truth.py` — `Truth` Pydantic model (`extra="forbid"`) + `load_truth` using
  `yaml.safe_load` only. Any new truth key must be added to the model.
- `src/sift/eval/thresholds.py` — `load_thresholds`, `MetricVerdict`, `GateResult`, `gate()`;
  all floors are uniform lower bounds (ADR 0010).
- `src/sift/eval/metrics.py` — `CaseResult` / `SuiteResult`, `negative_case_pass`,
  `determinism_stability`; the aggregation layer a new metric plugs into.
- `src/sift/pipeline/eustack.py` — `analyse_eustack_bundle`, the deterministic analyser the new
  eval metric scores against (no LLM involved).
- `tests/fixtures/eustack/` — signature-preserving derivative fixtures (93/93 signatures, capped
  thread counts) and the `_copy_fixture(only=...)` helper in `tests/test_cli.py`.

### Established Patterns

- **PERF-03 (Phase 12) is the direct analog for EUS-11** — same seam, same one-line shape, same
  D-07 rationale, same criterion-4 byte-identity proof asserted on derived cluster output rather
  than on the `case.db` files. `.planning/milestones/v1.2-phases/12-.../12-04-PLAN.md` is the
  reference plan.
- **Fact renderers read `store.query_events()` (unfiltered)** at `hypothesise.py:472`, so all three
  fact blocks (MCM, perfmon, eu-stack) survive ranking exclusion untouched — the blocker is
  `cli.py:880` returning early, not the renderers.
- **Golden truth files are frozen before prompt tuning** and must never be edited to make a run
  pass — a regression must fail, not be silently accommodated (header comment in every `truth.yaml`).
- Eval sensitivity tests live in `tests/test_eval_cases.py` and prove a metric genuinely depends on
  the mechanism under test.

### Integration Points

- `src/sift/store.py:335` — the one-line exclusion change (EUS-11).
- `src/sift/cli.py:876-882` — the `analyze` zero-groups short-circuit that must stop dead-ending
  eu-stack-only cases (D-19-02).
- `src/sift/eval/truth.py` — `Truth` model gains the optional eu-stack block.
- `src/sift/eval/metrics.py` / `report.py` / `thresholds.py` — the new metric, its column and its
  floor.
- `eval/thresholds.toml` — `eustack_detection_rate`.
- `eval/cases/eustack-healthy/`, `eval/cases/eustack-hang-*/` — new golden case directories.
- `tests/test_eval_cases.py`, `tests/test_store.py`, `tests/test_cluster.py` — the pinning tests.

</code_context>

<specifics>
## Specific Ideas

- The `analyze` dead-end (D-19-02) was found by reading `cli.py:876-882` against the exclusion
  change, not predicted by the milestone research — the research pass assumed eu-stack facts would
  keep flowing into `analyze` regardless of exclusion. Planning must treat "facts still narrate on
  an eu-stack-only case" as a **verified acceptance criterion with a test**, not an assumption.
- The negative golden case is the real healthy reference capture derivative; it can only prove the
  analyser does not raise false alarms. Recall is proven exclusively by authored fixtures, and the
  harness must say so in-band via `provenance`.
- `Truth` is `extra="forbid"` — adding the eu-stack block to `truth.yaml` without extending the
  model fails loudly at load. That is the intended behaviour; do not relax it.

</specifics>

<deferred>
## Deferred Ideas

- Additional hang scenarios beyond pool saturation + external-wait concentration (lock convergence,
  unresolvable-frame-heavy dumps) — the taxonomy supports them; authoring more than the one required
  positive is at Claude's discretion within this phase, and anything larger belongs in a later
  milestone.
- DET-01 / SEED-002 embedding vector reuse — Phase 20, functionally independent of this phase.
- The `generation.context` unset todo (`.planning/todos/pending/2026-07-21-generation-context-unset.md`)
  remains open and is not addressed here.

</deferred>
