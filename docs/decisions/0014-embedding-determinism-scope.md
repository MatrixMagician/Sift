# ADR 0014: embedding-stage determinism is scoped to a stable embedding-backend state

**Status:** Accepted
**Date:** 2026-07-25
**Answers:** In what sense do two `analyze` runs over the same case produce the
same `case.db`? Cross-refs SPEC.md §5.7 (reproducibility requirement), ADR
0008 (`sift report`'s determinism scope, which this ADR sits beside and does
not amend), and the settled investigation
`.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`.

**This documents a gap in previously-shipped behaviour, not a change to it.**
The embed-then-cluster path (`pipeline/cluster.py`) is unchanged by this ADR
except for the provenance recording landed alongside it; the gap it describes
has existed since batched embedding requests were introduced (`8818217`).

## Context

Re-running `sift analyze CS1066664` after raising `embeddings.context` from
8192 to 32768 produced **813 clusters (48 labelled)** where the immediately
preceding run had produced **814 clusters (40 labelled)** — same case, same
`case.db`, same embedding model (Qwen3-Embedding-0.6B-GGUF on Lemonade, dim
1024), same code. The case has 1781 template groups. This was settled at the
embed level, without re-running `sift analyze`, via three probes.

**Batch composition changes the vectors, not float noise.** Probe A embedded
each of 24 texts alone (24 requests) versus all together (1 request): 24 of 24
vectors differed, max abs component delta **3.21e-3**. Probe B embedded the
full 1781-text list at `context=8192` (62 requests) versus `context=32768`
(32 requests): 1385 of 1781 vectors differed, max abs component delta
**4.76e-3**. Float32 epsilon is about 1e-7, so this is four orders of
magnitude above numerical noise.

**Severity is confined to the near-duplicate tail.** Measured on L2-normalised
vectors with cosine distance — the same normalisation `cluster.py` applies
before HDBSCAN — perturbation (same text, two layouts) has max 3.19e-4, median
1.33e-4; spacing to the nearest *distinct* exemplar has min **1.76e-4**, 1st
percentile 2.15e-4, median 5.98e-2. Max perturbation over min spacing is 1.82
— the perturbation exceeds the tightest inter-point gap. No point (0 of 200)
is individually swamped, but 8 of 200 (4%) have their nearest-neighbour
*identity* change. HDBSCAN builds mutual reachability from exactly those
neighbour relations, so a 4% neighbour-flip rate is a sufficient mechanism for
the observed ±1 cluster wobble; the bulk structure is untouched, with median
spacing roughly 450 times the median perturbation.

**The trigger is the layout TRANSITION, not the context value.** Steady-state
re-runs are bit-identical: 0 of 200 differ, across four independent pairs. A
differently-batched predecessor request set perturbs the *next* run — 18 of
200 after a singleton-layout run, 14 of 200 after a `context=8192` run —
which then settles back to 0 of 200. Replicated three times, bit-identically.
This retracts an intermediate 15-of-200 reading from earlier in the
investigation, which looked like baseline nondeterminism but did not
replicate and was this same hysteresis, following a singleton-layout probe.

Two structural exposures follow from this. `pipeline/cluster.py` calls
`client.embed(texts)` unconditionally on every `analyze` and re-upserts, with
no reuse of persisted vectors, so every re-run re-embeds and is exposed. And
the endpoint is shared with the generation model, so any differently-shaped
workload between two runs — Sift's own generation calls, or another tool on
the box — can perturb the next embedding pass.

Therefore the invariant as literally written — identical case + config +
model + seed → byte-identical output — **holds in steady state**, but is
conditional on embedding-backend state Sift neither controls nor records.

## Decision

Three parts:

1. **Recorded.** The three batch-layout knobs actually used
   (`embeddings.context`, `embeddings.batch_size`,
   `embeddings.max_input_chars`) are now written to case `meta` as
   `embedding_context`, `embedding_batch_size`, and
   `embedding_max_input_chars` on every `analyze`, so a divergent re-run is at
   least diagnosable against the case.
2. **Scoped.** The determinism claim in CONTRIBUTING.md is qualified to a
   stable embedding-backend state, not asserted absolutely.
3. **Deferred.** Vector reuse — reusing persisted vectors when the template
   set is unchanged, instead of re-embedding on every `analyze` — is the
   structural fix that would close the exposure rather than document it. It
   is deferred to v1.3 (captured separately as SEED-002 / DET-01) and is
   explicitly out of scope here.

## Consequences

- Recording the knobs is **necessary but insufficient**: it cannot capture
  predecessor backend state, which is the actual trigger of the perturbation.
  A recorded knob tells you the layout *this run* used; it cannot tell you
  what the server's prior workload was.
- The knob keys use overwrite semantics deliberately, unlike the
  `embedding_dim` mismatch guard on `record_embedding_identity`: a legitimate
  reconfiguration (bumping `embeddings.context`, say) must never wedge a
  re-analyze.
- ADR 0008 remains correct and unamended: it scopes the report renderer's
  determinism given an identical `case.db`. This ADR covers the upstream
  question of whether two `analyze` runs produce an identical `case.db` in
  the first place — a different layer, not a contradiction.
- The report-determinism test (`tests/test_report_determinism.py`) stays
  valid: it drives the deterministic fake transport (EVAL-05), where no
  backend batching numerics exist, so it exercises the renderer layer this
  ADR does not touch.
