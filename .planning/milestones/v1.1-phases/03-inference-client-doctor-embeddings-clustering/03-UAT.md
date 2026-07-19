---
status: passed
phase: 03-inference-client-doctor-embeddings-clustering
source: [03-VERIFICATION.md]
started: 2026-07-17
updated: 2026-07-17
---

## Current Test

number: 1
name: Live inference-server round-trip (SC1 / LLM-03)
expected: |
  Against a real llama-server (or Lemonade) on a loopback endpoint (default :13305),
  `sift doctor <case>` performs real /v1/models + /v1/embeddings round-trips, reports
  model IDs, checks the embedding dimension against any existing index, warns on
  determinism-breaking server configs, and — on a Lemonade OGA/ONNX-recipe model —
  fails fast with the named "embeddings unsupported; load a llamacpp/flm-recipe model"
  message. `sift analyze <case>` then embeds exemplars, clusters, and produces
  human-readable cluster labels; `sift show clusters <case>` displays them.
awaiting: user response

## Tests

### 1. Live inference-server round-trip (SC1 / LLM-03)
expected: |
  Real endpoint round-trips succeed against a live loopback server; `sift doctor`
  fail-fast ordering + dimension check + determinism warning behave as designed;
  the Lemonade OGA/ONNX case is named explicitly; `sift analyze` + `sift show clusters`
  yield labelled clusters offline (localhost only).
suggested steps (scope to a fresh isolated case dir — do NOT point at a broad shared dir):
  1. Start a llama-server embeddings instance (llamacpp/flm recipe) on a loopback port.
  2. `mkdir -p /tmp/sift-uat-03 && rm -rf /tmp/sift-uat-03/*`; create a small case there.
  3. `uv run sift doctor <case>` — observe real round-trips, model IDs, dim check, warnings.
  4. `uv run pytest -m live` — the opt-in live suite (excluded from the default gate).
  5. `uv run sift analyze <case>` then `uv run sift show clusters <case>` — labelled clusters.
  6. (Optional) Point at a Lemonade OGA/ONNX chat model to confirm the named embeddings-unsupported failure.
result: passed — 2026-07-17, Fedora Strix Halo (AMD Ryzen AI MAX+ 395), Lemonade Server v10.4.0 on :13305 (embeddings=Qwen3-Embedding-0.6B-GGUF/1024-dim, generation=Qwen3-0.6B-GGUF, both llamacpp). `sift doctor`: real /v1/embeddings round-trip dim 1024, vec_version v0.1.9, case dim-vs-index match, all checks passed (exit 0); correctly named the "embeddings unsupported on this model/recipe" failure when no embedding model is loaded. `sift analyze` merged 18 template groups → 3 labelled clusters ("Database Connectivity Error" / "Cache Expired Session" / "Cache Miss"), offline; graceful signature fallback on a nondeterministic no-label run (never crashed). Loopback/RFC1918 refusal confirmed (public endpoint refused without `--i-know-what-im-doing`). Embedding model identity + dim + metric persisted in meta. `pytest -m live` PASSES with `LIVE_EMBEDDING_MODEL` set (test made multi-model-server aware). Note: cluster-label quality is nondeterministic with a 0.6B model — the signature fallback is by design.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
