# Requirements: Sift — Local-LLM Incident Triage Engine

**Defined:** 2026-07-16
**Core Value:** Turn a directory of raw diagnostics into a structured, evidence-cited triage report — entirely offline, with every claim citing verifiable event IDs.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Ingestion

- [ ] **INGST-01**: User can create a case from a directory of artefacts (`sift new`) and ingest it (`sift ingest`), producing canonical Event records with deterministic IDs (`sha256(source_file, byte_offset)[:16]`)
- [ ] **INGST-02**: Re-ingesting the same case adds zero new events (idempotent)
- [ ] **INGST-03**: Adapters auto-detect file formats via `sniff()` on first 64 KB; highest confidence ≥ 0.5 wins, fallback to genericlog; `--adapter glob=name` overrides
- [ ] **INGST-04**: genericlog adapter parses timestamped line-based logs (ISO 8601, syslog, epoch) and groups continuation lines into the preceding event
- [ ] **INGST-05**: Unparseable regions become `severity="unknown"` events (nothing dropped silently), and each file reports a parse-coverage metric (% of bytes attributed to events)
- [ ] **INGST-06**: Multi-line records (stack traces, MCM contract blocks, thread frames) are captured as one event, not one per line
- [ ] **INGST-07**: journald adapter parses `journalctl -o json` export files, mapping PRIORITY→severity, _SYSTEMD_UNIT→component, _PID/_COMM→attrs
- [ ] **INGST-08**: dsserrors adapter parses DSSErrors.log and rotated `.bak` siblings — extracts timestamp, thread, severity, component, multi-line MCM blocks, 0x error codes, SIDs, OIDs, and multi-node tags from directory names
- [ ] **INGST-09**: eustack adapter parses EU-stack/thread-dump files — one event per thread with condensed top frames, full stack in raw, lock info in attrs
- [ ] **INGST-10**: User can ingest gzip/zstd-compressed input files without manual decompression
- [ ] **INGST-11**: Timestamps normalise to UTC with per-node timezone override support and explicit `ts_confidence` so multi-node timelines cannot silently invert causality

### Case Store

- [ ] **STORE-01**: Each case persists to a single portable SQLite database (`case.db`) with sqlite-vec for vectors; deleting the file deletes the case
- [ ] **STORE-02**: Store owns schema migrations (PRAGMA user_version); `raw` text > 4 KB is zstd-compressed
- [ ] **STORE-03**: Embedding model identity and dimension are recorded in `meta`; a mismatch on reload is a hard error
- [ ] **STORE-04**: User can inspect stored data via `sift show <case> events|clusters|hypotheses [--filter …]` before trusting any AI output

### Dedup & Clustering

- [ ] **CLUS-01**: Template dedup masks volatile tokens (numbers, hex, UUIDs, SIDs, paths, timestamps) and groups events by normalised template with count, first/last seen, and exemplars — no ML required
- [ ] **CLUS-02**: Semantic clustering embeds one exemplar per template group and merges synonymous groups via HDBSCAN (L2-normalised; agglomerative fallback from config; noise points become singleton clusters)
- [ ] **CLUS-03**: Each cluster gets a short LLM-generated human-readable label from exemplars only, under a strict token budget

### Analysis (RAG)

- [ ] **RAG-01**: Clusters are ranked by a salience score combining severity, count, burstiness, novelty, and temporal proximity to a user-supplied incident time
- [ ] **RAG-02**: `sift analyze` produces ranked root-cause hypotheses conforming to the enforced JSON contract (title, narrative, confidence + reasoning, supporting_event_ids, contradicting_evidence, suggested_next_steps, timeline_summary, unexplained_signals)
- [ ] **RAG-03**: JSON output is enforced via constrained decoding where available, validated with Pydantic, repaired once on failure, and degrades gracefully (raw output persisted, run marked degraded) — never crashes
- [ ] **RAG-04**: Every cited event ID must exist in the case store AND have been present in the prompt ("cited ⊆ prompted"); invalid hypotheses are regenerated (max 1 retry) then flagged in the report
- [ ] **RAG-05**: A PromptBudget utility estimates tokens (server tokenize endpoint or chars/4 heuristic), reserves output headroom, and truncates exemplars breadth-first
- [ ] **RAG-06**: User can supply `--hint` free text and `--since/--until` time-window filters to scope analysis
- [ ] **RAG-07**: User can point analysis at a knowledge-base directory of Markdown runbooks/RCAs, retrieved by similarity into the triage context

### Inference Client

- [ ] **LLM-01**: All inference goes through one OpenAI-compatible client (`/v1/chat/completions`, `/v1/embeddings`) with per-role base_urls, timeouts, retries with backoff, and batched embeddings — no vendor SDK
- [ ] **LLM-02**: Non-loopback/non-RFC1918 endpoints are refused unless `--i-know-what-im-doing` is set; zero network egress otherwise
- [ ] **LLM-03**: `sift doctor` verifies both endpoints with real round-trips (including an actual embedding call), reports model IDs, checks embedding dimension against existing index, and warns on determinism-breaking server configs (e.g. multi-slot)
- [ ] **LLM-04**: llama.cpp-specific features (`/props`, `/tokenize`, grammar-constrained decoding, non-OpenAI `response_format` nesting) are feature-detected, never required — Lemonade Server works unmodified

### Reports

- [ ] **REPT-01**: `sift report` renders Markdown (primary) with executive summary, ranked hypotheses, inline `[evt:…]` citations linked to an evidence appendix showing raw text with file:line provenance, cluster inventory, timeline, unexplained signals, and run metadata
- [ ] **REPT-02**: JSON report contains the full hypotheses object plus cluster stats for downstream tooling
- [ ] **REPT-03**: Identical case + config + model + seed produces byte-identical JSON apart from timestamps (determinism scoped and documented against known llama-server caveats)
- [ ] **REPT-04**: User can optionally render a PDF report (via `sift[pdf]` extra)

### CLI & UX

- [ ] **CLI-01**: CLI exposes `new`, `ingest`, `analyze`, `report`, `show`, `eval`, `doctor` subcommands with config precedence: flags > `SIFT_*` env > `~/.config/sift/config.toml` > defaults
- [ ] **CLI-02**: All prompts live as versioned template files in the package; changing a prompt requires no Python changes
- [ ] **CLI-03**: Long operations (ingest, embedding, generation) show progress feedback
- [ ] **CLI-04**: Exit codes form a documented contract (success / degraded run / failure) so `sift` is scriptable in CI

### Evaluation

- [ ] **EVAL-01**: Golden suite of ≥ 5 synthetic-but-realistic cases, each with `input/`, `truth.yaml`, and README (e.g. memory-watermark cascade, SMTP rejection storm, thread-pool exhaustion, disk-full, dependency timeout)
- [ ] **EVAL-02**: `sift eval` reports retrieval hit rate, hypothesis hit@k, citation validity rate, and determinism drift across repeated runs
- [ ] **EVAL-03**: `sift eval` exits non-zero when scores regress below `eval/thresholds.toml` thresholds (CI-friendly)
- [ ] **EVAL-04**: Optional LLM-as-judge grading via the same local model, reported alongside keyword scores
- [ ] **EVAL-05**: Tests never call the network: the LLM client is injectable and tests run against a fake OpenAI-compatible server

### Packaging

- [ ] **PKG-01**: `uv tool install` from a clean checkout yields a working `sift` (pipx-compatible)
- [ ] **PKG-02**: Optional Podman Quadlet deployment files ship with a llama-server example, documented for Fedora/gfx1151 (Vulkan and ROCm notes)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Reports

- **REPT-05**: Report redaction/sanitisation pass (mask hostnames/IPs/SIDs) — also reusable for sanitising real cases into golden eval cases
- **REPT-06**: Event-volume histogram per cluster in reports (render-only; data already stored)

### Analysis

- **RAG-08**: Case baseline diff — "what's new vs a known-good case"

### Interface

- **UI-01**: TUI or web report viewer

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Live/streaming ingestion (tail -f) | Different architecture (stateful watch/alerting); batch determinism is the v1 identity |
| Agentic tool-calling investigation loop | Nondeterministic, unbounded token cost, breaks citation auditing — opposite of the trust model |
| Chat/conversational interface | Invites automation bias; unauditable; `--hint` + reviewable reports are the interaction surface |
| Cloud LLM fallback | Destroys the reason the product exists; hard loopback refusal instead |
| Auto-remediation / command execution | Acting on hallucinated RCA is the nightmare scenario; humans act |
| Model management (download/quantise/serve) | llama.cpp / Lemonade own this; duplicating it is a maintenance tar pit |
| Deep-learning anomaly-detection suite | Heavy deps, GPU entanglement, no training data; dedup + embeddings + HDBSCAN covers triage |
| Alerting integrations (Slack, PagerDuty, webhooks) | Network egress by definition; users pipe JSON output wherever they like |
| Telemetry/usage analytics | Instant disqualification for the target audience |
| Fine-tuning | Prompting + RAG only (SPEC non-goal) |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (populated by roadmap) | | |

**Coverage:**
- v1 requirements: 40 total
- Mapped to phases: 0
- Unmapped: 40 ⚠️ (pending roadmap)

---
*Requirements defined: 2026-07-16*
*Last updated: 2026-07-16 after initial definition*
