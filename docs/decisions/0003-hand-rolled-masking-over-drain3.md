# ADR 0003: Hand-rolled volatile-token masking over drain3

**Status:** Accepted (implementation lands in Phase 2 / M2)
**Date:** 2026-07-16 (research date; recorded during Phase 1 per D-02)
**Answers:** SPEC.md §10 template-mining question implied by §5.4 (template dedup approach)

## Context

Phase 2's template dedup stage must group near-identical log lines by masking
volatile tokens (numbers, hex, UUIDs, SIDs, OIDs, paths, timestamps) and
grouping by the masked string. The established off-the-shelf option is
drain3, an online log-template miner.

Research (STACK.md, 2026-07-16) found drain3 unfit for this project:

- Last release 0.9.11 on 2022-07-17 — effectively dormant for four years.
- Package metadata claims Python 3.7–3.11 support only; Sift's floor is 3.12.
- Drain learns templates online and order-sensitively, which conflicts with
  Sift's determinism constraint (identical case + config → identical output).
- MicroStrategy-domain tokens (DSSErrors SIDs, OIDs) need domain-specific
  masks that drain3 would never learn cleanly.

Hand-rolled masking is roughly 50 lines of regexes and a group-by: fully
deterministic, auditable, and tunable per adapter.

## Decision

Implement volatile-token masking by hand in `pipeline/dedup.py`, exactly as
SPEC.md §5.4 already describes. Do not add drain3.

## Consequences

- Zero new dependencies; the masking rules are ordinary reviewable code.
- Deterministic grouping — the same input always yields the same templates,
  which the eval harness (M7) depends on.
- Mask regexes must be maintained by hand; adapter-specific masks (e.g.
  DSSErrors SIDs) are added alongside their adapters in Phase 5.
- If template quality ever proves insufficient, the revisit point is a
  deliberate one — not an upgrade of a dormant dependency.
