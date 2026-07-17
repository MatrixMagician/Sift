# Phase 4: Salience, RAG & Citation-Gated Hypotheses - Research

**Researched:** 2026-07-17
**Domain:** Salience ranking, RAG prompt assembly, constrained-decoding + Pydantic enforcement, citation-gated anti-hallucination, exit-code contract
**Confidence:** HIGH (design is SPEC-driven and builds on frozen Phase 1–3 interfaces read directly from source; the only MEDIUM items are the live-server behaviours of llama.cpp constrained decoding)

## Summary

Phase 4 is the load-bearing slice: it turns the clusters produced by the Phase 3 clustering leg into ranked, evidence-cited root-cause hypotheses that *cannot cite what the model was never shown*. The pipeline stages to build are **salience → retrieve/assemble → hypothesise (generate + enforce + citation-gate) → persist**, chained onto the existing `sift analyze` command (which today stops after clustering + labelling).

Almost everything Phase 4 needs already exists as frozen contracts. `InferenceClient.chat()` is the single HTTP boundary (needs one additive extension for `response_format`); `PromptBudget` already does breadth-first truncation and `/tokenize`-or-`//4` estimation; `CaseStore` owns migrations and holds `clusters` (with member `template_ids`) and `template_groups` (with `first_ts`/`last_ts`/`count`/`severity_max`/`exemplar_event_ids`) — the raw material for both salience features and the "prompted set" of event IDs. **No new third-party dependency is required**: Pydantic 2.13.4, httpx, respx, scikit-learn and numpy are all already installed and in `pyproject.toml`.

The two hard requirements are the enforcement pipeline (RAG-03: constrained decode → Pydantic validate → one repair → degrade, never crash) and the citation gate (RAG-04: every `supporting_event_ids` entry must be `∈ prompted ∧ ∈ store`, regenerate once, then flag). Because the prompted event IDs are drawn *from the store* (`template_groups.exemplar_event_ids`), `cited ⊆ prompted` transitively satisfies `cited ⊆ store`, so the in-memory prompted set is the operational gate. These two retry budgets (schema-repair=1, citation-regenerate=1) are **distinct** and compose. The exit-code contract (CLI-04) maps success→0, degraded→3, failure→1, keeping Typer's usage-error 2 free.

**Primary recommendation:** Add `pipeline/salience.py` (pure, deterministic, aggregates cluster features from member template groups), `pipeline/hypothesise.py` (assemble prompt + prompted-id set, call `chat` with the llama.cpp `response_format.schema` shape, run the validate/repair/degrade + citation-gate state machine), Pydantic `HypothesisSet` models in `models.py`, a versioned `prompts/triage.md`, store migration 4 (`hypotheses` table + run-level meta), an additive `chat(..., response_format=…)` parameter, and extend `analyze` with `--hint/--since/--until/--top-clusters` and the 0/3/1 exit-code contract. Keep salience weights as hand-tuned module constants (SPEC OQ4) and do **not** build KB retrieval (that is RAG-07 / Phase 6).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Salience scoring | `pipeline/salience.py` (pure compute) | `store.py` (reads clusters + template_groups) | Deterministic ranking is a pure function of stored features; no I/O, no LLM |
| Triage-context assembly + prompted-id tracking | `pipeline/hypothesise.py` | `llm/budget.py` (token fit) | Breadth-first selection of cluster exemplars is where the prompted event-id set is defined; must live next to the code that sends the prompt |
| Constrained decoding request | `llm/client.py` (`chat`) | — | Single HTTP boundary (SPEC §5.6); the llama.cpp `response_format.schema` nesting belongs here, nowhere else |
| Schema validation / repair / degrade | `pipeline/hypothesise.py` | `models.py` (Pydantic) | Enforcement is orchestration over the Pydantic contract; models own the shape only |
| Citation gate (cited ⊆ prompted ⊆ store) | `pipeline/hypothesise.py` | — | The prompted set is only known where the prompt was built |
| Hypothesis persistence + run status | `store.py` (migration 4) | — | Store owns all schema + migrations (frozen invariant) |
| CLI surface (`--hint/--since/--until`), exit codes | `cli.py` | `config.py` (defaults) | Typer command owns flag parsing and process exit; pipeline stays print-free/typer-free |
| Prompt text (triage instructions + schema hint) | `prompts/triage.md` | — | CLI-02: changing a prompt must never require touching Python |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.13.4 (installed) | `HypothesisSet` schema, `model_validate_json`, `model_json_schema()` feeding constrained decoding | Already the project's validation backbone (config.py); `model_json_schema()` output is exactly what llama.cpp's JSON-schema decoder consumes [CITED: ./CLAUDE.md Validation Findings §5] |
| httpx | 0.28.1 (installed) | Transport under `InferenceClient` | Single HTTP boundary already built in Phase 3 |
| scikit-learn / numpy | 1.9.x / 2.x (installed) | Already used by clustering leg; salience needs only stdlib maths | No new use; salience is plain arithmetic |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| respx | 0.23.1 (installed) | `httpx.MockTransport` fake OpenAI server in tests | All Phase 4 tests (EVAL-05); return canned chat JSON incl. bad-citation and malformed variants |
| stdlib `datetime`, `math`, `json`, `hashlib` | — | Timestamp deltas, exponential proximity, prompt hashing, JSON (de)serialise | Salience + persistence + prompt_hash |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled validate/repair state machine | `instructor` / `outlines` | Explicitly forbidden by CLAUDE.md ("What NOT to Use") — framework weight + hides the request shape Sift must control; the ~1-repair loop is ~30 lines |
| `response_format.schema` constrained decoding | GBNF `grammar` field | Both are llama.cpp-specific; JSON-schema is derived free from Pydantic. Grammar is a fallback only if a target build mishandles `$defs` (see Open Questions) — never send both (hard error) [CITED: ./CLAUDE.md §5] |
| Salience weights in config | Module constants | SPEC OQ4: "start hand-tuned, revisit after golden-suite metrics." Constants now; graduate to a `[salience]` config section in Phase 7 if eval tuning demands it |

**Installation:** None. All Phase 4 dependencies are already present. Verified in-venv:
```bash
uv run python -c "import pydantic, httpx, respx, sklearn, numpy; print(pydantic.VERSION)"  # -> 2.13.4
```

## Package Legitimacy Audit

> No external packages are added in Phase 4. All libraries used are already declared in `pyproject.toml` and installed in `.venv` (verified above).

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| *(none added)* | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RAG-01 | Clusters ranked by salience (severity, count, burstiness, novelty, temporal proximity to incident time) | Salience formula below; features aggregated from `template_groups` (clusters lack timestamps — see Pitfall 1). Incident time = `--until` else case-end |
| RAG-02 | `sift analyze` produces ranked hypotheses matching the enforced JSON contract | `HypothesisSet` Pydantic model mirrors SPEC §5.5 verbatim; persisted to migration-4 `hypotheses` table |
| RAG-03 | Constrained decode where available → Pydantic validate → one repair → degrade, never crash | Enforcement state machine (Pattern 2); `chat(response_format=…)` extension; degrade persists raw + marks run |
| RAG-04 | Every cited event ID ∈ store ∧ ∈ prompt; regenerate max 1, then flag | Citation gate (Pattern 3); prompted set tracked during breadth-first assembly; `cited ⊆ prompted` is the operational gate |
| RAG-06 | `--hint` free text + `--since/--until` window filters | CLI extension; `--hint` passed verbatim into prompt (never parsed for a timestamp); window filters salience input at cluster granularity |
| CLI-04 | Documented exit-code contract (success/degraded/failure) | 0 / 3 / 1 mapping (Pattern 4); Typer usage-error 2 left untouched |
| STORE-04 (partial) | `sift show hypotheses` completes the partial-scope inspection target | Currently stubbed at `cli.py:485`; migration-4 `query_hypotheses` + sanitised render finishes it. Traceability assigns the hypotheses target to Phase 4 |

## Architecture Patterns

### System Architecture Diagram

```
 sift analyze <case> [--hint][--since][--until][--top-clusters N][--no-label][--model]
        │
        ▼
 load_config ──► CaseStore(case.db)      InferenceClient (generation + embeddings endpoints)
        │                                        │  (SSRF-guarded, injected httpx)
        ▼                                        │
 [Phase-3 leg]  cluster_and_label ───────────────┘   (embeds groups, writes clusters/chunks/vectors)
        │
        ▼  clusters + member template_groups (first_ts/last_ts/count/severity/exemplar_event_ids)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ salience.rank()  ── pure, deterministic ──►  ranked [(cluster, score)] │
 │   features: severity, count(log-norm), burstiness, novelty, proximity  │
 │   incident_time = --until or case last_ts;  window filter [since,until]│
 └───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ hypothesise.assemble()                                                 │
 │   breadth-first over top-N clusters via PromptBudget(ctx from /props)  │
 │   each line: [evt:<event_id>] <exemplar excerpt>                       │
 │   ⇒ prompt_text  +  prompted_ids : set[str]   (the citable universe)   │
 └───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ hypothesise.generate()  — the enforcement state machine                │
 │   1. chat(messages, response_format={"type":"json_schema",             │
 │            "schema": HypothesisSet.model_json_schema()})               │
 │   2. json.loads → HypothesisSet.model_validate                         │
 │        fail → REPAIR (1x): resend + validation errors → re-validate    │
 │        fail again → DEGRADE: persist raw, mark run degraded            │
 │   3. citation gate: cited ⊆ prompted_ids  for every hypothesis         │
 │        invalid → REGENERATE (1x) → re-validate → re-gate               │
 │        still invalid → flag citations, mark run degraded (never accept)│
 └───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
 store.replace_hypotheses(...) + run-level meta (timeline_summary,
 unexplained_signals, degraded, model, prompt_hash, created_at)  [one txn]
                                 ▼
 exit code: 0 success | 3 degraded | 1 failure     ── `sift show hypotheses` renders
```

### Recommended Project Structure
```
src/sift/
├── models.py                  # + HypothesisSet / Hypothesis Pydantic models (SPEC §7 names them here)
├── store.py                   # + migration_4 (hypotheses table); replace_hypotheses / query_hypotheses
├── config.py                  # + optional [triage] knobs (top_clusters default, ctx fallback, reserve_out)
├── llm/
│   ├── client.py              # chat() gains optional response_format param (llama.cpp nesting)
│   └── budget.py              # + fit_clusters()-style breadth-first over (cluster → exemplars) keeping ids
├── pipeline/
│   ├── salience.py            # NEW — deterministic rank(clusters, groups, incident_time, window)
│   └── hypothesise.py         # NEW — assemble + enforce + citation-gate + persist (typer-free, print-free)
├── prompts/
│   └── triage.md              # NEW — versioned triage instructions + schema hint (CLI-02)
└── cli.py                     # analyze: --hint/--since/--until/--top-clusters + exit-code contract;
                               # show hypotheses (un-stub cli.py:485)
```
> **Ponytail note:** Do **not** create `pipeline/retrieve.py` yet. SPEC lists it for KB retrieval, which is RAG-07 / Phase 6 (out of scope here). Phase-4 "retrieval" is just breadth-first assembly of already-clustered exemplars — it lives in `hypothesise.py`. An empty `retrieve.py` is speculative scaffolding.

### Pattern 1: Deterministic Salience (aggregate from template groups)
**What:** `salience.rank()` is a pure function producing a stable, reproducible ordering. Because the persisted `Cluster` row has **no timestamps** (migration 3 dropped `first_ts`/`last_ts` — see Pitfall 1), temporal features are aggregated from the member `template_groups` via `cluster.template_ids`.

**Per-cluster features (each normalised to [0,1] across the candidate set):**
- `severity` = `_SEVERITY_RANK[cluster.severity_max] / 5` (reuse the frozen rank dict from `cluster.py`/`dedup.py`; never lexicographic).
- `count` = `log1p(cluster.count) / log1p(max_count)` — log-damped so one giant template group doesn't swamp the rest.
- `burstiness` = `count / max(span_seconds, floor)` where `span = last_ts − first_ts` over member groups; then min-max normalised. A tight burst scores high; groups with no timestamps get a neutral default (0), never a crash.
- `novelty` = proximity of the cluster's **first** appearance to the incident time — a signal that only *emerged* near the incident is novel. `exp(-|first_ts − incident|/τ)`.
- `proximity` = proximity of the cluster's **last** appearance to the incident time. `exp(-|last_ts − incident|/τ)`.

**Score:** `w_sev·severity + w_count·count + w_burst·burstiness + w_novel·novelty + w_prox·proximity`, hand-tuned constants (starting point `0.35 / 0.20 / 0.15 / 0.10 / 0.20`, sum = 1.0). Ties broken by `cluster_id` ascending → **stable, deterministic** ordering (required for reproducible ranking tests).

**Incident time:** `--until` if supplied, else the case's latest `last_ts` (case end). `τ` (proximity decay) a module constant (e.g. the case time-span / 4, or a fixed 3600 s if the span is degenerate). `--hint` is **not** parsed for a timestamp (fragile, non-deterministic); it flows verbatim into the prompt only.

**Missing timestamps:** any cluster whose member groups all have `ts=None` (ingest kept them as `ts_confidence="missing"`) gets neutral temporal features (novelty=proximity=burstiness=0) so it still ranks on severity+count and never divides by zero.

### Pattern 2: Enforcement state machine (RAG-03) — validate → repair → degrade
```python
# pipeline/hypothesise.py (shape only; source: SPEC §5.5, ./CLAUDE.md §5)
def generate(client, prompt_messages, schema, prompted_ids) -> Outcome:
    raw = client.chat(prompt_messages, response_format=_schema_rf(schema))
    result = _validate(raw)                         # json.loads + HypothesisSet.model_validate
    if result.error:                                # RAG-03 repair, max 1
        raw = client.chat(prompt_messages + _repair_turn(raw, result.error),
                          response_format=_schema_rf(schema))
        result = _validate(raw)
    if result.error:                                # degrade — persist raw, never crash
        return Outcome(degraded=True, raw=raw, hypotheses=None)
    return _citation_gate(client, result.value, prompt_messages, schema, prompted_ids)
```
- `_schema_rf(schema)` produces the **llama.cpp** shape `{"type": "json_schema", "schema": <model_json_schema>}` — NOT OpenAI's `response_format.json_schema.schema` nesting [CITED: ./CLAUDE.md §5; llama.cpp issues #10732/#11847]. Send it unconditionally: llama-server / Lemonade-GGUF honour it, and a server that ignores it is still caught by Pydantic validation ("where available" per RAG-03).
- The repair turn appends a `user` message carrying the raw output + the Pydantic error string, instructing "return corrected JSON only." Keep it in `triage.md`-adjacent text or a short second prompt file — no inline Python prose beyond the error interpolation.
- Any transport failure (`httpx.HTTPError`) surfaces as **failure** (exit 1), distinct from a degraded-but-produced run.

### Pattern 3: Citation gate (RAG-04) — cited ⊆ prompted ⊆ store
```python
def _citation_gate(client, hset, messages, schema, prompted_ids):
    if _all_cited_within(hset, prompted_ids):
        return Outcome(hypotheses=hset)                     # success
    hset2 = _revalidate(client.chat(messages, response_format=_schema_rf(schema)))  # regenerate, max 1
    if hset2 and _all_cited_within(hset2, prompted_ids):
        return Outcome(hypotheses=hset2)
    winner = hset2 or hset
    _flag_invalid_citations(winner, prompted_ids)           # mark/strip out-of-set ids, never silently accept
    return Outcome(hypotheses=winner, degraded=True)
```
- **`prompted_ids`** is the union of every `event_id` printed into the prompt during breadth-first assembly. Since those come from `template_groups.exemplar_event_ids` (real stored events), `cited ⊆ prompted` transitively guarantees `cited ⊆ store` — the SPEC's two conditions are both satisfied by one in-memory subset check. (A defensive `store.event_ids_present()` is optional belt-and-braces; YAGNI unless a reviewer insists.)
- The schema-repair budget (Pattern 2) and the citation-regenerate budget (this pattern) are **separate**. A regeneration produces fresh output that must itself pass schema validation before re-gating.
- "Flag" = record which cited IDs were invalid on the hypothesis row (e.g. a `citations_valid` int/bool column + keep the offending ids visible) and set the run `degraded`. Never drop the hypothesis silently and never accept an invalid citation as valid.

### Pattern 4: Exit-code contract (CLI-04)
| Outcome | Exit | Meaning |
|---------|------|---------|
| Success | `0` | Schema-valid AND all citations ⊆ prompted |
| Degraded | `3` | Ran to completion but degraded: repair failed (raw persisted) OR citations still invalid after regenerate. Output persisted + flagged |
| Failure | `1` | Could not produce output: transport error, SSRF refusal, corrupt/absent case.db, unexpected exception |
| Usage | `2` | Typer/Click bad arguments (existing behaviour — do not reuse for degraded) |

Document this table in `analyze --help`, in a `docs/decisions/` ADR, and in the report metadata. `raise typer.Exit(3)` for the degraded path.

### Anti-Patterns to Avoid
- **Parsing `--hint` for a timestamp.** Non-deterministic and fragile; breaks reproducibility. Hint is prompt context only.
- **Trusting the model's citations because the JSON validated.** Schema validity ≠ citation validity — the gate is the whole point of the phase.
- **Rebuilding clusters inside the window filter.** `--since/--until` scope *which existing clusters feed salience*, not a re-cluster. Filter at cluster/group granularity.
- **Depth-first prompt truncation.** SPEC §5.5 mandates breadth-first (more clusters, shorter excerpts) so a whole failure mode is never dropped before others are shortened. `PromptBudget.fit` already encodes this.
- **Sending both `response_format.schema` and `grammar`.** Hard error in llama.cpp [CITED: ./CLAUDE.md §5].

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema for the contract | Hand-written JSON schema dict | `HypothesisSet.model_json_schema()` | Stays in lockstep with the Pydantic validator; one source of truth |
| Token counting / prompt fit | New estimator | Existing `PromptBudget` (`estimate` + breadth-first `fit`) | Already handles `/tokenize`-or-`//4` and never drops a cluster |
| Structured-output client | `instructor`/`outlines`/`openai` SDK | Extend `InferenceClient.chat` | Forbidden by CLAUDE.md; hides the llama.cpp request shape |
| Retry/backoff on transport | New retry loop | `InferenceClient._request` manual backoff | Already covers connect/timeout/5xx |
| Severity ordering | Lexicographic compare | Frozen `_SEVERITY_RANK` dict | "unknown" > "error" as strings is wrong; rank dict is the project idiom |
| Context length discovery | Hard-coded 4096/8192 | `client.props().get("n_ctx")` with config fallback | Feature-detected per LLM-04; Lemonade may lack `/props` → fall back |

**Key insight:** Phase 4 is 90% orchestration over interfaces that already exist. The genuinely new code is `salience.py` (pure arithmetic), the `hypothesise.py` state machine, the Pydantic models, one prompt file, one migration, and one additive client parameter.

## Runtime State Inventory

> Not a rename/refactor/migration-of-existing-data phase. Phase 4 is additive (new tables, new pipeline stages). The one schema change is a forward-only migration:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Migration 4 adds a `hypotheses` table + run-level `meta` keys. Existing cases at `user_version=3` migrate forward on next open (store owns the runner). No back-fill of existing rows needed. | New `_migration_4`; register in `_MIGRATIONS` |
| Live service config | None — Sift talks only to the configured localhost inference endpoint (already handled) | none |
| OS-registered state | None | none |
| Secrets/env vars | `SIFT_*` scalar env mapping may gain triage knobs (`SIFT_TRIAGE_TOP_CLUSTERS` etc.) if a `[triage]` config section is added; code-only, no secrets | Optional `_ENV_SCALARS` entries |
| Build artifacts | New package-data prompt `prompts/triage.md` must ship via the existing `importlib.resources` load path (same as `cluster_label.md`) | Ensure it's included as package data |

**Nothing found requiring a data migration of existing content** — verified: migration 4 only creates a new empty table; `analyze` writes hypotheses idempotently via `replace_hypotheses` (DELETE+insert, mirroring `replace_clusters`).

## Common Pitfalls

### Pitfall 1: The `clusters` table has no timestamps
**What goes wrong:** A naive salience implementation reads `first_ts`/`last_ts` off `Cluster` and finds they don't exist (migration 3's `clusters` schema is `cluster_id, label, signature, severity_max, count, template_ids` — SPEC §5.3's `first_ts`/`last_ts` were dropped in the implementation).
**Why it happens:** SPEC §5.3 lists cluster timestamps; the built schema aggregates them lazily instead.
**How to avoid:** Aggregate temporal features from member `template_groups` (which *do* carry `first_ts`/`last_ts`/`count`) via `cluster.template_ids` → `store.query_template_groups()`. Either (a) join in `salience.py` at rank time (simplest, no schema change), or (b) add `first_ts`/`last_ts` to `clusters` in migration 4 if you want them persisted for the report. **Recommendation:** option (a) — no schema churn, timestamps are already one query away. Note it explicitly so the planner doesn't assume SPEC §5.3's cluster columns exist.
**Warning signs:** `AttributeError` on `cluster.first_ts`; salience tests that never exercise the timestamp path.

### Pitfall 2: `chat()` does not send `response_format` today
**What goes wrong:** Calling constrained decoding fails silently — the current `chat(messages)` only sends `{"messages", "model"}`; there is no `response_format` plumbing.
**Why it happens:** Phase 3 only needed free-text labels.
**How to avoid:** Add an **optional** `response_format: dict | None = None` parameter to `chat`; when present, merge it into the payload. Keep it optional so `cluster_label.py`'s existing call is unchanged. Use the llama.cpp nesting.
**Warning signs:** Model returns prose/markdown-fenced JSON; validation failures that repair can't fix because decoding was never constrained.

### Pitfall 3: Pydantic `$defs`/`$ref` vs llama.cpp schema converter
**What goes wrong:** `HypothesisSet` nests `Hypothesis`, so `model_json_schema()` emits `$defs` + local `#/$defs/...` `$ref`. Some llama.cpp builds' JSON-schema→grammar converter mishandles indirection; external `$ref` is unsupported [CITED: ./CLAUDE.md §5].
**Why it happens:** Nested Pydantic models produce `$defs` by default.
**How to avoid:** Verify against the target build at implementation time (a `-m live` test). If it trips: flatten via `model_json_schema(ref_template=...)`/inlining, or fall back to `response_format={"type":"json_object"}` (shape-only) + rely on the Pydantic validate→repair→degrade pipeline, which is load-bearing regardless. Constrained decoding is "where available," not required.
**Warning signs:** Server 400 on the schema; grammar-compile errors in llama-server logs. (Flagged in STATE.md Blockers as a Phase-4 research item.)

### Pitfall 4: WAL not checkpointed / case dir not clean
**What goes wrong:** Leaving the store open leaves `-wal`/`-shm` files, breaking the "case dir holds only case.db" invariant.
**How to avoid:** Mirror `analyze`'s existing `finally: store.close()` and wrap all Phase-4 writes in one `store.transaction()` (as `cluster_and_label` does) so a mid-generation failure rolls back to zero hypotheses.
**Warning signs:** Stray WAL files in tests; partial hypotheses after an interrupted run.

### Pitfall 5: Untrusted server text into a rich renderable / sanitisation
**What goes wrong:** Model output (titles, narratives) is untrusted; rendering it raw (or through a rich `Progress` description) risks control-char / ANSI injection (T-03 threat class already mitigated in `show`/`analyze`).
**How to avoid:** Persist verbatim (citation fidelity) but sanitise at render (`_sanitise` in `cli.py`) for `show hypotheses`, exactly as `show clusters` does. Keep untrusted text out of any rich renderable description.

### Pitfall 6: Determinism drift from unstable ordering
**What goes wrong:** Equal-salience clusters ordered by dict/iteration order → non-reproducible prompts → non-reproducible `prompt_hash`.
**How to avoid:** Stable sort with `cluster_id` tiebreak everywhere; hash the exact assembled prompt (like `cluster_label_prompt_hash`) and store it for reproducibility (REPT-03 groundwork).

## Code Examples

### The enforced contract as Pydantic (models.py) — SPEC §5.5 verbatim
```python
# Source: SPEC.md §5.5 output contract (field names authoritative)
from typing import Literal
from pydantic import BaseModel, ConfigDict

class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")     # reject unknown keys (fail loud)
    title: str
    narrative: str
    confidence: Literal["high", "medium", "low"]
    confidence_reasoning: str
    supporting_event_ids: list[str]
    contradicting_evidence: str | None
    suggested_next_steps: list[str]

class HypothesisSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypotheses: list[Hypothesis]
    timeline_summary: str
    unexplained_signals: list[str]
```
> `sift analyze`'s prompt exposes `supporting_event_ids` candidates as `[evt:<event_id>]`; the gate checks each `∈ prompted_ids`.

### llama.cpp constrained-decoding request shape (client.py extension)
```python
# Source: ./CLAUDE.md Validation Findings §5 (llama.cpp expects schema at response_format.schema)
response_format = {"type": "json_schema", "schema": HypothesisSet.model_json_schema()}
# NOT {"type":"json_schema","json_schema":{"schema":...}} (that is OpenAI's nesting)
content = client.chat(messages, response_format=response_format)
```

### Breadth-first assembly keeps the prompted-id universe
```python
# Source: SPEC §5.5 (breadth-first), reuse PromptBudget (llm/budget.py)
prompted_ids: set[str] = set()
lines: list[str] = []
for cluster, groups in ranked:                     # salience order
    for gid in groups_exemplar_ids(cluster):        # round-robin / capped per cluster
        excerpt = exemplar_message(gid)
        lines.append(f"[evt:{gid}] {excerpt}")
        prompted_ids.add(gid)
# budget.fit(...) trims excerpts breadth-first; only ids that survive stay in prompted_ids
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Vendor SDK / framework structured output (LangChain, instructor) | httpx + Pydantic `model_json_schema()` + server-side JSON-schema decoding | Established project stance | Full control of the request shape; no network-egress surface |
| OpenAI `response_format.json_schema.schema` nesting | llama.cpp `response_format.schema` (top-level) | llama.cpp issues #10732/#11847 | Sending OpenAI's nesting silently fails against llama-server |
| `drain3` template mining | Hand-rolled masking (already shipped Phase 2) | — | Deterministic; irrelevant to Phase 4 but confirms the "boring tech" posture |

**Deprecated/outdated:** none relevant to this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Salience weights `0.35/0.20/0.15/0.10/0.20` are a sane hand-tuned start | Pattern 1 | Low — SPEC OQ4 says tune after golden suite; weights are constants, trivially adjustable |
| A2 | Incident time defaults to `--until` else case-end `last_ts`; `--hint` is not time-parsed | Pattern 1 / RAG-06 | Medium — if a reviewer wants an explicit `--at/--incident-time` flag, add it (requirements don't ask for one) |
| A3 | Aggregating temporal features from `template_groups` (no cluster-timestamp migration) is acceptable | Pitfall 1 | Low — data is one query away; option (b) adds columns if the report needs them |
| A4 | Exit codes 0/3/1 (degraded=3) — 3 is free and avoids Typer's usage-2 | Pattern 4 / CLI-04 | Low — any unused non-{0,1,2} code works; 3 is conventional. Confirm no CI wrapper assumes 2=degraded |
| A5 | Run-level fields (timeline_summary, unexplained_signals, degraded, model, prompt_hash) live in `meta` keys, per-hypothesis rows in `hypotheses` | Pattern 4 / persistence | Low — could instead be an `analysis_runs` table; meta reuses existing get/set_meta and matches SPEC §5.3's meta usage |
| A6 | `cited ⊆ prompted` is sufficient to satisfy `∈ store` (prompted ids come from stored exemplars) | Pattern 3 | Low — true by construction; optional store membership check is belt-and-braces |
| A7 | `sift show hypotheses` is in Phase-4 scope (STORE-04 partial completion) | Phase Requirements | Low — traceability + `cli.py:485` stub both point to Phase 4; not in the listed IDs but strongly implied |

**If this table is empty:** it is not — all items above are LOW/MEDIUM risk design choices the discuss/plan step may confirm. None are unverified external facts.

## Open Questions

1. **Does the target llama.cpp build accept `HypothesisSet.model_json_schema()` with `$defs`/`$ref`?**
   - What we know: llama.cpp supports JSON-schema constrained decoding; external `$ref` is unsupported; Pydantic emits local `$defs` for nested models [CITED: ./CLAUDE.md §5]. Flagged in STATE.md Blockers.
   - What's unclear: whether *this* build's converter handles local `$ref`.
   - Recommendation: add a `-m live` test at M4; if it fails, flatten the schema (`ref_template`/inlining) or degrade to `json_object` + Pydantic. Either way the validate→repair→degrade pipeline is the backstop.

2. **Should salience weights be config now or constants?**
   - Recommendation: constants now (SPEC OQ4). Graduate to a `[salience]` config section in Phase 7 when the eval harness can measure the effect. Do not build the config section speculatively.

3. **Window filter granularity (`--since/--until`).**
   - What we know: events carry `ts` (indexed); clusters/template_groups carry aggregate first/last.
   - Recommendation: filter salience *input* at cluster/group granularity (drop clusters whose `[first_ts,last_ts]` doesn't intersect the window). Per-event windowing would need a template→event join for marginal benefit; note as a documented limitation.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pydantic | Schema + validation | ✓ | 2.13.4 | — |
| httpx / respx | Client + fake server tests | ✓ | 0.28.1 / 0.23.1 | — |
| scikit-learn / numpy | (already used by clustering leg) | ✓ | 1.9.x / 2.x | — |
| Live `llama-server`/Lemonade | `-m live` constrained-decoding verification only | ✗ (not in CI) | — | Unit tests use `httpx.MockTransport`; live tests are opt-in `-m live` (already the project pattern) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** live inference server — all correctness is provable with the injected fake OpenAI server; only the real-server `$defs` behaviour (Open Question 1) needs a live check, marked `-m live`.

## Validation Architecture

> `workflow.nyquist_validation` is `true` — this section is required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + `typer.testing.CliRunner` + respx 0.23.1 (`httpx.MockTransport`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`addopts = "-m 'not perf and not live'"`) |
| Quick run command | `uv run pytest tests/test_hypothesise.py tests/test_salience.py -q` |
| Full suite command | `uv run pytest` (excludes `perf`/`live` by default) |
| Live (opt-in) | `uv run pytest -m live` (real inference server; schema `$defs` check only) |

Fake-server pattern (established in `tests/test_analyze.py`): inject an `httpx.MockTransport` through the `cli._make_http_client` seam; the autouse `_no_network` conftest fixture makes any real socket raise. All Phase-4 unit tests return canned chat JSON — no sockets.

### Phase Requirements → Test Map
| Req ID | Behaviour | Test Type | Automated Command | File Exists? |
|--------|-----------|-----------|-------------------|-------------|
| RAG-01 | Salience ranks by severity/count/burstiness/novelty/proximity; stable, deterministic order | unit | `pytest tests/test_salience.py -x` | ❌ Wave 0 |
| RAG-01 | Missing-timestamp cluster gets neutral temporal features, never divides by zero | unit | `pytest tests/test_salience.py -k missing_ts -x` | ❌ Wave 0 |
| RAG-02 | End-to-end `analyze` yields schema-valid `HypothesisSet` persisted + `show hypotheses` renders | integration | `pytest tests/test_hypothesise.py -k schema_valid -x` | ❌ Wave 0 |
| RAG-03 | Malformed JSON → 1 repair → valid; asserts exactly one repair round-trip | integration (fake server: bad-then-good) | `pytest tests/test_hypothesise.py -k repair -x` | ❌ Wave 0 |
| RAG-03 | Malformed twice → degrade: raw persisted, run marked degraded, no crash, exit 3 | integration (fake server: bad-then-bad) | `pytest tests/test_hypothesise.py -k degrade -x` | ❌ Wave 0 |
| RAG-04 | Model cites an ID not in prompt → regenerate once → valid → exit 0 | integration (fake server: badcite-then-goodcite) | `pytest tests/test_hypothesise.py -k regenerate -x` | ❌ Wave 0 |
| RAG-04 | Still-invalid citation after retry → flagged, never silently accepted, exit 3 | integration (fake server: badcite-then-badcite) | `pytest tests/test_hypothesise.py -k flagged -x` | ❌ Wave 0 |
| RAG-04 | `cited ⊆ prompted` holds on the golden path (100% validity after permitted retry) | integration | `pytest tests/test_hypothesise.py -k citation_valid -x` | ❌ Wave 0 |
| RAG-06 | `--hint` reaches the prompt verbatim; `--since/--until` filter salience input | unit/integration | `pytest tests/test_analyze.py -k hint_window -x` | ⚠️ extend existing `test_analyze.py` |
| CLI-04 | Exit codes: 0 success / 3 degraded / 1 failure (transport error, SSRF, corrupt db) | integration (CliRunner `.exit_code`) | `pytest tests/test_cli.py -k analyze_exit_codes -x` | ⚠️ extend existing `test_cli.py` |
| RAG-03 | Constrained-decoding request carries llama.cpp `response_format.schema` shape | unit (assert request body) | `pytest tests/test_llm_client.py -k response_format -x` | ⚠️ extend existing `test_llm_client.py` |
| STORE-04 | migration 4 hypotheses round-trips; `show hypotheses` sanitises untrusted fields (tampered db) | unit | `pytest tests/test_store.py -k hypotheses -x` | ⚠️ extend `test_store.py` |
| REPT-03(seed) | Determinism: identical inputs → identical `prompt_hash` and ranking | unit | `pytest tests/test_hypothesise.py -k determinism -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_salience.py tests/test_hypothesise.py -q && uv run ruff check && uv run pyright`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** full suite green + `ruff` + `pyright` clean before `/gsd-verify-work` (the milestone "done" rule).

### Wave 0 Gaps
- [ ] `tests/test_salience.py` — deterministic ranking + missing-timestamp path (RAG-01)
- [ ] `tests/test_hypothesise.py` — the full enforcement + citation-gate state machine, with a fake-server helper returning the four canned variants (good / bad-json / bad-then-good / bad-citation) (RAG-02/03/04)
- [ ] Extend `tests/test_llm_client.py` — assert `chat(response_format=…)` request body shape (llama.cpp nesting)
- [ ] Extend `tests/test_cli.py` — `analyze` exit-code matrix (0/3/1) via `CliRunner`
- [ ] Extend `tests/test_store.py` — migration 4 round-trip + sanitised `show hypotheses`
- [ ] Fixtures: a fake-chat-response builder (parameterised by scenario) — mirror the `_VECTORS`/handler pattern already in `test_analyze.py`

*Framework is already installed; no framework-install task needed.*

## Security Domain

> `security_enforcement: true`, ASVS level 1. Phase 4 introduces LLM-generated, model-controlled text into persistence and (later) reports, plus a new SQLite table.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI, no auth surface |
| V3 Session Management | no | — |
| V4 Access Control | no | Single-user local tool |
| V5 Input Validation | **yes** | Pydantic `extra="forbid"` on hypotheses; defensive JSON parsing (already the client pattern); untrusted model text treated as data; `_sanitise` at render (`show hypotheses`); parameterised SQL only (store allowlist idiom) |
| V6 Cryptography | no (hashing only) | `sha256` prompt_hash is integrity/provenance, not secrecy — no key material |
| V12/V13 (SSRF / API) | **yes (inherited)** | `_assert_local` SSRF guard already refuses non-loopback/RFC1918 endpoints unless `--i-know-what-im-doing` (LLM-02); Phase 4 opens no new network path |

### Known Threat Patterns for {local LLM triage over untrusted logs}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via log content ("ignore instructions…") in exemplars | Tampering | Triage prompt instructs the model to treat all excerpts as untrusted data, never instructions (same guard as `cluster_label.md`); citations are still gated against the prompted set regardless of model compliance |
| Hallucinated / fabricated event IDs (the core threat) | Spoofing | **Citation gate** — `cited ⊆ prompted ⊆ store`, regenerate once, flag, mark degraded; never silently accept |
| Control-char / ANSI injection from model text into terminal | Tampering | `_sanitise` whole-line at render (WR-01 idiom); persist verbatim for citation fidelity |
| Untrusted server body (NaN vectors, oversized content, non-object JSON) | DoS/Tampering | Already handled in `client.py` (`_coerce_vector`, `_MAX_CONTENT_CHARS`, `_json_object`); reuse for chat |
| SQL injection via model text into `hypotheses` | Tampering | Parameterised inserts only; column lists are module constants (store idiom) |
| SSRF to exfiltrate case data via a crafted endpoint | Info disclosure | `_assert_local` guard unchanged; no new egress path added |
| Non-finite / adversarial timestamps skewing salience | DoS | Salience clamps spans (`max(span, floor)`) and gives missing/degenerate ts neutral features; no unbounded maths |

## Sources

### Primary (HIGH confidence)
- `src/sift/llm/client.py`, `src/sift/llm/budget.py`, `src/sift/store.py`, `src/sift/pipeline/cluster.py`, `src/sift/cli.py`, `src/sift/config.py`, `src/sift/models.py` — read directly this session; frozen interfaces Phase 4 builds on
- `src/sift/prompts/cluster_label.md`, `tests/conftest.py`, `tests/test_analyze.py`, `pyproject.toml` — test/prompt patterns and dependency state
- `./SPEC.md` §5.3–5.6, §5.8, §8 (M4) — authoritative design contract
- `.planning/REQUIREMENTS.md` (RAG-01..06, CLI-04, STORE-04), `.planning/STATE.md` (decisions + Phase-4 blocker flag)

### Secondary (MEDIUM confidence)
- `./CLAUDE.md` Validation Findings §5 (llama.cpp `response_format.schema` nesting; `$defs`/grammar caveats; no vendor SDK) — project research dated 2026-07-16, cross-checked llama.cpp issues #10732/#11847
- `./.claude/CLAUDE.md` tech-stack table (Pydantic 2.13, boring-tech posture)

### Tertiary (LOW confidence)
- none — no unverified external lookups were needed; the phase is internal + already-researched stack

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all interfaces read from source and imports verified in-venv
- Architecture: HIGH — SPEC-prescribed pipeline mapped onto existing frozen contracts
- Pitfalls: HIGH — Pitfalls 1 & 2 (no cluster timestamps; `chat` lacks `response_format`) verified directly in source
- llama.cpp `$defs` behaviour: MEDIUM — documented caveat, needs a live check at M4 (Open Question 1)

**Research date:** 2026-07-17
**Valid until:** 2026-08-16 (stable stack; re-check only if the target llama.cpp/Lemonade build changes)
