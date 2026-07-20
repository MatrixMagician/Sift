---
status: resolved
trigger: "sift analyze Quipux failed: 'Clusters: 23 (0 labelled) / Error: hypothesis generation failed; the inference endpoint returned a transport error and no hypotheses were persisted'"
created: 2026-07-20
updated: 2026-07-20
---

# Debug: analyze "transport error" was actually a context overflow

## Current Focus
- hypothesis: RESOLVED — the "transport error" message was misleading; the real cause is a generation-context overflow.
- next_action: none (fixed, gate green, real repro confirms honest message)

## Root cause
The `user.Qwen2.5-14B-Instruct` generation model is loaded in Lemonade with only
`n_ctx = 4096`. Sift's triage prompt (~4867 tokens; per-cluster labels ~4416)
exceeds it. llama-server rejects with HTTP 400, but **Lemonade wraps it and
returns HTTP 200** with a nested `{"error": ... "exceed_context_size_error" ...}`
body (the same 200-with-error quirk already handled for `/embeddings`).

Failure chain:
1. `client.chat` saw HTTP 200 → `raise_for_status()` passed → no `choices` →
   raised generic `ValueError("chat response has no choices")`.
2. `hypothesise` caught it in `except (httpx.HTTPError, ValueError)` → `failed=True`.
3. `cli.py` printed a hardcoded **"transport error"** for any failure. Same cause
   silently produced **0 labelled** (label chats hit the same overflow, degraded).

Why the budget didn't prevent it: Lemonade doesn't serve llama.cpp `/props`
(returns web-UI HTML), so `_ctx_tokens` fell back to `ctx_fallback=8192` — double
the real 4096 ceiling — and `PromptBudget.fit` never trimmed.

## Evidence
- Raw 200 body: `request (4867 tokens) exceeds the available context size (4096 tokens), try increasing it` (`n_ctx: 4096`).
- Standalone `hypothesise()` on the same store SUCCEEDS when the prompt fits (8-cluster ~1850-token prompt) → pipeline healthy; it is purely a context ceiling.
- `curl` chat to the 14B with a small prompt: 200 in 0.18s → endpoint healthy.

## Fix (applied)
- `llm/client.py`: `_chat_reject_message` detects the 200 + `{"error":...}` chat
  body (mirrors `_embed_reject_message`) → actionable ValueError with the server's
  real message.
- `pipeline/hypothesise.py`: `Outcome.error` carries the real failure reason.
- `cli.py`: prints the real reason instead of "transport error"; wires
  `generation.context` into the budget fallback.
- `config.py`: new `generation.context` knob + `SIFT_GENERATION_CONTEXT` env, so
  Lemonade users (no `/props`) can align the token budget with their real n_ctx.

## Operator unblock (environment, not code)
Load the generation model with a larger context (>= ~8192; the 14B supports
32768), then re-run `sift analyze Quipux`.

## Verification
- ruff clean, pyright 0 errors, `pytest` 661 passed.
- New tests: chat surfaces the overflow message; `Outcome.error` populated;
  `SIFT_GENERATION_CONTEXT` coerced. Counterfactual: `PromptBudget` trims to the
  ctx value (3040 chars @1024 vs 25100 @32768).
- Real repro now prints: `hypothesis generation failed (chat completion rejected
  by server: request (4416 tokens) exceeds the available context size (4096
  tokens), try increasing it); no hypotheses were persisted`.
