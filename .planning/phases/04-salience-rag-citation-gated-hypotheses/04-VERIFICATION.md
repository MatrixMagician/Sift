---
phase: 04-salience-rag-citation-gated-hypotheses
verified: 2026-07-17T00:00:00Z
status: gaps_found
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification_resolved:
  - test: "Live llama-server constrained-decoding round-trip accepts HypothesisSet.model_json_schema() ($defs/$ref)."
    result: passed
    note: "Run 2026-07-17 on Strix Halo / Lemonade v10.4.0. Server ACCEPTS the $defs/$ref schema (HTTP 200, no 400) — Open Question 1 resolved. `sift analyze` with the configured Qwen3-0.6B degraded gracefully (exit 3, flagged, no crash, zero invalid citations). See 04-UAT.md test 1 evidence."
gaps:
  - id: G1
    severity: high
    requirement: RAG-03
    summary: "reasoning/empty/'no choices' 200 inference response crashes `sift analyze` with an uncaught ValueError traceback (exit 1) instead of degrading/failing cleanly — violates the load-bearing never-crash invariant. Found via live UAT (Qwen3.5-27B reasoning model). Root cause + fix in 04-UAT.md §Gaps G1."
---

# Phase 4: Salience, RAG & Citation-Gated Hypotheses — Verification Report

**Phase Goal:** The core value ships — `sift analyze` turns clusters into ranked, evidence-cited root-cause hypotheses that cannot cite what the model was never shown.
**Verified:** 2026-07-17
**Status:** human_needed (all automated truths VERIFIED; one live-server UAT item outstanding, per 04-VALIDATION.md)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth (SC) | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `sift analyze` produces schema-valid JSON hypotheses (full SPEC §5.5 field set) with 100% citation validity after the permitted retry | ✓ VERIFIED | `HypothesisSet`/`Hypothesis` Pydantic models with `extra="forbid"` + `Literal` confidence (models.py:61-83); golden-path e2e `test_analyze_exit_0_with_valid_cited_hypotheses` asserts exit 0, 1 persisted hypothesis, `citations_valid is True`, `triage_degraded == "0"` (test_cli.py:990-1024); `test_citation_valid_golden` asserts all rows valid after one permitted retry |
| 2 | Every cited id exists in store AND was in the prompt (cited ⊆ prompted); bad-id regeneration is tested; still-invalid flagged never dropped | ✓ VERIFIED | `_all_cited_within`/`_row_citations_valid` gate against `prompted_ids` built from stored exemplar ids (hypothesise.py:320-332, 335-380); `test_flagged_badcite_twice` asserts `citations_valid is False`, `_BAD_ID in supporting_event_ids` (kept visible), `triage_degraded == "1"`; `test_regenerate_badcite_then_good` asserts exactly one regeneration; e2e `test_analyze_exit_3_on_invalid_citation` |
| 3 | JSON failures degrade gracefully (constrained decode → Pydantic → one repair → raw persisted + degraded, never crash); exit codes distinguish success/degraded/failure | ✓ VERIFIED | `_generate` = chat → `_validate` → exactly one `_repair_turn` → re-validate (hypothesise.py:228-246); `test_degrade_bad_json_twice` (2 calls, raw captured, no raise); `test_transport_error_is_failed_not_persisted`; exit 0/3/1 mapped in cli.py:801-823; `test_analyze_exit_3_on_malformed_output` asserts `triage_raw` persisted. Live-server constrained-decode acceptance → human item (backstop tested) |
| 4 | Clusters ranked by salience (severity, count, burstiness, novelty, temporal proximity to incident time), budgeted breadth-first | ✓ VERIFIED | `rank_clusters` with all five weighted features (salience.py:44-48, 196-211); incident_time derived from case-end when None; span clamped `max(span, _SPAN_FLOOR)`; `PromptBudget.fit` breadth-first in `_assemble` (hypothesise.py:189-194); tests cover severity/count ordering, tie-determinism, missing-ts neutral path |
| 5 | User can scope analysis with `--hint` free text and `--since/--until` time-window filters | ✓ VERIFIED | `analyze` gains `--hint/--since/--until/--top-clusters` (cli.py:625-673); hint appended verbatim, never parsed as time (hypothesise.py:195-196); `--since/--until` parsed ISO→UTC, bad value → Exit(2) (`test_analyze_exit_2_on_bad_since`); window filter at cluster granularity (`test_window_excludes_non_intersecting_cluster`) |

**Score:** 5/5 truths verified (0 present, behavior-unverified). One additive live-server UAT item routes the overall status to human_needed.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/models.py` | Hypothesis/HypothesisSet, extra=forbid | ✓ VERIFIED | Both models present, `ConfigDict(extra="forbid")`, `Literal["high","medium","low"]` |
| `src/sift/store.py` | migration 4 + StoredHypothesis + replace/query + triage_* meta | ✓ VERIFIED | `_migration_4` registered `4:` in `_MIGRATIONS`; `_HYP_COLUMNS` module constant; parameterised `?` binds (`# noqa: S608`); WR-01 coercion + `bool(citations_valid)` in query |
| `src/sift/pipeline/salience.py` | deterministic rank_clusters | ✓ VERIFIED | Pure module, five features + weights, `_SEVERITY_RANK` frozen, sort `(-score, cluster_id)` |
| `src/sift/llm/client.py` | additive chat(response_format=) | ✓ VERIFIED | Keyword-only param; llama.cpp shape passed through verbatim; defensive parse untouched |
| `src/sift/pipeline/hypothesise.py` | Outcome + state machine + citation gate + atomic persist | ✓ VERIFIED | Full assemble→generate→validate→repair→degrade→gate→persist; one `store.transaction()` |
| `src/sift/prompts/triage.md` | versioned prompt w/ untrusted-data guard | ✓ VERIFIED | Ships as package data; guard phrase, `Evidence:` header, `[evt:<id>]` token present |
| `src/sift/cli.py` | analyze flags + 0/3/1 exit codes; show hypotheses un-stubbed | ✓ VERIFIED | Outcome→exit mapping; real `hypotheses` branch with whole-line `_sanitise` |
| `docs/decisions/0005-analyze-exit-codes.md` | exit-code ADR | ✓ VERIFIED | Present (4023 bytes); 0/3/1/2 contract + --until incident-time anchor |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| hypothesise `prompted_ids` | citation gate | `_all_cited_within` subset check | ✓ WIRED | prompted_ids = set of printed exemplar event ids; cited ⊆ prompted ⊆ store transitively guaranteed (exemplars are stored rows) |
| hypothesise | llm/client.chat | `response_format=_schema_rf(HypothesisSet.model_json_schema())` | ✓ WIRED | llama.cpp `{"type":"json_schema","schema":…}` shape (hypothesise.py:287) |
| cli.analyze | hypothesise Outcome | failed→1, degraded→3, else 0 | ✓ WIRED | cli.py:803-823 |
| migration 4 | CaseStore open | `_MIGRATIONS` PRAGMA user_version runner | ✓ WIRED | `4: _migration_4` self-applies |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase test suite (hypothesise/salience/cli/analyze/models/store) | `uv run pytest tests/test_{hypothesise,salience,cli,analyze,models,store}.py -q` | 138 passed in 1.23s | ✓ PASS |
| Citation gate: bad-id twice → flagged, degraded, id kept | `test_flagged_badcite_twice` | passes | ✓ PASS |
| Atomic rollback: mid-persist failure → zero rows | `test_atomic_persist_rolls_back` | passes | ✓ PASS |
| Exit-code matrix 0/3/1/2 | analyze exit tests (test_cli.py:990-1104) | pass | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RAG-01 | 04-02 | Salience ranking (5 features + incident time) | ✓ SATISFIED | salience.py + test_salience.py |
| RAG-02 | 04-01, 04-04, 04-05 | analyze produces enforced-JSON hypotheses | ✓ SATISFIED | models + golden e2e exit-0 test |
| RAG-03 | 04-03, 04-04 | Constrained decode / validate / one repair / degrade | ✓ SATISFIED | `_generate` + degrade tests (live-server confirm = human item) |
| RAG-04 | 04-01, 04-04 | cited ⊆ prompted, regen max 1, flag | ✓ SATISFIED | `_citation_gate` + flagged/regenerate tests |
| RAG-06 | 04-02, 04-05 | --hint + --since/--until scoping | ✓ SATISFIED | analyze flags + window/hint tests |
| CLI-04 | 04-05 | Documented 0/3/1(/2) exit-code contract | ✓ SATISFIED | cli mapping + ADR 0005 + --help test |
| STORE-04 | 04-05 | show hypotheses target (partial-scope; hypotheses leg here) | ✓ SATISFIED | real show hypotheses branch + render/flag/empty tests |

No ORPHANED requirements — every ID declared in the five plans' frontmatter maps to REQUIREMENTS.md and is marked Complete for Phase 4.

### Anti-Patterns Found

None. No `TBD/FIXME/XXX` debt markers in any phase-modified source file. No stub returns on the render/data paths (the old `show hypotheses` Phase-4-pending stub is replaced with a real branch). SQL uses parameterised binds with module-constant column lists; untrusted model text is persisted verbatim and whole-line `_sanitise`'d only at render.

### Human Verification Required

**1. Live constrained-decoding round-trip (`$defs`/`$ref` acceptance)**

- **Test:** Run `sift analyze <golden-case>` against a real `llama-server -m <model>` doing schema-constrained decoding, sending `HypothesisSet.model_json_schema()` (contains `$defs`/`$ref` for the nested `Hypothesis`).
- **Expected:** Server accepts the `response_format` schema and returns schema-valid JSON on the first try (no repair). If it 400s on `$defs`, the run degrades cleanly (exit 3, raw persisted) — never crashes.
- **Why human:** Needs a live inference server; zero-network-in-tests forbids automating it. Sole manual-only item in 04-VALIDATION.md; the validate→repair→degrade pipeline is the automated backstop and is fully tested.

### Gaps Summary

No gaps. The load-bearing anti-hallucination invariant (RAG-04) is enforced and tested in both the unit matrix (tests/test_hypothesise.py) and the CLI exit-code matrix (tests/test_cli.py): `cited ⊆ prompted ⊆ store` is checked in-memory against the prompted-id universe; an out-of-prompt citation triggers exactly one regeneration and, if still invalid, is FLAGGED (`citations_valid=false`, offending id kept visible) with the run marked degraded and exit-mapped to 3 — never silently accepted. Malformed JSON repairs once then degrades with raw persisted, never crashing; transport errors return a failed Outcome that persists nothing (exit 1). All persistence is atomic within one `store.transaction()`.

Overall status is `human_needed` solely because of the single deferred live-server UAT confirmation (an additive check with a tested automated backstop), not because of any code deficiency. Every automated success criterion is VERIFIED.

---

_Verified: 2026-07-17_
_Verifier: Claude (gsd-verifier)_
