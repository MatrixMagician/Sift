---
phase: 20-seed-002-embedding-vector-reuse-det-01
plan: 04
subsystem: pipeline
tags: [determinism, embedding-reuse, adr, documentation, encoding, adjacency]

# Dependency graph
requires:
  - phase: 20-seed-002-embedding-vector-reuse-det-01
    provides: "plan 20-01's reuse read, dedup and splice; plan 20-02's re_embed flag; plan 20-03's dimension rebuild"
provides:
  - "the D-02 dedup pin, the duplicate-stored-text determinism pin and the exact-text-equality pin"
  - "the D-12 mixed-run byte-identity pin (fake transport only) and the D-11 batch-knob non-invalidation pin"
  - "docs/decisions/0018-batch-knob-does-not-invalidate-vector-reuse.md"
  - "an honest CONTRIBUTING.md determinism claim naming what reuse closes and what it leaves open"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "a determinism assertion is written against the SPECIFIC expected value and its negation, so it cannot pass vacuously if the fixture was seeded identically"
    - "a byte-identity guarantee that only holds under the fake transport carries a docstring forbidding the live-backend equivalent, because that test would assert the opposite of the measured behaviour"
    - "an ADR that records a settled decision states it as settled — no live alternatives, no reopened question"

key-files:
  created:
    - docs/decisions/0018-batch-knob-does-not-invalidate-vector-reuse.md
  modified:
    - tests/test_cluster.py
    - CONTRIBUTING.md

key-decisions:
  - "D-11 recorded, not re-decided: the three batch knobs are provenance, never a cache guard. Invalidating on a knob change would re-embed under a NEW batch layout on the first run after any reconfiguration — exactly the layout transition ADR 0014 identified as the perturbation trigger — reopening the hysteresis reuse exists to eliminate"
  - "The reuse key is exact code-point equality with no normalisation, case folding, trimming or COLLATE. The asymmetry is deliberate: a miss costs one embed, whereas a normalising match could serve a vector computed from different bytes than the text being clustered — the same silent mis-attribution for which template_id was rejected as the key"
  - "ADR 0018's Consequences section states plainly that reuse closes ADR 0014's exposure for run 2 onward but NOT for the first run, with predecessor backend state still out of scope. CONTRIBUTING.md gains the same qualified claim rather than an upgrade to unconditional determinism — the prohibition in this plan is against overclaiming, and the run-1 residual is real"
  - "No live-backend byte-identity test was written, and the test docstring says why: against a real backend a full re-embed is precisely what perturbs the vectors, so such a test would assert the opposite of ADR 0014's measured finding"

patterns-established:
  - "_capturing_handler wraps the shared _embed_handler to record every batch of inputs, so 'this text was sent exactly once' is directly assertable without touching the shared fixture"
  - "the NFC/NFD test asserts unicodedata.normalize('NFC', nfd) == nfc inside the test, proving the two strings really are canonically equivalent so the cache miss demonstrates exact equality rather than an unrelated difference"

requirements-completed: [DET-01]

coverage:
  - id: D1
    description: "Byte-identical exemplar text is embedded once and the single vector is spliced to every position holding it"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_dedupes_identical_miss_texts"
        status: pass
    human_judgment: false
  - id: D2
    description: "Duplicate stored text resolves deterministically to the highest chunk_id, across repeated calls and a reopened store"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_duplicate_stored_text_resolves_deterministically"
        status: pass
    human_judgment: false
  - id: D3
    description: "Reuse-key equality is exact str equality — NFC vs NFD misses and is re-embedded; no COLLATE or unicodedata in the production path"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_key_is_exact_text_no_unicode_normalisation"
        status: pass
      - kind: grep
        ref: "grep -c COLLATE src/sift/store.py == 0; grep -c unicodedata src/sift/store.py src/sift/pipeline/cluster.py == 0"
        status: pass
    human_judgment: false
  - id: D4
    description: "A mixed hit/miss run produces a vectors list byte-identical to a full re-embed under the fake transport, proven non-vacuously"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_mixed_hit_miss_matches_full_reembed"
        status: pass
    human_judgment: false
  - id: D5
    description: "No live-backend byte-identity test exists; the guarantee is scoped to the fake transport in the test docstring"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "grep -n live tests/test_cluster.py — two hits, one a substring of 'delivery', one the docstring forbidding such a test"
        status: pass
    human_judgment: false
  - id: D6
    description: "Changing embeddings.context / batch_size / max_input_chars does not invalidate reuse; --re-embed applies it"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cluster.py::test_reuse_survives_batch_knob_change"
        status: pass
    human_judgment: false
  - id: D7
    description: "ADR 0018 exists, records D-11 and the exact-text decision, states the run-1 residual, and is referenced from CONTRIBUTING.md alongside ADR 0008 and 0014"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "3 required headings present; all three knobs named; 'first run' and 'out of scope' both present; CONTRIBUTING links 0018 and retains 0014; exactly one 0018-* and no 0019-*"
        status: pass
    human_judgment: false

duration: ~9min
completed: 2026-07-30
status: complete
---

# Phase 20 Plan 04: Determinism Guarantees and ADR 0018 Summary

**The guarantees that make reuse worth having are now pinned by five tests, and the settled decisions behind them are recorded in ADR 0018 with an honest determinism claim in CONTRIBUTING.md.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-30
- **Completed:** 2026-07-30
- **Tasks:** 3
- **Files modified:** 2 (+1 created)

## Accomplishments
- **Adjacency edge, write side:** byte-identical exemplar text is embedded exactly once and the single vector fans out to both chunk rows. Proven by capturing the actual embed inputs and asserting `count == 1`, plus asserting both persisted vector blobs are equal.
- **Adjacency edge, read side:** two `chunks` rows with byte-identical `text` and different vectors resolve to the higher `chunk_id`, three times in a row and again through a freshly opened `CaseStore` on the same file. Asserted against the specific expected vector *and* its negation, so a mis-seeded fixture cannot make it pass vacuously.
- **Encoding edge:** an NFD text does not match a stored NFC key, nor does a trailing-newline variant, and the miss genuinely reaches the endpoint (one fresh embed, one reuse). The test asserts `unicodedata.normalize("NFC", nfd) == nfc` inline so the miss demonstrably follows from exact equality.
- **D-12 byte identity:** a genuinely mixed hit/miss run (both counts asserted non-zero) produces a `text -> vector` mapping and cluster membership identical to an independent full re-embed. Docstring records that no live-backend equivalent should exist.
- **D-11 batch knobs:** a run with different `context`/`batch_size`/`max_input_chars` makes zero embed calls and reuses everything, while the three `meta` keys are overwritten with the new values — provenance recorded, never consulted as a guard. A third call with `re_embed=True` proves that is the way to apply a new knob.
- **ADR 0018** records all three decisions as settled, quoting ADR 0014's measured figures in Context, and its Consequences section states explicitly that reuse closes the exposure for run 2 onward but not for the first run.
- **CONTRIBUTING.md** gains one qualified sentence next to the existing ADR 0008/0014 references. The ADR 0014 qualification is intact and the claim was not upgraded to unconditional determinism.

## Task Commits

1. **Tasks 1-3: five determinism tests, ADR 0018 and the CONTRIBUTING.md sentence** - `21c0f03` (test)

## Files Created/Modified
- `docs/decisions/0018-batch-knob-does-not-invalidate-vector-reuse.md` - **created**; follows ADR 0014's structure (title, Context, Decision, Consequences), British English
- `tests/test_cluster.py` - `unicodedata` import, `_capturing_handler` helper, 5 new determinism tests
- `CONTRIBUTING.md` - the Determinism bullet gains the v1.3 reuse sentence with the run-1 caveat and the ADR 0018 link

## Decisions Made
- `test_reuse_dedupes_identical_miss_texts` drives two groups to the same exemplar text by repointing the second group's `exemplar_event_ids` at the first group's event. That is the reachable route: `exemplar_text` degrades to `group.template` only when the message is missing, so a shared *message* is how two distinct templates legitimately collide on text, exactly as the plan's `read_first` note about the partial-store fallback anticipated.
- `test_reuse_mixed_hit_miss_matches_full_reembed` compares two independent stores rather than two runs against one store, so the full-re-embed baseline cannot be contaminated by the mixed store's cache.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - incorrect acceptance assertion] `--re-embed` embed-call count is not 1 when `batch_size=2`**
- **Found during:** Task 2 (`test_reuse_survives_batch_knob_change`)
- **Issue:** The plan's third assertion says to assert "the embed call happened". The first implementation asserted `count("embeddings") == 1`, which failed with 3: the knob-changed client is constructed with `batch_size=2`, so a 5-text re-embed legitimately splits across three HTTP requests. The behaviour is correct; the exact-count assertion was wrong.
- **Fix:** Changed to `>= 1` with a comment naming the batching reason, and strengthened the surrounding assertions to `embedded_count == 5` and `reused_count == 0` so the test still proves a *full* re-embed rather than merely "some request happened".
- **Files modified:** `tests/test_cluster.py`
- **Verification:** `uv run pytest tests/test_cluster.py -k batch_knob` passes; the run is still proven full via the count assertions.
- **Committed in:** `21c0f03`

---

**Total deviations:** 1 auto-fixed, plus 2 test-construction decisions recorded above.
**Impact on plan:** No scope change. The fix made the assertion match the plan's stated intent ("an embed call did occur") while adding stronger evidence than the original criterion required.

## Issues Encountered
None. The plan's `grep -c "live" tests/test_cluster.py` manual-inspection criterion returned 2 hits, both benign: one is the substring inside `"beta smtp delivery retries"`, the other is the docstring that forbids writing a live-backend test.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full gate green: `uv run pytest` 873/873 passed, `uv run ruff check` clean, `uv run pyright` unchanged at the pre-existing 28-error baseline confined to `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py`
- All four probe-surfaced edges (ordering, empty, adjacency, encoding) are now covered by automated tests: ordering and empty in plan 20-01, adjacency and encoding here
- DET-01's four ROADMAP success criteria are all pinned: zero embedding calls on an unchanged second run (20-01), mixed-run byte identity (here), the operator-visible split (20-01), and batch-knob non-invalidation (here)
- **DET-01 is complete.** Phase 20 has no remaining plans; the phase is ready for verification and milestone completion
- The folded todo `.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md` is now answered by ADR 0018 and can be moved to done alongside the generation-context todo closed by plan 20-05

---
*Phase: 20-seed-002-embedding-vector-reuse-det-01*
*Completed: 2026-07-30*
