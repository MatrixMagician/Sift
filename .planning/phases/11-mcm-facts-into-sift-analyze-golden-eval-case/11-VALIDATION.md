---
phase: 11
slug: mcm-facts-into-sift-analyze-golden-eval-case
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-19
validated: 2026-07-20
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`; `perf` marker excluded via addopts) |
| **Quick run command** | `uv run pytest -k <name>` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30–60 seconds (excludes `@pytest.mark.perf`) |

Gate for "done" on every task: `uv run ruff check` + `uv run pyright` + `uv run pytest` all clean.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -k <name>` for the touched area
- **After every plan wave:** Run `uv run pytest` (full suite) + `uv run ruff check` + `uv run pyright`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Populated by the planner once PLAN.md task IDs exist; refined by `/gsd-validate-phase`.

| Task ID | Plan | Wave | Requirement | Criterion | Test (load-bearing) | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|---------------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | MCM-06 | C1 provenance / C2 | `test_render_surfaces_analyser_figures_and_denial_line`, `test_id_set_equals_printed_evt_tokens`, `test_top_5_per_dimension_in_analyser_order`, `test_empty_analysis_renders_to_empty_pair`, `test_log_derived_values_are_sanitised` | unit | `uv run pytest tests/test_mcm_facts.py` | ✅ | ✅ green |
| 11-01-02 | 01 | 1 | MCM-06 | C3 no-numbers / C2 determinism | `test_fragment_holds_no_authored_number`, `test_render_is_byte_identical_on_rerun`, `test_injection_directive_in_key_is_sanitised_prose_survives` | unit | `uv run pytest tests/test_mcm_facts.py` | ✅ | ✅ green |
| 11-02-01 | 02 | 2 | MCM-06 | C5 additivity | `test_apply_mcm_block_strips_and_substitutes`, `test_assemble_no_mcm_is_byte_identical_baseline` (+`_NO_KB_PROMPT_HASH == ef5b76801235d179` intact) | unit | `uv run pytest tests/test_kb_analyze.py` | ✅ | ✅ green |
| 11-02-02 | 02 | 2 | MCM-06 | C1 citation union | `test_mcm_block_injected_and_denial_id_citable`, `test_fabricated_id_not_citable`, `test_eval_path_parity_default_thresholds` | integration | `uv run pytest tests/test_mcm_analyze.py` | ✅ | ✅ green |
| 11-02-03 | 02 | 2 | MCM-06 | C2 anti-hallucination | `test_model_cannot_alter_mcm_figures`, `test_mcm_block_deterministic`, `test_mcm_and_kb_coexist` | integration | `uv run pytest tests/test_mcm_analyze.py` | ✅ | ✅ green |
| 11-03-01 | 03 | 3 | MCM-06 | CLI threading (D-17) | `test_analyze_surfaces_mcm_facts_end_to_end`, `test_analyze_threads_mcm_thresholds_override` | e2e/smoke | `uv run pytest tests/test_mcm_analyze.py` | ✅ | ✅ green |
| 11-03-02 | 03 | 3 | MCM-07 | C4 golden gate + MCM-sensitivity | `test_mcm_denial_case_discovered_and_scored_positive`, `test_mcm_denial_ingests_via_dsserrors_autosniff`, `test_mcm_denial_citation_validity_is_mcm_sensitive` | integration | `uv run pytest tests/test_eval_cases.py` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Criterion → test cross-check (all five load-bearing):**
1. **Citation union** — `test_mcm_block_injected_and_denial_id_citable` asserts the MCM `[evt:]` line reaches the prompt AND `denial_id ∈ prompted_ids`; `test_fabricated_id_not_citable` proves the negative (cited ⊆ prompted).
2. **Anti-hallucination / determinism** — `test_model_cannot_alter_mcm_figures` (fake model echoes a wrong figure; asserts analyser block present and wrong figure absent) + `test_mcm_block_deterministic` (byte-identical re-run).
3. **No-numbers template guard** — `test_fragment_holds_no_authored_number` loads `mcm_facts.md` via package data and asserts zero authored digits.
4. **MCM golden regression gate + sensitivity** — `test_mcm_denial_case_discovered_and_scored_positive` (discovered, dsserrors-ingested, scored positive, retrieval 1.0) + `test_mcm_denial_citation_validity_is_mcm_sensitive` (monkeypatches `render_mcm_facts → ("",set())`; the same citation then flags, `citation_validity_rate` drops below 1.0 — removing injection turns the case red; not vacuous).
5. **Byte-identical additivity** — `test_assemble_no_mcm_is_byte_identical_baseline` with `_NO_KB_PROMPT_HASH` unchanged at `ef5b76801235d179`.

---

## Wave 0 Requirements

- [x] `tests/test_mcm_analyze.py` — determinism proof (criterion 2) + citation-gate union (criterion 1)
- [x] Extended `tests/test_kb_analyze.py` golden hash guard with a symmetric no-MCM assertion (criterion 5)
- [x] `eval/cases/mcm-denial/truth.yaml` + fixture wiring — the MCM golden case (criterion 4, MCM-07)

*Existing infrastructure (pytest, respx/`httpx.MockTransport` fake-OpenAI harness, eval runner) covers the rest — no new framework.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end `sift analyze` on a real dsserrors case surfaces MCM facts as cited evidence | MCM-06 | Requires a live local LLM endpoint (zero-network in tests) | Run `sift analyze` on a case containing `hartford_deny_slice.log`; confirm a hypothesis cites an MCM `event_id` and its figures match `sift mcm` output |

*Automated coverage proves the mechanism; the manual check confirms the live integration.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (all 7 tasks carry a `<verify><automated>` block)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task has one)
- [x] Wave 0 covers all MISSING references (all three Wave 0 items landed)
- [x] No watch-mode flags
- [x] Feedback latency < 60s (four target files run in 0.69s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved — 2026-07-20

## Nyquist Audit (2026-07-20)

Adversarial coverage audit of Phase 11's five success criteria. All five map to
real behavioral tests that can fail (not structural/trivial), verified by running
`uv run pytest tests/test_mcm_facts.py tests/test_mcm_analyze.py tests/test_kb_analyze.py tests/test_eval_cases.py`
→ **32 passed in 0.69s**.

Key findings:
- **No vacuous gate.** Criterion 4's golden case would pass on raw-log string matching
  alone (retrieval), so the planners correctly designated `citation_validity_rate` the
  MCM-sensitive metric and proved it: `test_mcm_denial_citation_validity_is_mcm_sensitive`
  monkeypatches `render_mcm_facts → ("", set())`, and the same cited denial id then flags
  (rate < 1.0). Removing the injection genuinely turns the case red.
- **Anti-hallucination is load-bearing, not asserted.** `test_model_cannot_alter_mcm_figures`
  drives a fake model that echoes a wrong figure and asserts the analyser block reaches the
  prompt while the wrong figure does not — the prompt is the source of truth, not model output.
- **C5 additivity** holds the baseline hash `ef5b76801235d179` fixed; a residue-leaking
  strip would drift it and fail.
- **No coverage gap:** all 7 tasks carry `<automated>` verify blocks; no 3-consecutive-task gap.

**Verdict: FILLED (0 escalations, 0 skips). nyquist_compliant: true.**
