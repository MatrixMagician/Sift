---
phase: 18
slug: eu-stack-facts-into-sift-analyze
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-26
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by `/gsd-plan-phase 18` from `18-RESEARCH.md` § Validation Architecture.
> Per-task rows are completed once PLAN.md files exist; `/gsd-validate-phase 18` promotes
> `status` to `validated`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (project-pinned, `uv`-managed) |
| **Config file** | `pyproject.toml` (existing `[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/test_eustack_facts.py tests/test_eustack_analyze.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5 s quick · ~90 s full suite |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_eustack_facts.py tests/test_eustack_analyze.py -x`
- **After every plan wave:** Run `uv run pytest` — the full suite is mandatory per wave, not
  optional: MCM and perfmon byte-identity regressions share the `triage.md` template with this
  phase's new block and will only surface in their own frozen-hash tests.
- **Before `/gsd-verify-work`:** `uv run ruff check`, `uv run pyright`, `uv run pytest` all clean
  (CLAUDE.md's definition of "done").
- **Max feedback latency:** 5 s (quick) · 90 s (full)

---

## Per-Task Verification Map

> Rows are keyed to phase requirement + success criterion until plans exist; the planner fills
> `Task ID` / `Plan` / `Wave` when PLAN.md files are written.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| T1 (tracer) / T3 | 18-01 | 1 | EUS-10 (SC1) | T-18-04 | Printed `[evt:]` ids are exactly the ids joined into `prompted_ids`; all resolve in the store — `cited ⊆ prompted ⊆ store` holds | unit + integration | `uv run pytest tests/test_eustack_facts.py::test_id_set_equals_printed_evt_tokens tests/test_eustack_analyze.py::test_eustack_block_injected_and_ids_citable -x` | ❌ W0 | ⬜ pending |
| T2 | 18-01 | 1 | EUS-10 (SC2) | — | A case with no eu-stack events yields a prompt byte-identical to the pre-phase baseline; eu-stack presence never perturbs MCM or perfmon block bytes | integration (frozen-hash) | `uv run pytest tests/test_eustack_analyze.py::test_no_eustack_data_byte_identical_to_baseline -x` | ❌ W0 | ⬜ pending |
| T2 | 18-01 | 1 | EUS-10 (SC2, D-18) | — | The five locked presence combinations (NEITHER · MCM-ONLY · PERFMON-ONLY unchanged; EUSTACK-ONLY · ALL-THREE new-and-distinct) each match their frozen hash | integration (frozen-hash) | `uv run pytest tests/test_eustack_analyze.py::test_five_combination_byte_identity -x` | ❌ W0 | ⬜ pending |
| T3 | 18-01 | 1 | EUS-10 (SC3) | T-18-01 | `eustack_facts.md` contains no ASCII digit — every figure originates in Python, never in the template | unit | `uv run pytest tests/test_eustack_facts.py::test_fragment_holds_no_authored_number -x` | ❌ W0 | ⬜ pending |
| T3 | 18-01 | 1 | EUS-10 (SC3) | T-18-02 | A planted/model-echoed wrong figure provably never reaches the assembled prompt (MCM-06/PERF-07 pattern) | integration | `uv run pytest tests/test_eustack_analyze.py::test_model_cannot_alter_eustack_figures -x` | ❌ W0 | ⬜ pending |
| T1 | 18-02 | 2 | EUS-10 (SC4) | T-18-07 | Every printed aggregate's cited ids exist in `store.query_events()`; printed exemplar count equals `min(3, population)` | unit | `uv run pytest tests/test_eustack_facts.py::test_exemplar_ids_exist_in_store tests/test_eustack_facts.py::test_sampling_sentence_states_true_population -x` | ❌ W0 | ⬜ pending |
| T1 | 18-02 | 2 | EUS-10 (SC4, D-17) | T-18-04 | A multi-signature aggregate unions contributing signatures' event pools **before** taking the 3 lowest ids — one triple per aggregate, N stated as the aggregate's own population | unit | `uv run pytest tests/test_eustack_facts.py::test_multi_signature_aggregate_unions_before_sampling -x` | ❌ W0 | ⬜ pending |
| T2 | 18-02 | 2 | D-07 | T-18-08 | A case with >8 signatures renders exactly 8 sections plus an explicit "N further signatures not shown" statement — nothing dropped silently | unit | `uv run pytest tests/test_eustack_facts.py::test_signature_cap_states_dropped_count -x` | ❌ W0 | ⬜ pending |
| T1 | 18-03 | 3 | D-10 / D-11 | T-18-09 | A multi-dump case whose order basis is `ORDER_BASIS_FILENAME` renders last-dump state only, with an explicit suppression statement and **no** per-signature delta figures | unit + integration | `uv run pytest tests/test_eustack_facts.py::test_deltas_suppressed_on_unverified_order -x` | ❌ W0 | ⬜ pending |
| T2 | 18-03 | 3 | V5 (input validation) | T-18-03 | Every frame/rules-derived string routes through `sift.render._util.sanitise` before interpolation | unit | `uv run pytest tests/test_eustack_facts.py::test_control_chars_sanitised -x` | ❌ W0 | ⬜ pending |
| T2 | 18-03 | 3 | D-14 | T-18-05 | Combined MCM + perfmon + eu-stack fact blocks are **measured** against the fallback context, not estimated — fact blocks bypass `PromptBudget.fit` | unit (measured assertion) | `uv run pytest tests/test_eustack_facts.py::test_combined_fact_block_headroom_measured -x` | ❌ W0 | ⬜ pending |

**Supplementary rows added at plan time** (beyond the eleven seeded from RESEARCH.md):

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| T3 | 18-01 | 1 | EUS-10 (eval-path parity) | — | The default-config path (no `eustack_rules_path` / `eustack_thresholds` passed) still injects the block — the packaged rules default and `or EustackThresholdsConfig()` fallback work on the eval harness's path | integration | `uv run pytest tests/test_eustack_analyze.py::test_eval_path_parity_default_eustack_config -x` | ❌ W0 | ⬜ pending |
| T1 | 18-02 | 2 | Pitfall 1 (emptiness gate) | — | A zero-flag healthy capture with `total_threads > 0` still renders a full block — emptiness is gated on `total_threads == 0`, never on `saturation.flags` | unit | `uv run pytest tests/test_eustack_facts.py::test_zero_flag_capture_still_renders_block -x` | ❌ W0 | ⬜ pending |
| T1 | 18-02 | 2 | Determinism | — | Rendering the same bundle twice yields byte-identical text and an identical id set | unit | `uv run pytest tests/test_eustack_facts.py::test_block_byte_identical_on_rerun -x` | ❌ W0 | ⬜ pending |
| T1 | 18-03 | 3 | D-09 | — | A verified-order multi-dump case renders capped, cited per-signature deltas plus the verbatim `scope_note` | unit | `uv run pytest tests/test_eustack_facts.py::test_deltas_rendered_on_verified_order -x` | ❌ W0 | ⬜ pending |
| T1 | 18-03 | 3 | ADR 0015 non-goal | T-18-10 | No emitted string asserts per-thread continuity, lock possession, or a wait-for-graph conclusion (asserted over emitted output, not source text) | unit | `uv run pytest tests/test_eustack_facts.py::test_no_continuity_or_ownership_claim_in_emitted_strings -x` | ❌ W0 | ⬜ pending |
| T1 | 18-03 | 3 | D-10 / D-11 (integration) | T-18-09 | The suppression statement survives prompt assembly and reaches the assembled prompt on the real-shaped fixture | integration | `uv run pytest tests/test_eustack_analyze.py::test_eustack_suppression_reaches_prompt_on_real_shaped_fixture -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_eustack_facts.py` — unit tests for the new renderer; mirrors
      `tests/test_perfmon_facts.py` structure (id-set-equals-printed-tokens, cap-and-drop,
      sanitisation, byte-identity-on-rerun, no-authored-digit, sampling-sentence-honesty,
      exemplars-exist-in-store)
- [ ] `tests/test_eustack_analyze.py` — integration tests; mirrors `tests/test_mcm_analyze.py`
      and `tests/test_perfmon_analyze.py` (injected-and-citable, fabricated-id-not-citable,
      model-cannot-alter-figures, five-combination byte identity per D-18,
      deltas-suppressed-on-unverified-order against the real-shaped fixture per D-11)
- [ ] `src/sift/prompts/eustack_facts.md` — new versioned template (a data file mirroring
      `mcm_facts.md` / `perfmon_facts.md`; no framework install needed)

*No new test framework or fixture harness is required — `CaseStore`, `EustackAdapter` and the
existing `tests/fixtures/eustack/` fixtures already cover ingestion. The D-11 suppression path is
exercised against `tests/fixtures/eustack/reference_capture_derivative.txt`, the real-shaped,
header-timestamp-less fixture; per D-11 this is the **primary** path to test, not an edge case.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end narration quality on the real capture | EUS-10 | Requires a live local inference endpoint (llama.cpp / Lemonade); the default suite is socket-blocked per ADR 0002, and LLM prose quality is not assertable | `uv run sift analyze` on a case ingested from `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`; confirm the eu-stack block appears, figures match `sift show`, and every `[evt:]` id in the hypothesis resolves |

*Automated coverage proves all four success criteria; the manual check above is narration quality
only, which is explicitly out of scope for correctness verification beyond "never authored the
figure".*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90 s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
