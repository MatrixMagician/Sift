---
phase: 15-thread-role-taxonomy-rules-file
plan: 05
subsystem: analysis
tags: [eu-stack, thread-classification, aggregation, determinism, pydantic]

requires:
  - phase: 15-thread-role-taxonomy-rules-file
    provides: "15-01's Role/Reason/Classification models, normalise/signature_of/load_rules/classify_signature; 15-04's strict loader; 15-03's reference_capture_derivative.txt fixture"
provides:
  - "SignatureGroup: one distinct stack signature + thread_count + role/subsystem/pattern/frame_index/reason"
  - "EustackAnalysis: the five-bucket thread/signature partition, ranked signature collapse, full unclassified report, rules provenance"
  - "analyse_eustack(events, rules, rules_hash) -> EustackAnalysis — the aggregate entry point Phases 16-18 consume"
  - "_is_resolvable(symbol) — the D-07 no-resolvable-frame predicate, wired into classify_signature's residual split"
affects: [16-thread-role-taxonomy-expansion, 17-eustack-command, 18-eustack-facts, 19-eustack-ranking]

tech-stack:
  added: []
  patterns:
    - "Classify once per distinct signature (collections.Counter over signature_of(event.raw)), fan the result out by thread_count — never once per thread"
    - "Explicit total sort (-thread_count, frames) for output ordering; no set iteration, no Counter.most_common() tie reliance"
    - "Zero-filled per-role dicts from a fixed _ALL_ROLES tuple so every reader always sees all five keys, empty input included"

key-files:
  created: []
  modified:
    - src/sift/pipeline/eustack.py
    - tests/test_eustack_rules.py

key-decisions:
  - "An unresolvable frame (`??` or a bare `0x...` address) is skipped as a match candidate inside classify_signature's inner loop but stays in the signature tuple; when no rule matches, the residual reason splits on whether ANY frame was resolvable (matched-no-rule) or none were (no-resolvable-frame) — both keep role=unclassified, never a sixth role"
  - "EUS-02 marked complete at the same library level EUS-01 was: the unclassified report (per-signature, ranked, full frame list, distinct reason) is fully computed and exposed on EustackAnalysis; 'user sees' is satisfied by the deterministic core producing the data, mirroring how EUS-01 closed without a CLI (sift eustack CLI is Phase 17's job per D-13)"
  - "Test events for the aggregate cases are built as minimal in-memory Event objects (frozen dataclass, only .raw/.thread vary) rather than round-tripping through file I/O — faster and keeps each case's exact signature under direct control"

patterns-established:
  - "analyse_eustack's group-building loop is the house shape for classify-once/fan-out: iterate Counter.items(), classify each distinct key once, append, then apply one explicit sort — no per-item cleverness inside the loop"

requirements-completed: [EUS-01, EUS-02]

coverage:
  - id: D1
    description: "Every thread event in the derivative fixture lands in exactly one of five roles; per-role thread counts sum to total_threads (success criterion 1)"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_classification_partitions_all_threads"
        status: pass
    human_judgment: false
  - id: D2
    description: "An unmatched signature is reported in analysis.unclassified with its full thread_count and frames tuple, never folded into a known role (success criterion 3)"
    requirement: EUS-02
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_unmatched_signature_reports_count_and_example"
        status: pass
    human_judgment: false
  - id: D3
    description: "A thread whose every frame is unresolvable (`??`) reports reason=no-resolvable-frame, distinct in the same analysis from a resolvable-but-unmatched thread's reason=matched-no-rule; the unresolved frames stay in the signature tuple"
    requirement: EUS-02
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_all_unresolved_frames_is_distinct_category"
        status: pass
    human_judgment: false
  - id: D4
    description: "The unclassified list is the full, never-capped set, ranked by thread count descending, with ties broken ascending on the frames tuple (D-15)"
    requirement: EUS-02
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_unclassified_list_is_ranked_by_thread_count"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_equal_thread_counts_break_ties_on_frames_tuple"
        status: pass
    human_judgment: false
  - id: D5
    description: "classify_signature is invoked exactly once per distinct signature and strictly fewer times than the thread count, so work scales with signatures not threads (success criterion 5)"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_classification_is_per_signature_not_per_thread"
        status: pass
    human_judgment: false
  - id: D6
    description: "EustackAnalysis.model_dump_json() is byte-identical across two independent analyse_eustack calls on the same input"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_analysis_is_byte_identical_on_rerun"
        status: pass
    human_judgment: false
  - id: D7
    description: "An empty event list yields a zero-valued analysis with all five role keys present and empty tuples, never an exception"
    requirement: EUS-01
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_empty_event_list_yields_zero_analysis"
        status: pass
    human_judgment: false
  - id: D8
    description: "Preamble/cap-overflow events (event.thread is None) are excluded from every count"
    verification:
      - kind: unit
        ref: "tests/test_eustack_rules.py#test_preamble_events_are_excluded_from_counts"
        status: pass
    human_judgment: false
  - id: D9
    description: "Real out-of-repo capture reproduces the milestone's own headline figures: 3,902 threads collapse to 93 signatures, and the 1,715-thread signature classifies idle-parked/job-queue/MSIQTask::GetNextPreferredJob/frame_index=3"
    requirement: EUS-01
    verification:
      - kind: manual_procedural
        ref: "manual run against /home/oliverh/Downloads/iserver1_stacks_1-minute_diff/ — see Manual Verification section below"
        status: pass
    human_judgment: true
    rationale: "Source dump is 2.4 MB, out-of-repo (customer environment identifier), and cannot run in CI per D-14 — this is the manual, phase-verification-time measurement the plan's own <human-check> and 15-VALIDATION.md's Manual-Only Verifications table require."

duration: ~20min
completed: 2026-07-25
status: complete
---

# Phase 15 Plan 5: Aggregate Surface — SignatureGroup, EustackAnalysis, analyse_eustack Summary

**`analyse_eustack()` turns a list of eu-stack thread events into a deterministic five-bucket role partition with a ranked signature collapse and a full, never-capped unclassified report — classifying once per distinct signature (93, not 3,902) and splitting the residual into `matched-no-rule` vs `no-resolvable-frame`.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-25T11:40:00Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments

- `_is_resolvable(symbol)` added to `src/sift/pipeline/eustack.py` — the D-07 predicate: `??` and a
  bare hex address (`^0x[0-9A-Fa-f]+$`) are never match candidates, though they stay in the
  signature tuple. Wired into `classify_signature`'s inner loop (skip, don't break) and into the
  residual split (`matched-no-rule` if any frame was resolvable, `no-resolvable-frame` if none were).
- `SignatureGroup` — one distinct signature's `frames`, `thread_count`, `role`, `subsystem`,
  `pattern`, `frame_index`, `reason`.
- `EustackAnalysis` — `total_threads`, `total_signatures`, `threads_by_role`/`signatures_by_role`
  (always five keys, zero-filled), `signatures` (ranked, all of them), `unclassified` (the
  `role=="unclassified"` subset, same order, never capped), `rules_hash`/`rules_version`/
  `rules_validated_against`.
- `analyse_eustack(events, rules, rules_hash)` — selects thread events via `event.thread is not
  None`, builds `Counter[signature_of(event.raw)]` in one pass, classifies each distinct signature
  exactly once, fans out by thread count, sorts explicitly (`-thread_count`, `frames` ascending —
  no `set` iteration, no `Counter.most_common()` tie reliance), zero-fills both role dicts.
- Module docstring extended with `perfmon.py`'s own determinism-contract wording, now literally true
  of this module's aggregate output too.
- 9 new tests in `tests/test_eustack_rules.py` covering the partition property, unclassified
  reporting + the D-07 reason split, rank/tie ordering, the strict per-signature-not-per-thread call
  count (via a monkeypatched counting wrapper), byte-identical rerun, empty input, and
  preamble-exclusion — all against the real `reference_capture_derivative.txt` fixture where the
  plan calls for it, and small in-memory `Event`s elsewhere for precise control.
- **Manual verification against the real out-of-repo capture** (see below): confirms the milestone's
  own headline figures reproduce exactly through the new aggregate path.

## Task Commits

Each task was committed atomically:

1. **Task 1: SignatureGroup, EustackAnalysis and the analyse_eustack entry point** - `400092a` (feat)
2. **Task 2: Partition, unclassified-reporting, cost-scaling and determinism tests** - `45ed1aa` (test)

## Files Created/Modified

- `src/sift/pipeline/eustack.py` - `_is_resolvable`, `SignatureGroup`, `EustackAnalysis`,
  `analyse_eustack`, `classify_signature`'s D-07 wiring, extended module docstring
- `tests/test_eustack_rules.py` - 9 new aggregate tests, `FIXTURES` constant, `_thread_raw`/`_event`
  test helpers

## Decisions Made

- EUS-02 marked complete in `.planning/REQUIREMENTS.md`. The requirement's "user sees unrecognised
  frames counted and reported as `unclassified`" is fully delivered at the library-computation
  level this plan ships — `analysis.unclassified` is the exact per-signature, ranked, full-frame-list
  report D-15 specifies, with the D-07 reason split proven distinct in the same analysis. This
  mirrors how EUS-01 was already marked complete without a `sift eustack` CLI existing yet (D-13
  defers the CLI to Phase 17) — "user sees"/"user gets" in this project's requirement wording tracks
  what the deterministic core produces and exposes on its typed output, not literal terminal
  rendering, which is Phase 17's job.
- Test events for the small, hand-built cases use a minimal in-memory `Event(...)` helper rather than
  writing a file and round-tripping through `EustackAdapter.parse()` — faster, and keeps each test's
  exact signature (`??`, an unrecognised symbol, etc.) under direct, unambiguous control. The
  fixture-backed tests (partition, per-signature-not-per-thread, byte-identical rerun,
  preamble-exclusion) still go through the real adapter against the committed derivative, per the
  plan's own instruction not to hardcode per-role figures that move once 15-06 lands the 24-rule
  taxonomy.
- `classify_signature`'s inner loop change is `continue`, not `break`, on an unresolved frame — a
  later frame in the same signature can still be a match candidate for the same rule; only the
  unresolved frame itself is excluded.

## Deviations from Plan

None — plan executed exactly as written. `classify_signature`'s pre-existing behaviour (rule-major,
first-match-wins, D-01 loop order) was extended, not restructured, to skip unresolvable frames as
candidates while preserving their position for `frame_index` and the signature tuple.

## Issues Encountered

None.

## Manual Verification (D-14 full-capture measurement)

Run against the real out-of-repo reference capture (`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`,
the earlier "160739" dump, 2.4 MB, not committed) using the packaged rules file as it stands after
plan 15-01 (one rule: `idle-parked/job-queue/MSIQTask::GetNextPreferredJob`):

| Metric | Measured | Matches roadmap/research figure |
|---|---|---|
| `total_threads` | 3,902 | ✓ (3,902) |
| `total_signatures` | 93 | ✓ (93) |
| Headline signature | `thread_count=1715 role=idle-parked subsystem=job-queue pattern='MSIQTask::GetNextPreferredJob' frame_index=3` | ✓ (1,715, criterion 4) |
| `threads_by_role` | `idle-parked=1715, blocked-on-external=0, blocked-on-lock=0, running=0, unclassified=2187` | Partition holds: 1715+2187=3902 |
| `signatures_by_role` | `idle-parked=1, unclassified=92` (sums to 93) | Partition holds |
| Parse time | 0.079 s | — |
| `analyse_eustack` time | 0.029 s | Sub-second — cost scales with 93 signatures, not 3,902 threads (criterion 5) |

The high `unclassified` count (2,187/3,902 threads, 92/93 signatures) is expected and correct at this
point in the phase: only plan 15-01's single tracer rule is packaged. Expanding to the 24-rule
taxonomy researched for `eustack_roles.toml` is plan 15-06's job, not this plan's — this plan's
responsibility was the aggregate mechanism and the partition/reporting guarantees around whatever
rules are loaded, both of which hold exactly as measured.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `EustackAnalysis`'s field list (`total_threads`, `total_signatures`, `threads_by_role`,
  `signatures_by_role`, `signatures`, `unclassified`, `rules_hash`, `rules_version`,
  `rules_validated_against`) is the surface Phase 16 groups over by `(role, subsystem)` — every
  `SignatureGroup` already carries `subsystem`, so no second pass over events is needed for EUS-03/
  EUS-05, and `signatures` is already ranked for EUS-06.
- Phase 17 can render `rules_hash`/`unclassified` directly; Phase 18 can cite `pattern`/`frame_index`
  directly — no additional aggregation needed from either.
- `_is_resolvable` is the sole no-resolvable-frame predicate; any future format variant (e.g. a
  JVM-style dump per the adapter's own `[ASSUMED shape]` note) only needs to keep frame text
  spelling `??`/bare-address for unresolved symbols, or `_is_resolvable` needs a second pattern.
- Plan 15-06 (24-rule taxonomy expansion + ADR) can build directly on `analyse_eustack` without
  re-deriving the aggregation; the per-role figures this plan deliberately did NOT hardcode will
  become assertable once that plan lands.
- Full suite green: `uv run pytest` (714 passed, 8 deselected), `uv run ruff check`, `uv run pyright`
  all clean.

---
*Phase: 15-thread-role-taxonomy-rules-file*
*Completed: 2026-07-25*

## Self-Check: PASSED

- FOUND: src/sift/pipeline/eustack.py
- FOUND: tests/test_eustack_rules.py
- FOUND: .planning/phases/15-thread-role-taxonomy-rules-file/15-05-SUMMARY.md
- FOUND: commit 400092a
- FOUND: commit 45ed1aa
