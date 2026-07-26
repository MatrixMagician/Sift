---
phase: 18-eu-stack-facts-into-sift-analyze
verified: 2026-07-26T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Ingest /home/oliverh/Downloads/iserver1_stacks_1-minute_diff/ into a case and run `uv run sift analyze <case>`"
    expected: "(a) the eu-stack fact block appears in the generated report's evidence; (b) its figures match `uv run sift eustack <case>` output for the same case; (c) the suppression statement is present, because that capture carries no header timestamp (multi-dump, unverified order); (d) every `[evt:]` id cited in the resulting hypotheses resolves via `uv run sift show events`"
    why_human: "Requires a live local inference endpoint (llama.cpp / Lemonade). The default test suite is socket-blocked per ADR 0002 and LLM prose/narration quality is not assertable by automated means. This is the sole Manual-Only Verification row in 18-VALIDATION.md and no executor or verifier ran it — no live endpoint is available to this agent either."
---

# Phase 18: Eu-Stack Facts into `sift analyze` Verification Report

**Phase Goal:** `sift analyze` narrates the eu-stack figures the deterministic core computed,
each one citable back to real events, and behaves exactly as today on cases with no eu-stack
data.

**Verified:** 2026-07-26
**Status:** human_needed
**Re-verification:** No — initial verification.

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP success criterion) | Status | Evidence |
|---|------|--------|----------|
| 1 | SC1: a case with eu-stack dumps carries computed figures into the prompt as cited evidence, `cited ⊆ prompted ⊆ store` | ✓ VERIFIED | `render_eustack_facts` in `src/sift/pipeline/eustack_facts.py`; spliced via `_apply_eustack_block`/`_assemble` in `hypothesise.py:156-181,300-370`; `test_eustack_block_injected_and_ids_citable`, `test_id_set_equals_printed_evt_tokens`, `test_exemplar_ids_exist_in_store` all pass and assert non-vacuously (block text verbatim in prompt, `block_ids <= prompted_ids`, every id resolves against `store.query_events()`). |
| 2 | SC2: a case with no eu-stack data yields a prompt byte-identical to today's; presence never perturbs MCM/perfmon block bytes | ✓ VERIFIED | `test_no_eustack_data_byte_identical_to_baseline` and `test_five_combination_byte_identity` in `tests/test_eustack_analyze.py` assert against 3 pre-phase frozen hash constants (`_NEITHER_PROMPT_HASH`, `_MCM_ONLY_PROMPT_HASH`, `_PERFMON_ONLY_PROMPT_HASH`, the latter freshly measured against pre-Task-1 `triage.md`) plus 2 new eu-stack-present combinations, compared within-store per D-18. All 5 combinations pass; `test_perfmon_analyze.py::test_four_combination_byte_identity` unmodified and still green. |
| 3 | SC3: `eustack_facts.md` holds zero authored digits; a wrong figure echoed by the model never reaches the prompt | ✓ VERIFIED | `src/sift/prompts/eustack_facts.md` read directly — zero ASCII digits (decision numbers spelled "D-one" through "D-seventeen"). `test_fragment_holds_no_authored_number` and independent `python3 -c` digit-scan both pass. `test_model_cannot_alter_eustack_figures` plants `_MODEL_WRONG_FIGURE` in the model's narrative via a real `hypothesise.hypothesise()` call and asserts the real block is in the captured prompt while the planted figure is absent — passes. |
| 4 | SC4: every aggregate figure quoted resolves to a concrete, verifiable `event_id` set that exists in the store | ✓ VERIFIED | All four Phase-16 groupings, the signature listing, the saturation flags, and the progression deltas route through the single `_union_exemplars`/`_cite_prefix` mechanism. `test_exemplar_ids_exist_in_store` confirms every printed id is a real stored `event_id`. Critically, `test_every_cited_line_carries_sampling_sentence` — added by the CR-01 fix (commit `2a64b81`) — is a **whole-block invariant**, not a per-grouping spot check: it asserts every line in a real, non-synthetic rendered block (the 93-signature `reference_capture_derivative.txt` fixture, which genuinely produces `SaturationFlag`s) that carries an `[evt:]` token also carries the D-03 sampling-disclosure sentence. This closes the exact gap the code review found (`_flag_lines` previously the sole exception) and generalises the honesty guarantee across every grouping, not just the ones with dedicated tests. |

**Score:** 4/4 truths verified (0 present-but-behaviour-unverified).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/eustack_facts.py` | Leaf-module renderer, `(text, ids)` contract | ✓ VERIFIED | 591 lines; no import of `hypothesise`/`cli` (leaf-module boundary confirmed by grep); role/pool/lock-site/dependency/flag/signature/progression sections all present and wired. |
| `src/sift/prompts/eustack_facts.md` | Zero-digit versioned template | ✓ VERIFIED | Read directly; zero ASCII digits; carries the verbatim untrusted-data framing sentence and the "these facts ARE evidence" sentence. |
| Fourth sentinel pair in `src/sift/prompts/triage.md` | `EUSTACK_BLOCK_START`/`END` mirroring MCM/perfmon shape | ✓ VERIFIED | Character-for-character mirror of the perfmon marker/newline shape confirmed by direct read; `_EUSTACK_BLOCK_RE`/`_EUSTACK_MARKER_RE` in `hypothesise.py` are exact structural copies of the perfmon regex pair. |
| `tests/test_eustack_facts.py` | Unit tests for the renderer | ✓ VERIFIED | 700 lines, 19 test functions; all pass (`uv run pytest tests/test_eustack_facts.py -q`). |
| `tests/test_eustack_analyze.py` | Integration tests for `sift analyze` wiring | ✓ VERIFIED | 454 lines, 7 test functions; all pass. |
| `docs/decisions/0017-eustack-aggregate-citation-sampling.md` | ADR recording D-01/D-02/D-03/D-17 | ✓ VERIFIED | Exists; names D-01, D-02, D-03, D-17; records 3 rejected alternatives; cross-references ADR 0015 and 0016. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `hypothesise.hypothesise()` | `eustack_facts.render_eustack_facts` | `eustack_bundle = analyse_eustack_bundle(events, ...)`; `eustack_block = render_eustack_facts(eustack_bundle, events)` | ✓ WIRED | Confirmed at `hypothesise.py:472-480`; reuses the single `events = store.query_events()` call — `grep -c 'store.query_events()' src/sift/pipeline/hypothesise.py` returns exactly 1. |
| `hypothesise._assemble` | `triage.md` `<<EUSTACK_FACTS>>` slot | `_apply_eustack_block` called in the splice chain; `eustack_block[1]` joined into `prompted_ids` | ✓ WIRED | Confirmed at `hypothesise.py:340-341,363-369`. |
| `cli.py::analyze` | `hypothesise(...)` | `eustack_rules_path=config.eustack.rules_path`, `eustack_thresholds=config.eustack.thresholds` | ✓ WIRED | Confirmed at `cli.py:977-978`. |
| `eustack_facts.py` per-line citations | `store.query_events()` | `_signature_event_ids`/`_union_exemplars` re-derive `signature -> event_id` from `event.raw` (never `.message`) | ✓ WIRED | `grep -c 'event.message\|\.message)' src/sift/pipeline/eustack_facts.py` returns 0; confirmed by reading `_signature_event_ids`. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| EUS-10 | 18-01, 18-02, 18-03 | Eu-stack figures inside `sift analyze` as cited evidence; no-eu-stack prompt byte-identical | ✓ SATISFIED | See truths 1-4 above. `.planning/REQUIREMENTS.md` maps EUS-10 to Phase 18 exclusively (13/13 requirements mapped, no orphans, no duplicates). No orphaned requirements found for this phase. |

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX` debt markers in any file touched by this phase
(`eustack_facts.py`, `eustack_facts.md`, `triage.md`, `hypothesise.py`, `cli.py`,
`test_eustack_facts.py`, `test_eustack_analyze.py`, ADR 0017). No stub returns, no hardcoded
empty-data patterns, no console.log-only implementations found.

The one prior code-review finding (CR-01: `_flag_lines` omitting the D-03 disclosure sentence,
plus WR-01 unenforced positional lock-site coupling and WR-02 silent-drop fallback for an
unrecognised flag dimension) was fixed in commit `2a64b81` and independently re-verified during
this pass: `_flag_lines` (lines 301-376) now threads population figures for all three branches,
asserts the lock-site iterator is fully consumed, and raises `AssertionError` on an unrecognised
`SaturationFlag.dimension` rather than silently dropping it. The regression test
(`test_every_cited_line_carries_sampling_sentence`) exercises this against a real fixture with
genuine `SaturationFlag`s, not a synthetic stand-in. No new issues introduced by the fix were
found on inspection.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Eu-stack + analyze integration suite green | `uv run pytest tests/test_eustack_facts.py tests/test_eustack_analyze.py -q` | 22 passed | ✓ PASS |
| Full suite green (regression) | `uv run pytest` (pre-verified per task briefing) | 801 passed, 8 deselected | ✓ PASS |
| Lint/type gates clean | `uv run ruff check`; `uv run pyright` (pre-verified) | ruff clean; pyright 31 pre-existing errors confined to 3 Phase-17 test files, 0 in any phase-18 file | ✓ PASS |
| Zero-digit template guard | `python3 -c "...isdigit()..." eustack_facts.md` | exit 0 | ✓ PASS |

### Human Verification Required

### 1. End-to-end narration quality on the real capture

**Test:** Ingest `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` (confirmed present, real
multi-dump capture with no header timestamp) into a case and run `uv run sift analyze <case>`.
**Expected:** (a) the eu-stack fact block appears in the generated report's evidence; (b) its
figures match `uv run sift eustack <case>` output for the same case; (c) the suppression
statement is present (this capture carries no header timestamp, so the dump order is unverified);
(d) every `[evt:]` id cited in the resulting hypotheses resolves via `uv run sift show events`.
**Why human:** Requires a live local inference endpoint (llama.cpp `llama-server` or Lemonade).
The default automated suite is socket-blocked per ADR 0002 and LLM prose/narration quality is not
programmatically assertable. This is the sole "Manual-Only Verification" row named in
`18-VALIDATION.md`; no executor or this verifier ran it, since neither has a live endpoint
available.

### Gaps Summary

No gaps. All four ROADMAP success criteria are backed by passing, non-vacuous automated tests
that were independently re-read and spot-checked against the actual codebase (not inferred from
SUMMARY.md prose). The prior code-review Critical (CR-01) and both Warnings are fixed and the fix
is independently confirmed, with the regression test itself upgraded from a per-grouping spot
check to a whole-block invariant. The only reason this phase is not `passed` outright is the
single Manual-Only Verification row that no automated or agent process can execute in this
environment (no live local inference endpoint) — that item is deferred to human sign-off per its
own validation-strategy row, not because any automated check failed or is missing.
