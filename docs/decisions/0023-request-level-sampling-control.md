# ADR 0023: sampling is controlled per request, not left to the loaded model

**Status:** Accepted
**Date:** 2026-08-26
**Answers:** Sift's determinism guarantee names a seed. Who sets it? Cross-refs
ADR [0014](0014-embedding-determinism-scope.md) (the same class of exposure one
layer down, in embedding), ADR
[0008](0008-report-determinism-scope.md) (the report-layer determinism scope),
ADR [0020](0020-doctor-props-interpretation.md) (the `/props` warnings this
amends), and the v1.3 audit todo
`.planning/todos/pending/2026-07-30-generation-sampling-not-controlled.md`,
which this closes.

## Context

Two documents made the same conditional promise:

- `CONTRIBUTING.md`: "Identical case, configuration, model, and **seed**
  produce byte-identical JSON, modulo timestamps."
- `SPEC.md` §7: "identical case + config + model + **seed** (where the server
  supports seeding) should produce byte-identical JSON apart from timestamps."

Neither named who sets the seed, and at v1.3 nothing in Sift could.
`InferenceClient.chat` built its payload as `{"messages": ...}` plus an optional
`model` and `response_format` — no `seed`, no `temperature`. `GenerationConfig`
had no field for either, and `extra="forbid"` meant an operator could not even
smuggle one in through `config.toml`.

Reproducibility therefore depended entirely on how the operator happened to load
the model, and the v1.3 milestone audit measured the consequence. Against a
Lemonade-managed llama-server (`127.0.0.1:8002`, loaded with `seed=4294967295`
random, `temperature=0.8`), three **identical** prompts returned three different
completions, and `sift eval` scored `determinism_stability 0.00` — failing the
gate, along with `hypothesis_hit_at_k` and a false positive on
`negative-no-incident`. Nothing was wrong in Sift. The gate was measuring the
endpoint.

The same endpoint honoured per-request overrides: sending
`{"seed": 42, "temperature": 0}` in the chat body returned byte-identical
content across repeated calls. The fix was available at the request level and
Sift simply did not use it.

## Decision

Four parts.

**1. `generation.seed` and `generation.temperature` exist, and travel per
request.** Both are `int | None` / `float | None`, both default to `None`, and
each is added to the chat payload only when set — the same discipline `model`
and `response_format` already follow. A negative temperature is rejected at
config time rather than passed through to fail mid-analyse, after the embedding
work is already done.

**2. Unset stays unset, and that is the compatibility guarantee.** With neither
configured, the request body is byte-identical to the pre-ADR shape. This is not
only about not breaking anyone: an operator who deliberately loaded their model
with a particular sampling policy must not have it silently overridden by a
tool they pointed at it. Opting in is an act.

**3. `sift eval` defaults to `seed = 42`, `temperature = 0.0`.** This is the
part that changes what the gate *means*. Before it, a green
`determinism_stability` proved only that the endpoint happened to be
deterministic during that run. The default is applied per field and only where
the operator configured nothing (`model_fields_set` distinguishes "not
configured" from "configured to `None`"), so someone deliberately evaluating
their own sampling policy still can, and the flags > env > toml > defaults chain
is not inverted by the harness. The seed value is arbitrary; it only has to be
constant.

**4. `sift doctor` withholds a warning it no longer needs to give.** ADR 0020's
random-seed and non-zero-temperature warnings are correct only while Sift sends
neither knob. Once the corresponding config key is set, Sift overrides the
server on every request and the warning is false — and a warning about a
controlled risk is how operators learn to ignore warnings. The suppression is
per knob, and it does **not** extend to the multi-slot `n_parallel` warning:
slot scheduling is not something a request body can control, so that risk is
still real and still reported.

## Consequences

Sift's documented determinism guarantee is now reachable from Sift, and
`docs/CONFIGURATION.md` names the two keys that reach it rather than leaving the
guarantee conditional on an unnamed actor.

The guarantee remains scoped by the layer below. ADR 0014 established that
embedding batch composition perturbs vectors well above float32 noise, and that
Sift neither controls nor can fully record the backend state that produces them.
This ADR closes the **generation** exposure; it does not close, weaken or amend
that embedding one. A pinned seed does not make a re-embedded case identical to
its predecessor.

The default is still non-deterministic for anyone who does not opt in. That is
deliberate (decision 2), and `sift doctor` is what tells them: with no seed
configured, the random-server-seed warning fires exactly as before, and now
names `generation.seed` as one of the two ways to fix it.

## Alternatives considered

**Send `seed` and `temperature` always, with deterministic defaults.** Rejected:
it silently overrides a deliberately-configured server, changes the request
shape for every existing user, and makes Sift's opinion about sampling
unavoidable rather than available.

**Scope the guarantee down instead — "given a deterministic endpoint" — the way
ADR 0014 scoped embedding.** Rejected on the asymmetry that made 0014's scoping
honest: there, Sift genuinely cannot control the backend's batch behaviour.
Here it can, with two optional keys in a request body already being assembled.
Documenting an unreachable guarantee away is only correct when the guarantee is
genuinely unreachable.
