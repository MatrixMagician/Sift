---
seed_id: SEED-002
idea: Reuse persisted embedding vectors instead of re-embedding on every analyze
planted_during: v1.2 (post-milestone, 2026-07-25)
trigger_when: A milestone touches the clustering/embedding pipeline, the determinism invariant, analyze performance, or adds a second embedding consumer
status: open
target: v1.3 (candidate)
---

# SEED-002: Reuse persisted embedding vectors instead of re-embedding every run

## Idea

`pipeline/cluster.py` calls `client.embed(texts)` unconditionally on every
`sift analyze` and re-writes the results with `store.upsert_vectors(...)`. The
vectors are already persisted in `case.db` from the previous run, keyed by
template group. Make the embed step incremental: embed only the exemplars whose
text is not already vectorised, and reuse the stored vectors for the rest.

## Why This Matters

Two independent payoffs, one of them a correctness fix.

**1. It is the only option that closes the determinism exposure rather than
documenting it.** Settled 2026-07-25 (commit `bf00f39`, ADR 0014, and
`.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`):
embedding output depends on the *batch layout* of the request, and on the layout
of *preceding* requests to the same backend. Measured on
Qwen3-Embedding-0.6B-GGUF via Lemonade:

- batch composition changes vectors four orders of magnitude above float32
  epsilon (max component delta 4.8e-3);
- 4% of exemplars get a different nearest neighbour, enough to move HDBSCAN
  output at the near-duplicate margin (the observed ±1 cluster wobble);
- steady-state re-runs are bit-identical, but a differently-batched predecessor
  perturbs the next run — replicated three times, bit-identically.

Sift cannot control that backend state: the endpoint is shared with the
generation model, so any differently shaped workload between two runs can
perturb the next `analyze`. ADR 0014 records the knobs in case `meta` so a
divergence is *diagnosable*, and scopes the claim — but recording provenance is
not the same as being reproducible. If the vectors are read back instead of
regenerated, the exposure disappears for every run after the first, because
there is no second embedding pass to perturb.

**2. It removes the dominant cost of a re-analyze.** On case `CS1066664` that is
1781 exemplars / ~1.45 MB of text per run, re-embedded from scratch every time.
An incremental path makes re-runs after an ingest of a few new files close to
free.

## Sketch

- Key reuse on the exemplar text (or the existing `template_id`), not on row
  order — the template set legitimately grows between runs.
- Embed only the misses; preserve `embed`'s existing order-preservation contract
  when splicing hits and misses back together.
- The `embedding_dim` mismatch guard in `ensure_vectors_table` and the
  `embedding_model` provenance in `record_embedding_identity` already exist and
  must keep working: a change of embedding model or dimension has to invalidate
  reuse, not silently mix vector generations. The knobs ADR 0014 adds to `meta`
  (`embeddings.context` / `batch_size` / `max_input_chars`) are the signal for
  whether a stored vector was produced under a different batch layout — decide
  during planning whether a knob change should invalidate reuse or merely be
  recorded.
- Reuse must be observable: a re-run should report how many vectors were reused
  versus embedded, or the feature is untestable from the outside.

## Open Questions

- Should a changed `embeddings.context` invalidate the cache? Strictly the
  stored vectors are still self-consistent, and *not* invalidating is what makes
  re-runs reproducible — but it means a knob change no longer takes effect until
  a case is rebuilt. This is the central design decision and it is genuinely
  two-sided.
- Does an explicit re-embed escape hatch belong on the CLI (`analyze
  --re-embed`)? Probably yes, for the case where an operator wants the new knob
  to apply.
- Interaction with the citation/prompt-hash invariants: reused vectors must not
  change `prompted_ids` or the no-KB/no-MCM byte-identical prompt guards.

## Provenance

- Investigation and measurements: commit `bf00f39`; full evidence in
  `.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`
- Scoping decision and recorded provenance: ADR 0014
- Related: ADR 0008 (report-renderer determinism scope — deliberately narrower;
  it assumes an identical `case.db`, which is exactly the assumption this seed
  makes true)
