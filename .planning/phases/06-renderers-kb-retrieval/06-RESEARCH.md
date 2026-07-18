# Phase 6: Renderers & KB Retrieval - Research

**Researched:** 2026-07-18
**Domain:** Report rendering (Markdown/JSON/PDF), deterministic serialisation, KB (RAG) retrieval over a separate sqlite-vec namespace
**Confidence:** HIGH (this is an internal-integration phase; almost every seam already exists in-tree and was read directly)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**KB Retrieval (RAG-07)**
- **D-01:** KB runbooks/RCAs live in a **separate index/namespace**, NOT the case events/vectors table. KB chunks are **never assigned event_ids and can never appear in `supporting_event_ids`**. Preserves `cited ⊆ prompted ⊆ store` — only real case events are citable; KB is background reference context that enriches the prompt, not evidence.
- **D-02:** KB content informs the hypothesis prompt as retrieved context but is clearly delimited from citable events so the LLM (and the citation gate) cannot conflate the two.

**Evidence Appendix & Citations (REPT-01)**
- **D-03:** `[evt:a1b2c3d4]` renders as an **intra-document anchor link** (e.g. `[evt:a1b2c3d4](#evt-a1b2c3d4)`) jumping to an evidence-appendix entry — one self-contained file, one click from claim to evidence.
- **D-04:** Each appendix entry shows **file:line provenance + raw text truncated to a configurable cap** (default ~2 KB) with an explicit elision marker.
- **D-05:** Report sections: executive summary, ranked hypotheses (inline citations), evidence appendix, cluster inventory, timeline, unexplained signals, run metadata (models, prompt hashes, config), degraded-run banner when applicable.

**Determinism (REPT-03)**
- **D-06:** Byte-identical JSON comparison **excludes: generated-at timestamps, absolute filesystem paths (case-relative paths retained), and wall-clock durations**. Everything else must be byte-identical.
- **D-07:** Seed is passed through to the server; the determinism claim is **scoped and documented against known llama-server seed caveats**. The reproducibility test normalises the excluded fields, then asserts byte equality.

**PDF Path (REPT-04)**
- **D-08:** PDF = **Markdown → HTML → WeasyPrint** (reuses the Markdown renderer), per ADR 0002, behind the `sift[pdf]` extra.
- **D-09:** **External URL fetching disabled** — custom `url_fetcher` blocks non-local resource fetches (zero-egress invariant).
- **D-10:** When `sift[pdf]` is not installed, `sift report --format pdf` exits with a **helpful message** ("install sift[pdf] and pango") — never a traceback.

### Claude's Discretion
- KB chunking strategy, retrieval `k`, and KB-vs-event share of the prompt budget — resolve against `PromptBudget` (Phase 3) breadth-first truncation; keep KB an additive slice that provably changes retrieved context in a test.
- Exact Markdown section ordering and metadata layout, subject to D-05.
- Cluster labelling is **already resolved**: eager during Phase 3, persisted to `clusters.label`. `sift report` READS persisted labels — do NOT re-label at report time.

### Deferred Ideas (OUT OF SCOPE)
- **REPT-05** — report redaction/sanitisation pass (mask hostnames/IPs/SIDs).
- **REPT-06** — per-cluster event-volume histogram in reports.
- Web/TUI report viewer (v2 candidate per SPEC Non-goals).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPT-01 | `sift report` renders Markdown (primary): exec summary, ranked hypotheses, inline `[evt:…]` citations linked to an evidence appendix (raw text + file:line), cluster inventory, timeline, unexplained signals, run metadata | New `src/sift/render/markdown.py`. Reads `store.query_hypotheses()`, `store.query_clusters()`, `triage_*` meta. **Requires a new `store.get_events_by_ids()` reader** (evidence appendix — see Don't Hand-Roll / Pitfall 1). Anchors: `event_id` is `[0-9a-f]{16}`, an already-safe HTML `id` slug. |
| REPT-02 | JSON report = full hypotheses object + cluster stats | New `src/sift/render/json_out.py`. Assemble from `StoredHypothesis` rows + `triage_timeline_summary`/`triage_unexplained_signals` meta + `Cluster` rows. Canonical serialisation (see Pattern 3). |
| REPT-03 | Identical case+config+model+seed ⇒ byte-identical JSON apart from timestamps (scoped, documented) | Report is a **pure function of `case.db`** (no re-inference). Determinism reduces to canonical serialisation + excluding D-06 fields. Test drives two `analyze` runs against the injectable fake LLM (EVAL-05), renders JSON twice, normalises excluded fields, asserts byte equality. |
| REPT-04 | Optional PDF via `sift[pdf]` extra | New `src/sift/render/pdf.py`. `markdown` → HTML → `weasyprint.HTML(string=…, url_fetcher=<blocker>).write_pdf()`. Import-guarded (D-10). New `[project.optional-dependencies] pdf` in pyproject. |
| RAG-07 | Point analysis at a KB directory; retrieved by similarity into triage context | New `src/sift/pipeline/retrieve.py` + a **separate** `kb_chunks`/`kb_vectors` namespace (migration 5). `sift analyze --kb <dir>`. KB chunks never enter `prompted_ids`, so the citation gate mechanically enforces D-01. |
</phase_requirements>

## Summary

Phase 6 is an **integration phase, not a greenfield one**. Every hard part already exists in-tree and was read directly: the citation gate (`hypothesise.py`), the salience ranking, the vec0 vector store with a confined `_vec_to_blob`/`_blob_to_vec` pair (`store.py`), the batched embedding client (`InferenceClient.embed`), the breadth-first `PromptBudget`, the render-time `_sanitise`, the exit-code discipline (ADR 0005), and the persisted triage output (`hypotheses` table + `triage_*` meta). The phase wires these into three renderers and one KB retrieval slice.

The load-bearing insight for **KB non-citability (D-01)** is that it is enforced *mechanically*, not by prompt wording: the citation gate's allowed set is `prompted_ids`, which is built exclusively from **stored event exemplar ids** in `hypothesise._assemble`. KB chunks are never events, never get an `event_id`, and are never added to `prompted_ids` — so `cited ⊆ prompted ⊆ store` holds by construction even if the model tries to cite a runbook. The prompt delimiting (D-02) is defence-in-depth on top of a guarantee that already holds.

**Determinism (REPT-03)** is far easier than the SPEC's wording suggests, because `sift report` does **no inference** — it reads persisted rows and serialises them. Reproducibility therefore reduces to (a) a canonical, key-sorted JSON dump and (b) excluding the D-06 fields (generated-at, absolute paths, durations). `source_file` is already case-relative (`models.py`), so no absolute path leaks from events. The only wall-clock field in scope is `triage_created_at` meta. The fake-LLM test (EVAL-05) makes the *upstream* analyze deterministic; the report layer is a pure function on top.

**Primary recommendation:** Build in this order — (1) `store.get_events_by_ids()` + `render/json_out.py` + `render/markdown.py` + `report` CLI (REPT-01/02/03, the load-bearing outputs); (2) `pipeline/retrieve.py` + migration 5 + `analyze --kb` (RAG-07); (3) `render/pdf.py` + `sift[pdf]` extra (REPT-04, cleanly deferrable per ADR 0002 if the phase runs hot). Add **zero** runtime dependencies to the core; `markdown` + `weasyprint` land only in the optional `pdf` extra.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read persisted hypotheses/clusters/meta | `store.py` (CaseStore) | — | All persistence flows through the store; renderers never touch SQL |
| Fetch raw + file:line for cited events | `store.py` (new `get_events_by_ids`) | — | Vector/raw access stays confined to store.py (STORE invariant); `_decode_raw` is the single raw read path |
| Markdown assembly + anchors + truncation | `render/markdown.py` (new) | `cli.py` `_sanitise` | Renderers are pure string builders; sanitisation reused from cli |
| Canonical JSON serialisation | `render/json_out.py` (new) | — | stdlib `json` only; pure function of store rows |
| Markdown→HTML→PDF | `render/pdf.py` (new) | `render/markdown.py` | PDF reuses the Markdown renderer (ADR 0002); optional-import isolated here |
| KB directory chunk+embed+persist | `pipeline/retrieve.py` (new) | `store.py` (new kb tables), `llm/client.py` `embed` | Mirrors `cluster_and_label`'s caller-owns-transaction persistence idiom |
| KB similarity retrieval (KNN) | `store.py` (new `knn_kb_chunks`) | `pipeline/retrieve.py` | vec0 `MATCH` query lives in store.py alongside the confined blob pair |
| Thread KB context into the triage prompt | `pipeline/hypothesise.py` (extend `_assemble`) + `prompts/triage.md` | — | KB block inserted before `Evidence:`; header text lives in the template (CLI-02) |
| CLI wiring + exit codes | `cli.py` (`report`, extend `analyze`) | — | Follows ADR 0005 exit contract |

## Standard Stack

### Core
No new **core** runtime dependencies. Everything for Markdown + JSON is stdlib + already-present:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `json` (stdlib) | 3.12+ | Canonical JSON report serialisation | `sort_keys=True`, `ensure_ascii=False`, fixed separators give byte-stable output [VERIFIED: read `store.py` uses `json.dumps(..., sort_keys=True)` for `parse_coverage` already] |
| `importlib.resources` (stdlib) | 3.12+ | Load prompt templates | Already the pattern in `hypothesise._load_triage_template` / `cluster._load_template` [VERIFIED: read in-tree] |
| `pathlib` (stdlib) | 3.12+ | KB directory walk (`Path.rglob("*.md")`) | Boring-tech default |

### Supporting (the `sift[pdf]` extra ONLY — never core, never test-required)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `markdown` | 3.10.2 (PyPI, current) | Markdown → HTML for the PDF path | Only inside `sift[pdf]`. Import-guarded. [VERIFIED: PyPI `pip index versions markdown` → 3.10.2; sanctioned by ADR 0002] |
| `weasyprint` | 69.0 (PyPI, current) | HTML → print-quality PDF | Only inside `sift[pdf]`. Import-guarded. Needs system pango/harfbuzz/gdk-pixbuf. [VERIFIED: PyPI + Context7 official docs `/websites/doc_courtbouillon_weasyprint_stable`; sanctioned by ADR 0002] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `markdown` lib for PDF HTML | Hand-write HTML in `render/markdown.py` from the same model | Duplicates the Markdown structure in two renderers; `markdown` is one `md.convert(text)` call and is already ADR-sanctioned. Keep `markdown`. |
| WeasyPrint | ReportLab | Rejected in ADR 0002 — ReportLab renders neither MD nor HTML (order-of-magnitude more layout code). |
| Separate KB tables in `case.db` | Global KB index at `~/.local/share/sift/kb` (SPEC §10 Q5 "leaning global") | See Open Question 1 — **recommend per-case for MVP**: keeps one-file portability + determinism; global sharing is a clean later optimisation. |
| KB stored in `case.db` | Reuse `chunks`/`vectors` with a "kind" flag | **Rejected — violates D-01.** A shared table risks a KB row leaking an `event_id` or entering `prompted_ids`. A physically separate namespace makes non-citability structural. |

**Installation (adds the optional extra only):**
```bash
# Core install is unchanged and system-dep-free:
uv sync
# PDF extra (opt-in), plus the Fedora system libs WeasyPrint needs:
uv sync --extra pdf          # or: uv pip install 'sift[pdf]'
sudo dnf install pango harfbuzz gdk-pixbuf2   # reference platform
```

## Package Legitimacy Audit

> Only the optional `pdf` extra introduces packages. Both were already vetted at the 01-01 blocking-human legitimacy checkpoint and sanctioned by ADR 0002.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `markdown` (Python-Markdown) | PyPI | 15+ yrs (1.7 → 3.10.2) | very high (tens of M/mo) | github.com/Python-Markdown/markdown | OK | Approved — `[pdf]` extra only |
| `weasyprint` | PyPI | 12+ yrs (0.1 → 69.0) | high | github.com/Kozea/WeasyPrint | OK | Approved — `[pdf]` extra only |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

Both are the correct ecosystem (PyPI), long-lived, high-reputation, with public source repos. Recommend the planner keep the standard practice: pin exact versions in `pyproject`/`uv.lock` and note the pre-existing 01-01 checkpoint sign-off (no new human checkpoint strictly required, but the planner may add one for the `pdf` extra to match project convention).

## Architecture Patterns

### System Architecture Diagram

```
sift report <case> [--format md|json|pdf] [--out <path>]
        │
        ▼
   _case_store(case)                          (existing helper, cli.py:79)
        │  reads persisted rows (NO inference)
        ├── store.query_hypotheses()          → ranked StoredHypothesis rows
        ├── store.query_clusters()            → cluster inventory + labels
        ├── store.get_meta("triage_*")        → timeline, unexplained, model,
        │                                          prompt_hash, degraded, created_at
        └── store.get_events_by_ids(cited)    → NEW: raw + file:line for appendix
        │
        ▼
   render/  (pure string/bytes builders, no SQL, no HTTP)
        ├── markdown.py  ──► Markdown string ──► stdout or --out file   (REPT-01)
        │        │
        │        └──► json_out.py ──► canonical JSON ──► stdout/--out    (REPT-02/03)
        │
        └── pdf.py: markdown.py output ─► markdown.convert ─► HTML
                     ─► weasyprint.HTML(string=…, url_fetcher=BLOCK).write_pdf()  (REPT-04)


sift analyze <case> --kb <dir>                (extend existing analyze path)
        │
        ▼
   pipeline/retrieve.py  (NEW)
        ├─ walk <dir>/**/*.md → chunk → client.embed(texts)   (reuse InferenceClient)
        ├─ store.replace_kb_chunks() + store.upsert_kb_vectors()  (NEW, migration 5)
        └─ build query from top salient cluster text → store.knn_kb_chunks(qvec, k)
        │        returns KB text chunks (NEVER event_ids)
        ▼
   hypothesise._assemble(... kb_context=…)     (extend)
        │  prompt = template + KB block(delimited) + "Evidence:" + [evt:] lines
        │  prompted_ids = {event exemplar ids ONLY}  ← KB never added (D-01 guarantee)
        ▼
   citation gate: cited ⊆ prompted ⊆ store  (unchanged; mechanically excludes KB)
```

### Recommended Project Structure
```
src/sift/
├── render/                  # NEW package (SPEC §7 layout)
│   ├── __init__.py
│   ├── markdown.py          # REPT-01 — pure MD builder, anchors, appendix, banner
│   ├── json_out.py          # REPT-02/03 — canonical serialisation
│   └── pdf.py               # REPT-04 — import-guarded MD→HTML→PDF, url blocker
├── pipeline/
│   └── retrieve.py          # NEW — RAG-07 KB chunk/embed/persist/KNN orchestration
├── prompts/
│   └── triage.md            # EXTEND — add a delimited "Reference material" header
├── store.py                 # EXTEND — migration 5 (kb_chunks/kb_vectors),
│                            #   get_events_by_ids(), knn_kb_chunks(), kb persistence
├── config.py                # EXTEND — optional [kb] section (k, chunk size) if needed
└── cli.py                   # EXTEND — real `report` command; `analyze --kb`
```

### Pattern 1: Renderer = pure function of the store (no HTTP, no re-inference)
**What:** Renderers take an open `CaseStore` (or plain dataclasses read from it) and return `str`/`bytes`. They never call the network, never re-run analyze.
**When to use:** All three renderers.
**Why:** Makes REPT-03 determinism trivial and keeps the zero-egress invariant obviously intact (no client is even constructed in `report`).
```python
# render/markdown.py — shape only
def render_markdown(store: CaseStore) -> str:
    hyps = store.query_hypotheses()
    clusters = store.query_clusters()
    cited_ids = sorted({eid for h in hyps for eid in h.supporting_event_ids})
    events = store.get_events_by_ids(cited_ids)   # NEW store reader
    degraded = store.get_meta("triage_degraded") == "1"
    # ... assemble sections in D-05 order; return one string.
```

### Pattern 2: Stable evidence-appendix anchors (D-03/D-04)
**What:** `event_id` is `sha256(...)[:16]` → always `[0-9a-f]{16}`. That is already a valid, collision-safe HTML `id` and Markdown anchor slug — **no slugify, no escaping needed**.
**Link:** `[evt:a1b2c3d4](#evt-a1b2c3d4)` in hypothesis narratives.
**Target:** an explicit HTML anchor in the appendix so it survives BOTH GitHub-Markdown auto-anchoring *and* WeasyPrint's internal-link resolution (WeasyPrint honours `<a id>`/`#name` internal links — Context7 "internal links target anchor names"):
```markdown
#### <a id="evt-a1b2c3d4"></a>`evt:a1b2c3d4`
`source_file`:`line_start`–`line_end` · severity `error` · `2026-07-18T14:20:01Z`

```
<raw text, zstd-decompressed via store, truncated to cap>
… [truncated 5124 → 2048 bytes]
```
```
- Inline `[evt:…]` tokens in the model's `narrative` are plain text; the renderer must **rewrite** each `[evt:<id>]` occurrence into the anchor link form, and only for ids that are actually in the appendix (a cited-but-missing id stays plain text or is FLAGGED — never a dangling link).
- Raw text goes inside a fenced code block so log bytes cannot inject Markdown. Still run the existing `_sanitise` (strips C0/C1/DEL) on every rendered field — model/DB content is attacker-controlled in a shared `case.db` (WR-01 precedent).

### Pattern 3: Canonical JSON (REPT-02/03)
**What:** One deterministic dump; sort keys; stable separators; no absolute paths; no wall-clock.
```python
# render/json_out.py
import json

def render_json(store: CaseStore) -> str:
    doc = {
        "hypotheses": [ _hyp_to_dict(h) for h in store.query_hypotheses() ],
        "timeline_summary": store.get_meta("triage_timeline_summary") or "",
        "unexplained_signals": json.loads(store.get_meta("triage_unexplained_signals") or "[]"),
        "clusters": [ _cluster_stats(c) for c in store.query_clusters() ],
        "run": {                                   # metadata block
            "model": store.get_meta("triage_model"),
            "prompt_hash": store.get_meta("triage_prompt_hash"),
            "embedding_model": store.get_meta("embedding_model"),
            "degraded": store.get_meta("triage_degraded") == "1",
            # generated_at is EXCLUDED from the determinism comparison (D-06);
            # include it, but the reproducibility test normalises it out.
            "generated_at": store.get_meta("triage_created_at"),
        },
    }
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
```
- `query_hypotheses` returns rows already ordered by `hyp_index`; `query_clusters` has a documented order (count DESC, cluster_id ASC). Ordering is therefore deterministic without extra sorting, but `sort_keys=True` guarantees key order regardless.
- **No floats in scope:** cluster stats are ints/strings/severity; salience scores are not persisted. If any float is ever added, format it fixed (`round`/`format`) — never rely on repr.

### Pattern 4: KB retrieval into a separate namespace (RAG-07, D-01)
**What:** `pipeline/retrieve.py` mirrors `cluster_and_label`'s contract: typer-free, print-free, caller-owns-transaction, embeddings via the injected `InferenceClient.embed`.
**Steps:**
1. Walk `--kb <dir>` for `*.md` (`Path.rglob`), read UTF-8.
2. Chunk each file (see Open Question 2 — recommend paragraph/heading-bounded chunks, ~500–1000 chars, no overlap for MVP determinism).
3. `vectors = client.embed(chunk_texts)` — same model as the case index (dim must match `meta.embedding_dim`; reuse the existing dim-guard idiom).
4. Persist to **separate** `kb_chunks(kb_chunk_id, source_file, ordinal, text)` + `kb_vectors` vec0 table (migration 5). **No `event_id` column exists on these tables** — that is the structural D-01 guarantee.
5. At triage time, build a query vector (embed the concatenated top-N salient cluster excerpts, or embed each and average), then `store.knn_kb_chunks(qvec, k)` → top-k KB texts.
```sql
-- store.knn_kb_chunks — the vec0 KNN idiom already anticipated in store.py:680
SELECT kb.text
FROM kb_vectors v JOIN kb_chunks kb ON kb.kb_chunk_id = v.kb_chunk_id
WHERE v.embedding MATCH ? AND k = ?
ORDER BY distance
```
6. Thread the retrieved texts into the prompt via `_assemble(..., kb_context=[...])`. The KB block is inserted **before** `Evidence:` with a header that lives in `triage.md` (CLI-02: prompt change = template edit). `prompted_ids` is unchanged (event exemplars only).

**KB-vs-event budget share (discretion):** run the KB block through the *same* `PromptBudget` as evidence, but reserve a fixed sub-share for KB (e.g. budget the KB block to ≤25–33% of the fit budget) so KB context can never crowd out citable evidence. Keep evidence breadth-first as today.

### Pattern 5: PDF with egress blocked (REPT-04, D-09) + import guard (D-10)
```python
# render/pdf.py
def render_pdf(store: CaseStore, out: Path) -> None:
    try:
        import markdown as _md
        from weasyprint import HTML
    except ImportError as exc:
        raise PdfExtraMissing(          # caught in cli.py → helpful msg, exit 1
            "PDF output requires the optional extra: install 'sift[pdf]' "
            "and the pango system library (Fedora: dnf install pango)"
        ) from exc

    md_text = render_markdown(store)
    html = _md.markdown(md_text, extensions=["fenced_code", "tables"])

    def _block_all(url: str) -> dict[str, object]:
        # D-09 zero-egress: no external resource is ever fetched. The report is
        # self-contained (inline <style>, no <img>, only internal #anchors), so
        # this fetcher should never be called — but it fails loud if it is.
        raise ValueError(f"external fetch blocked (zero-egress): {url!r}")

    HTML(string=_wrap_html(html), url_fetcher=_block_all).write_pdf(str(out))
```
- **Belt-and-braces:** make the HTML fully self-contained (inline CSS in a `<style>` tag, no images, only `#evt-…` internal links). Then egress is impossible *by content*, and the rejecting `url_fetcher` is defence-in-depth.
- WeasyPrint API note: recent versions also expose a class `weasyprint.urls.URLFetcher(allowed_protocols=…)`; `allowed_protocols=()` blocks everything. The **plain callable** `url_fetcher=` form above is stable across many versions — prefer it and verify against installed 69.x at implementation. [CITED: Context7 doc_courtbouillon_weasyprint_stable — first_steps.html custom URL fetcher; api_reference URLFetcher]

### Anti-Patterns to Avoid
- **Re-labelling clusters at report time.** Labels are eager (Phase 3, `clusters.label`, ADR 0004). `sift report` READS them. Re-labelling would break determinism and touch the network.
- **Constructing an `InferenceClient` in `report`.** Report does zero inference — do not even build the client; keeps zero-egress obvious.
- **`query_events()` to build the appendix.** It hydrates + zstd-decompresses *every* event. The appendix needs only the handful of cited ids → new targeted reader (Pitfall 1).
- **A shared chunks/vectors table for KB with a discriminator flag.** Violates D-01's structural guarantee. Separate tables.
- **Slugifying `event_id` for anchors.** It is already a hex slug; adding a slugify step is dead code.
- **Putting the KB section header string in Python.** Prompt text is template-only (CLI-02). Header lives in `triage.md`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fetch raw+file:line for cited events | A loop over `query_events()` filtering by id | **New `store.get_events_by_ids(ids)`** selecting only those rows, decoding raw via `_decode_raw` | Confines raw/SQL to store.py; avoids decompressing the whole case |
| Vector (de)serialisation for KB | numpy `tobytes` in retrieve.py | `store._vec_to_blob`/`_blob_to_vec` (existing confined pair) | Keeps the sqlite-vec→numpy escape hatch an afternoon's work |
| KNN over KB | numpy brute-force in the pipeline | `store.knn_kb_chunks` (vec0 `MATCH … AND k=?`) | Vector access confined to store.py; vec0 already loaded |
| Token budgeting for KB context | A second budgeter | Existing `PromptBudget.fit` (breadth-first) | Already the label + triage budgeter |
| Markdown → HTML | Hand-written HTML template | `markdown` lib (`[pdf]` extra) | ADR-sanctioned; one call |
| Control-char stripping in output | New sanitiser | `cli._sanitise` (import/relocate) | Existing render-time C0/C1/DEL strip (T-04-01) |
| JSON determinism | Custom encoder | `json.dumps(sort_keys=True, ensure_ascii=False)` | stdlib gives byte-stability |

**Key insight:** the anti-hallucination guarantee is *already load-bearing and mechanical* — do not re-implement or re-check citation validity in the renderer. The renderer just surfaces the persisted per-row `citations_valid` flag as a FLAGGED marker (same as `show hypotheses`, cli.py:530).

## Runtime State Inventory

Not applicable — Phase 6 is additive (new renderers, new KB namespace, new CLI wiring). No rename/refactor/migration of existing stored strings, service config, OS state, secrets, or build artefacts. **None — verified by reading the phase scope (CONTEXT.md) and the additive nature of every task.** The one schema change is an *additive* migration 5 (new `kb_*` tables), not a rewrite of existing tables.

## Common Pitfalls

### Pitfall 1: No `get_events_by_ids` reader exists yet
**What goes wrong:** The evidence appendix (D-04) needs raw text + `source_file`:`line_start`–`line_end` for each cited event id. `store.py` currently offers only `query_events()` (all events, hydrated + all raw decompressed) and `iter_event_rows()` (streams but **does not select `raw`**).
**Why it happens:** Raw was deliberately never streamed during dedup/show for performance (Pitfall 2 comment in store).
**How to avoid:** Add a targeted `store.get_events_by_ids(ids: Sequence[str]) -> dict[str, Event]` (or a lean tuple form with raw+provenance) that `SELECT`s only the cited rows and decodes raw via `_decode_raw`. Confined to store.py.
**Warning signs:** A plan task that says "reuse query_events for the appendix" — that decompresses the whole case.

### Pitfall 2: Cited id not present as a stored event
**What goes wrong:** A FLAGGED (degraded) run persists hypotheses whose `supporting_event_ids` were not all shown/valid. An appendix link to a missing id would dangle.
**Why it happens:** `citations_valid=False` rows are kept visible on purpose (T-04-02).
**How to avoid:** Only rewrite `[evt:id]` → anchor when `id` is in the fetched appendix set. Missing/flagged ids render as plain text plus the existing FLAGGED marker. Never emit a broken link.

### Pitfall 3: KB embedding dimension mismatch
**What goes wrong:** KB embedded with a different model/dim than the case index.
**Why it happens:** `--kb` embeds KB text through the same client but into a separate table; nothing forces the dim to match unless checked.
**How to avoid:** Reuse the STORE-03 dim-guard idiom (`meta.embedding_dim`) for `kb_vectors` — same model, same dim, hard-fail on mismatch. Since KB is embedded in the same `analyze` run as the case, they share the client and dim naturally; still assert it.

### Pitfall 4: Determinism broken by an unstable field sneaking into JSON
**What goes wrong:** `triage_created_at`, an absolute `--out` path, or a duration leaks into the compared bytes.
**Why it happens:** Metadata block is convenient to dump wholesale.
**How to avoid:** The reproducibility test normalises the D-06 excluded set (`run.generated_at`, any path, any duration) before `assertEqual`. `source_file` is already case-relative (`models.py` docstring), so events contribute no absolute paths. Keep the excluded-field list in ONE place the test and any docs reference.

### Pitfall 5: WeasyPrint system libs absent → import succeeds but render crashes
**What goes wrong:** `weasyprint` Python import can succeed while pango/harfbuzz are missing, then `write_pdf` fails deep in cffi.
**Why it happens:** The system-lib dependency is not a Python import.
**How to avoid:** Catch both `ImportError` (extra not installed) **and** the WeasyPrint runtime/OSError at render, mapping both to the same helpful D-10 message ("install sift[pdf] and pango") — never a traceback. Test the missing-extra path by monkeypatching the import to raise.

### Pitfall 6: llama-server seed non-determinism misattributed to the report
**What goes wrong:** REPT-03 is read as "the model is byte-identical", which llama-server does not always guarantee (multi-slot, continuous batching).
**Why it happens:** SPEC wording conflates model determinism with report determinism.
**How to avoid:** Scope the claim (D-07): the **report renderer** is byte-deterministic given identical `case.db`. The test drives the deterministic *fake* LLM (EVAL-05), so the whole chain is reproducible in CI. Document the live-backend caveat in the report's run-metadata and/or a docs/decisions ADR. `sift doctor` already warns on determinism-breaking server configs (LLM-03).

### Pitfall 7: `--format pdf` exit code
**What goes wrong:** Missing extra maps to Typer's usage exit 2, colliding with ADR 0005.
**How to avoid:** Missing extra / render failure is a **failure (exit 1)** with a helpful message, not a usage error (2). Reserve 2 for Typer/Click (bad `--format` value). See CLI wiring below.

## Code Examples

### Rewriting inline citations to anchors (REPT-01)
```python
# render/markdown.py — only link ids that exist in the appendix
import re
_EVT_RE = re.compile(r"\[evt:([0-9a-f]{16})\]")

def _link_citations(narrative: str, appendix_ids: set[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        eid = m.group(1)
        return f"[evt:{eid}](#evt-{eid})" if eid in appendix_ids else m.group(0)
    return _EVT_RE.sub(repl, narrative)
```

### Migration 5: separate KB namespace (RAG-07, D-01)
```python
# store.py — additive migration; NO event_id column anywhere here
def _migration_5(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE kb_chunks (
            kb_chunk_id INTEGER PRIMARY KEY,
            source_file TEXT NOT NULL,   -- runbook path, case-relative or KB-relative
            ordinal     INTEGER NOT NULL,-- chunk index within the file
            text        TEXT NOT NULL    -- the chunk text (NEVER an event, NEVER cited)
        )
        """
    )
    # kb_vectors vec0 table is created lazily (dim unknown until first embed),
    # mirroring ensure_vectors_table — do NOT create it in the migration.
_MIGRATIONS[5] = _migration_5
```

### CLI `report` command (REPT-01/02/04, ADR 0005 discipline)
```python
# cli.py
class ReportFormat(str, Enum):
    md = "md"
    json = "json"
    pdf = "pdf"

@app.command()
def report(
    case: str,
    fmt: Annotated[ReportFormat, typer.Option("--format")] = ReportFormat.md,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    data_dir: DataDirOption = None,
) -> None:
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)            # exit 1 if corrupt/absent
    try:
        if not store.query_hypotheses():
            print("No hypotheses yet; run 'sift analyze' first")
            raise typer.Exit(1)
        if fmt is ReportFormat.pdf:
            if out is None:
                print("Error: --out is required for --format pdf")
                raise typer.Exit(1)
            try:
                from sift.render.pdf import render_pdf, PdfExtraMissing
                render_pdf(store, out)
            except PdfExtraMissing as exc:
                print(f"Error: {exc}")            # D-10: helpful, no traceback
                raise typer.Exit(1) from None
        else:
            text = (render_markdown if fmt is ReportFormat.md else render_json)(store)
            if out is not None:
                out.write_text(text, encoding="utf-8")
            else:
                print(text)
    finally:
        store.close()                            # WAL checkpoint (Pitfall 4 in-tree)
```
- Bad `--format` value → Typer raises exit **2** (usage), untouched (ADR 0005).
- Successful render of a *degraded* case → exit **0** with the degraded banner in the output (rendering succeeded). Do not propagate 3 from `report`; the banner communicates degradation. *(Confirm with planner — see Open Question 3.)*

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SPEC §5.7 "reportlab or weasyprint … decide during implementation" | WeasyPrint behind `sift[pdf]`, URL fetching disabled | ADR 0002 (2026-07-16) | Locked — MD→HTML→PDF reuses the MD renderer |
| SPEC §10 Q3 "cluster labelling eager vs lazy" | Eager at clustering, persisted to `clusters.label` | ADR 0004 | `report` reads labels, never re-labels |
| WeasyPrint `url_fetcher` callable only | Also a `URLFetcher(allowed_protocols=…)` class in recent versions | WeasyPrint ≥60ish | Prefer the callable for version-robustness; verify on 69.x |

**Deprecated/outdated:**
- Nothing deprecated in scope. `markdown` 3.10.2 and `weasyprint` 69.0 are current (2026-07-18).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Per-case KB index (tables in `case.db`) is the right MVP choice over a global `~/.local/share/sift/kb` index | Open Q1, Pattern 4 | If a user shares one KB across many cases, per-case re-embeds each analyze (wasteful but deterministic). Low risk for MVP; global is a clean later switch behind the same store interface. |
| A2 | Paragraph/heading-bounded chunks ~500–1000 chars, no overlap, is adequate KB chunking for MVP | Open Q2, Pattern 4 | Poor chunking → weaker retrieval, but RAG-07's bar is "demonstrably changes retrieved context", which any reasonable chunking meets. Tunable later. |
| A3 | `report` should exit 0 (not 3) when rendering a degraded case | CLI wiring, Open Q3 | If automation expects 3 to propagate through `report`, this differs. Cheap to change; flag for planner/discuss. |
| A4 | WeasyPrint 69.x accepts the plain `url_fetcher=<callable>` argument to `HTML(...)` | Pattern 5 | If the callable form is dropped in 69.x, switch to `URLFetcher(allowed_protocols=())`. Verify at implementation; self-contained HTML already prevents egress regardless. |
| A5 | The `markdown` extensions `fenced_code` + `tables` suffice for the report HTML | Pattern 5 | Missing extension → a section renders as literal text in PDF only; Markdown/JSON unaffected. Verify visually. |
| A6 | Embedding a query vector from top-salient cluster text and KNN-ing KB is the retrieval query strategy | Pattern 4 | A weak query → less relevant KB context; still satisfies the "changes retrieved context" test. Tunable. |

## Open Questions

1. **KB index location: per-case vs global (SPEC §10 Q5).**
   - What we know: CONTEXT D-01 mandates a *separate namespace*, not a location. SPEC §10 Q5 "leans global".
   - What's unclear: whether v1 wants KB shared across cases.
   - Recommendation: **per-case tables in `case.db` for MVP** (portability + determinism + simplest test). Keep all KB access behind the store interface so a global index is a later swap. Record the choice in `docs/decisions/`.

2. **KB chunking strategy + retrieval `k` (Claude's discretion).**
   - Recommendation: heading/paragraph-bounded chunks ~500–1000 chars, no overlap (deterministic); `k` = 3–5; budget KB to ≤⅓ of the fit budget. Make `k` and chunk size a `[kb]` config section if trivial, else in-code constants.

3. **Does `report` propagate the degraded (exit 3) signal, or always exit 0 on a successful render?**
   - Recommendation: exit 0 on successful render; surface degradation via the D-05 banner. Reserve 1 for render/IO/no-hypotheses failure, 2 for Typer usage. Confirm in planning.

4. **Where to embed the KB query strategy** — one averaged query vector vs per-cluster retrieval merged.
   - Recommendation: one query vector (concatenate/average top-N salient cluster excerpts) for MVP simplicity; revisit if eval (Phase 7) shows weak KB hit rate.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python stdlib `json`/`pathlib`/`importlib.resources` | MD + JSON renderers, KB walk | ✓ | 3.12+ | — |
| `sqlite-vec` (vec0, already loaded) | KB KNN | ✓ | 0.1.9 (pinned) | store's BLOB+numpy escape hatch |
| `markdown` (PyPI) | PDF path only | ✓ on PyPI | 3.10.2 | PDF is optional (ADR 0002) |
| `weasyprint` (PyPI) | PDF path only | ✓ on PyPI | 69.0 | PDF is optional |
| pango / harfbuzz / gdk-pixbuf (system) | WeasyPrint runtime | ✗ (not verified installed) | — | PDF opt-in; helpful error (D-10) if absent |
| Fake OpenAI-compatible server (respx/MockTransport) | REPT-03 test, KB test | ✓ | respx 0.23.1 (dev) | — (network is forbidden in tests) |

**Missing dependencies with no fallback:** none block the core (MD/JSON/KB).
**Missing dependencies with fallback:** pango system libs — PDF is optional and errors helpfully when absent (D-10). Verify `dnf install pango` on the reference platform before the PDF task; the planner may add an install/verify step.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (dev group) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `addopts = "-m 'not perf and not live'"` |
| Quick run command | `uv run pytest tests/test_render_markdown.py -x` (per new test file) |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REPT-01 | MD report has all D-05 sections; `[evt:id]` links resolve to appendix anchors; degraded banner present when `triage_degraded=1`; appendix shows file:line + truncated raw + elision marker | unit | `uv run pytest tests/test_render_markdown.py -x` | ❌ Wave 0 |
| REPT-01 | Cited-but-missing/flagged id does NOT emit a dangling link; whole line `_sanitise`d | unit | `uv run pytest tests/test_render_markdown.py -k citation -x` | ❌ Wave 0 |
| REPT-02 | JSON carries full hypotheses object + cluster stats + run metadata; key-sorted | unit | `uv run pytest tests/test_render_json.py -x` | ❌ Wave 0 |
| REPT-03 | Two analyze runs (fake LLM) → render JSON twice → normalise D-06 fields → byte-identical | integration (socket-blocked) | `uv run pytest tests/test_report_determinism.py -x` | ❌ Wave 0 |
| REPT-04 | Missing extra → helpful message, exit 1, no traceback (monkeypatch import to raise) | unit | `uv run pytest tests/test_render_pdf.py -k missing -x` | ❌ Wave 0 |
| REPT-04 | `url_fetcher`/self-contained HTML blocks external fetch (assert fetcher raises / no external refs in HTML) | unit | `uv run pytest tests/test_render_pdf.py -k egress -x` | ❌ Wave 0 |
| RAG-07 | Analyze with `--kb <dir>` vs without → retrieved KB context differs (assert the KB block appears in the assembled prompt / KNN returns the planted chunk) | integration (fake LLM) | `uv run pytest tests/test_kb_retrieval.py -x` | ❌ Wave 0 |
| RAG-07 (D-01) | KB chunk id can NEVER enter `prompted_ids` / `supporting_event_ids` (a model that "cites" a KB chunk is FLAGGED by the gate) | unit | `uv run pytest tests/test_kb_retrieval.py -k noncitable -x` | ❌ Wave 0 |
| CLI | `report` exit codes: 0 success, 1 no-hypotheses/render fail, 2 bad `--format` | unit (CliRunner) | `uv run pytest tests/test_cli_report.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the new test file for the task + `uv run ruff check` + `uv run pyright` (project "done" gate).
- **Per wave merge:** `uv run pytest` (full default suite).
- **Phase gate:** full suite green + ruff + pyright clean before `/gsd-verify-work`. `-m live` PDF-with-real-pango and any live-server checks stay manual UAT (socket-blocked suite by design).

### Wave 0 Gaps
- [ ] `tests/test_render_markdown.py` — REPT-01
- [ ] `tests/test_render_json.py` — REPT-02
- [ ] `tests/test_report_determinism.py` — REPT-03 (reuses the fake-LLM fixture from Phase 4 tests)
- [ ] `tests/test_render_pdf.py` — REPT-04 (monkeypatch import; assert self-contained HTML)
- [ ] `tests/test_kb_retrieval.py` — RAG-07 + D-01 non-citability
- [ ] `tests/test_cli_report.py` — CLI exit-code contract
- [ ] Shared fixture: a fully-analysed `case.db` (events + clusters + persisted hypotheses + `triage_*` meta) built via the existing fake OpenAI-compatible server — likely a `conftest.py` fixture reused across the above.

## Security Domain

> `security_enforcement` treated as enabled (no explicit `false` found). Sift's threat model: untrusted log bytes in a shared `case.db`, plus the zero-egress invariant.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation / Output Encoding | yes | `_sanitise` (C0/C1/DEL strip) on every rendered field; raw log text fenced in code blocks so it cannot inject Markdown/HTML; `[evt:]` anchors built only from validated `[0-9a-f]{16}` ids |
| V5 Injection (SQL) | yes | New `get_events_by_ids`/`knn_kb_chunks` use `?`-bound params and module-constant column lists (S608 convention already in store.py) |
| V10 / SSRF & egress | yes | PDF `url_fetcher` blocks all external fetches; self-contained HTML (no `<img>`/external CSS); `report` constructs NO inference client at all |
| V12 File handling | yes | KB `--kb <dir>` walks user-supplied paths — read-only, UTF-8 decode with error handling; `--out` writes only where the user points |
| V6 Cryptography | no | No new crypto (event_id/prompt_hash sha256 unchanged, not security-sensitive here) |

### Known Threat Patterns for {Markdown/HTML/PDF rendering + user-supplied KB dir}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Log bytes inject Markdown/HTML (e.g. `</style>`, `<script>`, bidi/control chars) into report or PDF | Tampering / Elevation | `_sanitise` strips control chars; raw text fenced; `markdown` output is not `unsafe`-flagged; report has no JS |
| Malicious `[evt:...]` or narrative crafts a link to an external URL | Tampering | Only rewrite ids present in the appendix; anchors are internal `#evt-…` only; never emit `http(s)` links from model text |
| PDF path used to exfiltrate via external resource fetch | Info disclosure (egress) | `url_fetcher` blocks all; HTML self-contained (D-09) |
| KB directory traversal / reading outside the KB dir | Info disclosure | Resolve + confine KB reads to the given dir; `rglob("*.md")` only; no symlink following surprises (mirror ingest's symlink-skip note) |
| Dangling/forged citation presented as valid evidence | Spoofing | Renderer surfaces persisted `citations_valid` as FLAGGED; KB chunks structurally non-citable (D-01) |
| Crash/traceback leaking paths when PDF extra/pango missing | Info disclosure / DoS | D-10 helpful message, exit 1, no traceback (Pitfall 5) |

## Sources

### Primary (HIGH confidence)
- In-tree source read this session: `src/sift/store.py` (vec0 tables, `_vec_to_blob`/`_blob_to_vec`, `query_hypotheses`, `query_clusters`, `iter_event_rows`, `_decode_raw`, migrations, `ensure_vectors_table` dim-guard), `src/sift/pipeline/hypothesise.py` (`_assemble`, `prompted_ids`, citation gate, `_persist` triage_* meta), `src/sift/pipeline/cluster.py` (`cluster_and_label` embed+persist idiom), `src/sift/llm/budget.py` (`PromptBudget.fit`), `src/sift/cli.py` (`report` stub, `analyze`, `show hypotheses`, `_sanitise`, `_case_store`, exit-code discipline), `src/sift/models.py` (Event, HypothesisSet, source_file case-relative), `src/sift/config.py`, `src/sift/prompts/triage.md`.
- `SPEC.md` §5.5, §5.7, §5.8, §10 — renderers, CLI, citation validation, open questions.
- `docs/decisions/0002-weasyprint-pdf-extra.md`, `0005-analyze-exit-codes.md` — PDF approach + exit contract.
- `.planning/phases/06-renderers-kb-retrieval/06-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`.

### Secondary (MEDIUM confidence)
- Context7 `/websites/doc_courtbouillon_weasyprint_stable` — `HTML(string=…)`, custom `url_fetcher`, `URLFetcher(allowed_protocols=…)`, internal anchor links (fetched 2026-07-18).
- PyPI `pip index versions` — `weasyprint` 69.0, `markdown` 3.10.2 (checked 2026-07-18).

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new core deps; MD/JSON are stdlib; `markdown`/`weasyprint` verified on PyPI + ADR-sanctioned.
- Architecture: HIGH — every reuse seam read directly in-tree; KB non-citability guarantee traced through `prompted_ids`.
- Pitfalls: HIGH — derived from actual store/CLI code (missing `get_events_by_ids`, streaming-no-raw, dim-guard, exit-code collisions).
- PDF specifics (`url_fetcher` exact 69.x shape): MEDIUM — verify callable vs class form at implementation (A4).
- KB chunking/k/location: MEDIUM — Claude's-discretion recommendations, tunable against Phase 7 eval.

**Research date:** 2026-07-18
**Valid until:** ~2026-08-17 (30 days; stable stack, internal-integration phase)
