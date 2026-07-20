---
phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case
plan: 04
subsystem: pipeline
tags: [perfmon, facts, prompt, citation, anti-hallucination, determinism]
requires:
  - "render_perfmon_facts(analysis) -> (block, citable_ids) — pipeline/perfmon_facts.py (14-03)"
  - "prompts/triage.md PERFMON_BLOCK sentinels + <<PERFMON_FACTS>> slot (14-03)"
  - "_apply_mcm_block / _MCM_BLOCK_RE / _MCM_MARKER_RE — the verbatim analog mirrored here"
provides:
  - "_apply_perfmon_block + _PERFMON_SLOT/_PERFMON_BLOCK_RE/_PERFMON_MARKER_RE — remove-whole-block-when-absent perfmon splice"
  - "_assemble perfmon_block kwarg: splices after MCM, unions printed ids into prompted_ids (perfmon facts citable)"
  - "hypothesise() pre-generation perfmon build reusing events + mcm_analysis (single decompress pass)"
affects:
  - "14-05: consumes the now-citable perfmon injection at the hypothesise() chokepoint for the golden truth.yaml eval case (PERF-08)"
tech-stack:
  added: []
  patterns:
    - "second citable fact block mirroring the MCM splice verbatim (independent sentinel, remove-whole-block strip, prompted_ids union)"
key-files:
  created: []
  modified:
    - src/sift/pipeline/hypothesise.py
    - tests/test_perfmon_analyze.py
    - tests/test_eval_cases.py
decisions:
  - "D-01: _apply_perfmon_block mirrors _apply_mcm_block verbatim; spliced AFTER the MCM apply (order KB -> MCM -> perfmon), stripped independently"
  - "D-05/PERF-07: _assemble unions the perfmon block's printed [evt:] ids into prompted_ids (set(event_ids) | mcm_ids | perfmon_ids) — the one-line inversion making perfmon facts citable"
  - "D-02: NEITHER + MCM-ONLY assembled-prompt hashes frozen to pre-perfmon-phase baselines; block-stripping restores them, NOT constant rebaselining"
  - "single-decompress: hypothesise() calls store.query_events() ONCE and computes mcm_analysis ONCE, reused by render_mcm_facts AND analyse_perfmon (no third pass)"
metrics:
  duration: ~40m
  completed: 2026-07-20
status: complete
---

# Phase 14 Plan 04: Perfmon Fact Splice + prompted_ids Union Summary

Splices the deterministic perfmon fact block into the triage prompt at the same
pre-generation chokepoint as MCM and unions its printed `[evt:]` ids into
`prompted_ids` — the one-line inversion (`| perfmon_ids`) that turns perfmon
figures into citable evidence with `cited ⊆ prompted ⊆ store` preserved. Delivers
PERF-07. The two Wave-1 RED byte-identity baselines are restored by block-stripping
(not constant rebaselining), and four-combination byte-identity, anti-hallucination
and citability tests lock the strictly-additive contract.

## What was built

**Task 1 — `_apply_perfmon_block` + `prompted_ids` union + pre-generation build**
- `hypothesise.py`: added `_PERFMON_SLOT`, `_PERFMON_BLOCK_RE`, `_PERFMON_MARKER_RE`
  and `_apply_perfmon_block`, mirroring the MCM trio verbatim (MCM→PERFMON) with
  identical remove-whole-block-when-absent semantics and trailing-newline capture.
- `_assemble`: new `perfmon_block: tuple[str, set[str]] | None` kwarg; the block is
  spliced AFTER the MCM apply (reading order KB → MCM → perfmon) and its printed ids
  are unioned into `prompted_ids` (`set(event_ids) | mcm_ids | perfmon_ids`).
- `hypothesise()`: `store.query_events()` is decompressed ONCE into a local, and
  `analyse_mcm(...)` computed once — reused by both `render_mcm_facts(mcm_analysis)`
  and `render_perfmon_facts(analyse_perfmon(mcm_analysis, events))`. No third pass.
  No CLI change — perfmon is built internally at the chokepoint the eval harness
  (14-05) also exercises.
- Restores the two Wave-1 RED baselines: `_apply_perfmon_block` removes the whole
  PERFMON sentinel block for a no-perfmon prompt, returning the original bytes and
  the pre-sentinel hash `ef5b76801235d179` (NOT the sentinel-polluted
  `72006ea95082e12a`).

**Task 2 — Analyze integration tests (`tests/test_perfmon_analyze.py`)**
- `test_four_combination_byte_identity` (D-02): assembles neither / MCM-only /
  perfmon-only / both; asserts the NEITHER (`8c4341e77deee439`) and MCM-ONLY
  (`0e49cb2cbf6ebb27`) hashes equal frozen pre-phase constants (source assertion,
  not merely equal to each other), that adding a block perturbs the prompt, and that
  all four combos are distinct — each sentinel stripped independently so perfmon
  presence never perturbs the no-data or MCM-only prompts.
- `test_model_cannot_alter_perfmon_figures` (T-14-07): drives the fake client to
  echo a WRONG figure; asserts the verbatim `render_perfmon_facts` block is in the
  prompt and the fabricated figure is not (prompt built before the reply).
- `test_perfmon_id_citable_and_fabricated_flagged` (D-05/PERF-07): a printed perfmon
  `[evt:]` id is in `prompted_ids` and cites cleanly (`citations_valid True`), while
  a fabricated perfmon id is FLAGGED (`citations_valid False`), both at the assemble
  level and end-to-end through `hypothesise()`.

## Verification

- `uv run pytest tests/test_perfmon_analyze.py -q` → **4 passed**.
- `uv run pytest tests/test_kb_analyze.py -q` → the two restored byte-identity
  baselines **green** (`ef5b76801235d179`).
- Full gate: `uv run pytest` → **656 passed, 8 deselected**; `uv run ruff check` →
  **All checks passed**; `uv run pyright` → **0 errors, 0 warnings**.
- **TDD fail-fast (counterfactual RED proof):** dropping the `| perfmon_ids` union
  made `test_perfmon_id_citable_and_fabricated_flagged` RED; neutering
  `_apply_perfmon_block`'s strip made `test_four_combination_byte_identity` AND
  `test_kb_analyze::test_assemble_no_kb_is_byte_identical_baseline` RED. Both
  restored byte-identically via `git checkout` (Task 1 already committed); 13 passed
  after restore.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 1 — Test correction] `test_eval_cases::test_mcm_denial_citation_validity_is_mcm_sensitive`**
- **Found during:** Task 1 full-suite gate (the Phase 11 MCM-sensitivity guard turned red).
- **Issue:** The guard stripped only `render_mcm_facts` and asserted the denial
  citation is then flagged. Wiring perfmon means `analyse_perfmon` now emits a D-08
  zero-sample disclosure group whose header cites the same denial boundary events,
  so the denial id is independently citable via the perfmon block — stripping only
  MCM no longer flags it. Confirmed empirically: for the mcm-denial case
  `perfmon_ids == {denial_id, window_start_id}` (both dsserrors boundary events).
- **Fix:** the guard now strips BOTH `render_mcm_facts` and `render_perfmon_facts`;
  the docstring records that perfmon covers the same denial boundary id since Phase
  14, so both injection sources must be removed to demonstrate the non-vacuous gate.
  This is a legitimate, expected consequence of the splice, not a regression.
- **Files modified:** tests/test_eval_cases.py
- **Commit:** e5a57e9

**2. [pyright] Explicit `set[str]()` on the union fallbacks**
- The multi-line `prompted_ids` union inferred `set[str | Unknown]`; typed the empty
  fallbacks as `set[str]()` (project pyright convention), 0 errors.

### Opportunistic (IN-03)
Skipped — the redundant `re.DOTALL` on the MCM marker RE and the cosmetic
double-newline at the MCM splice were left untouched to keep the diff minimal and
avoid any risk to the frozen MCM byte-identity baselines. Non-blocking, as noted.

## Threat surface

- T-14-07 (model fabricating a perfmon figure/citation): mitigated — figures built
  pre-generation (`analyse_perfmon` verbatim), the `cited ⊆ prompted` gate flags any
  id the block did not print; covered by the anti-hallucination + fabricated-id tests.
- T-14-08 (prompt-drift regressing the shipped no-data baseline): mitigated —
  independent sentinel removal + the four-combination byte-identity guard freezing
  the NEITHER and MCM-ONLY hashes.
- No new trust boundaries beyond the plan's threat model.

## Requirement status

**PERF-07 — COMPLETE.** Perfmon figures are injected as CITED evidence with
`cited ⊆ prompted ⊆ store` preserved; the fact block is built before generation so a
hallucinating model cannot alter or invent a number; the no-perfmon prompt is
byte-identical to today's across all four presence combos. **PERF-08 remains OPEN**
(the golden `truth.yaml` eval case is 14-05).

## Known Stubs

None. The `<<PERFMON_FACTS>>` slot in `triage.md` is now wired via
`_apply_perfmon_block`; no residual placeholder remains.

## Commits

- `e5a57e9` feat(14-04): splice perfmon fact block + union ids into prompted_ids
- `0877fd0` test(14-04): analyze-path perfmon byte-identity, anti-hallucination, citability

## Self-Check: PASSED
14-04-SUMMARY.md present; both commits (e5a57e9, 0877fd0) in history.
