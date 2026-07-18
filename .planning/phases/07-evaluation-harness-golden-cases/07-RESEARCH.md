# Phase 7: Evaluation Harness & Golden Cases - Research

**Researched:** 2026-07-18
**Domain:** Test/eval harness for a local-LLM RAG pipeline (metric computation, golden-case authoring, threshold-gated CI exit)
**Confidence:** HIGH (this phase is almost entirely codebase-internal reuse; the only external dependency is PyYAML, verified)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Author **6** synthetic-but-realistic cases under `eval/cases/<name>/`, covering the five SPEC §6 exemplars (memory-watermark cascade, SMTP relay rejection storm, thread-pool exhaustion, disk-full, dependency-service timeout) and guaranteeing the three ROADMAP-mandated shapes: designate **dependency-service-timeout** as the **mixed-timezone** case, add a distinct **quiet-cause** case (root cause is a low-severity/early signal, not the loudest error), and add a **negative (no-incident)** case (healthy logs → no confident root cause).
- **D-02:** Each case ships `input/` (sanitised artefacts), `truth.yaml`, and `README.md`. **`truth.yaml` is committed before any prompt tuning** and treated as frozen ground truth.
- **D-03:** `truth.yaml` fields: `root_cause` (descriptive string), `required_evidence` (list of **regex** patterns), `acceptable_keywords` (list for hit@k). **Retrieval hit rate** = fraction of `required_evidence` patterns present in the cluster exemplars/templates fed to the model. **Hypothesis hit@k** = any of the top-k hypotheses matches ground truth by case-insensitive **any-of** keyword match against title+narrative.
- **D-04:** The negative case supports an `expect_no_incident: true` marker, scored as a pass when no over-confident root cause is emitted.
- **D-05:** Signature `sift eval [--suite <dir>] [--json]`, default suite `eval/cases/`. Plain-text metric table by default; `--json` emits the machine-readable table. Fills the existing stub at `src/sift/cli.py:956`.
- **D-06:** **Determinism drift** = run `analyze` **N=2** times per case (config-overridable) and compare the normalised JSON via the Phase 6 `normalise_for_determinism` helper (`src/sift/render/json_out.py`) for byte-equality; drift metric = fraction of cases whose repeated runs are byte-identical.
- **D-07:** `eval/thresholds.toml` holds per-metric floors (`retrieval_hit_rate`, `hypothesis_hit_at_k`, `citation_validity_rate`, `determinism_drift`). `sift eval` exits **non-zero if any keyword metric is below its floor**; clean pass exits 0. Follows exit-code discipline of ADRs 0005/0007.
- **D-08:** `--judge` is **opt-in, off by default**. Judge prompt is a versioned template `src/sift/prompts/judge.md`. Judge scores are **advisory-only — reported alongside, never gating** the exit code.
- **D-09:** Default keyword-scored eval run is **fully offline** (network-free per EVAL-05) using the injectable fake client. The judge path is marked `@pytest.mark.live` and **excluded from the socket-blocked default suite** (same pattern as REPT-04/EVAL-05).
- **D-10:** Case-running logic lives in a new `src/sift/eval/` package invoked by the `sift eval` CLI command; it drives the existing pipeline (ingest → dedup/cluster → retrieve → hypothesise) against a **temp `case.db` per case**, with the fake OpenAI-compatible client injected for offline runs. Add **PyYAML** for `truth.yaml` parsing.

### Claude's Discretion
- Exact synthetic log content and volume per golden case, regex specificity in `truth.yaml`, table column formatting, and the default `k` for hit@k (suggest k = number of hypotheses `analyze` emits, typically 3).

### Deferred Ideas (OUT OF SCOPE)
- Real sanitised customer cases in the golden suite (added privately later, SPEC §6).
- Report redaction/sanitisation pass (REPT-05).
- Salience-weight retuning informed by the new metrics (SPEC open question #4).
- Wiring `sift eval` into an actual CI pipeline (Phase 8) — this phase only guarantees the CI-friendly non-zero exit.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | Golden suite of ≥5 synthetic-but-realistic cases, each with `input/`, `truth.yaml`, README | Golden-Case Authoring section: per-adapter log recipes, the 6-case mapping (D-01), `truth.yaml` schema + Pydantic validation model. `input/` files feed the existing adapters (genericlog/journald/dsserrors/eustack) unchanged. |
| EVAL-02 | `sift eval` reports retrieval hit rate, hypothesis hit@k, citation validity rate, determinism drift | Metric Computation Recipes section: each metric derived from already-persisted store rows + `truth.yaml`, reusing `query_clusters`/`query_template_groups`/`query_hypotheses`/`StoredHypothesis.citations_valid` and `render_json`+`normalise_for_determinism`. |
| EVAL-03 | `sift eval` exits non-zero when scores regress below `eval/thresholds.toml` | Threshold Gating section: `tomllib` load (stdlib, already used in `config.py`), per-metric floor comparison, exit-code contract mirroring ADR 0005/0007; new ADR 0010 recommended. |
| EVAL-04 | Optional LLM-as-judge grading via the same local model, alongside keyword scores | LLM-as-Judge section: reuses the existing hand-rolled `InferenceClient.chat` (no framework), `prompts/judge.md` versioned template, `@pytest.mark.live` seam, advisory-only (never gates exit). |
</phase_requirements>

## Summary

Phase 7 is a **codebase-internal reuse phase**, not a research-heavy one. Every metric it needs to compute is already a property of the persisted `case.db` after `sift analyze` runs: clusters and their exemplar messages (`query_clusters`, `query_template_groups`), hypotheses with a per-row citation verdict (`StoredHypothesis.citations_valid`), and a canonical determinism-comparable JSON serialisation (`render_json` + `normalise_for_determinism`). The harness's job is to (1) drive the existing pipeline against each golden case in a temp `case.db`, (2) read those rows back and score them against a frozen `truth.yaml`, (3) print a table, and (4) compare against `eval/thresholds.toml` floors and exit non-zero on a shortfall. There is exactly **one new third-party dependency (PyYAML)** and **zero new HTTP surface** — the LLM-as-judge reuses the sole `InferenceClient` boundary.

The single most important architectural clarity for the planner: **there are two distinct run contexts, and they measure different things.** The **offline default run** (pytest, socket-blocked, fake client per D-09) validates the *harness machinery* — metric arithmetic, `truth.yaml` parsing, threshold gating, exit codes, and the planted-regression gate — by feeding the fake client scripted good-then-bad responses. The **live run** (a human running `sift eval` against their real local model, optionally `--judge`) is where *real hypothesis quality* is measured. A fake client returns canned hypotheses, so offline `hypothesis_hit@k` is whatever the fake was scripted to return; that is correct and intentional — the offline test asserts "given this model output, the metric math and the gate behave correctly," which is exactly what SPEC §8's "exits non-zero on planted regression" acceptance requires.

**Primary recommendation:** Build `src/sift/eval/` as a thin orchestrator that reuses `cluster_and_label` + `hypothesise` (the same functions `analyze` calls), plus a set of **pure metric functions** (`store + truth → float`) that are trivially unit-testable offline with fabricated rows. Add PyYAML, load `truth.yaml` through a small Pydantic model (`safe_load`, never `load`), load `thresholds.toml` with stdlib `tomllib`, and record the exit-code contract in a new ADR 0010.

## Architectural Responsibility Map

Sift is a single-tier local CLI tool; there is no browser/frontend/API split. The "tiers" here are the internal pipeline layers this phase touches.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Golden-case artefacts (`input/`, `truth.yaml`, README) | `eval/cases/` repo data | Adapters (`src/sift/adapters/`) | Cases are static fixtures parsed by the existing adapters — zero adapter changes (SPEC §5.2 pluggability invariant). |
| Case orchestration (ingest→cluster→hypothesise per case) | `src/sift/eval/` (new) | `pipeline/` + `llm/client.py` | Reuses `cluster_and_label` + `hypothesise`; the harness owns no inference logic, only sequencing. |
| Metric computation | `src/sift/eval/` (new, pure functions) | `store.py`, `render/json_out.py` | Metrics are pure functions of persisted rows + `truth.yaml`; determinism reuses `normalise_for_determinism`. |
| Threshold gating + exit code | `src/sift/eval/` + `cli.py` `eval_()` | `eval/thresholds.toml` | Follows the CLI-04 / ADR 0005 exit-code discipline; the CLI command owns `typer.Exit`. |
| LLM-as-judge grading | `src/sift/eval/` (calls `InferenceClient.chat`) | `prompts/judge.md`, `llm/client.py` | Reuses the sole HTTP boundary; judge is advisory, never gates. |
| Metric table rendering | `src/sift/eval/` (text + `--json`) | — | Plain-text default, `--json` machine-readable (D-05). |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PyYAML (`yaml`) | 6.0.3 | Parse `truth.yaml` | The canonical Python YAML library; sanctioned by CLAUDE.md for M7 only. Already installed on the reference box (Fedora); on latest release. `[VERIFIED: pip index versions pyyaml → 6.0.3 latest+installed]` |
| tomllib (stdlib) | Python 3.12 stdlib | Parse `eval/thresholds.toml` | Zero new dependency; already used by `src/sift/config.py`. Open in binary mode (`open(path, "rb")`). `[VERIFIED: grep tomllib src/sift/config.py]` |
| Pydantic | 2.13.x (already a core dep) | Validate the `truth.yaml` shape after `safe_load` | Project convention is "Pydantic everywhere"; a `Truth` model gives typed, validated ground truth and a clear error on a malformed case file. `[VERIFIED: pyproject.toml core deps]` |

### Supporting (all already present — reused, not added)
| Module | Purpose | Reuse Point |
|--------|---------|-------------|
| `sift.pipeline.cluster.cluster_and_label` | Embed + cluster + label a case | `src/sift/pipeline/cluster.py:277`; called by `analyze` at `cli.py:778` |
| `sift.pipeline.hypothesise.hypothesise` | Salience + citation-gated hypotheses → `Outcome` | `src/sift/pipeline/hypothesise.py:285`; returns `Outcome(hypotheses, raw, degraded, failed, citations_valid, prompt_hash)` |
| `sift.pipeline.dedup.rebuild_template_groups` | Build template groups post-ingest | `src/sift/pipeline/dedup.py:92` (seen in `tests/test_analyze.py::_seed_case`) |
| `sift.pipeline.salience.rank_clusters` | Salience ranking (for "clusters fed to the model") | `src/sift/pipeline/salience.py:126` — already applied inside `hypothesise`; the harness reads the same top-N slice |
| `sift.render.json_out.render_json` / `normalise_for_determinism` | Determinism-drift comparison | `src/sift/render/json_out.py:49,85` |
| `sift.store.CaseStore` (`query_clusters`, `query_template_groups`, `query_hypotheses`, `query_events`, `get_meta`) | Read persisted rows back for metrics | `src/sift/store.py:924,693,1002,563,1030` |
| `sift.llm.client.InferenceClient.chat` | LLM-as-judge call | The sole HTTP boundary (SPEC §5.6) |
| `cli._make_http_client` seam | Inject a fake `httpx.MockTransport` in offline tests | `src/sift/cli.py:972`; monkeypatched in `tests/test_analyze.py::_patch_http` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reusing `cluster_and_label` + `hypothesise` directly | Shell out to `sift analyze` via subprocess / `CliRunner` | Subprocess is a heavier, slower seam and re-parses stdout; calling the pipeline functions directly is what `test_analyze.py` already does and keeps the harness in-process and typed. Use `CliRunner`-style invocation only in the harness's own tests. |
| PyYAML for `truth.yaml` | TOML (`tomllib`) for ground truth too | CLAUDE.md sanctions PyYAML *specifically* for `truth.yaml` (human-authoring ergonomics for multi-line `root_cause` + regex lists). Locked by D-10 — do not re-open. `thresholds.toml` stays TOML. |
| A `Truth` Pydantic model | Raw dict access after `safe_load` | Pydantic gives a typed, validated failure at load rather than a `KeyError` mid-metric; consistent with the project's Pydantic-everywhere convention. Cheap and boring. |

**Installation:**
```bash
uv add pyyaml            # runtime dep, guard behind M7 use only
# tomllib + Pydantic already present; no other additions
```

**Version verification:** `pip index versions pyyaml` → `6.0.3` is both LATEST and INSTALLED on the box (Python 3.12). `import yaml` currently raises `ModuleNotFoundError` in the project venv — **PyYAML is declared nowhere in `pyproject.toml` yet**, so an explicit `uv add pyyaml` install task is the first work item. `[VERIFIED: uv run python -c "import yaml" → ModuleNotFoundError; pip index versions pyyaml]`

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| pyyaml | PyPI | Latest release 2025-09-25 (6.0.3); library itself ~15 yrs | seam reported `unknown-downloads` (no data), but PyYAML is among the most-downloaded PyPI packages (tens of millions/week) | https://pyyaml.org/ (github.com/yaml/pyyaml) | SUS (reason: `unknown-downloads` only) | **Approved** — the SUS verdict is purely a missing-download-count signal from the seam, not a risk signal. `import yaml` is the canonical, ubiquitous YAML parser, already installed on the reference box, and explicitly sanctioned by CLAUDE.md for M7. No postinstall script (`postinstall: null`). |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** pyyaml — flagged only on `unknown-downloads`; this is a false-positive of the download-signal probe, not a legitimacy concern. The planner does **not** need a `checkpoint:human-verify` task: the package is CLAUDE.md-sanctioned, on its latest release, and already resident in the environment. If the planner prefers belt-and-braces, one line in the install task can pin `pyyaml==6.0.3`.

## Architecture Patterns

### System Architecture Diagram

```
                    eval/cases/<name>/                      eval/thresholds.toml
                    ├── input/*            truth.yaml        (per-metric floors)
                    │   (log artefacts)    (frozen GT)              │
                    │        │                  │                   │
                    ▼        ▼                  │                   │
  sift eval ──▶ for each case:                  │                   │
   (cli.py:956)   │                             │                   │
                  ▼                             │                   │
        ┌──────────────────────────┐           │                   │
        │ temp case.db (per case)  │           │                   │
        │  1. ingest input/  ──────┼──▶ adapters (unchanged)       │
        │  2. rebuild_template_groups                              │
        │  3. cluster_and_label(store, client) ◀── injected client │
        │  4. hypothesise(store, client) → Outcome                 │
        └───────────┬──────────────┘   (fake offline / real live) │
                    │ persisted rows                               │
                    ▼                                              │
        ┌──────────────────────────────────────────────┐          │
        │ pure metric functions (store + truth → float) │          │
        │  • retrieval_hit_rate  (required_evidence vs   │          │
        │      top-N cluster exemplars)                  │          │
        │  • hypothesis_hit@k    (acceptable_keywords vs │          │
        │      hypotheses title+narrative)               │          │
        │  • citation_validity_rate (StoredHypothesis    │          │
        │      .citations_valid)                         │          │
        │  • determinism_drift   (2× render_json +       │          │
        │      normalise_for_determinism byte-equality)  │          │
        │  • [optional] judge score (InferenceClient.chat│          │
        │      + prompts/judge.md) — advisory only       │          │
        └───────────┬───────────────────────────────────┘          │
                    │ aggregated metric table                       │
                    ▼                                               ▼
        print table (text default / --json)  ──▶  gate: any floor breached? ──▶ exit 1
                                                   else exit 0 (judge never gates)
```

File-to-implementation mapping is in the Component Responsibilities of the Standard Stack tables above; the diagram shows data flow only.

### Recommended Project Structure
```
src/sift/eval/
├── __init__.py
├── truth.py         # Truth Pydantic model + load_truth(path) via yaml.safe_load
├── runner.py        # run_case(case_dir, client, *, repeats) -> temp case.db(s) driven through the pipeline
├── metrics.py       # pure functions: retrieval_hit_rate, hypothesis_hit_at_k,
│                    #   citation_validity_rate, determinism_drift; + CaseResult/SuiteResult dataclasses
├── judge.py         # optional LLM-as-judge (InferenceClient.chat + prompts/judge.md); advisory
├── thresholds.py    # load_thresholds(path) via tomllib; gate(results, thresholds) -> pass/fail
└── report.py        # render the metric table (text) + a --json shape
src/sift/prompts/
└── judge.md         # NEW versioned judge prompt template (CLI-02: no Python change to tune)
eval/
├── cases/
│   ├── memory-watermark-cascade/   { input/, truth.yaml, README.md }
│   ├── smtp-rejection-storm/       { … }
│   ├── thread-pool-exhaustion/     { … }
│   ├── disk-full/                  { … }
│   ├── dependency-timeout-mixed-tz/{ … }   # doubles as the mixed-timezone shape (D-01)
│   ├── quiet-cause/                { … }   # root cause is a low-severity early signal
│   └── negative-no-incident/       { … }   # healthy logs; truth.yaml expect_no_incident: true
└── thresholds.toml
```
Note: D-01 mandates 6 *incident* cases folding in the three special shapes. The negative case is the distinct 6th; the tree above shows 7 dirs only if quiet-cause and negative are both counted separately from the five exemplars — reconcile to exactly the 6 D-01 requires (dependency-timeout = mixed-tz, then +quiet-cause +negative gives 6 when one exemplar is reused for a special shape). **Planner: confirm the final case count is 6 per D-01, not 7.**

### Pattern 1: Pure metric function (store + truth → float)
**What:** Each metric is a pure function taking persisted rows (or a `CaseStore`) and a `Truth`, returning a float in [0,1]. No I/O, no client.
**When to use:** All four keyword metrics. Keeps them unit-testable offline with fabricated rows (no pipeline run needed).
**Example:**
```python
# src/sift/eval/metrics.py  (illustrative; mirrors D-03 semantics)
import re

def retrieval_hit_rate(exemplar_texts: list[str], required_evidence: list[str]) -> float:
    """Fraction of required_evidence regexes matching the clusters fed to the model."""
    if not required_evidence:
        return 1.0
    haystack = "\n".join(exemplar_texts)
    hits = sum(1 for pat in required_evidence if re.search(pat, haystack, re.IGNORECASE))
    return hits / len(required_evidence)

def hypothesis_hit_at_k(hyps, acceptable_keywords: list[str], k: int) -> float:
    """1.0 if ANY of the top-k hypotheses matches ANY acceptable keyword (case-insensitive)."""
    kws = [w.lower() for w in acceptable_keywords]
    for h in hyps[:k]:
        blob = f"{h.title}\n{h.narrative}".lower()
        if any(w in blob for w in kws):
            return 1.0
    return 0.0
```

### Pattern 2: Reuse the analyze orchestration, not a reimplementation
**What:** `run_case` sequences the exact calls `sift analyze` makes, against a temp `case.db`.
**When to use:** Driving each golden case through the pipeline.
**Example (sequence, from `cli.py:722–823` and `test_analyze.py::_seed_case`):**
```python
store = CaseStore(temp_db_path)
with store.transaction():
    store.insert_events(events_from_ingesting(case_dir / "input"))
dedup.rebuild_template_groups(store)
cluster_and_label(store, client, config.clustering, label=True)
outcome = hypothesise(store, client, top_clusters=k, incident_time=None, ...)
# metrics read store.query_clusters(), store.query_hypotheses(), etc.
```
Reuse the *ingest* leg from `cli._ingest` (`cli.py:150`) rather than re-parsing directories by hand — it already dispatches adapters and records coverage.

### Pattern 3: Determinism drift via two runs + the M6 seam
**What:** Run the pipeline twice from the same ingested state, `render_json` each, `normalise_for_determinism`, compare bytes.
**Example:**
```python
a = normalise_for_determinism(json.loads(render_json(store_run1)))
b = normalise_for_determinism(json.loads(render_json(store_run2)))
identical = (json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))
```
Run each of N=2 against a **fresh copy of the post-ingest `case.db`** (or re-run `cluster_and_label`+`hypothesise` on the same db — `replace_hypotheses` overwrites). Copying the ingested db avoids state-carryover ambiguity. Planner discretion (D-06 is config-overridable N).

### Anti-Patterns to Avoid
- **Reimplementing the citation check in the harness.** `hypothesise` already sets `StoredHypothesis.citations_valid` per row (`store.py:441`, `hypothesise.py:464`). Read it; do not re-derive `cited ⊆ store`.
- **Reimplementing determinism normalisation.** `normalise_for_determinism` is the single source of the excluded-field set (ADR 0008). Reuse it; never hand-roll a second exclusion list.
- **`yaml.load` / `yaml.full_load`.** Use `yaml.safe_load` only — arbitrary-object construction is a code-execution vector, and truth files are trusted-but-verify fixtures.
- **A fake client whose output makes offline hit@k "pass" trivially and hides a broken metric.** Offline tests must include a *planted-regression* fixture (fake returns keyword-missing hypotheses) that drives the gate to a non-zero exit — that is the SPEC §8 acceptance, not an optional nicety.
- **Letting the judge influence the exit code.** D-08: judge is advisory, reported alongside, never gating.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Citation validity per hypothesis | A re-scan of `supporting_event_ids` against the store | `StoredHypothesis.citations_valid` | Already computed and persisted by the citation gate (the load-bearing anti-hallucination mechanism). Re-deriving risks divergence from the gate's own verdict. |
| Determinism-comparable JSON | A custom field-stripper | `render_json` + `normalise_for_determinism` | ADR 0008 fixes the excluded-field set in one place; a second copy will drift. |
| Cluster exemplar text ("fed to the model") | Re-reading events and guessing which were prompted | `query_clusters()[:top_clusters]` → `query_template_groups()` exemplar messages (the same slice `hypothesise`/`rank_clusters` use) | The prompted set is a deterministic function of salience ranking already implemented. |
| YAML parsing | A regex/line parser for `truth.yaml` | `yaml.safe_load` + Pydantic `Truth` model | Boring, correct, validated. |
| TOML parsing | A hand parser for thresholds | stdlib `tomllib` (binary mode) | Already the project's config format; zero new dep. |
| Offline fake inference server | A new fake server | `httpx.MockTransport` via `cli._make_http_client` monkeypatch | The exact EVAL-05 seam `test_analyze.py` already uses; keeps the zero-network rule enforceable. |

**Key insight:** This phase adds *measurement*, not *pipeline behaviour*. Almost every number it reports already exists as a persisted row or a reusable pure helper; the harness's real new code is (a) `truth.yaml`/`thresholds.toml` loading, (b) the four small metric functions, (c) the gate + exit wiring, and (d) the golden fixtures themselves.

## Golden-Case Authoring (EVAL-01)

**`truth.yaml` schema (D-03/D-04) — validate with a Pydantic `Truth` model:**
```yaml
# eval/cases/memory-watermark-cascade/truth.yaml
root_cause: >
  A memory high-watermark breach triggered progressive cache eviction that
  cascaded into OOM kills of the worker pool.
required_evidence:          # regex, matched case-insensitively against clusters fed to the model
  - "watermark.*(exceed|breach)"
  - "OOM|out of memory|oom-kill"
  - "evict"
acceptable_keywords:        # any-of, case-insensitive, vs hypothesis title+narrative
  - memory
  - watermark
  - OOM
  - cascade
expect_no_incident: false   # true only for negative-no-incident/
```

**Per-adapter authoring recipes (Claude's discretion on exact content/volume):**
- **genericlog** (simplest — use for most cases): ISO 8601-timestamped lines, tens-to-low-hundreds of lines. INGST-04/11 handle timestamp parsing and per-node tz. Ideal for memory-watermark, SMTP-rejection, thread-pool, disk-full.
- **mixed-timezone case (dependency-timeout, D-01):** author `input/` files from ≥2 nodes with different UTC offsets (or a per-node tz override) so INGST-11's UTC normalisation + `ts_confidence` is exercised; the "hit" depends on the timeline not silently inverting causality. genericlog with explicit `+HH:MM` offsets, or `journald` (`journalctl -o json` export) per node, both work.
- **quiet-cause case:** the loudest cluster (high count/severity) must be a *symptom*; the true root cause is a single low-severity, early-timestamp event. `required_evidence` targets the quiet signal; `acceptable_keywords` name the true cause. This stresses salience ranking, not just parsing.
- **negative-no-incident case:** healthy/steady-state logs (info-level, no error bursts). `expect_no_incident: true`. Scored a pass when the run emits no over-confident root cause — i.e. zero hypotheses, or hypotheses all at `confidence: low`, or a degraded/empty triage. **Planner: pin the exact "no confident hypothesis" predicate** (recommend: pass if `len(hypotheses)==0` OR every hypothesis `confidence=="low"`).
- **dsserrors / eustack cases (optional realism):** only if a case genuinely needs MicroStrategy-shaped evidence (SIDs, 0x codes, MCM blocks) or thread-dump shape. These adapters already parse fixtures under `tests/fixtures/`; reuse their sample shapes.

**Sanitisation:** synthetic logs are authored clean (no real hostnames/IPs/SIDs). REPT-05 (redaction) is deferred, so hand-author sanitised content directly.

**README.md per case:** one paragraph — the scenario, the planted root cause, and why the special shape (if any) matters. Frozen alongside `truth.yaml` before any prompt tuning (D-02).

## Metric Computation Recipes (EVAL-02) — with the determinism-direction gotcha

| Metric | Recipe | Data source |
|--------|--------|-------------|
| **retrieval_hit_rate** | fraction of `required_evidence` regexes matching the concatenated exemplar text of the top-N ranked clusters fed to the model | `query_clusters()[:top_clusters]` → their `template_ids` → `query_template_groups()` exemplar event messages (`_gather_exemplar_messages` idiom, `hypothesise.py:146`) |
| **hypothesis_hit@k** | 1.0 if any of top-k hypotheses' `title+narrative` contains any `acceptable_keywords` (case-insensitive any-of) | `query_hypotheses()` (`StoredHypothesis.title/narrative`) |
| **citation_validity_rate** | mean of `citations_valid` across hypotheses (or fraction of cited ids present in store) | `StoredHypothesis.citations_valid` (`store.py:441`) — already the gate's verdict |
| **determinism_drift** | fraction of cases whose N=2 repeated runs are byte-identical after `normalise_for_determinism` (D-06) | `render_json` + `normalise_for_determinism` |

**⚠ Direction gotcha the planner MUST resolve (STATE.md already flags this as a Phase-7 research risk):** the four floors in `thresholds.toml` are **lower bounds** ("exit non-zero if any metric is *below* its floor", D-07). Three metrics are naturally "higher is better" (hit rate, hit@k, citation validity). **"drift" is naturally "lower is better"** — a name/direction mismatch. Recommendation: **express the fourth metric as `determinism_stability` = fraction of cases that ARE byte-identical (higher is better), and gate it with a floor (e.g. 1.0)**, so all four metrics share one comparison direction (`value >= floor`). If the SPEC wording "determinism drift" must be preserved verbatim in the report, compute and *display* drift = `1 - stability` but gate on stability internally. Document the choice in ADR 0010. This removes the only genuinely ambiguous piece of the metric design.

**Negative-case scoring:** for a case with `expect_no_incident: true`, retrieval_hit_rate / hit@k are inverted-or-skipped — a "hit" would be a *false positive*. Recommend: the case passes when the no-confident-hypothesis predicate holds, and its contribution to the suite aggregates is "pass" rather than a keyword-match rate. Planner: decide whether the negative case feeds the same floors or a dedicated `negative_case_pass` boolean.

## Threshold Gating & CI Exit (EVAL-03)

- Load `eval/thresholds.toml` with stdlib `tomllib` (`with open(path, "rb") as f: tomllib.load(f)`), exactly as `config.py` already does.
- Shape:
```toml
# eval/thresholds.toml
retrieval_hit_rate      = 0.80
hypothesis_hit_at_k     = 0.60
citation_validity_rate  = 1.00   # the anti-hallucination invariant — expect 100%
determinism_stability   = 1.00   # see the direction gotcha above
```
- Gate: `sift eval` exits **1** if any keyword metric aggregate is below its floor; **0** on a clean pass. Judge scores never enter the gate (D-08).
- **Exit-code contract (recommend a NEW ADR 0010 — note ADR 0009 is already taken by the KB-index decision, per STATE.md):**

| Code | Meaning |
|------|---------|
| 0 | All keyword metrics meet their floors |
| 1 | A metric regressed below its floor (CI-friendly fail) — the primary SPEC §8 acceptance; also a harness/run failure (a case that could not complete) |
| 2 | Typer/Click usage error (bad `--suite` path, unknown flag) |

Keep it to `{0,1,2}` mirroring the *spirit* of ADR 0005/0007 without inventing a "degraded" tier the SPEC doesn't ask for. If the planner wants to distinguish "regression" from "harness could not run a case", a distinct code (e.g. 4) is defensible — but SPEC only requires *non-zero on regression*, so the minimal `{0,1,2}` is the lazy-correct default.

## LLM-as-Judge (EVAL-04)

- `--judge` opt-in, off by default (D-08). Uses the **existing** `InferenceClient.chat` against the same local model — **no framework** (LangChain/instructor are hard-forbidden by CLAUDE.md).
- Prompt is a **versioned template** `src/sift/prompts/judge.md` (CLI-02: tuning the judge must not touch Python). Load it the way `hypothesise._load_triage_template` does — `importlib.resources.files(_PROMPT_PACKAGE)` (`hypothesise.py:107`).
- The judge grades hypothesis-vs-`root_cause` match; parse leniently (the project's established "never crash on model output" idiom — degrade to no-judge-score rather than raise).
- Judge scores are **reported alongside** keyword scores in the table, **never gate** the exit code.
- **Testing:** the judge path needs the real model, so its test is `@pytest.mark.live` and excluded from the default socket-blocked suite (D-09). This is the exact pattern `tests/test_render_pdf.py` uses for the WeasyPrint live test (`@pytest.mark.live`, `pyproject.toml` `addopts = "-m 'not perf and not live'"`).

## Runtime State Inventory

Not applicable — Phase 7 is greenfield additive work (a new `src/sift/eval/` package, new `eval/` fixtures, one new prompt file, one new dependency). It renames/refactors nothing and stores no new runtime state beyond ephemeral temp `case.db` files created and discarded per eval run. **None — verified by inspection of the phase scope (new package + fixtures only; no changes to stored schema, service config, OS registrations, secrets, or build artefacts).**

## Common Pitfalls

### Pitfall 1: Offline eval "measures quality" (it does not)
**What goes wrong:** Treating the fake-client offline run's `hit@k` as a real quality number, or writing a threshold that only the fake client can satisfy.
**Why it happens:** The fake returns canned hypotheses; the metric reflects the fixture, not the model.
**How to avoid:** Frame offline tests as *machinery* tests. The quality-bearing assertion offline is the **planted-regression gate** (swap the fake's good response for a keyword-missing one → assert exit code 1). Real quality is a *live* concern.
**Warning signs:** A threshold like `hypothesis_hit_at_k = 1.0` that passes offline only because the fake was scripted to hit.

### Pitfall 2: determinism_drift direction inversion
**What goes wrong:** A floor-based gate on a "lower is better" drift metric silently inverts — a perfectly deterministic run (drift 0) fails a `>= floor` check, or a drifting run passes.
**Why it happens:** Three metrics are "higher is better"; drift is not.
**How to avoid:** Express as `determinism_stability` (higher is better) internally; display drift if the SPEC wording is wanted. (See Metric Recipes gotcha.)
**Warning signs:** The determinism threshold is the only one whose comparison operator differs.

### Pitfall 3: Live-model determinism is not guaranteed
**What goes wrong:** The determinism metric fails on a *live* run even though the harness is correct, because the local server isn't seeded / runs multi-slot (REPT-03 / ADR 0008 documented caveat).
**Why it happens:** llama-server determinism depends on server config.
**How to avoid:** Offline (fake client) the two runs are byte-identical by construction — that validates the *comparison*. On live runs, document that determinism_stability reflects server config, and that `sift doctor` already warns on determinism-breaking configs (LLM-03). Don't let a live non-determinism failure be read as a harness bug.
**Warning signs:** Offline determinism passes, live fails intermittently.

### Pitfall 4: `yaml.load` instead of `safe_load`
**What goes wrong:** Arbitrary Python object construction from a YAML file.
**How to avoid:** `yaml.safe_load` only; validate the result through the `Truth` Pydantic model.

### Pitfall 5: Negative case scored as a keyword miss
**What goes wrong:** The no-incident case reports `hit@k = 0` and drags the suite aggregate below the floor, failing CI on correct behaviour.
**How to avoid:** Score `expect_no_incident: true` cases by the no-confident-hypothesis predicate (a pass), not by keyword-match rate; keep them out of the hit@k aggregate or map their pass to 1.0.

### Pitfall 6: PyYAML not actually installed
**What goes wrong:** `import yaml` raises `ModuleNotFoundError` — it is declared nowhere in `pyproject.toml` today.
**How to avoid:** First task is `uv add pyyaml`; confirm with `uv run python -c "import yaml"` (verified missing this session).

## Code Examples

### Loading and validating `truth.yaml`
```python
# src/sift/eval/truth.py
from pathlib import Path
import yaml
from pydantic import BaseModel

class Truth(BaseModel):
    root_cause: str
    required_evidence: list[str] = []
    acceptable_keywords: list[str] = []
    expect_no_incident: bool = False

def load_truth(path: Path) -> Truth:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))  # NEVER yaml.load
    return Truth.model_validate(data or {})
```

### Loading thresholds (stdlib, mirrors config.py)
```python
# src/sift/eval/thresholds.py
import tomllib
from pathlib import Path

def load_thresholds(path: Path) -> dict[str, float]:
    with path.open("rb") as f:            # tomllib requires binary mode
        return {k: float(v) for k, v in tomllib.load(f).items()}
```

### Offline test seam (planted regression → non-zero exit)
```python
# tests/test_eval.py  (pattern from tests/test_analyze.py::_patch_http)
def _patch_http(monkeypatch, handler):
    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler),
                            timeout=httpx.Timeout(timeout))
    monkeypatch.setattr("sift.cli._make_http_client", _factory)
# A "good" handler returns keyword-hitting hypotheses (suite passes, exit 0);
# a "regressed" handler returns keyword-missing hypotheses (a floor breaches, exit 1).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LLM-eval frameworks (deepeval, ragas, promptfoo) | A ~few-hundred-line in-repo harness reusing persisted pipeline outputs | This project's design (SPEC §6) | Frameworks bring network egress, heavy deps, and abstraction over an API Sift must control — all forbidden. The metrics here are simple regex/keyword/byte-equality checks; a framework is pure overhead. |
| `yaml.load` | `yaml.safe_load` (default-safe since PyYAML 5.1, 2019) | PyYAML 5.1+ | Use `safe_load`; `load` without a Loader now warns/errors. |
| Determinism via ad-hoc field stripping | Single `normalise_for_determinism` seam (ADR 0008) | Phase 6 | One exclusion list; the eval harness reuses it verbatim. |

**Deprecated/outdated:**
- Any LLM-eval framework for this phase — architecturally excluded (CLAUDE.md, locked project decision).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The "clusters fed to the model" for retrieval_hit_rate = the top-`top_clusters` salience-ranked clusters' exemplar messages (the same slice `hypothesise` prompts with) | Metric Recipes | If the intended denominator is *all* clusters or a different slice, retrieval_hit_rate shifts. Low risk — D-03 says "clusters fed to the model", and `hypothesise`/`rank_clusters` define that slice. Planner should confirm against the exact prompt-assembly in `hypothesise._assemble`. |
| A2 | The no-incident pass predicate = zero hypotheses OR all `confidence=="low"` | Golden-Case Authoring / Pitfall 5 | If the intended predicate differs (e.g. also allow "degraded"), the negative case may mis-score. Planner must pin the exact predicate. |
| A3 | Recommending `determinism_stability` (higher-better) over literal `determinism_drift` for the gate | Metric Recipes gotcha | Cosmetic if the planner prefers to keep the "drift" name and invert the comparison; the underlying computation is identical. |
| A4 | New ADR number is 0010 (0009 taken by KB-index per STATE.md) | Threshold Gating | Trivial — verify the next free ADR number when writing it. |
| A5 | Suite is exactly 6 cases per D-01 (dependency-timeout doubles as mixed-tz) | Recommended Structure | If the planner reads D-01 as 5 exemplars + quiet + negative = 7, the count differs. D-01 text folds mixed-tz into an exemplar → 6. Planner to confirm. |

**These are the only items needing confirmation.** Everything else is verified against the codebase or SPEC.

## Open Questions

1. **Determinism metric name/direction in `thresholds.toml` and the printed table.**
   - What we know: floors are lower bounds (D-07); drift is "lower is better".
   - What's unclear: whether SPEC's literal "determinism drift" wording must appear in the table.
   - Recommendation: gate on `determinism_stability` (floor 1.0); display drift = `1 - stability` if desired. Record in ADR 0010.

2. **Does the negative case feed the same aggregate floors, or a separate boolean?**
   - What we know: a keyword "hit" on a no-incident case is a false positive.
   - Recommendation: score negative cases by the no-confident-hypothesis predicate as a pass; keep them out of hit@k averaging.

3. **N=2 determinism: two runs on the same db, or two fresh copies of the post-ingest db?**
   - Recommendation: copy the post-ingest `case.db` twice to avoid overwrite-carryover ambiguity; N is config-overridable per D-06.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PyYAML (`yaml`) | `truth.yaml` parsing (EVAL-01/02) | ✗ in venv (installed system-wide but not a project dep) | 6.0.3 available | None — must `uv add pyyaml` (blocking, trivial) |
| tomllib | `thresholds.toml` (EVAL-03) | ✓ (stdlib) | 3.12 | — |
| Pydantic | `Truth` validation | ✓ (core dep) | 2.13.x | — |
| Existing pipeline (`cluster_and_label`, `hypothesise`, `render_json`, `normalise_for_determinism`, `CaseStore`, `InferenceClient`) | Everything | ✓ (Phases 1–6 complete) | — | — |
| Local llama-server / Lemonade | Live eval + `--judge` only | ✓ on the reference box (Lemonade 13305) | — | Offline default run needs no server (fake client) |

**Missing dependencies with no fallback:** PyYAML — blocking but a one-line `uv add pyyaml` (first work item).
**Missing dependencies with fallback:** none.

## Validation Architecture

> nyquist_validation is enabled (config.json workflow.nyquist_validation = true).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (`uv run pytest`) `[VERIFIED: pyproject.toml, prior VALIDATION reconciliation]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `addopts = "-m 'not perf and not live'"`; markers include `live` |
| Quick run command | `uv run pytest tests/test_eval.py -x` |
| Full suite command | `uv run pytest` (socket-blocked default; excludes `perf` + `live`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EVAL-01 | Suite loads; each case has `input/`, `truth.yaml` (schema-valid), README | unit | `pytest tests/test_eval.py -k truth_schema -x` | ❌ Wave 0 |
| EVAL-02 | Each metric computes correctly on fabricated rows (pure functions) | unit | `pytest tests/test_eval.py -k metrics -x` | ❌ Wave 0 |
| EVAL-02 | Full run over a tiny case with fake client produces a metric table | integration (offline) | `pytest tests/test_eval.py -k run_suite -x` | ❌ Wave 0 |
| EVAL-03 | Clean suite → exit 0; planted regression (keyword-missing fake) → exit 1 | integration (offline) | `pytest tests/test_eval.py -k threshold_gate -x` | ❌ Wave 0 |
| EVAL-03 | `--json` emits machine-readable table | unit | `pytest tests/test_eval.py -k json_output -x` | ❌ Wave 0 |
| EVAL-04 | `--judge` calls the model and reports alongside; never gates | live | `pytest tests/test_eval.py -m live -k judge` | ❌ Wave 0 |
| EVAL-05 (regression) | Offline suite opens zero sockets | integration | `uv run pytest` (autouse `_no_network` guard) | ✓ (conftest) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_eval.py -x` + `ruff check` + `pyright` (project TDD gate).
- **Per wave merge:** `uv run pytest` (full socket-blocked suite — also the cross-phase regression gate).
- **Phase gate:** Full suite green + `ruff`/`pyright` clean before `/gsd-verify-work`; the `-m live` judge test and any real-model `sift eval` run are manual UAT (like REPT-04's live PDF check).

### Wave 0 Gaps
- [ ] `tests/test_eval.py` — covers EVAL-01/02/03 (+ a `live`-marked EVAL-04 judge test)
- [ ] Fake-client handler + planted-regression handler fixtures (reuse `test_analyze.py::_handler`/`_patch_http` shape)
- [ ] At least one tiny in-repo golden case usable offline for the run/gate integration tests (can be a minimal genericlog case)
- [ ] Framework install: `uv add pyyaml` (blocking — `import yaml` currently fails)

## Security Domain

> security_enforcement = true, ASVS level 1, block_on = high.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI, no auth surface |
| V3 Session Management | no | Stateless CLI |
| V4 Access Control | no | Single-user local tool |
| V5 Input Validation | **yes** | `truth.yaml` via `yaml.safe_load` + Pydantic `Truth` model; regex patterns from `required_evidence` compiled defensively; `thresholds.toml` via `tomllib` |
| V6 Cryptography | no | None introduced (determinism uses sha256 hashing already in `hypothesise`) |
| V12 Files & Resources | **yes** | Case `input/` dirs walked via the existing adapters' trust boundary; temp `case.db` under a temp dir; no symlink-following beyond what `retrieve.index_kb` already guards (IN-03) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| YAML deserialisation RCE (`yaml.load`) | Tampering / Elevation | `yaml.safe_load` **only**; validate through Pydantic `Truth` |
| Malicious regex in `required_evidence` (ReDoS) | Denial of Service | Golden-case `truth.yaml` files are in-repo, authored and reviewed (trusted); still, keep regex matching bounded (small exemplar haystack). Note: fixtures are committed, not user-supplied at runtime, so ReDoS risk is low but worth a bounded-input note. |
| Network egress during eval | Info disclosure | Offline default run is socket-blocked (autouse `_no_network`, EVAL-05); live/judge runs hit only the configured loopback endpoint via the existing SSRF-guarded `InferenceClient` (LLM-02). No new HTTP path. |
| Untrusted log content in `input/` reaching the model/prompt | Tampering | Reuses the existing sanitisation seams (`render/_util.sanitise`, prompt assembly) — the harness introduces no new prompt-injection surface beyond what `analyze` already handles; golden inputs are synthetic and trusted. |
| Temp `case.db` leaking outside the sandbox | Info disclosure | Create per-case temp db under `tempfile`/tmp dir; delete after; never under the user's real data dir (mirror the conftest XDG isolation). |

No `high`-severity threats introduced; the phase adds one deserialisation surface (`truth.yaml`) fully mitigated by `safe_load` + Pydantic.

## Sources

### Primary (HIGH confidence)
- Codebase (grep/read this session): `src/sift/cli.py` (analyze flow 623–858, eval stub 956, `_make_http_client` 972), `src/sift/pipeline/hypothesise.py` (Outcome 89, hypothesise 285, citation gate), `src/sift/pipeline/cluster.py:277`, `src/sift/pipeline/salience.py:126`, `src/sift/pipeline/dedup.py:92`, `src/sift/pipeline/retrieve.py` (index_kb/retrieve_kb), `src/sift/render/json_out.py` (render_json 49, normalise_for_determinism 85), `src/sift/store.py` (StoredHypothesis 430, query_* methods) — the reuse surface.
- `tests/test_analyze.py` (fake `httpx.MockTransport` handler + `_patch_http` + `_seed_case`), `tests/conftest.py` (`_no_network`, XDG isolation), `pyproject.toml` (`live`/`perf` markers, addopts) — the test seam and offline pattern.
- `SPEC.md` §6 (Evaluation Harness), §5.5, §8 (M7 acceptance) — authoritative metric definitions and acceptance.
- `docs/decisions/0005-analyze-exit-codes.md`, `0007-report-exit-codes.md`, `0008-report-determinism-scope.md` — exit-code and determinism precedent.
- `.planning/phases/07-.../07-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md` (Phase-7 drift-metric research flag; ADR 0009 = KB index).

### Secondary (MEDIUM confidence)
- `pip index versions pyyaml` → 6.0.3 latest/installed; `uv run python -c "import yaml"` → ModuleNotFoundError (PyYAML not a project dep yet).
- `gsd-tools query package-legitimacy check --ecosystem pypi pyyaml` → SUS on `unknown-downloads` only (false-positive of the download probe).

### Tertiary (LOW confidence)
- None — no web research was required; the phase is codebase-internal.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — PyYAML verified on registry + local; everything else is existing verified code.
- Architecture: HIGH — the reuse points were read directly (`hypothesise`, `render_json`, `StoredHypothesis.citations_valid`, the MockTransport seam).
- Pitfalls: HIGH for the determinism-direction and PyYAML-missing pitfalls (both verified); MEDIUM for live-determinism (depends on the user's server config).

**Research date:** 2026-07-18
**Valid until:** ~2026-08-17 (30 days — stable, codebase-internal; only PyYAML version could move, and only forward).
