---
type: todo
created: 2026-07-21
area: pipeline
status: pending
---

# Does embedding batch composition perturb clustering? (determinism invariant)

## Observation

Re-running `sift analyze CS1066664` after raising `embeddings.context` 8192 → 32768
produced **813 clusters (48 labelled)** where the immediately preceding run produced
**814 clusters (40 labelled)**. Same case, same case.db, same embedding model, same
code. The only variable was the batch layout: a larger context budget packs more
inputs per `/embeddings` request (`_pack_batches`, added in `8818217`).

## Why this is worth checking

Embeddings should be a pure function of their input, so re-batching the *same* texts
should return the *same* vectors and therefore the same clustering. If batch layout
changes the vectors, it is almost certainly llama.cpp numerics — padding / `n_ubatch`
packing making per-sequence results depend on what else shares the batch.

That collides with a load-bearing project invariant: "identical case + config + model
+ seed → byte-identical JSON (modulo timestamps)". A knob that silently changes
clustering output would make `embeddings.context` a determinism-affecting setting,
which is not how it is currently documented.

## Status: UNCONFIRMED — one observation, no controlled test

Do not treat the above as established. Two other explanations are live and cheaper:
- HDBSCAN instability at the margin (one cluster differing out of ~814 is well within
  what a density-based clusterer can do on near-tied points).
- The label count (40 → 48) is a token-budget artefact downstream of the cluster set,
  not independent evidence.

## How to settle it

Isolate the embedding stage from clustering entirely — do not re-run `sift analyze`:

1. Take the case's exemplar texts (`_exemplar_messages` + `exemplar_text`, as used in
   `pipeline/cluster.py:331-333`).
2. Embed the same list twice via `InferenceClient.embed`, once with a small
   `context` (forcing many small batches) and once with a large one (few big
   batches).
3. Compare the returned vectors elementwise. Identical → batching is clean and the
   cluster delta is HDBSCAN margin noise; different → confirm the magnitude and
   decide whether it is float-noise-tier or genuinely output-changing.

If vectors do differ, the determinism claim in the docs needs qualifying, and
`embeddings.context` should be recorded in the case `meta` alongside the embedding
model and dimension so a re-run is reproducible.
