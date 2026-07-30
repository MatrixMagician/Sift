---
id: 2026-07-30-generation-sampling-not-controlled
created: 2026-07-30
source: v1.3 milestone audit (.planning/milestones/v1.3-MILESTONE-AUDIT.md §4)
severity: medium
area: llm-client, config, determinism
requirement_hint: SEED-003 (candidate)
---

# Sift cannot reach its own determinism guarantee: sampling is never controlled

## The claim

`CONTRIBUTING.md:101` — "Identical case, configuration, model, and **seed**
produce byte-identical JSON, modulo timestamps."
`SPEC.md:219` — "identical case + config + model + **seed** (where the server
supports seeding) should produce byte-identical JSON apart from timestamps."

Both make the guarantee conditional on a seed. Neither names who sets it.

## The gap

**Nothing in Sift can set it.** Verified at HEAD:

- `InferenceClient.chat` builds its payload as `{"messages": ...}` plus an
  optional `model` and `response_format`. It sends **no** `seed` and **no**
  `temperature`.
- `GenerationConfig` (`config.py`) has `base_url`, `model`, `timeout`,
  `retries`, `backoff_base`, `context`. There is **no** `seed` or `temperature`
  field, and `extra="forbid"` means an operator cannot even smuggle one in via
  `config.toml`.
- `grep -rn "temperature" src/sift/` matches only the new `doctor` warning.

So reproducibility depends entirely on how the operator happened to load the
model. Sift's own guarantee is unreachable from Sift.

## Why it matters — measured, not hypothetical

Against the operator's Lemonade-managed llama-server (`127.0.0.1:8002`, loaded
with `seed=4294967295` random, `temperature=0.8`), three **identical** prompts
returned three different completions, and `sift eval` scored
`determinism_stability 0.00`, failing the gate along with two downstream
sampling-dependent floors (`hypothesis_hit_at_k`, and a false positive on
`negative-no-incident`).

The same endpoint **does** honour per-request sampling overrides — sending
`{"seed": 42, "temperature": 0}` in the chat body returned byte-identical
content across repeated calls:

```
POST /v1/chat/completions {"seed":42,"temperature":0,...}
  -> "Leaking memory in software applications."
  -> "Leaking memory in software applications."   (identical)
```

So the fix is available at the request level and Sift simply does not use it.

## Proposed change (not made in v1.3 — out of scope)

1. Add `generation.seed: int | None = None` and
   `generation.temperature: float | None = None` to `GenerationConfig`.
2. Include each in the `chat` payload **only when set**, so the no-config
   default stays byte-compatible with today's request shape (the same
   discipline `response_format` and `model` already follow, and the same
   byte-identity guard style used for the triage prompt).
3. Default the eval harness to a fixed seed at temperature 0, so
   `determinism_stability` measures *Sift's* determinism rather than the
   operator's server configuration.
4. Then reconcile the docs: either the guarantee names the new config keys, or
   it is scoped to "given a deterministic endpoint" the way ADR 0014 scoped the
   embedding layer.

Step 3 is the one that changes what the gate means. Today a green
`determinism_stability` proves only that the endpoint happened to be
deterministic during that run.

## Related

- ADR 0014 scoped the **embedding** layer's determinism to a stable backend
  state. This is the same class of exposure one layer over, in **generation**,
  and it is not yet recorded in any ADR.
- ADR 0018 (Phase 20) closed embedding re-embedding for run 2 onward; it
  explicitly does not touch generation sampling.
- `sift doctor` now *reports* a random seed and a non-zero temperature
  (`2281e93`), which is detection. This todo is the control.
