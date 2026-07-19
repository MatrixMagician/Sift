# Phase 6: Renderers & KB Retrieval - Pattern Map

**Mapped:** 2026-07-18
**Files analysed:** 9 (5 new, 4 modified)
**Analogs found:** 9 / 9 (every seam exists in-tree — this is an integration phase)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/render/__init__.py` (new) | package init | — | `src/sift/pipeline/__init__.py` | exact |
| `src/sift/render/markdown.py` (new) | renderer/utility | transform (store→str) | `src/sift/cli.py` `show hypotheses/clusters` (530-591) | role-match |
| `src/sift/render/json_out.py` (new) | renderer/utility | transform (store→str) | `store.query_hypotheses`/`query_clusters` consumers | role-match |
| `src/sift/render/pdf.py` (new) | renderer/utility | transform (str→bytes/file) | `render/markdown.py` (this phase) + import-guard idiom | partial (no PDF analog in tree) |
| `src/sift/pipeline/retrieve.py` (new) | service/pipeline | batch embed + persist + KNN | `src/sift/pipeline/cluster.py` `cluster_and_label` (277-346) | exact |
| `src/sift/store.py` (modify) | store/model | CRUD + migration + vec0 KNN | `_migration_4` (236), `ensure_vectors_table` (660), `upsert_vectors` (706), `query_hypotheses` (844) | exact |
| `src/sift/prompts/triage.md` (modify) | config/template | — | `src/sift/prompts/triage.md` (existing) | exact |
| `src/sift/cli.py` (modify: `report`, `analyze --kb`) | controller/CLI | request-response | `analyze` (632-834), `doctor`, `_case_store` (79) | exact |
| `pyproject.toml` (modify: `[pdf]` extra) | config | — | existing `[project]` deps table | role-match |

## Pattern Assignments

### `src/sift/render/markdown.py` (renderer, transform) — REPT-01

**Analogs:** `cli.py` `show hypotheses` (lines 508-538), `_sanitise` (57-76); `store.py` readers.

**Renderer = pure function of the store** (no HTTP, no client, no re-inference). Signature `render_markdown(store: CaseStore) -> str`. Reads only:
- `store.query_hypotheses()` (store.py:844-870) — ranked `StoredHypothesis` rows, already ordered by `hyp_index`, each with `.citations_valid` and `.supporting_event_ids`.
- `store.query_clusters()` (store.py:766-804) — cluster inventory, ordered count DESC / cluster_id ASC, `.label` already persisted (never re-label).
- `store.get_meta("triage_*")` (store.py:872) — `triage_timeline_summary`, `triage_unexplained_signals`, `triage_model`, `triage_prompt_hash`, `triage_degraded`, `triage_created_at` (keys set in `hypothesise._persist`, lines 431-443).
- **NEW** `store.get_events_by_ids(cited_ids)` — evidence appendix raw+provenance (see store section below).

**FLAGGED / degraded pattern to mirror** (`cli.py:518-537`):
```python
if store.get_meta("triage_degraded") == "1":
    # emit degraded banner (D-05)
for h in hyps:
    marker = "OK" if h.citations_valid else "FLAGGED"   # surface persisted verdict; never recompute the gate
```

**Sanitisation — reuse, do not re-implement** (`cli.py:57-76`). Every rendered field (titles, narratives, cited ids, cluster labels, raw appendix text) is attacker-controlled in a shared `case.db` (WR-01). Apply `_sanitise` to each rendered field/line; import or relocate it (currently a private cli function — plan should move it to a shared `render`/util module rather than import from `cli`). Raw appendix text additionally goes inside a fenced code block so log bytes cannot inject Markdown.

**Citation-anchor rewrite (D-03, Pattern 2/Code Example in RESEARCH):** `event_id` is `sha256(...)[:16]` → always `[0-9a-f]{16}`, a valid HTML/Markdown anchor slug — no slugify. Only rewrite `[evt:<id>]` → `[evt:<id>](#evt-<id>)` when `<id>` is in the fetched appendix set (Pitfall 2: never emit a dangling link). Appendix target uses an explicit `<a id="evt-...">` anchor (survives GitHub auto-anchoring + WeasyPrint internal-link resolution).

---

### `src/sift/render/json_out.py` (renderer, transform) — REPT-02/03

**Analog:** same store readers; canonical-dump precedent in `store.py` (already uses `json.dumps(..., sort_keys=True)` for `parse_coverage`).

**Canonical serialisation:** `json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n"`. Pure function of the store. Assemble `hypotheses` (from `query_hypotheses`), `clusters` (from `query_clusters`), `timeline_summary`/`unexplained_signals`/run-meta from `get_meta`. `unexplained_signals` is stored JSON → `json.loads(get_meta("triage_unexplained_signals") or "[]")`.

**Determinism (D-06):** include `generated_at` (`triage_created_at`) in the doc but the reproducibility test normalises it out along with any absolute path / duration. `source_file` is already case-relative (`models.py:26,41`) so events leak no absolute paths. No floats in scope (cluster stats are ints/strings; salience not persisted) — if a float is ever added, format fixed, never repr.

---

### `src/sift/render/pdf.py` (renderer, transform) — REPT-04

**Analog:** none in-tree for PDF; reuses `render_markdown` output. Import-guard idiom modelled on the optional-dependency error discipline in `cli.py` (`_case_store` helpful-message + `typer.Exit(1)`, lines 84-96).

**Shape (RESEARCH Pattern 5):**
```python
def render_pdf(store: CaseStore, out: Path) -> None:
    try:
        import markdown as _md
        from weasyprint import HTML
    except ImportError as exc:
        raise PdfExtraMissing("...install 'sift[pdf]' and pango (dnf install pango)") from exc
    md_text = render_markdown(store)
    html = _md.markdown(md_text, extensions=["fenced_code", "tables"])
    def _block_all(url: str) -> dict[str, object]:      # D-09 zero-egress
        raise ValueError(f"external fetch blocked (zero-egress): {url!r}")
    HTML(string=_wrap_html(html), url_fetcher=_block_all).write_pdf(str(out))
```
- Belt-and-braces: self-contained HTML (inline `<style>`, no `<img>`, only `#evt-` internal links) so egress is impossible by content; the rejecting `url_fetcher` is defence-in-depth.
- Catch BOTH `ImportError` (extra absent) AND WeasyPrint runtime/OSError (pango missing, Pitfall 5) → same helpful message, exit 1, never a traceback.

---

### `src/sift/pipeline/retrieve.py` (service, batch embed + persist + KNN) — RAG-07

**Analog:** `pipeline/cluster.py` `cluster_and_label` (lines 277-346) — the caller-owns-transaction embed+persist idiom to mirror exactly.

**Contract to copy:** typer-free, print-free, embeddings via the injected `client.embed` (client.py:204), caller owns the transaction. Steps:
```python
groups... texts = [...]           # here: chunk KB *.md files
vectors = client.embed(texts)     # cluster.py:300 — same batched call, same model
dim = len(vectors[0])
with store.transaction():         # cluster.py:333 — one transaction wraps all writes
    store.ensure_kb_vectors_table(dim)   # mirror ensure_vectors_table (660): dim-guard, lazy vec0
    store.replace_kb_chunks(chunks)      # mirror replace_chunks (725)
    store.upsert_kb_vectors(rows)        # mirror upsert_vectors (706): _vec_to_blob, DELETE-then-INSERT
```
- KB walk: `Path.rglob("*.md")`, UTF-8, confined to the given dir (V12 traversal control).
- Chunking (discretion): heading/paragraph-bounded ~500-1000 chars, no overlap (deterministic).
- Dim guard (Pitfall 3): reuse the STORE-03 `meta.embedding_dim` idiom — KB shares the case's client/model/dim; still assert.
- Query: embed top-N salient cluster excerpts, `store.knn_kb_chunks(qvec, k)` → KB texts. Budget the KB block through the existing `PromptBudget.fit` (budget.py:49), reserving ≤⅓ so KB never crowds out evidence.
- **D-01 is structural:** KB rows have NO `event_id` column and never enter `prompted_ids` — the citation gate (`hypothesise._all_cited_within`, 338-345) mechanically excludes them.

---

### `src/sift/store.py` (store, CRUD + migration + vec0 KNN) — REPT-01/RAG-07

**Analogs (all in this file):**

**Migration 5 — mirror `_migration_4` (236-261) + registration (264-269):**
```python
def _migration_5(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE kb_chunks (
        kb_chunk_id INTEGER PRIMARY KEY,
        source_file TEXT NOT NULL,
        ordinal     INTEGER NOT NULL,
        text        TEXT NOT NULL)""")   # NO event_id column anywhere — the D-01 guarantee
_MIGRATIONS[5] = _migration_5
```
The `kb_vectors` vec0 table is created lazily (dim unknown until first embed) — do NOT put it in the migration; mirror `ensure_vectors_table` (660-686).

**`get_events_by_ids(ids)` — NEW confined reader (Pitfall 1, Don't Hand-Roll).** Model on `query_events` (530-555) but SELECT only the cited rows and decode raw via `_decode_raw` (the single raw read path, used at line 552). Do NOT reuse `query_events` (decompresses the whole case) or `iter_event_rows` (570-593, never selects raw). Use `?`-bound params / module-constant column list (S608 convention, e.g. line 588).

**`ensure_kb_vectors_table` / `upsert_kb_vectors` / `replace_kb_chunks` — mirror the confined vector idiom:**
- `_vec_to_blob` (91-99) / `_blob_to_vec` (102-106) — the SINGLE vector (de)serialisation pair; all KB vector bytes go through these (confinement invariant + numpy escape hatch).
- `ensure_vectors_table` (660-686) — lazy vec0 DDL + `embedding_dim` dim-guard to copy.
- `upsert_vectors` (706-723) — DELETE-then-INSERT (vec0 has no `INSERT OR REPLACE`), caller owns transaction.
- `replace_chunks` (725-741) — DELETE-then-executemany, module-constant column list.

**`knn_kb_chunks(qvec, k)` — vec0 KNN idiom** (anticipated by the `WHERE embedding MATCH ? AND k = ?` comment at store.py:679-680):
```sql
SELECT kb.text FROM kb_vectors v JOIN kb_chunks kb ON kb.kb_chunk_id = v.kb_chunk_id
WHERE v.embedding MATCH ? AND k = ? ORDER BY distance
```
Bind `_vec_to_blob(qvec)` and `k`; confined to store.py alongside the blob pair.

---

### `src/sift/prompts/triage.md` (config/template) — RAG-07 D-02

**Analog:** the existing `triage.md` (header comment lines 1-4 documents the CLI-02 template-only rule; `Evidence:` marker at line 36).

Add a delimited "Reference material" / KB header **before** `Evidence:` — prompt text lives in the template, never in Python (CLI-02). `hypothesise._assemble` (160-197) inserts the KB block between the template and the `[evt:]` evidence lines; `prompted_ids` (line 197, `set(event_ids)`) stays event-exemplars-only.

---

### `src/sift/cli.py` (controller, request-response) — REPT-01/02/04 + RAG-07

**Analogs:** the `report` stub (837-841), `analyze` (632-834), `doctor`, `_case_store` (79-96), `_sanitise` (57-76).

**`report` command — replace stub, follow ADR 0005 exit contract** (mirrors `analyze` 808-834 and `_case_store`):
- `store = _case_store(case, config)` (line 79) — exit 1 if corrupt/absent, with `_sanitise`d message.
- No hypotheses → helpful message, exit 1 (mirror `show hypotheses` 513-515 message, but exit 1 for report).
- `try/finally: store.close()` — WAL checkpoint on every path (analyze 831-834; show 592-594).
- Bad `--format` value → Typer usage exit **2** (untouched, ADR 0005). Missing `sift[pdf]` extra / render failure → exit **1** with helpful message, never 2 or a traceback (Pitfall 7).
- Successful render of a degraded case → exit **0** with the D-05 banner in output (do NOT propagate 3; RESEARCH Open Q3 — confirm with planner). Contrast `analyze` which raises `typer.Exit(3)` on degrade (line 828).
- `--out` writes `text.write_text(..., encoding="utf-8")`; else `print(text)`.

**`analyze --kb <dir>` extension:** add a `--kb` `typer.Option` (mirror the option block style, e.g. `--hint` 652-658). Insert the KB build/retrieve step inside the existing http-client lifecycle, between `cluster_and_label` (775-777) and `hypothesise(...)` (789-799), so the same injected client embeds both. Wrap embed failures as `typer.Exit(1)` with `_sanitise`d message (mirror 778-780). Thread retrieved KB context into `hypothesise(...)` via a new `kb_context=` parameter.

**`pyproject.toml`:** add `[project.optional-dependencies] pdf = ["markdown==3.10.2", "weasyprint==69.0"]`. Core install stays system-dep-free (RESEARCH Standard Stack).

## Shared Patterns

### Render-time sanitisation
**Source:** `cli.py:57-76` `_sanitise` (strips C0/C1/DEL + Cf format chars).
**Apply to:** every rendered field in `markdown.py`, `json_out.py`, and the appendix raw text. Model/DB content is attacker-controlled in a shared `case.db` (WR-01, T-04-01). Plan should relocate `_sanitise` to a shared module (render or a small util) rather than importing from `cli.py`.

### Confined vector access + escape hatch
**Source:** `store.py` `_vec_to_blob`/`_blob_to_vec` (91-106), `ensure_vectors_table` (660), `upsert_vectors` (706).
**Apply to:** all KB vector work — it lives in `store.py` only, so swapping sqlite-vec for a numpy brute-force scan stays an afternoon's work.

### Caller-owns-transaction persistence
**Source:** `cluster.py:333` `with store.transaction():` wrapping `ensure_vectors_table` + `upsert_vectors` + `replace_chunks`; also `hypothesise._persist` (429-443).
**Apply to:** `pipeline/retrieve.py` KB persistence — one transaction, so an interrupted embed rolls back to zero KB rows.

### Citation gate is load-bearing and mechanical — never re-check in the renderer
**Source:** `hypothesise._all_cited_within`/`_row_citations_valid` (333-345); persisted per-row `citations_valid` (store.py:858-869).
**Apply to:** renderers surface the persisted `citations_valid` flag as FLAGGED (like `cli.py:530`); they do NOT recompute citation validity. KB non-citability (D-01) holds by construction because `prompted_ids` is event-exemplars-only.

### CLI exit-code discipline (ADR 0005)
**Source:** `analyze` (808-830: 1=fail, 3=degrade, 0=success), `_case_store` (1=absent/corrupt), Typer reserves 2 for usage.
**Apply to:** `report` — 0 success, 1 no-hypotheses/render/IO/missing-extra failure, 2 bad `--format` (Typer). Report does not propagate 3 (Open Q3).

### Prompt templates are edits, not code
**Source:** `hypothesise._load_triage_template` (79-82), `cluster._load_template` (191-194) via `importlib.resources`; `triage.md` header comment.
**Apply to:** the KB reference-material header — template edit only (CLI-02).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/sift/render/pdf.py` | renderer | transform | No PDF/WeasyPrint code exists in-tree yet. Reuses `render_markdown` output + the optional-import + helpful-error idiom from `_case_store`; WeasyPrint `url_fetcher` shape verified against Context7 docs (RESEARCH Pattern 5, A4). |

## Metadata

**Analog search scope:** `src/sift/store.py`, `src/sift/cli.py`, `src/sift/pipeline/{hypothesise,cluster}.py`, `src/sift/llm/{budget,client}.py`, `src/sift/models.py`, `src/sift/prompts/triage.md`.
**Files scanned:** 9 source files (all reuse seams read directly).
**Pattern extraction date:** 2026-07-18
</content>
</invoke>
