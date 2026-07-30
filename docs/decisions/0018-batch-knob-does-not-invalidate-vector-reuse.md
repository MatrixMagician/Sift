# ADR 0018: a batch-knob change does not invalidate embedding vector reuse

**Status:** Accepted
**Date:** 2026-07-30
**Answers:** Now that `analyze` reuses persisted embedding vectors (DET-01 /
SEED-002), which changes invalidate the cache and which do not, and what does
"the same exemplar text" mean? Cross-refs ADR
[0014](0014-embedding-determinism-scope.md) (whose deferral of vector reuse
this ADR closes), ADR [0008](0008-report-determinism-scope.md) (the
report-layer scope, which this ADR sits beside and does not amend), and the
settled investigation
`.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`.

**This records decisions settled during Phase 20 planning.** It does not
reopen them.

## Context

ADR 0014 measured that embedding **batch composition** perturbs vectors far
above float32 noise. Embedding the full 1781-text list at
`embeddings.context` 8192 (62 requests) versus 32768 (32 requests) left 1385
of 1781 vectors different, max absolute component delta **4.76e-3** against a
float32 epsilon of about 1e-7. On L2-normalised vectors under cosine distance —
the same normalisation `pipeline/cluster.py` applies before HDBSCAN —
perturbation reaches max **3.19e-4** and median **1.33e-4**, while spacing to
the nearest *distinct* exemplar has a minimum of **1.76e-4**. No point is
individually swamped, but 8 of 200 exemplars (**4%**) change
nearest-neighbour identity, which is a sufficient mechanism for the observed
±1 cluster wobble. Crucially, the trigger is the batch-layout **transition**,
not the context value: steady-state re-runs are bit-identical, and it is a
differently-batched predecessor request set that perturbs the next run.

ADR 0014 responded by recording the three knobs actually used
(`embeddings.context`, `embeddings.batch_size`, `embeddings.max_input_chars`)
in case `meta` with deliberate overwrite semantics, and by **deferring** vector
reuse to v1.3 as the structural fix. Phase 20 implements that reuse: a second
`analyze` on an unchanged case now performs no embedding call at all.

That immediately raises the question this ADR settles. The knobs are recorded
in the case. Does changing one invalidate the stored vectors?

## Decision

Three parts, all settled.

1. **A batch-knob change does NOT invalidate reuse.** `embeddings.context`,
   `embeddings.batch_size` and `embeddings.max_input_chars` are provenance,
   never a cache guard. `record_embedding_batch_knobs` remains an
   unconditional overwrite with no read, no comparison and no raise.

   Not invalidating is precisely what makes a re-run reproducible.
   Invalidating would re-embed under a *new* batch layout on the first run
   after any reconfiguration — which is exactly the layout transition ADR 0014
   identified as the trigger — reopening the hysteresis that reuse exists to
   eliminate. `sift analyze --re-embed` is the explicit operator escape hatch
   for applying a knob change when that is genuinely wanted.

2. **A model or dimension change DOES invalidate.** A *proven* embedding-model
   change — both `meta.embedding_model` and the client's resolved model known
   and differing — discards the whole reuse map and re-embeds every exemplar,
   silently, because no operator action is required and the
   `Embeddings: N new, 0 reused` line already makes the re-embed visible.

   A dimension change keeps the shipped STORE-03 hard error: `analyze` raises
   `embedding dimension mismatch` naming both dimensions, and nothing is
   dropped. `sift analyze --re-embed` is the recovery path, dropping and
   rebuilding the `vectors` and `kb_vectors` tables together at the new width,
   inside the one transaction that owns every write, having first announced the
   blast radius.

   When model identity is unknown on **either** side — no
   `meta.embedding_model`, or an endpoint and configuration that name no
   embedding model — reuse **proceeds**, with a stderr warning stating that
   vectors were reused without a verifiable model identity. Treating unknown as
   changed would permanently disable the feature against any endpoint that
   does not name its embedding model, which includes the reference Lemonade
   deployment; it would make the feature appear to work while silently never
   firing. Disclosure is the mitigation, not invalidation.

3. **The reuse key is exemplar text under exact equality.** A stored vector is
   located by `chunks JOIN vectors USING (chunk_id)` keyed on `chunks.text`,
   with **no Unicode normalisation, no case folding, no trimming and no
   `COLLATE` clause** — exact code-point equality over the decoded text, which
   for a UTF-8 round trip is byte equality. Canonically equivalent but not
   code-point-identical text (NFC versus NFD) misses the cache and is
   re-embedded.

   The asymmetry is deliberate. A miss costs one embedding call. A normalising
   match could return a vector computed from different bytes than the text
   being clustered, which is silent mis-attribution of evidence — the same
   failure mode for which `template_id` was rejected as the key, since
   `exemplar_event_ids[0]` can change after a re-ingest and so the message
   behind a given `template_id` can change while the id stays fixed.

   Two further consequences of keying on text. Byte-identical exemplar text
   appearing under two template groups is embedded **once** and the single
   vector fans out to both positions; without that deduplication, run 1 would
   embed the same text twice into two independently batched vectors differing
   by up to the measured 4.8e-3, while run 2 would fan one cached vector out to
   both — a self-inflicted disagreement between run 1 and run 2. And when the
   stored `chunks` table holds two rows with byte-identical `text`, the read is
   explicitly `ORDER BY chunks.chunk_id`, so the highest `chunk_id` wins
   deterministically rather than the winner depending on unspecified SQLite row
   order.

## Consequences

- **What reuse closes.** ADR 0014's batch-composition exposure is closed for
  **run 2 onward**: there is no second embedding pass to perturb, so a
  re-analysis of an unchanged case reproduces the previous run's vectors
  exactly rather than re-deriving them under whatever layout the endpoint is
  in.
- **What it does not close.** The **first run** of a case is still embedded
  under whatever state the shared endpoint happens to be in, and recording
  predecessor backend state remains explicitly **out of scope** — ADR 0014
  already noted that recording the knobs is necessary but insufficient,
  because a recorded knob describes this run's layout and cannot describe the
  server's prior workload. The determinism claim must therefore stay
  conditional; a document asserting that re-analysis is deterministic full
  stop would be overclaiming.
- **ADR 0008 is unamended.** Its report-layer scope ("given an identical
  `case.db`") is untouched. Reuse makes that assumption *true upstream* more
  often; it does not widen 0008, and the two layers must not be conflated.
- **KB vector reuse is not implemented.** `index_kb` still re-embeds every
  chunk on every `--kb` run, and a dimension rebuild drops `kb_vectors` and
  `kb_chunks` together so the KB regenerates at the new width on the next
  `--kb` run.
- **The byte-identity guarantee is asserted only under the fake transport.**
  `tests/test_cluster.py::test_reuse_mixed_hit_miss_matches_full_reembed`
  proves a mixed hit/miss run matches a full re-embed under
  `httpx.MockTransport`. No live-backend equivalent exists or should be
  written: against a real backend a full re-embed is precisely what perturbs
  the vectors, so a live byte-identity test would assert the opposite of ADR
  0014's measured finding.
