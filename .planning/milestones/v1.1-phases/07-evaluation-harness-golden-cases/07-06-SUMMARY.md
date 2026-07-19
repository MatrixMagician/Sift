---
phase: 07-evaluation-harness-golden-cases
plan: 06
subsystem: eval
tags: [gap-closure, test-harness, zero-network, live-marker, llm-as-judge, degrade, tdd]
requires: [eval-judge-advisory, inference-client-chat, no-network-guard, live-marker]
provides: [live-marker-network-carve-out, judge-reasoning-only-degrade-lock]
affects:
  - tests/conftest.py
  - tests/test_conftest_network_guard.py
  - tests/test_eval_judge.py
tech-stack:
  added: []
  patterns:
    - marker-scoped-autouse-fixture-carve-out
    - offline-loopback-listener-determinism-proof
    - never-crash-on-model-output-degrade-to-none
    - schema-keyed-offline-fake-distinguisher
key-files:
  created:
    - tests/test_conftest_network_guard.py
  modified:
    - tests/conftest.py
    - tests/test_eval_judge.py
decisions:
  - "The `_no_network` autouse guard exempts ONLY tests carrying the `live` marker (request.node.get_closest_marker(\"live\")); every unmarked test still raises the network-forbidden RuntimeError on socket.connect, so the default suite (-m 'not perf and not live') stays byte-for-byte socket-blocked."
  - "The carve-out is proven offline: Test B binds an in-process loopback listener on 127.0.0.1:0 and asserts the connect succeeds — a determinism proof of the marker gate needing no external server, distinct from the real-server test_judge_live_round_trip."
  - "Task 3 (reasoning-only/empty-content judge degrade) landed GREEN with zero judge.py change: InferenceClient.chat already raises ValueError on whitespace-only content (client.py:306) and judge_case already catches ValueError → None (judge.py:106). The plan proves that path against the exact live shape (HTTP 200, empty content, populated reasoning_content, finish_reason=length) rather than re-routing it."
  - "pyright strict flags FixtureRequest.node as Any; resolved with a scoped `# pyright: ignore[reportUnknownMemberType]` on the .node read plus a cast to pytest.Item — mirroring the file's existing targeted-ignore convention, not a global relaxation."
metrics:
  duration: ~3 min
  completed: 2026-07-19
  tasks: 3
  files: 3
status: complete
---

# Phase 7 Plan 6: Live-Marker Network Carve-Out & Judge Degrade Lock-In Summary

Exempts `@pytest.mark.live` tests from the autouse zero-network guard so the
Phase 7 live-judge round-trip is runnable, and locks the judge's return-None
degrade against the real reasoning-only/empty-content model reply — the sole UAT
gap blocking Phase 7 verification.

## What Was Built

Three atomic TDD commits closing UAT Gap 1:

1. **RED (d4075d7)** — `tests/test_conftest_network_guard.py`: two-halves regression.
   Test A (unmarked) asserts `socket.connect` still raises the zero-network
   RuntimeError; Test B (`@pytest.mark.live`) uses an in-process loopback
   listener to prove a live-marked connect succeeds. Test B is RED before the
   fix (guard blocks it) and deselected from the default suite so `uv run pytest`
   stays green.
2. **GREEN (1861e8c)** — `tests/conftest.py`: `_no_network` gains a
   `request: pytest.FixtureRequest` param and early-returns without patching
   `socket.connect` when `node.get_closest_marker("live")` is set. Because the
   exempt path never calls `monkeypatch.setattr`, there is nothing to revert.
3. **Lock-in (3c6f77c)** — `tests/test_eval_judge.py`:
   `test_reasoning_only_judge_reply_degrades` feeds the judge chat call the exact
   live reasoning-model shape (`content: ""`, `reasoning_content` populated,
   `finish_reason: "length"`) and asserts `sift eval --judge` exits 0, does not
   raise, and reports `n/a`. GREEN with no judge.py change.

## How to Verify

- `uv run pytest` — default suite green, socket-blocked (466 passed, 5 deselected).
- `uv run pytest -m live tests/test_conftest_network_guard.py` — green, offline,
  proves the marker carve-out with no server.
- `uv run ruff check` — clean; `uv run pyright` — 0 errors / 0 warnings / 0 informations.
- Operator UAT (outside the automated gate, needs Lemonade on 127.0.0.1:13305):
  `uv run sift doctor` then `uv run pytest -m live tests/test_eval_judge.py::test_judge_live_round_trip`
  — now reaches the socket instead of raising RuntimeError.

## Deviations from Plan

None — plan executed exactly as written. Task 3 landed GREEN as the plan
predicted (the empty-content root cause already lives at the sole HTTP boundary),
so no `judge.py` hardening was warranted.

## Threat Mitigations

- **T-07-06-01** (guard over-broadening): mitigated — the exemption keys strictly
  on the `live` marker; Test A proves unmarked tests still raise on connect, and
  the default `addopts` keep live tests out of the standard run.
- **T-07-06-02** (judge crashing the eval run): mitigated — the reasoning-only
  degrade is now locked by a deterministic mocked reproduction proving
  `judge_case → None`, exit unchanged.

## Self-Check: PASSED

- `tests/test_conftest_network_guard.py` — FOUND
- `tests/conftest.py` carve-out — FOUND
- `tests/test_eval_judge.py::test_reasoning_only_judge_reply_degrades` — FOUND
- Commits d4075d7, 1861e8c, 3c6f77c — FOUND
