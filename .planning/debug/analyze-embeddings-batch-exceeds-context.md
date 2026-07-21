---
status: resolved
trigger: "sift analyze CS1066664 → 'embedding/clustering failed: embeddings response has no data list (server: llama-server request failed); an input may exceed the model's context window — lower embeddings.max_input_chars (currently 8000)'"
created: 2026-07-21
updated: 2026-07-21
---

# Debug: embeddings batch aggregate exceeds the model context

## Current Focus
- hypothesis: RESOLVED — the failure was the **batch aggregate**, not any single input.
  `InferenceClient.embed` chunked by COUNT (64) with no awareness of input size, so
  one request could carry far more tokens than the embedding model's context window.
- next_action: none (fixed, gate green, real repro succeeds).

## Root cause

`client.embed` (`src/sift/llm/client.py:282`) slices inputs with a fixed stride:

```python
for start in range(0, len(inputs), self._batch_size):        # batch_size = 64
    batch = [text[: self._max_input_chars] for text in inputs[start : start + 64]]
```

`max_input_chars` bounds each input (8000) but **nothing bounds their sum**. A single
request can therefore carry 64 × 8000 = 512,000 chars. The loaded embedding model has
`n_ctx = 8192`.

The error message compounds it: it blames per-input size and tells the operator to lower
`max_input_chars`. For this case that is the wrong lever — the median input is 323 chars.

## Evidence (all measured against the live server, not inferred)

Server state: Lemonade 10.4.0, `Qwen3-Embedding-0.6B-GGUF`, llamacpp recipe, gpu.
Config is correct (GGUF embeddings model, not ONNX/OGA).

**Loaded context is 8192**, from the server's own rejection of a single 32,000-char input:
`request (16002 tokens) exceeds the available context size (8192 tokens)`, `n_ctx: 8192`.

**Real chars-per-token for this data: 1.94** — measured by forcing a rejection with 60,000
chars of the case's own exemplar text and reading `n_prompt_tokens = 30923`. Log text
(GUIDs, hex, paths, timestamps) tokenises at ~2 chars/token, NOT the ~4 the codebase's
`len//4` heuristic assumes. This is the number that makes the batches over-budget.

**The real case is over budget from the first request.** 1781 embed inputs, median 323
chars, 39 at the 8000 cap:

| batch | inputs | chars | ≈ tokens @1.94 | n_ctx |
|-------|--------|-------|----------------|-------|
| @0    | 64     | 24700 | ~12700         | 8192  |
| @64   | 64     | 19378 | ~9900          | 8192  |
| @128  | 64     | 29710 | ~15300         | 8192  |

**Batch-size probe** (deterministic, identical across two runs) with 8000-char inputs:

| n inputs | result |
|----------|--------|
| 1, 2, 3, 4 | OK |
| 8        | REJECT `Context size has been exceeded.` |
| 16       | OK  ← non-monotonic |
| 32, 64   | REJECT |

The n=16 anomaly is a llama.cpp batch-scheduling artefact and is reproducible; it does not
change the conclusion, but it does mean "it worked once at size N" is not evidence that N
is safe. The safe rule is the one the server states explicitly: keep a request's total
tokens inside `n_ctx`.

Why the 200-with-error shape hides it: Lemonade wraps llama-server's 500 in HTTP 200 with
`{"error": {"message": "llama-server request failed"}}` — the generic wrapper, unlike the
single-input case which surfaces the explicit token count. Same 200-with-error quirk
already handled for chat in the previous session.

## Fix (planned)
1. `config.py`: `embeddings.context` + `SIFT_EMBEDDINGS_CONTEXT`, mirroring the
   `generation.context` knob added in the previous debug session.
2. `llm/client.py`: pack each request up to a token budget (conservative 2 chars/token,
   matching the measured 1.94) AND the existing count cap, whichever binds first.
3. `llm/client.py`: reword `_embed_reject_message` — lead with the batch aggregate, since
   that is the usual cause; keep `max_input_chars` as the secondary lever.

## Not the cause (ruled out)
- Wrong embeddings recipe (ONNX/OGA) — the loaded model is llamacpp, and small batches embed fine.
- Server down / endpoint unhealthy — n=1 and n=64×100-char both return 200 with vectors.
- A single oversized input — `max_input_chars` already caps at 8000 ≈ 4100 tokens, which fits 8192.

## Verification
- ruff clean, pyright 0 errors, pytest 672 passed (670 before; +2).
- **Real repro fixed**: `sift analyze CS1066664` now completes — `Clusters: 814
  (40 labelled) / Hypotheses: 1`, exit 0, where it previously aborted at embed.
- Counterfactual: forcing `over_budget = False` (count-only batching, i.e. the old
  behaviour) fails both new tests on their behavioural assertions — "a 8000-char
  workload must not go out as one request" and "the oversized input must travel on
  its own" — not merely on the new kwarg. Restored and re-verified green.
