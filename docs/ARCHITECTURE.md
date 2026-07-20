<!-- generated-by: gsd-doc-writer -->
# Architecture

## System overview

Sift turns a directory of raw diagnostic artefacts (MicroStrategy `DSSErrors` logs,
`DSSPerformanceMonitor` PDH-CSV counter dumps, EU-stack thread dumps, journald exports, generic
application logs) into a ranked, evidence-cited triage report — entirely offline. It is a Typer
CLI (`sift`) over a five-stage batch pipeline, with all
state held in a single per-case SQLite database (`case.db`). The only network traffic is to a
locally hosted OpenAI-compatible inference endpoint (llama.cpp `llama-server` or Lemonade Server),
and that traffic is confined to one module.

The architectural style is a layered pipeline with a single persistence seam: every stage reads
from and writes to `CaseStore`, and no stage passes in-memory state to the next. This makes each
stage independently re-runnable, idempotent, and inspectable with `sift show`.

## Component diagram

```
        src/sift/cli.py  (Typer: new, ingest, show, analyze, report, mcm, perfmon, eval, doctor)
                              │  orchestration only — no SQL, no HTTP
   ┌──────────────┬───────────┼───────────────┬──────────────┬─────────────┐
   ▼              ▼           ▼               ▼              ▼             ▼
adapters/     pipeline/    pipeline/       pipeline/      render/          eval/
 base.py       dedup.py    cluster.py     hypothesise.py  markdown.py      runner.py
 dsserrors     salience.py retrieve.py    mcm.py          json_out.py      metrics.py
 dssperfmon                               mcm_facts.py    mcm_report.py     judge.py
 eustack                                  perfmon.py      perfmon_report.py thresholds.py
 journald                                 perfmon_facts.py pdf.py
 genericlog
   │              │           │               │              │             │
   └──────────────┴───────────┴───────┬───────┴──────────────┴─────────────┘
                                      ▼
                             src/sift/store.py            src/sift/config.py
                          CaseStore — the ONLY SQL        SiftConfig (D-08 precedence)
                          case.db + sqlite-vec
                                      ▲
                                      │ embeddings / chat
                             src/sift/llm/client.py       src/sift/prompts/*.md
                          InferenceClient — the ONLY HTTP  versioned templates
                          budget.py: PromptBudget
```

Data-flow direction of the pipeline proper:

```
raw files ──ingest──▶ events ──dedup──▶ template_groups ──embed+cluster──▶ chunks/vectors/clusters
                                                                              │
                                                       KB runbooks ──▶ kb_chunks/kb_vectors
                                                                              │
                                            salience rank ──▶ triage prompt ──▶ LLM
                                                                              │
                                                     citation gate ──▶ hypotheses ──▶ report
```

## Pipeline stages and their owning modules

| Stage | Owner | What it does |
|-------|-------|--------------|
| Ingest | `cli.py::_ingest` + `adapters/` | Walks the recorded input directory, picks an adapter per file (`adapters.detect`), parses to `Event`s, inserts with `CaseStore.insert_events`. Each file is wrapped in a `CaseStore.savepoint` inside one outer transaction, so a mid-file parse failure rolls that file back to zero rows without losing the run. |
| Dedup | `pipeline/dedup.py::rebuild_template_groups` | Masks volatile tokens (`mask`), groups identical masked messages, and writes `template_groups`. Recomputed from the store every time, so it is idempotent. |
| Cluster | `pipeline/cluster.py::cluster_and_label` | Embeds one exemplar per template group, L2-normalises, clusters with `sklearn.cluster.HDBSCAN` (agglomerative fallback), writes `chunks`, `vectors`, `clusters`, and optionally LLM-generated cluster labels — all inside one transaction. |
| Retrieve | `pipeline/retrieve.py` | `index_kb` chunks a directory of Markdown runbooks into `kb_chunks`/`kb_vectors`; `retrieve_kb` runs vec0 KNN and returns KB *text only*. |
| Rank | `pipeline/salience.py::rank_clusters` | Scores clusters on severity, count, burstiness, novelty and proximity to the incident time (weights `_W_SEVERITY` 0.35, `_W_COUNT` 0.20, `_W_BURST` 0.15, `_W_NOVELTY` 0.10, `_W_PROXIMITY` 0.20), applying any `--since`/`--until` window at cluster granularity. |
| Hypothesise | `pipeline/hypothesise.py::hypothesise` | Assembles the budgeted triage prompt, runs generate → validate → repair → citation gate, persists `hypotheses` plus `triage_*` meta. |
| Render | `render/` | `render_markdown`, `render_json`, `render_pdf`, and the separate MCM and perfmon bundles in `render/mcm_report.py` and `render/perfmon_report.py`. Pure functions of an open `CaseStore` — no client is constructed, so no re-inference can occur. |

Two deterministic, LLM-free analysers sit alongside these stages. `pipeline/mcm.py`
(`analyse_mcm`) is a MicroStrategy memory-contract-manager analyser over stored events, and
`pipeline/mcm_facts.py` (`render_mcm_facts`) renders its findings as citable `[evt:…]` fact lines
spliced into the triage prompt. `pipeline/perfmon.py` (`analyse_perfmon`) is the v1.2
`DSSPerformanceMonitor` correlator: it takes an `McmAnalysis` plus the events and annotates each MCM
episode with counter value-at-denial, slope-per-second and peak over the episode's lead-up window
(`CounterTrend`), attaching graded correlation hazards (`PerfmonHazard`). With no MCM episodes it
falls back to a per-source-file full-sample-range scope so it never implies a correlation it did not
perform. `pipeline/perfmon_facts.py` (`render_perfmon_facts`) renders that analysis as citable
`[evt:…]` fact lines the same way `mcm_facts` does. Neither analyser opens a socket or calls the
LLM.

## The canonical Event model and `event_id` determinism

`src/sift/models.py` defines the frozen `Event` dataclass every adapter normalises into:
`event_id`, `case_id`, `ts`, `ts_confidence`, `source`, `source_file`, `line_start`, `line_end`,
`severity`, `component`, `thread`, `session`, `message`, `attrs`, `raw`. The schema is frozen —
changes require a decision record in `docs/decisions/` and a store migration.

Identity is computed by `models.event_id(source_file, byte_offset)`:

```python
hashlib.sha256(f"{source_file}\x00{byte_offset}".encode()).hexdigest()[:16]
```

`source_file` is the case-relative POSIX path (the compressed file's own path for `.gz`/`.zst`
inputs) and `byte_offset` is the 0-based offset of the event's first byte in the *decompressed*
stream. The NUL separator prevents concatenation ambiguity. The function depends on nothing else —
no case id, no clock, no randomness — so re-ingesting the same directory is a no-op
(`INSERT OR IGNORE` in `CaseStore.insert_events`).

Severity is a fixed six-value vocabulary (`fatal`, `error`, `warn`, `info`, `debug`, `unknown`),
enforced by a SQL `CHECK` constraint. Unparseable regions become `severity="unknown"` events rather
than being dropped, and adapters report per-file coverage via `adapters.base.ParseStats`.

## The case store

`src/sift/store.py` owns **all** SQL in the codebase. Every statement uses `?` placeholders; no
value is ever interpolated into SQL text. Filter keys reaching the store from the CLI are checked
against allowlist dicts (`_EVENT_FILTER_SQL`, `_CLUSTER_FILTER_SQL`, `_CLUSTERS_TABLE_FILTER_SQL`)
that map a key to a fixed `WHERE` snippet — an unknown key raises before any query is built.

Migrations are numbered functions applied by a `PRAGMA user_version` runner, each inside
`BEGIN IMMEDIATE`:

| Version | Adds |
|---------|------|
| 1 | `events`, `meta`, `idx_events_ts` |
| 2 | `template_groups`; zstd-compresses existing oversized `raw` |
| 3 | `chunks`, `clusters` |
| 4 | `hypotheses` |
| 5 | `kb_chunks` |

Vector tables are **not** created by a migration, because the embedding dimension is unknown until
the first embedding round-trip. `CaseStore.ensure_vectors_table(dim)` and
`ensure_kb_vectors_table(dim)` lazily create the `sqlite-vec` virtual tables:

```sql
CREATE VIRTUAL TABLE vectors    USING vec0(chunk_id    INTEGER PRIMARY KEY, embedding FLOAT[dim]);
CREATE VIRTUAL TABLE kb_vectors USING vec0(kb_chunk_id INTEGER PRIMARY KEY, embedding FLOAT[dim]);
```

A dimension that disagrees with `meta.embedding_dim` is a hard error naming both dimensions — never
a silent re-index. Consequently a llama-free environment still opens an ingested case without ever
loading the native extension; `sqlite_vec.load` is called lazily, and extension loading is
re-locked immediately afterwards (`_load_sqlite_vec`).

Two other invariants live here. Vector (de)serialisation is confined to `_vec_to_blob` /
`_blob_to_vec` (float32 little-endian), so swapping sqlite-vec for a numpy brute-force scan stays a
local change. And `raw` text above 4 KB encoded is transparently zstd-compressed
(`_encode_raw`/`_decode_raw`), with a 128 MB decompression cap because a shared `case.db` is
untrusted input.

Run-level state lives in `meta`: `embedding_dim`, `embedding_metric`, `embedding_model`,
`mask_version`, `cluster_label_prompt_hash`, and the `triage_*` keys
(`triage_degraded`, `triage_prompt_hash`, `triage_created_at`, `triage_model`,
`triage_timeline_summary`, `triage_unexplained_signals`, `triage_raw`).

The KB namespace is deliberately separate: `kb_chunks` has no `event_id` column anywhere, so a KB
row structurally *cannot* become citable evidence. See
[`0009-kb-index-per-case.md`](decisions/0009-kb-index-per-case.md).

### The ranking-exclusion seam (`EXCLUDED_FROM_RANKING`)

`DSSPerformanceMonitor` samples are periodic observations, not diagnostics: thousands of
near-identical counter rows carry no incident signal and would dominate template counts if fed to
dedup, clustering and salience. `store.py` holds them out of *ranking only* through a single frozen
constant, `EXCLUDED_FROM_RANKING = frozenset({"dssperfmon"})`, applied at exactly one place —
`CaseStore.iter_event_summaries`, whose `SELECT` carries a `WHERE source NOT IN (...)` clause
(source values are `?`-bound from the constant, sorted for determinism). Because every ranking stage
— dedup, cluster exemplars, hypothesis excerpts and the eval runner — reads its event universe from
that one method, none re-implements the filter.

The asymmetry is deliberate and load-bearing: the near-identical `iter_event_rows` (which backs
`show events`, citation hydration and evidence display) does **not** apply the exclusion. Perfmon
events therefore stay fully citable and fully visible — they are held out of ranking, never out of
evidence — so a perfmon figure can still be cited by a hypothesis and appear in the report. The two
methods must not be merged into a shared helper; the split is the invariant.

## The adapter protocol

`src/sift/adapters/base.py` defines the frozen protocol:

```python
class Adapter(Protocol):
    name: str
    def sniff(self, path: Path) -> float: ...        # 0.0-1.0 confidence
    def parse(self, path: Path, case_id: str) -> Iterator[Event]: ...
```

Concrete adapters subclass `ConfigurableAdapter`, which carries the per-run state the orchestrator
sets and reads back uniformly (`input_root`, `tz_overrides`, `last_stats`) — deliberately outside
the frozen protocol. See [`0006-configurable-adapter.md`](decisions/0006-configurable-adapter.md).

Registration is one line in `src/sift/adapters/__init__.py`:

```python
REGISTRY: dict[str, Adapter] = {
    "genericlog": GenericLogAdapter(),
    "journald":   JournaldAdapter(),
    "dsserrors":  DsserrorsAdapter(),
    "eustack":    EustackAdapter(),
    "dssperfmon": DssperfmonAdapter(),
}
```

`adapters.detect(path, relpath, overrides)` resolves the adapter for a file: a `glob=name` override
(CLI `--adapter`, then config, in insertion order) wins unconditionally; otherwise every registered
adapter sniffs the file and a unique maximum confidence at or above `SNIFF_THRESHOLD` (0.5) wins;
a tie or an all-below-threshold result falls back to `genericlog`. Iteration order is the fixed
`REGISTRY` insertion order, so detection is deterministic.

Sniffing always sees decompressed bytes: `base.open_bytes` detects gzip and zstd by magic bytes and
`base.read_head` reads the first 64 KiB of the decompressed stream. Timezone normalisation is a
single shared path (`to_utc`, `tz_override_for`), so `ts_confidence` is `exact` for
timezone-aware inputs and `inferred` where an override or UTC assumption was applied.

The five registered adapters are `genericlog`, `journald`, `dsserrors`, `eustack` and the v1.2
`dssperfmon` (PDH-CSV counter dumps). `dssperfmon` is the one adapter whose events are held out of
ranking — the exclusion lives in `store.py`, not in the adapter, so the adapter stays a plain
`sniff`/`parse` module like the rest. Adding adapter #6 still requires exactly a new module plus one
registration line.

## The LLM boundary

`src/sift/llm/client.py` is the only module in Sift that opens HTTP. `InferenceClient` speaks the
OpenAI-compatible surface — `/v1/embeddings`, `/v1/chat/completions`, `/v1/models` — plus
llama.cpp's server-root `/props` and `/tokenize`, over an *injected* `httpx.Client`. No vendor SDK
is imported. Tests bind a `MockTransport`, so no socket ever opens.

Three controls are load-bearing:

- **Egress guard.** `_assert_local` refuses any `base_url` whose host is not `localhost`,
  `*.localhost`, or a literal loopback / RFC1918 / link-local IP, unless `allow_public` (the
  `--i-know-what-im-doing` break-glass) is set. It never resolves DNS — resolution would itself be
  egress and TOCTOU-racey. The guard runs at construction, for both the generation and embeddings
  endpoints. Reaching a host-side server from a container is covered by
  [`0011-quadlet-loopback-guard.md`](decisions/0011-quadlet-loopback-guard.md).
- **Manual backoff.** httpx's transport-level `retries=` only covers connection setup, so
  `_request` loops manually over `ConnectError`, `TimeoutException`, and status ≥ 500 with
  exponential backoff (`backoff_base * 2**attempt`).
- **Untrusted responses.** Embedding vectors are validated as non-empty lists of finite numbers of
  consistent dimension, reordered by the server's `data[].index`; chat content is capped at 100 000
  characters and empty/whitespace content is rejected as a malformed response.

Feature detection degrades rather than failing: `tokenize()` and `props()` return `None`/`{}` for
an absent endpoint, so Lemonade (which lacks `/tokenize`) works unmodified.

`src/sift/llm/budget.py` holds `PromptBudget`, which estimates tokens using the server's
`/tokenize` when available and a character heuristic otherwise, then `fit()` trims a list of
excerpts breadth-first — every excerpt is shortened before any excerpt is dropped, so no cluster
vanishes from the prompt entirely.

Constrained decoding uses llama.cpp's shape, `{"type": "json_schema", "schema": <schema>}`, with
the schema at `response_format.schema` — *not* OpenAI's deeper nesting — and never alongside a
`grammar` field. The schema comes from `HypothesisSet.model_json_schema()`.

## Citation validation — the anti-hallucination mechanism

The output contract is two Pydantic models in `models.py`, both `extra="forbid"`: `Hypothesis`
(`title`, `narrative`, `confidence`, `confidence_reasoning`, `supporting_event_ids`,
`contradicting_evidence`, `suggested_next_steps`) and `HypothesisSet` (`hypotheses`,
`timeline_summary`, `unexplained_signals`).

`hypothesise()` tracks a `prompted_ids` set — the exact universe of event ids the model was shown.
`_assemble` builds it as the union of three sources: the representative exemplar id of each ranked
cluster rendered as an `[evt:<event_id>] <message>` line, plus the ids `render_mcm_facts` printed,
plus the ids `render_perfmon_facts` printed. MCM and perfmon facts are the deliberate inverse of the
KB path: they are deterministic, LLM-free evidence spliced into the prompt as *cited-not-authored*
lines, so their ids join `prompted_ids` and become legitimately citable. Retrieved KB chunks are
spliced into a delimited block but are **never** added to `prompted_ids`, so a KB row can never
become a citation.

The state machine is:

1. `_generate` — one constrained chat call, `HypothesisSet` validation, then at most **one** repair
   round-trip that feeds the validation error back. If the second output is still invalid, the run
   *degrades*: the raw text is persisted under `meta.triage_raw` so nothing disappears silently.
2. `_citation_gate` — enforces `cited ⊆ prompted`. Because `prompted_ids` are stored exemplar ids,
   this transitively enforces `cited ⊆ prompted ⊆ store`. If any hypothesis cites an id outside the
   set, the model is asked to regenerate **once**. If the fresh output cites within the set, the run
   succeeds. Otherwise the offending hypotheses are flagged, not dropped: each row is persisted with
   its own `citations_valid` verdict (`_row_citations_valid`) and the run degrades.
3. `_persist` — hypotheses rows plus all `triage_*` meta are written inside one transaction, so a
   mid-persist failure rolls back to zero hypotheses rather than partial state.

Nothing here raises on bad model output. A transport failure, an SSRF refusal, or a malformed 200
body produces a *failed* `Outcome` (nothing persisted); schema or citation failure produces a
*degraded* `Outcome` (flagged output persisted). `sift analyze` maps these to its exit-code
contract — 0 success, 3 degraded, 1 failure, 2 usage — recorded in
[`0005-analyze-exit-codes.md`](decisions/0005-analyze-exit-codes.md). The renderers surface
degradation: `render_markdown` emits a **DEGRADED RUN** banner, a flagged count in the executive
summary, and a fenced "Raw model output (unvalidated)" section when raw text was persisted.

## Renderers

Every renderer in `src/sift/render/` is a pure function of an open `CaseStore` — no client is
constructed and no re-inference happens, which makes the zero-egress and determinism properties
obvious by construction.

- `markdown.py::render_markdown` — the primary report. Turns `[evt:<id>]` tokens in narratives into
  links to an evidence appendix built from `CaseStore.get_events_by_ids` (only the cited handful is
  hydrated, never the whole case). All store-derived text passes through `_util.sanitise` and
  Markdown structural escaping before output, and appendix `raw` is fenced and byte-capped.
- `json_out.py::render_json` — canonical key-sorted JSON with hypotheses, cluster stats, timeline
  summary, unexplained signals, and a `run` block (`model`, `prompt_hash`, `embedding_model`,
  `degraded`, `generated_at`). `normalise_for_determinism` strips `run.generated_at` plus absolute
  paths under path-named keys and duration-named keys, which defines the byte-equality comparison
  scope — see [`0008-report-determinism-scope.md`](decisions/0008-report-determinism-scope.md).
- `pdf.py::render_pdf` — Markdown → HTML → PDF via WeasyPrint, behind the optional `sift[pdf]`
  extra; a missing extra raises `PdfExtraMissing` with an actionable message rather than an import
  error. See [`0002-weasyprint-pdf-extra.md`](decisions/0002-weasyprint-pdf-extra.md). The URL
  fetcher blocks every external reference, so PDF rendering opens no sockets.
- `mcm_report.py` — the separate MCM forensics bundle (`mcm_report.md` or `.json`, plus
  `mcm_attribution.csv`) written by `sift mcm`.
- `perfmon_report.py` — the v1.2 perfmon correlation bundle written by `sift perfmon`:
  `render_perfmon_markdown` / `render_perfmon_json` produce `perfmon/perfmon_report.md` or
  `.json`, and `write_perfmon_trend_csv` writes `perfmon/perfmon_trend.csv`. The JSON path is
  key-sorted and `ensure_ascii=True`; the CSV path neutralises spreadsheet-formula triggers
  (`_csv_safe`). Like the other renderers it is a pure function of the analysis model — it
  constructs no client and opens no socket.

`sift report` exit codes are recorded in [`0007-report-exit-codes.md`](decisions/0007-report-exit-codes.md).

## The prompt-template layer

All prompts are Markdown files in `src/sift/prompts/`, loaded as package data via
`importlib.resources` and never executed: `triage.md`, `cluster_label.md`, `mcm_facts.md`,
`perfmon_facts.md`, `judge.md`. Changing a prompt never requires touching Python.

`triage.md` carries three delimited, optional blocks marked with HTML comments — a KB block, an
MCM block, and a perfmon block. `hypothesise._apply_kb_block`, `_apply_mcm_block` and
`_apply_perfmon_block` either splice content into the slot and strip the markers, or remove the
whole block residue-free when there is nothing to inject; each block is stripped independently so
perfmon presence can never perturb the no-perfmon or MCM-only prompt bytes. Each
assembled prompt is hashed (`sha256(prompt)[:16]`) into `meta.triage_prompt_hash`; the cluster-label
template hash goes to `meta.cluster_label_prompt_hash`. Identical inputs assemble an identical
prompt and therefore an identical hash, which is what makes a run reproducible.

Log-derived excerpts interpolated into a template are treated as untrusted data, not instructions.

## Configuration

`src/sift/config.py` resolves configuration by layering plain dicts and validating once with
Pydantic (`SiftConfig`, all sections `extra="forbid"` so a typo fails loudly). Precedence is
CLI flags > `SIFT_*` environment variables > `$XDG_CONFIG_HOME/sift/config.toml` > defaults.
Sections: `generation`, `embeddings`, `clustering`, `mcm` (with `mcm.thresholds`), plus the
`timezones` and `adapters` mappings, which are TOML/flag-only because they are nested mappings
rather than scalars. Model identity has no baked default — it comes from config or is left to the
server's loaded model.

## Evaluation harness

`src/sift/eval/` adds measurement, not pipeline behaviour. `runner.run_case` drives each golden
case under `eval/cases/` through the real ingest → cluster → hypothesise path against a temporary
`case.db` with an injectable client, then `metrics.py` scores it against a frozen `truth.yaml`
(`truth.py`): retrieval hit rate, hypothesis hit@k, citation validity rate, determinism stability,
and a negative-case pass for the no-incident case. `thresholds.py::gate` compares the suite against
`eval/thresholds.toml` and `report.py` renders the text or JSON table. `judge.py` adds an optional
advisory local-model judge score that never affects the gate. Exit codes are recorded in
[`0010-eval-exit-codes.md`](decisions/0010-eval-exit-codes.md).

## Directory structure rationale

```
src/sift/
├── cli.py           Typer entry point; orchestration only — no SQL, no HTTP
├── config.py        Layered config resolution and validation
├── models.py        Frozen Event dataclass + event_id; hypothesis output contract
├── store.py         The only SQL: schema, migrations, sqlite-vec, transactions
├── adapters/        Pluggable parsers (sniff/parse) + the registry
├── pipeline/        Stage logic: dedup, cluster, retrieve, salience, hypothesise, mcm, perfmon
├── llm/             The only HTTP: InferenceClient + PromptBudget
├── prompts/         Versioned Markdown prompt templates (package data)
├── render/          Pure store→text renderers: markdown, json, pdf, mcm + perfmon bundles
└── eval/            Golden-case harness: runner, metrics, thresholds, judge
docs/decisions/      Architecture decision records (ADR 0001–0013)
eval/cases/          Golden cases with frozen truth files
tests/               pytest suite; no test ever opens a socket
deploy/              Container/Quadlet deployment assets
```

The boundaries exist to keep four claims cheaply auditable: only `store.py` writes SQL, only
`llm/client.py` opens HTTP, only `prompts/` holds prompt text, and `render/` never re-infers. Each
of those is a one-directory review rather than a codebase-wide grep.

## Cross-cutting invariants

- **Determinism.** `event_id`, `template_id`, and prompt hashes are all `sha256(...)[:16]` of
  content-only inputs. Ordering is explicit everywhere (canonical event order, `count DESC` then id,
  score then `cluster_id`). Identical case + config + model + seed yields byte-identical JSON modulo
  the excluded volatile fields.
- **Nothing disappears silently.** Unparseable regions become `severity="unknown"` events; adapters
  emit per-file coverage; unvalidated model output is persisted and rendered; flagged citations stay
  visible rather than being dropped.
- **Untrusted inputs at every boundary.** A shared `case.db`, a log file, and an inference server
  response are all treated as hostile: allowlisted filters, decompression caps, defensive JSON
  coercion on read, and `sanitise` before anything reaches a terminal or a report.
- **No network in tests.** The inference client is injected, so the default suite runs with sockets
  blocked.
</content>
</invoke>
