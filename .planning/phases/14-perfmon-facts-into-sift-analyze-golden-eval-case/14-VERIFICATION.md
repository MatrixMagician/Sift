---
phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case
verified: 2026-07-20T00:00:00Z
status: passed
score: 11/11 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case Verification Report

**Phase Goal:** The triage report an engineer already reads now carries corroborating counter evidence the model can CITE but cannot AUTHOR — and a regression gate stops that from quietly degrading. (Mirror of shipped Phase 11.)
**Verified:** 2026-07-20
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | PERF-07 / D-05: `render_perfmon_facts` returns citable id set == exactly the printed `[evt:]` tokens; empty analysis → `("", set())` | ✓ VERIFIED | `src/sift/pipeline/perfmon_facts.py:107-184` — `_cite_prefix` records only ids that become printed tokens; `if not analysis.groups: return "", set()` at :123. Behaviourally proven by `test_perfmon_id_citable_and_fabricated_flagged` (fabricated id `cafefeedcafefeed` absent from `prompted_ids`) — passed. |
| 2 | PERF-07: `_assemble` unions perfmon ids into `prompted_ids`; block built pre-generation from reused events; `cited ⊆ prompted ⊆ store` | ✓ VERIFIED | `hypothesise.py:316-321` union `| (perfmon_block[1] if perfmon_block else set())`; single `store.query_events()` at :421; `render_perfmon_facts(analyse_perfmon(mcm_analysis, events))` at :424. `_apply_perfmon_block`/`_PERFMON_BLOCK_RE`/`_PERFMON_MARKER_RE` present :118-142. |
| 3 | PERF-07 anti-authoring: adversarial model cannot alter/invent a figure | ✓ VERIFIED | `test_model_cannot_alter_perfmon_figures` — verbatim block in prompt, `_MODEL_WRONG_FIGURE` (999999.999) never enters prompt (built pre-reply). Passed. |
| 4 | D-01: independent PERFMON sentinel block placed after MCM (KB→MCM→perfmon), removed whole when absent, not merged | ✓ VERIFIED | `src/sift/prompts/triage.md:51-53` PERFMON_BLOCK_START/END + `<<PERFMON_FACTS>>` immediately after MCM_BLOCK_END (:50); MCM block unchanged. |
| 5 | D-02: strictly additive byte-identity; pre-phase baselines NOT rebaselined; four-combination coverage | ✓ VERIFIED | `_NO_KB_PROMPT_HASH = "ef5b76801235d179"` unchanged vs `main` (git diff empty). `test_four_combination_byte_identity` asserts NEITHER/MCM-ONLY equal frozen constants `8c4341e77deee439`/`0e49cb2cbf6ebb27`, all 4 combos distinct. Passed. |
| 6 | D-03: rendered groups capped at `_MAX_GROUPS = 8`, severity-sorted, surplus ids excluded from citable set | ✓ VERIFIED | `perfmon_facts.py:78,133` `sorted(...)[:_MAX_GROUPS]`; only rendered groups feed `ids`. |
| 7 | D-04: salient counter subset matched on final backslash segment; correlator keeps no-allowlist every-counter behaviour | ✓ VERIFIED | `_SALIENT_COUNTERS` + `_select_counters` :57-63,187-212 (`rsplit("\\",1)[-1]`). No allowlist added to `_counter_trends` (git diff shows only a comment *reaffirming* "No allowlist: every key ... is swept"). |
| 8 | D-06: `perfmon_facts.md` zero authored digits, guarded by no-digit test; block renders from versioned template | ✓ VERIFIED | `grep -E '[0-9]'` on fragment returns nothing (decisions written as "D-six"/"CLI-two"). No-digit guard test in `test_perfmon_facts.py` passed. |
| 9 | D-07: golden gate anchored on Hartford deny signal via sanctioned overlapping re-timed slice | ✓ VERIFIED | `eval/cases/perfmon-denial/input/{perfmon_overlap.csv (6 data rows),perfmon_denial.log}`; `test_fixture_overlaps` proves ≥1 non-None `at_denial_event_id` resolving to a `dssperfmon` event. Passed. |
| 10 | D-08: episodes-present untimestamped sample disclosed (Option-B synthetic group reusing `_hazard_unplaceable_samples`); determinism + Hartford-clean preserved | ✓ VERIFIED | `perfmon.py:669-702` `_unattributed_group` + `UNATTRIBUTED_LABEL`, appended at fixed position :808. `test_unattributed_samples_disclosed_when_episodes_present` + `test_unattributed_disclosure_is_deterministic_and_hartford_clean` passed; no `PerfmonAnalysis` field added. |
| 11 | PERF-08: `perfmon-denial` registered & scored; citation-sensitivity gate non-vacuous; self-verifying overlap guard | ✓ VERIFIED | `_EXPECTED_CASES` includes `perfmon-denial` (suite count 8); `test_perfmon_denial_case_discovered_and_scored_positive` + `test_perfmon_denial_citation_validity_is_perfmon_sensitive` (monkeypatch `render_perfmon_facts→("",set())` drops `citation_validity_rate < 1.0`). Passed. |

**Score:** 11/11 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/sift/pipeline/perfmon_facts.py` | ✓ VERIFIED | `render_perfmon_facts`, `_MAX_GROUPS`, `_group_severity_rank`, `_load_perfmon_fragment`, `_SALIENT_COUNTERS`, `_select_counters` — substantive, imported by hypothesise.py |
| `src/sift/prompts/perfmon_facts.md` | ✓ VERIFIED | Zero-digit fragment + `<<PERFMON_LINES>>` slot |
| `src/sift/prompts/triage.md` | ✓ VERIFIED | PERFMON sentinel block after MCM |
| `src/sift/pipeline/hypothesise.py` | ✓ VERIFIED | `_apply_perfmon_block` + union wired; single query_events |
| `src/sift/pipeline/perfmon.py` | ✓ VERIFIED | `_unattributed_group`, `UNATTRIBUTED_LABEL` (D-08) |
| `eval/cases/perfmon-denial/{truth.yaml,README.md,input/*}` | ✓ VERIFIED | Frozen truth.yaml with anti-tuning header; overlapping fixture pair |
| `tests/test_perfmon_facts.py`, `test_perfmon_analyze.py`, `test_perfmon.py`, `test_eval_cases.py` | ✓ VERIFIED | Renderer, splice, byte-identity, anti-hallucination, disclosure, citation-sensitivity |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| `hypothesise._assemble` | `render_perfmon_facts` output | `prompted_ids | perfmon_block[1]` union | ✓ WIRED |
| `hypothesise()` | `analyse_perfmon` | pre-generation build from reused events (one query_events) | ✓ WIRED |
| `run_case` (eval) | perfmon injection | reuses `hypothesise` end-to-end; `citation_validity_rate` sensitive metric | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Byte-identity, anti-hallucination, citability, overlap guard, D-08 disclosure, citation-sensitivity | `uv run pytest` (targeted perfmon subset) | 45 passed, 0 failed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plans | Status | Evidence |
|-------------|--------------|--------|----------|
| PERF-07 | 14-02, 14-03, 14-04 | ✓ SATISFIED | Cited-not-authored perfmon facts; byte-identical no-data prompt; `cited ⊆ prompted ⊆ store`. REQUIREMENTS.md marks Complete — truthful. |
| PERF-08 | 14-01, 14-05 | ✓ SATISFIED | Registered golden case + non-vacuous citation-sensitivity gate. REQUIREMENTS.md marks Complete — truthful. |

### Anti-Patterns Found

None. The single `ponytail:` comment in `perfmon_facts.py:76-77` names a fixed-ceiling simplification with upgrade path (a sanctioned deliberate-simplification marker), not a `TBD`/`FIXME`/`XXX` debt marker.

### Deferred / Environmental

- Live `sift eval` returns 400 on `/v1/embeddings` in this sandbox (local Lemonade ONNX/OGA model lacks embeddings) — hits all 8 cases identically, pre-existing operator condition, not introduced by this phase. The authoritative offline MockTransport eval gate (EVAL-05) is green. Logged in `deferred-items.md`. Not a phase gap.

### Gaps Summary

None. All 11 must-haves are backed by substantive, wired code and passing behavioural tests. The anti-authoring contract, four-combination byte-identity (with unmoved pre-phase baselines), and non-vacuous regression gate — the three load-bearing invariants of the phase goal — are each proven by a passing test, not by presence alone.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
