# Phase 3: Inference Client, Doctor, Embeddings & Semantic Clustering - Research

**Researched:** 2026-07-17
**Domain:** Local OpenAI-compatible inference over HTTP, sqlite-vec vector persistence, HDBSCAN semantic clustering, LLM cluster labelling, SQLite disk-full atomicity
**Confidence:** HIGH on library APIs (frozen + Context7-verified in `.claude/CLAUDE.md`) and stdlib predicates (verified this session); MEDIUM on client internals and clustering thresholds (Claude's discretion / provisional per D-04)

<user_constraints>
## User Constraints (from 03-CONTEXT.md)

### Locked Decisions
- **D-01 (SPEC §10 #3 RESOLVED):** Cluster labels generated **eagerly** in the clustering stage of `sift analyze` and persisted to `clusters.label`. `sift show clusters` displays the label once clustering has run (raw `signature` shown until then / when `--no-label` or no endpoint). One batched LLM call per run over exemplars only, under a strict token budget. **Record this resolution as an ADR in `docs/decisions/`** (SPEC §10 requires it).
- **D-02 (`sift doctor` = fail-fast):** Checks run in dependency order (generation endpoint → embeddings endpoint → real embedding round-trip → dimension-vs-existing-index → determinism warnings) and **stop at the first critical failure**, exiting non-zero. The failing check must name the failure mode explicitly and actionably — in particular the Lemonade OGA/ONNX-recipe case ("embeddings unsupported on this recipe; load a llamacpp/flm-recipe model"), endpoint unreachable, and embedding-dimension mismatch against an existing index. Non-critical findings reached before the stop (e.g. multi-slot `--parallel > 1`) print as **warnings** without failing. The embedding check is a **real** round-trip, never just `/v1/models`.
- **D-03 (embedding model identity = config-only, NO baked-in default):** `embeddings.model` comes from config.toml / `SIFT_*` / `--model`; Sift asserts nothing about which model is loaded. `doctor` and the embed path record whatever identity + dimension the server returns into `meta`. A dimension mismatch against an existing index is a **hard error**; identity is recorded for provenance.
- **D-04 (HDBSCAN config):** Clustering parameters ship as **tuned defaults in code, overridable via `[clustering]` in config.toml**: `min_cluster_size`, `min_samples` (sklearn counts the point itself — +1 vs standalone), `cluster_selection_epsilon`, `metric = "cosine"`, and the agglomerative-fallback cosine `distance_threshold`. Use `sklearn.cluster.HDBSCAN` (research-locked; no standalone `hdbscan`). Noise points become singleton clusters. Weights/thresholds are provisional — revisit after the golden suite (Phase 7).

### Claude's Discretion (planner/executor decide, guided by SPEC + research)
- httpx client internals: retry/backoff schedule, timeout values, embedding batch-size default, connection pooling, per-role `base_url` wiring.
- Feature-detection mechanism for `/props`, `/tokenize`, grammar/JSON-schema decoding, and the llama.cpp `response_format.schema` nesting (send llama.cpp's shape; never require it).
- `PromptBudget` token-estimation seam (tokenize endpoint when present, else chars/4) — only the label-budgeting slice this phase.
- Progress-feedback mechanism for the embedding leg (reuse the Phase-2 ingest progress pattern).
- Exact `chunks`/`vectors`/`clusters` migration SQL and sqlite-vec `vec0` table definition.
- Fake OpenAI-compatible test server shape (respx vs tiny ASGI stub) — never hit the network (EVAL-05).

### Deferred Ideas (OUT OF SCOPE)
- Salience scoring, triage prompt, hypothesis JSON contract + citation validation — Phase 4 (M4).
- Full `PromptBudget` breadth-first truncation for the triage prompt — Phase 4 (only label-budgeting slice here).
- KB index + retrieval — Phase 6 (M6); per-case vs global location still open (SPEC §10 #5).
- Salience/clustering threshold tuning — deferred to post-golden-suite (Phase 7).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LLM-01 | One OpenAI-compatible client (`/v1/chat/completions`, `/v1/embeddings`), per-role base_urls, timeouts, backoff retries, batched embeddings — no vendor SDK | Standard Stack (httpx 0.28.1); Pattern 1 (injectable client + manual backoff because httpx transport retries connections only, A1) |
| LLM-02 | Non-loopback/non-RFC1918 endpoints refused unless `--i-know-what-im-doing`; zero egress otherwise | Pattern 2 (VERIFIED `ipaddress` predicate); Security Domain (SSRF guard) |
| LLM-03 | `sift doctor` real round-trips incl. actual embedding call, reports model IDs, checks dimension vs index, warns on determinism-breaking config | `doctor` fail-fast sequence (Code Examples); Pitfall 2 (OGA/ONNX); Pitfall 5 (`vec_version`) |
| LLM-04 | llama.cpp features (`/props`,`/tokenize`, grammar, `response_format` nesting) feature-detected, never required — Lemonade works unmodified | Pattern 1 probes; Pitfall 3 (`response_format.schema` nesting) |
| STORE-03 | Embedding model identity + dimension in `meta`; mismatch on reload = hard error | Pattern 3 (lazy `vec0`, dim guard); Pattern 4 (f32 blob) |
| CLUS-02 | Semantic clustering via HDBSCAN (L2-normalised); agglomerative fallback from config; noise→singletons | Pattern 5 (HDBSCAN/agglomerative, A2); Open Question 2 (fallback trigger) |
| CLUS-03 | Short LLM label per cluster from exemplars only, strict token budget | Pattern 6 (batched label, versioned template); Open Question 3 (label parsing) |
| RAG-05 | PromptBudget estimates tokens (tokenize endpoint or chars/4), reserves headroom, truncates breadth-first | PromptBudget seam (Code Examples) — label slice only this phase |
| CLI-02 | All prompts are versioned template files; changing a prompt needs no Python | Pattern 6 (`prompts/cluster_label.md` via importlib.resources) |
| EVAL-05 | Tests never call the network; client injectable; fake OpenAI-compatible server | Fake inference server (Code Examples); existing `_no_network` conftest fixture |

**Also carried forward (not a v1 requirement ID but a signed-off deferred fix):** WR-07 disk-full atomicity hole — see Pitfall 1.
</phase_requirements>

## Summary

The dependency question is closed. `.claude/CLAUDE.md` already carries Context7- and PyPI-verified,
frozen research for every library this phase touches (httpx, sqlite-vec `vec0`, `sklearn.cluster.HDBSCAN`,
zstandard, the no-vendor-SDK rule, the llama.cpp `response_format.schema` nesting, the Lemonade
embeddings-recipe caveat). This research does **not** re-litigate any of that — it maps those frozen
choices onto the concrete module shapes, method signatures, SQL, error-handling and test seams the
planner needs, and fills the implementation-level gaps the frozen research deliberately left open.

Phase 3 is the project's first network surface and its first new-dependency install since Phase 1.
Four packages must be added to `pyproject.toml` (they are NOT declared yet): `httpx`, `sqlite-vec`,
`scikit-learn` (which pulls `numpy`) as runtime, and `respx` as a dev dependency. Everything hangs off
one new `src/sift/llm/` module (the only place HTTP happens) and one new `src/sift/pipeline/cluster.py`.
The store gains migration 3 (chunks + clusters tables) plus a lazily-created `vec0` vectors table
(dimension is not known until the first embedding returns, per D-03's config-only model identity).

The load-bearing correctness items are all defence-at-a-boundary: the loopback/RFC1918 refusal predicate
(SSRF guard, LLM-02), the real-embedding round-trip in `doctor` that catches Lemonade's OGA/ONNX recipe
returning no embeddings (LLM-03), the hard dimension-mismatch error (STORE-03), and the carried-forward
WR-07 fix that reclassifies `SQLITE_FULL`/`SQLITE_IOERR` as fatal (they auto-rollback and destroy
savepoints, so the current per-file "log and continue" handler misreports a dead transaction).

**Primary recommendation:** Build one injectable `InferenceClient` (httpx, ~200 lines, manual backoff loop
because httpx transport retries connection errors only), keep every vector byte inside `store.py`, embed
one exemplar per existing template group, cluster with `HDBSCAN(min_cluster_size=2)` on L2-normalised
vectors (euclidean ≡ cosine when normalised), label all clusters in one batched chat call driven by a
`prompts/cluster_label.md` template, and test entirely against `respx`/`httpx.MockTransport` so no socket
ever opens. Fix WR-07 by checking `exc.sqlite_errorcode` before the generic per-file except.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTTP to inference server | `src/sift/llm/client.py` | — | SPEC §5.6: the ONLY module that talks HTTP; keeps egress auditable |
| Endpoint safety (loopback/RFC1918 refusal) | `llm/client.py` (construction-time) | `cli.py` (`--i-know-what-im-doing` flag) | SSRF guard belongs at the client boundary, not scattered per-call |
| Token estimation for label budget | `src/sift/llm/budget.py` | `llm/client.py` (`/tokenize` probe) | RAG-05 seam; label-budget slice only this phase |
| Embedding persistence + dimension guard | `src/sift/store.py` (`CaseStore`) | `meta` table | STORE-03; all vector access confined to store.py (BLOB+numpy escape hatch) |
| Semantic clustering + labelling orchestration | `src/sift/pipeline/cluster.py` | `llm/client.py`, `store.py` | typer-free/print-free/SQL-free like `dedup.py` — persistence via store methods only |
| Cluster-label prompt text | `src/sift/prompts/cluster_label.md` | — | CLI-02: changing a prompt touches no Python |
| `doctor` check sequencing + messages | `src/sift/cli.py` (`doctor`) | `llm/client.py`, `store.py` (`vec_version`) | Fail-fast orchestration (D-02) is a CLI concern; probes live in the client/store |
| Embedding-leg progress feedback | `src/sift/cli.py` (`analyze`) | rich.Progress | CLI-02(→CLI-03 leg): reuse the Phase-2 stderr/transient pattern |
| WR-07 disk-full atomicity | `src/sift/cli.py` (`_ingest`) | `src/sift/store.py` | The fatal-code reclassification lives at the per-file except in the ingest loop |

## Standard Stack

> Library **selection** is frozen in `.claude/CLAUDE.md` "Technology Stack". This table records the
> concrete versions to add to `pyproject.toml` (verified against PyPI this session) and what each is for.

### Core (add to `[project.dependencies]`)
| Library | Version (PyPI, 2026-07-17) | Purpose | Provenance |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | OpenAI-compatible client; `/v1/chat/completions`, `/v1/embeddings`, probes | [VERIFIED: pip index versions] + [CITED: .claude/CLAUDE.md] |
| sqlite-vec | 0.1.9 | `vec0` virtual table for embedding persistence | [VERIFIED: pip index versions] + [CITED: .claude/CLAUDE.md] |
| scikit-learn | 1.9.0 | `HDBSCAN` + `AgglomerativeClustering` fallback + `normalize` | [VERIFIED: pip index versions] + [CITED: .claude/CLAUDE.md] |
| numpy | 2.5.1 (transitive via sklearn) | float32 little-endian blob serialisation; vector matrix | [VERIFIED: pip index versions] |

### Supporting (add to `[dependency-groups].dev`)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| respx | 0.23.1 (>=0.22) | Mock httpx routes (fake OpenAI server) | Test-only; EVAL-05. 0.23.1 is current and tracks httpx 0.28. CLAUDE.md said 0.22.x — same library, version bumped for httpx-0.28 compat |

**Installation:**
```bash
uv add httpx==0.28.1 sqlite-vec==0.1.9 scikit-learn==1.9.0
uv add --dev respx
```

> Note: some of these already resolve in the local `.venv` transitively, but NONE are declared in
> `pyproject.toml` — the plan must add them explicitly (a milestone dependency, `uv.lock` pinned).

### Alternatives Considered
All alternatives (standalone `hdbscan`, vendor `openai` SDK, plain BLOB+numpy over sqlite-vec, ASGI stub
over respx) are already adjudicated in `.claude/CLAUDE.md`. The BLOB+numpy escape hatch remains the
documented fallback if sqlite-vec maintenance dies (keep all vector access in `store.py`).

## Package Legitimacy Audit

> `gsd-tools query package-legitimacy check` is unavailable on this runtime (shim not resolvable), so the
> audit rests on direct PyPI verification (`pip index versions`) + the frozen Context7/PyPI research in
> `.claude/CLAUDE.md`. All four are already legitimacy-approved there.

| Package | Registry | Age / maturity | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| httpx | PyPI | mature, ubiquitous (encode/) | very high | github.com/encode/httpx | OK | Approved |
| scikit-learn | PyPI | mature, ubiquitous | very high | github.com/scikit-learn/scikit-learn | OK | Approved |
| numpy | PyPI | mature, ubiquitous | very high | github.com/numpy/numpy | OK | Approved |
| respx | PyPI | maintained (lundberg) | high (test tool) | github.com/lundberg/respx | OK | Approved (dev) |
| sqlite-vec | PyPI | pre-v1 (0.1.9), single maintainer, 2025 maintenance stall then resumed | moderate | github.com/asg017/sqlite-vec | SUS (accepted) | Approved with escape hatch — already flagged in STATE.md Blockers |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** `sqlite-vec` — but this is a pre-existing, deliberately-accepted
project decision (SPEC §5.3, STATE.md cross-cutting blocker), not a new discovery. The mitigation (confine
all vector access to `store.py`; BLOB+numpy escape hatch) is already project policy. No new
`checkpoint:human-verify` needed — it was decided at project start.

## Architecture Patterns

### System Architecture Diagram

```
  sift doctor ─────────────┐                    sift analyze (embed→cluster→label leg)
       │                   │                              │
       ▼                   ▼                              ▼
  ┌──────────────────────────────────┐        ┌────────────────────────────────────┐
  │ InferenceClient (llm/client.py)  │        │ cluster.py (pipeline)              │
  │  • loopback/RFC1918 guard  ◄─────┼── url   │  1. read template_groups (store)   │
  │  • GET /v1/models  (ids)         │        │  2. one exemplar msg per group     │
  │  • GET /props   (ctx, n_parallel)│        │  3. client.embed(batched) ─────────┼──┐
  │  • POST /v1/embeddings (probe)   │        │  4. store.upsert_vectors(f32 blob) │  │
  │  • POST /tokenize (budget)       │        │  5. HDBSCAN(L2-norm) / agg fallback │  │
  │  • POST /v1/chat/completions     │◄───────┤  6. noise → singleton clusters     │  │
  │    (backoff retry loop)          │  labels │  7. store.replace_clusters()       │  │
  └───────────────┬──────────────────┘        │  8. client.chat(label prompt) ─────┼──┘
                  │ HTTP (loopback only)       │  9. store: clusters.label = …      │
                  ▼                            └──────────────────┬─────────────────┘
      ┌───────────────────────────┐                              │ store methods only
      │ llama-server / Lemonade   │              ┌───────────────▼───────────────────┐
      │ :port/v1 (generation)     │              │ CaseStore (store.py)               │
      │ :port/v1 (embeddings,     │              │  migration 3: chunks, clusters     │
      │   --embeddings / recipe)  │              │  lazy vec0 vectors(dim) @first embed│
      └───────────────────────────┘              │  meta: embedding_model, dim, metric │
                                                 │  sqlite_vec.load + vec_version()    │
                                                 └────────────────────────────────────┘
```

### Recommended Project Structure
```
src/sift/
├── llm/
│   ├── __init__.py
│   ├── client.py      # InferenceClient: the only HTTP; guard, probes, embed, chat, retry
│   └── budget.py      # PromptBudget seam: /tokenize when present, else chars//4 (label slice)
├── pipeline/
│   └── cluster.py     # embed → HDBSCAN/agglomerative → clusters → label (typer/print/SQL-free)
├── prompts/
│   └── cluster_label.md   # versioned template (CLI-02); loaded via importlib.resources
└── store.py           # + migration 3, lazy vec0 table, vector (de)serialisation, dim guard
```

### Pattern 1: Injectable client, two roles, manual backoff
**What:** One `InferenceClient` holding per-role endpoints and an injectable `httpx.Client`.
**When to use:** Every inference call. Tests inject a client bound to a respx/MockTransport.
**Example:**
```python
# src/sift/llm/client.py  (shape only — Claude's discretion on knobs, D-04 discretion list)
import httpx

@dataclass(frozen=True)
class Endpoint:
    base_url: str          # e.g. "http://localhost:13305/v1"
    model: str             # config-only, no baked default (D-03)

class InferenceClient:
    def __init__(self, generation: Endpoint, embeddings: Endpoint,
                 http: httpx.Client, *, allow_public: bool = False,
                 retries: int = 2, backoff_base: float = 0.5) -> None:
        _assert_local(generation.base_url, allow_public)   # LLM-02 SSRF guard
        _assert_local(embeddings.base_url, allow_public)
        self._http = http                                   # injectable (EVAL-05)
        ...

    def _request(self, method, url, **kw):
        # httpx.HTTPTransport(retries=) retries CONNECTION errors ONLY — not
        # read timeouts or 5xx. So loop manually over (ConnectError,
        # TimeoutException, 5xx) with exponential backoff. [ASSUMED: httpx docs]
        for attempt in range(self._retries + 1):
            try:
                r = self._http.request(method, url, **kw)
                if r.status_code < 500:
                    return r
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt == self._retries:
                    raise
            time.sleep(self._backoff_base * 2 ** attempt)
        r.raise_for_status()
```

### Pattern 2: Loopback / RFC1918 refusal (LLM-02, SSRF guard) — VERIFIED predicate
**What:** Refuse any non-local `base_url` unless `--i-know-what-im-doing`. Do NOT resolve DNS (that is
itself egress and can vary between check and use).
```python
import ipaddress
from urllib.parse import urlsplit

def _assert_local(base_url: str, allow_public: bool) -> None:
    host = urlsplit(base_url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return
    try:
        ip = ipaddress.ip_address(host)          # literal IP only
    except ValueError:
        ip = None
    ok = ip is not None and (ip.is_loopback or ip.is_private)  # RFC1918 + link-local
    if not ok and not allow_public:
        raise ValueError(
            f"refusing non-local inference endpoint {base_url!r}; "
            "pass --i-know-what-im-doing to override"
        )
```
Verified this session (python 3.12.13): `127.0.0.1`/`::1` → loopback True; `10.x`/`172.16.x`/`192.168.x`/
`169.254.x` → is_private True; `8.8.8.8` and `172.32.0.1` → is_private False (correctly refused).
`is_private` already subsumes loopback + link-local + RFC1918, so `is_loopback or is_private` is belt-and-braces.

### Pattern 3: Lazy `vec0` table (dimension unknown until first embed, D-03)
```python
# store.py — dimension comes from the server's first embedding, not config
def ensure_vectors_table(self, dim: int) -> None:
    existing = self.get_meta("embedding_dim")
    if existing is not None and int(existing) != dim:
        raise ValueError(                         # STORE-03 hard error
            f"embedding dimension mismatch: index has {existing}, server returned {dim}"
        )
    if existing is None:
        _load_sqlite_vec(self._conn)              # enable_load_extension + sqlite_vec.load
        # dim is an int computed by us, never user text — safe to interpolate.
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vectors "
            f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{int(dim)}])"
        )
        self.set_meta("embedding_dim", str(dim))
        self.set_meta("embedding_metric", "cosine")   # cosine≡L2 on normalised vectors
```
`vec0` DDL, the `MATCH ... AND k = ?` KNN shape, ≤8192 dims, and the `enable_load_extension` requirement
are all [CITED: .claude/CLAUDE.md Validation Finding #1 / Context7 /asg017/sqlite-vec]. KNN retrieval is
NOT needed this phase (clustering reads the whole matrix); note the shape for Phase 4/6.

### Pattern 4: float32 little-endian blob (all vector bytes in store.py)
```python
import numpy as np
def _vec_to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()   # sqlite-vec expects float32
# INSERT INTO vectors(chunk_id, embedding) VALUES (?, ?)   -- (chunk_id, blob)
```

### Pattern 5: HDBSCAN on normalised vectors, noise → singletons (CLUS-02, D-04)
```python
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.preprocessing import normalize
import numpy as np

X = normalize(np.asarray(vectors, dtype=np.float64), norm="l2")   # cosine≡euclidean now
if cfg.algorithm == "agglomerative" or len(X) < cfg.min_cluster_size:
    # fallback: metric="cosine" REQUIRES linkage in {average, complete} — NOT ward
    labels = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average",
        distance_threshold=cfg.distance_threshold,
    ).fit_predict(X)
else:
    labels = HDBSCAN(
        min_cluster_size=cfg.min_cluster_size,     # 2 (success criterion 3)
        min_samples=cfg.min_samples,               # sklearn counts the point itself: +1 vs standalone
        cluster_selection_epsilon=cfg.epsilon,
        metric="euclidean",                        # == cosine on L2-normalised X
    ).fit_predict(X)
# HDBSCAN noise label is -1 → each becomes its own singleton cluster
```
`min_samples` self-count (+1 vs standalone `hdbscan`) and the sklearn-HDBSCAN choice are
[CITED: .claude/CLAUDE.md Validation Finding #2]. The `linkage != "ward"` constraint for non-euclidean
metrics is [ASSUMED] (sklearn API; could not import sklearn this session — numpy absent in that venv);
the planner should have the executor confirm at implementation time.

### Pattern 6: One batched label call from a versioned template (CLUS-03, D-01, CLI-02)
```python
from importlib.resources import files
TEMPLATE = files("sift.prompts").joinpath("cluster_label.md").read_text(encoding="utf-8")
# Build ONE prompt listing every cluster's exemplar excerpt (budget-truncated,
# breadth-first). Ask for one short British-English label per cluster, returned
# as a parseable list keyed by cluster index. Freeform text — NO schema-constrained
# decoding needed for labels (that machinery is Phase 4). Record prompt hash in meta.
```

### Anti-Patterns to Avoid
- **Baking an embedding-model default** — D-03 forbids it; a wrong default causes silent identity mismatch the dimension check cannot catch.
- **Using `httpx` transport `retries=` as your retry policy** — it only retries connection establishment, never timeouts or 5xx. Silent under-retry.
- **`AgglomerativeClustering(metric="cosine", linkage="ward")`** — ward requires euclidean; raises at fit.
- **Schema-constrained decoding for labels** — unnecessary this phase; labels are freeform. Keep the `response_format.schema` feature-detection for Phase 4.
- **Resolving the endpoint hostname via DNS in the safety check** — that is egress and TOCTOU-racey; only accept literal local IPs + `localhost`.
- **Loading sqlite-vec eagerly in `CaseStore.__init__`** — Phase 1/2 code paths and tests never touch vectors; load lazily so extension-loading is only required when embeddings are actually used, and a llama-free environment still opens cases.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retries/timeouts/pooling | urllib loop | httpx.Client (+ small backoff wrapper) | Connection pooling, timeouts, respx-testability |
| Vector KNN / storage | numpy scan (yet) | sqlite-vec `vec0` | Frozen decision; escape hatch documented if it dies |
| HDBSCAN + agglomerative | custom density clustering | `sklearn.cluster.*` | Already a required dep; both algorithms in one import |
| RFC1918/loopback classification | regex on IP strings | stdlib `ipaddress` | `is_private`/`is_loopback` are correct on edge cases (v6, link-local) |
| Fatal-vs-recoverable SQLite errors | string-match error text | `exc.sqlite_errorcode` vs `sqlite3.SQLITE_FULL` | Numeric codes are stable; text is localised/versioned |
| Token counting | custom tokenizer | server `/tokenize`, else `len//4` | Exact when available; the heuristic is the documented fallback (RAG-05) |
| Mock inference server | real socket server | respx / httpx.MockTransport | Zero network, deterministic, no port juggling (EVAL-05) |

**Key insight:** Every "hard" part here already has a boring, in-tree or stdlib answer. The genuinely
new code is glue + boundary validation, which is exactly where the effort should go.

## Runtime State Inventory

> This is a greenfield feature phase (new modules + one migration), not a rename/refactor. The only
> "existing runtime state" concern is schema/meta continuity:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `meta` gains `embedding_model`, `embedding_dim`, `embedding_metric`, label prompt hash; new `chunks`/`clusters`/`vectors` tables via migration 3 (+ lazy vec0) | Migration + meta writes; dimension guard on reload |
| Live service config | Inference endpoints (`base_url`s) are config-only, not stored state | none |
| OS-registered state | None — Sift registers nothing | None (verified: no daemons/services) |
| Secrets/env vars | New `SIFT_*` scalar keys likely (embeddings/generation base_url, timeouts, batch, clustering params) — extends the config precedence machinery | Extend `config.py` SiftConfig + env mapping |
| Build artifacts | `pyproject.toml` + `uv.lock` change (4 new deps) | `uv sync`; PKG-01 clean-checkout install still works |

## Common Pitfalls

### Pitfall 1: SQLITE_FULL/IOERR silently misreported as a per-file parse error (WR-07 — carried forward)
**What goes wrong:** On `SQLITE_FULL` or `SQLITE_IOERR` mid-ingest, SQLite auto-rolls-back the entire
transaction and destroys all savepoints. The current `_ingest` loop (`cli.py` ~L277 `except Exception`)
catches it, records the file as a failed parse, and **continues** — but the transaction is now dead, so
subsequent inserts and the final `COMMIT` operate on a broken transaction and the disk-full is reported
as one bad file rather than a fatal abort.
**Why it happens:** The savepoint-per-file design assumes recoverable per-file errors; storage-exhaustion
errors are not recoverable and are not scoped to one file.
**How to avoid:** Before the generic per-file handling, detect fatal codes and abort loudly:
```python
except sqlite3.Error as exc:
    code = getattr(exc, "sqlite_errorcode", None)
    # SQLITE_FULL=13, SQLITE_IOERR=10 (+ IOERR extended codes share low byte).
    if code in (sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR) or (
        code is not None and code & 0xFF == sqlite3.SQLITE_IOERR
    ):
        raise DiskFullError(                       # break out — do NOT swallow per-file
            f"disk full / I/O error during ingest at {relpath}: "
            "no events committed (transaction rolled back)"
        ) from exc
    # …fall through to the existing recoverable per-file handling…
```
The outer `store.transaction()` already tolerates a dead transaction (its `ROLLBACK` catch/pass). Net
effect: all-or-nothing is preserved **and** honestly reported; exit non-zero (a distinct code if CLI-04
wants one). Verified this session: `sqlite3.SQLITE_FULL == 13`, `sqlite3.SQLITE_IOERR == 10` exist as
module constants (Python 3.11+); `exc.sqlite_errorcode` is populated on errors originating from SQLite
(not on hand-constructed exceptions).
**Warning signs:** an ingest that "completed" with one failed file but committed zero events; confusing
COMMIT-time errors.
**Test tip:** force a real `SQLITE_FULL` without filling the disk via `PRAGMA max_page_count=<small>` on
the connection, then ingest past that many pages; assert exit non-zero, zero events, disk-full message.

### Pitfall 2: Lemonade OGA/ONNX-recipe model silently returns no usable embedding
**What goes wrong:** `/v1/models` lists a model, but `/v1/embeddings` on an OGA/ONNX-recipe model errors
or returns empty — chat "works", embeddings don't.
**How to avoid:** `doctor` (and the embed path) must do a **real** embedding round-trip and name this
failure: `"embeddings unsupported on this model/recipe; load a llamacpp/flm-recipe embedding model
(Lemonade) or start llama-server with --embeddings"`. Never infer capability from `/v1/models`.
[CITED: .claude/CLAUDE.md Validation Finding #7]

### Pitfall 3: llama.cpp `response_format` nesting differs from OpenAI
**What goes wrong:** OpenAI puts schema at `response_format.json_schema.schema`; llama.cpp wants
`response_format.schema`. Not relevant to freeform labels this phase, but the feature-detection code
written here will be reused in Phase 4 — send llama.cpp's shape, feature-detect, never require.
[CITED: .claude/CLAUDE.md Validation Finding #5]

### Pitfall 4: Untrusted server response size (DoS)
**What goes wrong:** httpx has no default response-body cap; a hostile/misconfigured local server could
stream an enormous body and OOM Sift.
**How to avoid:** set explicit timeouts and treat the server as untrusted input — validate the returned
embedding dimension, cap label lengths, defensively parse JSON. (ASVS V5; see Security Domain.)

### Pitfall 5: `enable_load_extension` unavailable on some Pythons
**What goes wrong:** loading sqlite-vec needs the interpreter's SQLite to permit extension loading;
Fedora's python3 allows it, some macOS system Pythons don't.
**How to avoid:** `doctor` loads sqlite-vec and reports `vec_version()`; on failure it names the
enable-extension caveat. Load lazily (only when vectors are used) so non-embedding paths never require it.
[CITED: .claude/CLAUDE.md Validation Finding #1]

## Code Examples

### `doctor` fail-fast sequence (D-02) — critical vs warning
```python
# cli.py doctor — stop at first CRITICAL (exit non-zero); print warnings reached before the stop.
# 1. construct client → runs loopback/RFC1918 guard (refuses public w/o override)   [CRITICAL]
# 2. GET /v1/models on generation endpoint → report ids                              [CRITICAL if unreachable]
# 3. GET /v1/models on embeddings endpoint                                           [CRITICAL if unreachable]
# 4. POST /v1/embeddings tiny probe → REAL round-trip; catch OGA/ONNX empty          [CRITICAL]
#      → record returned dimension
# 5. if case index exists: compare returned dim vs meta.embedding_dim                [CRITICAL on mismatch]
# 6. sqlite_vec.load + SELECT vec_version() on a throwaway conn → report             [CRITICAL if cannot load]
# 7. GET /props → if n_parallel>1 / continuous batching / no seed: determinism WARN  [WARNING, non-fatal]
```

### PromptBudget seam (RAG-05, label slice only)
```python
# src/sift/llm/budget.py
class PromptBudget:
    def __init__(self, client: InferenceClient | None, ctx_tokens: int, reserve_out: int): ...
    def estimate(self, text: str) -> int:
        toks = self._client.tokenize(text) if self._client and self._client.has_tokenize else None
        return toks if toks is not None else max(1, len(text) // 4)   # chars/4 fallback
    # breadth-first truncation of exemplar excerpts across ALL clusters (short each),
    # not depth-first — full triage budgeting lands Phase 4.
```

### Fake inference server for tests (EVAL-05)
```python
# Preferred: respx for endpoint shapes; httpx.MockTransport for deterministic embeddings.
import httpx
def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/embeddings"):
        inputs = json.loads(request.content)["input"]
        # deterministic vectors: synonymous templates → near-identical; noise → orthogonal
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": _planted_vector(t)} for i, t in enumerate(inputs)]})
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, json={"choices": [{"message": {"content": "…labels…"}}]})
    ...
client = httpx.Client(transport=httpx.MockTransport(_handler))   # NO socket opens
```
The existing `conftest.py` `_no_network` fixture blocks `socket.socket.connect`; with MockTransport/respx
no socket is opened at all, so **no relaxation is needed for unit tests**. The fixture comment ("Phase 3
will relax this for loopback only") applies only to an optional live-server integration test — mark it
(e.g. `@pytest.mark.live`) and exclude it from the default suite, mirroring the `perf` marker pattern.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| respx 0.22.x (CLAUDE.md) | respx 0.23.1 | 2026 | Tracks httpx 0.28; use `>=0.22`, pin 0.23.1 in dev |
| standalone `hdbscan` | `sklearn.cluster.HDBSCAN` | sklearn 1.3+ | one fewer compiled dep; `min_samples` counts self |
| zstandard package | stdlib `compression.zstd` | Python 3.14 | not yet — floor is 3.12; keep zstandard |

**Deprecated/outdated:** none newly discovered; the frozen research holds.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | httpx transport `retries=` retries connection errors only (not timeouts/5xx) → manual backoff loop required | Pattern 1 | LOW — if wrong, retry policy is merely simpler; confirm at impl |
| A2 | `AgglomerativeClustering(metric="cosine")` requires `linkage` in {average, complete}, not ward | Pattern 5 | LOW — fails fast at fit; executor picks average |
| A3 | Embed the exemplar **event message** (not the masked template) per group for richer semantics | cluster.py | MEDIUM — affects clustering quality; provisional like all D-04 thresholds, revisit post-golden-suite (Phase 7). Planner should confirm which text is embedded |
| A4 | llama.cpp `/v1/embeddings` batch `input` accepts a list and returns `data[].index` for order | Pattern 1 / tests | LOW — OpenAI-standard; CLAUDE.md confirms endpoint compat |
| A5 | Agglomerative fallback trigger = config `algorithm` selector OR auto-fallback when `n < min_cluster_size` | Pattern 5 | MEDIUM — D-04 says "config-driven"; exact trigger is Claude's discretion, confirm in plan |

**If any of these prove wrong at implementation time, they are localised to the clustering/label leg and
do not affect the frozen store/endpoint contracts.**

## Open Questions (RESOLVED)

> All three resolved into the plan set (03-03 embeds the exemplar message per OQ1; 03-05 routes the agglomerative fallback per OQ2 and the lenient `{index: label}` parse per OQ3). Recommendations are provisional per D-04 and revisited with the golden suite (Phase 7).

1. **Which text represents a template group for embedding — exemplar message vs masked template?**
   - What we know: SPEC §5.4 says "embed one exemplar chunk per template group"; `template_groups` already stores `exemplar_event_ids` and the masked `template`.
   - What's unclear: real message (richer, but volatile tokens add noise) vs masked template (stable, but strips distinguishing content).
   - RESOLVED: embed the first exemplar event's `message` (create one `chunk` row per group, `event_ids` = exemplars, `text` = message). Provisional; revisit with the golden suite (Phase 7), same posture as D-04.

2. **Exact agglomerative-fallback trigger.**
   - What we know: D-04 says config-driven cosine `distance_threshold`.
   - What's unclear: pure config selector vs automatic fallback when HDBSCAN degenerates.
   - RESOLVED: `[clustering].algorithm = "hdbscan"` default; explicit `"agglomerative"` option; plus auto-singleton path when `n_groups < min_cluster_size`. Confirm in plan.

3. **Label response format for robust parsing.**
   - What we know: one batched call, freeform labels, no schema decoding.
   - RESOLVED: ask for a JSON object `{index: label}` and parse leniently (one repair-free pass; on parse failure, leave labels NULL and fall back to `signature` — never crash). Full JSON-contract enforcement is Phase 4.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python sqlite3 `enable_load_extension` | sqlite-vec load | ✓ (Fedora) | 3.12.13 | none — `doctor` names the caveat; some macOS Pythons lack it |
| httpx / sqlite-vec / scikit-learn / numpy | whole phase | resolvable in venv but NOT in pyproject | 0.28.1 / 0.1.9 / 1.9.0 / 2.5.1 | must `uv add` — declaring them IS the action |
| respx | tests (EVAL-05) | resolvable | 0.23.1 | httpx.MockTransport (also stdlib-free of network) |
| A live llama-server / Lemonade | `doctor` live check, `analyze` real run | ✗ (not in this env) | — | Unit tests use fakes (no live server); live path behind a `@pytest.mark.live` opt-in |

**Missing dependencies with no fallback:** none block *development* — all inference is faked in tests.
**Missing with fallback:** a live inference server is absent; the phase is fully buildable and testable
without one (that is the whole point of EVAL-05). Acceptance criterion 1 ("`doctor` passes against a live
llama-server") is a **human/manual UAT** item, not an automated gate — flag it for the verifier.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`addopts = "-m 'not perf'"`) |
| Quick run command | `uv run pytest tests/test_<x>.py -x` |
| Full suite command | `uv run pytest` (excludes `perf`; add a `live` marker excluded the same way) |
| Gate | `uv run ruff check` + `uv run pyright` + `uv run pytest` all clean (project "done" rule) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LLM-01 | Client hits both roles; batched embeddings; backoff retry on 5xx/timeout | unit | `pytest tests/test_llm_client.py -x` | ❌ Wave 0 |
| LLM-02 | Public endpoint refused; `--i-know-what-im-doing` overrides; local IPs allowed | unit | `pytest tests/test_llm_client.py -k refuse` | ❌ Wave 0 |
| LLM-03 | `doctor` fail-fast order; real embedding round-trip; OGA/ONNX message; dim-mismatch message; `vec_version` check | unit (fakes) | `pytest tests/test_doctor.py -x` | ❌ Wave 0 |
| LLM-04 | `/props`,`/tokenize`,grammar feature-detected; absent → graceful (Lemonade path) | unit | `pytest tests/test_llm_client.py -k feature_detect` | ❌ Wave 0 |
| STORE-03 | embedding model+dim in `meta`; reload mismatch = hard error; f32 blob roundtrip | unit | `pytest tests/test_store_vectors.py -x` | ❌ Wave 0 |
| CLUS-02 | HDBSCAN merges planted synonyms (min_cluster_size=2); noise→singletons; agglomerative fallback | unit (deterministic fake vectors) | `pytest tests/test_cluster.py -x` | ❌ Wave 0 |
| CLUS-03 | One batched label call from `prompts/cluster_label.md`; budget-truncated; labels persisted; `--no-label`/no-endpoint → signature | unit | `pytest tests/test_cluster.py -k label` | ❌ Wave 0 |
| RAG-05 | PromptBudget uses `/tokenize` when present else chars//4; breadth-first truncation | unit | `pytest tests/test_budget.py -x` | ❌ Wave 0 |
| CLI-02 | Changing `cluster_label.md` changes label output with zero Python change; embedding-leg progress on stderr | unit + manual | `pytest tests/test_cli.py -k label_prompt` | ❌ Wave 0 |
| EVAL-05 | Whole suite runs with zero sockets; client injectable | unit (autouse `_no_network` + fakes) | `uv run pytest` | ✅ conftest exists; extend |
| WR-07 | `SQLITE_FULL`/`IOERR` mid-ingest → non-zero exit, zero events, disk-full message | unit | `pytest tests/test_store.py -k disk_full` | ❌ Wave 0 |

### Observable signals per requirement
- **LLM-02:** process refuses with a named error and non-zero exit for `8.8.8.8`; succeeds for `127.0.0.1`.
- **LLM-03:** stdout/stderr contains the exact OGA/ONNX and dimension-mismatch strings; exit code non-zero on first critical.
- **STORE-03:** second open with a different server dim raises before any write; `meta` rows present.
- **CLUS-02:** two planted-synonym templates share a cluster id; the planted-noise template is a singleton.
- **CLUS-03:** `clusters.label` populated after `analyze`; editing the prompt file (no code change) alters labels; `show clusters` shows label (or signature when unlabelled).
- **WR-07:** after a forced `SQLITE_FULL`, `sift show events` returns zero new rows and the CLI printed a disk-full abort.

### Sampling Rate
- **Per task commit:** the touched module's test file + `ruff` + `pyright` (project skill: gate per task).
- **Per wave merge:** `uv run pytest` (full, minus perf/live).
- **Phase gate:** full suite green + manual live `doctor` UAT before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_llm_client.py` — LLM-01/02/04 (fake transport, refusal, feature-detect)
- [ ] `tests/test_doctor.py` — LLM-03 fail-fast order + messages
- [ ] `tests/test_store_vectors.py` — STORE-03 dim guard + blob roundtrip + `vec_version`
- [ ] `tests/test_cluster.py` — CLUS-02/03 with deterministic planted vectors + label parsing
- [ ] `tests/test_budget.py` — RAG-05 tokenize/heuristic
- [ ] `tests/test_store.py` disk_full case — WR-07 (via `PRAGMA max_page_count`)
- [ ] Shared fake-inference fixtures (a `MockTransport` handler + planted-vector helper) — add in a test module, not conftest (conftest is 01-01-owned)
- [ ] Framework install: `uv add httpx sqlite-vec scikit-learn` + `uv add --dev respx`

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high`. This phase opens the
> first network surface — the SSRF-adjacent endpoint guard is the headline control.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | localhost inference, no auth surface |
| V3 Session Management | no | stateless CLI |
| V4 Access Control | no | single-user local tool |
| V5 Input Validation | **yes** | Validate `base_url` (loopback/RFC1918 predicate); treat every server response as untrusted (validate dimension, cap label length, defensive JSON parse); sanitise labels/signatures at render (existing `_sanitise`) |
| V6 Cryptography | no | no secrets, no crypto in this phase |
| V12/V13 Files & API / SSRF | **yes** | Endpoint refusal predicate is the SSRF guard; `--i-know-what-im-doing` is the explicit break-glass; never DNS-resolve in the check |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| User points `base_url` at a public/metadata/internal host (SSRF/exfil) | Info-disclosure / Elevation | `_assert_local` refusal (loopback/RFC1918 only); override is explicit and loud; tests assert refusal |
| Malicious/misconfigured server streams huge body (DoS/OOM) | Denial of Service | explicit httpx timeouts; validate dimension; cap label length; defensive parse |
| Tampered `case.db` holds hostile vectors/labels | Tampering | vectors are numeric blobs (dim-checked); labels/signatures sanitised at render (WR-01 precedent) |
| Native extension loading (`sqlite_vec.load`) | Elevation | load only the vetted `sqlite_vec`; `enable_load_extension(True)` then `(False)` immediately; lazy-load only when embedding |
| Determinism-breaking server config (multi-slot) misleads triage | (integrity) | `doctor` warns on `n_parallel>1`/no-seed (non-fatal); documented determinism caveat (REPT-03 later) |
| Network egress leak in tests | (privacy) | autouse `_no_network` fixture + MockTransport/respx → no socket opens; `live` marker opt-in only |

## Sources

### Primary (HIGH confidence)
- `.claude/CLAUDE.md` "Technology Stack / Validation Findings" — sqlite-vec `vec0` API (Context7 `/asg017/sqlite-vec`), llama.cpp `response_format.schema` nesting + `--embeddings` + `/props`/`/tokenize` (official server README), Lemonade port 13305 + embeddings-recipe caveat, `sklearn.cluster.HDBSCAN` vs standalone, no-vendor-SDK. All Context7/official-docs/PyPI-verified 2026-07-16.
- Python 3.12.13 REPL (this session) — `ipaddress` loopback/RFC1918 predicate values; `sqlite3.SQLITE_FULL=13`/`SQLITE_IOERR=10` constants; `exc.sqlite_errorcode` population behaviour.
- `pip index versions` (this session) — httpx 0.28.1, sqlite-vec 0.1.9, scikit-learn 1.9.0, numpy 2.5.1, respx 0.23.1.
- Repo source (this session) — `store.py`, `config.py`, `cli.py` (Phase-2 progress + savepoint/transaction pattern), `pipeline/dedup.py`, `models.py`, `conftest.py`; `SPEC.md` §5.3/§5.4/§5.6/§8-M3/§3/§10; `03-CONTEXT.md` D-01..D-04; ADR 0003 format.

### Secondary (MEDIUM confidence)
- httpx retry-semantics (transport `retries=` = connection-only) — [ASSUMED] from training/httpx docs; confirm at impl (A1).
- sklearn `AgglomerativeClustering` linkage/metric constraint — [ASSUMED]; could not import sklearn this session (numpy absent in that venv) (A2).

### Tertiary (LOW confidence)
- none.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — frozen + PyPI-verified this session.
- Store/vectors/endpoint contracts: HIGH — CLAUDE.md Context7-verified + stdlib predicates verified this session.
- Client internals (retry/backoff/timeouts/batch size): MEDIUM — Claude's discretion (D-04), A1 to confirm.
- Clustering thresholds + embed-text choice: MEDIUM — provisional by D-04, revisit post-golden-suite (Phase 7).
- WR-07 fix: HIGH — root cause + fatal-code detection verified against stdlib this session.

**Research date:** 2026-07-17
**Valid until:** 2026-08-16 (stable stack; sqlite-vec is the one fast-moving/pre-v1 item — re-check before pinning if the plan slips a month)
