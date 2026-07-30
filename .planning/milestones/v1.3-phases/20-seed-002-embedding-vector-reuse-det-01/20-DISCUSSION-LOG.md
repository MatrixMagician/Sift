# Phase 20: SEED-002 Embedding Vector Reuse (DET-01) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-28
**Phase:** 20-seed-002-embedding-vector-reuse-det-01
**Areas discussed:** Reuse key, Model/dim invalidation semantics, Where the reuse/embed split is reported, `--re-embed` surface and blast radius, Folded todo (generation.context depth)

---

## Todo cross-reference

| Option | Description | Selected |
|--------|-------------|----------|
| Fold: embedding-batch-composition-determinism | 2026-07-21, area pipeline, score 0.9; frontmatter already declares `resolves_phase: 20`. The settled investigation behind ADR 0014 and SEED-002. | ✓ |
| Fold: generation-context-unset | 2026-07-21, area llm, score 0.6. `generation.context` unset so PromptBudget uses a fallback instead of the real n_ctx. Matched on keyword overlap only; generation/prompt-budget layer, not the embedding path. | ✓ |

**User's choice:** Both folded.
**Notes:** The scope concern on `generation-context-unset` (different subsystem, widens the phase) was raised in the option description before selection and the user folded it anyway — treated as their decision. Depth was then scoped explicitly in the dedicated area below, and CONTEXT.md D-10 requires it be planned as its own plan rather than entangled with the embedding path.

---

## Reuse key

### Q1 — What should a stored vector be looked up by when deciding hit vs miss?

| Option | Description | Selected |
|--------|-------------|----------|
| Exemplar text, via chunks⇔vectors join | `SELECT c.text, v.embedding FROM chunks c JOIN vectors v USING (chunk_id)` at the top of `cluster_and_label`, before any write. Zero schema migration, zero new columns. Text is exactly what was embedded, so a changed exemplar message is automatically a miss. Model identity handled separately as a whole-cache gate. | ✓ |
| `sha256(embedding_model + text)` in a new chunks column | Adds a `text_hash` column + migration. Fixed-size key, folds model identity into the key so mixed generations are structurally impossible rather than gate-enforced. Closer to the researched composite-key ideal, but pays a migration for a store that already holds the text verbatim. | |
| `template_id` | Cheapest key, no join on text. But `exemplar_event_ids[0]` can change between runs after a re-ingest, so the message behind a `template_id` can change while the id stays fixed — reuses a vector for text it was never computed from. Silent corruption, no error. | |

**User's choice:** Exemplar text, via chunks⇔vectors join.
**Notes:** Research pass (web) established the canonical minimum key as `hash(model_id + content)`, with the fuller composite adding tokenizer/normalisation/template hashes, and confirmed batch-layout parameters are deliberately absent from every recommended key — independently corroborating the pre-settled knob decision (D-11). Scouting then found the decisive local fact: `chunk_id` is a positional index from `enumerate(groups)` rewritten wholesale by `replace_chunks`, so it can never serve as an identity — which rules out the naive design and makes the text join the cheap correct one.

### Q2 — When two template groups yield the same exemplar text, should the miss list be deduplicated before embedding?

| Option | Description | Selected |
|--------|-------------|----------|
| Dedupe misses, splice one vector to all positions | Embed each distinct miss text once, fan the vector out to every position holding it. Identical text always gets an identical vector — strictly more deterministic, and makes the cache and embed path agree (a text-keyed cache would fan out on the next run anyway; not deduping means run 1 and run 2 disagree). | ✓ |
| Embed every position, no dedupe | Preserves today's exact behaviour on the rare collision path — duplicates get independently-batched vectors that may differ slightly. Simpler index-for-index splice, but leaves a first-run/second-run inconsistency. | |

**User's choice:** Dedupe misses, splice one vector to all positions.
**Notes:** Collision is near-impossible by construction (identical messages mask to identical templates, so they would be one group), but reachable through `exemplar_text()`'s fallback to `group.template` when a message is missing on a tampered or partial store.

---

## Model/dim invalidation semantics

### Q1 — How should a changed embedding model, and a changed dimension, each invalidate the cache?

| Option | Description | Selected |
|--------|-------------|----------|
| Model → auto re-embed; dim → raise, recoverable via `--re-embed` | Model change drops stored vectors and re-embeds (vec0 schema still valid, no DDL, no operator action). Dim change keeps the shipped STORE-03 hard raise, but `--re-embed` DROPs and recreates the vec0 table at the new dim. Turns a currently-unrecoverable wedge into a recoverable one without ever destroying a vec0 table implicitly. | ✓ |
| Both auto re-embed, no raise | Uniform, satisfies criterion 3 most literally. But relaxes a deliberate tested hard error, and a dim change would implicitly DROP the vectors table — `kb_vectors` shares `meta.embedding_dim`, so a `--kb` index could be silently invalidated by an unrelated model swap. | |
| Both raise; `--re-embed` is the only path | Loudest and most explicit — no vector discarded without the operator asking. Costs an ergonomic speed bump on the common case (swapping models), where re-embedding is the only correct action anyway. | |

**User's choice:** Model → auto re-embed; dim → raise, recoverable via `--re-embed`.
**Notes:** Surfaced the tension directly: criterion 3 says a dim change "forces a full re-embed", but `ensure_vectors_table` currently raises with no recovery path short of deleting the case. A dim change also genuinely requires DDL because vec0 declares `FLOAT[N]`.

### Q2 — When model identity is unknown on either side, what should reuse do?

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse, and warn on stderr | Invalidate only on a proven change (both sides known and different). Unknown identity reuses but emits a visible note. Mirrors ADR 0014's precedent: record what you cannot guard, don't hard-fail on a condition you cannot prove. | ✓ |
| Reuse silently | Simplest, matches today's status quo (no identity check exists). But an operator swapping models on a server that doesn't report them gets stale-generation mixing with nothing saying so. | |
| Treat unknown as changed — full re-embed | Strictest: never reuse a vector you cannot attribute. But on any endpoint that doesn't name its embedding model this disables reuse permanently — the feature would appear to work and silently never fire. | |

**User's choice:** Reuse, and warn on stderr.
**Notes:** `client.embedding_model` is optional by D-03; `cluster.py:436-440` skips `record_embedding_identity` entirely when neither server nor config names a model, so "did the model change?" is genuinely unanswerable in some deployments.

---

## Where the reuse/embed split is reported

### Q1 — How should the reuse/embed split be exposed?

| Option | Description | Selected |
|--------|-------------|----------|
| Return object + case meta | `cluster_and_label` returns a frozen dataclass (clusters, embedded, reused); CLI prints the line. AND counts are written to meta inside the already-open transaction (~2 lines). Unit-testable without a DB round-trip, and the split survives in `case.db` — the same "diagnosable from the case alone" reasoning ADR 0014 used for the batch knobs. | ✓ |
| Return object only | Smallest diff satisfying criterion 1 literally. But hand someone a `case.db` afterwards and there is no way to tell whether its vectors were reused or fresh — provenance lives only in terminal scrollback. | |
| Case meta only, keep `-> int` | No signature change; CLI reads meta back. Durable provenance, zero call-site churn. But makes the split a storage side-effect rather than part of the function's contract, so a unit test must go through the store — weaker than "returned counts". | |

**User's choice:** Return object + case meta.
**Notes:** No web research applied — local API-shape decision. Call sites confirmed as `cli.py:943` and `tests/test_kb_analyze.py:177`; `eval/runner.py` deliberately bypasses `cluster_and_label`, so the eval harness is insulated.

### Q2 — What exact line should analyze print, and does it print when reuse is zero?

| Option | Description | Selected |
|--------|-------------|----------|
| House style: `Embeddings: 12 new, 1769 reused` | Matches the `Label: value` shape of every existing summary line, on stdout beside `Clusters:`/`Hypotheses:`. Always printed, including first runs (`Embeddings: 1781 new, 0 reused`). ROADMAP's phrasing was illustrative, not a contract. | ✓ |
| ROADMAP wording verbatim: `Embedded 12 new exemplars, reused 1769 stored vectors` | Makes criterion 1 checkable word-for-word. Costs consistency — the only prose sentence among four `Label: value` lines, and noticeably longer. | |
| House style, suppressed when reuse is 0 | Keeps first-run output identical to today, so no existing CLI test changes. But makes the line's absence meaningful, harder to assert than a printed zero, and hides the "nothing was reused" signal. | |

**User's choice:** House style, always printed.

---

## `--re-embed` surface and blast radius

The flag surface itself was **not** re-asked — ROADMAP already names `sift analyze --re-embed` as the operator escape hatch, so it was recorded (D-07), not re-decided.

### Q1 — On a dimension-change `--re-embed`, what happens to the stale `kb_vectors` table?

| Option | Description | Selected |
|--------|-------------|----------|
| Drop `kb_vectors` too, in the same transaction | A dim change makes every vector in the case invalid, KB included — they share one vector space and one `meta.embedding_dim`. Dropping both keeps the guard honest and closes the latent bug. Cost bounded: a `--kb` run already re-indexes the whole directory from scratch every time. | ✓ |
| Leave `kb_vectors` alone, guard against the mismatch | Narrower blast radius — `--re-embed` only touches what the phase scopes. Requires `ensure_kb_vectors_table` to stop trusting meta and check the existing table's declared dim, raising on mismatch. More code, nothing destroyed implicitly. | |
| Out of scope — record it as a known gap | Ship exemplar-vector reuse only; document the interaction as a known limitation and seed it. Keeps Phase 20 tight, but knowingly leaves a corruption path reachable via `--re-embed` + `--kb`. | |

**User's choice:** Drop `kb_vectors` too, in the same transaction.
**Notes:** This question only existed because scouting found a latent bug created by the D-03 decision: `kb_vectors` is declared `FLOAT[N]` at the old dim and shares `meta.embedding_dim`, so after a dim rebuild updates meta, a later `--kb` run's `ensure_kb_vectors_table(new_dim)` passes the meta guard while `CREATE VIRTUAL TABLE IF NOT EXISTS` no-ops against the surviving old-width table. Also established that `index_kb` (`retrieve.py:60-89`) re-embeds unconditionally with no reuse, so the KB path needs nothing else from this phase.

### Q2 — Should one `--re-embed` flag cover both the harmless cache bypass and the destructive dim rebuild?

| Option | Description | Selected |
|--------|-------------|----------|
| One flag, but the destructive path announces itself | `--re-embed` does both. On the dim path it prints exactly what it is discarding before doing it. Keeps the CLI at one flag as ROADMAP scopes; the operator hitting it is already responding to a hard error that named the mismatch. | ✓ |
| One flag, silent on both paths | Simplest. But an operator passing it to pick up a new `embeddings.context` knob would silently lose a KB index if a dim change happened to be pending too. | |
| Split: `--re-embed` bypasses cache, `--rebuild-index` does the destructive dim path | Cleanest separation of blast radius. Costs a second CLI flag ROADMAP didn't scope, and the dim path is rare enough that it may not earn its own surface. | |

**User's choice:** One flag, destructive path announces itself.

---

## Folded todo: `generation.context` depth

| Option | Description | Selected |
|--------|-------------|----------|
| Wire `/props` discovery, warn when unavailable | When `config.generation.context` is None, consult the existing `client.props()` for the served `n_ctx`; when `/props` is absent (Lemonade returns web-UI HTML — the reference deployment) fall back to the built-in default AND warn that the budget is estimated, not discovered. Subsumes warn-only; the client method already exists so this is wiring, not new capability. | ✓ |
| Warn only | One-line notice when `generation.context` is None. ~5 lines, zero new behaviour. Closes the "silent" half but leaves the budget wrong on any server that would have reported `n_ctx`. | |
| Docs and config only, no code | Document the knob, set it, close the todo. Zero code. But the next operator on a fresh machine hits the identical silent fallback — the todo's root cause is that nothing surfaces the gap. | |

**User's choice:** Wire `/props` discovery, warn when unavailable.
**Notes:** An initial framing that this option would meaningfully widen the phase was corrected mid-area after finding `client.props()` / `client.has_props()` already exist at `client.py:510-522` (LLM-04, probed once, returns `{}` when absent) — the plumbing is present and simply never consulted when resolving the prompt budget. Scope concern restated once and then respected: CONTEXT.md D-10 requires this be its own plan, not entangled with the embedding path.

---

## Claude's Discretion

- Exact `meta` key names for the embedded/reused counts, following the existing `embedding_*` convention.
- Field names and module location of the frozen result dataclass.
- Whether the reuse lookup loads the `text → embedding` map eagerly or streams it (~7.3 MB at 1781 × 1024 float32; either is fine).
- Exact wording of the unknown-identity warning and the discard announcement, subject to British English.
- Whether `sift show` gains any surface for the persisted split (not required by DET-01).
- Trivially-obvious paths needing no decision: no `vectors` table yet (first run), partial cache after an interrupted run, `--re-embed` on a case with nothing stored.

## Deferred Ideas

- **Vector reuse for the KB index.** `index_kb` embeds every chunk of every `*.md` unconditionally on every `--kb` run, with no reuse at all — the exact gap this phase closes for exemplars, one table over. No DET requirement covers it, and D-08 only needs to *drop* `kb_vectors`. Natural SEED for a later milestone, cheap once this phase establishes the text-keyed pattern.
- **Recording predecessor backend state.** ADR 0014 notes that recording the knobs is "necessary but insufficient" because it cannot capture the server's prior workload, which is the actual trigger. Vector reuse makes this moot from run 2 onward but not for a case's first run. Noted so it is not mistaken for something this phase fixed.

## Out-of-band verification performed during discussion

- **vec0 read-back without `MATCH`/KNN** — D-01 depends on it entirely. Verified empirically on 2026-07-28 against the pinned `sqlite-vec==0.1.9` (`vec_version()` → `v0.1.9`): a `chunks c JOIN vectors v ON c.chunk_id = v.chunk_id` returned every row with its float32 blob intact (4-dim probe, 16-byte blobs, round-tripped through `struct.unpack`). Recorded in CONTEXT.md `<code_context>` so the planner does not re-derive it. A recalled memory asserted this; it was re-run rather than trusted.
