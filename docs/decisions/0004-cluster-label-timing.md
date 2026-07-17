# ADR 0004: Cluster labels generated eagerly during clustering

**Status:** Accepted (implementation lands in Phase 3 / M3)
**Date:** 2026-07-17 (Phase 3 context; recorded per SPEC §10 open-question rule)
**Answers:** SPEC.md §10 open question #3 — when are cluster labels generated?

## Context

Phase 3's semantic-clustering stage groups synonymous template groups into
`clusters` and gives each cluster a short, human-readable label from one batched
local-LLM call. SPEC.md §10 leaves open *when* that label is produced:

- **Eagerly**, during the clustering stage of `sift analyze`, persisted to
  `clusters.label`; or
- **Lazily**, deferred to the Phase-6 report-rendering path, computed on demand.

`sift show clusters` (STORE-04) is the pre-AI inspection surface: an engineer
inspects clusters *before* any report exists. A raw masked `signature` is
readable but terse; a natural-language label is the payoff of the clustering
stage. Deferring labels to Phase 6 would leave `show clusters` unlabelled for
the whole of M3–M5 and make M3's acceptance criterion ("cluster labels
generated") depend on a Phase-6 path that does not yet exist.

## Decision

Generate labels **eagerly** in the clustering stage of `sift analyze` and
persist them to `clusters.label`:

- One batched LLM `chat` call per run over the cluster **exemplars only**, under
  a strict `PromptBudget` (breadth-first truncation), from the versioned
  `prompts/cluster_label.md` template (CLI-02).
- `sift show clusters` displays the label once clustering has run, and falls
  back to the raw `signature` until then, when `--no-label` is passed, or when
  no inference endpoint is configured.
- Label parsing is lenient (`{index: label}`): on any parse or chat failure the
  labels stay NULL and clusters degrade to their `signature` — the run never
  crashes.
- The label-prompt hash is recorded in `meta` so a template change is
  detectable.

## Consequences

- `sift show clusters` is human-readable immediately after `analyze`, without
  the Phase-6 report path — M3 acceptance is demonstrable in isolation.
- Labelling costs one extra LLM round-trip per `analyze` run; the `--no-label`
  and no-endpoint paths skip it and keep the signature.
- A malformed or hostile label response degrades gracefully to the signature
  rather than corrupting cluster state (never crashes); label text is
  length-capped and sanitised at render (WR-01 precedent).
- Full JSON-contract enforcement (schema-constrained decoding, repair
  round-trips) is deliberately out of scope here — that machinery lands with
  the hypothesis contract in Phase 4. Labels are freeform this phase.
