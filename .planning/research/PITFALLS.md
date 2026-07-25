# Pitfalls Research

**Domain:** Thread-dump (eu-stack) hang/slowdown analysis added to an existing deterministic,
citation-gated incident-triage pipeline (Sift v1.3)
**Researched:** 2026-07-25
**Confidence:** MEDIUM (grounded in measured project evidence — reference capture, ADR 0012–0014,
SEED-002 — plus general Linux/ELF domain facts corroborated by web search; no real hung-server
capture exists to validate detection recall, which is itself the subject of Pitfall 5)

This document assumes the milestone context already established: composition of the 93 distinct
stack signatures is the signal, not motion; the intuitive "identical stack after 60 s = stuck"
heuristic is empirically inverted (98.9% false-positive rate on a healthy server); and v1.2's
`Total MCM Denial` counter (0 across 13,596 samples despite confirmed denials) is the project's
first instance of this same failure class. Every pitfall below either extends that lesson into a
new area or is a direct integration risk against code that already exists in this repo.

## Critical Pitfalls

### Pitfall 1: Composition-blind heuristics reproduce the 98.9% false-positive class

**What goes wrong:**
Any hang/saturation heuristic keyed on a thread's own history or raw counts — not its role —
fires on a healthy, near-idle server. This is one failure class with several entry points:

- **Thread-count growth.** `MSIQTask`/bursting/generic pools grow and shrink elastically under
  load; a threshold on raw thread-count delta between dumps fires during a legitimate load spike
  exactly as readily as during real saturation.
- **Deep stacks.** Depth 19 (158 threads in the reference capture) is a normal call chain for one
  idle path, not evidence of anything. A raw depth threshold penalises architecture, not health.
- **Blocking syscalls.** `pthread_cond_timedwait`, `__select`, `futex`-family waits are *correct*
  behaviour for parked pool workers and blocked-on-external threads alike — being "in a syscall for
  N seconds" is the same inverted signal already killed by the identical-stack measurement, just
  restated at the syscall layer instead of the stack-identity layer.
- **Short-lived thread aliasing.** A transient worker can present the same shallow, generic-looking
  stack as another transient worker sampled moments apart; treating "stack unchanged" as "same unit
  of work, still stuck" conflates population turnover with persistence (feeds into Pitfall 2).

**Why it happens:**
All of these are proxies for "this thread has been doing X for a while," which is true of the
overwhelming majority of a healthy server's idle pool workers by design. The proxies are easy to
compute and *look* diagnostic, which is exactly why the project's own pre-scoping measurement
caught the flagship version of this mistake rather than a code review.

**How to avoid:**
Classification must be a hard prerequisite gate, not a parallel signal: no verdict (hang, saturated,
contended) may be computed from a thread's raw persistence, depth, or syscall state — only from its
assigned **role** (idle-parked / blocked-on-external / blocked-on-lock / running / unclassified),
and verdicts operate on **role populations** ("N of the warehouse-wait population," not "thread T
has looked like this for 60 s"). This is already the direction the milestone scope commits to
("composition, not motion"); the risk is a later phase quietly reintroducing a motion-based check
as a "quick" secondary signal.

**Warning signs:**
The regression-gated healthy-capture eval case (already scoped as the negative fixture) reports any
non-zero hang/contention flags; a code review finds a threshold expressed in terms of `time since
last change` or `stack depth` rather than `role population share`.

**Phase to address:**
Thread-role taxonomy phase — this ordering is load-bearing: saturation/contention analysis cannot
be built correctly until role classification exists, so taxonomy must ship first and gate the
saturation phase's design, not just its data.

---

### Pitfall 2: TID reuse fabricates identity continuity the input format cannot support

**What goes wrong:**
Linux TIDs are recycled, and churn is real even on an idle server: the reference dumps, 60 s apart,
show 9 TIDs exit and 10 new TIDs appear out of ~3,900. A short-lived worker can be assigned a
recently-freed TID and be misread as "the same logical thread, still present" — or worse, a thread
that legitimately advanced (one of the 44 with a changed stack) can have its TID reused by an
unrelated new thread in a later dump, and a naive per-TID progression narrative would attribute the
new thread's stack to the old thread's story.

**Why it happens:**
eu-stack's native output carries **no start time and no thread name** — TID plus frame data only.
There is no positive identity signal in the input at all; this is an information-theoretic limit of
the format, not an engineering gap Sift can close by trying harder.

**How to avoid:**
Never assert per-TID identity continuity as fact. Multi-dump progression signals must be phrased
as **population deltas per stack signature** ("signature X: 79 → 85 threads"), which is robust to
TID churn because it doesn't depend on any single TID surviving between dumps. Where "which threads
advanced" (the 44 changed-stack threads) is reported, caveat it explicitly as *TID match, not
verified identity* — a lower-confidence tier than the deterministic figures elsewhere in the
report — and never narrate it as a causal single-thread story ("thread N progressed through cube
generation") without a corroborating signal. This is the same "never fabricate" boundary that
governs the LLM layer, applied one level down to the deterministic layer itself.

**Warning signs:**
A report sentence names a specific TID's trajectory as established fact rather than a population
statistic; an eval fixture asserts "thread N is stuck" using only TID match across two dumps.

**Phase to address:**
Multi-dump progression signals phase.

---

### Pitfall 3: Symbol brittleness turns a "never guess" classifier into a silent guesser

**What goes wrong:**
The rules file matches demangled C++ symbols. Compiler/build changes break this in specific,
recurring ways: template parameter strings differing between builds, `@@GLIBC_2.3.2`-style versioned
symbol suffixes appended to libc/libstdc++ calls, inlining removing a frame the rule looks for
entirely, static-vs-dynamic linking changing which frames resolve to real symbols at all, and
stripped binaries yielding bare hex addresses or `??`. The dangerous failure direction is not the
rule failing to match (safe — falls to `unclassified`, exactly as scoped) but the **rule matching
something it shouldn't**: an unanchored substring match colliding with an unrelated frame is the
same mechanism ADR 0013 already found and fixed in `dsserrors`'s sniff markers (a bare `"MCM"`
substring collided with a PDH counter path). A frame-matching rules engine that reaches for loose
substring/regex matching for convenience reintroduces that exact class of bug one layer up.

**Why it happens:**
Loose matching is the easy way to write a rule that "just works" against the one reference capture;
it is invisible until a different build's symbol strings shift underneath it.

**How to avoid:**
Match on a normalised, anchored basis — strip GLIBC version suffixes and template argument lists
before comparison, and match qualified function names, not raw substrings of the full frame text
(never repeat the bare-substring mistake ADR 0013 already paid for in a sibling adapter). A frame
that is only a hex address or `??` must classify its thread as unclassified for that tier and be
counted and surfaced in the report ("N threads with no resolvable frame"), never silently dropped or
guessed. Version the rules file against the MicroStrategy build(s) it was validated on, mirroring
ADR 0014's "record the knobs even though you can't fully control the underlying state" pattern, so
cross-build drift is diagnosable rather than invisible.

**Warning signs:**
`unclassified` percentage jumps after a rules-file or fixture update tied to a new build; a rules
match uses a bare `in` / unanchored regex against full frame text (should draw the same review
scrutiny ADR 0013 describes).

**Phase to address:**
Thread-role taxonomy phase — specifically the rules-matching engine's design, before the rules file
grows past its initial hand-curated set.

---

### Pitfall 4: Hand-picked thresholds from one healthy sample are neither defensible nor tunable

**What goes wrong:**
Saturation and contention verdicts need thresholds (e.g., "pool occupancy above X% = saturated"),
but only one real sample exists and it is healthy. A threshold picked to "look right" against that
single sample is unfalsifiable — it wasn't validated against an actual hang, and nothing in the
shipped report lets a reader independently check whether the threshold is reasonable for their
server.

**Why it happens:**
With no real hung-server capture, a threshold's only empirical anchor is a sample where every real
number should read "not saturated" — so any threshold above the observed baseline "passes," which
proves nothing about where the true line should sit.

**How to avoid:**
Follow the pattern already shipped for MCM (config-tunable, graded info/warn/critical flags, not a
hardcoded binary cutoff) rather than inventing a new one: thresholds live in config, not as magic
constants. The report must show the raw computed value **next to** the threshold and the verdict
(e.g., "cube-generation pool: 3/40 busy (7.5%), threshold 20% → not saturated") so a reader can
recompute and disagree with the classification without re-running Sift. Disclose in the report/docs
that thresholds are calibrated against one healthy reference plus synthetic fixtures, not a hang
corpus — the same honesty the eval harness already commits to for its positive cases.

**Warning signs:**
A threshold exists as a bare constant with no config knob; report output shows a verdict without
the underlying computed number beside it.

**Phase to address:**
Saturation & contention analysis phase.

---

### Pitfall 5: Synthetic hang fixtures written to match the detector prove nothing

**What goes wrong:**
With no real hung-server capture, positive eval cases must be hand-authored. The classic failure:
whoever writes the fixture encodes exactly the pattern the classifier already checks for (e.g.,
threads with the literal frame string the rule matches), so the test proves only "the code
recognises what its own author encoded" — a tautology, not evidence the detector generalises to a
real hang shape that differs in any cosmetic way.

**Why it happens:**
It is far easier to write a fixture backwards from the implementation than to derive one from an
independently-documented hang scenario, especially under time pressure to make the eval pass.

**How to avoid:**
1. Author positive fixtures from independently-documented hang/contention scenarios (warehouse
   connection-pool exhaustion, RWLock writer starvation, external-HTTP stall) — using the project's
   own MicroStrategy domain expertise as the source of the *scenario*, not the rules file as the
   source of the *fixture*.
2. Mutate each fixture cosmetically (rename a symbol as if from a different compiler, add a
   template-parameter variant, inject unrelated noise threads, shift stack depth by one frame) and
   require the classifier to still fire. A fixture that stops matching after a cosmetic mutation was
   overfit to string equality, not to the scenario.
3. Real dumps carry thousands of idle noise threads alongside any real problem (the reference
   capture: ~3,400 of 3,902 threads are parked, only 44 changed) — a fixture with zero noise threads
   is not representative and should be rejected in review.
4. In eval output and reporting, weight the synthetic-positive pass rate as **weaker** evidence than
   the real-capture negative pass rate; never claim "hang detection validated" from synthetic cases
   alone — state it as "does not cry wolf (measured), catches known hang shapes (synthetic, not yet
   observed in the wild)."

**Warning signs:**
A fixture's frame list is a near-verbatim copy of a rules-file pattern string; the fixture has no
noise threads; renaming one symbol in the fixture breaks the test.

**Phase to address:**
Golden eval harness phase — but the "derive from documented scenario, not from the rule" constraint
belongs as an acceptance criterion on the taxonomy and saturation phases too, since fixtures will
likely be authored alongside them, not only at the end.

---

### Pitfall 6: Naive per-thread work ignores the free 40x reduction the architecture already implies

**What goes wrong:**
At ~3,900 threads × ~10 frames per dump, several naive implementation choices create needless
O(threads) or O(threads²) cost: classifying every thread independently against every rule
(O(threads × rules)); matching TIDs across dumps with a nested loop instead of a dict keyed on TID
(O(threads²)); and, for multi-dump cases, computing progression per-thread rather than
per-signature.

**Why it happens:**
Threads are the natural unit to iterate over, so a straightforward implementation loops over all
3,900 of them — missing that the reference capture already collapses them to 93 distinct stack
signatures, a 40x reduction that the "composition, not motion" architecture makes available for
free.

**How to avoid:**
Classify the ~93 distinct signatures once, then broadcast the verdict to every thread sharing that
signature — this should be a stated acceptance criterion ("classification cost is O(distinct
signatures × rules), not O(threads × rules)"), not a later optimisation pass. Cross-dump TID
matching must build a `TID → stack` dict per dump and use dict/set operations, never a nested
comparison loop. Multi-dump progression signals should key on signature population deltas across N
dumps (O(N × signatures)), the same amortisation, not O(N × threads).

**Warning signs:**
Wall-clock analysis time scales with thread count rather than distinct-signature count; profiling
shows time concentrated in per-thread regex matching or nested TID comparison.

**Phase to address:**
Thread-role taxonomy phase (classification) and multi-dump progression phase — bake the
per-signature design in from the start; retrofitting it after threads are the primary computed unit
is a materially bigger diff than designing for it up front.

---

### Pitfall 7: A naive embedding-reuse cache silently reopens the determinism exposure it's meant to close

**What goes wrong:**
SEED-002 / DET-01 adds a reuse layer over `cluster.py`'s embed step to close the ADR 0014 exposure
(batch layout — including the layout of *preceding* requests — perturbs up to 4% of nearest
neighbours). A cache/reuse layer can reintroduce silent corruption in several specific ways instead
of fixing anything:

- **Stale vectors surviving a model change.** If the reuse key doesn't include embedding model
  identity and dimension, switching models (or Lemonade recipe) but reading back old vectors mixes
  two incompatible vector spaces into one HDBSCAN run — clusters become meaningless with no crash to
  reveal it.
- **Mixed vector generations from a batch-layout knob change.** Reusing a vector produced under one
  `embeddings.context`/`batch_size` while re-embedding new exemplars under another mixes two
  layouts inside the *same* clustering run — arguably worse than the documented ADR 0014 exposure,
  because it's not "a predecessor run perturbed this run," it's "this run's own vector set is
  internally inconsistent, permanently, until a full re-embed." SEED-002 names this as the open
  design question (invalidate reuse on a knob change, or not) — the wrong default is silent
  partial reuse across a knob change with no signal to the user.
- **Cache key collisions.** Keying reuse on raw `template_id` rather than a hash of the *exact* text
  actually sent to `embed()` (post-masking, post-truncation) risks two logically distinct groups
  sharing one cached vector, or one group's truncated text colliding differently across runs.
- **Breaking `prompted_ids` / prompt-hash invariants.** Reuse must be invisible to every downstream
  artefact's bytes — cluster labelling's prompt hash (already recorded to `meta`, pinned by
  `test_label_prompt_hash_written_to_meta`) must depend only on the final vector+cluster assignment,
  never on whether a given vector was a cache hit or miss.
- **Order-preservation bugs splicing hits and misses back together.** `embed()`'s existing contract
  reorders each batch by the server's `data[].index` and preserves input order end-to-end (pinned by
  `test_embed_preserves_index_order`). A reuse splice that appends embedded-misses after
  cached-hits instead of re-interleaving by original position will silently assign vector[i] to the
  wrong exemplar[i] — wrong numbers, no exception, one layer below where citation validation would
  ever catch it.

**Why it happens:**
Reuse/cache layers are usually added as a pure performance optimisation, so the design instinct is
"skip work when possible," not "prove every skipped-vs-redone path produces bit-identical
downstream artefacts" — but here the cache *is* the correctness fix (per ADR 0014), so getting the
invalidation and splice semantics wrong doesn't just cost performance, it reopens the exact
determinism gap the feature exists to close, silently.

**How to avoid:**
Reuse key = hash of the exact post-masking, post-truncation text plus embedding model identity and
dimension (reusing the existing `embedding_dim` mismatch guard and `record_embedding_identity`
provenance — a model/dim change must invalidate all cached vectors, hard, matching the guard's
existing behaviour). Resolve the open batch-layout-knob-change question explicitly and record the
decision (mirrors ADR 0014's "recorded, not silently applied" pattern) rather than leaving it
implicit. Build the reuse-splice as index-preserving by construction: allocate a result array sized
to the exemplar list up front, fill hits by original index, embed only misses (in their original
relative order), fill misses back by original index — and add a dedicated test mirroring
`test_embed_preserves_index_order` for the mixed-hit/miss case specifically. Make reuse observable
(a reused-vs-embedded count in output), which the seed itself already calls untestable otherwise.

**Warning signs:**
A re-run with a partial hit/miss split produces cluster/label differences not explained by
genuinely new template groups; a stale vector from a different model is read back without error;
the prompt hash in `meta` differs between two runs over identical case data purely because the
hit/miss split differed.

**Phase to address:**
SEED-002 / DET-01 vector-reuse phase.

---

### Pitfall 8: Integration regressions against invariants this codebase already enforces elsewhere

**What goes wrong, in four specific and separately testable ways:**

1. **Zero-authored-digit fact templates.** `mcm_facts.md` and `perfmon_facts.md` both hold zero
   authored digits and are byte-identical-additive when their data source is absent, each backed by
   an anti-hallucination test proving a planted wrong figure never reaches the prompt. A new
   `eustack_facts.md` that embeds a computed number directly in prose instead of expanding a
   template variable from computed code — or that omits the matching anti-hallucination test —
   breaks the pattern the entire citation mechanism depends on, silently, because nothing else in
   the pipeline checks *how* a fact template was written.

2. **Citable aggregate facts need a concrete event_id trail.** Unlike an MCM denial episode
   (naturally one citable thing), an eu-stack fact like "1,715 threads idle in the job queue" is an
   aggregate over a stack signature, not a single event. If the fact block cites the aggregate
   without resolving it to the concrete constituent `event_id`s under the hood, the
   `cited ⊆ prompted ⊆ store` anti-hallucination validator has nothing to check — the aggregate
   figure would be uncitable by construction even though it looks like every other cited fact in the
   report.

3. **CSV formula injection via symbol text — the wrong sibling to copy from.** `_csv_safe` in
   `perfmon_report.py` exists precisely because perfmon counter names are attacker-influenceable
   free text; `mcm_report.write_attribution_csv` deliberately does *not* carry the same guard because
   its keys are structurally hex SIDs/OIDs that cannot begin with a formula trigger. Demangled C++
   symbols (operator overloads, template angle brackets, `@@GLIBC_2.3.2` suffixes) are unstructured,
   attacker-shaped free text containing `=`, `<`, `>`, `+`, `-`, `@` — the perfmon risk profile, not
   the MCM one. Because eu-stack data is keyed by TID (numeric, MCM-shaped) it is easy to reach for
   the *wrong* sibling's reasoning ("keys are numeric, quoting suffices") while the actual injection
   surface is the free-text symbol/frame column. `sift eustack`'s CSV writer must reuse `_csv_safe`
   (compose with `render._util.sanitise`, sanitise-then-quote order, as already documented) on every
   symbol/frame string cell, with its own parametrised `test_csv_formula_guard`.

4. **Byte-identical-additive when no eu-stack data is present, and a pinned decision on ranking
   exclusion.** A case with no eustack events must produce byte-identical `sift analyze` output to
   pre-v1.3 behaviour (mirrors PERF-07). Separately, `EXCLUDED_FROM_RANKING` currently holds only
   `"dssperfmon"`, and eu-stack's ~3,900 events per dump currently flow through ranking — the
   milestone explicitly defers this decision. Whichever way it resolves, `store.py` already carries
   an inline warning that `iter_event_summaries` (ranking-filtered) and `iter_event_rows`
   (unfiltered, used for citation/evidence display) are deliberately **not** unified — applying an
   eustack exclusion to the wrong one of the two would either silently drop eu-stack evidence from
   citations or leak it back into cluster/salience competition, defeating the exclusion. Whichever
   choice is made needs its own golden-eval regression pinning the *chosen* cluster-output behaviour
   for a case *with* eu-stack data present, not only the "no data" byte-identical case.

**Why it happens:**
Each of these looks like a small, local change (add a fact template, add a CSV writer, add one
constant to a set) that pattern-matches against an existing sibling in the codebase — but the
correct sibling to copy from is determined by a property (numeric vs free-text key; ranking vs
citation path) that isn't obvious from the surface shape of the code.

**How to avoid:**
Treat each of the four as an explicit acceptance criterion with a named test, not an implicit
consequence of "add eu-stack facts / add a CSV export / decide on ranking": a fact-template
anti-hallucination test, a no-eustack byte-identical test, a CSV formula-guard test, and a
cluster-output regression test for a case *with* eu-stack data.

**Warning signs:**
A new fact template contains a literal digit; `sift eustack` CSV output has no formula-guard test;
an eustack ranking-exclusion change touches `iter_event_rows` instead of `iter_event_summaries` (or
vice versa depending on the direction of the change); no eval case exists asserting cluster output
with eu-stack data present.

**Phase to address:**
`sift analyze` integration phase and the ranking-exclusion decision (same phase per the milestone's
own scope grouping of items 5 and 6); `sift eustack` report/CSV phase for item 3.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Classify per-thread instead of per-signature | Simpler mental model, iterate the obvious unit | O(threads) cost that should be O(signatures); harder to retrofit later than to design in now | Never for v1.3 — the 40x reduction is free and known up front |
| Loose substring/regex rule matching in the taxonomy file | Faster to write a rule that passes on the reference capture | Reproduces the ADR 0013 bare-substring collision class one layer up | Never — anchor on qualified names from the start |
| Hardcoded saturation/contention thresholds | Ships faster, no config plumbing | Unfalsifiable against one healthy sample; not tunable per deployment | Never — mirror MCM-03's config-tunable graded-flag pattern |
| Authoring hang fixtures by copying the rule's own match pattern | Green eval test quickly | Proves nothing about real hang detection (Pitfall 5) | Never — derive from documented scenarios first |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|------------------|-------------------|
| `EXCLUDED_FROM_RANKING` seam | Filtering `iter_event_rows` (citation path) instead of `iter_event_summaries` (ranking path), or vice versa | Read both methods' docstrings first; the asymmetry is deliberate and documented inline in `store.py` |
| CSV export of symbol/frame text | Copying `mcm_report.write_attribution_csv`'s "keys are numeric, quoting suffices" reasoning | Copy `perfmon_report._csv_safe`'s reasoning instead — symbol text is free-text and attacker-shaped |
| Embedding vector reuse (SEED-002) | Keying cache reuse on `template_id` alone | Key on hash of exact post-masking/post-truncation text plus model identity + dimension |
| `embed()` order contract | Splicing cache hits/misses back by appending instead of by original index | Allocate result array by exemplar-list length up front; fill by original index for both hits and misses |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Per-thread rule matching | Analysis time scales linearly with thread count, not signature count | Classify the ~93 distinct signatures once, broadcast to member threads | Any case with a large idle pool (the norm, not the exception, per the reference capture) |
| Nested-loop TID matching across dumps | Analysis time grows quadratically with thread count as dump count increases | Build a `TID → stack` dict per dump, use dict/set operations | Cases with more than a handful of dumps |
| Per-thread progression deltas across many dumps | Redundant recomputation per thread instead of per signature | Key progression on signature population deltas | Multi-dump cases with high dump counts |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Treating eu-stack symbol/frame text as trusted because it "looks like" MCM's numeric-keyed data | CSV formula injection via demangled symbols starting with `=`, `+`, `-`, `@` | Reuse `_csv_safe` + `render._util.sanitise` composition on every symbol/frame string cell, with a dedicated formula-guard test |
| Asserting per-TID identity continuity as fact | A fabricated causal narrative ("thread N progressed...") presented with false certainty — the anti-fabrication boundary applied one layer below the LLM | Phrase multi-dump signals as signature-population deltas; caveat any per-TID claim explicitly |
| Loose rules-file matching misclassifying instead of falling to unclassified | A thread silently gets the wrong role attributed, undermining "unknown frames reported, never guessed" | Anchor matches on qualified names, stripped of build-specific suffixes; unresolved frames stay unclassified and are counted |

## "Looks Done But Isn't" Checklist

- [ ] **Thread-role taxonomy:** Often missing — an explicit `unclassified` count and rate surfaced
  in the report; verify the rules engine reports how many threads/frames failed to resolve, not
  just how many succeeded.
- [ ] **Saturation/contention thresholds:** Often missing — the raw computed value shown alongside
  the threshold in report output; verify a reader can recompute the verdict without re-running Sift.
- [ ] **Multi-dump progression:** Often missing — an explicit disclaimer on TID-based claims; verify
  no report sentence asserts single-TID identity continuity as unqualified fact.
- [ ] **Golden eval hang fixtures:** Often missing — cosmetic-mutation robustness and noise-thread
  presence; verify a fixture still passes after renaming a symbol or adding unrelated threads.
- [ ] **`eustack_facts.md`:** Often missing — the anti-hallucination test proving a planted wrong
  figure never reaches the prompt; verify it exists exactly as it does for `mcm_facts.md` /
  `perfmon_facts.md`.
- [ ] **SEED-002 vector reuse:** Often missing — a mixed hit/miss index-preservation test; verify
  vector[i] corresponds to exemplar[i] for every i in a partial-reuse run, not just full-hit or
  full-miss runs.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|-----------------|
| Composition-blind false positives shipped (Pitfall 1) | LOW | The regression-gated healthy-capture eval case catches this before release; if it slips through, disable the offending heuristic and re-run the negative case to confirm zero flags before re-enabling |
| TID-identity overclaiming in a shipped report (Pitfall 2) | LOW | Rephrase report language to population deltas; no data model change required since signatures are already computed |
| Rules-file misclassification after a build change (Pitfall 3) | MEDIUM | Add the new build's symbol variants to the versioned rules file; re-run the eval suite; the rules file is editable without touching Python by design, so this is a data change, not a code change |
| Reused vectors mixing generations (Pitfall 7) | HIGH | Requires a full re-embed of the affected case (`--re-embed` escape hatch, per SEED-002's sketch) plus an audit of any report already generated from the corrupted `case.db` |
| CSV formula injection guard missing (Pitfall 8.3) | LOW | Add the `_csv_safe` composition and a regression test; no data model change, existing CSVs can be regenerated |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1. Composition-blind false positives | Thread-role taxonomy | Healthy-capture negative eval case reports zero flags |
| 2. TID reuse / identity fabrication | Multi-dump progression signals | Report language audit: no unqualified per-TID causal claims |
| 3. Symbol/frame brittleness | Thread-role taxonomy (rules engine) | Unclassified-rate regression test across a build-variant fixture |
| 4. Threshold arbitrariness | Saturation & contention analysis | Report shows raw value beside threshold; thresholds are config keys |
| 5. Synthetic-fixture self-deception | Golden eval harness (+ taxonomy/saturation as fixtures are authored) | Cosmetic-mutation robustness test per positive fixture |
| 6. Scale/perf traps | Thread-role taxonomy + multi-dump progression | Classification cost scales with distinct-signature count, not thread count |
| 7. Vector-reuse determinism regressions | SEED-002 / DET-01 | Mixed hit/miss index-preservation test; model/dim-change invalidation test |
| 8. Integration regressions (facts, CSV, ranking) | `sift analyze` integration + `sift eustack` report/CSV | Anti-hallucination test, formula-guard test, byte-identical-additive test, with-data cluster regression test |

## Sources

- `.planning/research/MILESTONE-CONTEXT-v1.3.md` — measured reference-capture evidence (3,902/3,903
  threads, 93 signatures, 98.9% identical-stack rate, TID churn 9/10) — HIGH (first-party measurement)
- `.planning/PROJECT.md`, `.planning/MILESTONES.md` — v1.1/v1.2 retrospective, the `Total MCM Denial`
  precedent, requirement/decision history — HIGH (first-party project record)
- `.planning/seeds/SEED-002-embedding-vector-reuse.md` — vector-reuse design sketch and open
  questions — HIGH (first-party, pre-decision)
- `docs/decisions/0014-embedding-determinism-scope.md` — batch-layout determinism measurement
  (probes A/B, 4% neighbour-flip rate, hysteresis behaviour) — HIGH (first-party measurement)
- `docs/decisions/0013-dsserrors-qualified-mcm-sniff.md` — bare-substring sniff-marker collision,
  the precedent for Pitfall 3's rules-matching concern — HIGH (first-party measurement)
- `docs/decisions/0012-perfmon-naive-timestamps.md` — precedent for "record, don't apply" when a
  declared value can't be trusted — HIGH (first-party)
- Codebase inspection via graphmind: `src/sift/store.py` (`EXCLUDED_FROM_RANKING`,
  `iter_event_summaries` vs `iter_event_rows` asymmetry), `src/sift/llm/client.py` (`embed()` order
  contract), `src/sift/render/perfmon_report.py` (`_csv_safe`) — HIGH (first-party, read directly)
- [How to obtain a unique thread identifier on Linux](http://www.alexonlinux.com/how-to-obtain-unique-thread-identifier-on-linux) — TID reuse mechanics — MEDIUM
- [ptrace() — Tracing the wrong thread after TID recycling (LKML)](https://lkml.rescloud.iu.edu/2208.3/01031.html) — confirms TID-reuse misattribution is a known, recurring class of bug in other tools — MEDIUM
- [DunnDunnDunn: GCC demangling and stack traces](http://cdunn2001.blogspot.com/2012/05/gcc-demangling-and-stack-traces.html) — dynamic-symbol visibility and demangling fragility — MEDIUM

---
*Pitfalls research for: Sift v1.3 EU-Stack Hang & Slowdown Diagnosis*
*Researched: 2026-07-25*
