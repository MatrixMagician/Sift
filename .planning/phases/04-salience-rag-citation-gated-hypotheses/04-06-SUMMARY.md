---
phase: 04-salience-rag-citation-gated-hypotheses
plan: 06
subsystem: rag
tags: [rag, never-crash, gap-closure, degrade, inference-client, robustness]
status: complete
gap_closure: true
requires:
  - "04-04: hypothesise() + Outcome state machine (the generation try/except)"
  - "04-03: InferenceClient.chat(response_format=) — the malformed-response boundary"
  - "04-05: cli.analyze failed→exit 1 mapping (already wired, unchanged)"
provides:
  - "Never-crash on a malformed/empty 200 inference response (G1, RAG-03)"
  - "client.chat() normalises empty/whitespace-only content to a malformed-response ValueError"
  - "hypothesise() generation handler maps (httpx.HTTPError, ValueError) to a clean failed run"
affects:
  - src/sift/pipeline/hypothesise.py
  - src/sift/llm/client.py
  - tests/test_hypothesise.py
tech-stack:
  added: []
  patterns:
    - "One guard at the shared boundary: client.chat() is the single point every malformed-response shape routes through"
    - "Malformed/empty 200 body → failed (exit 1, nothing persisted), NOT degraded (exit 3, persists raw) — symmetric with transport failure"
    - "Broadened except is precise: the only ValueError source inside the try is client.chat (_validate swallows its own; _assemble's zip runs before the try)"
key-files:
  created: []
  modified:
    - src/sift/pipeline/hypothesise.py
    - src/sift/llm/client.py
    - tests/test_hypothesise.py
decisions:
  - "A no-choices / absent-content / empty-content 200 body maps to failed (exit 1), not degraded (exit 3): it produced nothing inspectable, so persisting an empty triage_raw would mislead CI — symmetric with the existing transport-failure→failed path"
  - "Empty/whitespace-only content is a malformed no-usable-content response (reasoning model that exhausts its budget on reasoning_content, finish_reason 'length'), unified with the existing no-choices/absent-content ValueErrors at the one boundary all callers route through"
requirements: [RAG-03]
metrics:
  duration_minutes: 3
  tasks: 2
  files_changed: 3
  tests_total: 311
  completed: 2026-07-17
---

# Phase 4 Plan 06: Gap G1 — Never-Crash on Malformed/Empty Inference Response Summary

Closed gap G1 (RAG-03 never-crash): a reasoning/empty/"no choices" 200 inference response now maps to a clean `failed` Outcome (exit 1, nothing persisted) instead of crashing `sift analyze` with an uncaught `ValueError` traceback.

## What Was Built

**Root cause (from live UAT, Qwen3.5-27B reasoning model):** `hypothesise()` wrapped the generation state machine in `except httpx.HTTPError` only. `client.chat()` raises a plain `ValueError` — not an `httpx.HTTPError` — on a malformed-but-200 body (no `choices`, absent/non-string `content`), so it escaped the Outcome machinery and the CLI handler as a raw traceback. Additionally, empty/whitespace-only content (a reasoning model that exhausts its budget on `reasoning_content`, `finish_reason: "length"`) passed through `chat()` silently as `""`.

**Fix (one guard at the shared boundary, root-cause not symptom):**
1. `src/sift/llm/client.py` — `chat()` now raises `ValueError("chat response has empty content")` on empty/whitespace-only content, unifying it with the existing no-choices/absent-content guards. Every malformed shape surfaces as one `ValueError` at the one boundary all callers route through.
2. `src/sift/pipeline/hypothesise.py` — the generation-call handler broadened from `except httpx.HTTPError:` to `except (httpx.HTTPError, ValueError):`, mapping to the SAME clean `failed` Outcome it already returned (hypotheses=None, raw=None, degraded=False, failed=True). Never a raw traceback.

**Tests (`tests/test_hypothesise.py`):** extended the `_handler` fixture with an optional `raw_body` param (returns a verbatim 200 JSON body, bypassing the content-envelope queue) and added three regression tests — `test_malformed_generation_no_choices`, `_absent_content`, `_empty_content` — each asserting a clean failed run with nothing persisted and no raise.

## Failed-vs-Degraded Decision

The malformed/empty 200 body maps to `failed` (exit 1), NOT `degraded` (exit 3).

`degraded` exists for a run that PRODUCED inspectable output later rejected (malformed JSON or bad citations), where the raw text is persisted as `triage_raw` so an operator can see what the model returned. A no-choices / absent-content / empty-content response produced NOTHING inspectable — the same situation as a transport failure that produced no output, which the existing code already maps to `failed`/exit 1. Mapping this to `failed` keeps the two "nothing was produced" cases symmetric and honest; mapping to `degraded` would persist an empty, useless `triage_raw` and mislead CI scripting. Recorded in a one-line code comment on the broadened `except`.

## Why the Broadened Except Is Safe

Inside the generation `try` the only `ValueError` source is `client.chat()` on a malformed response: `_validate` swallows its own `ValueError` (returns `(None, error)`), and `_assemble`'s `zip(strict=True)` runs before the `try`. So no legitimate error is masked and no existing degrade/citation-gate path changes.

## Deviations from Plan

None — plan executed exactly as written. Both tasks (RED tests, GREEN fix) landed as atomic commits.

## Verification

- `uv run pytest -q` — 311 passed, 2 deselected (perf-marked). The three new `test_malformed_generation_*` tests pass; all pre-existing phase-4 and full-suite tests unchanged.
- `uv run ruff check` — All checks passed.
- `uv run pyright` — 0 errors, 0 warnings, 0 informations.
- RED demonstrated before the fix: against unfixed source the three tests failed (no_choices/absent_content raised the uncaught `ValueError`; empty_content asserted the old degrade path).

## Commits

- `729c92c` test(04): add RED regression tests for malformed/empty 200 inference response (G1)
- `99996a5` fix(04): map malformed/empty 200 inference response to a clean failed run, never crash (G1, RAG-03)

## Threat Mitigation

T-04-06-D (high, DoS) mitigated: a malformed/empty 200 body no longer aborts `sift analyze` with a traceback. T-04-06-T (medium, tampering) mitigated: empty content normalised to a malformed-response ValueError at the shared boundary. No new dependency (boring-tech constraint held); `hypothesise.py` stays typer-free and print-free.
