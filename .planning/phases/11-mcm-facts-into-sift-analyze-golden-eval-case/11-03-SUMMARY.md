---
phase: 11-mcm-facts-into-sift-analyze-golden-eval-case
plan: 03
subsystem: cli, eval
tags: [mcm, cli, eval, golden-case, citation-provenance, regression-gate, determinism]
requires:
  - "pipeline/hypothesise.py::hypothesise(mcm_thresholds=...) — the MCM injection chokepoint (11-02)"
  - "pipeline/mcm_facts.py::render_mcm_facts (11-01)"
  - "config.py::SiftConfig.mcm.thresholds (McmThresholdsConfig)"
  - "eval/runner.py::run_case + eval/truth.py::Truth (yaml.safe_load, extra=forbid)"
provides:
  - "cli.analyze threads mcm_thresholds=config.mcm.thresholds into hypothesise (no new flag, D-17)"
  - "eval/cases/mcm-denial/ — the 7th golden case (frozen truth.yaml + README + committed slice)"
  - "citation_validity_rate documented + proven as the MCM-sensitive metric for the case (T-11-06)"
affects:
  - "sift eval now scores an MCM denial case and exits non-zero on its regression (MCM-07/EVAL-03)"
tech-stack:
  added: []
  patterns:
    - "one-line config threading at the CLI (mirrors kb_context=), no new CLI surface (D-17)"
    - "golden case reuses a committed, validated fixture verbatim (D-18) — no synthetic authoring"
    - "MCM-sensitivity via citation_validity_rate, proven by an injection-on/off run_case diff"
key-files:
  created:
    - eval/cases/mcm-denial/input/hartford_deny_slice.log
    - eval/cases/mcm-denial/truth.yaml
    - eval/cases/mcm-denial/README.md
  modified:
    - src/sift/cli.py
    - tests/test_mcm_analyze.py
    - tests/test_eval_cases.py
decisions:
  - "required_evidence is matched by run_case against the CLUSTER EXEMPLARS (raw log), not the injected MCM block — so the MCM-sensitive metric is citation_validity_rate, documented in truth.yaml/README and proven by a dedicated test (resolves the plan-checker vacuous-gate warning, T-11-06)."
  - "MCM-off is simulated by monkeypatching hypothesise.render_mcm_facts to ('', set()) — the minimal, honest 'remove the injection' lever; the same cited denial id then flags."
  - "The denial event_id is stable across ingest locations (relpath 'hartford_deny_slice.log' + byte offset), so a MockTransport handler can cite it before run_case ingests."
metrics:
  duration: "~30 min"
  completed: 2026-07-19
  tasks: 2
  files: 6
  commits: 5
status: complete
---

# Phase 11 Plan 03: MCM Facts at the `sift analyze` CLI + Golden Eval Case Summary

`sift analyze` now threads `config.mcm.thresholds` into the MCM injection built at
the `hypothesise` chokepoint in Plan 02 — a single additive kwarg, no new CLI flag
(D-17) — so an operator's `[mcm.thresholds]` override reaches the injected,
cited MCM facts and composes with `--kb`. The 7th golden case
`eval/cases/mcm-denial/` reuses the committed Hartford deny slice verbatim (D-18)
with a frozen `truth.yaml`; `sift eval` discovers it, ingests it via dsserrors
auto-sniff, and scores it as a positive case, exiting non-zero on regression
(MCM-07 / EVAL-03).

## What was built

- **`src/sift/cli.py`** — `analyze` passes `mcm_thresholds=config.mcm.thresholds`
  (the same `McmThresholdsConfig` object `sift mcm` uses at cli.py:1036) to the
  existing `hypothesise(...)` call, beside `kb_context=`. One line, no new option,
  injection still driven by whether `analyse_mcm` returns episodes (D-17).
- **`eval/cases/mcm-denial/input/hartford_deny_slice.log`** — the committed
  `tests/fixtures/mcm/hartford_deny_slice.log` copied byte-for-byte (D-18); auto-
  sniffs as dsserrors, so `sift eval` ingests it with no `--adapter` override.
- **`eval/cases/mcm-denial/truth.yaml`** — frozen ground truth
  (`expect_no_incident: false`); `root_cause` names the working-set-driven MCM
  denial; `required_evidence` (`Contract Request Failed`, `MCM denial state`,
  `memory is running low`) matches the exemplars (retrieval 3/3); `acceptable_keywords`
  any-of {memory, MCM, working set, denial}. A header documents that
  `citation_validity_rate`, not retrieval, is the MCM-sensitive metric.
- **`eval/cases/mcm-denial/README.md`** — case origin, the deterministic denial
  figures (AvailableMCM = 0, working set 65.4% of IServer virtual, denial at
  `2026-04-07 12:39:47.230`), and the MCM-sensitivity rationale + proof pointer.
- **`tests/test_mcm_analyze.py`** — two CLI-level tests: an e2e `analyze` run
  (CliRunner + `httpx.MockTransport`) surfaces the MCM denial fact line and cites
  the denial event validly (clean exit 0, never a crash); a config-threading test
  where an `[mcm.thresholds]` override flips a flag tier warn→critical in the
  injected block, proving the CLI threads the config object, not a default.
- **`tests/test_eval_cases.py`** — suite is now the seven cases; the MCM case is
  discovered, ingests via dsserrors (denial banner + AvailableMCM grant lines),
  and scores as a positive case (not run_failed). A sensitivity test proves
  `citation_validity_rate` is `1.0` with injection and `< 1.0` once
  `render_mcm_facts` is stripped — removing the injection turns the case red.

## Deviations from Plan

None — plan executed as written. The MCM-sensitivity guard folded into Task 2's
`<action>` was resolved by confirming `run_case` matches `required_evidence`
against cluster exemplars only, then designating `citation_validity_rate` the
MCM-sensitive metric and proving it (the plan's own fallback path when the runner
matches exemplars). The TDD RED→GREEN split per task is the plan's convention, not
a deviation.

## Threat mitigations verified

- **T-11-05 (YAML RCE):** `truth.yaml` is parsed only by `eval/truth.py`'s
  `yaml.safe_load` + `Truth(extra="forbid")`; the new case adds no custom tags.
  `test_every_truth_yaml_loads` covers it.
- **T-11-06 (vacuous gate / frozen-truth):** the MCM case is a positive case whose
  MCM-sensitive metric (`citation_validity_rate`) genuinely regresses when the
  injection is removed — proven by `test_mcm_denial_citation_validity_is_mcm_sensitive`.
  `truth.yaml` was authored before any tuning.
- **T-11-04 (prompt injection via MCM text):** the CLI change only threads a config
  object; values are already `sanitise`d in the Plan 01 renderer. No new untrusted
  surface.
- **T-11-SC (installs):** zero new packages this plan.

## Verification

- `uv run pytest tests/test_mcm_analyze.py -x` — 8 passed (CLI threading e2e +
  config threading + the Plan 02 injection tests).
- `uv run pytest tests/test_eval_cases.py -x` — 7 passed (discovery, dsserrors
  ingest, positive scoring, MCM-sensitivity).
- Phase gate: `uv run ruff check` clean, `uv run pyright` 0 errors,
  `uv run pytest` **536 passed / 8 deselected**.

## Known Stubs

None. The CLI threads real config; the golden case is fully wired and frozen; the
MCM-sensitivity of the regression gate is proven, not asserted vacuously.

## Self-Check: PASSED

All created/modified files exist on disk; all five per-task commits (bf7515c,
e554e4f, 5d6569b, 50cbc9d, cdfbd17) are in git history; full done-gate green.
