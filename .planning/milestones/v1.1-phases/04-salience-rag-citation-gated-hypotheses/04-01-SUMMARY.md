---
phase: 04-salience-rag-citation-gated-hypotheses
plan: 01
subsystem: hypothesis-contract-and-store
tags: [models, store, migration, pydantic, sqlite, citation-gate]
status: complete
requires:
  - "store.py migration runner (PRAGMA user_version) — Phase 3 (migration 3)"
  - "config.py ConfigDict(extra=forbid) idiom — Phase 3"
provides:
  - "models.Hypothesis / models.HypothesisSet (SPEC §5.5 output contract + JSON schema seam)"
  - "store.StoredHypothesis dataclass"
  - "store.CaseStore.replace_hypotheses / query_hypotheses"
  - "store migration 4 (hypotheses table) + triage_* run-meta key convention"
  - "store._coerce_str_list (shared WR-01 JSON-list coercion helper)"
affects:
  - "04-03 llm/client chat(response_format=...) will consume HypothesisSet.model_json_schema()"
  - "04-04 hypothesise state machine assembles/validates/persists via these models + store methods"
  - "04-05 sift show hypotheses renders query_hypotheses rows + triage_* meta"
tech-stack:
  added: []
  patterns:
    - "additive Pydantic BaseModel with extra=forbid as fail-loud anti-hallucination control"
    - "numbered migration function registered in _MIGRATIONS, self-applies via user_version runner"
    - "caller-owned transaction for replace_* CRUD (mirrors replace_clusters)"
    - "WR-01 defensive JSON-list coercion factored into _coerce_str_list"
key-files:
  created:
    - none
  modified:
    - src/sift/models.py
    - src/sift/store.py
    - tests/test_models.py
    - tests/test_store.py
    - tests/test_store_vectors.py
decisions:
  - "Run-level triage status persists as triage_* meta keys, not a second table (RESEARCH A5)"
  - "citations_valid persists per hypothesis (INTEGER 0/1) so an invalid citation stays flagged, never dropped (T-04-02)"
  - "RAG-02/RAG-04 left unmarked in REQUIREMENTS.md — this plan is the substrate; full scope lands 04-04/04-05 (partial-scope convention)"
metrics:
  duration: 6m
  completed: 2026-07-17
  tasks: 2
  files_modified: 5
---

# Phase 4 Plan 01: Hypothesis Contract & Store Substrate Summary

Frozen `Hypothesis`/`HypothesisSet` Pydantic models (SPEC §5.5 verbatim, `extra="forbid"`) plus store migration 4 — the `hypotheses` table with a persisted per-hypothesis `citations_valid` flag, `replace_hypotheses`/`query_hypotheses` CRUD, and the `triage_*` run-meta convention — the durable substrate the 04-04 enforcement state machine and 04-05 render build on.

## What was built

**Task 1 — Hypothesis models (`models.py`, commit `9e44618`)**
Two additive `BaseModel` classes with `model_config = ConfigDict(extra="forbid")`: `Hypothesis` (title, narrative, `confidence: Literal["high","medium","low"]`, confidence_reasoning, supporting_event_ids, `contradicting_evidence: str | None`, suggested_next_steps) and `HypothesisSet` (hypotheses, timeline_summary, unexplained_signals). The frozen `Event` dataclass was untouched. Schemas are self-contained so `model_json_schema()` inlines `Hypothesis` under `$defs` (no external `$ref`) — the 04-03/04-04 constrained-decoding path can send the schema directly. RED-first tests assert the valid SPEC shape, unknown top-level key rejection, unknown nested key rejection, bad `confidence` rejection, `contradicting_evidence=None`, and that the JSON schema is a dict containing the `Hypothesis` `$def`.

**Task 2 — Store migration 4 (`store.py`, commit `05ad5c5`)**
`_migration_4` creates `CREATE TABLE hypotheses` (`hyp_index` PK, NOT-NULL text columns, `confidence` CHECK-constrained to the three-value vocabulary, nullable `contradicting_evidence`, `citations_valid INTEGER NOT NULL`), registered as `4: _migration_4` in `_MIGRATIONS` so it self-applies on the next `CaseStore` open (stderr announces `migrating case.db to schema v4`). Added the frozen `StoredHypothesis` dataclass beside `Cluster`, the `_HYP_COLUMNS` module constant, `replace_hypotheses` (DELETE + `executemany` INSERT, all `?`-bound, `json.dumps` the two list fields, `int(citations_valid)`; caller owns the transaction) and `query_hypotheses` (ordered by `hyp_index` ASC, `bool(citations_valid)`). Run-level status uses the existing `get_meta`/`set_meta` under documented `triage_*` keys — no new methods.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Bumped schema-head assertions 3→4 in pre-existing migration tests**
- **Found during:** Task 2 (full-suite gate after registering migration 4)
- **Issue:** Four pre-existing tests hardcoded the latest `user_version` as 3 (`test_fresh_store_reaches_latest_user_version`, `test_v1_to_v2_upgrade`, `test_reopen_migrated_store_is_noop` in `test_store.py`; `test_migration_3_creates_chunks_and_clusters` in `test_store_vectors.py`). Registering migration 4 legitimately moves the head to 4, so these assertions failed.
- **Fix:** Updated the `== 3` assertions (and two docstrings) to `== 4`, noting the head moved with plan 04-01. No behavioural change to those tests otherwise.
- **Files modified:** tests/test_store.py, tests/test_store_vectors.py
- **Commit:** 05ad5c5

### Simplification (ponytail)

**`_coerce_str_list` helper** — the WR-01 non-list-JSON coercion was duplicated inline in `query_clusters`/`query_template_groups`. `query_hypotheses` needs it on two columns, so the idiom was factored into one module-level `_coerce_str_list(value)`. The existing inline call sites were left untouched (out of scope for this plan); a future cleanup could route them through the helper too.

## Threat surface

Both threat-model mitigations for this plan are implemented:
- **T-04-05 (SQLi):** `_HYP_COLUMNS` is a module constant; every model value is `?`-bound — no model text reaches SQL. Carries the existing `# noqa: S608` column-list-is-constant convention.
- **T-04-02 (citation spoofing):** `citations_valid` persists per row, so an invalid/unverifiable citation is visibly flagged for the report (backs the 04-04 gate).
- **T-04-08 (tampered JSON):** `_coerce_str_list` wraps non-arrays and `str()`s every element on both list columns; a tampered `case.db` never crashes the read path.

No new security surface beyond the plan's `<threat_model>` was introduced.

## Requirements

RAG-02, RAG-04, STORE-04 were NOT marked complete in REQUIREMENTS.md — `requirements.mark-complete` returned `applied: false`. This is correct: this plan lays the persistence substrate only; the citation gate (RAG-02) and full retrieval/hypothesis behaviour (RAG-04) are delivered by 04-04/04-05. They complete when the full phase lands (partial-scope convention).

## Verification

- `uv run pytest -q` — 276 passed, 2 deselected.
- `uv run ruff check` — all checks passed.
- `uv run pyright` — 0 errors, 0 warnings.
- A v3 `case.db` opened by the new code reports `note: migrating case.db to schema v4` on stderr and gains the `hypotheses` table (`test_v3_to_v4_migration_adds_hypotheses_table`).

## Known Stubs

None. This plan is a substrate; its consumers (04-03/04-04/04-05) are separate planned work, not stubs.

## Self-Check: PASSED

- FOUND: src/sift/models.py (Hypothesis, HypothesisSet)
- FOUND: src/sift/store.py (_migration_4, StoredHypothesis, replace_hypotheses, query_hypotheses)
- FOUND: commit 9e44618 (Task 1)
- FOUND: commit 05ad5c5 (Task 2)
