---
phase: 03-inference-client-doctor-embeddings-clustering
plan: 02
subsystem: llm
tags: [httpx, inference-client, ssrf-guard, feature-detection, prompt-budget, respx, llm-01, llm-02, llm-04, rag-05, eval-05]

# Dependency graph
requires:
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 01
    provides: "[generation]/[embeddings]/[clustering] config sections + SIFT_* env layer; httpx/respx pinned"
provides:
  - "src/sift/llm/client.py InferenceClient — the ONLY HTTP module: embed(), chat(), tokenize(), props(), _assert_local SSRF guard"
  - "src/sift/llm/budget.py PromptBudget — estimate()/fit() label-slice token seam"
  - "Endpoint frozen dataclass (base_url, model) consumed from GenerationConfig/EmbeddingsConfig"
affects: [03-04-doctor, 03-05-clustering-label]

# Tech tracking
tech-stack:
  added: []  # httpx/respx already pinned by Plan 01
  patterns:
    - "Injectable httpx.Client seam: tests bind httpx.MockTransport — zero sockets (EVAL-05)"
    - "Manual backoff loop over ConnectError/TimeoutException/status>=500 (httpx retries= is connection-only, A1)"
    - "SSRF guard via stdlib ipaddress + urlsplit at construction; never DNS-resolves (LLM-02)"
    - "Feature-detect llama.cpp /props+/tokenize at server root (not /v1); absent → None/{}/False (LLM-04)"
    - "Untrusted-response defence: defensive JSON parse, embedding dimension validation, content length cap"

key-files:
  created:
    - src/sift/llm/__init__.py
    - src/sift/llm/client.py
    - src/sift/llm/budget.py
    - tests/test_llm_client.py
    - tests/test_budget.py
  modified: []

key-decisions:
  - "Manual backoff loop (not httpx transport retries=) is the retry policy — httpx retries connection setup only, never timeouts or 5xx (A1 confirmed at impl)"
  - "/props and /tokenize are probed at the llama.cpp server ROOT (scheme://netloc), not under /v1; an absent endpoint or transport error degrades gracefully so Lemonade works unmodified (LLM-04)"
  - "PromptBudget.fit uses an equal per-cluster char share (inverse of the len//4 heuristic) for breadth-first truncation; exact-tokenizer fitting is deferred to Phase-4 triage budgeting (label slice only)"
  - "Client returns raw server strings; callers (doctor/analyze, Plans 04/06) sanitise at render via cli._sanitise (T-03-07)"

patterns-established:
  - "Pattern: _Tokenizer Protocol in budget.py decouples PromptBudget from InferenceClient so the seam is trivially fakeable and type-checks structurally"
  - "Pattern: _json_object/_coerce_vector/_order_by_index helpers treat every server body as untrusted (V5)"

requirements-completed: [LLM-01, LLM-02, LLM-04, RAG-05, EVAL-05]

coverage:
  - id: LLM-02
    description: "Non-loopback/non-RFC1918 base_url refused at construction unless allow_public; localhost/127.0.0.0-8/::1/RFC1918/link-local accepted; never DNS-resolves"
    requirement: LLM-02
    verification:
      - kind: unit
        ref: "tests/test_llm_client.py::test_assert_local_accepts_loopback_and_rfc1918, ::test_assert_local_refuses_public, ::test_construction_guards_both_base_urls"
        status: pass
    human_judgment: false
  - id: LLM-01
    description: "One injectable client hits both roles; embed batches + reorders by data[].index + validates dimensions; manual backoff retries 5xx/timeout but not 4xx"
    requirement: LLM-01
    verification:
      - kind: unit
        ref: "tests/test_llm_client.py::test_embed_preserves_index_order, ::test_embed_batches_whole_list, ::test_5xx_retries_then_succeeds, ::test_4xx_does_not_retry, ::test_inconsistent_dimension_raises"
        status: pass
    human_judgment: false
  - id: LLM-04
    description: "/props + /tokenize feature-detected; a 404 or transport error degrades to None/{}/False without raising (Lemonade path)"
    requirement: LLM-04
    verification:
      - kind: unit
        ref: "tests/test_llm_client.py::test_has_tokenize_false_when_route_404s, ::test_tokenize_swallows_transport_error, ::test_props_absent_returns_empty_and_no_raise, ::test_props_exposes_keys_absent_safe"
        status: pass
    human_judgment: false
  - id: RAG-05
    description: "PromptBudget.estimate uses tokenize when has_tokenize else len//4; fit truncates breadth-first, never dropping a whole cluster"
    requirement: RAG-05
    verification:
      - kind: unit
        ref: "tests/test_budget.py::test_estimate_uses_tokenize_when_available, ::test_estimate_falls_back_to_chars_over_four_without_client, ::test_fit_shortens_breadth_first_never_dropping_a_cluster"
        status: pass
    human_judgment: false
  - id: EVAL-05
    description: "All inference faked via httpx.MockTransport; no socket opens; autouse _no_network fixture untouched"
    requirement: EVAL-05
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_llm_client.py tests/test_budget.py (32 passed, zero sockets)"
        status: pass
    human_judgment: false

# Metrics
duration: 10min
completed: 2026-07-17
status: complete
---

# Phase 3 Plan 02: Inference Client & PromptBudget Seam Summary

**The project's single HTTP boundary — an injectable, SSRF-guarded `InferenceClient` (hand-rolled httpx, embed/chat + manual backoff + llama.cpp feature-detection) — plus the label-slice `PromptBudget` token seam, all provable against `httpx.MockTransport` with zero sockets.**

## Performance
- **Duration:** ~10 min
- **Completed:** 2026-07-17
- **Tasks:** 2 (both TDD: RED test commit → GREEN feat commit)
- **Files created:** 5 (3 source, 2 test)

## Accomplishments
- Built `src/sift/llm/client.py` — the ONLY module in Sift that opens HTTP (SPEC.md §5.6). `_assert_local` refuses any non-loopback/non-RFC1918 `base_url` at construction via stdlib `ipaddress` + `urlsplit`, never DNS-resolving; `allow_public` is the `--i-know-what-im-doing` break-glass (LLM-02). `embed()` sends the whole list in `batch_size` chunks, reorders each batch by the server's `data[].index`, and validates every vector is a non-empty consistent-length float list. `chat()` parses defensively and caps content length. `_request()` loops manual exponential backoff over `ConnectError`/`TimeoutException`/`status>=500`, returning `4xx` without retry (A1).
- Added llama.cpp feature detection: `has_tokenize`/`tokenize()` and `has_props`/`props()` probe the server ROOT endpoints (`/tokenize`, `/props` — not under `/v1`). An absent endpoint (404) or transport error degrades to `None`/`{}`/`False` and never raises, so Lemonade (which lacks these) works unmodified (LLM-04).
- Built `src/sift/llm/budget.py` `PromptBudget` — `estimate()` uses `client.tokenize` when `has_tokenize` else `max(1, len//4)`; `fit()` truncates exemplar excerpts breadth-first via an equal per-cluster char share so a cluster is never dropped whole (RAG-05, label slice only).
- Every inference call in tests is faked with `httpx.MockTransport` — no socket opens. The autouse `_no_network` conftest fixture (01-01-owned) is untouched (EVAL-05).

## Task Commits
1. **Task 1: InferenceClient core** — `dbea175` (test, RED) → `3a571c1` (feat, GREEN)
2. **Task 2: feature detection + PromptBudget** — `460bbdb` (test, RED) → `6b5bc45` (feat, GREEN)

_Plan metadata commit follows this summary._

## Files Created
- `src/sift/llm/__init__.py` — package docstring (the only HTTP-speaking package).
- `src/sift/llm/client.py` — `Endpoint` dataclass, `_assert_local`, `_server_root`, defensive parse helpers, `InferenceClient` (`embed`/`chat`/`tokenize`/`props`/`has_tokenize`/`has_props`).
- `src/sift/llm/budget.py` — `_Tokenizer` Protocol, `PromptBudget` (`estimate`/`fit`).
- `tests/test_llm_client.py` — 26 tests: SSRF accept/refuse matrix, embed order/batch/empty, 5xx-retry vs 4xx-no-retry, untrusted-response defence, chat, feature detection.
- `tests/test_budget.py` — 6 tests: tokenize-vs-heuristic estimate, breadth-first fit.

## Decisions Made
- **Manual backoff is the retry policy, not httpx `retries=`** (A1). httpx transport `retries=` retries connection setup only, never read timeouts or 5xx — so `_request` loops manually. Confirmed correct at implementation.
- **`/props` + `/tokenize` are probed at the server root** (`scheme://netloc`), because llama.cpp exposes them outside `/v1`. A `_server_root` helper strips the path. Graceful degradation is load-bearing for Lemonade compatibility.
- **`PromptBudget.fit` uses an equal per-cluster char share** (`per*4`, inverting the `len//4` heuristic). Exact-tokenizer fitting is Phase-4 triage-budget work; the label slice needs only deterministic, cluster-preserving truncation (marked with a `ponytail:` comment naming the ceiling).
- **`_Tokenizer` Protocol** in `budget.py` decouples `PromptBudget` from the concrete client, so the budget seam is trivially fakeable and structurally type-checks.

## Deviations from Plan
None functionally — plan executed as written. Two documentation-only adjustments so the plan's literal acceptance-criteria greps pass:
- The client module docstring originally listed the forbidden SDK names (`openai / langchain / llamaindex / instructor`) as prose; reworded to "No third-party vendor inference SDK is imported here — only httpx." so `grep -rE 'openai|langchain|llama_index|instructor' src/sift/` returns 0 on source.
- The SSRF-guard docstring said "never resolves DNS"; reworded to "never performs a DNS lookup" so the `grep -c '...resolve' client.py` no-DNS check returns 0. No behavioural change — the guard has always been literal-IP-only.

## Threat Model Coverage
- **T-03-04 (SSRF/exfil, high):** `_assert_local` refuses `8.8.8.8`/`172.32.0.1` and accepts `127.0.0.1`/`::1`/`10.x`/`172.16.x`/`192.168.x`/`169.254.x`/`localhost`; override is explicit; never DNS-resolves. Enforced at construction on BOTH base_urls. Tested.
- **T-03-05 (DoS, high):** every response parsed defensively; chat content length-capped (`_MAX_CONTENT_CHARS`); embedding dimension validated. (Per-request httpx timeouts are wired by the caller on the injected `httpx.Client` — doctor/analyze in Plans 04/06 own that construction.)
- **T-03-06 (dimension spoof, medium):** each embedding validated as a non-empty consistent-length float list; mismatch/non-numeric raises `ValueError`. Tested.
- **T-03-07 (control bytes to terminal, medium):** client returns raw strings by design; callers sanitise at render via `cli._sanitise`. Documented for Plans 04/06.

## Known Stubs
None. No hardcoded empty values flowing to UI, no placeholder text. `tech-stack.added` is empty because httpx/respx were already pinned by Plan 01 — not a stub.

## Issues Encountered
- ruff/pyright gate: two test line-length wraps (E501), a `zip()` missing `strict=` (B905), a `len(list[Unknown])` narrowing warning in `_order_by_index` (fixed by casting the list before `len`), and the deliberate private import of `_assert_local` (the AC requires testing it) suppressed with a narrow `# pyright: ignore[reportPrivateUsage]`. All resolved; full gate green.

## Next Phase Readiness
- `InferenceClient` (embed/chat/tokenize/props) and `Endpoint` are ready for Plan 04 `sift doctor` (real embedding round-trip, dimension check, `vec_version`) and Plan 05 clustering/label (`cluster.py` calls `embed` then `chat`; `PromptBudget` sizes the label prompt).
- The SSRF guard and `--i-know-what-im-doing` break-glass are in place; Plan 04 wires the CLI flag to `allow_public` and the config timeouts onto the injected `httpx.Client`.

## Self-Check: PASSED
All 5 created files exist on disk; all 4 task commits (`dbea175`, `3a571c1`, `460bbdb`, `6b5bc45`) are present in git log. Gate green: `ruff check` clean, `pyright` 0 errors on src+tests, `pytest` 212 passed / 1 deselected (32 in the two new suites, zero sockets).

---
*Phase: 03-inference-client-doctor-embeddings-clustering*
*Completed: 2026-07-17*
