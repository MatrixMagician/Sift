---
type: quick
created: 2026-07-25
quick_id: 260725-cxs
slug: record-embedding-batch-knobs-in-case-meta
autonomous: true
files_modified:
  - src/sift/llm/client.py
  - src/sift/store.py
  - src/sift/pipeline/cluster.py
  - tests/test_llm_client.py
  - tests/test_store_vectors.py
  - tests/test_cluster.py
  - CONTRIBUTING.md
  - docs/ARCHITECTURE.md
  - docs/decisions/0014-embedding-determinism-scope.md

must_haves:
  truths:
    - Every `analyze` records the three embedding batch-layout knobs actually used, in case `meta`.
    - Re-analysing the same case with different knob values overwrites the recorded values and never raises.
    - The knobs are recorded even when no embedding model identity is known (the D-03 model-is-None path).
    - The determinism invariant in CONTRIBUTING.md is qualified, not absolute, and points at both ADRs.
  artifacts:
    - docs/decisions/0014-embedding-determinism-scope.md
    - Read-only knob properties on `InferenceClient`
    - A store method recording the knobs via the `set_meta` idiom
  key_links:
    - cluster.py reads the knobs FROM the client instance (never by re-reading config), inside the same `store.transaction()` as the other provenance writes.
---

# Quick: record embedding batch knobs in case meta, and qualify the determinism claim

## Problem

Commit `bf00f39` settled the investigation in
`.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`:
embedding batch *layout* perturbs the vectors far above float32 noise, so two `analyze`
runs over the same case may not produce an identical `case.db`. Two consequences are
outstanding.

1. **Nothing is recorded.** `case.db` `meta` holds `embedding_model` and `embedding_dim`
   but not the three knobs that determine batch layout (`embeddings.context`,
   `embeddings.batch_size`, `embeddings.max_input_chars`). A divergent re-run is
   currently undiagnosable — you cannot tell whether the layout changed between runs.
2. **The docs overclaim.** `CONTRIBUTING.md` (~line 102) asserts determinism
   unconditionally. ADR 0008 deliberately scopes its guarantee to the *report renderer*
   given an identical `case.db`; the embedding stage is an undocumented gap upstream of
   that, so a new ADR is the right shape, not an edit to 0008.

Recording the knobs is necessary but insufficient — it cannot capture predecessor
backend state. That is understood and must be said out loud in the ADR.

## Out of scope

- **Vector reuse** (reusing persisted vectors when the template set is unchanged). This
  is the substantive fix and is deliberately deferred to v1.3, captured separately. Do
  not plan, implement, or scaffold it here.
- Surfacing the knobs in the rendered report (`render/json_out.py`, `render/markdown.py`).
  `meta` is enough for diagnosability.
- Any change to `record_embedding_identity`'s existing dim-mismatch semantics.

<context>
@.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md
@docs/decisions/0008-report-determinism-scope.md
@src/sift/llm/client.py
@src/sift/store.py
@src/sift/pipeline/cluster.py
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: record the batch-layout knobs actually used, as case meta provenance</name>
  <files>src/sift/llm/client.py, src/sift/store.py, src/sift/pipeline/cluster.py, tests/test_llm_client.py, tests/test_store_vectors.py, tests/test_cluster.py</files>
  <read_first>
    - `src/sift/llm/client.py` lines 243-273 (`InferenceClient.__init__`, where `_batch_size` / `_max_input_chars` / `_context` are clamped with `max(1, ...)`) and 365-373 (the `embedding_model` property — the idiom to mirror).
    - `src/sift/store.py` lines 798-814 (`record_embedding_identity`) and 1066-1080 (`get_meta` / `set_meta`).
    - `src/sift/pipeline/cluster.py` lines 373-392 (the `store.transaction()` block; note `record_embedding_identity` is called only when `client.embedding_model is not None`, per D-03).
    - `tests/test_store_vectors.py` lines 159-170 (`test_record_embedding_identity_guards_dim`) and `tests/test_cluster.py` lines 76-104 (`_embed_handler` / `_client` — the `httpx.MockTransport` fake; no socket ever opens) plus lines 234-249 for the meta-assertion style.
    - `tests/test_llm_client.py` lines 271-298 for the property-test style.
  </read_first>
  <behavior>
    Write these as failing tests FIRST, then implement.

    `tests/test_llm_client.py`:
    - The three new read-only properties return the values the constructor was given.
    - They return the *clamped* value, not the raw argument: constructing with a zero or
      negative knob yields 1, matching the existing `max(1, ...)` normalisation. This is
      the assertion that pins "what is recorded is what was actually used".

    `tests/test_store_vectors.py`:
    - The new store method writes all three keys, readable via `get_meta`.
    - Calling it a second time with different values OVERWRITES all three and raises
      nothing. This is the anti-regression for the deliberate divergence from
      `record_embedding_identity`: these knobs legitimately change between runs, so a
      changed value must never wedge a re-analyze.

    `tests/test_cluster.py`:
    - After `cluster_and_label` with a client built with non-default knobs, the three
      meta keys equal those knob values.
    - The existing `_client` helper yields `embedding_model is None` (the fake returns no
      `model` field and the `Endpoint` model is `None`), so this test simultaneously
      proves the knobs are recorded on the path where `record_embedding_identity` is
      skipped. Assert that explicitly — `get_meta("embedding_model") is None` while the
      knob keys are populated.
  </behavior>
  <action>
    Three changes, smallest diff that holds.

    1. `InferenceClient`: expose `_context`, `_batch_size` and `_max_input_chars` as three
    read-only properties named `embedding_context`, `embedding_batch_size` and
    `embedding_max_input_chars`. Mirror the `embedding_model` property idiom exactly —
    `@property`, a one-line return of the private attribute, a short docstring saying
    these are the batch-layout knobs recorded as case provenance. Return the clamped
    private attributes, never the raw constructor arguments. Do not change the
    constructor signature, so no call site anywhere needs touching.

    2. `store.py`: add `record_embedding_batch_knobs` next to `record_embedding_identity`,
    taking the three ints as keyword-only arguments and writing them with `set_meta`
    under the keys `embedding_context`, `embedding_batch_size` and
    `embedding_max_input_chars` — prefix-consistent with the sibling `embedding_dim` /
    `embedding_metric` / `embedding_model` keys. Plain unconditional overwrite: no
    `get_meta` read, no comparison, no raise. Its docstring must state why it
    deliberately does NOT mirror `record_embedding_identity`'s mismatch guard — a knob
    change is a legitimate reconfiguration, and hard-failing on one would make a
    re-analyze impossible after any config tweak. Cite the settled investigation
    (`.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`) and
    ADR 0014 as the reason the keys exist at all: batch layout perturbs the vectors, so
    the layout must be recoverable from the case.

    3. `cluster.py`: inside the existing `store.transaction()` block, next to the
    `record_embedding_identity` call, invoke the new store method with the three values
    read from the `client` instance's new properties. Two constraints, both load-bearing:
    read from the client, never by re-reading config at the call site, so what is
    recorded is what the embed pass actually used; and call it UNCONDITIONALLY — outside
    the `if model is not None` guard — because the knobs are known even when the model
    identity is not.

    No new dependency, no config change, no CLI surface.
  </action>
  <verify>
    <automated>cd /home/oliverh/repos/github/MatrixMagician/Sift &amp;&amp; uv run pytest tests/test_llm_client.py tests/test_store_vectors.py tests/test_cluster.py -q &amp;&amp; uv run ruff check &amp;&amp; uv run pyright &amp;&amp; uv run pytest -q</automated>
  </verify>
  <done>
    All three knobs are readable off `InferenceClient` and land in `case.db` `meta` on
    every `analyze`, including when the embedding model identity is unknown; a second
    call with different values overwrites without raising; `uv run ruff check`,
    `uv run pyright` and `uv run pytest` are all clean. One atomic commit.
  </done>
</task>

<task type="auto">
  <name>Task 2: qualify the determinism claim and record ADR 0014</name>
  <files>CONTRIBUTING.md, docs/ARCHITECTURE.md, docs/decisions/0014-embedding-determinism-scope.md</files>
  <read_first>
    - `docs/decisions/0008-report-determinism-scope.md` in full (the ADR this one sits beside and must not contradict).
    - `docs/decisions/0013-dsserrors-qualified-mcm-sniff.md` lines 1-20 for the current house header style (`# ADR NNNN: <lowercase claim>`, then `**Status:**` / `**Date:**` / `**Answers:**`, then `## Context` / `## Decision` / `## Consequences`).
    - `CONTRIBUTING.md` around line 102 — the `- **Determinism.**` bullet in the "Invariants a change must not break" list.
    - `docs/ARCHITECTURE.md` line ~142 — the `Run-level state lives in meta:` sentence enumerating the meta keys.
  </read_first>
  <action>
    Docs only, British English throughout. No code, no test changes.

    (a) `CONTRIBUTING.md`: rewrite the `- **Determinism.**` bullet so the byte-identical
    claim is conditional rather than absolute. Keep the `event_id` / idempotent
    re-ingestion sentence as-is (it is unaffected and true). Qualify the second sentence:
    the guarantee holds given a stable embedding-backend state, because embedding batch
    layout perturbs the vectors and Sift neither controls nor can fully record that
    backend state. Cross-reference both ADRs by number, naming what each covers — 0008
    the report renderer given an identical `case.db`, 0014 the embedding stage upstream
    of it. Keep it to a bullet; the detail belongs in the ADR.

    (b) Create `docs/decisions/0014-embedding-determinism-scope.md`, matching 0013's
    header block and section order. `**Status:** Accepted`, `**Date:** 2026-07-25`,
    `**Answers:**` a question about the sense in which two `analyze` runs over the same
    case produce the same `case.db`, cross-referring SPEC.md §5.7, ADR 0008, and the
    settled todo. Note in the header block that this documents a gap in previously-shipped
    behaviour rather than a change to it.

    `## Context` must record these MEASURED findings verbatim — figures are from the todo
    file, do not invent, re-round, or approximate any of them. Case `CS1066664`, 1781
    template groups, Qwen3-Embedding-0.6B-GGUF on Lemonade, dim 1024. Original
    observation: 814 clusters (40 labelled) became 813 clusters (48 labelled) on the
    re-run after `embeddings.context` was raised 8192 to 32768, same case.db, same model,
    same code.

    - Batch composition changes the vectors, not float noise. Probe A: each text alone
      (24 requests) versus all together (1 request) differed in 24 of 24 vectors, max abs
      component delta 3.21e-3. Probe B: the full list at `context` 8192 (62 requests)
      versus 32768 (32 requests) differed in 1385 of 1781 vectors, max abs component
      delta 4.76e-3. Float32 epsilon is about 1e-7, so this is four orders of magnitude
      above numerical noise.
    - Severity is confined to the near-duplicate tail. Measured on L2-normalised vectors
      with cosine distance, the same normalisation `cluster.py` applies before HDBSCAN:
      perturbation max 3.19e-4, median 1.33e-4; spacing to the nearest *distinct*
      exemplar min 1.76e-4, 1st percentile 2.15e-4, median 5.98e-2; max perturbation over
      min spacing is 1.82. No point (0 of 200) is individually swamped, but 8 of 200 (4%)
      have their nearest-neighbour *identity* change. HDBSCAN builds mutual reachability
      from exactly those neighbour relations, so a 4% neighbour-flip rate is a sufficient
      mechanism for the plus-or-minus-one cluster wobble observed; the bulk structure is
      untouched, with median spacing roughly 450 times the median perturbation.
    - The trigger is the layout TRANSITION, not the context value. Steady-state re-runs
      are bit-identical: 0 of 200 differ, across four independent pairs. A
      differently-batched predecessor request set perturbs the next run — 18 of 200 after
      a singleton-layout run, 14 of 200 after a `context` 8192 run — which then settles
      back to 0 of 200. Replicated three times, bit-identically. Record that this retracts
      an intermediate 15-of-200 reading which looked like baseline nondeterminism but did
      not replicate and was this same hysteresis.
    - Two structural exposures: `pipeline/cluster.py` calls `client.embed(texts)`
      unconditionally on every `analyze` and re-upserts, with no reuse of persisted
      vectors, so every re-run re-embeds and is exposed; and the endpoint is shared with
      the generation model, so any differently shaped workload between two runs — Sift's
      own generation calls, or another tool on the box — can perturb the next embedding
      pass.
    - Therefore the invariant as literally written holds in steady state, but is
      conditional on embedding-backend state Sift neither controls nor records.

    `## Decision`: state all three parts. The three batch-layout knobs are now recorded
    in case `meta` (`embedding_context`, `embedding_batch_size`,
    `embedding_max_input_chars`) so a divergent re-run is at least diagnosable. The
    determinism claim is scoped to a stable embedding-backend state, not asserted
    absolutely. Vector reuse — reusing persisted vectors when the template set is
    unchanged — is the structural fix that would close the exposure rather than document
    it, and is deferred to v1.3, captured separately; do not restate it as anything other
    than deferred.

    `## Consequences` must be honest about the limits: recording the knobs is necessary
    but insufficient, since it cannot capture predecessor backend state, which is the
    actual trigger; the knob keys use overwrite semantics deliberately, unlike the
    `embedding_dim` mismatch guard, so a legitimate reconfiguration can never wedge a
    re-analyze; ADR 0008 remains correct and unamended, because it scopes the renderer
    given an identical `case.db` and this ADR covers the upstream question of whether two
    runs produce an identical `case.db` in the first place; and the report-determinism
    test stays valid because it drives the deterministic fake transport, where no backend
    batching exists.

    (c) `docs/ARCHITECTURE.md`: add the three new keys to the `Run-level state lives in
    meta:` enumeration so the documented key list does not go stale. One-line edit.
  </action>
  <verify>
    <automated>cd /home/oliverh/repos/github/MatrixMagician/Sift &amp;&amp; test -f docs/decisions/0014-embedding-determinism-scope.md &amp;&amp; grep -c '0014' CONTRIBUTING.md &amp;&amp; grep -c '0008' docs/decisions/0014-embedding-determinism-scope.md &amp;&amp; grep -c '3\.21e-3' docs/decisions/0014-embedding-determinism-scope.md &amp;&amp; grep -c '4\.76e-3' docs/decisions/0014-embedding-determinism-scope.md &amp;&amp; grep -c '1\.76e-4' docs/decisions/0014-embedding-determinism-scope.md &amp;&amp; grep -c 'embedding_max_input_chars' docs/ARCHITECTURE.md &amp;&amp; uv run ruff check &amp;&amp; uv run pyright &amp;&amp; uv run pytest -q</automated>
  </verify>
  <done>
    ADR 0014 exists in house style carrying every measured figure unaltered, the three-part
    decision, and the honest consequences; the CONTRIBUTING.md determinism bullet is
    conditional and cites both ADRs; the ARCHITECTURE.md meta key list includes the new
    keys; `uv run ruff check`, `uv run pyright` and `uv run pytest` are all clean. One
    atomic commit, separate from Task 1's.
  </done>
</task>

</tasks>

<verification>
- `uv run ruff check`, `uv run pyright`, `uv run pytest` all clean (non-negotiable gate).
- No test opens a socket: the new tests use the existing `httpx.MockTransport` fakes only.
- Two atomic commits, one per task.
- Vector reuse appears nowhere in the diff except as an explicitly deferred item in ADR 0014.
</verification>

<success_criteria>
A re-run of `sift analyze` whose clustering differs from a previous run can now be
diagnosed against `case.db`: the recorded knobs show whether the batch layout changed.
The determinism claim in the docs matches what Sift can actually guarantee, with the
measured evidence and the deferred fix recorded in ADR 0014.
</success_criteria>

<output>
Create `.planning/quick/260725-cxs-record-embedding-batch-knobs-in-case-met/260725-cxs-SUMMARY.md` when done.
</output>
