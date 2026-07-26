# ADR 0017: eu-stack aggregate-citation sampling — bounded exemplars, K=3, mandatory disclosure

**Status:** Accepted (implemented in Phase 18 / v1.3)
**Date:** 2026-07-26
**Answers:** How does a signature-population figure — one-to-many with events, unlike an MCM
denial episode or a perfmon sample, both one-to-one — become a citable `[evt:<id>]` reference
inside the `sift analyze` triage prompt, and what must the block say alongside that citation so
it is never mistaken for an enumeration of the whole population? Cross-refs REQUIREMENTS.md
EUS-10, `.planning/phases/18-eu-stack-facts-into-sift-analyze/18-CONTEXT.md` D-01 through D-04
and D-17, and `.planning/phases/18-eu-stack-facts-into-sift-analyze/18-RESEARCH.md` § Open
Questions (D-17/D-18 resolutions).

This records decisions already made during Phase 18 discussion and research; it does not
re-argue them.

## Context

`mcm_facts.py` and `perfmon_facts.py` (Phases 11 and 14) each surface figures that are already
one-to-one with a stored event: an MCM denial episode carries its own `denial_event_id`, a
perfmon sample its own `event_id`. Citing either is a direct lookup — no sampling question ever
arises.

Eu-stack breaks that pattern. A role-composition line, a per-pool occupancy figure, a lock-site
convergence count, an external-wait concentration total, and the per-signature listing all report
a **population** — hundreds or thousands of threads sharing one stack signature — and none of the
frozen Phase 15/16/17 models (`EustackAnalysis`, `SaturationAnalysis`, `ProgressionAnalysis`)
carries an `event_id` for that population. `SaturationFlag`'s own docstring names this gap
explicitly as Phase 18's open design question, by design: widening those frozen models to carry
event ids was rejected before this phase began (D-04 below), so the question is not "should the
gap exist" but "how does a fact renderer resolve it at citation time, without touching Phase
15–17's shipped surface."

## Decision

### D-01 — A population figure cites a bounded exemplar sample, never the full population

The existing `[evt:<id>]` citation token is reused unchanged. No new citation kind, no new store
table, no change to the citation-gate validator (`_row_citations_valid`/`_all_cited_within` in
`hypothesise.py`) — a sampled figure's citations are ordinary stored `event_id`s, indistinguishable
in shape from an MCM or perfmon citation. The only new question this phase answers is which ids,
out of a population that can run into the thousands, get printed.

### D-02 — K = 3, the lowest three event_ids in sort order

`event_id` is `sha256(source_file, byte_offset)[:16]` — a pure function of where a thread event
lives on disk. Sorting the resulting hex strings ascending and taking the first three is therefore
stable by construction: re-running the identical ingest reproduces the identical three ids, with no
tie-break rule needed and no dependency on iteration order anywhere in the pipeline. K is fixed at
three, matching the concrete worked example fixed during discussion (`[evt:a1b2c3d4e5f6a7b8]
[evt:b2c3d4e5f6a7b8c9][evt:c3d4...]`) — small enough to keep every fact-block line short, large
enough that a curious reader can independently spot-check more than one thread's frames via `sift
show events`.

### D-03 — The block must state in words that it is sampling

Every aggregate line carries a mandatory disclosure sentence naming both the exemplar count and the
aggregate's own true population size, e.g. `(3 of 1,715 thread events cited as exemplars)`
(`_sampling_sentence`, the single definition site every grouping's parenthetical routes through).
Printing three citation tokens beside the figure 1,715 with no such sentence would let a reader —
human or model — assume the population had been enumerated. This wording is treated as load-bearing
honesty, not cosmetic polish: it is the only thing standing between "three real citations" and "an
implied full accounting" for every multi-thousand-thread population this renderer reports.

### D-17 — Union-then-sample-3 for a multi-signature aggregate

A pool, a lock site, or a dependency-wait row can be backed by more than one distinct stack
signature. The chosen rule unions ALL contributing signatures' event-id pools first, then takes the
three lowest ids from that union — never three-per-contributing-signature concatenated. This is the
only rule that keeps D-03's disclosure sentence honest for a multi-signature row: the sentence
states one exemplar count against the aggregate's own total population, and a single
lowest-three-of-the-union satisfies that arithmetic directly, where a per-signature-then-concatenate
strategy would produce up to `3 × signature_count` citations for one summary line while the
disclosure sentence could state only one of those counts. `_union_exemplars` implements this
uniformly across every grouping — role composition, per-pool occupancy, lock-site convergence,
external-wait concentration, the capped signature listing, and Plan 18-03's multi-dump progression
deltas — so a future fifth grouping has one obvious place to plug into, not a second bespoke
sampling routine.

## Rejected alternatives

**Cite the full population.** For the reference capture's own 1,715-thread
`MSIQTask::GetNextPreferredJob` signature this is roughly 31 KB of citation tokens for one summary
line. Rejected on cost alone: fact blocks are spliced into the prompt BEFORE `PromptBudget.fit`
ever runs (`hypothesise.py`'s `_assemble`), so nothing downstream can trim an oversized citation
list — it would simply inflate the prompt unchecked, worsening the exact headroom risk D-14
quantifies.

**Persist each aggregate as its own store row with a synthetic citable id.** Technically closes the
"exists in the case store" requirement, but at the cost of a new store table, a schema migration,
and a second citation kind the citation-gate validator would need to learn to distinguish from a
real ingested event. It also raises a re-ingest hazard: a synthetic aggregate row would need
explicit upsert logic to avoid duplicating on every re-analyse, blurring the ingest-vs-analysis
boundary CLAUDE.md's adapter-owns-events convention protects. Rejected as unnecessary architecture
for a problem D-01/D-02 already solve with existing, already-stored, already-citable rows.

**Lowest-three-per-contributing-signature, concatenated, for a multi-signature aggregate.**
Considered and rejected in favour of D-17's union-then-sample. Produces up to
`3 × signature_count` citation tokens on one summary line, and — more importantly — makes the D-03
disclosure sentence unanswerable: which of the contributing signatures' population figures would
the sentence's "of M" refer to? Union-then-sample-3 sidesteps the question entirely by sampling
from the aggregate's own combined pool.

## Consequences

**Positive.** No change to any frozen Phase 15/16/17 model, no schema migration, no new citation
kind for the citation-gate validator to learn — `render_eustack_facts` is a pure leaf-module
composition of already-exported primitives (`signature_of`, `group_dumps`, the
most-recent-dump-where-present idiom `compute_progression` already established). The mandatory
disclosure sentence gives every aggregate figure in the fourth fact-injection module the same
sampling honesty MCM and perfmon never needed, closing the gap `SaturationFlag`'s own docstring
named as an open question.

**Negative / accepted.** The exemplar-sampling contract is costly to change once golden fixtures
depend on its exact byte shape: the frozen prompt-hash constants in `tests/test_eustack_analyze.py`
(`_NEITHER_PROMPT_HASH`, `_MCM_ONLY_PROMPT_HASH`, `_PERFMON_ONLY_PROMPT_HASH`) and any Phase 19
golden-eval fixtures built against a specific eu-stack block text are pinned to K=3,
lowest-sort-order selection, and the union-then-sample-3 rule exactly as shipped. Changing K, the
selection rule, or the disclosure wording is a breaking change to every fixture built against this
ADR's shape, not a routine tuning knob.

## Cross-references

- ADR 0015 (eu-stack thread-role taxonomy) — the permanent lock-ownership non-goal this phase's
  lock-site convergence lines inherit unchanged: no emitted string in `eustack_facts.py` ever
  attributes lock possession, mirroring ADR 0015's own `unclassified`-is-the-sole-residual and
  ownership-blind discipline.
- ADR 0016 (eu-stack saturation & contention analysis) — the four groupings (role composition,
  per-pool occupancy, lock-site convergence, external-wait concentration) and the `SaturationFlag`
  record this ADR's D-01/D-02/D-03/D-17 citation mechanism resolves an `event_id` set for; ADR
  0016 S-3 is the origin of `SaturationFlag`'s own docstring naming the aggregate-citation gap this
  ADR closes.
