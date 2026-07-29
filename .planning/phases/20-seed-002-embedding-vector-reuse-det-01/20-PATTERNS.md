# Phase 20: SEED-002 Embedding Vector Reuse (DET-01) - Pattern Map

**Mapped:** 2026-07-28
**Files analyzed:** 6 (all modifications — no new source modules; one new ADR file)
**Analogs found:** 6 / 6 (all patterns exist in-repo already; this phase is pure internal-mechanics wiring, confirmed by RESEARCH.md)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/sift/store.py` (new `load_vectors_by_text`, `drop_vectors_table`, `drop_kb_vectors_table`) | model/storage | CRUD (read-through-cache + DDL rebuild) | same file: `ensure_vectors_table` (774), `_blob_to_vec`/`_vec_to_blob` (98-113) | exact — same file, same module conventions |
| `src/sift/pipeline/cluster.py` (`cluster_and_label` reuse gate + splice + dataclass return) | service/pipeline | transform (batch read → hit/miss split → write) | same file: existing `cluster_and_label` body (310-400) | exact — modifying the function itself |
| `src/sift/cli.py` (`analyze`: `--re-embed` flag, D-06 print line, D-09 announcement, D-10 wiring) | controller/CLI | request-response | same file: `analyze` (777), existing bool `typer.Option` flags (779-792), summary block (995-998) | exact — modifying the function itself |
| `docs/decisions/0018-*.md` | doc/config (ADR) | N/A | `docs/decisions/0014-embedding-determinism-scope.md` | exact — same doc type, same directory |
| `tests/test_cluster.py` (new reuse/invalidation/splice tests + 4 updated assertions) | test | unit | same file: `_seed`/`_embed_handler`/`_client` helpers (70-105) | exact — extend existing file, reuse existing fixtures |
| `tests/test_store_vectors.py` (new dim-rebuild test) | test | unit | same file: `_tables()` helper (22-32), `test_migration_3_creates_chunks_and_clusters` (38) | exact — extend existing file |
| `tests/test_cli.py` (new `--re-embed`/summary-line tests) | test | unit | existing `analyze` CLI test(s) in same file (not excerpted — locate and extend, do not duplicate client-mocking boilerplate per RESEARCH.md Wave-0 gap note) | role-match |

No "No Analog Found" section needed — every file in scope is a modification to an existing, already-conventioned file.

## Pattern Assignments

### `src/sift/store.py` — new reuse read + dim-rebuild methods

**Analog:** same file, `_vec_to_blob`/`_blob_to_vec` (lines 98-113) and `ensure_vectors_table` (774-799)

**Confinement pattern to copy verbatim** (lines 98-113, already shipped):
```python
def _vec_to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()

def _blob_to_vec(  # currently pyright: ignore[reportUnusedFunction] — becomes a real
    blob: bytes,   # production consumer once the reuse read lands
) -> list[float]:
    """SINGLE vector read path — the inverse of ``_vec_to_blob``."""
    return [float(x) for x in np.frombuffer(blob, dtype="<f4")]
```
Rule: the new reuse read MUST call `_blob_to_vec` per row. Do not add a second unpack implementation in `cluster.py` — this is the load-bearing confinement invariant RESEARCH.md names explicitly.

**New method to add** (RESEARCH.md's verified sketch — copy this shape):
```python
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

**Existing guard NOT to touch** (`store.py:774-799`, STORE-03 hard-raise — `tests/test_store_vectors.py:114` asserts it verbatim): keep `ensure_vectors_table` completely unchanged. Add `drop_vectors_table()` / `drop_kb_vectors_table()` as separate methods, called only from the `--re-embed` dim-mismatch path, invoked *before* `ensure_vectors_table` so its guard never trips on that path (RESEARCH.md Pitfall 4, Open Question 1 — two single-table methods, mirroring the existing one-table-per-method convention of `ensure_vectors_table`/`ensure_kb_vectors_table`).

**DDL pattern for the rebuild** (empirically verified against pinned `sqlite-vec==0.1.9`, safe inside the existing `store.transaction()`):
```python
conn.execute("BEGIN IMMEDIATE")
conn.execute("DROP TABLE vectors")
conn.execute(
    "CREATE VIRTUAL TABLE vectors USING vec0("
    "chunk_id INTEGER PRIMARY KEY, embedding FLOAT[8])"
)
```
Interpolate only an already-validated `int(dim)`, mirroring the existing justified `# noqa: S608` precedent at `store.py:795` / `store.py:898` — never raw server/user text.

**Return-type dataclass idiom to copy** (`store.py:418-429`, `TemplateGroup` — this IS the existing frozen-dataclass-as-pipeline-result idiom the planner should match for D-05's new return type):
```python
@dataclass(frozen=True)
class TemplateGroup:
    """One template dedup group (CLUS-01), persisted in template_groups."""

    template_id: str  # sha256(template)[:16], mirrors the event_id idiom
    template: str  # masked message
    count: int
    first_ts: str | None  # ISO 8601 string or None
    last_ts: str | None
    severity_max: str  # six-severity CHECK vocabulary
    exemplar_event_ids: list[str]
```
Place the new `cluster_and_label` result dataclass (`cluster_count`/`embedded_count`/`reused_count` per D-05) in `store.py` alongside `TemplateGroup`/`Cluster`, or in `cluster.py` next to the function it returns from — either location fits the existing convention; Claude's Discretion per CONTEXT.md.

---

### `src/sift/pipeline/cluster.py` — `cluster_and_label` reuse gate + splice

**Analog:** same file, existing body (lines 373-399, already shipped, RESEARCH.md's exact excerpt)

**Caller-owns-transaction pattern to preserve** (`cluster.py:373-399`):
```python
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
Any new write this phase adds (dim-rebuild DDL, new `meta` count keys, `set_meta("embedding_reused_count", ...)`) goes inside this same block — do not open a second transaction.

**Ordering constraint** (RESEARCH.md Pitfall 1): read `client.embedding_model` and the new reuse map at the very top of the function, before the single `client.embed(...)` call and before any write — matching the file's existing "embed precedes every write" contract (T-03-22).

**Splice-order constraint** (RESEARCH.md Pitfall 2): build the final `vectors` list by iterating `texts` in original order, looking up either the reuse map or the freshly-embedded (deduplicated) map per text. Never concatenate hits-list + misses-list — this desyncs `vector_rows = list(enumerate(vectors))` (the existing `enumerate(groups)` chunk-id construction at 399/404) from HDBSCAN row order.

**Print-free contract** (`retrieve.py:6`, cited in CONTEXT.md and RESEARCH.md): `cluster.py` stays typer-free/print-free. The D-04 unknown-identity warning and D-09 discard announcement belong at the CLI boundary, not inside `cluster_and_label` — RESEARCH.md's Open Question 2 recommends computing both directly in `cli.py` from `store.get_meta(...)` and `client.embedding_model`, which are already accessible there without needing the pipeline to surface a new field.

---

### `src/sift/cli.py` — `--re-embed` flag, summary line, D-10 wiring

**Analog:** same file, `analyze` (777-845) — existing boolean flag pattern to copy verbatim:
```python
no_label: Annotated[
    bool,
    typer.Option(
        "--no-label",
        help="Skip LLM cluster labels; clusters keep their signature (D-01)",
    ),
] = False,
```
Add `re_embed: Annotated[bool, typer.Option("--re-embed", help="...")] = False` in the same style/position among the other flags.

**Existing `Label: value` summary line to copy** (`cli.py:997-998`):
```python
labelled = sum(1 for c in store.query_clusters() if c.label)
print(f"Clusters: {n_clusters} ({labelled} labelled)")
```
D-06's `Embeddings: {N} new, {M} reused` line goes alongside this, always printed (including M=0), same stdout/no-untrusted-text discipline (counts are ints — the comment above `n_clusters` at line 995 documents why this is safe to print unsanitised).

**Call-site to update** (`cli.py:943`, inside the existing `Progress` block at 927-949):
```python
n_clusters = cluster_and_label(
    store, client, config.clustering, label=not no_label
)
```
becomes a dataclass-returning call; `n_clusters` becomes `result.cluster_count` (or chosen field name), threading `re_embed=re_embed` through. Keep it inside the same `try/except (httpx.HTTPError, ValueError)` block — no behaviour change to the exit-code contract (`docs/decisions/0005-analyze-exit-codes.md`).

**D-10 wiring sketch** (separate plan within the phase, RESEARCH.md Code Examples — shares no code with the vector-reuse path):
```python
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
This replaces the existing `ctx_fallback=config.generation.context or _TRIAGE_CTX_FALLBACK` at `cli.py:989`. `client.props()`/`client.has_props()` already exist at `client.py:510-522` — no new client code.

---

### `docs/decisions/0018-*.md` — new ADR

**Analog:** `docs/decisions/0014-embedding-determinism-scope.md`

Read that file directly for exact section headings/format (Decision / Recorded / Scoped / Deferred / Consequences) before writing 0018. Content is dictated verbatim by D-11: batch-knob changes (`embeddings.context`, `embeddings.batch_size`, `embeddings.max_input_chars`) do NOT invalidate reuse — record, do not re-decide.

---

### Tests

**`tests/test_cluster.py`** — reuse existing fixtures verbatim, do not duplicate:
```python
def _seed(store: CaseStore, messages: list[str]) -> None:
    """Insert one event per message and rebuild template groups (one per msg)."""
    events = [_ev(i, m) for i, m in enumerate(messages)]
    with store.transaction():
        store.insert_events(events)
    dedup.rebuild_template_groups(store)


def _embed_handler(
    calls: list[str] | None = None, *, chat_content: str | None = None
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            if calls is not None:
                calls.append("embeddings")
            data = [
                {"index": i, "embedding": _VECTORS.get(text, [0.0] * 8)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        ...
    return handler


def _client(handler: Handler) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)
```
`_embed_handler`'s `calls` list param is the existing mechanism for asserting an embed call happened/didn't — use it to assert zero-embeds-on-full-reuse (DET-01's first test) and the miss-count-only-embed case, rather than inspecting mock call counts directly (matches D-05's stated goal: assertable from the returned dataclass, not mock internals).

**Return-type migration sites** (exact, from RESEARCH.md's grep-verified enumeration):
| File | Line(s) | Action |
|------|---------|--------|
| `src/sift/cli.py` | 943 | update to read new dataclass field |
| `tests/test_cluster.py` | 127, 181, 195, 225 | update assertions to dataclass field |
| `tests/test_kb_analyze.py` | 177 | no change (discards return) |
| `src/sift/eval/runner.py` | 86 | no change (discards return) |

**`tests/test_store_vectors.py`** — reuse existing helper verbatim:
```python
def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
```
Use `_tables(db)` before/after the dim-rebuild call to assert all four vec0 shadow tables (`vectors_info`, `vectors_chunks`, `vectors_rowids`, `vectors_vector_chunks00`) are replaced together, per RESEARCH.md's empirical verification. The existing hard-raise test (`test_ensure_vectors_table_dim_mismatch_is_hard_error`, line 114) must keep passing completely unmodified — do not touch it; add a new, separate test for the `--re-embed` rebuild path.

**`tests/test_cli.py`** — locate the existing `analyze` CLI test fixture in this file before writing new tests; extend it for `--re-embed` and the `Embeddings: N new, M reused` line rather than rebuilding client-mocking boilerplate (RESEARCH.md Wave-0 gap explicitly flags this — no excerpt captured in this pass since the file wasn't read; planner/executor should `gm_outline`/read `tests/test_cli.py` directly to find the right insertion point).

## Shared Patterns

### Vector (de)serialisation confinement
**Source:** `src/sift/store.py:98-113` (`_vec_to_blob`/`_blob_to_vec`)
**Apply to:** the new `load_vectors_by_text` method only — never re-implement unpacking in `cluster.py` or anywhere else.

### Caller-owns-transaction
**Source:** `src/sift/pipeline/cluster.py:373-399`
**Apply to:** every new write this phase adds (dim-rebuild DDL, new `meta` keys) — all inside the one existing `store.transaction()` block in `cluster_and_label`.

### Typer-free/print-free pipeline boundary
**Source:** comment convention at `src/sift/pipeline/retrieve.py:6`
**Apply to:** `cluster.py` — no `print()`/`typer` calls added there; D-04/D-09 messages computed and printed only in `cli.py`.

### Frozen-dataclass pipeline result
**Source:** `src/sift/store.py:418-429` (`TemplateGroup`)
**Apply to:** the new `cluster_and_label` return type (D-05) — named fields, `@dataclass(frozen=True)`, one-line docstring naming the requirement it satisfies (mirrors `# CLUS-01` style comments throughout `store.py`).

### DDL interpolation safety
**Source:** existing `# noqa: S608` precedent at `store.py:795`, `store.py:898`
**Apply to:** the new dim-rebuild DROP/CREATE DDL — interpolate only `int(dim)` already validated as an int, never raw text.

## Metadata

**Analog search scope:** `src/sift/store.py`, `src/sift/pipeline/cluster.py`, `src/sift/cli.py`, `src/sift/llm/client.py`, `src/sift/pipeline/retrieve.py`, `tests/test_cluster.py`, `tests/test_store_vectors.py`, `docs/decisions/0014-*.md`
**Files scanned:** 8 (all already fully characterised by RESEARCH.md with verified line numbers; this pass added direct reads of `store.py:418-447` for the dataclass idiom, `cli.py:777-1004` for the flag/summary/call-site excerpts, and `tests/test_cluster.py:60-114` + `tests/test_store_vectors.py:1-40` for the test-helper excerpts)
**Pattern extraction date:** 2026-07-28
