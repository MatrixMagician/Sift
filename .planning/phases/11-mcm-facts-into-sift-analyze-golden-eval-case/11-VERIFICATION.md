---
phase: 11-mcm-facts-into-sift-analyze-golden-eval-case
verified: 2026-07-20T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 11: MCM Facts into `sift analyze` + Golden Eval Case Verification Report

**Phase Goal:** The deterministic MCM facts feed the LLM hypothesis pipeline as cited evidence — never authored by the model — and an MCM golden case regression-gates the whole feature.
**Verified:** 2026-07-20
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | MCM facts injected into `sift analyze` as CITABLE evidence (`cited ⊆ prompted ⊆ store`) | ✓ VERIFIED | `hypothesise._assemble` line 271: `prompted_ids = set(event_ids) \| (mcm_block[1] if mcm_block else set())` — the printed `[evt:]` ids are unioned into the citation-gate allowed set. `_citation_gate`/`_all_cited_within` enforce `cited ⊆ prompted`; exemplar ids come from the store, so `cited ⊆ store` transitively holds. Behavioural tests pass: `test_mcm_block_injected_and_denial_id_citable`, `test_fabricated_id_not_citable`, `test_analyze_surfaces_mcm_facts_end_to_end` (cited denial id → `citations_valid is True`, exit 0). |
| 2 | Model cannot alter/invent figures — block assembled pre-generation, verbatim from analyser | ✓ VERIFIED | `hypothesise()` builds `render_mcm_facts(analyse_mcm(store.query_events(), …))` at lines 369-371 **before** `_generate`. Figures read verbatim from `analyse_mcm` (`flag.value_pct`, `granted_bytes`); template holds no numbers. Behavioural proof `test_model_cannot_alter_mcm_figures` passes: verbatim analyser block present in prompt, model's `999.9%` figure absent (prompt built before the model reply). |
| 3 | Fact block via a versioned template file with no authored numbers | ✓ VERIFIED | `src/sift/prompts/mcm_facts.md` holds labels/prose only, zero ASCII digits (decision IDs written as words "D-twenty / CLI-two"). `render_mcm_facts` loads it via `importlib.resources` and fills `<<MCM_LINES>>`; wording changes touch no Python. Guard `test_fragment_holds_no_authored_number` (no-digit assertion) passes. |
| 4 | MCM golden case + `sift eval` non-zero on regression, genuinely MCM-sensitive | ✓ VERIFIED | `eval/cases/mcm-denial/` exists: frozen `truth.yaml` (`expect_no_incident: false`, authored pre-tuning), `README.md`, committed `input/hartford_deny_slice.log`. Sensitivity proven by `test_mcm_denial_citation_validity_is_mcm_sensitive`: injection ON → `citation_validity_rate == 1.0`; monkeypatch `render_mcm_facts → ("", set())` (injection OFF) → same cited denial id FLAGGED → `citation_validity_rate < 1.0`. Case scores positive (not run_failed); `sift eval` gate exits non-zero on regression (EVAL-03). |
| 5 | Byte-identical prompt when no MCM data | ✓ VERIFIED | `_apply_mcm_block(template, None)` strips the whole `<!-- MCM_BLOCK_START…END -->` sentinel region residue-free (line 104-105); `mcm_block[1]` empty set adds no ids. `test_assemble_no_mcm_is_byte_identical_baseline` asserts assembled hash == `_NO_KB_PROMPT_HASH = "ef5b76801235d179"` (the pre-phase baseline, unchanged). Passes. |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/pipeline/mcm_facts.py` | Pure model-free fact renderer → (block, citable_ids) | ✓ VERIFIED | Leaf module; reads analyser tree + fragment only. Every log-derived value routed through `sanitise`. Returned id set == printed `[evt:]` tokens. |
| `src/sift/prompts/mcm_facts.md` | Versioned fragment, no authored numbers | ✓ VERIFIED | Labels/prose + single `<<MCM_LINES>>` placeholder; zero digits. Framed as citable evidence (inverse of KB). |
| `src/sift/prompts/triage.md` | Sentinel MCM block, byte-identical when absent | ✓ VERIFIED | `<!-- MCM_BLOCK_START … <<MCM_FACTS>> … MCM_BLOCK_END -->` below `Evidence:`. |
| `src/sift/pipeline/hypothesise.py` | Splice + prompted_ids union at chokepoint | ✓ VERIFIED | `_apply_mcm_block`, `_assemble(mcm_block=)` union, `hypothesise(mcm_thresholds=)` builds facts pre-generation. |
| `src/sift/cli.py` | Threads config.mcm.thresholds, no new flag | ✓ VERIFIED | Line 859: `mcm_thresholds=config.mcm.thresholds` in the `hypothesise(...)` call (D-17, no CLI surface). |
| `eval/cases/mcm-denial/` | Golden case with frozen truth.yaml | ✓ VERIFIED | `truth.yaml` + `README.md` + committed slice present. |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `hypothesise()` | `render_mcm_facts`/`analyse_mcm` | Built at chokepoint pre-generation (lines 369-371) | ✓ WIRED |
| `_assemble` | citation gate | `mcm_block[1]` unioned into `prompted_ids` (line 271) | ✓ WIRED |
| `cli.analyze` | `hypothesise` | `mcm_thresholds=config.mcm.thresholds` (line 859) | ✓ WIRED |
| `eval/runner` | MCM injection | Calls `hypothesise` (no thresholds) → default `McmThresholdsConfig()` still injects | ✓ WIRED (`test_eval_path_parity_default_thresholds`) |

### Behavioural Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase-11 test files | `uv run pytest tests/test_mcm_facts.py tests/test_mcm_analyze.py tests/test_kb_analyze.py tests/test_eval_cases.py` | 32 passed | ✓ PASS |
| Determinism (crit 2) | `test_mcm_block_deterministic` | byte-identical prompts | ✓ PASS |
| Regression sensitivity (crit 4) | `test_mcm_denial_citation_validity_is_mcm_sensitive` | ON=1.0 / OFF<1.0 | ✓ PASS |
| No-MCM byte identity (crit 5) | `test_assemble_no_mcm_is_byte_identical_baseline` | hash == baseline | ✓ PASS |
| MCM+KB coexistence | `test_mcm_and_kb_coexist` | MCM citable, KB not | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MCM-06 | 11-01/02/03 | MCM facts as cited evidence, computed not model-authored | ✓ SATISFIED | Criteria 1-3, 5; REQUIREMENTS.md line 94 `[x]` |
| MCM-07 | 11-03 | MCM golden case, regression-gated | ✓ SATISFIED | Criterion 4; REQUIREMENTS.md line 95 `[x]` |

### Anti-Patterns Found

None. Source files read in full — no stubs, no `TODO`/`FIXME`/`XXX`, no placeholder returns. `render_mcm_facts` is fully wired to `analyse_mcm`; empty-analysis `("", set())` is the correct residue-free no-op, not a stub.

### Quality Gate

`uv run ruff check` clean · `uv run pyright` 0 errors · `uv run pytest` 536 passed / 8 deselected. Milestone-done gate green.

### Human Verification Required

None required for goal achievement. VALIDATION.md lists one optional live smoke test (run `sift analyze` against a real local LLM endpoint on a dsserrors case). This is a redundant integration confirmation, not a gap: the project's load-bearing invariant is zero-network-in-tests via an injectable client, and `test_analyze_surfaces_mcm_facts_end_to_end` already exercises the full `sift analyze` code path (CliRunner + `httpx.MockTransport`) end-to-end. The external LLM server itself is out of phase scope.

### Gaps Summary

No gaps. All five ROADMAP success criteria are delivered by the code and proven by passing behavioural tests through the project's canonical fake-server seam. The two most failure-prone claims — that the model cannot author figures (criterion 2) and that the golden case genuinely turns red when injection is removed (criterion 4) — are each backed by a dedicated behavioural test that manipulates the model reply / strips the injection and asserts the invariant holds. The goal is achieved.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
