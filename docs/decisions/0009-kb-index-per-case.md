# ADR 0009: KB index lives per-case inside `case.db`, not in a global store

**Status:** Accepted (implementation lands in Phase 6 / M6, plan 06-03)
**Date:** 2026-07-18 (Phase 6 context; recorded per SPEC §10 open-question rule)
**Answers:** SPEC §10 Q5 and Phase 6 RESEARCH Open Question 1 — where does the
knowledge-base (runbooks / prior RCAs) index physically live, and how is it kept
from ever becoming citable case evidence? Cross-refs SPEC.md §5.4 (retrieval),
Phase 6 CONTEXT decision D-01 (KB non-citability), RESEARCH Pattern 4, and
Assumptions A1/A2/A6.

## Context

`sift analyze --kb <dir>` enriches the triage prompt with background reference
material — internal runbooks and prior root-cause analyses — so hypotheses are
generated against relevant institutional knowledge. Two questions had to be
settled before building the data path:

1. **Where does the KB vector index live?** A single global index (e.g.
   `~/.local/share/sift/kb`) shared across every case, or a per-case index
   inside each `case.db`?
2. **How is D-01 enforced?** The load-bearing anti-hallucination invariant is
   `cited ⊆ prompted ⊆ store`: every cited event id must exist in the case
   store and must have been in the prompt. KB chunks are reference text, NOT
   case evidence — they must never be citable. If a KB chunk could ever acquire
   an `event_id`, a model could "cite" a runbook line and the citation gate
   would wrongly pass.

## Decision

**1. The KB index lives per-case, in the same `case.db`, in a physically
separate namespace.** Migration 5 adds `kb_chunks(kb_chunk_id, source_file,
ordinal, text)` and a lazily-created `kb_vectors` vec0 table (dim unknown until
the first embed, mirroring `ensure_vectors_table`). These are distinct tables
from the citable `chunks` / `vectors` — a shared table with a discriminator flag
is explicitly rejected, because a flag is a runtime property that a bug or a
tampered `case.db` could flip, whereas separate tables make miscitation
structurally impossible.

**2. D-01 non-citability is structural, not prompt-worded.** `kb_chunks` has NO
`event_id` column anywhere. A KB row therefore cannot be assigned an event id,
`knn_kb_chunks` returns KB *texts* only (never ids), and `prompted_ids` stays
event-exemplars-only — so the citation gate (`hypothesise._all_cited_within`)
mechanically excludes KB chunks. A structural test
(`PRAGMA table_info(kb_chunks)` has no `event_id`) guards this.

**3. MVP chunking and retrieval defaults are in-code constants (Assumptions
A2/A6), no config surface yet.** `KB_CHUNK_CHARS = 800` (paragraph/heading-
bounded, no overlap → deterministic re-indexing) and `KB_TOP_K = 5`. The KB
shares the case's embedding model and dimension and reuses the existing
`meta.embedding_dim` hard-fail guard (Pitfall 3), so a dimension mismatch is
never silently re-indexed.

## Consequences

- **One-file portability + determinism (Assumption A1):** the KB travels,
  copies, and deletes with `case.db`; re-ingestion is idempotent and a case is a
  single self-contained artefact — matching SPEC's one-file-per-case model.
- **All KB vector access stays behind the `store.py` interface** (via the
  confined `_vec_to_blob`/`_blob_to_vec` pair), so switching to a global index —
  or swapping sqlite-vec for a numpy brute-force scan — remains a clean, later,
  behind-the-interface change with no pipeline rewrite.
- **Accepted debt (Assumption A1):** a KB shared across many cases is
  re-embedded per case (wasteful but deterministic and low-risk for MVP). A
  global index is the documented later switch, not a reason to add daemon-backed
  storage now.
- **RAG-07's bar is met:** pointing retrieval at a KB dir demonstrably changes
  the retrieved context (the planted-chunk test), without weakening
  `cited ⊆ prompted ⊆ store`.
