# Phase 3 Discussion Log

**Date:** 2026-07-17
**Mode:** discuss (interactive, single-pass)

Human-reference audit trail. Not consumed by downstream agents (see 03-CONTEXT.md for the locked decisions).

## Areas Discussed

### 1. Cluster label timing (SPEC §10 Open Question #3)
- **Options presented:** Eager at M3/analyze (persist to clusters.label) vs Lazy at report time.
- **Selected:** Eager at M3/analyze.
- **Notes:** Makes `sift show clusters` human-readable pre-report; M3 acceptance demonstrable without the Phase-6 report path. → D-01; record ADR in docs/decisions/.

### 2. `sift doctor` behaviour on check failure
- **Options presented:** Run-all + report-all + exit non-zero, vs Fail-fast on first critical.
- **Selected:** Fail-fast on first critical.
- **Notes:** Stop at first critical, exit non-zero; must name the failure mode (esp. Lemonade OGA/ONNX no-embeddings, unreachable endpoint, dimension mismatch). Warnings before the stop (e.g. multi-slot determinism) still print. → D-02.

### 3. Default embedding model identity
- **Options presented:** Config-only (no default) vs ship nomic-embed as documented default.
- **Selected:** Config-only, no baked-in default.
- **Notes:** Record actual server-returned identity + dimension in meta; dimension mismatch = hard error. Aligns with SPEC §3 "defaults, all configurable". → D-03.

### 4. HDBSCAN clustering config surface
- **Options presented:** Sensible defaults + config-overridable vs hardcode-for-now.
- **Selected:** Sensible defaults, config-overridable via [clustering].
- **Notes:** min_cluster_size/min_samples/epsilon/metric/fallback_threshold in config; provisional pending golden suite (Phase 7). → D-04.

## Deferred Ideas
- Salience / triage prompt / hypothesis contract + citation validation → Phase 4.
- KB index + retrieval (per-case vs global, SPEC §10 #5) → Phase 6.
- Salience + clustering threshold tuning → post-golden-suite (Phase 7).

## Claude's Discretion (delegated to planner/executor)
httpx retry/backoff/timeout/batch-size internals; feature-detection mechanism; PromptBudget seam;
embedding-leg progress bar; migration SQL + vec0 table; fake-server test shape.
