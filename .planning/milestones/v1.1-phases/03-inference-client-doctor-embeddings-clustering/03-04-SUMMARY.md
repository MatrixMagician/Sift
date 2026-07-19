---
phase: 03-inference-client-doctor-embeddings-clustering
plan: 04
subsystem: cli
tags: [doctor, fail-fast, ssrf-guard, embeddings-round-trip, sqlite-vec, vec-version, llm-03, llm-02, eval-05]
status: complete

# Dependency graph
requires:
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 02
    provides: "InferenceClient (embed/chat/props) + Endpoint + _assert_local SSRF guard"
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 03
    provides: "store meta.embedding_dim + the vetted _load_sqlite_vec path"
provides:
  - "sift doctor: dependency-ordered fail-fast health check (LLM-03), exits non-zero at the first critical failure"
  - "InferenceClient.models(endpoint): GET /v1/models through the sole HTTP boundary"
  - "store.vec_version(): throwaway-connection sqlite-vec load probe reusing _load_sqlite_vec"
  - "cli._make_http_client seam: per-request httpx timeouts + MockTransport injection point"
  - "--i-know-what-im-doing / --model flags on doctor"
affects: [03-05-clustering-label, 03-06-analyze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-fast CLI orchestration: each critical check prints Error + raises typer.Exit(1) from None; stops at the first"
    - "REAL /v1/embeddings round-trip is the OGA/ONNX probe — capability never inferred from /v1/models (Pitfall 2)"
    - "Module-level _make_http_client seam lets tests bind httpx.MockTransport while the real SSRF guard still runs at construction"
    - "Whole-line _sanitise on every server-supplied string (model IDs, error text) before printing"

key-files:
  created:
    - tests/test_doctor.py
  modified:
    - src/sift/cli.py
    - src/sift/llm/client.py
    - src/sift/store.py

key-decisions:
  - "Added InferenceClient.models(endpoint) rather than reimplementing GET /v1/models in cli.py — client.py is the ONLY HTTP module (SPEC §5.6)"
  - "Added public store.vec_version() reusing the vetted _load_sqlite_vec (enable→load→re-lock) rather than duplicating the native-extension surface in cli.py (T-03-09)"
  - "An OGA/ONNX empty-data embedding makes client.embed() raise ValueError; doctor translates ANY embed failure at step 3 into the named message (the endpoint was already proven reachable at step 2)"
  - "Determinism WARNING only fires when /props is present and signals risk (n_parallel>1 or seed<0); an absent /props (Lemonade → {}) warns nothing"

requirements-completed: [LLM-03, LLM-02, EVAL-05]

coverage:
  - id: LLM-03
    description: "doctor fail-fast order; real embedding round-trip; OGA/ONNX named message; dim-mismatch names both dims; vec_version check; determinism WARNING"
    requirement: LLM-03
    verification:
      - kind: unit
        ref: "tests/test_doctor.py::test_healthy_server_passes, ::test_oga_onnx_empty_embedding_fails_with_named_message, ::test_dimension_mismatch_names_both_dims, ::test_unreachable_generation_stops_before_embeddings, ::test_multi_slot_warns_but_passes"
        status: pass
    human_judgment: false
  - id: LLM-02
    description: "doctor refuses a non-loopback/non-RFC1918 endpoint unless --i-know-what-im-doing"
    requirement: LLM-02
    verification:
      - kind: unit
        ref: "tests/test_doctor.py::test_public_endpoint_refused_without_override, ::test_public_endpoint_allowed_with_override"
        status: pass
    human_judgment: false
  - id: EVAL-05
    description: "doctor fully exercised against a fake server via MockTransport; zero sockets; live variant @pytest.mark.live excluded by default"
    requirement: EVAL-05
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_doctor.py (7 passed, 1 deselected — the live test)"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-17
---

# Phase 3 Plan 04: sift doctor Fail-Fast Health Check Summary

**`sift doctor` is now a dependency-ordered, fail-fast health check that verifies both inference endpoints with real round-trips (including an actual `/v1/embeddings` call that catches Lemonade's OGA/ONNX recipe), checks the returned dimension against any existing case index, proves sqlite-vec loads, and warns on determinism-breaking config — stopping at the first critical failure with a non-zero exit, all proven against a fake server with zero sockets.**

## Performance
- **Duration:** ~12 min
- **Completed:** 2026-07-17
- **Tasks:** 2 (implementation, then tests)
- **Files:** 1 created, 3 modified

## Accomplishments
- Replaced the `doctor` stub with the D-02 fail-fast sequence in `src/sift/cli.py`: (1) construct the `InferenceClient` — the SSRF guard refuses a public endpoint unless `--i-know-what-im-doing`; (2) `GET /v1/models` on the generation endpoint [critical if unreachable]; (3) same on the embeddings endpoint; (4) a **real** `POST /v1/embeddings` round-trip — an OGA/ONNX-recipe server that lists a model but returns an empty embedding fails with the exact named message; (5) if a case is given, compare the server dimension against `meta.embedding_dim` and fail naming both dims on mismatch; (6) load sqlite-vec on a throwaway connection and read `vec_version()`, naming the `enable_load_extension` caveat on failure; (7) `/props` determinism WARNING (`n_parallel>1` or `seed<0`) that never fails. Every server-supplied string is `_sanitise`'d before printing.
- Added `InferenceClient.models(endpoint)` so `GET /v1/models` routes through the single HTTP boundary (SPEC §5.6) instead of being reimplemented in the CLI.
- Added public `store.vec_version()` — a throwaway in-memory connection reusing the vetted `_load_sqlite_vec` path (enable → load → re-lock, T-03-09) — so doctor's Pitfall-5 probe never duplicates the native-extension surface.
- Added the `cli._make_http_client(timeout)` seam: wires per-request httpx timeouts onto the injected client (03-02 left this to callers) AND gives tests a place to bind an `httpx.MockTransport` while the real SSRF guard still runs at construction.
- `tests/test_doctor.py` drives the whole sequence against a fake OpenAI-compatible server via `MockTransport` — zero sockets — asserting fail-fast order (an unreachable generation endpoint never reaches the embeddings probe), the OGA/ONNX and dimension-mismatch messages, the SSRF refusal/override pair, and the multi-slot determinism warning. The live variant is `@pytest.mark.live`, excluded by the default `addopts`.

## Task Commits
1. **Task 1: doctor fail-fast sequence + flags** — `9f7cdfe`
2. **Task 2: test_doctor.py** — `8ad05bf`

_Plan metadata commit follows this summary._

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added `InferenceClient.models(endpoint)` (src/sift/llm/client.py)**
- **Found during:** Task 1
- **Issue:** The plan's `files_modified` lists only `cli.py` + the test, but doctor's must-have sequence requires `GET /v1/models` on both endpoints, and the Wave-2 client exposed no such method. Reimplementing the GET in `cli.py` would violate the load-bearing "client.py is the ONLY module that talks HTTP" invariant (SPEC §5.6).
- **Fix:** Added a small `models(endpoint) -> list[str]` method (defensive JSON parse, untrusted ids) that goes through the existing `_request` backoff path.
- **Files modified:** src/sift/llm/client.py
- **Commit:** 9f7cdfe

**2. [Rule 3 - Blocking] Added public `store.vec_version()` (src/sift/store.py)**
- **Found during:** Task 1
- **Issue:** The vec_version check needs to load sqlite-vec on a throwaway connection. The only load path (`_load_sqlite_vec`) is a private module function; importing a private symbol into `cli.py` (or inlining `enable_load_extension`) would either need a `# pyright: ignore` in production code or duplicate the security-sensitive T-03-09 native-extension surface.
- **Fix:** Added a public `vec_version()` module function that runs the probe on an in-memory connection reusing `_load_sqlite_vec`. The 03-03 summary explicitly anticipated doctor reusing this path.
- **Files modified:** src/sift/store.py
- **Commit:** 9f7cdfe

Both additions are pure extensions of existing boundaries (no behaviour change to prior code); the full 236-test suite stays green.

## Threat Model Coverage
- **T-03-12 (Info-disclosure, public endpoint):** client construction runs `_assert_local` on both base_urls; doctor refuses a public endpoint unless `--i-know-what-im-doing`. Tested (refuse + override).
- **T-03-13 (Integrity, silent OGA/ONNX embed failure):** a REAL `/v1/embeddings` round-trip; an empty embedding fails with the named `llamacpp/flm-recipe` message; capability is never inferred from `/v1/models`. Tested.
- **T-03-14 (Spoofing, hostile server control bytes):** every server-supplied string (model IDs, error text, vec_version) is whole-line `_sanitise`'d before printing.
- **T-03-15 (Integrity, determinism-breaking multi-slot):** `/props` emits a non-fatal WARNING on `n_parallel>1` (and `seed<0`); an absent `/props` warns nothing. Tested (`n_parallel=4` → warns, exit 0).

## Known Stubs
None. The doctor exercises live behaviour end-to-end (real client construction, real sqlite-vec load); the only faked surface is the inference server (via MockTransport), which is the mandated EVAL-05 pattern, not a stub.

## Verification
- `uv run pytest tests/test_doctor.py` — 7 passed, 1 deselected (live)
- `uv run pytest` — 236 passed, 2 deselected (full suite green, no regressions)
- `uv run ruff check` + `uv run pyright` — clean on cli.py, store.py, llm/client.py, tests/test_doctor.py

## Notes for downstream
- `sift analyze` (Plan 06) reuses the `_make_http_client` seam + `InferenceClient` construction for the embed/cluster leg; the per-request timeout wiring now lives in `_make_http_client`.
- Manual UAT (flagged, not automated): `sift doctor` against a live llama-server — deferred to `/gsd-verify-work`. The `@pytest.mark.live` test restores loopback networking and skips unless a server is listening on `127.0.0.1:13305`.

## Self-Check: PASSED
- tests/test_doctor.py — FOUND
- 03-04-SUMMARY.md — FOUND
- Commits 9f7cdfe, 8ad05bf — verified present in git log
