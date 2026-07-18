---
phase: 06-renderers-kb-retrieval
verified: 2026-07-18T11:30:48Z
status: passed
score: 4/5 must-haves verified
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:

  - truth: "Installing the sift[pdf] extra enables PDF report rendering — the real weasyprint.HTML(...).write_pdf() produces a valid PDF (REPT-04 / SC4 render leg)"
    test: "In an environment with the extra + pango installed (uv sync --extra pdf; dnf install pango), run `uv run pytest tests/test_render_pdf.py -m live` and/or `uv run sift report <analysed-case> --format pdf --out r.pdf` and open r.pdf."
    expected: "A valid, self-contained PDF is written; no external resource is fetched (url_fetcher rejects all)."
    why_human: "The pango/harfbuzz system library and the sift[pdf] extra are absent in the default socket-blocked suite (by design, ADR 0002). The live test is deselected/skipped here, so the actual PDF byte generation was not exercised. All security, error-path and call-shape legs of SC4 ARE verified network-free (see notes)."
human_verification:

  - test: "uv sync --extra pdf && (dnf install pango) then `uv run pytest tests/test_render_pdf.py -m live` — or render a real PDF via `uv run sift report <case> --format pdf --out r.pdf`."
    expected: "A valid PDF is produced with no external fetch; url_fetcher blocks any attempted resource load."
    why_human: "Real WeasyPrint render needs pango system libs + the optional extra, both absent in the default suite; the render leg is a documented `-m live` test."
---

# Phase 6: Renderers & KB Retrieval Verification Report

**Phase Goal:** A user can hand a colleague a self-contained, reproducible triage report where every claim is one click from its raw evidence
**Verified:** 2026-07-18T11:30:48Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal decomposes into the four ROADMAP success criteria plus the load-bearing anti-hallucination invariant that KB retrieval must not weaken. Four of five are fully verified with passing, network-free behavioural tests exercising the real runtime paths. The fifth (SC4 / REPT-04) is verified for every leg that can run without the optional `sift[pdf]` extra and the pango system library — import-guard, helpful-error, url_fetcher block, self-contained HTML, call shape — but the actual PDF byte generation (real `weasyprint.write_pdf()`) is a deliberately `-m live` test that is skipped in this environment. That render leg is routed to live verification.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1/REPT-01 — `sift report` Markdown: all D-05 sections, working `[evt:id]→#evt-id` anchors, dangling cite stays plain text, appendix file:line + fenced raw truncated to byte cap, degraded banner + FLAGGED surfaced from persisted verdict | ✓ VERIFIED | `render_markdown` (src/sift/render/markdown.py) reads persisted rows only, no client; `_link_citations` gates rewrite on `appendix_ids`; `_truncate_raw` caps at RAW_BYTE_CAP=2048 with elision marker; FLAGGED/degraded read from `citations_valid`/`triage_degraded` meta. tests/test_render_markdown.py + tests/test_cli_report.py pass |
| 2 | SC2/REPT-02+03 — JSON carries full hypotheses object + cluster stats; two runs byte-identical after normalising ONLY D-06 fields; scope documented (ADR 0008) | ✓ VERIFIED | `render_json` uses `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)`+newline; `normalise_for_determinism`/`DETERMINISM_EXCLUDED` is the single D-06 helper. tests/test_report_determinism.py runs network-free (MockTransport, `_no_network` autouse), perturbs only generated_at, asserts raw differs then equal after normalise; drops abs paths + duration keys, retains case-relative. docs/decisions/0008 present |
| 3 | SC3/RAG-07 — pointing analysis at a KB dir demonstrably changes retrieved context | ✓ VERIFIED | migration 5 `kb_chunks` (no event_id col); `index_kb`/`retrieve_kb` (src/sift/pipeline/retrieve.py); `knn_kb_chunks` vec0 KNN. tests/test_kb_retrieval.py: planted chunk returned by KNN(k=1); interrupted embed rolls back to zero rows; chunking deterministic. tests/test_kb_analyze.py: KB runbook text reaches the real triage prompt |
| 4 | SC4/REPT-04 — installing `sift[pdf]` enables PDF rendering, URL fetching disabled | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Security/error/wiring legs VERIFIED network-free: pyproject `pdf=["markdown==3.10.2","weasyprint==69.0"]`, core deps clean, no stray pdf import in core; `render_pdf` import-guarded → PdfExtraMissing (ImportError+OSError) → CLI exit 1 helpful message; `_block_all` url_fetcher rejects every URL; self-contained HTML (inline style, no img). REAL render leg (`write_pdf` producing PDF bytes) is `-m live`, SKIPPED — extra + pango absent here (see Human Verification) |
| 5 | Anti-hallucination invariant preserved (D-01): KB structurally non-citable; a cited KB id is FLAGGED end-to-end; `prompted_ids` event-exemplars-only with and without `--kb` | ✓ VERIFIED | `kb_chunks` has NO event_id column (test_kb_chunks_table_has_no_event_id_column); `_assemble` returns `set(event_ids)` — KB never added; `_apply_kb_block` inserts KB as delimited reference material only. tests/test_kb_analyze.py: no-kb prompt byte-identical baseline, prompted_ids unchanged by kb, AND end-to-end `analyze --kb` citing a KB id → exit 3, `citations_valid=False`, `triage_degraded=1`; valid exemplar citation with --kb still clean (exit 0) |

**Score:** 4/5 truths verified (1 present, behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/sift/render/__init__.py, _util.py, markdown.py | Markdown renderer + shared sanitise/PdfExtraMissing | ✓ VERIFIED | `sanitise` single impl (no cli↔render cycle); pure store function |
| src/sift/render/json_out.py | Canonical JSON + single D-06 helper | ✓ VERIFIED | render_json + normalise_for_determinism |
| src/sift/render/pdf.py | Import-guarded PDF renderer | ✓ VERIFIED (code) | Reuses render_markdown; url_fetcher block; dual-failure→PdfExtraMissing |
| src/sift/store.py::get_events_by_ids | Targeted appendix reader | ✓ VERIFIED | `?`-bound IN(...), `_decode_raw` single path, no whole-case hydrate |
| src/sift/store.py KB methods (_migration_5, ensure_kb_vectors_table, replace_kb_chunks, upsert_kb_vectors, knn_kb_chunks) | Separate non-citable KB namespace | ✓ VERIFIED | kb_chunks no event_id; kb_vectors lazy vec0; reuses _vec_to_blob + embedding_dim guard |
| src/sift/pipeline/retrieve.py::index_kb, retrieve_kb | KB index/retrieve, caller-owns-txn | ✓ VERIFIED | typer-free/print-free; embed via injected client; rglob confined to kb_dir |
| src/sift/pipeline/hypothesise.py (_assemble kb_context, _apply_kb_block) | KB threading, prompted_ids intact | ✓ VERIFIED | prompted_ids=set(event_ids); no-kb byte-identical |
| src/sift/cli.py::report, analyze --kb | CLI wiring | ✓ VERIFIED | report is pure store fn (no client); analyze --kb inside existing client lifecycle |
| src/sift/prompts/triage.md | Sentinel KB block | ✓ VERIFIED | KB_BLOCK_START/END + <<KB_CONTEXT>> slot; prose in template not Python |
| pyproject.toml [project.optional-dependencies] pdf | Extra only, core clean | ✓ VERIFIED | pdf extra present; markdown/weasyprint NOT in core |
| docs/decisions/0007, 0008, 0009 | ADRs | ✓ VERIFIED | All three present |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| cli.report | render_markdown / render_json / render_pdf | lazy import; pure store fn, no InferenceClient | ✓ WIRED |
| render_markdown | store.query_hypotheses/query_clusters/get_meta/get_events_by_ids | direct calls | ✓ WIRED |
| cli.analyze --kb | retrieve.index_kb + retrieve_kb → hypothesise(kb_context=…) → _assemble | inside existing http lifecycle | ✓ WIRED |
| retrieve.index_kb | client.embed → store.ensure_kb_vectors_table/replace_kb_chunks/upsert_kb_vectors | one transaction, embed-before-write | ✓ WIRED |
| _assemble | prompted_ids = set(event_ids) | KB never added | ✓ WIRED |
| render_pdf | render_markdown → markdown → weasyprint.HTML(url_fetcher=BLOCK).write_pdf | in-function import guard | ✓ WIRED (real render live-only) |

### Behavioural Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase-6 renderers + KB + PDF-guard + report CLI | `uv run pytest tests/test_kb_analyze.py tests/test_report_determinism.py tests/test_kb_retrieval.py tests/test_render_pdf.py tests/test_render_markdown.py tests/test_render_json.py tests/test_cli_report.py -q` | 34 passed, 1 deselected | ✓ PASS |
| Real PDF render (pango) | `uv run pytest tests/test_render_pdf.py -m live -q` | 1 skipped (extra+pango absent) | ? SKIP → live |
| ruff on phase source | `uv run ruff check src/sift/render/ .../retrieve.py .../hypothesise.py` | All checks passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| REPT-01 | 06-01 | Markdown report + evidence appendix + inline citations | ✓ SATISFIED | Truth 1 |
| REPT-02 | 06-02 | JSON report full hypotheses + cluster stats | ✓ SATISFIED | Truth 2 |
| REPT-03 | 06-02 | Byte-identical JSON determinism (scoped/documented) | ✓ SATISFIED | Truth 2 |
| REPT-04 | 06-05 | Optional PDF via sift[pdf] extra | ⚠️ SATISFIED (render leg needs live) | Truth 4 |
| RAG-07 | 06-03, 06-04 | KB directory retrieval into triage context | ✓ SATISFIED | Truths 3, 5 |

All 5 declared IDs map to Phase 6 in REQUIREMENTS.md; no orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TBD/FIXME/XXX/HACK/PLACEHOLDER in phase source | none | Clean |

### Human Verification Required

**1. Real PDF render (SC4/REPT-04 render leg)**

**Test:** Install the optional extra and pango system library, then run the live PDF test or render a real report:
`uv sync --extra pdf` and (Fedora) `dnf install pango`, then `uv run pytest tests/test_render_pdf.py -m live` — or `uv run sift report <analysed-case> --format pdf --out r.pdf`.
**Expected:** A valid, self-contained PDF is written; no external resource is fetched (the `url_fetcher` rejects every URL); the report content matches the Markdown render.
**Why human:** The pango/harfbuzz system library and the `sift[pdf]` extra are absent from the default socket-blocked, system-lib-free suite (by design, ADR 0002). The real `write_pdf()` byte generation is a documented `-m live` test that is skipped here. Every other SC4 leg — import-guard, helpful error (exit 1, no traceback), url_fetcher block, self-contained HTML, correct call shape — IS verified network-free and passing.

### Gaps Summary

No blocking gaps. The Markdown (primary) and JSON report paths, the reproducibility/determinism contract, the KB retrieval data path, and — critically — the load-bearing anti-hallucination invariant (KB structurally non-citable; a cited KB id FLAGGED end-to-end at exit 3 with `citations_valid=0`; `prompted_ids` event-exemplars-only with and without `--kb`) are all verified with passing, network-free behavioural tests. The single unexercised item is the real WeasyPrint PDF byte generation, which requires the optional extra plus the pango system library and is a deliberately-scoped `-m live` test — routed to live verification, not a code gap. Phase gate (ruff/pyright/pytest) is clean.

---

_Verified: 2026-07-18T11:30:48Z_
_Verifier: Claude (gsd-verifier)_
