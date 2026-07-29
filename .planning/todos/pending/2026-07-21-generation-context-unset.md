---
type: todo
created: 2026-07-21
area: llm
status: pending
---

# `generation.context` is unset, so the prompt budget uses a fallback, not the real n_ctx

## Problem

`~/.config/sift/config.toml` sets `embeddings.context = 32768` (added 2026-07-21) but
has no `generation.context`, so `load_config().generation.context` is `None` and
`PromptBudget` falls back to the built-in default instead of the generation model's
actual loaded window.

This is the exact gap the 2026-07-20 debug session
(`.planning/debug/analyze-transport-error-context-overflow.md`) added the knob for:
Lemonade does not serve llama.cpp's `/props` (it returns web-UI HTML), so Sift cannot
discover the loaded `n_ctx` and the budget never trims to fit. That session's operator
note — "load the generation model with a larger context, then re-run" — was followed,
but the matching Sift-side knob was never set.

## Why it matters now

`sift analyze CS1066664` on 2026-07-21 finished **degraded**: `Clusters: 813 (48
labelled) / Hypotheses: 0 (degraded)`, exit 3 — the citation gate rejected the model's
output. The immediately preceding run produced `Hypotheses: 1`, exit 0.

**Not yet attributed.** The degradation is at the generation stage, which the
embeddings-context change does not touch, so the likelier explanation is a marginal
14B producing invalid citations on a slightly different prompt (48 labelled clusters
vs 40) rather than a regression. One hypothesis out of 814 clusters was not a healthy
baseline either. Do not assume causation without checking.

## Next steps

1. Read the generation model's real loaded window (`user.Qwen2.5-14B-Instruct`,
   bartowski/Qwen2.5-14B-Instruct-GGUF:Q4_K_M) — Lemonade's `/v1/models` reports
   `max_context_window`, which is the model max, NOT the loaded `n_ctx`. The reliable
   probe is the same one used for embeddings: send one oversized single input and read
   `n_ctx` back from the rejection body (batch rejections are collapsed to a generic
   "llama-server request failed").
2. Set `generation.context` in `~/.config/sift/config.toml` to that value, and reload
   the model with a matching `--ctx-size ... --save-options` if it is still small.
3. Re-run `sift analyze CS1066664` and check whether the degradation clears. If it does
   not, the cause is model capability, not budget — worth recording either way, since
   "1 hypothesis from 814 clusters" is weak regardless.
