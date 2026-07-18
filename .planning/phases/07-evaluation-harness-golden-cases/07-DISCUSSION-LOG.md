# Phase 7: Evaluation Harness & Golden Cases — Discussion Log

**Mode:** `--auto` (fully autonomous — no user questions; recommended defaults chosen)
**Date:** 2026-07-18

> Human-reference audit trail only. Not consumed by downstream agents.
> Canonical output is `07-CONTEXT.md`.

## Gray areas auto-selected

`[--auto] Selected all gray areas: Golden Suite Composition, truth.yaml Schema & Matching, sift eval CLI & Metrics, Threshold Gating & CI Exit, LLM-as-judge, Harness Architecture.`

## Auto-resolved decisions

| Area | Question | Selected (recommended default) | → CONTEXT |
|------|----------|--------------------------------|-----------|
| Golden Suite Composition | How many cases and which scenarios? | 6 cases: 5 SPEC exemplars + fold in the 3 ROADMAP-mandated shapes (dependency-timeout = mixed-tz; distinct quiet-cause; distinct negative) | D-01 |
| Golden Suite Composition | truth.yaml frozen before tuning? | Yes — committed before any prompt tuning, frozen ground truth | D-02 |
| truth.yaml Schema | How do evidence/keyword matches work? | `required_evidence` regex vs cluster templates (retrieval hit rate); `acceptable_keywords` any-of case-insensitive vs title+narrative (hit@k) | D-03 |
| truth.yaml Schema | How is the negative case scored? | `expect_no_incident: true` marker — pass when no over-confident root cause emitted | D-04 |
| sift eval CLI & Metrics | Output format & signature? | `sift eval [--suite <dir>] [--json]`; text table default, `--json` machine-readable; fills cli.py:956 stub | D-05 |
| sift eval CLI & Metrics | How is determinism drift measured? | N=2 repeated analyze runs, compare via M6 `normalise_for_determinism` byte-equality | D-06 |
| Threshold Gating | What gates the exit code? | `eval/thresholds.toml` per-metric floors; non-zero if any keyword metric below floor; follows ADR 0005/0007 | D-07 |
| LLM-as-judge | Default & gating role? | `--judge` opt-in, off by default; versioned `prompts/judge.md`; advisory-only, never gates | D-08 |
| LLM-as-judge | Test strategy given no-network rule? | Default run fully offline (EVAL-05 fake client); judge path `@pytest.mark.live`, excluded from socket-blocked suite (REPT-04 pattern) | D-09 |
| Harness Architecture | Where does it live / how invoked? | New `src/sift/eval/` package driven by the CLI; temp case.db per case; injected fake client; add PyYAML for truth.yaml | D-10 |

## Deferred ideas

- Real sanitised customer golden cases (private, later — SPEC §6).
- Report redaction/sanitisation pass (REPT-05) — its own concern.
- Salience-weight retuning (SPEC open question #4) — later tuning pass.
- CI pipeline wiring — Phase 8; this phase only guarantees the CI-friendly exit code.

## Claude's discretion (noted in CONTEXT)

- Synthetic log content/volume per case, regex specificity, table formatting, default `k` for hit@k (suggest k = number of hypotheses analyze emits, ~3).

---
*Auto-discussion completed 2026-07-18.*
