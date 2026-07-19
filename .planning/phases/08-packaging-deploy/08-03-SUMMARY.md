---
phase: 08-packaging-deploy
plan: 03
subsystem: docs
tags: [readme, quickstart, documentation, human-verify]
requires:
  - packaging-uv-tool-install   # 08-01 (install proof)
  - quadlet-deploy-files        # 08-02 (deploy section)
provides:
  - readme-quickstart
affects:
  - README.md
tech-stack:
  added: []
  patterns:
    - "Human-verify checkpoint: README accuracy walked end-to-end on a real Fedora box, not self-approved"
    - "Every quickstart command checked against the live CLI (--help) before sign-off"
key-files:
  created: []
  modified:
    - README.md
decisions:
  - "README quickstart order frozen: install -> backend-is-user-managed prereqs -> two-instance backend setup -> sift doctor -> new/ingest/analyze/report -> optional sift[pdf] -> one-line deploy pointer to ADR 0011."
  - "Generation-model-quality note added after the walkthrough: a small/unstable model yields DEGRADED or failed hypotheses (handled gracefully); ranked cited hypotheses need a competent stable model. Ingest/cluster/timeline are model-independent."
metrics:
  duration: ~1h (incl. human-verify walkthrough + a spun-off embedding bug fix)
  completed: 2026-07-19
status: complete
---

# Phase 8 Plan 03: README Quickstart Summary

Rewrites the 2-line `README.md` stub into a Fedora quickstart that takes a
stranger from a clean checkout to a first triage report using only the README —
the headline goal of Phase 8. Delivered under a blocking human-verify checkpoint:
the user walked the quickstart on a real box against real diagnostics before
sign-off, which surfaced (and got fixed) two real defects the plan text alone
would not have caught.

## What was built

- **`README.md`** (rewritten, 180 lines): title + one-paragraph pitch; **1. Install**
  (`uv tool install .` / `git+https`, `pipx` alternative, `sift --version`);
  **Prerequisites** — the inference backend is the user's to run (Sift never
  downloads/serves models); **2. Start a backend** — two endpoints
  (`SIFT_GENERATION_BASE_URL` + `SIFT_EMBEDDINGS_BASE_URL`), the `--embeddings`
  two-instance rule, Option A llama.cpp (Vulkan default / ROCm alternative on
  gfx1151) and Option B Lemonade (`:13305`, the OGA/ONNX-can't-embed caveat →
  `sift doctor`); **3. `sift doctor`**; **4. First case** (`new`/`ingest`/
  `analyze`/`report`, `--out`, `sift show`); **5. Optional PDF** (`sift[pdf]` +
  `dnf install pango`); **Containerised deployment** (one-line pointer to
  `deploy/` + ADR 0011). British English throughout; no `--i-know-what-im-doing`.

## Verification

- **Automated (Task 1):** README contains `uv tool install`, both base-url env
  vars, `sift doctor`, `sift analyze`, `pango`, Vulkan, ROCm, Lemonade, `13305`,
  and no `--i-know-what-im-doing`. Every quickstart command checked against the
  real CLI (`--help`) and env-var names against `src/sift/config.py`.
- **Human-verify (Task 2):** user walked the full pipeline on a real 62 MB
  MicroStrategy `DSSErrors.log` (178,925 events): `install` ✓, `doctor` ✓,
  `new`/`ingest` ✓ (99.8% coverage), `analyze` ✓ (524 clusters), `report` ✓
  (exit 0, renders). Sign-off given after the model-capability note was added.

## Findings from the walkthrough (fixed, not deferred)

1. **README `sift show` argument order was reversed** — showed
   `sift show clusters my-incident`; the real CLI is `sift show {case} {what}`.
   Would error for a stranger. Fixed to `sift show my-incident clusters`
   (commit `cf97381`), verified empirically against `sift show --help`.
2. **Embedding-overflow bug in `analyze` (separate defect, Phase 3/4 pipeline).**
   The walkthrough's `sift analyze` aborted with "embeddings response 'data' is
   not a list": clustering embeds each group's exemplar event message, and a
   large MCM memory-dump event (~16 KB / 10,237 tokens) exceeds the embedding
   model's 8,192-token context; the backend rejects it and Sift crashed. Fixed
   under TDD in `client.embed()` — truncate each input to
   `EmbeddingsConfig.max_input_chars` (default 8000; env
   `SIFT_EMBEDDINGS_MAX_INPUT_CHARS`) plus an actionable over-context error
   (commits `35874b5` RED + `0c27499` GREEN; ruff/pyright clean, 468 tests).
   Proven: `analyze` now clusters the real case instead of aborting.
3. **Generation-model-quality note added** (commit `f1502a6`): on this box only
   a weak model (Qwen3-0.6B → degraded) is stable; the 27B returns empty
   completions / drops the connection and the 0.8B-vLLM fails to load — all
   handled gracefully by Sift. The note tells a stranger that ranked cited
   hypotheses need a competent stable generation model.

## Deviations from Plan

The plan anticipated a clean README-only checkpoint. The human-verify walkthrough
did its job — it exposed a real doc error (finding 1) and a real product bug
(finding 2), both fixed before sign-off rather than shipped. Finding 2 is a
Phase 3/4 pipeline fix carried on this branch by explicit user authorisation; it
is outside PKG-01/PKG-02 scope and is tracked as its own atomic commits.

## Known Stubs

None.

## Self-Check: PASSED
- README.md — modified, FOUND
- Commit 0ef3889 (docs, Task 1 README rewrite) — FOUND
- Commit cf97381 (fix, sift show arg order) — FOUND
- Commit f1502a6 (docs, model-capability note) — FOUND
- Human-verify checkpoint (Task 2) — resolved: user walked it on real Fedora, approved
