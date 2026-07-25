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

## Status: CONFIRMED 2026-07-25 — batch layout changes vectors; remedy outstanding

Settled at the embed level as prescribed below, without re-running `sift analyze`.
All figures from case `CS1066664` (1781 template groups — note the 814 above is the
*cluster* count downstream, not the exemplar count), Qwen3-Embedding-0.6B-GGUF on
Lemonade, dim 1024.

### Finding 1 — batch composition changes the vectors (not float noise)

| Probe | Layouts compared | Vectors differing | max abs component delta |
|-------|------------------|-------------------|-------------------------|
| A | each text alone (24 requests) vs all together (1 request) | **24/24** | 3.21e-3 |
| B | full list at `context=8192` (62 requests) vs `32768` (32 requests) | **1385/1781** | 4.76e-3 |

Float32 epsilon is ~1e-7, so this is four orders of magnitude above numerical noise.
In probe A *every* element of *every* vector changed (24576 = 24 x 1024). Both probes
assert the two paths genuinely used different batching, so neither can pass vacuously.

### Finding 2 — severity: the perturbation reaches the near-duplicate tail

Measured on L2-normalised vectors with cosine distance — the same normalisation
`cluster.py` applies before HDBSCAN:

- perturbation (same text, two layouts): max 3.19e-4, median 1.33e-4
- spacing to nearest *distinct* exemplar: min 1.76e-4, 1st percentile 2.15e-4,
  median 5.98e-2
- **max perturbation / min spacing = 1.82** — the perturbation exceeds the tightest
  inter-point gap
- 0/200 points are individually swamped (perturbation >= own NN distance), but
  **8/200 (4%) have their nearest-neighbour *identity* change**

HDBSCAN builds mutual-reachability from exactly those neighbour relations, so a 4% NN
flip rate is a sufficient mechanism for the observed +/-1 cluster wobble. The bulk
structure is untouched (median spacing is ~450x the median perturbation); only the
near-duplicate tail moves. That is why the effect showed up as 1 cluster in ~814
rather than as gross instability.

### Finding 3 — the real trigger is the layout *transition*, not the context value

Steady-state re-runs are bit-identical; a preceding differently-batched request set
perturbs the *next* run, which then settles. Replicated three times, bit-identically:

```
steady-state pair:            0/200 differ
after singleton-layout run:  18/200 differ
after context=8192 run:      14/200 differ
steady-state again:           0/200 differ
```

This explains the original observation without needing HDBSCAN noise: the re-run that
produced 813 was the first run after the `8192 -> 32768` change, i.e. the one with a
different-layout predecessor. It also retracts an intermediate reading of this
investigation — a single 15/200 result that looked like baseline nondeterminism did
not replicate (0/200 on the next three pairs) and was this same hysteresis, following
a singleton-layout probe.

### What this means for the determinism invariant

The invariant as literally written — identical case + config + model + seed ->
byte-identical output — **holds in steady state** (0/200 across four independent
pairs). What is false is the implied assumption that it holds *unconditionally*: it is
conditional on embedding-backend state that Sift neither controls nor records. Two
concrete exposures:

- `pipeline/cluster.py:333` calls `client.embed(texts)` unconditionally on every
  `analyze` and re-`upsert_vectors` — there is no reuse of persisted vectors, so every
  re-run re-embeds and is exposed.
- the Lemonade endpoint is shared with the generation model, so *any* differently
  shaped workload between two `analyze` runs — including Sift's own generation calls,
  or another tool on the box — can perturb the next embedding pass.

### Remedy — NOT yet applied, needs a decision

1. Record `embeddings.context` (and arguably `batch_size` / `max_input_chars`) in the
   case `meta` beside the embedding model and dimension, so a re-run is at least
   *diagnosable*. Necessary but insufficient — it cannot capture predecessor state.
2. Qualify the determinism claim in the docs: byte-identical re-runs require a stable
   embedding-backend state, which Sift cannot guarantee against a shared local server.
3. The substantive fix: make the embed step reuse persisted vectors when the template
   set is unchanged, instead of re-embedding every run. This makes re-runs genuinely
   reproducible *and* faster, and is the only option that closes the exposure rather
   than documenting it. Design change, not a patch — hence a decision, not a todo.

Repro scripts used are throwaway (scratchpad, not committed); the recipe is fully
described above and is ~40 lines against `InferenceClient.embed`.
