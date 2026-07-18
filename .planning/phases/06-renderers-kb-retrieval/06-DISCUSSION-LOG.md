# Phase 6: Renderers & KB Retrieval - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-18
**Phase:** 6-renderers-kb-retrieval
**Areas discussed:** KB retrieval (RAG-07), Evidence appendix & [evt:] links, Determinism scope (REPT-03), PDF path (REPT-04)

---

## KB Retrieval (RAG-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Separate index, non-citable | KB in own vec table/namespace; chunks never get event_ids, never citable; enriches prompt as background | ✓ |
| Same vectors table, tagged | KB shares events table with source tag; risks KB becoming citable | |
| In-memory only, per-run | KB embedded fresh each run, never persisted | |

**User's choice:** Separate index, non-citable
**Notes:** Load-bearing for the `cited ⊆ prompted ⊆ store` anti-hallucination invariant — only real case events are evidence.

---

## Evidence Appendix & [evt:] Links

| Option | Description | Selected |
|--------|-------------|----------|
| Intra-doc anchors + capped raw | `[evt:id](#evt-id)` → appendix entry with file:line + raw truncated to a cap | ✓ |
| Full raw, no truncation | Complete raw per event; can balloon on stack traces/MCM blocks | |
| Inline footnotes | Markdown footnotes instead of appendix section | |

**User's choice:** Intra-doc anchors + capped raw
**Notes:** Self-contained one-file report, one click from claim to evidence; cap configurable (~2 KB default) with elision marker.

---

## Determinism Scope (REPT-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Timestamps + abs paths + durations | Exclude these three; everything else byte-identical; seed passed through, llama-server caveats documented | ✓ |
| Timestamps only | Only strip timestamps; likely flaky across machines due to abs paths | |
| Whole-object hash of stable subset | Hash canonical subset instead of byte-diff; weaker guarantee | |

**User's choice:** Timestamps + abs paths + durations
**Notes:** Determinism is a scoped, documented guarantee against nondeterministic local backends — not absolute.

---

## PDF Path (REPT-04)

| Option | Description | Selected |
|--------|-------------|----------|
| MD→HTML→WeasyPrint, URLs off | Reuse Markdown renderer → HTML → WeasyPrint (ADR 0002); external URL fetch disabled; helpful error if extra missing | ✓ |
| Defer PDF to post-M8 | Ship only MD + JSON; leaves REPT-04 unmet | |

**User's choice:** MD→HTML→WeasyPrint, URLs off
**Notes:** Confirms ADR 0002; zero-egress url_fetcher; no traceback when `sift[pdf]` absent.

---

## Claude's Discretion

- KB chunking strategy, retrieval `k`, KB-vs-event prompt-budget share (resolve against Phase 3 PromptBudget).
- Exact Markdown section ordering / metadata layout.

## Deferred Ideas

- REPT-05 report redaction/sanitisation pass — future requirement.
- REPT-06 per-cluster event-volume histogram — deferred.
- Web/TUI report viewer — v2 candidate per SPEC non-goals.

## Correction Noted

- Cluster labelling is already resolved (eager, Phase 3, persisted to `clusters.label`); SPEC §10 open question #3 is closed — `sift report` reads persisted labels, not re-labelled at report time.
