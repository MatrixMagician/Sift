# Phase 20: SEED-002 Embedding Vector Reuse (DET-01) - Context

**Gathered:** 2026-07-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Make `sift analyze` reuse the embedding vectors already persisted in `case.db`
instead of re-embedding every exemplar on every run.

This closes the determinism exposure ADR 0014 documented but deliberately did
not fix: embedding output depends on the *batch layout* of the request and on
the layout of *preceding* requests to the same shared endpoint, at magnitudes
four orders above float32 noise. If the vectors are read back rather than
regenerated, there is no second embedding pass to perturb, so the exposure
disappears for every run after the first. It also removes the dominant cost of
a re-analyse (1781 exemplars / ~1.45 MB of text on case `CS1066664`).

**In scope:** the exemplar-vector path — `pipeline/cluster.py`, the `vectors`
vec0 table, the `chunks` table it joins against, model/dimension invalidation,
the `--re-embed` escape hatch on `sift analyze`, and the reuse/embed split
reporting. Plus one folded todo on the generation prompt-budget context window
(see D-10) which shares no code with the above and belongs in its own plan.

**Out of scope:** reuse for the KB index (`index_kb` has no reuse today and
gains none here — see Deferred Ideas), any change to HDBSCAN/clustering
parameters, and any change to the batch-packing logic itself.

</domain>

<decisions>
## Implementation Decisions

### Reuse key

- **D-01:** A stored vector is looked up by **exemplar text**, via a
  `chunks JOIN vectors USING (chunk_id)` read at the **top of
  `cluster_and_label`, before any write**. No schema migration and no new
  column — `chunks(chunk_id, template_id, text, event_ids)` already stores the
  text verbatim, and `replace_chunks` does not wipe it until later in the same
  transaction, so the previous run's `text → embedding` mapping is intact at
  that point. Model identity is enforced separately as a whole-cache gate
  (D-03), not folded into the key.
  Rejected: `template_id` as the key — `exemplar_event_ids[0]` can change
  between runs after a re-ingest, so the message behind a given `template_id`
  can change while the id stays fixed; that reuses a vector for text it was
  never computed from, silently and with no error.

- **D-02:** Miss texts are **deduplicated before embedding**: each distinct
  miss text is embedded once, and the resulting vector is spliced to every
  position holding that text. Identical text therefore always yields an
  identical vector. Without this, run 1 (two independently-batched vectors for
  the same text, differing by up to the measured 4.8e-3) and run 2 (one cached
  vector fanned out) disagree — a self-inflicted determinism gap. Reachable
  via `exemplar_text()`'s fallback to `group.template` when a message is
  missing on a tampered or partial store.

### Model and dimension invalidation

- **D-03:** **Model change → automatic full re-embed.** When
  `meta.embedding_model` and `client.embedding_model` are both known and
  differ, stored vectors are discarded and everything is re-embedded. No DDL
  is needed (the vec0 schema is still valid at the same dim) and no operator
  action is required.
  **Dimension change → keeps the shipped STORE-03 hard raise**
  (`ensure_vectors_table`, `store.py:784-789`), but `--re-embed` now `DROP`s
  and recreates the vec0 table at the new dim. This converts a currently
  *unrecoverable* wedge — today a dim mismatch cannot be resolved short of
  deleting the case — into a recoverable one, without ever destroying a vec0
  table implicitly.
  — **Reversibility:** costly — undoing this changes the recovery semantics of
  a shipped, tested hard error (STORE-03) that `tests/test_store.py` asserts,
  and operators may come to rely on `--re-embed` as the documented dim-change
  recovery path.

- **D-04:** When model identity is **unknown on either side** (`meta` has no
  `embedding_model`, or `client.embedding_model` is `None` — D-03 leaves the
  model optional and `cluster.py:436-440` skips recording entirely in that
  case), **reuse proceeds and a warning is emitted on stderr** saying reuse
  happened without a verifiable model identity. Invalidation fires only on a
  *proven* change: both sides known and different.
  Rationale: treating unknown as changed would permanently disable reuse on
  any endpoint that does not name its embedding model — the feature would
  appear to work and silently never fire. This mirrors ADR 0014's own
  precedent of recording what cannot be guarded rather than hard-failing on a
  condition that cannot be proven.

### Reporting the reuse/embed split

- **D-05:** `cluster_and_label` returns a **frozen result dataclass**
  (cluster count, embedded count, reused count) **and** writes the embedded/
  reused counts to case `meta` inside the transaction that is already open.
  The return object satisfies DET-01's "assertable from the printed/returned
  counts, without inspecting mock call counts" and is unit-testable with no DB
  round-trip; the `meta` keys make the split diagnosable from `case.db` alone,
  which is the same reasoning ADR 0014 used when it put the batch knobs in
  `meta`.
  — **Reversibility:** costly — the return type changes from `int` at
  `cli.py:943` and `tests/test_kb_analyze.py:177`, and the new `meta` keys
  become a persisted on-disk contract that later readers may depend on.

- **D-06:** `sift analyze` prints **`Embeddings: {N} new, {M} reused`** to
  stdout, alongside the existing `Clusters:` / `Hypotheses:` lines
  (`cli.py:998`). It is **always printed**, including first runs where reused
  is 0. The `Label: value` shape matches every other summary line; ROADMAP's
  prose phrasing ("Embedded N new exemplars, reused M stored vectors") was
  illustrative, not a contract. A stable output shape means tests assert one
  format, and a zero-reuse run is itself a signal worth seeing.

### `--re-embed` escape hatch

- **D-07:** `--re-embed` is a **boolean flag on `sift analyze` only** — no
  standalone subcommand. Recorded, not re-decided: ROADMAP already names it as
  the operator escape hatch for applying a batch-knob change.

- **D-08:** A **dimension-change `--re-embed` drops `kb_vectors` alongside
  `vectors`, in the same transaction.** This closes a latent corruption path
  created by D-03: `kb_vectors` is declared `FLOAT[N]` at the old dim and
  shares `meta.embedding_dim` (`store.py:878-902`), so after a dim rebuild
  updates `meta`, a later `--kb` run's `ensure_kb_vectors_table(new_dim)`
  passes the meta guard while `CREATE VIRTUAL TABLE IF NOT EXISTS` no-ops
  against the surviving old-width table. A dim change invalidates every vector
  in the case, KB included — they share one vector space and one meta key.
  Cost is bounded: `index_kb` already re-indexes the whole directory from
  scratch on every `--kb` run, so the KB regenerates on the operator's next
  `--kb` pass at no extra design cost.
  — **Reversibility:** costly — undoing it means teaching
  `ensure_kb_vectors_table` to stop trusting `meta` and inspect the existing
  table's declared width instead, which is a different and larger change than
  simply reverting the drop.

- **D-09:** **One flag covers both meanings**, but the destructive path
  announces itself. `--re-embed` performs both the harmless cache bypass and
  the destructive dim rebuild; on the dim path it prints exactly what it is
  discarding before doing it (e.g. `dimension changed 1024 -> 768; dropping N
  stored vectors and M KB vectors`). The operator reaching for it on the dim
  path is already responding to a hard error that named the mismatch, so they
  are not surprised — but they are told the blast radius before work is lost.

### Folded todo: generation prompt-budget context window

- **D-10:** When `config.generation.context` is `None`, **consult the existing
  `client.props()` for the served `n_ctx`** and use it. When `/props` is absent
  — Lemonade returns web-UI HTML, which is the reference deployment — fall back
  to the built-in default **and warn** that the prompt budget is estimated
  rather than discovered. The client plumbing already exists (`client.props()`
  / `client.has_props()`, `client.py:510-522`, LLM-04, probed once, returns
  `{}` when absent); it is simply never consulted when resolving the budget.
  This is wiring, not new capability.
  **Scope note:** this shares no code with vector reuse and must be planned as
  its own plan within the phase, not entangled with the embedding path.

### Carried forward — settled, do not re-litigate

- **D-11:** A **batch-knob change does NOT invalidate reuse.**
  `embeddings.context`, `embeddings.batch_size` and
  `embeddings.max_input_chars` are recorded in `meta` (ADR 0014, overwrite
  semantics, no guard) and a change to any of them leaves stored vectors
  valid. Not invalidating is precisely what makes a re-run reproducible;
  invalidating would re-embed under a new batch layout on the first run after
  any knob change, reopening the hysteresis this phase exists to eliminate.
  `--re-embed` is the explicit path for an operator who wants a new knob to
  take effect.
  **Plan-time task:** *record* this as a new ADR in `docs/decisions/` — the
  next free number is **0018** (0001-0017 are taken). Do not re-decide it.

- **D-12:** DET-01's success criterion 2 — "a mixed hit/miss run produces
  output byte-identical to a full re-embed of the same exemplars" — is a
  guarantee that the **splice preserves original group order**, and is
  assertable only **under the deterministic fake transport** (EVAL-05).
  Against a real backend, a full re-embed is *precisely* what perturbs the
  vectors — that is ADR 0014's entire finding — so a test asserting byte
  identity against a live endpoint would be asserting the opposite of the
  measured behaviour. Plan the test on the fake transport; do not write an
  unsatisfiable live-backend equivalent.

### Claude's Discretion

- Exact `meta` key names for the embedded/reused counts (D-05), following the
  existing `embedding_*` naming convention.
- Field names and module location of the frozen result dataclass (D-05).
- Whether the reuse lookup loads the full `text → embedding` map eagerly or
  streams it; at ~1781 exemplars x 1024 float32 (~7.3 MB) either is fine.
- Exact wording of the D-04 unknown-identity warning and the D-09 discard
  announcement, subject to British English.
- Whether `sift show` gains any surface for the persisted split (D-05); not
  required by DET-01.
- Handling of the trivially-obvious paths: no `vectors` table yet (first run),
  a partial cache after an interrupted run, and `--re-embed` on a case with
  nothing stored — all must be graceful no-op-to-full-embed, none need a
  decision.

### Folded Todos

- **`.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`**
  (area: pipeline, match score 0.9; frontmatter already declares
  `resolves_phase: 20`). The settled investigation behind ADR 0014 and
  SEED-002: batch composition perturbs vectors by up to 4.8e-3, 4% of
  exemplars change nearest neighbour, and the trigger is the layout
  *transition* rather than the context value. It is this phase's evidence
  base and its motivation; Phase 20 shipping closes it.

- **`.planning/todos/pending/2026-07-21-generation-context-unset.md`**
  (area: llm, match score 0.6). `generation.context` is unset so `PromptBudget`
  falls back to a built-in default instead of the generation model's real
  loaded window; Lemonade does not serve `/props`, so Sift never discovers
  `n_ctx`. Folded by explicit user decision after the scope concern was
  raised. Fits as a separate plan under D-10 — same `sift analyze` invocation,
  entirely different subsystem.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Decisions this phase must honour or extend
- `docs/decisions/0014-embedding-determinism-scope.md` — the measured
  exposure, the three probes, and the explicit deferral of vector reuse to
  v1.3/SEED-002. Its "Decision" section (Recorded / Scoped / Deferred) is the
  direct predecessor of this phase; its "Consequences" section explains why
  the batch knobs use overwrite semantics unlike the `embedding_dim` guard.
- `docs/decisions/0008-report-determinism-scope.md` — scopes the *report
  renderer's* determinism given an identical `case.db`. Deliberately narrower
  and unamended; this phase makes its assumption true upstream. Do not
  conflate the two layers.
- `docs/decisions/0005-analyze-exit-codes.md` — the 0/3/1/2 contract
  `sift analyze` must keep honouring with the new flag and output line.

### Phase motivation and evidence
- `.planning/seeds/SEED-002-embedding-vector-reuse.md` — the sketch this
  phase implements, including the explicit warning against keying on row
  order and the requirement that reuse be externally observable.
- `.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`
  — full probe data (Probe A/B/C, the hysteresis replication, the retracted
  15-of-200 intermediate reading).
- `.planning/todos/pending/2026-07-21-generation-context-unset.md` — the D-10
  folded todo, including the 2026-07-20 debug session it traces back to.
- `.planning/REQUIREMENTS.md` — DET-01 (line 65) and its Determinism section.

### Code that constrains the implementation
- `src/sift/pipeline/cluster.py` §`cluster_and_label` (line 310) — the single
  `client.embed(texts)` call, the `enumerate(groups)` chunk-id construction,
  and the one `store.transaction()` that owns every write.
- `src/sift/store.py` §`ensure_vectors_table` (774), `record_embedding_identity`
  (802), `record_embedding_batch_knobs` (819), `upsert_vectors` (841),
  `replace_chunks` (860), `ensure_kb_vectors_table` (878) — every guard and
  write this phase touches or must keep working.
- `src/sift/cli.py` §`analyze` (777) and its cluster call site (943) and
  summary block (998) — where the flag and the output line land.
- `src/sift/llm/client.py` §`props` / `has_props` (510-522) — the existing
  `/props` plumbing D-10 wires in.
- `src/sift/pipeline/retrieve.py` §`index_kb` (60) — proves the KB path
  re-embeds unconditionally and needs nothing from `--re-embed` except D-08's
  drop.

### Project rules
- `CLAUDE.md` — load-bearing invariants (determinism, citation validation,
  zero network egress in tests), the boring-technology constraint, and
  British English in user-facing strings.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`chunks` table** (`store.py:219`) already persists `(chunk_id,
  template_id, text, event_ids)` — the `text` column *is* the reuse index.
  Joined to `vectors` on `chunk_id`, it yields `text → embedding` with zero
  migration. This is the single finding that makes D-01 cheap.
- **vec0 rows are readable by plain `SELECT`/`JOIN` — no `MATCH`, no `k =`.**
  D-01's whole design depends on this and it is **verified empirically**
  (2026-07-28) against the pinned `sqlite-vec==0.1.9` (`vec_version()` →
  `v0.1.9`): a `chunks c JOIN vectors v ON c.chunk_id = v.chunk_id` returned
  every row with its exact float32 blob intact (4-dim probe, 16-byte blobs,
  round-tripped through `struct.unpack`). No parallel BLOB column is needed
  and the documented sqlite-vec escape hatch stays unused. Note that
  `store.py` already confines every vector byte to `_vec_to_blob`
  (the confinement invariant) — the read side needs the matching unpack.
- **`client.props()` / `client.has_props()`** (`client.py:510-522`) — already
  probes `/props` once and degrades to `{}`; D-10 is wiring, not new code.
- **`store.transaction()` caller-owns idiom** — `cluster_and_label` already
  wraps every write in one transaction, so the D-08 `kb_vectors` drop and the
  D-05 meta writes have an existing home with rollback already correct.
- **`record_embedding_batch_knobs`** (`store.py:819`) — the precedent for
  "record, do not guard", which D-04 and D-11 both follow.

### Established Patterns
- **`chunk_id` is positional, not an identity.** It comes from
  `enumerate(groups)` (`cluster.py:399`, `cluster.py:404`) and `replace_chunks`
  does `DELETE FROM chunks` then reinserts wholesale (`store.py:868`). Reuse
  can never key on it — this is the constraint that rules out the naive design.
- **vec0 tables are created lazily at a fixed declared width** and have no
  `INSERT OR REPLACE`; `upsert_vectors` deletes then inserts. A dim change
  therefore genuinely requires DDL, which is why D-03 cannot simply "re-embed"
  past a dim mismatch without a `DROP`.
- **The embed call precedes every write** (T-03-22), so an interrupted embed
  rolls back to zero clusters/vectors. Any reuse read must sit *before* the
  transaction's writes to preserve this.
- **Summary output is `Label: value` on stdout** (`cli.py:518, 998, 1027`);
  progress bars go to stderr. D-06 follows the former.
- **Prompts and reports are print-free at the pipeline layer** —
  `cluster.py`'s contract is "typer-free, print-free" (`retrieve.py:6`), so
  the D-04 warning and D-09 announcement belong at the CLI boundary, driven by
  the returned result object rather than printed from inside the pipeline.

### Integration Points
- `cli.py:943` — the `cluster_and_label(...)` call site; absorbs the D-05
  return-type change and threads the D-07 `--re-embed` flag through.
- `cli.py:998` — the summary block where the D-06 line lands.
- `tests/test_kb_analyze.py:177` — the only other `cluster_and_label` caller;
  must be updated for the return-type change.
- `eval/runner.py` deliberately does **not** call `cluster_and_label`
  (`runner.py:18`), so the eval harness is insulated from D-05.

</code_context>

<specifics>
## Specific Ideas

- The reuse read must happen at the very top of `cluster_and_label`, before
  `ensure_vectors_table` and before any write, so the previous run's `chunks`
  rows are still present to join against.
- The measured baseline to beat, from ADR 0014 and SEED-002: case
  `CS1066664`, 1781 template groups, ~1.45 MB of exemplar text re-embedded
  from scratch on every run. A re-run after ingesting a handful of new files
  should approach free.
- Perturbation magnitudes worth keeping in the plan's language so nobody
  re-derives them: max component delta 4.76e-3 (Probe B), cosine perturbation
  max 3.19e-4 / median 1.33e-4, min spacing to nearest distinct exemplar
  1.76e-4, 8 of 200 exemplars (4%) change nearest-neighbour identity.

</specifics>

<deferred>
## Deferred Ideas

- **Vector reuse for the KB index.** `index_kb` (`retrieve.py:60-89`) embeds
  every chunk of every `*.md` unconditionally on every `--kb` run, with no
  reuse whatsoever — the exact gap this phase closes for exemplars, one table
  over. It is deliberately out of scope here (no DET requirement covers it,
  and D-08 only needs to *drop* `kb_vectors`, not reuse them). A natural
  SEED for a later milestone, and cheap once this phase establishes the
  text-keyed reuse pattern.
- **Recording predecessor backend state.** ADR 0014 notes that recording the
  knobs is "necessary but insufficient" because it cannot capture the
  server's prior workload, which is the actual trigger. Vector reuse makes
  this moot for run 2 onward but not for the first run of a case. Out of
  scope; noted so it is not mistaken for something this phase fixed.

</deferred>

---

*Phase: 20-SEED-002 Embedding Vector Reuse (DET-01)*
*Context gathered: 2026-07-28*
