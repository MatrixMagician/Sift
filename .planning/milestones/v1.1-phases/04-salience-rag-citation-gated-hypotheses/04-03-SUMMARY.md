---
phase: 04-salience-rag-citation-gated-hypotheses
plan: 03
subsystem: llm
tags: [llm, constrained-decoding, rag, http-boundary]
requires:
  - "llm/client.py InferenceClient.chat (SPEC §5.6 single HTTP boundary)"
provides:
  - "chat(messages, *, response_format=None) — optional server-side constrained decoding"
affects:
  - "04-04 hypothesise.py — will call chat(response_format=...) with the llama.cpp schema shape"
tech-stack:
  added: []
  patterns:
    - "additive keyword-only param preserves all existing positional callers"
    - "llama.cpp response_format nesting: schema at response_format.schema (top-level), NOT OpenAI's response_format.json_schema.schema"
    - "test-the-request-body: capture httpx.Request via MockTransport, json.loads(request.content), assert shape"
key-files:
  created: []
  modified:
    - src/sift/llm/client.py
    - tests/test_llm_client.py
decisions:
  - "response_format is keyword-only and optional; cluster.py's label chat([...]) call is untouched (no new positional arg)"
  - "client stays generic — it does not build the schema dict; hypothesise.py (04-04) owns the llama.cpp shape"
  - "constrained decoding is best-effort transport; Pydantic validation downstream remains the load-bearing backstop"
metrics:
  duration: "~6 min"
  completed: 2026-07-17
  tasks: 1
  files: 2
status: complete
---

# Phase 4 Plan 3: Constrained-Decoding response_format on chat Summary

Added an optional, keyword-only `response_format` param to `InferenceClient.chat` so the triage call (RAG-03) can request server-side constrained decoding using llama.cpp's `{"type":"json_schema","schema":{...}}` shape — the first line of the validate→repair→degrade pipeline, living in the one module allowed to open HTTP.

## What Was Built

- **`chat(self, messages, *, response_format: dict[str, object] | None = None) -> str`** — when `response_format` is not None it is merged verbatim into the request payload after the `model` merge; otherwise the body carries no `response_format` key (unchanged behaviour). Every downstream defensive step (`_json_object`, choices/message/content extraction, `[:_MAX_CONTENT_CHARS]` cap) is untouched.
- **Docstring** documents the llama.cpp nesting (schema at `response_format.schema`, NOT OpenAI's deeper nesting), the never-send-`grammar` rule, and that the server constraint is best-effort while Pydantic validation is the backstop.
- **Two request-body-shape tests** (RED-first): `response_format` absent when not passed; when passed it appears verbatim and no `grammar` key is present. Both drive the outgoing `httpx.Request` through the existing `MockTransport` idiom — zero sockets.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 (RED) | failing request-body-shape test | eaa3639 | tests/test_llm_client.py |
| 1 (GREEN) | additive response_format param | 3bc53d8 | src/sift/llm/client.py, tests/test_llm_client.py |

## Deviations from Plan

None affecting scope. One incidental fix during GREEN: pyright rejected the test's nested dict literal against `dict[str, object]` (dict value-type invariance), resolved by adding an explicit `rf: dict[str, object]` annotation on the test fixture — a Rule 3 blocking-issue fix, test-side only, no production impact.

## Threat Surface

No new surface. `response_format` opens no new network path or endpoint (T-04-06 inherited `_assert_local` SSRF guard unchanged); response parsing stays defensive (T-04-04); only `response_format` is ever sent, never a co-`grammar` field (T-04-10).

## Verification

- `uv run pytest -q` — 285 passed, 2 deselected (new response_format tests green, no regression).
- `uv run ruff check` — clean.
- `uv run pyright` — 0 errors, 0 warnings.

## Self-Check: PASSED

- FOUND: src/sift/llm/client.py (chat signature includes response_format param)
- FOUND: tests/test_llm_client.py (two response_format tests)
- FOUND commit: eaa3639 (RED)
- FOUND commit: 3bc53d8 (GREEN)
