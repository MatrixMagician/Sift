# Phase 6: Renderers & KB Retrieval - Context

**Gathered:** 2026-07-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Turn stored analysis (hypotheses, clusters, events) into a self-contained, reproducible triage report, and let `sift analyze` optionally draw on a knowledge-base directory. Delivers:

- `sift report <case> [--format md|json|pdf] [--out <path>]` — Markdown (primary), JSON, optional PDF.
- KB retrieval (`sift analyze --kb <dir>`) that demonstrably changes retrieved context (RAG-07).

Requirements in scope: **REPT-01, REPT-02, REPT-03, REPT-04, RAG-07** (Mode: MVP).

**Out of scope (own future work):** REPT-05 report redaction/sanitisation pass (mask hostnames/IPs/SIDs), REPT-06 per-cluster event-volume histogram. No web/TUI view.
</domain>

<decisions>
## Implementation Decisions

### KB Retrieval (RAG-07)
- **D-01:** KB runbooks/RCAs live in a **separate index/namespace**, NOT the case events/vectors table. KB chunks are **never assigned event_ids and can never appear in `supporting_event_ids`**. This preserves the load-bearing anti-hallucination invariant `cited ⊆ prompted ⊆ store` — only real case events are citable; KB is background reference context that enriches the prompt, not evidence.
- **D-02:** KB content informs the hypothesis prompt as retrieved context but is clearly delimited from citable events so the LLM (and the citation gate) cannot conflate the two.

### Evidence Appendix & Citations (REPT-01)
- **D-03:** `[evt:a1b2c3d4]` renders as an **intra-document anchor link** (e.g. `[evt:a1b2c3d4](#evt-a1b2c3d4)`) jumping to an evidence-appendix entry — the report is one self-contained file, one click from claim to evidence.
- **D-04:** Each appendix entry shows **file:line provenance + raw text truncated to a configurable cap** (default order ~2 KB) with an explicit elision marker. Prevents multi-line stack traces / MCM blocks from ballooning the report while keeping fidelity.
- **D-05:** Report sections: executive summary, ranked hypotheses (inline citations), evidence appendix, cluster inventory, timeline, unexplained signals, run metadata (models, prompt hashes, config), degraded-run banner when applicable.

### Determinism (REPT-03)
- **D-06:** Byte-identical JSON comparison **excludes: generated-at timestamps, absolute filesystem paths (case-relative paths retained), and wall-clock durations**. Everything else — hypotheses, citations, cluster stats, ordering — must be byte-identical.
- **D-07:** Seed is passed through to the server; the determinism claim is **scoped and documented against known llama-server seed caveats** (backend may not guarantee bit-exact generation). The reproducibility test normalises the excluded fields, then asserts byte equality.

### PDF Path (REPT-04)
- **D-08:** PDF = **Markdown → HTML → WeasyPrint** (reuses the Markdown renderer), per ADR 0002, behind the `sift[pdf]` extra.
- **D-09:** **External URL fetching disabled** — custom `url_fetcher` blocks non-local resource fetches (zero-egress invariant).
- **D-10:** When `sift[pdf]` is not installed, `sift report --format pdf` exits with a **helpful message** ("install sift[pdf] and pango") — never a traceback.

### Claude's Discretion
- KB chunking strategy, retrieval `k`, and KB-vs-event share of the prompt budget — resolve in research/planning against `PromptBudget` (Phase 3) breadth-first truncation; keep KB an additive slice that provably changes retrieved context in a test.
- Exact Markdown section ordering and metadata layout, subject to D-05.
- Cluster labelling is **already resolved**: eager during Phase 3 clustering, persisted to `clusters.label` (SPEC §10 open question #3 closed). `sift report` reads persisted labels — do NOT re-label at report time.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Specification
- `SPEC.md` §5.7 Renderers — Markdown/JSON/PDF contract, `[evt:…]` links, evidence appendix, reproducibility requirement.
- `SPEC.md` §5.8 CLI Design — `sift report` / `sift analyze --kb` signatures, config precedence, prompt-template-file rule.
- `SPEC.md` §5.5 — citation validation (anti-hallucination) that KB retrieval must not weaken.
- `SPEC.md` §10 — open questions #2 (reportlab vs weasyprint, resolved by ADR 0002) and #3 (cluster labelling eager vs lazy).

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — REPT-01..04, RAG-07 (in scope); REPT-05, REPT-06 (deferred).
- `.planning/ROADMAP.md` §"Phase 6: Renderers & KB Retrieval" — goal + 4 success criteria.

### Decisions
- `docs/decisions/` ADR 0002 — WeasyPrint behind `sift[pdf]` extra (PDF approach).

### Reusable code (see code_context)
- `src/sift/pipeline/` (retrieval, budget), `src/sift/models.py` (Event, hypothesis schema), `src/sift/store.py` (vectors/sqlite-vec), `src/sift/prompts/*.md`.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sift/pipeline/` — Phase 4 RAG retrieval + `PromptBudget` breadth-first truncation: KB retrieval slots in here as an additive context source.
- `src/sift/store.py` — sqlite-vec vectors table + `vec_version()`; the escape-hatch (BLOB + numpy) pattern applies if a separate KB index is added. Keep all vector access confined here.
- `src/sift/models.py` — hypothesis object + Event dataclass drive both JSON serialisation and Markdown rendering.
- `src/sift/prompts/*.md` — versioned templates; any KB-context prompt change is a template edit, not Python (CLAUDE.md invariant).
- Existing `_sanitise` (render-time control-char stripping, Phase 4) — reuse for report output.

### Established Patterns
- Citation gate `cited ⊆ prompted ⊆ store` (Phase 4, plan 04-04) — KB non-citability (D-01) is designed to preserve it.
- `sift analyze`/`show hypotheses` CLI vertical with 0/3/1/2 exit-code contract (ADR 0005) — `sift report` should follow the same exit-code discipline.
- `sift report` is currently a Phase-6 stub at `src/sift/cli.py:838`.

### Integration Points
- `sift report` reads persisted hypotheses/clusters/events from `case.db` (no re-inference).
- `sift analyze --kb <dir>` extends the existing analyze path with an optional KB index build/retrieve step.
- New `src/sift/render/` package (does not yet exist) + `src/sift/pipeline/retrieve.py` KB index (per SPEC §"code layout").
</code_context>

<specifics>
## Specific Ideas

Report must be handed to a colleague as one self-contained file where every claim is one click from raw evidence (phase goal). Determinism is a scoped, documented guarantee — not an absolute claim — given nondeterministic local backends.
</specifics>

<deferred>
## Deferred Ideas

- **REPT-05** — report redaction/sanitisation pass (mask hostnames/IPs/SIDs): own future requirement, out of Phase 6 scope.
- **REPT-06** — per-cluster event-volume histogram in reports: render-only enhancement, deferred.
- Web/TUI report viewer — explicitly a v2 candidate per SPEC §"Non-goals".
</deferred>

---

*Phase: 6-renderers-kb-retrieval*
*Context gathered: 2026-07-18*
