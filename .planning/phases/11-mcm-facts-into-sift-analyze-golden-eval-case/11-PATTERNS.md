# Phase 11: MCM Facts into `sift analyze` + Golden Eval Case - Pattern Map

**Mapped:** 2026-07-19
**Files analyzed:** 8 (2 new source, 3 modified source, 1 new prompt, 1 new eval case, tests)
**Analogs found:** 8 / 8 (all in-repo; zero new dependencies)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/prompts/mcm_facts.md` | prompt-template (config/data) | transform | `src/sift/prompts/triage.md` (KB_BLOCK region) | exact |
| `src/sift/pipeline/mcm_facts.py` *(NEW renderer, or fold into hypothesise.py)* | utility/renderer | transform | `_apply_kb_block` + `render/mcm_report.py` | role-match |
| `src/sift/pipeline/hypothesise.py` | pipeline (prompt assembler) | request-response | itself (`_apply_kb_block`, `_assemble`, `hypothesise`) | exact (self-mirror) |
| `src/sift/cli.py` (`analyze`) | route/command | request-response | `cli.py` `--kb` splice (824–861) + `mcm` cmd (1003–1036) | exact |
| `eval/cases/mcm-denial/truth.yaml` + `README.md` + `input/` | config/test-fixture | batch | `eval/cases/memory-watermark-cascade/truth.yaml` | exact |
| `tests/test_mcm_analyze.py` *(NEW)* | test | request-response | `tests/test_kb_analyze.py` + `tests/test_hypothesise.py` | exact |
| `tests/test_kb_analyze.py` (extend) | test | request-response | `_NO_KB_PROMPT_HASH` guard (line 64) | self |
| `tests/test_eval_cases.py` (extend) | test | batch | existing case-discovery assertions | self |

**Consumed read-only (not modified):** `src/sift/pipeline/mcm.py` (`analyse_mcm` + model tree), `src/sift/config.py:76,103` (`McmThresholdsConfig`, `McmConfig.thresholds`), `src/sift/render/mcm_report.py` (formatting precedent).

## Pattern Assignments

### `src/sift/prompts/mcm_facts.md` (prompt-template, transform)

**Analog:** `src/sift/prompts/triage.md` lines 36–47 (the KB block).

The KB block is the exact shape to mirror — HTML-comment sentinels around a `<<SLOT>>`, prose framing the injected text — **but with inverted citability polarity**. KB prose (triage.md:38–42) says *"It is NOT evidence … MUST NOT be cited in `supporting_event_ids`."* The MCM fragment must say the opposite: these lines carry `[evt:<id>]` tokens and MAY be cited. Numbers are NEVER in this file (D-20) — only labels, prose, and a body placeholder (e.g. `<<MCM_LINES>>`).

**Sentinel block pattern to copy** (`triage.md:36–47`):
```markdown
<!-- KB_BLOCK_START (inserted only for `sift analyze --kb`; hypothesise._apply_kb_block substitutes <<KB_CONTEXT>> and drops these two marker lines, or removes the whole block ... when no KB is supplied, so the no-KB prompt stays byte-identical) -->
Reference material follows ... It is NOT evidence: it carries no `[evt:<id>]` citation tokens ... MUST NOT be cited ...

<<KB_CONTEXT>>

<!-- KB_BLOCK_END -->
Evidence:
```

The `<!-- MCM_BLOCK_START ... -->` / `<<MCM_FACTS>>` / `<!-- MCM_BLOCK_END -->` block goes **inside/adjacent to the `Evidence:` region** (MCM facts are evidence, unlike KB which sits above `Evidence:`). Match the trailing-`\n` layout exactly so the residue-free strip preserves the baseline hash.

---

### `src/sift/pipeline/hypothesise.py` — splice + citable-ids union (pipeline, request-response)

**Analog:** the file's own `_apply_kb_block` (54–74), `_assemble` (188–231), `hypothesise` (285–369).

**1. Sentinel constants + splice fn** — copy `_apply_kb_block` (54–74) verbatim, rename KB→MCM, invert citability in the docstring:
```python
# lines 54–74, the template to mirror:
_KB_SLOT = "<<KB_CONTEXT>>"
_KB_BLOCK_RE = re.compile(
    r"<!-- KB_BLOCK_START.*?-->\n.*?<!-- KB_BLOCK_END.*?-->\n", re.DOTALL
)
_KB_MARKER_RE = re.compile(r"<!-- KB_BLOCK_(?:START|END).*?-->\n", re.DOTALL)

def _apply_kb_block(template: str, kb_context: list[str] | None) -> str:
    if not kb_context:
        return _KB_BLOCK_RE.sub("", template)          # residue-free strip → byte-identical
    joined = "\n\n".join(sanitise(chunk) for chunk in kb_context)
    return _KB_MARKER_RE.sub("", template).replace(_KB_SLOT, joined)
```
The MCM mirror: `_apply_mcm_block(template, fact_block: str | None)` — same three-regex shape. **Critical (Pitfall 2 / anti-pattern):** the block regex MUST capture the trailing `\n` exactly as `_KB_BLOCK_RE` does, or `_NO_KB_PROMPT_HASH` drifts and C5 fails.

**2. Fragment loader** — copy `_load_triage_template` (107–113):
```python
def _load_triage_template() -> str:
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_PROMPT_FILE)
        .read_text(encoding="utf-8")
    )
```
Add `_MCM_FILE = "mcm_facts.md"` and an analogous `_load_mcm_fragment()`.

**3. `_assemble` — union MCM ids into `prompted_ids`** (the load-bearing inversion). Current signature (188–197) takes `kb_context` and applies it (210) but the returned `set(event_ids)` at line 231 does NOT include KB ids (KB is non-citable). Add a keyword `mcm_block: tuple[str, set[str]] | None = None`; splice the text like line 210, and change line 231:
```python
# current line 210:
template = _apply_kb_block(template, kb_context)
# current return line 231:
return [{"role": "user", "content": prompt}], set(event_ids), prompt
```
becomes — splice MCM after KB, then `set(event_ids) | mcm_ids`. **Only ids actually printed as `[evt:<id>]` in the fact block may be unioned** (mirrors the exemplar contract at 224–227; anti-pattern: never add an id the model wasn't shown).

**4. `hypothesise` — build facts at the chokepoint** (313–330). It already holds `store`, calls `store.query_clusters()`/`query_template_groups()`, loads the template (320), and calls `_assemble` (327–330 passing `kb_context=kb_context`). Add:
- new param `mcm_thresholds: McmThresholdsConfig | None = None` (default constructed) — matching the `kb_context: list[str] | None = None` param style at 294;
- `analyse_mcm(store.query_events(), mcm_thresholds or McmThresholdsConfig())` then `render_mcm_facts(...)`, passed into `_assemble` as `mcm_block=`.

**Why here, not `cli.analyze` (VERIFIED, load-bearing):** `eval/runner.py::_run_pipeline` (71–96) calls `hypothesise(...)` directly (86–93) and never touches `cli.analyze` or `kb_context`. Building MCM inside `hypothesise` makes the eval golden case exercise it for free; wiring it in `cli.analyze` would leave the eval path un-exercised (C4 vacuous — Pitfall 1).

---

### `src/sift/pipeline/mcm_facts.py` (NEW renderer, utility, transform)

**Analog:** figure-formatting in `src/sift/render/mcm_report.py` (severity ordering, `value_pct`, attribution slicing) + `sanitise` usage from `_apply_kb_block` (73).

Pure fn `render_mcm_facts(analysis: McmAnalysis) -> tuple[str, set[str]]`. Sourcing (VERIFIED, `pipeline/mcm.py` model tree, RESEARCH Finding 3):
- summary: `ep.denial_ts` + `ea.window.label`; cite `ep.denial_event_id`.
- flags: iterate `ea.flags`, sort by severity `{"critical":0,"warn":1,"info":2}` (same order used in `cli.py:1059`); surface `flag.value_pct` (already computed, machine-independent per D-11) — do NOT re-derive %. Each flag's `event_ids == (denial_event_id,)`.
- attributions: `ea.attribution.by_oid[:5]`, `by_source[:5]`, `by_sid[:5]` — already sorted granted desc / key asc, plain slice = top-5 (D-19). Union each `row.event_ids`.
- **Every log-derived value (`row.key`, `flag.message`) through `render._util.sanitise`** before interpolation (V5 / prompt-injection defence; mirrors `sanitise(chunk)` at hypothesise.py:73).

Returns `("", set())` when `analysis.episodes == ()` → drives the residue-free strip (byte-identical no-MCM prompt).

---

### `src/sift/cli.py` — thread thresholds into `analyze` (route, request-response)

**Analog:** the `--kb` block at 824–861 (build context, pass down) and the `mcm` command at 1003–1036 (`analyse_mcm` call + config).

`analyze` calls `hypothesise(...)` at 850–861 already passing `kb_context=kb_context`. Add one kwarg `mcm_thresholds=config.mcm.thresholds` — the exact value `sift mcm` uses:
```python
# cli.py:1036 — the established call
analysis = analyse_mcm(store.query_events(), config.mcm.thresholds)
```
No new CLI flag (D-17). `config.mcm.thresholds` is `McmThresholdsConfig` (config.py:103). This is additive and composes with `--kb` (both citable-MCM and non-citable-KB in the same run — Coexistence criterion).

---

### `eval/cases/mcm-denial/` (config/test-fixture, batch)

**Analog:** `eval/cases/memory-watermark-cascade/truth.yaml` (full file above) + `eval/runner.py::run_case`/`_run_pipeline`.

`truth.yaml` schema (frozen-truth rule — author before prompt tuning):
```yaml
# Frozen ground truth (D-02): authored before any prompt tuning. Do not edit to
# make a run pass — a regression must fail ...
root_cause: > ...
required_evidence:     # regexes, case-insensitive, vs clusters/MCM lines fed to the model
  - "working set.*%"
  - "AvailableMCM"
  - "<denial timestamp>"
acceptable_keywords:   # any-of vs hypothesis title + narrative
  - memory
  - MCM
  - working set
  - denial
expect_no_incident: false
```
Layout: `input/hartford_deny_slice.log` = copy of `tests/fixtures/mcm/hartford_deny_slice.log` (D-18). dsserrors adapter auto-sniffs (0.8) — no `--adapter` override. `sift eval` discovers sorted dirs containing `truth.yaml` (cli.py:1134–1139); gate exits non-zero on regression (EVAL-03). Parse is `yaml.safe_load` + `Truth(extra="forbid")` only — no custom tags.

---

### `tests/test_mcm_analyze.py` (NEW) + extensions (test, request-response)

**Analog:** `tests/test_hypothesise.py::_handler` (fake-OpenAI `httpx.MockTransport`) + `tests/test_kb_analyze.py` (seed corpus, `_NO_KB_PROMPT_HASH` at line 64, citability flag `_KB_CITE_ID` at 58).

- **C1/coexistence:** seed dsserrors case from `hartford_deny_slice.log`, assemble prompt, assert MCM `[evt:]` lines present AND `denial_event_id ∈ prompted_ids` (valid citation); assert MCM + `--kb` coexist independently.
- **C2 determinism proof (load-bearing):** fake `InferenceClient` returns a schema-valid `HypothesisSet` whose narrative says a WRONG figure (e.g. `"99%"`) while citing the real `denial_event_id`; assert the spliced fact block contains the analyser's verbatim `value_pct` and NOT `99%`; run assembly twice → byte-identical block. Mirror `_prompt_hash` usage.
- **C3:** assert `mcm_facts.md` contains no digit that is a figure (fragment holds no numbers).
- **C5:** re-run `test_assemble_no_kb_is_byte_identical_baseline` (must stay `ef5b76801235d179`) + add a symmetric no-MCM hash assertion (the KB seed corpus is genericlog-only → `analyse_mcm` returns `()` → strip to nothing).

## Shared Patterns

### Sanitisation of untrusted log text
**Source:** `hypothesise.py:73` (`sanitise(chunk)`), `render._util.sanitise`.
**Apply to:** every log-derived value entering the MCM fact block (`row.key`, `flag.message`).
```python
joined = "\n\n".join(sanitise(chunk) for chunk in kb_context)
```

### Residue-free sentinel strip = byte-identical-when-empty
**Source:** `hypothesise.py:55–58, 71–72`.
**Apply to:** `_apply_mcm_block`. The block regex captures through the end-marker's trailing `\n`; `.sub("", template)` when empty leaves pre-change bytes unchanged. Guarded by `_NO_KB_PROMPT_HASH` (test_kb_analyze.py:64).

### Package-data prompt loading (CLI-02)
**Source:** `hypothesise.py:107–113` (`_load_triage_template`).
**Apply to:** `_load_mcm_fragment` — same `importlib.resources.files(_PROMPT_PACKAGE).joinpath(...).read_text(encoding="utf-8")` idiom.

### `prompted_ids` = the citation gate's allowed set
**Source:** `hypothesise.py:231` (`set(event_ids)`), `_row_citations_valid` (372–374), `_all_cited_within` (377+).
**Apply to:** MCM ids are unioned in (citable); KB ids are NOT (non-citable) — the polarity inversion is the whole phase.

### Frozen ground-truth eval case
**Source:** `eval/cases/memory-watermark-cascade/truth.yaml:1–2` header + schema.
**Apply to:** the new `mcm-denial/truth.yaml`.

## No Analog Found

None. Every file has a strong in-repo analog; Phase 11 writes almost no new mechanism (RESEARCH "Key insight"). The only genuinely new artefacts are `mcm_facts.md` (patterned on triage.md's KB block) and `render_mcm_facts` (patterned on mcm_report.py formatting + sanitise) — both role-matched, not novel.

## Metadata

**Analog search scope:** `src/sift/pipeline/`, `src/sift/prompts/`, `src/sift/cli.py`, `src/sift/eval/`, `eval/cases/`, `tests/`.
**Files scanned:** hypothesise.py, triage.md, cli.py (analyze+mcm), eval/runner.py, memory-watermark-cascade/truth.yaml, test_kb_analyze.py, config.py.
**Pattern extraction date:** 2026-07-19
