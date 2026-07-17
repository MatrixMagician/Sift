---
status: testing
phase: 04-salience-rag-citation-gated-hypotheses
source: [04-VERIFICATION.md]
started: 2026-07-17T00:00:00Z
updated: 2026-07-17T00:00:00Z
---

## Current Test

number: 1
name: Live llama-server constrained-decoding round-trip accepts the HypothesisSet schema ($defs/$ref)
result: passed
awaiting: none — resolved 2026-07-17 on the Strix Halo box (Lemonade Server v10.4.0, 127.0.0.1:13305)

## Tests

### 1. Live llama-server constrained-decoding round-trip accepts the HypothesisSet schema
expected: |
  Point Sift at a live constrained-decoding server and run `sift analyze` on the first golden
  case in a freshly created, isolated case directory. Confirm EITHER (a) schema-valid JSON on the
  first attempt with exit 0 and 100% citation validity, OR (b) if the build rejects local
  $defs/$ref, the run degrades to exit 3 with raw output persisted and marked degraded — never a
  crash.
result: passed
evidence: |
  Run 2026-07-17 on the Strix Halo box, Lemonade Server v10.4.0 (127.0.0.1:13305), llamacpp GGUFs
  (gen Qwen3-0.6B-GGUF, embeddings Qwen3-Embedding-0.6B-GGUF), isolated case dir.
  - `sift doctor`: generation + embeddings endpoints OK; REAL embedding round-trip OK (dim 1024);
    sqlite-vec v0.1.9 OK. Exit 0.
  - Case: 13 DSSErrors events → 100% coverage → 5 template groups → 2 clusters (labelled live).
  - Direct probe: POST /v1/chat/completions with response_format
    `{"type":"json_schema","schema": HypothesisSet.model_json_schema()}` (schema contains local
    `$defs`/`$ref`) returned HTTP 200 — the server ACCEPTS the $defs/$ref schema; NO 400.
    Open Question 1 (llama.cpp $defs/$ref acceptance) is RESOLVED.
  - `sift analyze` (Qwen3-0.6B): exit 3 (degraded), flagged output persisted, no crash, zero
    invalid citations accepted — the validate→repair→degrade + citation gate backstop worked.
  Caveat observed: Lemonade's llamacpp path ACCEPTS `response_format.schema` but does not appear
  to ENFORCE constrained decoding for this GGUF (returned free prose), so the degrade pipeline is
  load-bearing in practice, exactly as designed.

## Summary

total: 1
passed: 1
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

### G1 — reasoning/empty/"no choices" 200 response crashes `sift analyze` (never-crash invariant)
status: failed
severity: high
requirement: RAG-03
found: 2026-07-17 (live UAT, Strix Halo)
symptom: |
  Running `sift analyze` with a reasoning generation model (Qwen3.5-27B-GGUF) that exhausts its
  token budget on `reasoning_content` and returns a 200 body with empty/absent `message.content`
  (or no `choices`) causes an UNCAUGHT `ValueError("chat response has no choices")` traceback and
  exit 1 — a raw crash, violating the load-bearing "never crash — always degrade gracefully"
  invariant (CLAUDE.md LLM output contract; RAG-03).
root_cause: |
  `src/sift/pipeline/hypothesise.py` wraps the generation call in `except httpx.HTTPError`
  (~line 304) → maps transport errors to a clean `failed`/exit 1. But `client.chat()` raises a
  plain `ValueError` on a malformed-but-200 response (no/empty `choices`), which is NOT an
  `httpx.HTTPError`, so it escapes the Outcome machinery and the analyze CLI handler entirely.
expected: |
  A malformed/empty 200 inference response must map to a clean outcome — degrade (exit 3, flagged)
  or fail (sanitised one-line error, exit 1) — NEVER a raw Python traceback.
fix: |
  Broaden hypothesise.py generation-call handling to catch `ValueError` (malformed/empty response)
  alongside `httpx.HTTPError` and map to `failed` (or degrade). Also treat an empty-content 200
  (`finish_reason == "length"`, reasoning-only) as a malformed generation. Add regression tests to
  tests/test_hypothesise.py (RED first): a fake server returning `{"choices": []}` and one
  returning a choice with empty `content` → assert graceful failed/degraded outcome, no traceback.
