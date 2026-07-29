---
phase: 17-multi-dump-progression-sift-eustack-report-csv
plan: 02
subsystem: analysis
tags: [pydantic, eustack, multi-dump, progression, determinism]

requires:
  - phase: 17-multi-dump-progression-sift-eustack-report-csv (plan 01)
    provides: "eustack_progression.py leaf module — group_dumps, resolve_dump_order (D-01 single/timestamp path with D-02 raising NotImplementedError), frozen progression models, analyse_eustack_bundle orchestration; sift eustack CLI wiring"
provides:
  - "resolve_dump_order full three-state resolution: ORDER_BASIS_SINGLE, ORDER_BASIS_TIMESTAMP (D-01), ORDER_BASIS_FILENAME with a loud OrderingFlag (D-02) — no timestamp ever invented"
  - "Synthetic multi-dump fixture set (tests/fixtures/eustack/progression/) with a reproducible provenance script — reversed-filename-order (D-01 discriminator) and grew-then-shrank warehouse sequence (D-08 discriminator) baked in"
  - "compute_progression — per-signature counts/step_deltas/overall_delta across N dumps (D-08), appeared/vanished derived from counts (D-09), classification from the last dump a signature actually appears in, ranked on an explicit total sort key, no cap"
affects: [17-03-progression-rendering]

tech-stack:
  added: []
  patterns:
    - "Cross-dump join on the full SignatureGroup.frames tuple via a dict-per-dump lookup, never the D-07 display projection (matched_frame/leaf_frame), which stays a rendering concern"
    - "Deterministic union-of-keys via dict.setdefault insertion order (never a set) before an explicit re-sort on a total key — mirrors group_dumps' own perfmon.py-derived discipline"

key-files:
  created:
    - tests/fixtures/eustack/progression/derive_progression_fixtures.py
    - tests/fixtures/eustack/progression/dump_charlie.txt
    - tests/fixtures/eustack/progression/dump_bravo.txt
    - tests/fixtures/eustack/progression/dump_alpha.txt
    - tests/fixtures/eustack/progression/dump_delta_nots.txt
    - tests/test_eustack_progression.py
  modified:
    - src/sift/pipeline/eustack_progression.py

key-decisions:
  - "resolve_dump_order picks each dump's representative by the FIRST event with event.thread is not None, reading only .ts/.ts_confidence off it — never a preamble lookup, never a second raw-text timestamp regex"
  - "compute_progression's classification fields (role/subsystem/pattern/frame_index/reason/matched_frame/leaf_frame) come from the LAST dump where a signature has a non-zero count, not the last dump overall — a signature that vanished before the final dump (e.g. 'departing', only in dump_charlie) still carries a real classification instead of empty cells"
  - "Ranking sort key is the explicit total order (-abs(overall_delta), -counts[-1], frames) — absolute delta first, current count as tie-break, frames tuple as the final tie-break so two runs over reordered input events produce byte-identical output (proven by test_progression_ranking_is_a_total_order)"
  - "PROGRESSION_SCOPE_NOTE's bare mention of 'TID reuse' (shipped in 17-01) is not itself a D-10 violation — it explains why continuity CANNOT be established, not a claim that it was. The D-10 test bans continuity verbs (persisted/remained/stayed/still blocked) and concrete thread-identifier VALUES (e.g. 'TID 100001'), not the generic word 'TID'"
  - "12th test (test_progression_carries_every_signature_no_cap) added beyond the plan's 11 named Task-3 tests to satisfy its own acceptance criterion of 'at least 12 tests collected' — the plan's artifact list and its numeric threshold were inconsistent by one; closed with a genuine no-cap regression test rather than a filler"

patterns-established: []

requirements-completed: [EUS-07, EUS-08]

coverage:
  - id: D1
    description: "Dump ordering states its basis explicitly (D-01 timestamp / D-02 filename-fallback-with-flag / single-dump), and an unresolvable ordering is flagged loudly rather than assumed, with no timestamp ever invented"
    requirement: EUS-08
    verification:
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_order_by_timestamp_ignores_filename_order"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_order_fallback_flagged_when_any_dump_untimestamped"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_order_fallback_still_renders_progression"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_no_timestamp_is_invented"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_single_dump_needs_no_ordering"
        status: pass
    human_judgment: false
  - id: D2
    description: "A three-or-more-dump case carries both consecutive-pair step deltas and an overall first-to-last delta per signature, so a population that grew then shrank is visible rather than cancelled out"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_step_and_overall_deltas_disagree_on_grew_then_shrank"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_unchanged_signature_has_zero_delta"
        status: pass
    human_judgment: false
  - id: D3
    description: "Newly-appeared and vanished signatures are distinguishable and derived purely from the count sequence, ranked on a total sort key with no cap applied to the signature set"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_appeared_and_vanished_signatures"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_progression_carries_every_signature_no_cap"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_progression_ranking_is_a_total_order"
        status: pass
    human_judgment: false
  - id: D4
    description: "Adding dumps never changes which dump the classification/saturation figures come from (last dump only, never a union); progression carries no per-thread continuity claim or thread-identifier value anywhere"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_saturation_computed_on_last_dump_only"
        status: pass
      - kind: unit
        ref: "tests/test_eustack_progression.py#test_no_per_tid_claim_in_progression_strings"
        status: pass
    human_judgment: false
  - id: D5
    description: "Synthetic multi-dump fixture set is reproducible from its committed derivation script alone, carries no customer identifier, and classifies into non-unclassified signatures"
    requirement: EUS-07
    verification:
      - kind: unit
        ref: "uv run python tests/fixtures/eustack/progression/derive_progression_fixtures.py && git status --porcelain tests/fixtures/eustack/progression"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_cli.py -k phase5_e2e -q"
        status: pass
    human_judgment: false

duration: ~30min (this session — Task 3 only; Tasks 1-2 landed in a prior session, see below)
completed: 2026-07-26
status: complete
---

# Phase 17 Plan 2: Multi-Dump Ordering & Progression Summary

**`resolve_dump_order`'s D-01/D-02 fallback and `compute_progression`'s per-signature population deltas (consecutive-pair + overall, appeared/vanished, no cap) generalise the Wave-1 tracer from N=1 to N dumps, backed by a five-signature synthetic fixture set with a reproducible provenance script.**

## Performance

- **Duration:** Task 1 + Task 2 ~unrecorded in this session (executed and committed in a prior, interrupted session — see Session Continuity below); Task 3 (this session) ~30 min
- **Completed:** 2026-07-26
- **Tasks:** 3
- **Files modified:** 7 (6 created, 1 modified)

## Accomplishments
- `tests/fixtures/eustack/progression/` — a deterministic five-signature, four-dump synthetic fixture set (`derive_progression_fixtures.py` as sole source of truth) with the reversed-filename-order property (D-01 discriminator) and the warehouse 3→7→5 grew-then-shrank sequence (D-08 discriminator) both encoded by construction
- `resolve_dump_order` fully implements all three ordering states — single dump (no flag), all-timestamped (D-01, sorted on `(ts, source_file)`), any-untimestamped (D-02, sorted on `source_file` alone with exactly one loud `OrderingFlag`) — with no clock read and no timestamp ever invented, inferred or filesystem-derived on any code path
- `compute_progression` joins signature groups across the resolved dump order on the full `frames` tuple, producing `counts`/`step_deltas`/`overall_delta` (both figures, always) plus `appeared`/`vanished` derived purely from the count sequence, ranked on an explicit total key so output is byte-identical regardless of input event ordering
- 12 tests in `tests/test_eustack_progression.py` cover both the ordering and progression halves; full suite (763 tests), `ruff check`, and `pyright` are all clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Synthetic multi-dump fixture set with a provenance script** - `8c7d805` (test)
2. **Task 2: Dump ordering — D-01 timestamp basis, D-02 declared fallback and its loud flag** - `827b306` (feat)
3. **Task 3: Population deltas — consecutive steps, overall first-to-last, appeared and vanished** - `70dad28` (feat)

_Note: Tasks 1-2 were executed and committed in a prior session that was interrupted three times by upstream API 529 errors after landing both commits; this SUMMARY was written and Task 3 executed in the resumed session, per `.planning/STATE.md`'s recorded halt point._

## Files Created/Modified
- `tests/fixtures/eustack/progression/derive_progression_fixtures.py` - provenance script; `SIGNATURES` (5 authored frame chains), `DUMPS` (4 dumps' filenames/timestamps/counts), `main()` writes the four `.txt` files
- `tests/fixtures/eustack/progression/dump_charlie.txt` / `dump_bravo.txt` / `dump_alpha.txt` - the timestamped trio, chronological order the exact reverse of filename order (16:07:39 → 16:08:37 → 16:09:35)
- `tests/fixtures/eustack/progression/dump_delta_nots.txt` - `dump_bravo.txt`'s population with the ISO-8601 header line omitted entirely (D-02 trigger)
- `src/sift/pipeline/eustack_progression.py` - `resolve_dump_order`'s D-02 fallback branch (replacing the `NotImplementedError` 17-01 left), `compute_progression` (new), `analyse_eustack_bundle` rewired to build one `ordered_analyses` tuple and delegate signature-building to `compute_progression`
- `tests/test_eustack_progression.py` - 12 tests: 5 ordering (Task 2) + 7 progression (Task 3, including one no-cap regression test beyond the plan's named 6)

## Decisions Made
- `compute_progression`'s classification fields are read from the LAST dump where a signature has a non-zero count, not the last dump overall — verified against the `departing` signature (present only in `dump_charlie.txt`, vanished by `dump_bravo.txt`), which still resolves to `idle-parked`/`command-queue` rather than empty cells.
- The 12th test (`test_progression_carries_every_signature_no_cap`) was added because the plan's Task 3 acceptance criteria required "at least 12 tests collected" while its own named test list enumerated only 11 (5 from Task 2 + 6 from Task 3). Rather than pad with a no-op test, the added test asserts a genuine invariant from the plan's own action text ("Apply no cap to the signature set … the analysis model carries every signature") — all five fixture signatures, including the unchanged `stable`, are present in `ProgressionAnalysis.signatures`.
- `test_no_per_tid_claim_in_progression_strings` bans continuity verbs (persisted/remained/stayed/"still blocked") and concrete thread-identifier VALUE tokens (`TID\s*\d+`) rather than the bare word "TID" — `PROGRESSION_SCOPE_NOTE` (shipped in 17-01) legitimately uses "TID reuse" to explain why per-thread continuity *cannot* be established, which is the D-10 rationale itself, not a violation of it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed E501 line-length violation in `analyse_eustack_bundle`**
- **Found during:** Task 3 (`ruff check` gate)
- **Issue:** The rewritten `last_analysis` fallback expression exceeded the 88-character line limit
- **Fix:** Split the ternary across three lines
- **Files modified:** `src/sift/pipeline/eustack_progression.py`
- **Verification:** `uv run ruff check src/sift tests` exits 0
- **Committed in:** `70dad28` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking/lint)
**Impact on plan:** Cosmetic only. No scope creep.

## Issues Encountered
None beyond the pre-existing session interruption (upstream API 529 errors) recorded in `.planning/STATE.md` before this resumed session began; no code-level issues in Task 3.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
`ProgressionAnalysis.signatures` now carries real multi-dump deltas (`counts`/`step_deltas`/`overall_delta`/`appeared`/`vanished`) for every signature, with `resolve_dump_order` fully resolving all three ordering states. 17-03 (progression rendering) can consume this shape directly: the D-09 changed-only Markdown filter, the CSV's per-dump count + delta columns, and the D-07 `matched_frame`/`leaf_frame` display projection are all already populated on `SignatureProgression`. No blockers.

---
*Phase: 17-multi-dump-progression-sift-eustack-report-csv*
*Completed: 2026-07-26*

## Self-Check: PASSED

All claimed files exist on disk; all three task commits (`8c7d805`, `827b306`, `70dad28`) present in `git log`.
