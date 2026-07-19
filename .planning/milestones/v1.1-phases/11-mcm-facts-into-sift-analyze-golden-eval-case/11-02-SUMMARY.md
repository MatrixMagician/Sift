---
phase: 11-mcm-facts-into-sift-analyze-golden-eval-case
plan: 02
subsystem: pipeline
tags: [mcm, prompts, hypothesise, citation-provenance, anti-hallucination, determinism]
requires:
  - "pipeline/mcm_facts.py::render_mcm_facts(analysis) -> (block_text, citable_ids) (11-01)"
  - "pipeline/mcm.py::analyse_mcm(events, thresholds)"
  - "config.py::McmThresholdsConfig (default-constructible)"
  - "store.py::CaseStore.query_events"
provides:
  - "pipeline/hypothesise.py::_apply_mcm_block(template, fact_block) -> str (residue-free strip / slot-fill)"
  - "pipeline/hypothesise.py::_assemble(mcm_block=...) — unions printed [evt:] ids into prompted_ids"
  - "pipeline/hypothesise.py::hypothesise(mcm_thresholds=...) — builds MCM facts at the chokepoint"
  - "prompts/triage.md — <!-- MCM_BLOCK_START/END --> sentinel region around <<MCM_FACTS>>"
affects:
  - "Wave 3 (11-03): the golden eval case exercises MCM injection for free (hypothesise chokepoint)"
tech-stack:
  added: []
  patterns:
    - "sentinel-delimited prompt block mirroring _apply_kb_block (DOTALL regex, trailing-\\n capture)"
    - "citable-id union at _assemble — inverse polarity to the non-citable KB path"
    - "deterministic facts built pre-generation; model reply never feeds the figures"
key-files:
  created:
    - tests/test_mcm_analyze.py
  modified:
    - src/sift/prompts/triage.md
    - src/sift/pipeline/hypothesise.py
    - tests/test_kb_analyze.py
decisions:
  - "MCM block placed just below the `Evidence:` marker (MCM facts ARE citable evidence) — opposite placement/polarity to the KB block above it."
  - "Task 1 wires _assemble to strip the MCM block unconditionally so the pre-phase baseline hash stays intact; Task 2 generalises the same splice to the mcm_block param + prompted_ids union."
  - "hypothesise builds facts via analyse_mcm(store.query_events(), mcm_thresholds or McmThresholdsConfig()) at module-top imports — no circular import appeared, so no lazy import needed."
metrics:
  duration: "~25 min"
  completed: 2026-07-19
  tasks: 3
  files: 4
  commits: 6
status: complete
---

# Phase 11 Plan 02: MCM Facts Threaded Into `sift analyze` Summary

The deterministic MCM fact block (Plan 01's `render_mcm_facts`) is now spliced into
the triage prompt inside `hypothesise` — the chokepoint both `cli.analyze` and
`eval/runner._run_pipeline` funnel through — as **citable** evidence: the ids the
renderer printed as `[evt:<id>]` tokens are unioned into `prompted_ids`, so a
hypothesis may validly cite an MCM denial event while `cited ⊆ prompted ⊆ store`
holds. Figures are a pure function of `analyse_mcm`, built before generation, so a
model echoing a mutated number cannot change the surfaced facts. With no MCM data
the assembled prompt is byte-identical to its pre-phase form (`_NO_KB_PROMPT_HASH`
unchanged).

## What was built

- **`src/sift/prompts/triage.md`** — an `<!-- MCM_BLOCK_START --> … <<MCM_FACTS>> …
  <!-- MCM_BLOCK_END -->` sentinel region placed directly below the `Evidence:`
  marker (MCM facts are citable evidence, the inverse placement of the KB block
  above). Newlines laid out so a residue-free strip returns the file to its
  pre-phase bytes.
- **`src/sift/pipeline/hypothesise.py`** — `_MCM_SLOT`, `_MCM_BLOCK_RE`,
  `_MCM_MARKER_RE` mirroring the KB shape (same DOTALL regexes, same trailing-`\n`
  capture) plus `_apply_mcm_block(template, fact_block)`: strip the whole block
  when falsy, else drop the markers and fill the slot. `_assemble` gained a
  `mcm_block: tuple[str, set[str]] | None` kwarg — it splices the text after the
  KB splice and unions **only the ids the renderer printed** into the returned
  `prompted_ids` (the load-bearing inversion vs KB). `hypothesise` gained a
  `mcm_thresholds` kwarg and builds `render_mcm_facts(analyse_mcm(store.query_events(),
  mcm_thresholds or McmThresholdsConfig()))` at the chokepoint, passing it down —
  so the eval harness (which calls `hypothesise` with no thresholds) injects MCM
  automatically.
- **`tests/test_mcm_analyze.py`** (new, 6 tests) — injection + denial-id citability,
  fabricated-id non-citability, eval-path parity (default thresholds still inject),
  `test_model_cannot_alter_mcm_figures` (analyser block verbatim in the prompt, the
  model's wrong figure absent), MCM determinism (two assemblies byte-identical), and
  `test_mcm_and_kb_coexist` (MCM citable + KB threaded-but-non-citable in one run).
- **`tests/test_kb_analyze.py`** — extended with `_apply_mcm_block` unit coverage and
  a symmetric no-MCM byte-identity guard; the existing baseline test and
  `_NO_KB_PROMPT_HASH = ef5b76801235d179` are unchanged.

## Deviations from Plan

None — plan executed as written. The Task-1/Task-2 split of the `_assemble` splice
(strip-only in Task 1, then param + union in Task 2) is the sequencing the plan's own
byte-identity guard requires, not a deviation.

## Threat mitigations verified

- **T-11-02 (figure tampering):** `test_model_cannot_alter_mcm_figures` — the fact
  block spliced into the prompt equals `render_mcm_facts` verbatim, built before the
  generation call; the model's mutated figure never enters the prompt.
- **T-11-03 (fabricated citation):** `test_fabricated_id_not_citable` — only printed
  `[evt:]` ids enter `prompted_ids`; the existing `_citation_gate` flags any id
  outside the set.
- **T-11-04 (prompt injection via MCM text):** values already `sanitise`d in the Plan
  01 renderer; `_apply_mcm_block` only splices, never re-interpolates.

## Verification

- `uv run pytest tests/test_kb_analyze.py -x` — no-MCM byte-identity, baseline hash intact.
- `uv run pytest tests/test_mcm_analyze.py tests/test_hypothesise.py -x` — injection,
  citability, determinism proof, coexistence.
- Full done-gate: `uv run ruff check` clean, `uv run pyright` 0 errors, `uv run pytest`
  **531 passed / 8 deselected**.

## Known Stubs

None. MCM facts are fully wired through `hypothesise` for both `cli.analyze` and the
eval path. The golden regression case is Wave 3 (11-03) scope, not a stub.

## Self-Check: PASSED

All modified/created files exist on disk; all six per-task commits
(c5b3663, bb22934, 7ab9aed, bf11b81, 36e0aa4, plus this docs commit) are in git
history; full done-gate green.
