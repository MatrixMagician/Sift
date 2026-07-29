---
phase: 18-eu-stack-facts-into-sift-analyze
plan: 02
subsystem: analysis
tags: [eu-stack, citation-gate, hypothesise, fact-renderer, prompt-injection]

requires:
  - phase: 18-eu-stack-facts-into-sift-analyze
    provides: "Plan 18-01's render_eustack_facts leaf module (role-composition grouping, _union_exemplars/_cite_prefix/_signature_event_ids helpers, the eustack_facts.md template, and the hypothesise() splice)"
provides:
  - "render_eustack_facts now renders all four Phase 16 groupings (role composition, per-pool occupancy, lock-site convergence, external-wait concentration) plus graded SaturationFlag lines"
  - "_sampling_sentence(k, population) — single definition site for the D-03 exemplar-count/population wording"
  - "_MAX_SIGNATURES = 8 capped, drop-disclosing per-signature listing (D-06/D-07/D-08)"
  - "Six new unit tests pinning D-17 union-before-sampling, D-03 sampling honesty, the cap/dropped-count contract, zero-flag rendering, byte-identity, and lock-site ownership-blind vocabulary"
affects: [18-03-eu-stack-facts-headroom-and-progression, 19-eus-11-ranking-exclusion]

tech-stack:
  added: []
  patterns:
    - "Aggregate-to-citable-event_id resolution extended uniformly: pool/lock-site/dependency/signature-listing rows all route through the same _union_exemplars single entry point (D-17), so a future fifth grouping has one obvious place to plug in."
    - "Per-grouping helper returns (lines, exemplar-map) so downstream SaturationFlag lines can reuse an aggregate's already-computed exemplar set instead of re-deriving it — flags and their parent aggregate can never disagree about which events back a figure."

key-files:
  created: []
  modified:
    - src/sift/pipeline/eustack_facts.py
    - src/sift/prompts/eustack_facts.md
    - tests/test_eustack_facts.py

key-decisions:
  - "Lock-site lines resolve their site via a new _lock_site_of(group) helper that imports and reuses enclosing_application_frame + UNKNOWN_LOCK_SITE verbatim from eustack.py — never a second walk or a re-declared sentinel string, so the renderer's site attribution can never drift from analyse_saturation's."
  - "SaturationFlag lines map to their grading aggregate three ways: unclassified_thread_pct and no_resolvable_frame_pct resolve their own frame_tuples directly (subsystem is None, and unclassified+no-resolvable-frame respectively); lock_convergence_count flags consume bundle.saturation.lock_sites via a plain iterator in lockstep, since analyse_saturation() is documented (ADR 0016 S-6) to emit exactly one such flag per lock_sites row in that row's own order — avoiding a fragile match-on-thread-count-value approach that ties would make ambiguous."
  - "lock_finding_note is accumulated then prepended only if at least one lock-site line actually rendered (exemplars resolved) — never a floating disclaimer over an empty section, and never printed more than once."
  - "Tasks 1 and 2 landed in a single commit: both extend the same render_eustack_facts body and share _union_exemplars/_cite_prefix, so every new grouping (pools, lock sites, dependencies, flags, signature listing) is threaded through render_eustack_facts in one contiguous 208-line insertion with no natural git-hunk boundary between the two tasks. Splitting would have required synthesising an artificial intermediate state rather than reflecting genuine atomicity."

requirements-completed: [EUS-10]

coverage:
  - id: D1
    description: "render_eustack_facts renders per-pool occupancy, lock-site convergence and external-wait concentration lines, each citing the union of contributing signatures' event pools sampled to the lowest three ids (D-17), never per-signature triples concatenated"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_multi_signature_aggregate_unions_before_sampling"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_exemplar_ids_exist_in_store"
        status: pass
    human_judgment: false
  - id: D2
    description: "The D-03 sampling sentence states the exemplar count and the aggregate's own true population — never a contributing signature's — for every grouping, and a zero-flag healthy capture still renders a full, non-empty block"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_sampling_sentence_states_true_population"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_zero_flag_capture_still_renders_block"
        status: pass
    human_judgment: false
  - id: D3
    description: "The per-signature listing is capped at 8, most-populous-first with no re-sort, states an explicit dropped-count sentence only when signatures were actually dropped, and lock-site lines never use ownership/possession vocabulary"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_signature_cap_states_dropped_count"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_signature_cap_no_dropped_sentence_when_at_or_under_cap"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_lock_site_lines_carry_no_ownership_language"
        status: pass
  - id: D4
    description: "Rendering the same bundle twice is byte-identical, and eustack_facts.md still carries zero authored ASCII digits after the new prose"
    requirement: "EUS-10"
    verification:
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_block_byte_identical_on_rerun"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_facts.py#test_fragment_holds_no_authored_number"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-07-26
status: complete
---

# Phase 18 Plan 2: Remaining Eu-Stack Fact Groupings and Capped Signature Listing Summary

**All four Phase 16 groupings (role composition, pool occupancy, lock-site convergence, external-wait concentration) plus graded saturation flags now render as cited summary lines, capped by an 8-signature drop-disclosing listing — every aggregate figure resolves through one D-17 union-then-sample entry point.**

## Performance

- **Duration:** ~55 min
- **Completed:** 2026-07-26T15:21:11Z
- **Tasks:** 2 (landed in one commit — see Deviations)
- **Files modified:** 3 (`src/sift/pipeline/eustack_facts.py`, `src/sift/prompts/eustack_facts.md`, `tests/test_eustack_facts.py`)

## Accomplishments

- `render_eustack_facts` now emits `_pool_lines` (EUS-03), `_lock_site_lines` (EUS-04), `_dependency_lines` (EUS-05) and `_flag_lines` (graded `SaturationFlag`s) alongside the existing role-composition grouping, every line routed through the shared `_union_exemplars`/`_cite_prefix` pair so the D-17 union-then-sample-3 contract holds uniformly across all four groupings and the capped signature listing.
- New `_sampling_sentence(k, population)` is the single definition site for the D-03 `"(k of M thread events cited as exemplars)"` wording — verified by `grep -c 'def _sampling_sentence'` returning exactly 1.
- New `_MAX_SIGNATURES = 8` caps the per-signature listing to a plain slice of `bundle.analysis.signatures` (already thread-count-descending sorted by `analyse_eustack`, so no second sort was added); a dropped-count statement is emitted only when `dropped > 0` (D-07), and the cap is composition-independent — no flagged signature is ever force-included below the cut (D-08).
- Lock-site lines reuse `enclosing_application_frame`/`UNKNOWN_LOCK_SITE` verbatim (imported, never re-declared) and emit `bundle.saturation.lock_finding_note` exactly once, only when at least one site line actually renders.
- Verified against the real 93-signature `reference_capture_derivative.txt` fixture: the rendered block is 9,217 characters, renders 8 signature rows plus `"85 further signatures not shown (of 93 total signatures)."`, and every printed figure resolves to a real, verifiable `event_id`.

## Task Commits

Both tasks landed in one commit (see Deviations for why):

1. **Tasks 1 & 2: Four Phase-16 groupings + capped signature listing** - `ea62c92` (feat)

**Plan metadata:** (this commit, pending)

## Files Created/Modified

- `src/sift/pipeline/eustack_facts.py` - Added `_lock_site_of`, `_pool_lines`, `_lock_site_lines`, `_dependency_lines`, `_flag_lines`, `_signature_listing_lines`, `_sampling_sentence`, `_MAX_SIGNATURES`; `render_eustack_facts` now assembles all four groupings, flags, and the capped signature listing
- `src/sift/prompts/eustack_facts.md` - One new framing paragraph naming all four groupings and the signature-listing cap; still zero ASCII digits
- `tests/test_eustack_facts.py` - Six new tests: `test_exemplar_ids_exist_in_store`, `test_sampling_sentence_states_true_population`, `test_multi_signature_aggregate_unions_before_sampling`, `test_zero_flag_capture_still_renders_block`, `test_block_byte_identical_on_rerun`, `test_lock_site_lines_carry_no_ownership_language`, `test_signature_cap_states_dropped_count`, `test_signature_cap_no_dropped_sentence_when_at_or_under_cap` (8 new test functions total, exceeding the plan's minimum of 6)

## Decisions Made

- **Lock-convergence flag → site mapping via lockstep iteration, not value-matching:** `analyse_saturation()` emits exactly one `lock_convergence_count` flag per `lock_sites` row, in that row's own order (ADR 0016 S-6). `_flag_lines` consumes `bundle.saturation.lock_sites` through a plain `iter()` advanced once per such flag, rather than matching on `flag.value == float(site.thread_count)` — the latter would be ambiguous under a thread-count tie between two distinct sites.
- **Shared exemplar maps, not re-derivation:** `_pool_lines` and `_lock_site_lines` both return `(lines, exemplar_map)` so `_flag_lines` reuses the exact same exemplar tuple already computed for the parent aggregate (`unclassified_thread_pct` reuses the `None`-subsystem pool's exemplars; `lock_convergence_count` reuses the matching site's). A flag and its parent aggregate can therefore never cite different event sets for what should be the same population.
- **Template addition kept minimal:** rather than adding per-grouping headed sections (no precedent in `mcm_facts.md`/`perfmon_facts.md`, both of which use one generic framing paragraph plus a slot), added a single sentence naming all four groupings and the signature-cap disclosure behaviour — consistent with the established zero-digit, prose-only template convention.

## Deviations from Plan

### Process deviation (not a Rule 1-4 auto-fix)

**Tasks 1 and 2 committed together, not as two separate atomic commits.** Both tasks extend the exact same `render_eustack_facts` function body and share `_union_exemplars`/`_cite_prefix`; the resulting diff is one contiguous 208-line insertion block in `eustack_facts.py` with helpers for both tasks interleaved with no unchanged-context boundary between them (confirmed via `git diff --unified=0`). Splitting into two commits would have required manually constructing an artificial intermediate file state that was never actually run or tested standalone — false atomicity rather than real. Both tasks' tests, verification commands, and acceptance criteria were run and passed independently before the single commit landed.

### Fail-first demonstrations (recorded per plan's `<output>` instruction)

**Task 1 — D-17 rejected strategy (per-signature-lowest-three-concatenated):** temporarily replaced `_union_exemplars`'s union-then-sample body with a per-signature-then-concatenate variant. `test_multi_signature_aggregate_unions_before_sampling` failed:
```
AssertionError: assert ['aaaaaaaaaaaaaaa1', 'aaaaaaaaaaaaaaa3', 'aaaaaaaaaaaaaaa5'] == ['aaaaaaaaaaaaaaa1', 'aaaaaaaaaaaaaaa2', 'aaaaaaaaaaaaaaa3']
```
(the rejected strategy returns signature A's own lowest three, ignoring signature B's contribution entirely). Reverted; `uv run ruff check`/`pyright`/the two targeted tests confirmed byte-identical to the committed state.

**Task 2 — raised cap:** temporarily raised `_MAX_SIGNATURES` from `8` to `100`. `test_signature_cap_states_dropped_count` failed:
```
AssertionError: assert 93 == 8
```
(all 93 signatures rendered instead of the capped 8). Reverted; confirmed the file diff against HEAD showed no residue (`git diff --stat` matched the intended implementation exactly) before the final commit.

---

**Total deviations:** 1 process deviation (commit granularity), 0 auto-fixes.
**Impact on plan:** No scope creep; both fail-first demonstrations behaved exactly as the plan predicted and were cleanly reverted.

## Issues Encountered

- `DumpSlice` (in `eustack_progression.py`) carries two more required fields (`ts_confidence`, `thread_count`) than its two-field docstring summary suggested from a partial read — caught immediately by pyright when constructing a synthetic bundle for `test_multi_signature_aggregate_unions_before_sampling`; fixed by reading the full class definition and supplying both fields.
- The initial pyright run flagged `_load_eustack_fragment` as a private-usage import in the test file (a check the Plan 18-01 test file had not triggered, since it did not carry the `# pyright: ignore[reportPrivateUsage]` marker perfmon's analogous test carries). Added the marker, which incidentally reduced the pyright baseline from 32 to 31 errors rather than merely holding it steady.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 18-03 (headroom + progression) can build directly on this shipped surface: `render_eustack_facts` now emits the full deterministic non-progression block, so 18-03's job is purely additive (per-signature population deltas under the same `_MAX_SIGNATURES` cap, suppressed when the dump order is unverified).
- Quality gate at this commit: `uv run ruff check` clean, `uv run pyright` 31 errors (improved from the 32-error pre-phase/18-01 baseline — see Issues Encountered), `uv run pytest` 794 passed (up from 786 after Plan 18-01, +8 new tests).
- No blockers.

## Self-Check: PASSED

All claimed files found on disk (`src/sift/pipeline/eustack_facts.py`, `src/sift/prompts/eustack_facts.md`, `tests/test_eustack_facts.py`, this SUMMARY.md); commit `ea62c92` found in `git log`.

---
*Phase: 18-eu-stack-facts-into-sift-analyze*
*Completed: 2026-07-26*
