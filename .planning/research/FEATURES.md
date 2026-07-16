# Feature Landscape

**Domain:** Local-first LLM-powered incident/log triage CLI
**Researched:** 2026-07-16
**Overall confidence:** MEDIUM (web-verified across multiple independent sources; no single authoritative spec for the category)

## How the Ecosystem Splits

Four families of prior art, each defining a slice of user expectations:

1. **CLI log viewers** (lnav, angle-grinder, GoAccess) — set expectations for ingestion UX: auto-detect formats, handle compressed/rotated files, merge multi-file timelines, filter, "point at a directory and it works".
2. **Log-mining libraries** (Drain3, LogAI, LogPAI ecosystem) — set expectations for the analysis core: template mining, dedup, clustering, anomaly detection. Libraries, not products; no end-user workflow.
3. **LLM triage agents** (k8sgpt, HolmesGPT) — set expectations for AI output: human-readable explanations, ranked findings, suggested next steps, runbook/knowledge integration. Both are cloud-LLM-first and Kubernetes-scoped; HolmesGPT is agentic (nondeterministic ReAct loop), k8sgpt is deterministic analyzers + LLM explanation.
4. **Commercial AIOps** (BigPanda, PagerDuty AIOps, Datadog Event Management, Splunk ITSI) — set expectations for the pipeline shape: normalise → deduplicate (70–85% compression is the marketed norm) → correlate → root-cause → reduce noise. This is exactly Sift's pipeline, minus the SaaS.

The local/offline niche is nearly empty: existing "local LLM log analysis" tools are single-file Ollama prompt wrappers with no event schema, no dedup, no citations, no eval. Sift's SPEC already targets the actual gap. (Confidence: LOW→MEDIUM — absence of tooling is hard to prove, but repeated searches surfaced only prototypes.)

## Table Stakes

Features users expect. Missing = product feels incomplete. "SPEC" column = already covered by SPEC.md v0.1.

| Feature | Why Expected | Complexity | SPEC? | Notes |
|---------|--------------|------------|-------|-------|
| Normalise heterogeneous inputs to one event schema | Universal AIOps baseline; lnav's core trick | Med | Yes (§5.1–5.2) | Canonical `Event` + adapters |
| Format auto-detection | lnav sets the bar ("point at a directory") | Low | Yes (§5.2 sniff) | 64 KB sniff + genericlog fallback |
| Robust generic/fallback parser (nothing dropped silently) | Users judge tools by the file it *can't* parse | Med | Yes (§5.2 rule) | `severity="unknown"` events + parse-coverage metric is stronger than most tools |
| Deduplication with counts (template mining) | 70–85% compression is the marketed AIOps norm; Drain-style masking is standard | Med | Yes (§5.4) | Cheap-first masking before ML matches industry practice |
| Correlation/clustering of related events | Core AIOps value: alerts → few incidents | Med | Yes (§5.4) | Embeddings + HDBSCAN |
| Ranked root-cause findings, human-readable | k8sgpt/HolmesGPT norm | High | Yes (§5.5) | |
| Suggested next steps per hypothesis | Present in every LLM triage tool | Low | Yes (§5.5 JSON) | |
| Timeline reconstruction | Incident responders think in timelines | Med | Yes (§5.5, §5.7) | |
| Machine-readable output (JSON) + stable exit codes | CLI tools live in scripts/CI | Low | Mostly | JSON yes; **gap:** define exit-code contract for `analyze` (e.g. non-zero on degraded run) |
| Compressed/rotated file handling (.gz, .zst, .bak siblings) | lnav auto-decompresses; rotated logs are the normal case | Low | **Partial gap** | SPEC covers dsserrors `.bak` but not gzip/zstd inputs generally — add to genericlog/ingest |
| Time-window scoping (`--since`/`--until`) | journalctl/lnav muscle memory; triage is time-anchored | Low | **Gap** | SPEC has `--hint` free text only; a hard time filter on analyse (and ideally ingest) is expected |
| Progress feedback on long operations | 2 GB ingest + local-LLM latency; silent CLI = "is it hung?" | Low | **Gap** | Coverage stats exist post-hoc; add progress reporting during ingest/embed/generate |
| Inspection commands (query events/clusters before trusting AI) | lnav's SQLite querying; engineers verify | Med | Yes (§5.8 `sift show`) | Filterable show is the trust bridge |
| Health check of dependencies | Local inference is flaky; k8sgpt has `auth`/backend checks | Low | Yes (`sift doctor`) | |
| Easy install, no daemon | "Simple tools win" — recurring theme in CLI tool adoption | Low | Yes (§M8, SQLite) | |

## Differentiators

Not expected, but valued — Sift's competitive edge for its niche.

| Feature | Value Proposition | Complexity | SPEC? | Notes |
|---------|-------------------|------------|-------|-------|
| Hard citation validation (claims must cite real event IDs) | Directly answers the #1 adoption blocker: hallucination/trust (51% rate it top challenge; CISOs distrust conclusions that don't match evidence). No surveyed tool enforces this | Med | Yes (§5.5) | The load-bearing differentiator — keep it hard-fail |
| `unexplained_signals` honesty section | Anti-automation-bias: showing what the model *can't* explain builds trust faster than confident narrative | Low | Yes (§5.5 JSON) | Rare in the wild; keep |
| Fully offline, backend-agnostic (OpenAI-compatible only), loopback-enforced | The niche driver: regulated/air-gapped users (GDPR/HIPAA/SOC2). Existing local tools are prototypes; agents are cloud-first | Med | Yes (§5.6) | Refuse-non-loopback is itself a marketable feature |
| Determinism + reproducible reports | Auditable RCA; agentic competitors (HolmesGPT) are inherently nondeterministic | Med | Yes (§5.7) | Pairs with eval harness |
| Evaluation harness with golden incidents + CI thresholds | No local tool measures itself; converts "vibes" into regression-tested quality | High | Yes (§6) | Also a credibility asset in the README |
| Deep domain adapters (dsserrors, eustack) | Encodes MicroStrategy expertise no generic tool has; multi-line MCM blocks, SIDs, multi-node tags | Med–High | Yes (§5.2) | The moat for the author's user base |
| Local knowledge-base retrieval (runbooks/prior RCAs) | HolmesGPT's runbooks are its most-praised feature; Sift gets the same effect statically and deterministically | Med | Yes (§5.5) | |
| Evidence appendix with file:line provenance | Reviewers can jump from claim to raw text; deeper than any surveyed tool's output | Low | Yes (§5.7) | |
| Report redaction/sanitisation pass | Privacy users eventually need to *share* the report (vendor support, tickets) even though inputs stay local; masking hostnames/IPs/SIDs on render extends the privacy story end-to-end | Med | **Gap (v1.x candidate)** | Also needed anyway to sanitise real cases into golden eval cases — consider building once, using twice |
| Event-volume histogram in report (counts over time per cluster) | lnav's histogram is beloved; a burstiness sparkline/table strengthens the timeline | Low | **Gap (cheap add)** | Data already exists (first/last_ts, counts); render-only |
| Case baseline diff ("what's new vs a known-good case") | Classic triage question; LogReducer-style delta analysis | High | Gap (defer to v2) | Needs two-case comparison machinery; note in roadmap, don't build |

## Anti-Features

Features to explicitly NOT build — each is somewhere in the ecosystem and would damage this product.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Agentic tool-calling investigation loop (HolmesGPT-style ReAct) | Nondeterministic, unbounded token cost on local hardware, breaks citation auditing and reproducibility — the opposite of Sift's trust model | Fixed pipeline: salience-ranked retrieval → one constrained generation → validation |
| Chat/conversational interface | Invites automation bias; unauditable; scope creep towards a product Sift isn't | `--hint` for user context; reviewable reports as the interaction surface |
| Cloud LLM fallback ("degrade to OpenAI when local is slow") | Destroys the only reason the product exists; one accidental egress = trust gone | Hard loopback/RFC1918 refusal (already in SPEC §5.6) |
| Auto-remediation / suggested-command execution | Acting on hallucinated RCA is the nightmare scenario the trust literature warns about | `suggested_next_steps` as text; humans act |
| Live streaming/tail mode | Different architecture (stateful watch, alerting); batch determinism is the v1 identity | Batch cases; re-ingest is idempotent and cheap |
| Deep-learning anomaly-detection suite (LogAI-style CNN/LSTM/Transformer) | Heavy deps, GPU entanglement, training data Sift doesn't have; LogAI exists for researchers | Template dedup + embeddings + HDBSCAN covers the triage need |
| Alerting/notification integrations (Slack, PagerDuty, webhooks) | Network egress by definition; SaaS-platform territory | JSON output; users pipe it wherever they like |
| Model management (download/quantise/serve) | llama.cpp and Lemonade own this; duplicating it is a maintenance tar pit | `sift doctor` diagnoses the endpoint; README documents setup |
| Web UI/TUI in v1 | "Simple CLI tools win"; UI triples surface area before the pipeline is proven | Markdown/PDF reports are the UI; revisit post-v1 |
| Telemetry/usage analytics | Instant disqualification for the target audience | None. Ever. |

## Feature Dependencies

```
Event schema → adapters (genericlog → journald/dsserrors/eustack)
Event schema → case store → template dedup → semantic clustering
Inference client → doctor
Inference client + clustering → cluster labels → salience → RAG hypothesis generation
Hypothesis generation → citation validation → renderers (MD → JSON → PDF)
KB retrieval → RAG (optional input)
Full pipeline → eval harness (golden cases exercise everything)
Renderers → redaction pass (gap; render-time feature)
Cluster stats (first/last_ts, count) → histogram rendering (gap; render-time feature)
Time-window filter (gap) → sits at ingest/analyse boundary; independent of LLM features
```

Notably, all three cheap gap-fills (time filter, progress reporting, histogram) have no dependency on the LLM stack — they slot into M1–M2 and M6 respectively without touching the RAG core.

## MVP Recommendation

The SPEC's M1–M8 ordering already matches the ecosystem's dependency structure (pipeline before AI, AI before polish). Adjustments from this research:

1. **Fold the three cheap table-stakes gaps into existing milestones:** gzip/zstd input handling + `--since/--until` + progress reporting into M1–M2; exit-code contract into M4; histogram into M6. All Low complexity.
2. **Keep citation validation and the eval harness sacred** — they are the answer to the domain's #1 complaint (hallucination/trust) and no competitor has them locally.
3. **Defer, but record:** report redaction (v1.x — build alongside golden-case sanitisation in M7 if it falls out naturally), case baseline diff (v2), TUI/web view (v2).
4. **Resist:** everything in the anti-features table, especially agentic loops and cloud fallback — the surveyed products that have them serve a different (cloud, interactive) market.

## Sources

- [HolmesGPT: Agentic troubleshooting (CNCF blog)](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/) — MEDIUM
- [HolmesGPT documentation](https://holmesgpt.dev/0.35.0/) — MEDIUM
- [Open Source AI SRE tools comparison (Arvo)](https://www.aurorasre.ai/blog/open-source-ai-sre-aurora-vs-holmesgpt-vs-k8sgpt) — LOW (vendor blog, cross-checked with CNCF/docs)
- [salesforce/logai (GitHub)](https://github.com/salesforce/logai) + [LogAI paper](https://arxiv.org/pdf/2301.13415) — MEDIUM
- [lnav features (official)](https://lnav.org/features) + [tstack/lnav](https://github.com/tstack/lnav) — MEDIUM
- [AIOps features overview (Splunk)](https://www.splunk.com/en_us/blog/learn/aiops.html), [Selector AIOps tools guide](https://www.selector.ai/learning-center/aiops-tools-key-features-and-top-8-solutions/) — MEDIUM (consistent across vendors)
- [Local LLM log analysis prototypes: llm-rca-assistant](https://github.com/Mustafa3946/llm-rca-assistant), [stratosphereips/llm-log-analyzer](https://github.com/stratosphereips/llm-log-analyzer), [Ollama log analysis write-up](https://dev.to/devopsstart/local-llm-for-log-analysis-privacy-first-debugging-with-ollama-361o) — LOW
- [AI hallucination trust surveys/commentary (Dropzone AI)](https://www.dropzone.ai/blog/when-ai-gets-it-wrong-the-critical-importance-of-context-engineering), [CSO Online](https://www.csoonline.com/article/4143444/9-ways-cisos-can-combat-ai-hallucinations.html) — MEDIUM (consistent across sources)
