---
phase: 11-mcm-facts-into-sift-analyze-golden-eval-case
plan: 01
subsystem: pipeline
tags: [mcm, prompts, rendering, citation-provenance, determinism]
requires:
  - "pipeline/mcm.py::analyse_mcm (McmAnalysis model tree, D-11 value_pct)"
  - "render/_util.py::sanitise (V5 control-char strip)"
provides:
  - "pipeline/mcm_facts.py::render_mcm_facts(analysis) -> (block_text, citable_ids)"
  - "pipeline/mcm_facts.py::_load_mcm_fragment()"
  - "prompts/mcm_facts.md (versioned fragment, labels/prose + single placeholder)"
affects:
  - "Wave 2 (11-02): hypothesise splices render_mcm_facts output + unions the ids into prompted_ids"
tech-stack:
  added: []
  patterns:
    - "importlib.resources package-data load (mirrors _load_triage_template)"
    - "sanitise every log-derived value before interpolation (mirrors _apply_kb_block)"
    - "id set == printed [evt:] tokens (exemplar contract)"
key-files:
  created:
    - src/sift/prompts/mcm_facts.md
    - src/sift/pipeline/mcm_facts.py
    - tests/test_mcm_facts.py
  modified: []
decisions:
  - "Attribution rows print + expose only row.event_ids[0] (one [evt:] token per row), keeping the returned id set exactly the printed set — the exemplar-contract invariant overrides the RESEARCH sketch's looser ids.update(row.event_ids)."
  - "Fragment carries zero ASCII digits (including decision-ID numerals rewritten as words) so the strict C3 no-digit guard holds."
metrics:
  duration: "~20 min"
  completed: 2026-07-19
  tasks: 2
  files: 3
  commits: 4
status: complete
---

# Phase 11 Plan 01: MCM Fact Renderer + Versioned Fragment Summary

Deterministic, model-free `render_mcm_facts(analysis) -> (block_text, set[str])` plus
the versioned `prompts/mcm_facts.md` fragment: the byte-identical-on-re-run source of
truth that Wave 2 splices into the triage prompt as citable evidence, with every figure
read verbatim from `analyse_mcm` and every id it exposes being a token it actually printed.

## What was built

- **`src/sift/pipeline/mcm_facts.py`** — a pure leaf module. `render_mcm_facts` walks each
  `EpisodeAnalysis`: an episode-summary line citing `denial_event_id` (denial time +
  `window.label` AvailableMCM descent), the graded flags sorted critical→warn→info each
  surfacing `DiagnosticFlag.value_pct` (`:.1f%`, never re-derived — D-11), and the top-5
  attribution rows per dimension (`by_oid`/`by_source`/`by_sid` plain `[:5]`, already
  granted-desc sorted — D-19) rendering `granted_bytes / 1024**2` MB. Every log-derived
  value (`row.key`, `flag.message`, `window.label`, `denial_ts`) passes through
  `render._util.sanitise` first (T-11-01). Empty analysis → `("", set())`. `_load_mcm_fragment`
  mirrors `_load_triage_template` (importlib.resources package data).
- **`src/sift/prompts/mcm_facts.md`** — labels + prose framing the lines as *citable*
  evidence (opposite polarity to the KB block), plus a single `<<MCM_LINES>>` body
  placeholder. Holds no figure and no ASCII digit at all.
- **`tests/test_mcm_facts.py`** — 8 tests: analyser-figure surfacing, id-set == printed
  `[evt:]` tokens, top-5 slice in order, empty→`("",set())`, sanitise of hostile key/message,
  C3 no-digit fragment guard, render determinism (byte-identical + equal id sets), and an
  injection-directive sanitise proof with prose-framing survival.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Placeholder token duplicated inside the fragment comment**
- **Found during:** Task 1 (top-5 test failed: 10 source lines, not 5)
- **Issue:** the fragment's leading HTML comment literally contained `<<MCM_LINES>>`
  ("substituted for the `<<MCM_LINES>>` placeholder"), so `str.replace` substituted the
  rendered lines twice — once in the comment, once at the real slot — doubling every line and
  leaking a stray "placeholder" word. (KB avoids this because `_apply_kb_block` strips its
  marker comment via regex *before* the replace; the MCM fragment is emitted whole.)
- **Fix:** reworded the comment to reference the placeholder without the literal token.
- **Files modified:** src/sift/prompts/mcm_facts.md
- **Commit:** 5cdf1e3

**2. [Rule 3 - Blocking] Decision-ID numerals tripped the C3 no-digit guard**
- **Found during:** Task 2 (C3 guard found digits `0 6 2 0 0 2` from `MCM-06, D-20, CLI-02`)
- **Issue:** the fragment comment cited decision IDs whose numerals are ASCII digits — the
  strict no-digit guard (the preferred D-20 form) rejected them.
- **Fix:** rewrote the IDs as words ("D-twenty / CLI-two") so the template carries zero digits.
- **Files modified:** src/sift/prompts/mcm_facts.md
- **Commit:** 6d66d71

**Design note (not a deviation):** the RESEARCH renderer sketch unions `row.event_ids` (all
grant-line ids) into the returned set. The plan's own behaviour test and exemplar-contract
criterion require the id set to equal exactly the printed `[evt:]` tokens, so only
`row.event_ids[0]` (the one printed per row) is exposed. The strict invariant governs.

## Verification

- `uv run pytest tests/test_mcm_facts.py` — 8 passed.
- Full done-gate: `uv run ruff check` clean, `uv run pyright` 0 errors, `uv run pytest`
  523 passed / 8 deselected.

## Known Stubs

None. `render_mcm_facts` is fully wired to `analyse_mcm`'s real output; the fragment is the
final versioned text. Splicing into the triage prompt and extending `prompted_ids` is the
explicit scope of Wave 2 (11-02), not a stub.

## Self-Check: PASSED

All created files exist on disk; all per-task commits (1b0257c, 5cdf1e3, 6d66d71)
present in git history; full done-gate green (ruff clean, pyright 0, pytest 523 passed).
