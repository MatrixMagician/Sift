---
phase: 18-eu-stack-facts-into-sift-analyze
plan: 03
subsystem: analysis
tags: [eu-stack, progression, citation-gate, hypothesise, fact-renderer, prompt-injection, adr]

requires:
  - phase: 18-eu-stack-facts-into-sift-analyze
    provides: "Plan 18-01/18-02's render_eustack_facts (role composition, all four Phase 16 groupings, capped signature listing, _union_exemplars/_cite_prefix/_sampling_sentence helpers, the eustack_facts.md template, and the hypothesise() splice)"
provides:
  - "render_eustack_facts now renders multi-dump progression: verified-order dump sequence plus capped, cited per-signature population deltas for changed signatures, OR an explicit suppression statement and no delta figure at all when the order is unverified or fewer than two dumps are present (D-09/D-10/D-11)"
  - "test_control_chars_sanitised (V5) and test_combined_fact_block_headroom_measured (D-14) close the phase's remaining two verification rows"
  - "docs/decisions/0017-eustack-aggregate-citation-sampling.md — ADR recording D-01/D-02/D-03/D-17"
affects: [19-eus-11-ranking-exclusion]

tech-stack:
  added: []
  patterns:
    - "Progression suppression predicate reads bundle.progression.order_basis directly against the shipped ORDER_BASIS_FILENAME constant, never re-deriving resolve_dump_order's decision — the same read-the-resolved-fact discipline every other grouping in this module already follows."
    - "A single suppression-branch (order unverified OR <2 dumps) shares one sentence naming both possible reasons, rather than two near-duplicate branches, so no delta figure is ever printed without the fact being disclosed."

key-files:
  created:
    - docs/decisions/0017-eustack-aggregate-citation-sampling.md
  modified:
    - src/sift/pipeline/eustack_facts.py
    - src/sift/prompts/eustack_facts.md
    - tests/test_eustack_facts.py
    - tests/test_eustack_analyze.py

key-decisions:
  - "Suppression predicate merges D-10 (unverified filename-fallback order) and the degenerate <2-dump case into ONE branch with ONE sentence naming both reasons ('either the dump order could not be verified, or fewer than two dumps were available') — avoids a second near-duplicate message while staying truthful for both triggers, per the plan's own literal instruction to treat both under one _suppression_statement()."
  - "Population figure for a verified-branch delta row is read from the SAME per-dump signature-id map _union_exemplars already resolves against (the most-recent-dump-where-present rule), not from SignatureProgression.counts[-1] — the latter is 0 for a vanished signature even though its exemplars (and true population) come from an earlier dump, so counts[-1] would silently misreport the sampling sentence for exactly the row where it matters most."
  - "D-14 measured combined MCM+perfmon+eu-stack fact-block size directly (not estimated): 18,115 combined characters -> ~4,528 estimated tokens (len//4 heuristic) against a 6,000-token frozen regression ceiling, comfortably under the 7,168-token excerpt budget PromptBudget.fit reserves (ctx_fallback=8192 minus reserve_out=1024). Recorded finding: does NOT overrun the excerpt budget on this exact combined case — ~2,640 tokens of headroom remain for cluster excerpts before the assembled prompt would exceed the 8192 fallback context."
  - "ADR 0017 is a pure recording task (per its own frontmatter note) — D-01/D-02/D-03/D-17 were already locked in 18-CONTEXT.md before this plan started; the ADR restates them beside ADRs 0015/0016 for rationale continuity, changing no behaviour."

requirements-completed: [EUS-10]

coverage:
  - id: D1
    description: "A multi-dump case with a verified (timestamp-ordered) dump order renders the resolved dump sequence plus capped, cited per-signature population deltas for changed signatures only, alongside the verbatim scope note"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_deltas_rendered_on_verified_order"
        status: pass
    human_judgment: false
  - id: D2
    description: "A multi-dump case whose ordering basis falls back to sorted file names (the real reference capture's own shape, D-11) renders last-dump state only, an explicit suppression statement, and NO delta figure anywhere — proven both at the renderer level and through the assembled sift analyze prompt"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_deltas_suppressed_on_unverified_order"
        status: pass
      - kind: integration
        ref: "tests/test_eustack_analyze.py#test_eustack_suppression_reaches_prompt_on_real_shaped_fixture"
        status: pass
    human_judgment: false
  - id: D3
    description: "No emitted string (verified or suppressed branch) asserts per-thread continuity, lock possession, or a wait-for conclusion"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_no_continuity_or_ownership_claim_in_emitted_strings"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every rules-derived/frame-derived string interpolated into the block is control-character sanitised while the template's untrusted-data framing sentence survives; the combined MCM+perfmon+eu-stack fact-block size is measured against the excerpt budget and bounded by a frozen regression ceiling"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_control_chars_sanitised"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_combined_fact_block_headroom_measured"
        status: pass
    human_judgment: false
  - id: D5
    description: "ADR 0017 records the aggregate-citation sampling decision (D-01/D-02/D-03/D-17) and its rejected alternatives beside ADRs 0015 and 0016"
    requirement: "EUS-10"
    verification:
      - kind: other
        ref: "test -f docs/decisions/0017-eustack-aggregate-citation-sampling.md && grep -c 'D-01\\|D-02\\|D-03\\|D-17' docs/decisions/0017-eustack-aggregate-citation-sampling.md"
        status: pass
    human_judgment: false

duration: ~70min
completed: 2026-07-26
status: complete
---

# Phase 18 Plan 3: Multi-Dump Progression, Sanitisation Gate and D-14 Measured Headroom Summary

**Multi-dump signature-population deltas render only when the dump order is verified by timestamp; on the real reference capture's own unverified-filename-fallback shape, the block states plainly that progression was suppressed and prints no delta figure anywhere — closing the phase with a measured (not estimated) combined fact-block headroom of ~4,528 tokens against the 7,168-token excerpt budget.**

## Performance

- **Duration:** ~70 min
- **Completed:** 2026-07-26T16:10:00Z
- **Tasks:** 3
- **Files modified:** 5 (1 new: `docs/decisions/0017-eustack-aggregate-citation-sampling.md`; 4 modified: `eustack_facts.py`, `eustack_facts.md`, `test_eustack_facts.py`, `test_eustack_analyze.py`)

## Accomplishments

- `_progression_lines`/`_suppression_statement` added to `render_eustack_facts`: on a verified (`ORDER_BASIS_TIMESTAMP`) multi-dump case, emits the resolved dump sequence (source file, timestamp, confidence, thread count per dump) followed by capped, cited population-change rows for CHANGED signatures only (`overall_delta != 0` or any non-zero `step_delta`), sliced at `_MAX_SIGNATURES = 8` with a drop-count statement when applicable, each row citing through the existing `_union_exemplars` most-recent-dump-where-present rule.
- **D-10/D-11, the highest-risk item in this phase:** when the resolved order basis is `ORDER_BASIS_FILENAME` (the D-02 sorted-filename fallback) OR fewer than two dumps are present, the block emits NO delta figure at all — only `bundle.progression.scope_note` verbatim, a single suppression sentence, and any `ordering_flags` as graded, direction-free lines. Proven as the PRIMARY path (not an edge case) against the real-shaped, header-timestamp-less `reference_capture_derivative.txt` fixture ingested twice under distinct filenames, both at the renderer level and through the fully assembled `sift analyze` prompt.
- V5 sanitisation gate (`test_control_chars_sanitised`) proves a control-char-laden rules-derived subsystem string and frame symbol are stripped before interpolation while the template's "these facts ARE evidence" framing sentence survives intact.
- D-14 measured (not estimated) the combined MCM + perfmon + eu-stack fact-block size over a real ingested case carrying all three fact families: 18,115 combined characters -> ~4,528 estimated tokens against a frozen 6,000-token regression ceiling, comfortably inside the 7,168-token excerpt budget `PromptBudget.fit` reserves.
- ADR 0017 records D-01 (bounded exemplar sample), D-02 (K=3, lowest event_id), D-03 (mandatory sampling-disclosure sentence) and D-17 (union-then-sample for multi-signature aggregates) beside ADRs 0015 and 0016, with their three rejected alternatives.

## Task Commits

Each task was committed atomically:

1. **Task 1: Multi-dump progression with delta suppression on unverified ordering (D-09, D-10, D-11)** - `d805428` (feat)
2. **Task 2: V5 sanitisation gate and the D-14 measured combined-headroom assertion** - `c6c9992` (test)
3. **Task 3: ADR 0017 — record the aggregate-citation sampling decision** - `c7f41fe` (docs)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/sift/pipeline/eustack_facts.py` - Added `_suppression_statement`, `_progression_lines`; wired into `render_eustack_facts` after the signature listing
- `src/sift/prompts/eustack_facts.md` - One new paragraph naming the progression section and the suppression behaviour; still zero ASCII digits
- `tests/test_eustack_facts.py` - Six new tests: `test_deltas_suppressed_on_unverified_order`, `test_deltas_rendered_on_verified_order`, `test_no_continuity_or_ownership_claim_in_emitted_strings`, `test_control_chars_sanitised`, `test_combined_fact_block_headroom_measured`; new helpers `_parse_progression_fixture`/`_progression_bundle`/`_two_untimestamped_dumps`; new constant `_CONTINUITY_VERBS`
- `tests/test_eustack_analyze.py` - New test: `test_eustack_suppression_reaches_prompt_on_real_shaped_fixture`
- `docs/decisions/0017-eustack-aggregate-citation-sampling.md` - New ADR

## Decisions Made

- **D-14 finding (the actual deliverable of Task 2's headroom measurement):** measured combined fact-block figure is **4,528 estimated tokens** (18,115 combined characters: MCM 1,953 + perfmon 2,161 + eu-stack 10,152 chars of fact-block text, plus the 3,849-char triage template), computed via `PromptBudget.estimate`'s own `len(text) // 4` fallback heuristic. Against the **7,168-token** excerpt budget (`ctx_fallback=8192 - reserve_out=1024`) `PromptBudget.fit` reserves for cluster excerpts, this combined figure does **NOT** overrun that budget on its own — roughly 2,640 tokens of headroom remain for cluster excerpts before the assembled prompt would exceed the 8192-token fallback context. Recorded as a real measurement, not the research-stage order-of-magnitude estimate it replaces (18-RESEARCH.md assumption A1). Building `n_ctx` auto-discovery remains explicitly out of scope; frozen ceiling constant `_CEILING_TOKENS = 6000` in `test_combined_fact_block_headroom_measured` gives headroom to the ceiling itself, so the test is a regression bound on unbounded block growth, not a tight pin on today's figure. No follow-up todo is needed since the measured figure is comfortably under budget.
- **Suppression predicate merges D-10 and the <2-dump case into one branch, one sentence:** rather than two near-duplicate messages, `_suppression_statement()` names both possible reasons ("either the dump order could not be verified, or fewer than two dumps were available") in one sentence, matching the plan's own literal instruction to treat both conditions under a single `_suppression_statement()` call while staying truthful for either trigger.
- **Progression section population figure resolved via the same per-dump signature-id map `_union_exemplars` walks**, not `SignatureProgression.counts[-1]` — the latter is 0 for a vanished signature even though its true population and citable exemplars come from an earlier dump (the most-recent-dump-where-present rule). Using `counts[-1]` would have silently reported population 0 alongside real, non-empty citations for exactly the row (a vanished signature) where getting this right matters most.
- **Progression section placed last** in `render_eustack_facts` (after the capped signature listing), since it is a temporal layer over the same signatures the preceding section already lists.

## Deviations from Plan

None - plan executed exactly as written, including the merged suppression-branch design the plan's own `<action>` text specified.

### Fail-first demonstrations (recorded per plan's `<output>` instruction)

**Task 1 — basis check disabled (D-10):** temporarily replaced the `unverified` predicate with `unverified = False`. `test_deltas_suppressed_on_unverified_order` failed:
```
AssertionError: the suppression statement must be present
assert "progression across dumps was not reported" in block
```
Reverted via exact file restore (confirmed byte-identical to the committed state via `diff`); the test passed green again.

**Task 2 — one `sanitise` call removed:** temporarily removed the `sanitise(...)` wrap around the pool-line subsystem label (`_pool_lines`). `test_control_chars_sanitised` failed:
```
AssertionError: assert '\x1b' not in '<!-- eustac...his block.\n'
'\x1b' is contained here:
  -stack job\x1b[31m-queue pool occupancy: ...
```
Reverted via exact file restore (confirmed byte-identical via `diff`); the test passed green again.

## Issues Encountered

- Initial wording of the `test_deltas_suppressed_on_unverified_order`/`test_deltas_rendered_on_verified_order` absence/presence checks used the generic substring `"population change"`, which collided with the template's own prose ("signatures whose population changed") and produced a false pass/fail. Fixed by asserting on the exact delta-row marker string (`"eu-stack signature population change:"`) instead of a loose substring — caught and corrected before the fail-first demonstration, during initial test authoring.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 18 is complete: all eleven `18-VALIDATION.md` primary rows plus all six supplementary rows now map to a passing named test (`uv run pytest tests/test_eustack_facts.py tests/test_eustack_analyze.py -q` — 21 tests, all pass).
- Quality gate at this commit: `uv run ruff check` clean, `uv run pyright` 31 errors (unchanged baseline: 24 `test_eustack_progression.py` + 5 `test_eustack_report.py` + 2 `test_cli_eustack.py`, 0 in any file this plan touched), `uv run pytest` 800 passed, 8 deselected (up from 794 pre-plan, +6 new tests: 5 in `test_eustack_facts.py`, 1 in `test_eustack_analyze.py`).
- **Manual-only verification remains, per `18-VALIDATION.md`'s own "Manual-Only Verifications" table** (not executable by this executor — no live local inference endpoint available, and the default suite is socket-blocked per ADR 0002): ingest `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` into a case, run `uv run sift analyze <case>`, and confirm (a) the eu-stack fact block appears in the generated report's evidence, (b) its figures match `uv run sift eustack <case>` output for the same case, (c) the suppression statement is present (that capture carries no header timestamp), and (d) every `[evt:]` id cited in the resulting hypotheses resolves via `uv run sift show events`. This is narration-quality verification, explicitly out of scope for correctness beyond "never authored the figure" — automated coverage already proves all four success criteria.
- No blockers for Phase 19 (EUS-11 ranking exclusion).

## Self-Check: PASSED

All claimed files found on disk (`src/sift/pipeline/eustack_facts.py`, `src/sift/prompts/eustack_facts.md`, `tests/test_eustack_facts.py`, `tests/test_eustack_analyze.py`, `docs/decisions/0017-eustack-aggregate-citation-sampling.md`, this SUMMARY.md); all three task commits (`d805428`, `c6c9992`, `c7f41fe`) found in `git log`.

---
*Phase: 18-eu-stack-facts-into-sift-analyze*
*Completed: 2026-07-26*
