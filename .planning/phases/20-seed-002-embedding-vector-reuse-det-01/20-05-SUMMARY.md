---
phase: 20-seed-002-embedding-vector-reuse-det-01
plan: 05
subsystem: pipeline
tags: [prompt-budget, context-window, precedence, disclosure, cli, llm]

# Dependency graph
requires:
  - phase: 20-seed-002-embedding-vector-reuse-det-01
    provides: "plan 20-02 (wave ordering only — this plan shares no code with the reuse path)"
provides:
  - "_ctx_tokens keyword parameter configured: int | None — configured wins over a discovered n_ctx"
  - "hypothesise keyword parameter ctx_configured: int | None"
  - "cli._resolve_generation_ctx(configured, client) -> tuple[int, str | None] — the single resolution point plus the estimated-budget warning"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "a resolution helper RETURNS its warning rather than printing it, so the whole decision is unit-testable without a CliRunner and without depending on how the pinned Click version separates stdout from stderr"
    - "an authoritative configured value short-circuits the discovery probe entirely, so honouring a pinned setting also costs no HTTP request"
    - "the one-request guarantee is pinned by counting real requests through the mock transport, not by grepping call sites"

key-files:
  created: []
  modified:
    - src/sift/pipeline/hypothesise.py
    - src/sift/cli.py
    - tests/test_hypothesise.py
    - tests/test_cli.py

key-decisions:
  - "RESEARCH.md and PATTERNS.md both sketched the WRONG change for D-10 — they propose adding a client.props() n_ctx read to cli.py, but hypothesise._ctx_tokens has shipped exactly that since Phase 4. Following either would have created a second resolution site and a second uncached HTTP GET per run. The plan's own planning_correction_to_research identified this; this execution followed the correction and reused _ctx_tokens"
  - "The two genuine deltas implemented: (1) the precedence inversion, where cli.py fused config.generation.context into ctx_fallback and _ctx_tokens then preferred the server's n_ctx over it; (2) the missing disclosure when the budget is estimated"
  - "A non-positive configured value (0 or negative) falls through to the probe — it is not a usable context window, and treating it as authoritative would size every prompt at zero"
  - "The warning is returned rather than printed, and emitted at the CLI AFTER the Progress live region has exited so no bar redraw can overwrite it"
  - "ctx_fallback stays on hypothesise's signature unchanged and eval/runner.py is untouched — it passes no ctx_configured, so its /props probe behaves exactly as today"

patterns-established:
  - "_ctx_client / _props_handler test helpers built from the shipped tests/test_llm_client.py mock-transport idiom, recording request paths so 'issued no request' is directly assertable"
  - "the one-props-per-analyze guarantee is pinned by a request-counting integration test rather than a grep, because sift doctor legitimately has its own props() call"

requirements-completed: []

coverage:
  - id: D1
    description: "A configured generation.context is the prompt budget's window; a server-reported n_ctx no longer overrides it"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_ctx_configured_wins_over_props_n_ctx"
        status: pass
      - kind: unit
        ref: "tests/test_cli.py::test_resolve_generation_ctx_prefers_configured"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unconfigured with a positive discovered n_ctx uses the discovered value (shipped behaviour preserved)"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_ctx_falls_back_to_props_n_ctx_when_unconfigured"
        status: pass
      - kind: unit
        ref: "tests/test_cli.py::test_resolve_generation_ctx_discovers_n_ctx"
        status: pass
    human_judgment: false
  - id: D3
    description: "Unconfigured with no usable n_ctx uses the fallback AND warns that the budget is estimated"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_ctx_falls_back_to_default_when_props_absent"
        status: pass
      - kind: unit
        ref: "tests/test_cli.py::test_resolve_generation_ctx_warns_when_props_absent"
        status: pass
      - kind: unit
        ref: "tests/test_cli.py::test_resolve_generation_ctx_warns_when_n_ctx_unusable"
        status: pass
    human_judgment: false
  - id: D4
    description: "No warning when generation.context is configured — a pinned value is a choice, not an estimate"
    requirement: "DET-01"
    verification:
      - kind: unit
        ref: "tests/test_cli.py::test_resolve_generation_ctx_prefers_configured"
        status: pass
    human_judgment: false
  - id: D5
    description: "Exactly ONE props request per sift analyze invocation"
    requirement: "DET-01"
    verification:
      - kind: integration
        ref: "tests/test_cli.py::test_analyze_issues_exactly_one_props_request"
        status: pass
      - kind: manual
        ref: "ctx_configured removed in-tree — the count becomes 2 and the test fails, proving the assertion is non-vacuous"
        status: pass
    human_judgment: false
  - id: D6
    description: "src/sift/eval/runner.py is unchanged and its hypothesise() call keeps probing exactly as today"
    requirement: "DET-01"
    verification:
      - kind: grep
        ref: "git diff --quiet src/sift/eval/runner.py exits 0"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_eval_thresholds.py — green"
        status: pass
    human_judgment: false

duration: ~10min
completed: 2026-07-30
status: complete
---

# Phase 20 Plan 05: Generation Context Precedence and Disclosure Summary

**A configured `generation.context` is now authoritative over anything the endpoint reports, and an estimated prompt budget is disclosed on stderr instead of assumed in silence.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-07-30
- **Completed:** 2026-07-30
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Fixed the precedence inversion: `cli.py` previously passed `ctx_fallback=config.generation.context or _TRIAGE_CTX_FALLBACK`, and `_ctx_tokens` then preferred the server's `n_ctx` over that value — so a pinned `generation.context` was silently overridden, inverting the precedence documented in `CLAUDE.md`. The configured value now travels on its own `ctx_configured` parameter and wins outright.
- `_ctx_tokens(client, fallback, *, configured)` short-circuits before `client.props()` when `configured` is positive, so honouring a pinned window also costs no HTTP request. Non-positive values fall through to the probe.
- `cli._resolve_generation_ctx` is the single resolution point on the analyze path and returns `(context_tokens, warning_or_None)`. Returning the warning keeps the decision a pure function and makes all four branches unit-testable without a `CliRunner`.
- The estimated-budget disclosure lands on stderr with the pinned fragment `estimated rather than discovered`, naming the assumed token count and pointing at `generation.context`. This is the silence that caused the 2026-07-21 degraded run in the folded todo to be misdiagnosed as a model failure.
- Exactly one props request per `sift analyze`, pinned by counting real requests through the mock transport.
- 10 new tests: 5 in `tests/test_hypothesise.py` (configured wins with no request issued, discovery preserved, absent-props fallback, and a parametrised pair for `configured=0`/`-1`) and 5 in `tests/test_cli.py` (four helper branches plus the request-count guarantee), with an additional end-to-end no-props exit-code guard.

## Task Commits

1. **Task 1 + Task 2: the `configured` precedence, the CLI resolution point, the warning and all tests** - `614b1fc` (fix)

Landed together: Task 2's `ctx_configured=` argument does not exist until Task 1 adds the parameter, and Task 1's parameter has no production caller until Task 2 wires it.

## Files Created/Modified
- `src/sift/pipeline/hypothesise.py` - `_ctx_tokens` gained keyword-only `configured`, with the precedence stated in its docstring; `hypothesise` gained `ctx_configured` and passes it through
- `src/sift/cli.py` - `_resolve_generation_ctx` added next to `_parse_moment`; called in `analyze` after the `Progress` block exits, warning printed to stderr, `ctx_fallback` restored to the plain constant
- `tests/test_hypothesise.py` - `_ctx_client`/`_props_handler`/`_props_requests` helpers and 5 new tests
- `tests/test_cli.py` - `_ctx_probe_client`/`_ctx_props_handler` helpers, `_resolve_generation_ctx` imported, and 6 new tests

## Decisions Made
- Followed the plan's `<planning_correction_to_research>` rather than RESEARCH.md/PATTERNS.md. Both sketched adding a `client.props()` read to `cli.py` next to the existing `ctx_fallback` line, but `hypothesise._ctx_tokens` already shipped exactly that consultation. Implementing the sketch would have produced two resolution sites that could disagree, plus a second uncached GET per run.
- Added `test_ctx_non_positive_configured_falls_through_to_probe` (parametrised over `0` and `-1`) and `test_analyze_issues_exactly_one_props_request` beyond the plan's named set. The latter replaces the plan's `grep -c "props()" src/sift/cli.py == 1` criterion, which cannot hold: `sift doctor` legitimately has its own `props()` call for the determinism warning. Counting real requests on the analyze path tests the actual guarantee, and was verified non-vacuous by removing `ctx_configured` in-tree (the count became 2).
- `test_resolve_generation_ctx_warns_when_n_ctx_unusable` loops over `None`, `0`, `-1` and `"big"` so a non-int, a zero and a negative are all proven to route to the estimate rather than only the one case the plan named.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - unsatisfiable acceptance criterion] `grep -c "props()" src/sift/cli.py` cannot return 1**
- **Found during:** Task 2 verification
- **Issue:** The criterion expects exactly one `props()` call site in `cli.py` as a proxy for "one request per run". `sift doctor` has a shipped, unrelated `props()` call at `cli.py:1574` for the T-03-15 determinism warning, so the count is 2 and cannot be 1 without deleting shipped behaviour.
- **Fix:** Replaced the proxy with a direct test of the underlying guarantee, `test_analyze_issues_exactly_one_props_request`, which counts real requests reaching the mock transport during a full `analyze` invocation. Verified non-vacuous by removing the `ctx_configured` argument in-tree, which makes the count 2 and fails the test.
- **Files modified:** `tests/test_cli.py`
- **Verification:** `uv run pytest tests/test_cli.py -k one_props_request` passes; fails with `ctx_configured` removed.
- **Committed in:** `614b1fc`

**2. [Rule 1 - imprecise acceptance criterion] `grep -c "ctx_configured" src/sift/cli.py == 1`**
- **Found during:** Task 2 verification
- **Issue:** The count is 2 — the keyword argument plus one explanatory comment mentioning it.
- **Fix:** Verified the intent: exactly one `ctx_configured=` argument passed, at one call site. The second occurrence is a comment.
- **Files modified:** None.
- **Verification:** `grep -n "ctx_configured" src/sift/cli.py` shows line 807 (comment) and line 832 (the argument).
- **Committed in:** `614b1fc`

---

**Total deviations:** 2 auto-fixed (one unsatisfiable criterion replaced with a stronger direct test, one imprecise criterion verified by intent), plus 2 additional test decisions recorded above.
**Impact on plan:** No scope change. Deviation 1 replaced a grep proxy with a test that actually proves the one-request guarantee.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full gate green: `uv run pytest` 868/868 passed, `uv run ruff check` clean, `uv run pyright` unchanged at the pre-existing 28-error baseline
- `src/sift/eval/runner.py` verified unmodified; `tests/test_eval_thresholds.py` green, so the eval harness's `/props` probe still behaves exactly as before
- Every existing `hypothesise(...)` caller across `tests/test_mcm_analyze.py`, `tests/test_perfmon_analyze.py`, `tests/test_eustack_analyze.py` and `tests/test_hypothesise.py` passes unmodified — the new keyword defaults to `None`
- The folded todo `.planning/todos/pending/2026-07-21-generation-context-unset.md` is now addressed and can be moved to done at phase completion
- One manual verification remains open: confirming against a live Lemonade endpoint that the stderr warning appears and the run still completes — no agent has access to one, so it belongs in end-of-phase human UAT

---
*Phase: 20-seed-002-embedding-vector-reuse-det-01*
*Completed: 2026-07-30*
