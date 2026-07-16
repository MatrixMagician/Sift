# Stack Research

**Domain:** Local-first, privacy-preserving LLM-powered incident/log triage CLI (Python)
**Researched:** 2026-07-16
**Confidence:** MEDIUM (versions verified against PyPI registry and official docs; provider tiers assigned via classify-confidence seam)

**Mandate:** SPEC.md prescribes the stack; this document validates it rather than proposing alternatives. Verdict up front: **the SPEC stack survives pressure-testing intact.** Every prescribed choice is current and fit for purpose. The open questions (Typer vs argparse, PDF library, drain3 vs hand-rolled) are resolved below with recommendations.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12+ (3.13 fine) | Language | SPEC constraint; 3.12 gives `itertools.batched`, improved error messages, per-interpreter GIL groundwork. Do not require 3.14 yet (see zstandard note) |
| uv | latest (self-updating) | Dependency/venv/tool management | SPEC constraint; `uv tool install` is the packaging target for M8 |
| httpx | 0.28.1 | OpenAI-compatible HTTP client | Latest release (Dec 2024, still current Jul 2026 — stable, slow-moving). Sync client is sufficient; timeouts, connection pooling, and `base_url` per role built in. No vendor SDK, per SPEC |
| Pydantic | 2.13.x | Schema validation for hypothesis JSON contract, config | Current 2.13.4 (May 2026). `model_json_schema()` output feeds directly into llama.cpp schema-constrained decoding; `model_validate_json` is the enforcement backstop |
| SQLite (stdlib `sqlite3`) + sqlite-vec | sqlite-vec 0.1.9 | Case store + vector KNN | Zero-daemon, one `case.db` per case, per SPEC. See maturity notes below |
| scikit-learn | 1.9.0 | HDBSCAN clustering + agglomerative fallback | `sklearn.cluster.HDBSCAN` (in sklearn since 1.3) covers the semantic-clustering stage AND the agglomerative fallback in one dependency — the standalone `hdbscan` package is redundant here (see Alternatives) |
| Typer | 0.27.0 | CLI framework | Actively released (Jul 2026). Resolves SPEC open question #1 — recommendation: **Typer**, rationale below |
| zstandard | 0.25.0 | Compress `raw` event text > 4 KB | Maintained (Sep 2025 release). Required because Python floor is 3.12; stdlib `compression.zstd` only exists from 3.14 |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | 2.x (sklearn dependency) | Vector serialisation to sqlite-vec (`float32` little-endian blobs), cosine maths | Comes free with scikit-learn; use `np.asarray(embedding, dtype=np.float32).tobytes()` for sqlite-vec inserts |
| markdown | 3.x | Markdown → HTML for the PDF path | Only inside the optional `sift[pdf]` extra |
| WeasyPrint | 69.0 | HTML → PDF | Only inside `sift[pdf]`; resolves SPEC open question #2, rationale below |
| PyYAML | 6.x | `truth.yaml` in the eval harness | M7 only. (`tomllib` is stdlib for config/thresholds — prefer TOML wherever Sift owns the format; YAML only for eval truth files if human-authoring ergonomics matter, else use TOML there too and drop PyYAML entirely) |
| respx | 0.22.x | Mock httpx in tests (fake OpenAI-compatible server) | Test-only; SPEC names it. Keeps the zero-network-in-tests rule enforceable |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ruff | Lint + format | Part of the "done" gate per SPEC §9 |
| pyright | Type checking | Part of the "done" gate; strict mode recommended from M1 so it never becomes a retrofit |
| pytest | Test runner | Fixtures include per-adapter sample artefacts |

## Installation

```bash
# Core runtime
uv add httpx pydantic sqlite-vec scikit-learn typer zstandard

# Optional PDF extra (declare as [project.optional-dependencies] pdf = [...])
uv add --optional pdf markdown weasyprint

# Dev
uv add --dev pytest respx ruff pyright pyyaml
```

## Validation Findings (the questions asked)

### 1. sqlite-vec — maturity and API

- **Current:** PyPI 0.1.9 (2026-03-31); upstream on a 0.1.10-alpha track. **Pre-v1 software.**
- **History to know:** development visibly stalled in H1 2025 (GitHub issue #226 "is this maintained?"), then resumed with 2026 releases. Single-maintainer risk is real but acceptable: the extension is small pure C, the stable API surface is tiny, and Sift's usage (one vec0 table, brute-force KNN) touches only the oldest, most-tested code path.
- **API confirmed (Context7, official docs):** `import sqlite_vec; db.enable_load_extension(True); sqlite_vec.load(db)`. Create `create virtual table vectors using vec0(chunk_id integer primary key, embedding float[<dim>])`; KNN is `where embedding match ? and k = ? order by distance`. Metadata columns (up to 16) can be filtered in the KNN `WHERE` clause — useful if cluster-scoped retrieval is ever needed. Max 8192 dims (nomic/bge are 768/1024 — no issue).
- **Caveat:** stable path is brute-force scan. Fine to ~100K vectors; SPEC's tens-of-thousands scale is comfortably inside. ANN modes (IVF/DiskANN) are experimental — do not use them.
- **Caveat:** `sqlite3.enable_load_extension` requires the interpreter's SQLite to permit extension loading. Fedora's python3 does; some macOS system Pythons don't. `sift doctor` should verify `vec_version()` loads and report it.
- **Verdict: keep.** Record embedding dimension in `meta` and hard-fail on mismatch, exactly as SPEC prescribes. Confidence: MEDIUM.

### 2. hdbscan vs scikit-learn's HDBSCAN

- Standalone `hdbscan` 0.8.44 (2026-06-01) is still maintained. `sklearn.cluster.HDBSCAN` has been in scikit-learn since 1.3; current sklearn is 1.9.0.
- **They are not identical:** sklearn's `min_samples` includes the point itself (add 1 to match standalone results); `cluster_selection_epsilon` behaviour differs; sklearn lacks soft clustering (`membership_vector`) and `approximate_predict`.
- Sift needs none of the standalone extras: it clusters template exemplars once per case, batch, no prediction on new points.
- **Verdict: use `sklearn.cluster.HDBSCAN` and do not add the standalone package.** scikit-learn is required anyway for the agglomerative fallback (`AgglomerativeClustering` with `metric="cosine"`, `distance_threshold` from config), so this deletes one compiled dependency with zero capability loss. Confidence: MEDIUM.

### 3. Typer vs argparse (SPEC open question #1)

- Typer 0.27.0 released 2026-07-15 — very actively maintained.
- Dependency cost: standard `typer` pulls `click`, `typing-extensions`, `rich`, `shellingham`. If that offends, `typer-slim` drops rich/shellingham.
- **Verdict: Typer.** The CLI surface is non-trivial — seven subcommands, repeated `--adapter glob=name` options, per-command flags — and Typer gives typed parameters that pyright checks, auto-generated help, and shell completion for roughly four packages of dependency cost. argparse is the correct call only if the dependency budget is absolute; it is explicitly sanctioned by SPEC, so this is preference not correctness. Record the decision in `docs/decisions/`. Confidence: MEDIUM.

### 4. zstandard bindings

- `zstandard` 0.25.0 (2025-09-14), maintained (Gregory Szorc). This is the canonical binding; do not use `zstd` or `pyzstd`.
- Python 3.14 shipped stdlib `compression.zstd`, but the project floor is 3.12 — the package stays. Note the future deletion: when the floor reaches 3.14, swap to stdlib and drop the dependency.
- **Verdict: keep `zstandard` 0.25.x.** Confidence: MEDIUM.

### 5. Structured output against llama.cpp

Confirmed from the current llama-server README (2026-07):

- `response_format` accepts `{"type": "json_object"}` and `{"type": "json_schema", "schema": {...}}`. **Gotcha: the nesting is NOT OpenAI's.** OpenAI puts the schema at `response_format.json_schema.schema`; llama.cpp expects it at `response_format.schema` directly (historical issues #10732, #11847 document clients breaking on this). Sift's client must send llama.cpp's shape when talking to llama-server/Lemonade-GGUF — feature-detect or just use the llama.cpp shape since remote OpenAI is out of scope anyway.
- Non-standard request fields also exist: top-level `json_schema` and `grammar` (GBNF). Specifying both `json_schema` and `grammar` is a hard error. External `$ref` in schemas is unsupported — keep the hypothesis schema self-contained (Pydantic's `model_json_schema()` inlines by default with `ref_template` tweaks; verify no `$defs` indirection trips the converter, or flatten).
- Grammar-constrained decoding guarantees syntactic shape only, not semantic validity — the SPEC's Pydantic-validate → one repair round-trip → degrade pipeline remains load-bearing. Keep it regardless of server-side constraints.
- **Verdict: SPEC §5.5 enforcement pipeline is correct as written.** Confidence: MEDIUM.

### 6. Embeddings via llama-server

Confirmed from the current README:

- `--embedding`/`--embeddings` flag **restricts the server to embedding-only use** — so generation and embeddings genuinely need two server instances (or Lemonade managing both). SPEC's per-role `base_url` design is validated as necessary, not optional.
- `/v1/embeddings` (OpenAI-compatible) requires pooling ≠ `none` and returns Euclidean-normalised vectors. `--pooling {none,mean,cls,last,rank}`; model default applies if unspecified (nomic/bge GGUFs carry sane defaults — mean/cls).
- Normalised output means cosine distance and L2 distance rank identically — pick one in sqlite-vec (`distance_metric=cosine` on the vec0 column or default L2) and record it in `meta`.
- `/props` and `/tokenize` exist for feature-detection and the `PromptBudget` tokenize path, exactly as SPEC §5.6 assumes.
- **Verdict: SPEC assumptions all hold.** Confidence: MEDIUM.

### 7. Lemonade Server compatibility

- OpenAI-compatible base URL `http://localhost:13305/v1` (**default port 13305 in current versions — older docs say 8000; make the port config-only, never assumed**).
- Supports `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/models`; `response_format` and `tools` accepted.
- **Critical compat note:** `/v1/embeddings` works **only for models loaded via the `llamacpp` or `flm` recipes; ONNX/OGA-recipe models do not support embeddings.** On Strix Halo, users may default to NPU/OGA models for chat — `sift doctor` must actually round-trip an embedding call, not just check `/v1/models`, and report this failure mode by name.
- GGUF models in Lemonade route through llama.cpp, so structured-output behaviour matches llama-server (same `response_format.schema` nesting).
- **Verdict: compatible; encode the embeddings-recipe caveat into `sift doctor`.** Confidence: MEDIUM.

### 8. Template mining: drain3 vs hand-rolled (SPEC open question, implied)

- `drain3` 0.9.11: **last release 2022-07-17**, metadata claims Python 3.7–3.11 only. Effectively dormant; wrong tool for a 3.12+ project in 2026.
- Hand-rolled masking (regexes for numbers, hex, UUIDs, SIDs, OIDs, paths, timestamps → placeholders, then group by masked string) is ~50 lines, fully deterministic, auditable, and tunable per adapter — which matters because DSSErrors SIDs/OIDs need domain-specific masks drain3 would never learn cleanly.
- **Verdict: hand-rolled masking, as SPEC §5.4 already describes. Do not add drain3.** Confidence: MEDIUM.

### 9. PDF: reportlab vs weasyprint (SPEC open question #2)

- ReportLab 5.0.0 (2026-06): pure Python since 4.0, no system deps — but it is a programmatic canvas/flowables API. It does not render Markdown or HTML; a Sift PDF renderer on ReportLab means hand-writing layout code for every report element. That is the expensive path disguised as the light one.
- WeasyPrint 69.0 (2026-06): renders HTML+CSS to print-quality PDF; the pipeline is trivially `markdown → HTML → PDF`, reusing the Markdown renderer that already exists. Cost: system libraries (pango, harfbuzz, gdk-pixbuf) that pip cannot install. On Fedora (reference platform) these are one `dnf install` away; the Quadlet container can bake them in.
- **Verdict: WeasyPrint behind an optional extra `sift[pdf]`, implemented in M6 or deferred post-M8.** Core `uv tool install sift` stays system-dep-free; `sift report --format pdf` errors helpfully ("install sift[pdf] and pango") when the extra is absent. Do not use ReportLab — its zero-system-deps advantage is bought with an order of magnitude more rendering code. Confidence: MEDIUM.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| sklearn.cluster.HDBSCAN | standalone `hdbscan` 0.8.44 | Only if soft clustering / `approximate_predict` becomes a requirement (it isn't in v1) |
| Typer | argparse (stdlib) | If the dependency budget becomes absolute; SPEC permits either |
| sqlite-vec | Plain BLOB columns + numpy brute-force | If sqlite-vec maintenance dies again before v1; at Sift's scale (<100K vectors) numpy cosine over an in-memory matrix is an afternoon's migration — this is the documented escape hatch, not a reason to switch now |
| sqlite-vec | Qdrant/Chroma/LanceDB | Only past ~1M chunks/case (SPEC's own threshold); all violate zero-daemon or dependency-light constraints |
| WeasyPrint (`[pdf]` extra) | Defer PDF entirely to post-M8 | If M6 runs hot; Markdown+JSON are the load-bearing outputs |
| httpx | stdlib `urllib.request` | Never — retries, timeouts, pooling, respx-testability justify it |
| zstandard | stdlib `compression.zstd` | When Python floor reaches 3.14 — then delete the dependency |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `openai` SDK | Vendor coupling, drags in httpx anyway, hides the request shape Sift must control (llama.cpp's non-standard `response_format.schema` nesting) | Hand-rolled httpx client (~200 lines), per SPEC §5.6 |
| `drain3` | Dormant since 2022; Python ≤3.11 metadata; learns templates non-deterministically vs Sift's determinism constraint | Hand-rolled regex masking in `pipeline/dedup.py` |
| standalone `hdbscan` package | Redundant compiled dependency; sklearn (already required) ships HDBSCAN since 1.3 | `sklearn.cluster.HDBSCAN` |
| ReportLab for the report renderer | No Markdown/HTML rendering — you'd hand-write all layout | WeasyPrint via `sift[pdf]` extra |
| LangChain / LlamaIndex / instructor | Framework weight, network-egress surface, abstraction over an API Sift must control precisely | httpx + Pydantic + prompt files |
| `chromadb` / `qdrant-client` | Daemon or heavyweight deps; violates one-file-per-case portability | sqlite-vec |
| sqlite-vec ANN modes (IVF/DiskANN) | Explicitly experimental | Default brute-force KNN |
| OpenAI-style `response_format.json_schema.json_schema.schema` nesting against llama-server | llama.cpp expects `{"type":"json_schema","schema":{...}}` — the OpenAI shape historically failed (issues #10732/#11847) | Send llama.cpp's shape; Pydantic-validate regardless |

## Stack Patterns by Variant

**If the inference server is llama-server:**
- Two instances: one generation (`llama-server -m <30B>.gguf`), one embeddings (`llama-server -m nomic-embed.gguf --embeddings`) — the `--embeddings` flag makes the server embedding-only, so one instance cannot serve both roles.
- Feature-detect `/props` and `/tokenize` for context length and token budgeting.

**If the inference server is Lemonade:**
- Single base URL `:13305/v1` for both roles; embedding model must be a `llamacpp`/`flm`-recipe model — `sift doctor` must round-trip an actual embedding, not just list models.

**If PDF output is requested:**
- `sift[pdf]` extra (markdown + WeasyPrint); document `dnf install pango` for Fedora; bake into the Quadlet image.

**If sqlite-vec becomes unmaintained pre-v1:**
- Escape hatch: swap the `vectors` vec0 table for a BLOB column + numpy brute-force scan behind the same store interface. Keep vector access confined to `store.py` so this stays an afternoon's work.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| sqlite-vec 0.1.9 | Python 3.12/3.13 sqlite3 | Requires `enable_load_extension`; Fedora python3 OK — verify in `sift doctor` |
| scikit-learn 1.9.0 | numpy 2.x, Python 3.12+ | HDBSCAN `min_samples` counts self (+1 vs standalone semantics) — matters only if comparing against literature defaults |
| zstandard 0.25.0 | Python 3.12+ | Prebuilt wheels for Fedora x86_64 |
| Typer 0.27.0 | click 8.x | Pulls rich + shellingham; `typer-slim` if trimming |
| WeasyPrint 69.0 | pango ≥1.44 system lib | Fedora: `dnf install pango` — not pip-installable; hence optional extra |
| Pydantic 2.13.4 | llama.cpp json_schema converter | Keep schemas self-contained (no external `$ref`); verify `$defs` handling with the target server build in M4 |
| httpx 0.28.1 | respx 0.22.x | respx pins compatibility with httpx minor versions — pin both in dev deps |

## Sources

- `/asg017/sqlite-vec` (Context7) — Python bindings, vec0 API, KNN queries, capacity limits — MEDIUM
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md (fetched 2026-07-16) — response_format/json_schema/grammar, `--embeddings`, pooling, `/props`, `/tokenize` — MEDIUM (official docs, cross-checked with issues #10732, #11847)
- https://lemonade-server.ai/docs/api/openai/ (fetched 2026-07-16) — endpoints, port 13305, embeddings recipe restriction — MEDIUM
- PyPI JSON API (fetched 2026-07-16) — exact versions + release dates for sqlite-vec, hdbscan, typer, zstandard, httpx, pydantic, drain3, weasyprint, reportlab, scikit-learn — MEDIUM
- https://github.com/scikit-learn/scikit-learn/issues/27829 — sklearn vs standalone HDBSCAN result differences — MEDIUM
- https://github.com/asg017/sqlite-vec/issues/226 — 2025 maintenance stall — MEDIUM
- https://doc.courtbouillon.org/weasyprint/stable/first_steps.html — pango/harfbuzz system deps — MEDIUM
- https://docs.reportlab.com/install/open_source_installation/ — pure-Python since 4.0 — MEDIUM

---
*Stack research for: local-LLM incident triage CLI (Sift)*
*Researched: 2026-07-16*
