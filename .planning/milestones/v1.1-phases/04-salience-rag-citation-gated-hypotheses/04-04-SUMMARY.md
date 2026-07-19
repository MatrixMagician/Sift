---
phase: 04-salience-rag-citation-gated-hypotheses
plan: 04
subsystem: pipeline
tags: [rag, citation-gate, constrained-decoding, pydantic, anti-hallucination, llama.cpp]

# Dependency graph
requires:
  - phase: 04-01
    provides: Hypothesis/HypothesisSet models, hypotheses store table (migration 4), replace_hypotheses/query_hypotheses, triage_* run-meta keys
  - phase: 04-02
    provides: salience.rank_clusters deterministic top-N ordering
  - phase: 04-03
    provides: additive InferenceClient.chat(response_format=) constrained-decoding param
provides:
  - pipeline/hypothesise.py — Outcome dataclass + hypothesise() enforcement + citation-gate state machine
  - prompts/triage.md — versioned triage prompt with untrusted-data guard
  - zero-network fake OpenAI-compatible server fixture (scenario builder + MockTransport handler)
affects: [04-05, cli, render, report]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "validate -> repair (max 1) -> degrade enforcement state machine (never crash)"
    - "cited ⊆ prompted ⊆ store citation gate with one regeneration then a visible flag"
    - "prompted_ids (printed exemplar ids) IS the citable universe — one in-memory subset check enforces both SPEC conditions"
    - "response_format sends the llama.cpp {type:json_schema, schema:...} shape, never OpenAI nesting, never with grammar"
    - "caller-owns-transaction atomic persist (rows + triage_* meta in one store.transaction())"

key-files:
  created:
    - src/sift/pipeline/hypothesise.py
    - src/sift/prompts/triage.md
    - tests/test_hypothesise.py
  modified: []

key-decisions:
  - "Representative exemplar per cluster = the member group with highest (severity, count); its first exemplar event id is the citable id (mirrors cluster.py's signature representative)"
  - "triage_model provenance uses client.embedding_model (the only public model accessor; client.py is out of scope for this plan) — None when unknown, which is acceptable per D-03"
  - "raw model output is persisted (triage_raw) only on a hard degrade (no schema-valid set); a flagged-but-valid set persists the structured rows instead"
  - "Schema-repair budget (1) and citation-regenerate budget (1) are distinct and compose (a regeneration must itself pass schema validation before re-gating)"

patterns-established:
  - "Pattern: fake OpenAI-compatible server via httpx.MockTransport with a per-call canned-body queue; the triage generation call is discriminated by response_format presence so bad-then-good / regenerate scenarios pop in order — zero sockets"
  - "Pattern: seed deterministic clusters through the real Phase-3 clustering path (orthogonal planted vectors -> noise singletons) so representative exemplar ids are known constants"

requirements-completed: [RAG-02, RAG-03, RAG-04]

coverage:
  - id: D1
    description: "triage.md ships as package data with the untrusted-data guard and an Evidence: header; loads via importlib.resources"
    requirement: "RAG-02"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_fixture_or_prompt_triage_guard_present"
        status: pass
    human_judgment: false
  - id: D2
    description: "Malformed JSON triggers exactly one repair round-trip carrying the Pydantic error; a second failure degrades (raw captured, no crash)"
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_repair_bad_then_good, ::test_degrade_bad_json_twice"
        status: pass
    human_judgment: false
  - id: D3
    description: "Citation gate: cited ⊆ prompted; regenerate once; still-invalid citations are flagged (citations_valid=false, run degraded) — never silently accepted, bad id kept visible"
    requirement: "RAG-04"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_regenerate_badcite_then_good, ::test_flagged_badcite_twice, ::test_citation_valid_golden"
        status: pass
    human_judgment: false
  - id: D4
    description: "All hypotheses + triage_* run-meta persist inside one store.transaction(); a mid-persist failure rolls back to zero rows"
    requirement: "RAG-02"
    verification:
      - kind: unit
        ref: "tests/test_hypothesise.py::test_atomic_persist_rolls_back"
        status: pass
    human_judgment: false
  - id: D5
    description: "llama.cpp constrained-decoding schema (HypothesisSet.model_json_schema() with $defs/$ref) accepted by a real server's decoder"
    verification: []
    human_judgment: true
    rationale: "Requires a live llama-server / Lemonade round-trip; the automated suite is socket-blocked by design. The validate->repair->degrade pipeline is the automated backstop regardless (VALIDATION.md manual-only item; run `uv run pytest -m live` once a server is available)."

# Metrics
duration: 9min
completed: 2026-07-17
status: complete
---

# Phase 4 Plan 04: Citation-Gated Hypotheses Core Summary

**The anti-hallucination core: `hypothesise()` assembles a budgeted triage prompt over the top-N salient clusters, enforces validate→repair→degrade on the model's JSON, then gates every citation to the prompted-id universe (regenerate once, else flag + degrade), and persists atomically — a hypothesis cannot cite an event the model was never shown.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-17T16:06:04Z
- **Completed:** 2026-07-17T16:15:52Z
- **Tasks:** 3
- **Files modified:** 3 created

## Accomplishments

- **`prompts/triage.md`** — versioned triage prompt shipping as package data, copying the untrusted-data guard verbatim from `cluster_label.md`, instructing the model to cite ONLY the `[evt:<id>]` tokens shown and return ONLY the SPEC §5.5 JSON contract (British English). Editing the `.md` changes triage output with no Python change; the prompt hash is recorded in `triage_prompt_hash`.
- **Zero-network fake server fixture** — a scenario builder (`good` / `bad_json` / `bad_then_good` / `bad_citation` / `badcite_then_goodcite`) plus an `httpx.MockTransport` handler that serves `/v1/embeddings` from planted vectors and `/v1/chat/completions` from a per-call queue, discriminating the triage generation call by `response_format` presence so repair/regenerate scenarios pop bodies in order. No socket is ever opened.
- **`pipeline/hypothesise.py`** — typer-free, print-free `Outcome` dataclass + `hypothesise()`:
  - ranks clusters via `salience.rank_clusters`, takes the top `top_clusters`, assembles `[evt:<event_id>] <exemplar message>` lines breadth-first via `PromptBudget.fit`, tracking `prompted_ids` (the citable universe);
  - the hint flows verbatim into the prompt (never parsed for a timestamp);
  - generation uses `chat(response_format={"type":"json_schema","schema":HypothesisSet.model_json_schema()})` — the llama.cpp shape, never OpenAI nesting, never with a grammar field;
  - **enforcement**: valid → success; invalid → exactly one repair turn carrying the raw + Pydantic error → re-validate; invalid twice → degrade (second raw captured), never crash; transport error → failed (nothing persisted);
  - **citation gate**: all cited within prompted → success; else exactly one regeneration (must itself pass schema validation) → re-gate; still invalid → each offending row flagged `citations_valid=false` (offending id kept visible), run marked `triage_degraded=1` — never silently accepted, never dropped;
  - **atomic persist**: `replace_hypotheses` + `triage_*` run-meta inside ONE `store.transaction()`; a mid-persist failure rolls back to zero rows.
- Deterministic `prompt_hash = sha256(prompt)[:16]` — identical inputs assemble an identical prompt and hash.

## Key Decisions

- **Representative exemplar** per cluster is the highest-`(severity, count)` member group's first exemplar event id (mirrors `cluster.py`'s signature representative), keeping the citable id deterministic.
- **`triage_model`** provenance uses the public `client.embedding_model` accessor; `client.py` was out of scope for this plan, and the field is optional (`None` when unknown) per D-03.
- **`triage_raw`** is persisted only on a hard degrade (no schema-valid set produced); a flagged-but-schema-valid set persists structured rows so the report can display and flag them.

## Deviations from Plan

None — plan executed exactly as written. The three tasks landed as three atomic commits, each gated green on `pytest` + `ruff` + `pyright`.

## Threat Surface

All Phase-4 threat-register mitigations for this plan are implemented and test-covered:

- **T-04-01** (prompt injection) — `triage.md` untrusted-data guard; the citation gate holds regardless of model compliance.
- **T-04-02** (hallucinated ids) — `cited ⊆ prompted ⊆ store` enforced in-memory against `prompted_ids`; regenerate once, then flag + degrade.
- **T-04-04** (malformed output) — `HypothesisSet` `extra="forbid"` validation; malformed JSON degrades, never crashes.
- **T-04-11** (atomic persistence) — all writes inside one `store.transaction()`.

No new security surface introduced beyond the plan's `<threat_model>`.

## Self-Check: PASSED

- `src/sift/prompts/triage.md` — FOUND
- `src/sift/pipeline/hypothesise.py` — FOUND
- `tests/test_hypothesise.py` — FOUND
- commit a3d5ab5 (Task 1) — FOUND
- commit 592a0b0 (Task 2) — FOUND
- commit 0848bfd (Task 3) — FOUND
- Full suite: 296 passed, 2 deselected; `ruff check` clean; `pyright` 0 errors.
