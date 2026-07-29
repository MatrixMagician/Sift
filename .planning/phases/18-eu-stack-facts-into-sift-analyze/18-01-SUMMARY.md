---
phase: 18-eu-stack-facts-into-sift-analyze
plan: 01
subsystem: analysis
tags: [eu-stack, prompt-injection, citation-gate, hypothesise, fact-renderer]

requires:
  - phase: 17-multi-dump-progression-sift-eustack-report-csv
    provides: analyse_eustack_bundle / EustackBundle (last-dump analysis + progression), sift eustack report
provides:
  - src/sift/pipeline/eustack_facts.py — render_eustack_facts(bundle, events) leaf-module fact renderer (role-composition grouping only; the other three Phase-16 groupings and the capped per-signature listing are Plan 18-02's job)
  - src/sift/prompts/eustack_facts.md — versioned, zero-digit template
  - Fourth independently-strippable sentinel block (EUSTACK_BLOCK_START/END) in triage.md
  - hypothesise() eustack_rules_path / eustack_thresholds kwargs, eustack_block splice + prompted_ids union
  - cli.py analyze command threading config.eustack.rules_path / config.eustack.thresholds
  - Byte-identity, anti-hallucination and zero-authored-digit test coverage for the new block
affects: [18-02-eu-stack-facts-remaining-groupings, 18-03-eu-stack-facts-headroom-and-progression, 19-eus-11-ranking-exclusion]

tech-stack:
  added: []
  patterns:
    - "Fourth instance of the fact-injection pattern (mcm_facts -> perfmon_facts -> eustack_facts): leaf module + versioned zero-digit template + independently-strippable sentinel pair in triage.md + prompted_ids union in hypothesise()."
    - "Aggregate-to-citable-event_id resolution: re-derive signature->event_id from store.query_events() via signature_of(event.raw) at render time (never widen the frozen Phase 15-17 models); union contributing signatures' ids first, then take the lowest K (D-17)."

key-files:
  created:
    - src/sift/pipeline/eustack_facts.py
    - src/sift/prompts/eustack_facts.md
    - tests/test_eustack_facts.py
    - tests/test_eustack_analyze.py
  modified:
    - src/sift/pipeline/hypothesise.py
    - src/sift/prompts/triage.md
    - src/sift/cli.py

key-decisions:
  - "D-01/D-02/D-17 exemplar sampling: a population figure cites the lowest 3 event_ids (sort order) from the UNION of all contributing signatures' event pools — never per-signature triples concatenated — keeping the '(N of M cited as exemplars)' sentence honest for the aggregate's own M."
  - "Emptiness gate is bundle.analysis.total_threads == 0, never bundle.saturation.flags being empty — a healthy zero-flag capture must still render a useful block."
  - "render_eustack_facts(bundle, events) deliberately takes a second events argument, diverging from the sibling render_mcm_facts(analysis)/render_perfmon_facts(analysis) signature, because no frozen Phase 15-17 model carries event_ids."
  - "D-18 minimal 5-combination byte-identity subset (not the full 2x2x2 matrix): NEITHER/MCM-ONLY/PERFMON-ONLY unchanged, EUSTACK-ONLY/ALL-THREE new-and-distinct within one eu-stack-carrying store."

patterns-established:
  - "Store-provenance: measuring a NEW frozen prompt-hash constant against the pre-phase template via `git show HEAD~N:<file>` written to a temp path, then cross-checked against the post-phase code with the new block absent, to prove the constant is a genuine pre-phase baseline rather than a post-hoc echo."

requirements-completed: [EUS-10]

coverage:
  - id: D1
    description: "render_eustack_facts(bundle, events) leaf module renders the role-composition grouping, returning (text, citable_ids); every printed id resolves to a real store event_id and is unioned into prompted_ids"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_analyze.py#test_eustack_block_injected_and_ids_citable"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_id_set_equals_printed_evt_tokens"
        status: pass
    human_judgment: false
  - id: D2
    description: "A case with no eu-stack data reproduces the pre-phase prompt byte-for-byte across NEITHER/MCM-ONLY/PERFMON-ONLY; adding eu-stack data never perturbs the other three fact blocks"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_analyze.py#test_no_eustack_data_byte_identical_to_baseline"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_analyze.py#test_five_combination_byte_identity"
        status: pass
    human_judgment: false
  - id: D3
    description: "eustack_facts.md carries zero authored digits; a model-planted wrong figure never reaches the assembled prompt; the default packaged-rules/thresholds path works with no explicit override (eval-harness parity)"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_fragment_holds_no_authored_number"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_analyze.py#test_model_cannot_alter_eustack_figures"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_analyze.py#test_eval_path_parity_default_eustack_config"
        status: pass
    human_judgment: false

duration: ~45min
completed: 2026-07-26
status: complete
---

# Phase 18 Plan 1: End-to-End Eu-Stack Role-Composition Facts Summary

**`render_eustack_facts` splices a citable role-composition block into `sift analyze`'s triage prompt, byte-identical when no eu-stack data is present, with both fail-first gates demonstrated red-then-green.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-07-26T14:58:47Z
- **Tasks:** 3
- **Files modified:** 7 (4 new: `eustack_facts.py`, `eustack_facts.md`, `test_eustack_facts.py`, `test_eustack_analyze.py`; 3 modified: `hypothesise.py`, `triage.md`, `cli.py`)

## Accomplishments

- New leaf module `src/sift/pipeline/eustack_facts.py` renders the eu-stack role-composition grouping: `render_eustack_facts(bundle: EustackBundle, events: list[Event]) -> tuple[str, set[str]]`, re-deriving a `signature -> event_id` map from `events` via `signature_of(event.raw)` (never `event.message`), unioning contributing signatures' ids before sampling the lowest 3 (D-17), and returning `("", set())` only when `bundle.analysis.total_threads == 0`.
- Fourth independently-strippable sentinel pair (`EUSTACK_BLOCK_START`/`EUSTACK_BLOCK_END`) landed in `triage.md`, `_apply_eustack_block` in `hypothesise.py`, and `eustack_block` threaded through `_assemble`'s `prompted_ids` union — mirroring the MCM/perfmon pattern exactly.
- `hypothesise()` gained `eustack_rules_path`/`eustack_thresholds` keyword-only parameters, computed at the same pre-generation chokepoint as MCM/perfmon and reusing the single `store.query_events()` decompression pass; `cli.py`'s `analyze` command threads `config.eustack.rules_path`/`config.eustack.thresholds`.
- Five-combination byte-identity gate (D-18) proves the fourth block never perturbs the other three: NEITHER/MCM-ONLY/PERFMON-ONLY reproduce three frozen pre-phase hash constants exactly; EUSTACK-ONLY and ALL-THREE are new and distinct within one eu-stack-carrying store.
- Anti-hallucination and zero-authored-digit gates: a planted wrong figure never reaches the assembled prompt; `eustack_facts.md` carries zero ASCII digits; the packaged-default rules/thresholds path (no explicit override) still injects the block, proving eval-harness parity.

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end eu-stack role composition reaches the triage prompt as cited evidence** - `57283b1` (feat)
2. **Task 2: Byte-identity gate — the fourth block strips residue-free** - `c05dc7f` (test)
3. **Task 3: Anti-hallucination and zero-authored-digit gates** - `6c126f9` (test)

_Task 1 was `type="tracer"`: committed as production-quality (real `<verify>`, real citation accounting), then the tracer-verify gate (re-running its `<verify>` end-to-end) passed under auto mode (`workflow.auto_advance: true`), so execution proceeded straight to Task 2 without a checkpoint._

## Files Created/Modified
- `src/sift/pipeline/eustack_facts.py` - New leaf module: `render_eustack_facts`, `_signature_event_ids`, `_events_by_dump_in_order`, `_union_exemplars`, `_cite_prefix`, `_load_eustack_fragment`
- `src/sift/prompts/eustack_facts.md` - New versioned template, zero authored digits, verbatim-copied prompt-injection framing sentence
- `src/sift/pipeline/hypothesise.py` - `_EUSTACK_SLOT`/`_EUSTACK_BLOCK_RE`/`_EUSTACK_MARKER_RE`/`_apply_eustack_block`; `eustack_block` param on `_assemble`; `eustack_rules_path`/`eustack_thresholds` params on `hypothesise()`
- `src/sift/prompts/triage.md` - Fourth sentinel pair appended after `PERFMON_BLOCK_END`, character-for-character matching the MCM/perfmon marker/newline shape
- `src/sift/cli.py` - `analyze` command's `hypothesise(...)` call gains `eustack_rules_path=config.eustack.rules_path`, `eustack_thresholds=config.eustack.thresholds`
- `tests/test_eustack_facts.py` - New module: `test_fragment_holds_no_authored_number`, `test_id_set_equals_printed_evt_tokens`
- `tests/test_eustack_analyze.py` - New module: `test_eustack_block_injected_and_ids_citable`, `test_no_eustack_data_byte_identical_to_baseline`, `test_five_combination_byte_identity`, `test_model_cannot_alter_eustack_figures`, `test_eval_path_parity_default_eustack_config`

## Decisions Made

- **`_PERFMON_ONLY_PROMPT_HASH` measurement (D-18's missing baseline):** measured as `e3dc94ae1b32cd90` by loading the perfmon-denial case, assembling the prompt with `mcm_block=None` and the real `render_perfmon_facts` block, against the **pre-Task-1** `triage.md` obtained via `git show HEAD~2:src/sift/prompts/triage.md` (the commit immediately before Task 1 landed — confirmed identical to `HEAD~1` for that file, i.e. Task 1 was the only phase-time edit to it) written to a scratch path, and hashed with `hypothesise._prompt_hash`. Cross-checked: re-running the identical assembly against the **current** (post-Task-1) `triage.md` with `eustack_block=None` reproduced the exact same hash (`e3dc94ae1b32cd90`), confirming the fourth sentinel block's residue-free strip.
- Emptiness gate for `render_eustack_facts` is `bundle.analysis.total_threads == 0`, never `bundle.saturation.flags` — a healthy zero-flag capture ("nothing is flagged" is itself a finding) must still render.
- `_MODEL_WRONG_FIGURE = "9,999,999 threads idle-parked"` — an eu-stack-shaped figure orders of magnitude beyond any real thread count, mirroring the MCM/perfmon analogs' own choice of an implausible planted value.
- Task 1's simpler scope (role-composition grouping only, per the plan's explicit "no other grouping, no cap, no progression, no delta") deferred `_MAX_SIGNATURES`, the per-signature listing, and the other three Phase-16 groupings (pool occupancy, lock-site convergence, external-wait concentration) to Plan 18-02, exactly as the plan's `<artifacts_this_phase_produces>` section documents them as landing there.

## Deviations from Plan

None - plan executed exactly as written. The two fail-first demonstrations (Task 2 marker perturbation, Task 3 planted digit) were run and reverted per the plan's own instructions, not deviations.

### Fail-first demonstration outputs (recorded per plan's `<output>` instruction)

**Task 2 — marker perturbation (D-12/Pitfall 5):** appending a stray blank line after the `EUSTACK_BLOCK_END` marker line in `triage.md` (a residual the `_EUSTACK_BLOCK_RE`/`_EUSTACK_MARKER_RE` regexes do not consume, since they match only through one `-->\n`) flipped `test_no_eustack_data_byte_identical_to_baseline` red:
```
E       AssertionError: assert 'f43f1936504c5b98' == '8c4341e77deee439'
E         - 8c4341e77deee439
E         + f43f1936504c5b98
```
Reverted via exact file restore (confirmed byte-identical to the committed HEAD state via `diff`); the test passed green again.

**Task 3 — planted digit (D-16):** replacing "D-one" with "D-1" in `eustack_facts.md`'s header comment flipped `test_fragment_holds_no_authored_number` red:
```
E       AssertionError: eustack_facts.md holds an authored figure: ['1']
E       assert ['1'] == []
```
Reverted via exact file restore (confirmed byte-identical via `diff`); the test passed green again.

### `render_eustack_facts` signature as shipped

```python
def render_eustack_facts(
    bundle: EustackBundle, events: list[Event]
) -> tuple[str, set[str]]:
```

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 18-02 can build directly on the shipped leaf module: add `_MAX_SIGNATURES = 8`, the per-signature listing, and the remaining three Phase-16 groupings (pool occupancy, lock-site convergence, external-wait concentration), reusing `_signature_event_ids`/`_events_by_dump_in_order`/`_union_exemplars` unchanged.
- Plan 18-03 can rely on the frozen `_NEITHER_PROMPT_HASH`/`_MCM_ONLY_PROMPT_HASH`/`_PERFMON_ONLY_PROMPT_HASH` constants in `tests/test_eustack_analyze.py` as an established baseline for the combined fact-block headroom measurement (D-14).
- No blockers. Full quality gate green: `uv run ruff check` clean, `uv run pyright` 32 errors (unchanged pre-existing baseline in `test_cli_eustack.py`/`test_eustack_progression.py`/`test_eustack_report.py`, none introduced by this plan), `uv run pytest` 786 passed (up from 779 pre-phase).

## Self-Check: PASSED

All claimed files found on disk (`src/sift/pipeline/eustack_facts.py`, `src/sift/prompts/eustack_facts.md`, `tests/test_eustack_facts.py`, `tests/test_eustack_analyze.py`, this SUMMARY.md); all three task commits (`57283b1`, `c05dc7f`, `6c126f9`) found in `git log`.

---
*Phase: 18-eu-stack-facts-into-sift-analyze*
*Completed: 2026-07-26*
