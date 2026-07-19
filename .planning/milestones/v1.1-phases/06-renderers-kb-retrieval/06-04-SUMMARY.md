---
phase: 06-renderers-kb-retrieval
plan: 04
subsystem: retrieval
tags: [rag, kb, prompt, citation-gate, non-citability, cli, analyze]
status: complete

# Dependency graph
requires:
  - phase: 06-03
    provides: pipeline/retrieve.py (index_kb, retrieve_kb), kb_chunks/kb_vectors namespace, knn_kb_chunks
  - phase: 06-01
    provides: sift analyze/report vertical, exit-code discipline, _sanitise via render._util
  - phase: 04-inference-client (hypothesise)
    provides: _assemble/hypothesise, prompted_ids citation gate (cited ⊆ prompted ⊆ store)
provides:
  - "sift analyze --kb <dir>: KB context threaded into the triage prompt (RAG-07 user slice complete)"
  - "hypothesise._apply_kb_block + kb_context param on _assemble/hypothesise (KB block substitution/stripping)"
  - "Sentinel-delimited reference-material block in triage.md (D-02), non-citable by construction (D-01)"
affects: [phase-07-eval, kb-retrieval-quality]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Template sentinel block resolved at assembly: fill+strip-markers when present, remove-whole-block when absent — keeps the no-feature path byte-identical"
    - "Non-citability enforced mechanically via prompted_ids, not prose: KB text enters the prompt but never the citable id set"
    - "Untrusted KB text sanitise()d before prompt insertion (control-char strip, T-06-16)"

key-files:
  created:
    - tests/test_kb_analyze.py
  modified:
    - src/sift/prompts/triage.md
    - src/sift/pipeline/hypothesise.py
    - src/sift/cli.py

key-decisions:
  - "KB block sentinels are HTML comments carrying their own doc note; both marker lines are stripped at assembly so nothing leaks to the model and the no-KB prompt is byte-identical"
  - "KB retrieval query = top-salient cluster labels (fallback signatures), capped to --top-clusters; averaged query vector via retrieve_kb (RESEARCH Q4/A6)"
  - "byte-identity guarded by a golden no-KB prompt-hash constant captured pre-change, plus the untouched Phase-4 suite"

patterns-established:
  - "Pattern: add an optional feature to a hashed/deterministic artifact by delimiting it with strippable sentinels and asserting a golden hash for the feature-off path"
  - "Pattern: reuse an existing structural invariant (prompted_ids) rather than adding a second guard for a new input source"

requirements-completed: [RAG-07]

coverage:
  - id: D2
    description: "analyze --kb changes the assembled prompt (KB reference block present, delimited before Evidence:); no-kb byte-identical to the pre-change golden"
    requirement: "RAG-07"
    verification:
      - kind: unit
        ref: "tests/test_kb_analyze.py#test_assemble_kb_block_present_and_stripped"
      - kind: unit
        ref: "tests/test_kb_analyze.py#test_assemble_no_kb_is_byte_identical_baseline"
  - id: D1
    description: "KB chunks never enter prompted_ids; a model citing a KB-derived id is FLAGGED (citations_valid=0, exit 3) end-to-end with KB active"
    requirement: "RAG-07"
    verification:
      - kind: unit
        ref: "tests/test_kb_analyze.py#test_assemble_prompted_ids_unchanged_by_kb"
      - kind: integration
        ref: "tests/test_kb_analyze.py#test_analyze_kb_context_present_yet_noncitable_end_to_end"

metrics:
  duration_min: 13
  completed: 2026-07-18
  tasks: 3
  files_touched: 4
  tests_total: 412
---

# Phase 6 Plan 04: `sift analyze --kb` KB-context wiring Summary

Thread retrieved KB runbook/RCA context into the `sift analyze --kb <dir>` triage prompt (RAG-07) as delimited, structurally non-citable reference material — enriching hypotheses while the anti-hallucination gate stays mechanically intact because KB chunks never enter `prompted_ids`.

## What was built

- **`src/sift/prompts/triage.md`** — a sentinel-delimited (`<!-- KB_BLOCK_START … -->` / `<!-- KB_BLOCK_END -->`) reference-material block inserted immediately before the `Evidence:` section marker. The British-English header states the material is internal runbooks/RCAs, untrusted data (not instructions), and MUST NOT be cited (no `[evt:]` ids). All KB prompt prose lives here (CLI-02) — no Python string literal carries it.
- **`src/sift/pipeline/hypothesise.py`** — new `_apply_kb_block(template, kb_context)`: fills `<<KB_CONTEXT>>` with the joined, `sanitise`d chunks and drops the two marker lines when KB is present; removes the whole block (start-through-end) when it is absent, so the no-KB assembled prompt is byte-identical. Added `kb_context: list[str] | None = None` to both `_assemble` (keyword-only) and `hypothesise`, threaded through the single call site. `prompted_ids` stays `set(event_ids)` — KB is never added.
- **`src/sift/cli.py`** — new `analyze --kb <dir>` `typer.Option(Path | None)`. Inside the existing http-client lifecycle, after `cluster_and_label` and before `hypothesise`: `retrieve.index_kb(store, client, kb)` then a query built from the top-salient cluster labels/signatures → `retrieve.retrieve_kb(...)`, wrapped `(httpx.HTTPError, ValueError)` → `typer.Exit(1)` with a sanitised message (mirrors the cluster-embed failure). The retrieved list is passed as `hypothesise(..., kb_context=…)`; without `--kb`, `kb_context=None` (unchanged path). The KB embeds through the SAME injected client whose SSRF guard already ran (LLM-02) — no new HTTP path.
- **`tests/test_kb_analyze.py`** — network-free (httpx.MockTransport) coverage of the three load-bearing truths (below).

## Load-bearing invariants proven

- **D-01 (non-citability)** — `prompted_ids` is identical with and without `kb_context` (`test_assemble_prompted_ids_unchanged_by_kb`); an end-to-end `analyze --kb` run whose model cites a KB-derived id is FLAGGED (`citations_valid=0`, `triage_degraded=1`, exit 3) while the KB text is confirmed present in the real triage prompt — `cited ⊆ prompted ⊆ store` holds transitively with KB active.
- **D-02 (delimited enrichment)** — the assembled prompt changes with `--kb` (the KB block appears before `Evidence:`); a valid-exemplar citation with `--kb` is still a clean exit 0.
- **Byte-identity / determinism** — the no-KB assembled prompt reproduces the pre-change golden hash `ef5b76801235d179` (captured before the template/`_assemble` edits); the untouched `tests/test_hypothesise.py` + `tests/test_analyze.py` stay green, so Phase-4 behaviour and `triage_prompt_hash` are unchanged.

## Deviations from Plan

None — plan executed exactly as written. Rules 1–3 not triggered; no architectural changes (Rule 4) required.

## Known Stubs

None. The KB query strategy (top-salient cluster labels/signatures → averaged query vector, RESEARCH Q4/A6) and in-code chunking/`k` defaults (from 06-03) are intentional MVP choices, tunable against Phase 7 eval — not stubs.

## Threat surface

No new surface beyond the plan's `<threat_model>`. `--kb` embeds through the existing SSRF-guarded injected client (T-06-18); KB text is `sanitise`d before prompt insertion (T-06-16); embed/index failure → exit 1 sanitised (T-06-19); no-KB path byte-identical (T-06-17); KB citation FLAGGED by the existing gate (T-06-15).

## Quality gate

`uv run pytest` → 412 passed, 3 deselected (perf/live). `uv run ruff check` clean. `uv run pyright` → 0 errors, 0 warnings.

## Commits

- `abb9ace` test(06-04): add failing KB-analyze tests (RED)
- `e732443` feat(06-04): thread KB context into analyze --kb (RAG-07, D-01, D-02)
- `0bad9e9` test(06-04): end-to-end analyze --kb non-citability (D-01, RAG-07)

## Self-Check: PASSED

All created/modified files present on disk; all three commit hashes present in git log.
