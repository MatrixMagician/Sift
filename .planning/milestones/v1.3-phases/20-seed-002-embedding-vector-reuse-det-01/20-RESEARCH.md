# Phase 20: SEED-002 Embedding Vector Reuse (DET-01) - Research

**Researched:** 2026-07-28
**Domain:** SQLite/sqlite-vec vector persistence, embedding-cache invalidation, CLI flag plumbing (pure internal codebase mechanics — no new external libraries)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** A stored vector is looked up by **exemplar text**, via a `chunks JOIN vectors USING (chunk_id)` read at the **top of `cluster_and_label`, before any write**. No schema migration, no new column. Model identity is enforced separately as a whole-cache gate (D-03), not folded into the key. Rejected: `template_id` as the key (exemplar_event_ids[0] can change between runs after re-ingest).
- **D-02:** Miss texts are **deduplicated before embedding**: each distinct miss text is embedded once, spliced to every position holding that text. Reachable via `exemplar_text()`'s fallback to `group.template`.
- **D-03:** **Model change → automatic full re-embed** (no DDL needed, same dim, no operator action). **Dimension change → keeps the shipped STORE-03 hard raise** (`ensure_vectors_table`, `store.py:784-789`), but `--re-embed` now `DROP`s and recreates the vec0 table at the new dim.
- **D-04:** When model identity is **unknown on either side**, reuse proceeds and a warning is emitted on stderr. Invalidation fires only on a *proven* change: both sides known and different.
- **D-05:** `cluster_and_label` returns a **frozen result dataclass** (cluster count, embedded count, reused count) **and** writes the embedded/reused counts to case `meta` inside the transaction already open. Reversibility: costly — return type changes from `int` at `cli.py:943` and `tests/test_kb_analyze.py:177` (research correction below: also `tests/test_cluster.py` and, transitively but harmlessly, `src/sift/eval/runner.py:86`).
- **D-06:** `sift analyze` prints **`Embeddings: {N} new, {M} reused`** to stdout, always (including zero-reuse first runs), alongside `Clusters:`/`Hypotheses:` (`cli.py:998`).
- **D-07:** `--re-embed` is a **boolean flag on `sift analyze` only** — no standalone subcommand.
- **D-08:** A **dimension-change `--re-embed` drops `kb_vectors` alongside `vectors`, in the same transaction** — closes a latent corruption path (KB shares `meta.embedding_dim`; a dim rebuild would otherwise leave a stale-width `kb_vectors` table that `CREATE VIRTUAL TABLE IF NOT EXISTS` silently no-ops against).
- **D-09:** **One flag covers both meanings**, but the destructive path announces itself before doing it: e.g. `dimension changed 1024 -> 768; dropping N stored vectors and M KB vectors`.
- **D-10:** When `config.generation.context` is `None`, consult `client.props()` for served `n_ctx`; when `/props` is absent, fall back to the built-in default **and warn**. Shares no code with vector reuse — its own plan within the phase.
- **D-11 (carried forward, do not re-litigate):** A batch-knob change does **NOT** invalidate reuse. Plan-time task: record it as ADR `docs/decisions/0018-*.md` (next free number confirmed below).
- **D-12 (carried forward, do not re-litigate):** The mixed hit/miss byte-identity guarantee is assertable **only under the deterministic fake transport** (EVAL-05/`httpx.MockTransport`), never against a live backend.

### Claude's Discretion

- Exact `meta` key names for embedded/reused counts, following the existing `embedding_*` naming convention.
- Field names and module location of the frozen result dataclass.
- Whether the reuse lookup loads the full `text → embedding` map eagerly or streams it (~1781 × 1024 float32 ≈ 7.3 MB either way — fine).
- Exact wording of the D-04 unknown-identity warning and the D-09 discard announcement (British English).
- Whether `sift show` gains any surface for the persisted split — not required by DET-01.
- Graceful no-op-to-full-embed handling of: no `vectors` table yet (first run), a partial cache after an interrupted run, `--re-embed` on a case with nothing stored.

### Deferred Ideas (OUT OF SCOPE)

- Vector reuse for the KB index (`index_kb`, `retrieve.py:60-89`) — no DET requirement covers it; D-08 only needs to *drop* `kb_vectors`, not reuse them. Natural follow-on SEED once this phase establishes the text-keyed reuse pattern.
- Recording predecessor backend state — ADR 0014 already notes this is "necessary but insufficient"; vector reuse makes it moot for run 2+ but not run 1. Not this phase's job.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DET-01 | User re-running `sift analyze` on an unchanged case reuses persisted embedding vectors instead of re-embedding, with the reuse/embed split reported | Read path confirmed cheap (existing `_blob_to_vec` inverse function already ships, §Code Examples); transaction-ordering constraint confirmed (§Architecture Patterns); vec0 DROP+recreate-in-transaction empirically verified safe on the pinned sqlite-vec 0.1.9 including rollback (§Pitfall 3 / Code Examples); exact call-site blast radius for the D-05 return-type change enumerated with line numbers (§Don't Hand-Roll / correction note) |

</phase_requirements>

## Summary

This phase has almost no "what library should we use" content — it is 100% internal
mechanics against code that already exists and is already tested. The two things a planner
cannot safely guess and that this research pins down are: (1) the exact read-path function
already shipped as the inverse of the write-path confinement invariant, and (2) whether
`DROP TABLE` + `CREATE VIRTUAL TABLE ... USING vec0(...)` at a new declared width, followed
by either `COMMIT` or `ROLLBACK`, behaves correctly on the pinned `sqlite-vec==0.1.9` — this
was the single named highest-risk unknown in the phase brief and is now empirically settled,
not assumed.

The reuse read (D-01) has no missing plumbing to build: `store.py`'s `_blob_to_vec` (line
109) is *already shipped* as "the read half of the confined pair" — it exists today,
unused in production code, referenced only by test round-trips (`tests/test_store_vectors.py`,
imported with `# pyright: ignore[reportUnusedFunction]`). The reuse feature does not need a
new unpack function; it needs a new *query* (`chunks JOIN vectors USING (chunk_id)`) plus a
call to the function that already exists. This collapses what looked like new
serialisation work into "wire up an existing private helper."

The vec0 DDL question (D-03/D-08's dimension rebuild) was verified directly against the
pinned `sqlite-vec==0.1.9` in this session: `DROP TABLE vectors` followed by
`CREATE VIRTUAL TABLE vectors USING vec0(...)` at a *different* declared width, inside one
`BEGIN IMMEDIATE` transaction, commits cleanly — the four vec0 shadow tables
(`vectors_info`, `vectors_chunks`, `vectors_rowids`, `vectors_vector_chunks00`) are dropped
and recreated together, no orphaned shadow state. A second test confirmed the safety case
that matters most: if the transaction is **rolled back** after the DROP+CREATE (simulating a
mid-transaction failure), the *original* table and its *original* declared width are
restored intact — a subsequent insert at the old dimension succeeds and one at the new
dimension would fail, proving the rollback is a genuine undo, not a partial/corrupted state.
This means D-03/D-08's rebuild can sit inside the *same* `store.transaction()` block that
already owns every other write in `cluster_and_label`, with no special-cased two-phase commit.

The one correction this research surfaces against CONTEXT.md's canonical refs: the claim
that `eval/runner.py` "does NOT call `cluster_and_label`" is true only for the eu-stack-only
sub-path (`_run_eustack_case`); the harness's *primary* path (`_run_pipeline`, line 86)
**does** call `cluster_and_label` for every non-eu-stack golden case, and the determinism
harness (`run_case`, D-06/EVAL-05) drives it `repeats` times — but always on **fresh
`shutil.copyfile` db copies**, never the same on-disk case.db twice. Practically this means
the reuse feature is invisible to the existing determinism harness (each repeat is a cold
miss-everything run) and the D-05 return-type change is a no-op there too, because
`eval/runner.py:86` discards the return value exactly like `tests/test_kb_analyze.py:177`
does. The dataclass-vs-int blast radius is real only where the return value is *captured* —
enumerated exactly below.

**Primary recommendation:** Read the reuse map via a single `SELECT chunks.text, vectors.embedding FROM chunks JOIN vectors USING (chunk_id)` at the very top of `cluster_and_label`, before `store.query_template_groups()`'s result is even turned into embed calls; gate reuse on model identity via `client.embedding_model` read *before* any `embed()` call (it already resolves to the configured model pre-embed, no round-trip needed); implement the dimension rebuild as a new `store.py` method (e.g. `drop_vectors_table()` / `rebuild_vectors_table(dim)`) called only from the `--re-embed` dimension path, never touching `ensure_vectors_table`'s existing STORE-03 hard-raise contract (its shipped test must keep passing unmodified).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reuse-key read (`chunks JOIN vectors`) | Database / Storage (`store.py`) | Pipeline (`cluster.py` calls it) | Vector byte access is confined to `store.py` by the shipped confinement invariant (`_vec_to_blob`/`_blob_to_vec`); the pipeline only consumes a `dict[str, list[float]]` |
| Hit/miss split + splice-back-to-order | Pipeline (`cluster.py`) | — | This is business logic over already-fetched data, not a storage concern; `cluster_and_label` already owns list-order invariants (`enumerate(groups)`) |
| Model/dim invalidation decision | Pipeline (`cluster.py`), reading `InferenceClient.embedding_model` | Database (`store.get_meta("embedding_model")`) | The comparison needs both sides; `store.py` exposes read-only meta accessors, `client.py` exposes the configured/reported model — `cluster.py` is where both are already in scope |
| Dim-mismatch DDL rebuild | Database / Storage (`store.py`, new method) | CLI (`--re-embed` triggers it) | vec0 DDL is SQL and must stay inside the existing `store.transaction()` — same rule as every other write in this function |
| `--re-embed` flag + discard announcement | CLI (`cli.py`) | — | `cluster.py`'s contract is "typer-free, print-free" (per shipped comment at `retrieve.py:6`); the flag and its stderr/stdout text belong at the CLI boundary |
| Reuse/embed split reporting (`Embeddings: N new, M reused`) | CLI (`cli.py`) | Database (`meta` keys persisted by `cluster.py`) | Printed line is CLI; the same numbers persist to `meta` inside the pipeline's transaction (D-05) so they're diagnosable from `case.db` alone without re-running |
| Generation prompt-budget `n_ctx` discovery (D-10) | LLM client (`client.py`, already has `props()`/`has_props()`) | CLI (`cli.py` resolves `ctx_fallback`) | Wiring only — no new capability; `client.props()` already exists and is already probed-once/degrade-to-`{}` |

## Standard Stack

No new external dependencies. This phase is entirely additive logic over the already-pinned
stack (`sqlite-vec==0.1.9`, stdlib `sqlite3`, numpy via scikit-learn) documented in the
project's Recommended Stack (`.claude/CLAUDE.md`). No `Standard Stack` table is needed;
listing one would imply a choice that does not exist here.

**Installation:** none required.

## Package Legitimacy Audit

**Not applicable.** This phase installs no new packages. `sqlite-vec==0.1.9` is already pinned
in `pyproject.toml`/`uv.lock` and was legitimacy-checked in an earlier phase; nothing new is
being added to `pyproject.toml` here.

## Architecture Patterns

### System Architecture Diagram

```
sift analyze [--re-embed]
      │
      ▼
cli.py:analyze()
      │  loads config, builds InferenceClient (client.embedding_model already
      │  resolves to config.embeddings.model here — no embed() call has happened yet)
      ▼
cluster_and_label(store, client, cfg, re_embed=<flag>)   [pipeline/cluster.py]
      │
      ├─(1)─► store.query_template_groups()  — unchanged, existing first line
      │
      ├─(2)─► NEW: reuse-map read, BEFORE any write:
      │         SELECT text, embedding FROM chunks JOIN vectors USING (chunk_id)
      │       → dict[str, list[float]]  (empty dict on first run / no vectors table)
      │
      ├─(3)─► NEW: model/dim identity gate
      │         meta.embedding_model vs client.embedding_model (pre-embed value)
      │         both known + differ  → treat reuse-map as empty (full re-embed)
      │         either unknown       → proceed with reuse-map, warn on stderr (D-04)
      │         --re-embed flag      → treat reuse-map as empty unconditionally (D-07/D-09)
      │
      ├─(4)─► split texts into HIT (found in reuse-map) / MISS (not found)
      │         MISS texts deduplicated (D-02) before embedding
      │
      ├─(5)─► client.embed(deduped_miss_texts)   — the ONLY embed() call, smaller now
      │         (embed() must precede every write — T-03-22 unchanged)
      │
      ├─(6)─► splice HIT vectors + newly-embedded MISS vectors back into
      │         ORIGINAL group order (D-12: this splice is what byte-identity depends on)
      │
      └─(7)─► store.transaction():
                ├─ IF --re-embed AND dim changed: NEW drop+rebuild vectors/kb_vectors
                │    (empirically verified: DROP + CREATE VIRTUAL TABLE at new dim,
                │     inside the same BEGIN IMMEDIATE, commits cleanly; a mid-transaction
                │     failure ROLLBACKs to the ORIGINAL table/dim intact — verified below)
                ├─ ensure_vectors_table(dim)          — unchanged (STORE-03 guard intact)
                ├─ record_embedding_identity(...)     — unchanged
                ├─ record_embedding_batch_knobs(...)  — unchanged
                ├─ upsert_vectors(vector_rows)        — unchanged, now writes fewer rows
                ├─ replace_chunks(chunks)             — unchanged
                ├─ replace_clusters(clusters)         — unchanged
                ├─ NEW: set_meta("embedding_reused_count", ...) / ("embedding_new_count", ...)
                └─ set_cluster_labels / cluster_label_prompt_hash — unchanged

              returns NEW frozen dataclass (cluster_count, embedded_count, reused_count)
      │
      ▼
cli.py: print(f"Embeddings: {result.embedded_count} new, {result.reused_count} reused")
        print(f"Clusters: {result.cluster_count} ...")
```

### Recommended Project Structure

No new files. Changes land in:
```
src/sift/store.py            # new reuse-read query + new dim-rebuild method(s)
src/sift/pipeline/cluster.py # reuse-map read/gate/splice logic + new return dataclass
src/sift/cli.py              # --re-embed flag, D-06 print line, D-09 discard announcement,
                              # D-10 wiring (config.generation.context fallback via client.props())
docs/decisions/0018-*.md     # ADR recording D-11 (batch-knob non-invalidation), verbatim
```

### Pattern: caller-owns-transaction (already established, reused verbatim)

**What:** Every write in `cluster_and_label` happens inside one `with store.transaction():`
block; the caller (`cluster.py`) owns it, `store.py`'s methods assume they're called inside
one.
**When to use:** Any new write this phase adds (the dim-rebuild DDL, the new `meta` count
keys) must go inside this same block, not a separate transaction.
**Example (existing code, `cluster.py:373-399`):**
```python
# Source: src/sift/pipeline/cluster.py:373 (already shipped)
with store.transaction():
    store.ensure_vectors_table(dim)
    model = client.embedding_model
    if model is not None:
        store.record_embedding_identity(model, dim)
    store.record_embedding_batch_knobs(
        context=client.embedding_context,
        batch_size=client.embedding_batch_size,
        max_input_chars=client.embedding_max_input_chars,
    )
    store.upsert_vectors(vector_rows)
    store.replace_chunks(chunks)
    store.replace_clusters(clusters)
```

### Pattern: single vector (de)serialisation confinement point

**What:** All vector bytes flow through exactly two functions in `store.py` — `_vec_to_blob`
(write) and `_blob_to_vec` (read) — never reimplemented elsewhere.
**When to use:** The reuse read MUST call `_blob_to_vec` on every blob it fetches from the
`vectors` table; do not add a second unpacking implementation anywhere (e.g. in `cluster.py`).
**Example (existing code, `store.py:98-113`):**
```python
# Source: src/sift/store.py:98 (already shipped, currently test-only consumer)
def _vec_to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()

def _blob_to_vec(  # currently pyright: ignore[reportUnusedFunction] — becomes a real
    blob: bytes,   # production consumer once the reuse read lands
) -> list[float]:
    """SINGLE vector read path — the inverse of ``_vec_to_blob``."""
    return [float(x) for x in np.frombuffer(blob, dtype="<f4")]
```
The reuse read's natural home is a new `store.py` method (e.g.
`load_vectors_by_text() -> dict[str, list[float]]`) that runs the `chunks JOIN vectors`
query and calls `_blob_to_vec` per row — this keeps the confinement invariant intact and
removes the `# pyright: ignore[reportUnusedFunction]` comment, since the function becomes
genuinely used.

### Pattern: pre-embed model identity is available without an HTTP round-trip

**What:** `client.embedding_model` (`client.py:365-373`) returns
`self._last_embedding_model or self._embeddings.model`. Before any `embed()` call in a given
process, `_last_embedding_model` is `None`, so the property resolves to the **configured**
`config.embeddings.model` — known at `InferenceClient` construction time, zero network calls.
**When to use:** The D-03/D-04 model-identity gate must read `client.embedding_model` at the
top of `cluster_and_label`, *before* calling `client.embed(...)`. Reading it after the embed
call would still work (it then prefers the server-reported name) but is unnecessary — the
comparison must happen before the embed call anyway per D-01's ordering constraint, and the
pre-embed value is exactly the value D-03 needs to compare against `meta.embedding_model`.

### Anti-Patterns to Avoid

- **Keying reuse on `chunk_id` or `template_id`:** both are positional/re-derivable, not
  identity — `chunk_id` comes from `enumerate(groups)` and is wiped/reinserted wholesale by
  `replace_chunks` every run; `template_id`'s exemplar can silently change message after a
  re-ingest (explicitly rejected in D-01).
- **Modifying `ensure_vectors_table`'s STORE-03 hard-raise to "fix" the dim-mismatch UX:**
  the shipped test `test_ensure_vectors_table_dim_mismatch_is_hard_error`
  (`tests/test_store_vectors.py:114`) asserts this raise verbatim and must keep passing
  unmodified. The dimension-rebuild path must be a **separate** method invoked only under
  `--re-embed`, called *before* `ensure_vectors_table` in that path so the guard sees a
  cleared/matching state and never trips.
- **Two-phase writes for the dim rebuild (DROP in one transaction, CREATE in another):**
  unnecessary and reopens the exact "zero-vector wedge" bug class WR-02 already fixed
  (`tests/test_cluster.py:278`, `test_failure_mid_transaction_does_not_lock_dimension`).
  The empirical test in this research confirms DROP+CREATE-at-new-dim commits and rolls
  back cleanly as one unit inside a single transaction — there is no reason to split it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vector byte unpacking | A new `struct.unpack`/`np.frombuffer` call site in `cluster.py` or a new store method | The already-shipped `_blob_to_vec` (`store.py:109`) | It is the documented inverse of `_vec_to_blob`; a second implementation would violate the confinement invariant the codebase already enforces by comment convention |
| Return-value migration for `cluster_and_label` | Ad-hoc tuple return (`(n_clusters, n_embedded, n_reused)`) | A frozen dataclass (D-05 already locks this) | Named fields are self-documenting at every call site and match the codebase's existing `TemplateGroup`/`Cluster` dataclass conventions elsewhere in `store.py` |

**Key insight:** there is nothing genuinely novel to hand-roll in this phase; the risk is
re-implementing something that already exists elsewhere in the file (the unpack function) or
touching a guard that is already correct and tested (STORE-03's hard raise).

### Correction to CONTEXT.md canonical refs — `eval/runner.py`'s actual `cluster_and_label` usage

CONTEXT.md's "Integration Points" section states: *"`eval/runner.py` deliberately does not call
`cluster_and_label` (`runner.py:18`)."* This is **imprecise** as a blanket claim and needs
correcting before planning locks task scope:

- `eval/runner.py` line 18 is inside a **docstring** describing only the eu-stack-only
  sub-path (`_run_eustack_case`), which is indeed LLM-free and skips clustering — that part
  is accurate.
- But `eval/runner.py` **does** import `cluster_and_label` (line 44) and **does** call it
  (line 86, inside `_run_pipeline`) for **every non-eu-stack golden case** — this is the
  harness's primary path.
- The call at line 86 **discards the return value** (`cluster_and_label(store, client,
  config.clustering, label=True)` with no assignment), so the D-05 return-type change
  (`int` → dataclass) does not break this call site at runtime — it is unaffected, but for a
  different reason than "it's never called."
- The determinism harness's `repeats` loop (`run_case`, `runner.py:280-282`) uses
  `shutil.copyfile(seed_db, run_db)` for each repeat — a **fresh copy** every time, never the
  same on-disk `case.db` reused across repeats. This means the reuse feature this phase adds
  is **never exercised** by the existing determinism eval harness (every repeat is a
  first-run/full-miss scenario by construction). D-12's byte-identity test needs its own
  fixture — most naturally in `tests/test_cluster.py`, calling `cluster_and_label` twice on
  the *same* `CaseStore` instance (the pattern already used by
  `test_failure_mid_transaction_does_not_lock_dimension`), not a new eval golden case.

**Exact call-site enumeration for the D-05 return-type change** (verified via `grep`):

| File | Line(s) | Captures return value? | Action needed |
|------|---------|------------------------|---------------|
| `src/sift/cli.py` | 943 | Yes (`n_clusters = ...`), consumed at line 998 | Update to read `.cluster_count` (or chosen field name) from the dataclass |
| `tests/test_cluster.py` | 127, 181, 195, 225 | Yes (`n = cluster.cluster_and_label(...)`), asserted against `len(...)` | Update each assertion to the dataclass field |
| `tests/test_cluster.py` | 162, 211, 213, 237, 269, 296, 320, 336, 353, 376, 390, 404 | No | No change needed for the call itself; some of these tests read persisted `meta`/store state after the call — check individually if they assert on the OLD int return, most don't |
| `tests/test_kb_analyze.py` | 177 | No | No change needed |
| `src/sift/eval/runner.py` | 86 | No | No change needed |

## Common Pitfalls

### Pitfall 1: Comparing model identity after the embed call instead of before

**What goes wrong:** If the D-03/D-04 gate reads `client.embedding_model` *after* calling
`client.embed(...)`, the property may now return the **server-reported** name instead of the
configured one, and — more importantly — the ordering violates D-01's "reuse read before any
write, at the very top" placement, since the gate decision must inform whether to even
attempt a reuse read.
**Why it happens:** `embedding_model`'s fallback (`_last_embedding_model or
self._embeddings.model`) makes it easy to assume the property is only meaningful after an
embed call, since that's its literal STORE-03 provenance purpose today.
**How to avoid:** Read `client.embedding_model` at the very top of `cluster_and_label`,
before any `embed()` call — it is fully populated pre-embed from `config.embeddings.model`,
which is exactly what D-03's comparison needs.
**Warning signs:** A test that configures a model name, mocks an embed response that reports
a *different* model, and asserts invalidation — if that test needs the mock response to
matter, the gate is reading the property too late.

### Pitfall 2: Splicing hit/miss vectors out of original group order

**What goes wrong:** If HIT vectors (from the reuse map) and MISS vectors (from the new,
possibly-deduplicated `embed()` call) are concatenated in "hits first, then misses" order
rather than spliced back into each group's original position, every downstream index
(`vector_rows = list(enumerate(vectors))`, `rep_excerpt` selection, HDBSCAN's row order) goes
out of sync with `groups`/`texts`, corrupting clustering silently rather than crashing.
**Why it happens:** The natural way to batch a miss list is to build a fresh list of miss
texts and embed them, which produces a *different* ordering than the original `texts` list.
**How to avoid:** Build the final `vectors` list by iterating `texts` in original order and
looking up either the reuse map or the (deduplicated) freshly-embedded map per text — never
concatenate two separately-ordered lists.
**Warning signs:** D-12's mixed hit/miss byte-identity test (against the fake transport) is
the direct guard for this — if it fails only on mixed-order fixtures but passes on all-hit or
all-miss fixtures, this is the bug.

### Pitfall 3: DDL rebuild of vec0 tables mid-transaction (now empirically resolved)

**What goes wrong (the risk before verification):** sqlite-vec's `vec0` virtual tables
materialise multiple shadow tables (`<name>_info`, `<name>_chunks`, `<name>_rowids`,
`<name>_vector_chunks00`, plus an `sqlite_autoindex_*` index). A naive assumption that
`DROP TABLE`/`CREATE VIRTUAL TABLE` on the primary name alone might leave orphaned shadow
tables, or that a virtual table DDL inside `BEGIN IMMEDIATE` might not roll back cleanly on
failure.
**Verified in this session** (direct tool execution against the pinned `sqlite-vec==0.1.9`,
not training-data recall):
- `DROP TABLE vectors` + `CREATE VIRTUAL TABLE vectors USING vec0(chunk_id INTEGER PRIMARY
  KEY, embedding FLOAT[<new_dim>])`, both inside one `BEGIN IMMEDIATE ... COMMIT`, correctly
  drops and recreates **all** shadow tables together (verified via
  `SELECT name FROM sqlite_master` before/after — no orphaned `_info`/`_chunks`/`_rowids`
  tables from the old-width table survive).
- A subsequent `INSERT` at the new width succeeds and the row count/dimension is exactly as
  expected.
- Simulating a mid-transaction failure (DROP + CREATE + INSERT, then `conn.rollback()`
  instead of `commit()`) restores the **original** table at its **original** declared width —
  proven by successfully inserting a vector shaped for the old width immediately after the
  rollback (an insert at the new width would fail against the restored old-width table).
**How to avoid:** Implement the dim rebuild as `DROP TABLE IF EXISTS vectors` followed by the
existing `ensure_vectors_table(new_dim)` call (or an equivalent inline DDL), inside the same
`store.transaction()` that owns the rest of the run's writes — exactly like every other write
in `cluster_and_label`. No special two-phase handling, no manual shadow-table cleanup, no
separate savepoint.
**Warning signs:** none expected in practice, but if a future sqlite-vec version changes shadow
table naming, a test asserting `sqlite_master` table names before/after a rebuild (mirroring
this session's manual verification) would catch a regression immediately.

### Pitfall 4: Breaking the STORE-03 dim-mismatch hard-raise while adding the rebuild path

**What goes wrong:** `ensure_vectors_table` (`store.py:774-799`) raises `ValueError` whenever
`meta.embedding_dim` is already set to a different value — this is intentional and tested
(`tests/test_store_vectors.py:114`). A naive implementation of D-03's rebuild might try to
add a bypass parameter to `ensure_vectors_table` itself (e.g. `ensure_vectors_table(dim,
force=True)`), which risks accidentally weakening the guard for the *default* (non-re-embed)
call path too.
**Why it happens:** It's the path of least resistance to add a flag to the existing function
rather than write a new one.
**How to avoid:** Keep `ensure_vectors_table` completely unchanged. Add a distinct method
(e.g. `drop_vectors_table()`) that the `--re-embed` dim-mismatch path calls *before*
`ensure_vectors_table`, so the guard's `existing != dim` branch is never even reached on that
path (meta is cleared or the table already matches by the time `ensure_vectors_table` runs).
**Warning signs:** if `tests/test_store_vectors.py::test_ensure_vectors_table_dim_mismatch_is_hard_error`
needs modification to pass, the implementation touched the wrong function.

### Pitfall 5: KB vectors surviving a dimension rebuild at the old width (D-08's named bug)

**What goes wrong:** `ensure_kb_vectors_table` (`store.py:878-903`) shares
`meta.embedding_dim` with the exemplar `vectors` table. If a dim rebuild updates
`meta.embedding_dim` to the new width but leaves `kb_vectors` at its old declared width, a
later `--kb` run's `ensure_kb_vectors_table(new_dim)` will pass the meta guard (dims now
agree) while its `CREATE VIRTUAL TABLE IF NOT EXISTS` silently no-ops against the
surviving old-width table — corrupting the KB index at the wrong dimension with no error.
**Why it happens:** the two tables are structurally independent (`vectors` vs `kb_vectors`)
but share one guard key.
**How to avoid:** D-08 already mandates dropping `kb_vectors` in the same transaction as
`vectors` on the dim-change `--re-embed` path — implement this as an unconditional pairing,
never a dim rebuild of `vectors` alone.
**Warning signs:** a test that does a dim-change `--re-embed`, then a `--kb` run, and checks
`kb_vectors`'s declared FLOAT width matches the new dim (not just that the table exists).

## Code Examples

### The reuse read query (new, to be added to `store.py`)

```python
# New store.py method — mirrors query_template_groups's read-only style.
# Returns {} if the vectors table doesn't exist yet (first run) — vec0 virtual
# tables are lazily created, so a bare SELECT against a missing table must be
# guarded (catch sqlite3.OperationalError naming "no such table", or check
# _tables()-style existence first — either is fine, first run is the common case).
def load_vectors_by_text(self) -> dict[str, list[float]]:
    """text -> embedding for every stored (chunk, vector) pair (D-01 reuse key).

    Empty on a fresh case (no ``vectors`` table yet) or a partial/interrupted
    prior run — reuse degrades to full re-embed, never raises.
    """
    try:
        rows = self._conn.execute(
            "SELECT chunks.text, vectors.embedding "
            "FROM chunks JOIN vectors USING (chunk_id)"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {text: _blob_to_vec(blob) for text, blob in rows}
```

### Empirically verified: vec0 DROP + recreate-at-new-dim, commit path

```python
# Verified interactively against the pinned sqlite-vec==0.1.9 in this session.
conn.execute("BEGIN IMMEDIATE")
conn.execute("DROP TABLE vectors")
conn.execute(
    "CREATE VIRTUAL TABLE vectors USING vec0("
    "chunk_id INTEGER PRIMARY KEY, embedding FLOAT[8])"
)
conn.execute("INSERT INTO vectors (chunk_id, embedding) VALUES (?, ?)", (2, blob8))
conn.commit()
# -> all four old-width shadow tables gone, all four new-width shadow tables
#    present, row count and dimension correct.
```

### Empirically verified: rollback restores the original table intact

```python
# Verified interactively: same DROP+CREATE+INSERT sequence, but conn.rollback()
# instead of conn.commit() — the ORIGINAL (old-width) table survives with its
# original row(s); a subsequent old-width insert succeeds, proving genuine undo.
conn.execute("BEGIN IMMEDIATE")
conn.execute("DROP TABLE vectors")
conn.execute("CREATE VIRTUAL TABLE vectors USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[8])")
conn.execute("INSERT INTO vectors (chunk_id, embedding) VALUES (2, ?)", (blob8,))
conn.rollback()
# -> old-width table restored; INSERT of an old-width vector succeeds afterward.
```

### D-10 wiring sketch (separate plan within the phase, per CONTEXT.md scope note)

```python
# cli.py — resolving the generation ctx_fallback, wiring in client.props()
n_ctx = None
if config.generation.context is None and client.has_props:
    reported = client.props().get("n_ctx")
    if isinstance(reported, int) and reported > 0:
        n_ctx = reported
    else:
        print("Warning: /props present but n_ctx missing/invalid; using built-in "
              "fallback", file=sys.stderr)
if n_ctx is None and config.generation.context is None:
    print("Warning: prompt budget context is estimated, not discovered "
          "(/props absent)", file=sys.stderr)
ctx_fallback = config.generation.context or n_ctx or _TRIAGE_CTX_FALLBACK
```

## Assumptions Log

No claims in this research are tagged `[ASSUMED]`. Every factual claim above was verified
either by direct code reading (with exact line numbers cited), by reading the shipped test
suite, or by direct tool execution against the project's own pinned dependency
(`sqlite-vec==0.1.9`) in this session. There is no external-library ambiguity in this phase
requiring `[CITED]`-level research either, since no new package or API surface is introduced.

**This table is empty — no user confirmation needed on factual grounds.** (CONTEXT.md's
`Claude's Discretion` items — exact meta key names, dataclass field names, warning wording —
are legitimate open *naming* choices, not unverified factual claims, and are called out
separately above.)

## Open Questions

1. **Exact name and signature of the new dim-rebuild store method.**
   - What we know: it must `DROP TABLE` both `vectors` and (per D-08) `kb_vectors`, then let
     the existing `ensure_vectors_table`/`ensure_kb_vectors_table` recreate them at the new
     dim, all inside the transaction the `--re-embed` dim path already owns.
   - What's unclear: whether to expose one combined method (`rebuild_vector_tables(dim)`) or
     two single-table methods called together from `cluster.py`/`cli.py`.
   - Recommendation: two single-table methods (`drop_vectors_table()`,
     `drop_kb_vectors_table()`), mirroring the existing one-table-per-method convention
     (`ensure_vectors_table` / `ensure_kb_vectors_table` are already separate); the caller
     pairs them per D-08, keeping the pairing an explicit decision at the call site rather
     than hidden inside a single method name.

2. **Where exactly does the D-04 unknown-identity warning and D-09 discard announcement get
   printed relative to the Progress bar context manager in `cli.py`?**
   - What we know: `cluster.py` must stay print-free (existing contract); the warning/
     announcement text is CLI-boundary work, and `cli.py:927-936` already wraps the
     `cluster_and_label` call in a `Progress(...)` context with a static description.
   - What's unclear: whether the new dataclass needs a `warnings: list[str]` field for
     `cluster_and_label` to hand printable-but-unprinted text back to `cli.py` (keeping the
     print-free contract), or whether the D-04/D-09 messages are simple enough to compute at
     the CLI layer directly from information already available there (config vs. stored meta,
     both readable via `store.get_meta` before calling `cluster_and_label`).
   - Recommendation: compute D-04's "unknown identity" case at the CLI layer by reading
     `store.get_meta("embedding_model")` and `client.embedding_model` directly — both are
     already accessible in `cli.py` without needing the pipeline to surface anything new.
     D-09's discard announcement is simplest printed directly by `cli.py` before calling
     `cluster_and_label`, since `cli.py` already has `config.embeddings` and can read
     `store.get_meta("embedding_dim")` itself to compute the message.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (confirmed 9.1.1 in a prior phase's validation reconciliation) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, default `addopts` excludes `perf`/`live`/`packaging` markers) |
| Quick run command | `uv run pytest tests/test_cluster.py tests/test_store_vectors.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DET-01 | Second `sift analyze` on unchanged case: zero new embeds, split reported in return value | unit | `pytest tests/test_cluster.py::test_reuse_zero_embeds_on_unchanged_case -x` | ❌ Wave 0 (new test) |
| DET-01 | Mixed hit/miss run byte-identical to full re-embed, same ordering, on the deterministic fake transport | unit | `pytest tests/test_cluster.py::test_reuse_mixed_hit_miss_matches_full_reembed -x` | ❌ Wave 0 (new test) |
| DET-01 | Model change forces full re-embed (both sides known + differ) | unit | `pytest tests/test_cluster.py::test_reuse_invalidated_on_model_change -x` | ❌ Wave 0 (new test) |
| DET-01 | Unknown model identity (either side) proceeds with reuse + stderr warning | unit | `pytest tests/test_cluster.py::test_reuse_proceeds_with_warning_on_unknown_identity -x` | ❌ Wave 0 (new test) |
| DET-01 | Batch-knob change (context/batch_size/max_input_chars) does NOT invalidate reuse | unit | `pytest tests/test_cluster.py::test_reuse_survives_batch_knob_change -x` | ❌ Wave 0 (new test) |
| DET-01 | `--re-embed` on unchanged dim: bypasses cache, embeds everything, no DDL | unit | `pytest tests/test_cli.py::test_re_embed_flag_bypasses_cache -x` | ❌ Wave 0 (new test) |
| DET-01 | Dimension change: `ensure_vectors_table` still hard-raises WITHOUT `--re-embed` (unchanged STORE-03 contract) | unit | `pytest tests/test_store_vectors.py::test_ensure_vectors_table_dim_mismatch_is_hard_error -x` | ✅ (must keep passing unmodified) |
| DET-01 | Dimension change WITH `--re-embed`: drops+rebuilds `vectors` AND `kb_vectors`, discard announcement printed | unit | `pytest tests/test_store_vectors.py::test_drop_and_rebuild_vectors_at_new_dim -x` | ❌ Wave 0 (new test) |
| DET-01 | `sift analyze` prints `Embeddings: {N} new, {M} reused` on every run including first (M=0) | unit | `pytest tests/test_cli.py::test_analyze_prints_embedding_split -x` | ❌ Wave 0 (new test) |
| DET-01 | `cluster_and_label`'s dataclass return exposes cluster/embedded/reused counts | unit | `pytest tests/test_cluster.py::test_cluster_and_label_return_dataclass_fields -x` | ❌ Wave 0 (new test) |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_cluster.py tests/test_store_vectors.py tests/test_cli.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** Full suite green (`uv run ruff check && uv run pyright && uv run pytest`) before `/gsd-verify-work`, per project "done" convention (CLAUDE.md).

### Wave 0 Gaps

- [ ] `tests/test_cluster.py` — add reuse/invalidation/splice-order test cases listed above (extends the existing file; no new fixture module needed, reuses `_client`/`_embed_handler`/`_seed` helpers already present)
- [ ] `tests/test_store_vectors.py` — add the dim-rebuild-with-`--re-embed` test (extends the existing file; reuses `_tables()` helper already present)
- [ ] `tests/test_cli.py` — add `--re-embed` flag and `Embeddings: N new, M reused` output tests (check whether an existing `analyze` CLI test fixture already exists in this file to extend, rather than duplicating client-mocking boilerplate)
- [ ] Update (not add) `tests/test_cluster.py` lines 127, 181, 195, 225 and `tests/test_kb_analyze.py:177` for the D-05 dataclass return type
- [ ] No new test framework/config needed — pytest + `httpx.MockTransport` fixtures already cover everything this phase needs (EVAL-05 compliant, zero network egress)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Phase touches no auth surface |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | Marginal | `dim`/`chunk_id` values are already validated as ints before DDL interpolation (existing `# noqa: S608` pattern with a code comment justifying it, `store.py:795`, `store.py:898`) — the new DROP+rebuild DDL must follow the identical pattern (interpolate only the already-validated `int(dim)`, never user/server text directly) |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via interpolated `dim` in the new DROP/CREATE DDL | Tampering | Mirror the existing pattern exactly: `dim` is always `int(dim)` from a value already validated as an int (never raw server/user text) before it reaches an f-string; this is the same justified `# noqa: S608` precedent already in `ensure_vectors_table`/`ensure_kb_vectors_table` |
| Operator running `--re-embed` accidentally discarding vectors without realising the blast radius | (Not a STRIDE category — an operator-safety concern, not a security vulnerability) | D-09 already mandates announcing the discard (`dimension changed X -> Y; dropping N stored vectors and M KB vectors`) before doing it — this is a UX safeguard, not a security control, but is the closest analogue to "no silent destructive action" in this phase |

No new attack surface is introduced: no new network calls, no new file I/O outside the
existing `case.db`, no new secrets, no change to the SSRF guard (`_assert_local`) or the
zero-network-egress test invariant. `security_enforcement` is active per
`.planning/config.json`, but this phase's risk profile does not warrant a dedicated
`SECURITY.md` addendum beyond the DDL-interpolation note above, which simply extends an
already-reviewed pattern.

## Sources

### Primary (HIGH confidence — verified via direct tool execution or direct code/test reading in this session)

- `src/sift/store.py:98-113` (`_vec_to_blob`/`_blob_to_vec`), `:774-903` (`ensure_vectors_table`,
  `record_embedding_identity`, `record_embedding_batch_knobs`, `upsert_vectors`,
  `replace_chunks`, `ensure_kb_vectors_table`) — read directly, line numbers verified against
  current HEAD
- `src/sift/pipeline/cluster.py:60-172, 310-400` (`exemplar_text`, `_exemplar_messages`,
  `cluster_and_label`) — read directly
- `src/sift/cli.py:770-1029` (`analyze` command, call site, summary block) — read directly
- `src/sift/llm/client.py:255-388, 480-533` (`InferenceClient.__init__`, `embed`,
  `embedding_model`/`embedding_context`/`embedding_batch_size`/`embedding_max_input_chars`,
  `has_props`/`props`) — read directly
- `src/sift/pipeline/retrieve.py:1-98` (`index_kb`) — read directly
- `src/sift/eval/runner.py:1-100, 280-282` — read directly (source of the correction above)
- `tests/test_store_vectors.py` (full), `tests/test_cluster.py:1-100, 260-310`,
  `tests/test_kb_analyze.py:140-200` — read directly
- `docs/decisions/0014-embedding-determinism-scope.md` — read directly for ADR format and the
  measured probe figures this phase closes
- Empirical verification against pinned `sqlite-vec==0.1.9` (`uv run python3`, this session):
  `vec_version()` returns `v0.1.9`; DROP+CREATE-at-new-dim inside one transaction commits
  cleanly with all shadow tables replaced; rollback after DROP+CREATE restores the original
  table at its original width intact
- `docs/decisions/` directory listing — confirmed 0001-0017 exist, 0018 is the next free
  number

### Secondary (MEDIUM confidence)

None required for this phase.

### Tertiary (LOW confidence)

None — this phase involved no speculative or unverified claims.

## Metadata

**Confidence breakdown:**
- Standard stack: N/A — no new stack decisions this phase
- Architecture: HIGH — every pattern cited is either already-shipped code or empirically verified in this session
- Pitfalls: HIGH — five pitfalls identified, three from direct code/test reading (existing guard semantics), two from direct empirical testing (vec0 DDL behaviour)

**Research date:** 2026-07-28
**Valid until:** 2026-08-27 (30 days — stable internal mechanics, no fast-moving external dependency in scope)
