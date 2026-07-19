# Phase 11: MCM Facts into `sift analyze` + Golden Eval Case - Research

**Researched:** 2026-07-19
**Domain:** Additive LLM-integration over an existing deterministic analyser (in-repo Python 3.12 / Typer / Pydantic / httpx)
**Confidence:** HIGH — every finding is grounded in the actual current source, not web patterns.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-17: Automatic + additive — no CLI flag.** The MCM fact block is injected into the triage prompt whenever the case contains dsserrors MCM denial episodes (i.e. `analyse_mcm` returns ≥1 episode). When no MCM data is present, the triage prompt is **byte-identical** to today — satisfying success-criterion 5 mechanically (a golden prompt-hash test asserts it). No `--mcm`/`--no-mcm` flag is added. *(Rejected: opt-out `--no-mcm`, opt-in `--mcm`.)*
- **D-18: Reuse an existing committed MCM fixture slice.** The golden eval case input is an existing redacted denial slice already committed under `tests/fixtures/mcm/` (e.g. `hartford_deny_slice.log`), copied/referenced into `eval/cases/<mcm-case>/`, with `truth.yaml` asserting its known deterministic breakdown figures. No new customer-data decision, no synthetic authoring. *(Rejected: author a new synthetic/redacted fixture.)*
- **D-19: Summary + breakdown + graded flags + top-5 attributions per dimension.** The block carries: episode summary (denial time, `AvailableMCM` headroom descent), denial-time memory breakdown as **% of HWM/total** (not raw GB in headline figures, matching D-11), the graded diagnostic flags (info/warn/critical + triggering %), and the **top-5** attribution rows per dimension (OID / Source / SID) by granted memory. The block is **token-bounded** so it fits the existing prompt budget without crowding out cluster exemplars. *(Rejected: summary+flags only; all attribution rows.)*
- **D-20: Separate fragment `src/sift/prompts/mcm_facts.md`, spliced via a sentinel.** Python computes and formats every figure, renders the fragment, and injects it into the triage prompt at a sentinel marker (mirroring the existing `--kb` block precedent). `triage.md` stays byte-identical when there is no MCM data. Changing the fragment's wording touches **no Python** — but the *numbers* come from the analyser, so the template holds only labels/wording and placeholders, never authored values. *(Rejected: a new conditional section inside `triage.md`.)*

### Claude's Discretion
- Exact sentinel marker string, fragment field ordering, and the precise Pydantic/dataclass shape carrying facts into the renderer are the planner's/executor's call, provided the four decisions above and the carried-forward invariants hold.
- Final `truth.yaml` metric selection for the MCM golden case (which figures to assert, tolerance) is the planner's call, provided the case regression-gates (`sift eval` exits non-zero on regression) per MCM-07.

### Deferred Ideas (OUT OF SCOPE)
- DSSPerformanceMonitor PDH-CSV time-series correlation (PERF-01) — already deferred to v2 (SEED-001).
- Per-run CLI threshold/window knobs for MCM — deferred in Phase 10 (D-12/D-13); Phase 11 does not reintroduce them.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCM-06 | Structured MCM facts (episode summary, memory breakdown, flags, top attributions) feed `sift analyze` as cited evidence, preserving cited ⊆ prompted ⊆ store; figures computed deterministically, never authored by the model | §Injection Point (extend `prompted_ids`), §Sentinel Splice (mirror `_apply_kb_block`), §Analyser API (`analyse_mcm` return shape), §Prompts (fragment loader) |
| MCM-07 | An MCM golden case (denial episode with known breakdown) added to the eval suite and regression-gated | §Eval Harness (`run_case`/`_ingest`/`truth.yaml`/`thresholds.toml`), §Validation Architecture criterion 4 |
</phase_requirements>

## Summary

This is a pure **integration** phase. The deterministic MCM analyser (`pipeline/mcm.py`, `analyse_mcm`) is already built and returns fully typed, `event_id`-carrying facts. The triage prompt assembler (`pipeline/hypothesise.py`) already has the exact machinery Phase 11 needs — a sentinel-spliced reference block (`_apply_kb_block`) and a `prompted_ids` citation gate. Phase 11 threads one more block through that machinery, with the opposite citability polarity to KB: **MCM facts ARE citable** (their `event_id`s get added to `prompted_ids`), whereas KB is deliberately not.

The single most load-bearing structural finding: **the eval harness (`eval/runner.py::_run_pipeline`) calls `hypothesise()` directly and bypasses `cli.analyze` entirely.** Therefore, to make the MCM golden case actually exercise MCM injection (MCM-07), the MCM facts must be built at a chokepoint **both** paths reach. The lowest-touch, most-correct location is **inside `hypothesise()` itself** — call `analyse_mcm(store.query_events(), thresholds)` there, render the fragment, splice it, and extend `prompted_ids`. This is strictly fewer touch-points than mirroring the `kb_context` pattern (which is built in `cli.analyze` and passed down, and would then require a *second* identical wiring in `eval/runner.py`). Building it inside `hypothesise` means the eval path gets MCM injection for free.

**Primary recommendation:** Add MCM injection inside `hypothesise()`: (1) new `mcm_facts.md` fragment (labels + `{placeholders}` only); (2) a pure Python renderer that fills placeholders from `analyse_mcm` output (figures as % of HWM/total per D-19), emitting `[evt:<id>] …` lines; (3) splice via an MCM sentinel in `triage.md` that mirrors `_apply_kb_block` (residue-free strip when empty → byte-identical no-MCM prompt); (4) union the printed MCM `event_id`s into `prompted_ids` so the facts are citable. Then add the 7th golden case reusing `tests/fixtures/mcm/hartford_deny_slice.log`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Compute MCM figures (breakdown %, flags, attributions) | `pipeline/mcm.py` (analyser) | — | Already built (Phases 9–10); model-free, deterministic. Phase 11 only *reads* it. |
| Render fact block text (labels + filled placeholders) | `prompts/mcm_facts.md` + a Python renderer | `render/mcm_report.py` (formatting precedent) | D-20: wording in the template file (CLI-02), numbers computed in Python. |
| Splice fact block into prompt + make citable | `pipeline/hypothesise.py` (`_assemble` / `hypothesise`) | — | The prompt assembler owns `prompted_ids` — the citation gate's allowed set (04-04). |
| Trigger injection automatically | `pipeline/hypothesise.py` (via `analyse_mcm(store.query_events())`) | `cli.analyze`, `eval/runner.py` reach it for free | D-17: automatic when ≥1 episode; both entrypoints funnel through `hypothesise`. |
| Regression-gate the feature | `eval/cases/<mcm>/truth.yaml` + `eval/thresholds.toml` | `eval/runner.py`, `sift eval` | MCM-07/EVAL-03: existing gate exits non-zero on regression. |

## Standard Stack

No new dependencies. Phase 11 is built entirely from libraries already pinned in `uv.lock` and used by the touched modules.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pydantic | 2.13.x | The MCM models (`McmEpisode`, `MemoryBreakdown`, `DiagnosticFlag`, `AttributionRow`) are already `BaseModel(frozen, extra="forbid")`; `Truth` uses the same | Already the project's schema layer |
| Typer | 0.27.0 | `analyze` command surface — **unchanged** (D-17: no new flag) | Already the CLI |
| PyYAML | 6.0.3 | `truth.yaml` for the new golden case (`yaml.safe_load` only) | Already pinned for the eval harness (07) |
| stdlib `importlib.resources` | — | Loading `mcm_facts.md` package data (mirror `_load_triage_template`) | Zero-dep, CLI-02 pattern |
| stdlib `re` | — | Sentinel strip/substitute regexes (mirror `_KB_BLOCK_RE`) | Zero-dep |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Build MCM facts inside `hypothesise()` | Mirror `kb_context`: build in `cli.analyze`, pass a param down | Requires a **second identical wiring** in `eval/runner.py::_run_pipeline` or the golden case never exercises MCM. More files, more drift risk. Reject. |
| Reuse `render/mcm_report.py` formatting helpers | New standalone renderer | The report renderer emits full Markdown tables in MB; the fragment needs a **token-bounded, %-of-HWM, `[evt:]`-tagged** shape. A small purpose-built renderer is cleaner than bending the report one. |

**Installation:** none — `uv sync` already provides everything.

## Package Legitimacy Audit

**Not applicable.** Phase 11 installs **zero** new external packages. All code is written against modules and dependencies already present in the repository and `uv.lock`. No registry lookups required.

## Architecture Patterns

### System Data Flow (MCM injection)

```
store.query_events() ──► analyse_mcm(events, thresholds)  [pipeline/mcm.py, deterministic, model-free]
                                   │  McmAnalysis(episodes=(EpisodeAnalysis, ...))
                                   ▼
                         render_mcm_facts(analysis)  [NEW pure fn: fills mcm_facts.md placeholders,
                                   │                   % of HWM/total, top-5 per dim, [evt:<id>] lines]
                                   │  (fact_block_text, mcm_event_ids: set[str])
                                   ▼
   triage.md ──► _apply_mcm_block(template, fact_block)  [NEW, mirrors _apply_kb_block:
                                   │                        fill sentinel slot OR residue-free strip]
                                   ▼
   _assemble(...) ──► prompt = template + evidence lines
                      prompted_ids = {exemplar ids} ∪ mcm_event_ids   ◄── MCM facts become CITABLE
                                   ▼
   hypothesise state machine (generate → validate → repair → citation gate cited ⊆ prompted → persist)
```

Contrast the KB path: `_apply_kb_block` splices reference material but `prompted_ids` is **left unchanged** — KB stays non-citable (D-01). MCM is the mirror image: same splice mechanism, but its ids **are** unioned into `prompted_ids`.

### Finding 1 — Injection Point (`pipeline/hypothesise.py`)

- The triage prompt is assembled in `_assemble()` (lines 188–231). It builds `event_ids`/`excerpts` from ranked clusters, fits them with `PromptBudget.fit`, emits `[evt:{eid}] {excerpt}` lines, and returns `(chat_messages, set(event_ids), prompt_text)`.
- **`prompted_ids` = `set(event_ids)`** — the printed exemplar ids — IS the citation gate's allowed set. `_citation_gate` (387–432) enforces `cited ⊆ prompted` via `_all_cited_within`. Because those ids are stored exemplars, `cited ⊆ prompted ⊆ store` holds transitively (module docstring, 15–19). `[VERIFIED: src/sift/pipeline/hypothesise.py]`
- **To make MCM facts citable:** union the MCM fact block's `event_id`s into the returned `prompted_ids`. Only ids **actually printed** as `[evt:<id>]` tokens in the fact block may be added — mirroring the exemplar contract (never add an id the model wasn't shown). The MCM `event_id` sources are:
  - `McmEpisode.denial_event_id` — the flags and the episode-summary/breakdown all cite this (every `DiagnosticFlag.event_ids == (denial_event_id,)`, see `compute_flags`).
  - `AttributionRow.event_ids` — the grant-line ids behind each top-5 row.
  - Optionally `LifecycleSignal.event_id` and `avail_timeline` sample ids, if the summary prints them.
- **Where to build it:** inside `hypothesise()` (285–369), after `store.query_clusters()`/`query_template_groups()` and before/inside `_assemble`. `hypothesise` already holds `store`; add one `store.query_events()` call and an `analyse_mcm(...)` call. Pass the rendered fact block + its ids into `_assemble` (a new keyword arg, mirroring `kb_context=`), which splices the block and unions the ids.
- **Thresholds:** `analyse_mcm(events, thresholds)` needs a `McmThresholdsConfig`. `hypothesise` does **not** currently receive config. Add a parameter `mcm_thresholds: McmThresholdsConfig | None = None` (default `McmThresholdsConfig()`). `cli.analyze` passes `config.mcm.thresholds`; `eval/runner.py` can pass the default (figures `value_pct` are threshold-independent ratios — thresholds only set the severity *tier*, so a default is fine for the golden case). `[VERIFIED: src/sift/config.py:98-116 McmConfig.thresholds]`

### Finding 2 — `--kb` Sentinel Splice Precedent (`hypothesise.py` + `triage.md`)

The exact mechanism to mirror (lines 50–74):

```python
_KB_SLOT = "<<KB_CONTEXT>>"
_KB_BLOCK_RE  = re.compile(r"<!-- KB_BLOCK_START.*?-->\n.*?<!-- KB_BLOCK_END.*?-->\n", re.DOTALL)
_KB_MARKER_RE = re.compile(r"<!-- KB_BLOCK_(?:START|END).*?-->\n", re.DOTALL)

def _apply_kb_block(template, kb_context):
    if not kb_context:
        return _KB_BLOCK_RE.sub("", template)        # residue-free strip → byte-identical
    joined = "\n\n".join(sanitise(chunk) for chunk in kb_context)
    return _KB_MARKER_RE.sub("", template).replace(_KB_SLOT, joined)
```

In `triage.md` the KB block is delimited (lines 36–46) by `<!-- KB_BLOCK_START ... -->` / `<!-- KB_BLOCK_END ... -->` around a `<<KB_CONTEXT>>` slot, sitting between the JSON-contract instructions and the trailing `Evidence:` marker. **When absent, the whole block (start-marker through end-marker line, including trailing `\n`) is removed, leaving the pre-change bytes unchanged.**

**Mirror for MCM (D-20):** add an `<!-- MCM_BLOCK_START ... -->` / `<!-- MCM_BLOCK_END ... -->` block with an `<<MCM_FACTS>>` slot, and an `_apply_mcm_block` with the same three-regex shape. **Placement:** because MCM facts are *citable evidence*, place the MCM block adjacent to / inside the `Evidence:` region (so the model treats it as evidence, not background) — unlike KB, which is explicitly framed "NOT evidence … MUST NOT be cited". The fragment text must say the opposite: these lines carry `[evt:<id>]` tokens and MAY be cited.

**No-block byte-identity guard (criterion 5):** the existing golden hash lives in `tests/test_kb_analyze.py`:
```python
_NO_KB_PROMPT_HASH = "ef5b76801235d179"   # pre-change no-KB assembled-prompt hash
# test_assemble_no_kb_is_byte_identical_baseline asserts _prompt_hash(prompt_no) == _NO_KB_PROMPT_HASH
```
The seeded corpus there is **genericlog only** (no dsserrors events) → `analyse_mcm` returns `episodes=()` → the MCM block strips to nothing. **So if the MCM strip is residue-free, this hash stays valid.** The plan must (a) confirm the hash is unchanged after adding the MCM block, and (b) add a symmetric MCM guard: a no-MCM case whose assembled prompt hash equals the pre-MCM baseline. `[VERIFIED: tests/test_kb_analyze.py:60-64,230-238]`

### Finding 3 — Analyser API (`pipeline/mcm.py`)

`analyse_mcm(events: list[Event], thresholds: McmThresholdsConfig) -> McmAnalysis` (956–976) is the single entry. Return shape (all `frozen`, `extra="forbid"`):

```
McmAnalysis
└─ episodes: tuple[EpisodeAnalysis, ...]        # () for a case with no MCM denial → strip, no block
   EpisodeAnalysis
   ├─ episode:  McmEpisode
   │   ├─ denial_event_id: str          # the citable id for summary + breakdown + all flags
   │   ├─ denial_ts: str | None         # episode-summary "denial time"
   │   ├─ recovery: str | None; open_truncated: bool; fragmented: bool
   │   ├─ event_ids: tuple[str, ...]    # every row in the episode span (the ⊆ store bridge)
   │   ├─ lifecycle: tuple[LifecycleSignal, ...]   # kind/event_id/ts/text
   │   ├─ breakdown: MemoryBreakdown    # ALWAYS present; empty ⇒ accessors return None (D-03)
   │   ├─ hwm_bytes: int | None         # last lead-up HWM sample — the "% of HWM" denominator
   │   └─ avail_timeline: tuple[(event_id, avail_bytes, hwm_bytes), ...]  # AvailableMCM descent
   ├─ window:  EpisodeWindow            # threshold_pct, start_event_id, label ("AvailableMCM < 25% of HWM …")
   ├─ flags:   tuple[DiagnosticFlag, ...]   # dimension/severity/value_pct/message/event_ids=(denial_event_id,)
   └─ attribution: Attribution
      ├─ by_oid:    tuple[AttributionRow, ...]   # sorted granted_bytes desc, key asc → take [:5]
      ├─ by_source: tuple[AttributionRow, ...]   # AttributionRow: dimension/key/granted_bytes/
      ├─ by_sid:    tuple[AttributionRow, ...]   #   request_count/event_ids/sids(oid only)
      └─ unmatched_event_ids: tuple[str, ...]
```

Key sourcing per D-19:
- **Episode summary:** `episode.denial_ts` (denial time) + `episode.avail_timeline` / `window.label` (AvailableMCM headroom descent). Cite `denial_event_id`.
- **Breakdown as % of HWM/total:** `MemoryBreakdown` accessors return **MB** (`working_set_mb`, `iserver_virtual_mb`, `cube_caches_mb`, `physical_total`, …). Headline percentages are **already computed** in the flags (`DiagnosticFlag.value_pct` = part/whole·100, e.g. working-set % of IServer virtual = 65.4% at Hartford). **Prefer surfacing the flag `value_pct` figures directly** rather than re-deriving in the fragment renderer — they are the milestone-locked machine-independent ratios (D-11). For any % not covered by a flag, compute `part_mb / (hwm_bytes/1024² ) * 100` in the Python renderer.
- **Graded flags:** iterate `ea.flags`; each has `severity` (info/warn/critical), `value_pct`, and a British-English `message` with the % inline. Sort by severity for display (the CLI uses `{"critical":0,"warn":1,"info":2}`, cli.py:1059).
- **Top-5 attributions per dimension:** `attribution.by_oid[:5]`, `by_source[:5]`, `by_sid[:5]` — rows are **already sorted** `granted_bytes` desc then `key` asc (`attribute_window.rows`, 933–946), so a plain slice gives the top-5 (D-19). `AttributionRow.event_ids` are the citable grant-line ids.
- **Multi-episode:** `episodes` may hold several `EpisodeAnalysis`. The fragment/renderer must bound tokens across all episodes (D-19 "token-bounded") — e.g. cap episodes or top-N globally; the `hartford_deny_slice.log` golden is single-episode, but `hartford_two_episode_partial.log` exists if a multi-episode budget test is wanted.

`analyse_mcm` is pure, I/O-free, network-free, and byte-identical on re-run (no `set` iteration) — this is what makes the determinism proof (criterion 2) mechanical. `[VERIFIED: src/sift/pipeline/mcm.py]`

### Finding 4 — Prompts (`prompts/triage.md`, `prompts/__init__.py`)

- Templates are plain `.md` package data, loaded via `importlib.resources.files("sift.prompts").joinpath("triage.md").read_text()` (`_load_triage_template`, 107–113). No templating engine — substitution is literal `str.replace` on `<<SLOT>>` markers plus regex strip. `[VERIFIED: src/sift/pipeline/hypothesise.py:107-113]`
- **`mcm_facts.md` (D-20)** holds only labels/wording + placeholders. The Python renderer fills placeholders with `analyse_mcm` figures; the template **never** carries a number. Changing wording touches no Python (CLI-02). Load it with the same `importlib.resources` idiom (add `_MCM_FILE = "mcm_facts.md"`).
- Placeholder style: reuse the literal-marker convention (e.g. `<<MCM_FACTS>>` in `triage.md` is the splice point; the *body* rendered from `mcm_facts.md` can itself use `str.format`-style `{denial_ts}`, `{working_set_pct}`, or a repeated-row placeholder the renderer expands). Keep the fragment's own placeholder scheme the executor's call (discretion), but numbers must originate in Python.
- **Untrusted-data framing:** log-derived text (attribution keys, messages) is untrusted. Run every interpolated log-derived value through `render._util.sanitise` before it enters the prompt (the KB path does exactly this: `sanitise(chunk)`), and the fragment prose must instruct the model to treat the facts as data. Note the values here are mostly regex-gated (hex ids, numeric %) so the exposure is small, but `sanitise` is the established belt-and-braces.

### Finding 5 — Eval Harness (`eval/`, `sift eval`)

- **Case layout:** each `eval/cases/<name>/` has `input/` (raw artefacts), `truth.yaml`, `README.md`. `sift eval` discovers cases as sorted dirs containing `truth.yaml` (cli.py:1134–1139). `[VERIFIED: eval/cases/*, cli.py:1073-1190]`
- **`truth.yaml` schema** (`eval/truth.py`, `Truth` model, `extra="forbid"`, `yaml.safe_load` only):
  - `root_cause: str` (required) — prose, also used by the optional judge.
  - `required_evidence: list[str]` — regexes matched case-insensitively against the **cluster exemplars fed to the model** → drives `retrieval_hit_rate` (floor 0.80).
  - `acceptable_keywords: list[str]` — any-of, case-insensitive, vs a hypothesis's title+narrative → drives `hypothesis_hit_at_k` (floor 1.00).
  - `expect_no_incident: bool` — negative-case marker.
- **How a case runs (`eval/runner.py::run_case`):** creates a temp `case.db`, sets `meta` `input_dir` = `<case>/input`, calls `cli._ingest`, then `_run_pipeline` (which calls `cluster_and_label` + **`hypothesise` directly** — *not* `cli.analyze*), repeats N=2 times for determinism, and scores four metrics against `truth.yaml`. `[VERIFIED: eval/runner.py:71-199]`
  - **⇒ This is why MCM injection must live inside `hypothesise` (Finding 1):** `run_case` never touches `cli.analyze` or `kb_context`. If MCM were wired only in `cli.analyze`, the golden case would run the pipeline **without** MCM facts and `truth.yaml` could not assert them. Building MCM inside `hypothesise` makes `_run_pipeline` exercise it automatically. If instead the planner keeps MCM building in `cli.analyze`, `_run_pipeline` (lines 71–96) MUST be extended to build and pass the same facts — flag this explicitly in the plan.
- **The 7th golden case (D-18):** create `eval/cases/mcm-denial/` with `input/hartford_deny_slice.log` (copy the committed `tests/fixtures/mcm/hartford_deny_slice.log`) + `truth.yaml` + `README.md`. The dsserrors adapter's `sniff` returns 0.8 on this file (`_SNIFF_STRINGS = ("Contract Request Failed", "Info Dump", "MCM", "I-Server")` and the `[*.cpp:NNNN]` src-loc regex both match the slice's content) so ingest auto-selects the dsserrors adapter — **no `--adapter` override needed**. `[VERIFIED: src/sift/adapters/dsserrors.py:90-91,165-168 + fixture head]`
- **`truth.yaml` for the MCM case:** `required_evidence` regexes should match the MCM fact lines now fed to the model (e.g. `working set.*%`, `AvailableMCM`, the denial timestamp), and `acceptable_keywords` (memory, MCM, working set, denial). Because the fake/real model must produce a hypothesis citing the denial event to score `hit@k` and `citation_validity`, the eval run needs an inference endpoint — offline test runs bind `httpx.MockTransport` via the `_make_http_client` seam (EVAL-05); the live `sift eval` needs a real server. **Frozen-truth rule:** author `truth.yaml` before prompt tuning; a regression must fail, never be edited to pass.
- **Gate (EVAL-03, ADR 0010):** `eval/thresholds.toml` holds four lower-bound floors; `gate()` fails (exit 1) if any aggregate regresses, any case `run_failed`, an `expect_no_incident` case emits a confident hypothesis, or a positive aggregate is vacuously empty. The MCM case is a **positive** case (`expect_no_incident: false`). `[VERIFIED: cli.py:1181-1190, eval/thresholds.toml]`

### Finding 6 — Determinism Proof (criterion 2 test shape)

The anti-hallucination guarantee: figures surfaced for a hypothesis come from `analyse_mcm` (via the fact block + the citation→evidence path), **never** from the model's free-text output. `analyse_mcm` is model-free and byte-identical on re-run, and the fact block is assembled **before** the generation call. So a model that echoes mutated numbers cannot change what the fact block (or the persisted/rendered figures) says.

**Concrete test (reuse the fake-OpenAI harness in `tests/test_hypothesise.py` / `tests/test_kb_analyze.py`):**
1. Seed a case from `hartford_deny_slice.log` through the real ingest→dedup path (dsserrors events).
2. Build the fake `InferenceClient` over `httpx.MockTransport` (the autouse `_no_network` fixture stays active — zero sockets). Return a schema-valid `HypothesisSet` whose narrative contains a **wrong** figure (e.g. `"working set was 99% of virtual"`) while `supporting_event_ids` cites the real `denial_event_id`.
3. Assert the **fact block spliced into the prompt** contains the analyser's verbatim figure (e.g. `65.4%`) and **not** `99%` — i.e. `render_mcm_facts(analyse_mcm(...))` is the source of truth, independent of the LLM reply.
4. Assert `prompted_ids` contains the MCM `event_id`(s) → the model's citation of `denial_event_id` is **valid** (a positive citability check), while an invented id is still flagged.
5. (Determinism) run assembly twice and assert byte-identical fact blocks.

The essence: the fact block is a pure function of `analyse_mcm` output, constructed pre-generation; no code path lets the model's response feed back into the figures. This mirrors how the KB tests prove non-citability by construction rather than by inspecting model output.

### Anti-Patterns to Avoid
- **Wiring MCM only in `cli.analyze`.** The eval golden case bypasses it → MCM-07 silently un-exercised (a green suite that proves nothing — see claude-smart rule s3-52 on vacuous aggregates). Build at the `hypothesise` chokepoint.
- **Letting the fragment carry numbers.** Violates D-20/CLI-02. Numbers computed in Python only.
- **Adding MCM ids to `prompted_ids` that are not printed in the block.** Breaks the "model was actually shown it" invariant — only union ids for lines actually rendered.
- **A non-residue-free strip.** Any leftover whitespace/newline when no MCM present changes the prompt hash → criterion 5 fails. Match `_KB_BLOCK_RE`'s trailing-`\n` capture exactly.
- **Re-deriving % from MB when a flag already computed it.** Prefer `DiagnosticFlag.value_pct` (the machine-independence-locked ratio) over recomputing in the renderer.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Splice a conditional block into the prompt with byte-identical-when-empty | A new bespoke templating scheme | Mirror `_apply_kb_block` + three regexes | Proven, golden-hash-guarded, residue-free |
| Load the fragment file | `open()`/path math | `importlib.resources.files("sift.prompts")` | CLI-02 package-data pattern already in `_load_triage_template` |
| Compute breakdown percentages | New % maths in the fragment | `DiagnosticFlag.value_pct` from `compute_flags` | Already computed, machine-independent (D-11), 1-dp rounded |
| Top-5 per dimension | Re-sort attribution rows | `attribution.by_*[:5]` | Rows already sorted granted desc, key asc |
| Citation enforcement for MCM | New gate | Union ids into `prompted_ids`; existing `_citation_gate` does the rest | `cited ⊆ prompted ⊆ store` holds transitively |
| Eval case scoring | New harness | `run_case` + `truth.yaml` + `thresholds.toml` | EVAL-02/03 already built; add a 7th dir |
| Zero-network test LLM | Real server / new stub | `httpx.MockTransport` handler from `tests/test_hypothesise.py` | EVAL-05, established fake OpenAI-compatible server |

**Key insight:** Phase 11 writes almost no new *mechanism* — it reuses two existing chokepoints (the sentinel splice and the `prompted_ids` gate) with inverted citability polarity, plus one new pure renderer and one fragment file.

## Common Pitfalls

### Pitfall 1: Golden case never exercises MCM
**What goes wrong:** MCM wired only in `cli.analyze`; `sift eval` runs `hypothesise` directly, so the golden case scores a "pass" with no MCM facts in the prompt.
**How to avoid:** Build MCM inside `hypothesise` (Finding 1/5). Add a test asserting the MCM block appears in the prompt during a `run_case`/`_run_pipeline` run for the MCM case.
**Warning signs:** MCM case green but `required_evidence` regexes never match MCM lines; removing the injection code doesn't turn the suite red.

### Pitfall 2: No-MCM prompt hash drift (criterion 5)
**What goes wrong:** The MCM sentinel strip leaves a stray blank line → `_NO_KB_PROMPT_HASH` breaks.
**How to avoid:** Copy `_KB_BLOCK_RE` exactly (capture the trailing `\n`). Re-run `test_assemble_no_kb_is_byte_identical_baseline` after adding the block; it must still pass unchanged, and add an equivalent no-MCM assertion.

### Pitfall 3: Thresholds not available in `hypothesise`
**What goes wrong:** `analyse_mcm` needs `McmThresholdsConfig`; `hypothesise` has no config.
**How to avoid:** Add `mcm_thresholds: McmThresholdsConfig | None = None` (default `McmThresholdsConfig()`); `cli.analyze` passes `config.mcm.thresholds`, eval passes the default. `value_pct` figures are threshold-independent, so the default is safe for the golden case.

### Pitfall 4: Token budget crowd-out (D-19)
**What goes wrong:** An unbounded MCM block (all attribution rows, all episodes) pushes cluster exemplars out of `PromptBudget`.
**How to avoid:** Top-5 per dimension (`[:5]`) and a bounded episode/summary shape. Note the MCM block is spliced into the template *before* `PromptBudget.fit` runs on the exemplar excerpts — the fact block is fixed overhead, so keep it small.

### Pitfall 5: MCM facts framed as non-evidence
**What goes wrong:** Copy KB's "MUST NOT be cited" prose into `mcm_facts.md` → the model refuses to cite the figures, `hit@k`/citation metrics suffer.
**How to avoid:** The fragment must frame MCM lines as **citable evidence** carrying `[evt:<id>]` tokens (opposite polarity to KB), and their ids must be in `prompted_ids`.

## Code Examples

### The splice mirror (new, modelled on `_apply_kb_block`)
```python
# pipeline/hypothesise.py  — mirrors lines 54-74 with inverted citability
_MCM_SLOT = "<<MCM_FACTS>>"
_MCM_BLOCK_RE  = re.compile(r"<!-- MCM_BLOCK_START.*?-->\n.*?<!-- MCM_BLOCK_END.*?-->\n", re.DOTALL)
_MCM_MARKER_RE = re.compile(r"<!-- MCM_BLOCK_(?:START|END).*?-->\n", re.DOTALL)

def _apply_mcm_block(template: str, fact_block: str | None) -> str:
    if not fact_block:                                   # no episodes → byte-identical strip
        return _MCM_BLOCK_RE.sub("", template)
    return _MCM_MARKER_RE.sub("", template).replace(_MCM_SLOT, fact_block)
```

### Sourcing figures + citable ids from the analyser (renderer sketch)
```python
# NEW pure fn (e.g. pipeline/mcm_facts.py or render/mcm_facts.py)
def render_mcm_facts(analysis: McmAnalysis) -> tuple[str, set[str]]:
    if not analysis.episodes:
        return "", set()
    ids: set[str] = set()
    lines: list[str] = []
    for ea in analysis.episodes:
        ep = ea.episode
        ids.add(ep.denial_event_id)
        lines.append(f"[evt:{ep.denial_event_id}] MCM denial at {ep.denial_ts}; "
                     f"{ea.window.label}")
        for f in sorted(ea.flags, key=lambda f: {'critical':0,'warn':1,'info':2}[f.severity]):
            lines.append(f"[evt:{f.event_ids[0]}] {f.severity}: {sanitise(f.message)}")  # % inline
        for dim in (ea.attribution.by_oid, ea.attribution.by_source, ea.attribution.by_sid):
            for r in dim[:5]:                              # top-5, already sorted (D-19)
                ids.update(r.event_ids)
                lines.append(f"[evt:{r.event_ids[0]}] {r.dimension}={sanitise(r.key)} "
                             f"granted {r.granted_bytes/1024**2:,.1f} MB")
    # fill mcm_facts.md's <<MCM_FACTS>> body with "\n".join(lines) (labels live in the template)
    return _load_mcm_fragment().replace("<<MCM_LINES>>", "\n".join(lines)), ids
```
*(Placeholder scheme is executor's discretion; the invariant is numbers-from-Python, wording-from-template.)*

## State of the Art

Not applicable — no external technology choices. The "current approach" is the in-repo `_apply_kb_block` + `prompted_ids` pattern established in Phase 6 (KB) and Phase 4 (citation gate); Phase 11 follows it directly.

## Validation Architecture

> nyquist_validation is `true` in `.planning/config.json` — this section is included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (confirmed Phase 6) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`; perf tests behind `@pytest.mark.perf`, excluded by default `addopts`) |
| Quick run command | `uv run pytest tests/test_hypothesise.py tests/test_mcm.py -x` |
| Full suite command | `uv run pytest` (plus `uv run ruff check` and `uv run pyright` — the "done" gate) |
| Zero-network harness | `httpx.MockTransport` handler (`tests/test_hypothesise.py::_handler`, `test_kb_analyze.py`); autouse `_no_network` conftest fixture (EVAL-05) |

### Phase Requirements → Test Map (proving each success criterion)
| Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|-------------------|-------------|
| C1 (MCM-06) | MCM facts injected into `sift analyze` prompt as **citable** evidence; MCM ids in `prompted_ids`; `cited ⊆ prompted ⊆ store` holds | unit + e2e | `pytest tests/test_mcm_analyze.py -x` | ❌ Wave 0 |
| C2 (determinism proof) | Fake LLM echoing **mutated** numbers cannot alter surfaced figures; fact block == `analyse_mcm` verbatim, built pre-generation, byte-identical on re-run | unit | `pytest tests/test_mcm_analyze.py::test_model_cannot_alter_mcm_figures -x` | ❌ Wave 0 |
| C3 (D-20) | Fact block is a versioned `mcm_facts.md` fragment; wording change touches no Python; numbers from Python | unit | `pytest tests/test_mcm_analyze.py::test_fragment_holds_no_numbers -x` | ❌ Wave 0 |
| C4 (MCM-07/EVAL-03) | 7th golden case with `truth.yaml`; `sift eval` exits non-zero on regression | integration | `pytest tests/test_eval_cases.py -x` + a live/offline `sift eval` run | ⚠️ extend `tests/test_eval_cases.py` |
| C5 (additivity) | No dsserrors/MCM data ⇒ prompt **byte-identical** to pre-MCM (golden hash) | unit | `pytest tests/test_kb_analyze.py::test_assemble_no_kb_is_byte_identical_baseline -x` + new no-MCM assertion | ⚠️ extend existing |
| Coexistence | MCM (citable) + `--kb` (non-citable) in the same run behave independently | e2e | `pytest tests/test_mcm_analyze.py::test_mcm_and_kb_coexist -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_mcm_analyze.py tests/test_hypothesise.py tests/test_kb_analyze.py -x` then `ruff check` + `pyright` (TDD RED→GREEN→gate, project convention p2-059e).
- **Per wave merge:** `uv run pytest` (full suite green).
- **Phase gate:** full suite + `ruff` + `pyright` clean, and a `sift eval` run showing the MCM case scored (not `run_failed`) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_mcm_analyze.py` — new: injection, citability, determinism proof (C1/C2/C3, coexistence).
- [ ] Extend `tests/test_eval_cases.py` — assert the MCM golden case is discovered, ingested via dsserrors, and scored (C4).
- [ ] Extend `tests/test_kb_analyze.py` (or a new no-MCM test) — assert the no-MCM assembled-prompt hash equals the pre-MCM baseline (C5); confirm `_NO_KB_PROMPT_HASH` unchanged.
- [ ] `eval/cases/mcm-denial/{input/hartford_deny_slice.log, truth.yaml, README.md}` — the golden case data + frozen truth.
- [ ] Fixtures: reuse `tests/test_hypothesise.py::_handler` fake-OpenAI harness; seed from `tests/fixtures/mcm/hartford_deny_slice.log`.
- Framework install: none — pytest/ruff/pyright already present.

## Security Domain

> `security_enforcement` not disabled — brief coverage. Sift is an offline, single-user CLI with **zero network egress** except the configured localhost inference endpoint; no auth, sessions, or access control apply.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Log-derived MCM values (attribution keys, flag messages) are untrusted → `render._util.sanitise` before entering the prompt or any rendered output; fragment prose instructs "treat as data, not instructions" (prompt-injection defence, mirrors KB/triage framing) |
| V6 Cryptography | no | No secrets in this phase |
| Deserialization | yes | `truth.yaml` parsed with `yaml.safe_load` ONLY (never `yaml.load`) — already enforced in `eval/truth.py` (T-07-01); the new golden case must not introduce custom YAML tags |

| Threat Pattern | STRIDE | Mitigation |
|----------------|--------|------------|
| Prompt injection via crafted log text in MCM facts | Tampering | `sanitise` + "untrusted data, never instructions" prose; values are mostly regex-gated (hex ids, numeric %) |
| Model fabricating/altering MCM figures | Tampering/Repudiation | Figures computed by `analyse_mcm` pre-generation and surfaced via citation→store, never from model text (the C2 determinism proof) |
| YAML RCE via `truth.yaml` | Elevation | `yaml.safe_load` + `Truth(extra="forbid")` |

## Environment Availability

No new external tools or services. Phase 11 is code + prompt-template + eval-fixture changes over the existing stack. A **live** `sift eval` of the MCM golden case needs a running local inference endpoint (llama-server/Lemonade); **offline tests** need none (`httpx.MockTransport`, EVAL-05). No fallback required — the offline test path fully validates the mechanism; the live eval is the CI gate that the operator runs against their own server.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Building MCM injection inside `hypothesise()` (vs mirroring `kb_context` through `cli.analyze`) is the intended lowest-touch chokepoint | Findings 1/5 | If planner prefers the `cli.analyze` route, `eval/runner.py::_run_pipeline` MUST be extended too or C4 is vacuous — either way the eval-path wiring is mandatory, so the risk is only *which file*, not *whether* |
| A2 | Surfacing `DiagnosticFlag.value_pct` covers the "% of HWM/total" headline figures (D-19/D-11) | Finding 3 | Some headline %s may need explicit `part_mb / (hwm_bytes/1024²)·100` computation in the renderer; low risk — the maths is trivial and the values exist |
| A3 | `hartford_deny_slice.log` is single-episode and ingests cleanly via dsserrors auto-sniff into `eval/cases/.../input/` | Finding 5 | If the slice is multi-episode or needs an adapter override, the golden case setup adjusts (fixtures for both single and multi-episode exist); verify at plan time by ingesting it |
| A4 | The existing `_NO_KB_PROMPT_HASH` baseline remains valid after adding a residue-free MCM block | Finding 2 | If it drifts, the strip regex is wrong; caught immediately by the existing test — self-correcting |

**Note:** No `[ASSUMED]` package claims — zero new packages. The assumptions above are integration-design choices the planner confirms by reading the same source, not unverified external facts.

## Open Questions

1. **`truth.yaml` metric selection for the MCM case (explicitly planner's discretion, D-19/MCM-07).**
   - What we know: schema is `root_cause`/`required_evidence`/`acceptable_keywords`/`expect_no_incident`; floors are retrieval 0.80, hit@k 1.00, citation 1.00, determinism 1.00.
   - What's unclear: exactly which MCM figures/regexes to assert as `required_evidence` and which keywords.
   - Recommendation: assert the working-set % flag line, the denial timestamp, and `AvailableMCM`; keywords {memory, MCM, working set, denial}. Freeze before any prompt tuning (frozen-truth rule).

2. **Fact-block episode/token bound for multi-episode cases (D-19 "token-bounded").**
   - What we know: `hartford_deny_slice.log` is the golden (single episode); top-5 per dimension caps attribution.
   - What's unclear: global cap when several episodes exist.
   - Recommendation: single-episode is enough for the golden case; add a bound (e.g. first N episodes) with a comment noting the ceiling if multi-episode budget pressure ever arises.

## Sources

### Primary (HIGH confidence — in-repo source, read this session)
- `src/sift/pipeline/hypothesise.py` — `_apply_kb_block`, `_assemble`, `prompted_ids`, `_citation_gate`, `hypothesise` signature — injection point + splice precedent.
- `src/sift/pipeline/mcm.py` — `analyse_mcm` and full return model tree (`McmAnalysis`→`EpisodeAnalysis`→`McmEpisode`/`MemoryBreakdown`/`DiagnosticFlag`/`AttributionRow`).
- `src/sift/prompts/triage.md`, `src/sift/prompts/__init__.py` — sentinel block + package-data loading.
- `src/sift/cli.py` (`analyze` ~660–896, KB splice 824–842, `mcm` 1002–1070, `eval` 1073–1190) — command wiring, exit-code contract.
- `src/sift/eval/runner.py`, `src/sift/eval/truth.py`, `eval/thresholds.toml`, `eval/cases/memory-watermark-cascade/truth.yaml` — harness, truth schema, gate.
- `tests/test_kb_analyze.py`, `tests/test_hypothesise.py` — fake-OpenAI harness + golden no-KB hash guard.
- `src/sift/adapters/dsserrors.py:90-91,165-168` + `tests/fixtures/mcm/hartford_deny_slice.log` — sniff auto-selection of the golden fixture.
- `src/sift/config.py:98-116` — `McmConfig.thresholds`.
- `src/sift/render/mcm_report.py` — existing figure-formatting precedent (flags value_pct %, attribution sort).
- `.planning/STATE.md` decisions D-01..D-16 (MCM analyser invariants), `.planning/REQUIREMENTS.md` (MCM-06/07).

### Secondary / Tertiary
- None — no web sources needed; the phase is fully in-repo.

## Metadata

**Confidence breakdown:**
- Injection point / splice mechanism: HIGH — read the exact functions and the golden-hash test that guards them.
- Analyser API / figure sourcing: HIGH — full model tree read; % figures already computed in `compute_flags`.
- Eval harness / golden case: HIGH — read `run_case`, `truth.py`, thresholds, and confirmed dsserrors auto-sniff on the fixture.
- Determinism proof shape: HIGH — grounded in the model-free analyser + existing fake-LLM harness.

**Research date:** 2026-07-19
**Valid until:** 2026-08-18 (30 days — stable in-repo code; re-verify only if `hypothesise.py`, `mcm.py`, or the eval harness change before planning).
