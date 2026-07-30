# Phase 18: Eu-Stack Facts into `sift analyze` - Context

**Gathered:** 2026-07-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Carry the eu-stack figures the deterministic core already computed (Phases 15–17) into the
`sift analyze` prompt as cited evidence, so the LLM narrates them rather than authoring them —
while a case with no eu-stack data produces a prompt byte-identical to today's.

This is the **fourth copy of the fact-injection pattern**, after `mcm_facts` (MCM-06),
`perfmon_facts` (PERF-07) and their prompt templates. Requirement: **EUS-10**.

Explicitly NOT in this phase:
- **EUS-11** (eu-stack events excluded from dedup/embed/cluster/salience) — Phase 19. The
  REQUIREMENTS.md decision table locks the sequencing: exclusion lands only after EUS-09 and
  EUS-10 ship, because eu-stack events today produce working clusters and hypotheses for
  eu-stack-only cases and removing them first opens a regression window.
- **EUS-12** (regression-gated golden eval) — Phase 19.
- **DET-01** (embedding-vector reuse) — separate requirement, deliberately left pending.

</domain>

<decisions>
## Implementation Decisions

### Aggregate → citable event_id set

This was the ROADMAP's flagged unsolved question. An MCM episode and a perfmon sample are
already one-to-one with events; a signature population is one-to-many. Resolved in discussion
rather than deferred to an ADR:

- **D-01:** A population figure cites a **bounded exemplar sample**, not the full population.
  The existing `[evt:<id>]` citation token is reused unchanged — no new citation kind, no new
  store table, no validator change.
- **D-02:** **K = 3** exemplar thread event_ids per signature, selected as the **lowest three
  event_ids in sort order**. `event_id` is `sha256(source_file, byte_offset)[:16]`, so this
  selection is stable by construction and needs no tie-break rule.
- **D-03:** The block **must state in words that it is sampling** — the count of cited
  exemplars and the true population size both appear, e.g.
  `(3 of 1,715 thread events cited as exemplars)`. Emitting three citations beside the figure
  1,715 without that sentence would imply the population was enumerated. This wording is
  load-bearing honesty, not cosmetic.
- **D-04:** Rejected alternatives, recorded so they are not re-litigated: citing the full
  population (~31 KB for one figure, unaffordable when fact blocks bypass `PromptBudget.fit`);
  and persisting each aggregate as its own store row with a synthetic citable id (needs a new
  table, a migration, and a second citation kind the validator must learn).

### Fact-block scope and cap

- **D-05:** All four Phase 16 groupings enter the block as summary lines: role composition,
  per-pool occupancy, lock-site convergence, external-wait concentration. Each is bounded and
  small on its own.
- **D-06:** Only the **per-signature listing** takes a cap. `_MAX_SIGNATURES = 8`, matching
  `mcm_facts._MAX_EPISODES = 8` and `perfmon_facts._MAX_GROUPS = 8` — one consistent ceiling
  across all four fact modules, ranked most-significant-first exactly as its siblings are.
  The real reference capture holds 93 signatures, which is precisely what the cap is for.
- **D-07:** Dropped signatures must be **stated as dropped**, never silently truncated —
  the project's "nothing disappears silently" invariant.
- **D-08:** Rejected: a composition-dependent cap that force-includes flagged signatures below
  the cut. That makes block length depend on case composition, the same determinism hazard the
  D-07 source-kind principle already rejects at `store.py:333-334`.

### Multi-dump cases and the ordering flag

- **D-09:** On a multi-dump case the block carries **last-dump state (D-11) plus Phase 17's
  per-signature population deltas** for changed signatures, under the same `_MAX_SIGNATURES`
  cap. Direction of travel is what a hang diagnosis turns on, so the progression layer must not
  stay locked inside `sift eustack`.
- **D-10:** **When the dump order is unverified, deltas are suppressed entirely.** If
  `resolve_dump_order` fell back to `ORDER_BASIS_FILENAME` (the D-02 sorted-filename path), the
  block carries last-dump state only and states plainly that progression was not reported
  because the dump order could not be verified. The model must never be given a direction of
  travel derived from a guessed order — the figures would all be real and only their order
  wrong, which is exactly the error citation validation cannot catch.
- **D-11:** Note for the researcher and planner: **the real reference capture takes the
  unverified path** — `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` carries no
  header timestamp. Suppression is therefore the common case on real data, not an edge case,
  and must be tested as the primary path. The synthetic `tests/fixtures/eustack/progression/`
  set authored in Phase 17 is what exercises the verified-ordering path.

### Byte-identity when no eu-stack data is present

- **D-12:** Reuse the **MCM-06 / PERF-07 test pattern verbatim** — whatever
  `tests/test_mcm_facts.py` and `tests/test_perfmon_facts.py` already do to prove the
  no-MCM and no-perfmon prompts are byte-identical gets a third instance for eu-stack. The
  planner reads those two test modules and mirrors them rather than inventing a third approach.
- **D-13:** Rejected: a committed golden prompt hash (brittle — fires on every legitimate
  template edit, and none of the other three fact modules work that way).

### Prompt budget

- **D-14:** Folded from todo `.planning/todos/pending/2026-07-21-generation-context-unset.md`:
  `generation.context` is unset, so `PromptBudget` uses a built-in fallback rather than the
  generation model's real `n_ctx` — Lemonade exposes no `/props` endpoint to discover it. A
  fourth fact block that **bypasses `PromptBudget.fit`** makes this headroom question concrete.
  In scope for this phase: quantify the assembled worst-case fact-block size against the
  fallback budget, and state whether the four blocks together can overrun it. Not in scope:
  building `n_ctx` auto-discovery.

### Module placement

- **D-15:** `src/sift/pipeline/eustack_facts.py` stays a **leaf module** — `hypothesise`
  imports it, never the reverse — matching `mcm_facts.py` and `perfmon_facts.py`.
- **D-16:** `src/sift/prompts/eustack_facts.md` is a versioned template containing **zero
  authored digits**, matching `mcm_facts.md` and `perfmon_facts.md`. Changing the prompt must
  never require touching Python.

### Claude's Discretion

- Exact section ordering and heading wording inside the fact block
- How the sampling sentence in D-03 is phrased, provided both numbers appear
- Whether the four groupings are separate template sections or one table
- Test file organisation, provided D-12's mirroring holds

</decisions>

<specifics>
## Specific Ideas

- The exemplar-citation shape the user selected, as a concrete target:

  ```
  Idle job-queue pool: 1,715 threads across 1 signature
  [evt:a1b2c3d4e5f6a7b8][evt:b2c3d4e5f6a7b8c9][evt:c3d4...]
  (3 of 1,715 thread events cited as exemplars)
  ```

- The healthy reference capture raises **zero flags** — that is the Phase 16 D-09 gate. The
  fact block must still be useful on a zero-flag case, since "nothing is flagged" is itself a
  finding the model should be able to narrate.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement and milestone scope
- `.planning/REQUIREMENTS.md` — EUS-10 text, plus the "Decisions folded into these
  requirements" table (deterministic-core-vs-LLM boundary; EUS-11 sequencing after EUS-09 and
  EUS-10; exclusion as a property of source kind with no composition-dependent middle option)
- `.planning/ROADMAP.md` §"Phase 18" — goal, the four success criteria, and the research flag
  naming the aggregate-citation problem as unsolved

### Eu-stack analysis being narrated
- `docs/decisions/0015-eustack-thread-role-taxonomy.md` — role/subsystem taxonomy, the rules
  file, and why classification is never LLM-authored
- `docs/decisions/0016-eustack-saturation-analysis.md` — the four groupings this block reports;
  per-pool occupancy definition, ownership-blind lock-site convergence, external-wait
  concentration, signature collapse
- `.planning/phases/17-multi-dump-progression-sift-eustack-report-csv/17-CONTEXT.md` — D-01/D-02
  ordering basis, D-07 identity projection, D-08 both-deltas rule, D-09 ranking, D-10 no
  per-thread claim, D-11 last-dump scoping
- `.planning/phases/17-multi-dump-progression-sift-eustack-report-csv/17-VERIFICATION.md` — the
  D-10 vocabulary gate's agreed scope (bans continuity verbs and concrete `TID <n>` value
  tokens, not the bare word "TID")

### Fact-injection pattern to mirror
- `src/sift/pipeline/mcm_facts.py` — `_MAX_EPISODES = 8`, severity ranking, leaf-module shape
- `src/sift/pipeline/perfmon_facts.py` — `_MAX_GROUPS = 8`, `_cite_prefix` / citable-id
  accumulation, the `ponytail:` note on the fixed group ceiling
- `src/sift/prompts/mcm_facts.md`, `src/sift/prompts/perfmon_facts.md` — zero-authored-digit
  template shape
- `tests/test_mcm_facts.py`, `tests/test_perfmon_facts.py` — the byte-identity and
  planted-wrong-figure tests D-12 mirrors
- `tests/test_hypothesise.py` — where the fact blocks meet prompt assembly

### Determinism and citation invariants
- `docs/decisions/0012-perfmon-naive-timestamps.md` — the "record, don't apply" precedent D-10
  above follows
- `docs/decisions/0014-embedding-determinism-scope.md` — the determinism boundary this phase
  must not widen
- `CLAUDE.md` §"Load-bearing invariants" — citation validation as the anti-hallucination
  mechanism, `cited ⊆ prompted ⊆ store`, nothing disappears silently

### Folded todo
- `.planning/todos/pending/2026-07-21-generation-context-unset.md` — the `generation.context` /
  `PromptBudget` fallback question folded in as D-14

**No new ADR is required for the aggregate-citation question** — D-01 through D-04 settle it.
The ROADMAP's research flag recommended an ADR only because the question was open; the planner
should still record the choice in `docs/decisions/` if it wants the rationale beside 0015/0016,
but it is not a blocker on the plan freezing.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `perfmon_facts._cite_prefix(event_ids, ids)` — joins `[evt:<id>]` tokens and accumulates the
  citable-id set. The exemplar citation in D-01/D-02 is exactly this call with a sliced tuple.
- `render_perfmon_facts(analysis) -> tuple[str, set[str]]` — the `(text, citable_ids)` return
  signature `render_eustack_facts` should match.
- `_group_severity_rank` / `_episode_severity_rank` — the ranking-then-slice shape D-06 mirrors.
- `EustackBundle` / `ProgressionAnalysis` / `SignatureProgression` from
  `src/sift/pipeline/eustack_progression.py` — already carry counts, step_deltas,
  overall_delta, appeared, vanished, and the classification fields.
- `OrderingFlag` and the `ORDER_BASIS_*` constants — D-10's suppression predicate reads the
  resolved basis directly; no re-derivation needed.

### Established Patterns
- Fact blocks bypass `PromptBudget.fit`, which is why every fact module owns a fixed cap. This
  is the constraint behind both D-06 and D-14.
- Prompt templates are versioned files under `src/sift/prompts/`; changing a prompt must never
  require touching Python.
- Thread event_ids are already individually citable and already in the store — no ingestion or
  store change is needed for D-01 to hold.

### Integration Points
- `src/sift/pipeline/hypothesise.py` — imports the fact renderers and assembles the prompt.
  The eu-stack block is appended alongside the MCM and perfmon blocks; D-12's byte-identity
  requirement lives at this seam.
- `src/sift/pipeline/eustack_progression.py::analyse_eustack_bundle` — the single entry point
  producing everything the block reports.

</code_context>

<deferred>
## Deferred Ideas

- **EUS-11** — eu-stack events excluded from dedup/embed/cluster/salience. Phase 19, and
  sequenced there deliberately (REQUIREMENTS.md decision table).
- **EUS-12** — regression-gated golden eval over the real healthy capture and synthetic hang
  fixtures. Phase 19.
- **DET-01 / SEED-002** — reusing persisted embedding vectors instead of re-embedding. Matched
  the phase-18 todo scan on keywords but is its own requirement, unrelated to fact injection.
  Stays in `.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`.
- **`generation.context` auto-discovery** — quantifying the headroom is in scope (D-14);
  building `n_ctx` discovery is not. Lemonade exposes no `/props`.
- **Per-thread continuity narration** — a permanent non-goal, not a deferral. Eu-stack carries
  no monitor-ownership edges and TIDs are reused; the analyser is population-level only and
  must never emit "deadlock".

</deferred>

---

*Phase: 18-eu-stack-facts-into-sift-analyze*
*Context gathered: 2026-07-26*
