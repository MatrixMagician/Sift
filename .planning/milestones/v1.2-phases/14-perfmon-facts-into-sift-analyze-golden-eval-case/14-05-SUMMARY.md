---
phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case
plan: "05"
subsystem: eval-harness
tags: [perfmon, eval, golden-case, citation-validity, regression-gate, PERF-08, EVAL-03]
requires:
  - "eval case perfmon-denial input pair (14-01, shipped)"
  - "render_perfmon_facts spliced into hypothesise() (14-03/14-04, shipped)"
  - "sift.eval.runner.run_case + citation_validity_rate metric (Phase 10, shipped)"
provides:
  - "perfmon-denial golden case (truth.yaml + README) discovered by sift eval as the 8th case"
  - "citation-sensitivity regression gate proving the perfmon path is non-vacuous (PERF-08)"
affects:
  - "sift eval suite: 7 -> 8 golden cases; the frozen truth.yaml is a regression tripwire"
tech-stack:
  added: []
  patterns:
    - "mirror the mcm-denial golden case wiring verbatim for a new deterministic-injection case"
    - "citation-sensitivity test: strip the renderer at the hypothesise chokepoint, assert citation_validity_rate < 1.0"
key-files:
  created:
    - eval/cases/perfmon-denial/truth.yaml
    - eval/cases/perfmon-denial/README.md
  modified:
    - tests/test_eval_cases.py
decisions:
  - "The perfmon-denial required_evidence regexes are the same three denial-log strings as mcm-denial (Contract Request Failed / MCM denial state / memory is running low): the overlapping fixture IS the denial log, and retrieval is matched against raw exemplars (insensitive to injection by construction, Assumption A2) — so retrieval is correctly NOT the perfmon-sensitive metric."
  - "Stripping ONLY render_perfmon_facts (not render_mcm_facts) is sufficient for the sensitivity test because the cited perfmon id is a dssperfmon sample disjoint from the MCM denial boundary ids — this isolates the perfmon-correlation path (mcm-denial's own test must strip both, since its denial id is citable via either block)."
metrics:
  tasks: 2
  files_changed: 3
  duration_min: 6
  completed: 2026-07-20
status: complete
---

# Phase 14 Plan 05: Perfmon Golden Eval Case + Regression Gate Summary

Registered `perfmon-denial` as the 8th frozen golden case and proved its
regression gate has teeth: `sift eval` discovers and positively scores the case,
and a citation-sensitivity test shows that removing the perfmon correlation
injection turns the case red (`citation_validity_rate` drops below its 1.0 floor).
This delivers **PERF-08** — the eval CI contract now fails when perfmon
correlation output regresses.

## What was built

- **`eval/cases/perfmon-denial/truth.yaml`** — frozen ground truth mirroring
  `mcm-denial`: a British-English `root_cause` describing the working-set-driven
  memory-pressure denial with the corroborating counter trend; three
  `required_evidence` regexes (`Contract Request Failed`, `MCM denial state`,
  `memory is running low`) each verified present in the denial log and yielding
  `retrieval_hit_rate == 1.0`; perfmon-flavoured `acceptable_keywords`
  (memory / MCM / working set / denial / counter); `expect_no_incident: false`.
  Carries the frozen-before-tuning header and the perfmon-sensitivity note.
- **`eval/cases/perfmon-denial/README.md`** — documents the overlapping 14-01 pair
  origin (and why the raw non-overlapping Hartford pair was not used), the
  incident, and the perfmon-sensitivity guard: `citation_validity_rate` is the
  injection-sensitive metric because a perfmon citation is valid only via the
  perfmon block, whose ids are disjoint from the MCM boundary ids.
- **`tests/test_eval_cases.py`** — `perfmon-denial` added to `_EXPECTED_CASES`;
  the suite-count test renamed/retuned to assert exactly eight cases; a
  discovery/positive test (`test_perfmon_denial_case_discovered_and_scored_positive`);
  and the citation-sensitivity test
  (`test_perfmon_denial_citation_validity_is_perfmon_sensitive`) plus a
  `_citable_perfmon_id` helper that ingests the case and returns a real
  `dssperfmon` at-denial id printed by `render_perfmon_facts`.

## Non-vacuous proof (the load-bearing point, PERF-08 / T-14-10)

- **GREEN with injection ON:** a hypothesis citing the real `dssperfmon` at-denial
  id passes the citation gate — `render_perfmon_facts` unions that id into
  `prompted_ids` — so `citation_validity_rate == 1.0`.
- **RED with injection OFF:** monkeypatching `hypothesise.render_perfmon_facts`
  to `("", set())` removes the id from `prompted_ids`; the SAME citation is now
  flagged and `citation_validity_rate < 1.0` — the case regresses, so `sift eval`
  would exit non-zero.
- **Counterfactual (fail-fast rule):** the sensitivity test passed on first run,
  so I temporarily neutered the strip (left the perfmon block intact in the "off"
  branch) and confirmed the test FAILS with `assert 1.0 < 1.0` — proving the teeth
  come specifically from stripping the perfmon renderer, and that the perfmon id
  is citable via the perfmon block alone (stripping `render_mcm_facts` is not
  needed). The test was restored byte-identically before commit.

## Deviations from Plan

**1. [Rule 3 — blocking gate fix] Shortened an over-length assert message.**
- **Where:** Task 2, `_citable_perfmon_id` assert message (89 > 88 cols, E501).
- **Fix:** trimmed the message to `"perfmon-denial must print >=1 citable dssperfmon id"`; folded into the Task 2 commit (local-only) to keep it atomic.
- **Impact:** none on behaviour; ruff clean.

No other deviations: no bugs, no missing critical functionality, no auth gates, no architectural changes. `truth.yaml` was authored before any tuning and never edited to make a run pass (prohibition honoured).

## Deferred Issues (out of scope for 14-05)

- **Live `sift eval` (EVAL-03) exits non-zero in this sandbox for an unrelated
  reason:** the local Lemonade endpoint (`:13305`) returns `400 Bad Request` on
  `/v1/embeddings` — the loaded model does not support embeddings (the documented
  ONNX/OGA-recipe caveat: `/v1/embeddings` needs a `llamacpp`/`flm`-recipe model).
  This makes ALL 8 golden cases `run-failed` identically (mcm-denial, disk-full,
  memory-watermark-cascade, …), so it is a pre-existing operator-endpoint
  condition, NOT introduced by this plan. The authoritative zero-network gate is
  the offline MockTransport eval-harness suite (EVAL-05), which is fully green.
  Logged in `deferred-items.md`.

## Known Stubs

None. The golden case is complete: frozen truth, README, discovery + sensitivity
tests all present and green.

## Verification

- `uv run pytest tests/test_eval_cases.py tests/test_perfmon_analyze.py -q` → 13 passed.
- Full gate: `uv run ruff check` → All checks passed; `uv run pyright` → 0 errors,
  0 warnings; `uv run pytest -q` → **658 passed, 8 deselected** (up from 657 —
  two new eval tests, one pre-existing test renamed).
- `sift eval` discovers `perfmon-denial` as the 8th case (visible in the suite
  table). Live exit-0 requires a llamacpp/flm-recipe embeddings model on the local
  endpoint (EVAL-03 operator gate); the offline harness is the zero-network proof.
- PERF-08 delivered: the perfmon regression gate is non-vacuous, proven by the
  counterfactually-verified citation-sensitivity test.

## Commits

- `899a057` — feat(14-05): author frozen truth.yaml + README for perfmon-denial
- `c297054` — feat(14-05): register perfmon-denial + prove citation-sensitivity gate (PERF-08)

## Self-Check: PASSED

- `eval/cases/perfmon-denial/truth.yaml` — FOUND
- `eval/cases/perfmon-denial/README.md` — FOUND
- `tests/test_eval_cases.py` (perfmon-denial tests) — FOUND
- commit `899a057` — FOUND; commit `c297054` — FOUND
