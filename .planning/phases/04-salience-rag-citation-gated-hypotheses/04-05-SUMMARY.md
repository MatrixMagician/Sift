---
phase: 04-salience-rag-citation-gated-hypotheses
plan: 05
subsystem: cli
tags: [cli, rag, exit-codes, salience, hypotheses, sanitisation]
status: complete
requires:
  - "04-04: hypothesise() + Outcome state machine"
  - "04-02: salience.rank_clusters"
  - "04-01: HypothesisSet models + query_hypotheses / triage_* meta"
provides:
  - "sift analyze --hint/--since/--until/--top-clusters + 0/3/1 exit-code contract"
  - "sift show hypotheses (un-stubbed, sanitised render, citation flag)"
  - "ADR 0005 exit-code contract + --until incident-time anchor"
affects:
  - src/sift/cli.py
tech-stack:
  added: []
  patterns:
    - "Outcome -> exit code mapping (failed 1 / degraded 3 / success 0); Typer usage 2 reserved"
    - "whole-line _sanitise on every DB/model-sourced render line (WR-01/T-04-03)"
    - "empty --filter allowlist so an unsupported filter fails loudly (exit 2)"
    - "--until doubles as the salience incident-time anchor (no separate flag)"
key-files:
  created:
    - docs/decisions/0005-analyze-exit-codes.md
  modified:
    - src/sift/cli.py
    - tests/test_cli.py
    - tests/test_analyze.py
decisions:
  - "3 is the degraded exit code — lowest free code that avoids Typer/Click usage-error 2 (ADR 0005, CLI-04)"
  - "--until is the incident-time anchor (falls back to case end); no separate --incident-time flag (RESEARCH Q3)"
  - "sift show hypotheses filter allowlist is empty for M4 — any --filter fails loudly rather than being silently ignored"
metrics:
  duration_minutes: 12
  tasks: 3
  files_changed: 4
  tests_total: 308
  completed: 2026-07-17
---

# Phase 4 Plan 5: Salience/RAG CLI — the vertical slice completes Summary

`sift analyze <case>` now runs the full triage slice — embed → cluster → label → salience → citation-gated hypotheses — with `--hint/--since/--until/--top-clusters` scoping and a scriptable 0/3/1 exit-code contract; `sift show hypotheses` is un-stubbed and renders the persisted, ranked hypotheses safely (whole-line sanitised, invalid citations FLAGGED).

## What was built

**Task 1 — analyze wiring + exit codes (commit 92ed87e)**
- Extended `analyze` with `--hint` (verbatim into the prompt, never parsed as a time), `--since`/`--until` (ISO 8601, UTC-normalised via a new `_parse_moment` helper; a bad value is a usage error → exit 2), and `--top-clusters` (default `_DEFAULT_TOP_CLUSTERS = 12`).
- After the existing embed/cluster/label leg (unchanged — same SSRF guard, `_make_http_client`, `cluster_and_label`, and both `finally: http.close()` / `finally: store.close()`), `analyze` calls `hypothesise(...)` with `incident_time = <parsed --until or None>`, `since`, `until`, `hint`, `top_clusters`, `ctx_fallback=_TRIAGE_CTX_FALLBACK`, `reserve_out=_TRIAGE_RESERVE_OUT`, all within the still-open client lifecycle.
- The run `Outcome` maps to exit codes: `failed → 1`, `degraded → 3` (stderr banner + `Hypotheses: N (degraded)`), else `0`. SSRF refusal / transport error / missing case stay 1; Typer usage errors stay 2.

**Task 2 — un-stub `show hypotheses` (commit 62edb71)**
- Replaced the Phase-4-pending stub with a real branch modelled on `show clusters`: reads `store.query_hypotheses()`, renders one line per hypothesis (`hyp_index  confidence  OK|FLAGGED  title`) plus a `cites:` line, passing the COMPLETE line through `_sanitise` (WR-01 whole-line, T-04-03).
- A degraded run (`triage_degraded == "1"`) prints a stderr banner; an un-analysed case prints "No hypotheses yet; run 'sift analyze' first" and exits 0.
- `_FILTER_KEYS["hypotheses"] = ()` — an empty allowlist so any `--filter` fails loudly (exit 2) rather than being silently ignored (fail-loud culture).

**Task 3 — ADR 0005 + `--help` table (commit f72f4dc)**
- `docs/decisions/0005-analyze-exit-codes.md` records the 0/3/1/2 contract (3 chosen because it is the lowest free code avoiding Typer's usage-error 2), citing CLI-04 and SPEC §5.8, and documents `--until` doubling as the salience incident-time anchor (RESEARCH Q3).
- Added the exit-code table + incident-time note to the `analyze` docstring (renders in `--help` via Click's `\b` no-rewrap marker).

## Deviations from Plan

None — plan executed as written. The `--until`-as-incident-anchor clarification noted in the task brief was already the plan's intent and is implemented and documented (ADR + `--help`).

## Tests

- `tests/test_analyze.py`: `_handler` updated to branch on the `response_format` key — the generation call is served a valid `HypothesisSet` (default: empty set, trivially cited ⊆ prompted, exit 0), the label call keeps its prior behaviour. All existing analyze/show-clusters tests stay green.
- `tests/test_cli.py`: new exit-code matrix via `CliRunner().invoke(...).exit_code` — 0 (valid model whose citation is a genuinely prompted id, RAG-02 e2e, persisted row `citations_valid=True`), 3 (malformed output twice; and separately an invalid citation FLAGGED), 1 (missing case, SSRF refusal), 2 (malformed `--since`). New `show hypotheses` tests: render + `OK` marker + cited id; `FLAGGED` + degraded stderr banner; hostile C1/bidi title stripped whole-line; empty-before-analyze message; `--filter` rejected. New `analyze --help` assertion for the exit-code + incident-time wording.
- Hostile-byte fixtures use `U+202E`/`\x9b` escape sequences — zero raw control/bidi bytes on disk (verified).

## Gate

`uv run pytest && uv run ruff check && uv run pyright` all clean: **308 passed**, ruff clean, pyright 0 errors.

## Requirements

- RAG-02 (citation-gated hypotheses surfaced e2e) — delivered at the CLI.
- CLI-04 (exit-code contract) — delivered + documented (ADR 0005, `--help`).
- RAG-06 (salience scoping via `--since`/`--until`/`--top-clusters` + incident anchor) — delivered.
- STORE-04 (show target filter allowlist) — extended with the `hypotheses` target.

## Self-Check: PASSED
