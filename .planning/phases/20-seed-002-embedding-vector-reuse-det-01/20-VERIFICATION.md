# Phase 20 Verification — SEED-002 Embedding Vector Reuse (DET-01)

**Verified:** 2026-07-30
**Result:** PASS — all 5 plans complete, DET-01 closed, all four ROADMAP success
criteria proven.

---

## Automated Gate

| Gate | Command | Result |
|---|---|---|
| Full suite | `uv run pytest` | **873 passed**, 8 deselected (835 pre-phase baseline + 38 new) |
| Quick run | `uv run pytest tests/test_cluster.py tests/test_store_vectors.py tests/test_cli.py` | 147 passed |
| Lint | `uv run ruff check` | clean |
| Types | `uv run pyright` | 28 errors — **unchanged** from the pre-phase baseline, all confined to `tests/test_cli_eustack.py`, `tests/test_eustack_progression.py`, `tests/test_eustack_report.py` (no new error, and one pre-existing ruff E501 was fixed in `fdf78e9`) |

Measured runtimes correct the plan's estimate: the quick run is ~2.3 s and the
full suite ~6.4 s, not the "~3–5 min" seeded into `20-VALIDATION.md`.

---

## End-to-End Verification Against the Real Binary

Automated tests all drive `httpx.MockTransport`, which cannot prove the shipped
console entry point behaves correctly across process boundaries. A separate
harness — `verify-det01-e2e.py`, kept alongside this file — runs the real `sift`
executable against a stub OpenAI-compatible endpoint on a real loopback socket,
counting actual HTTP embedding requests server-side.

**15/15 checks passed.** Observed output:

```
run 1:              exit=0  Embeddings: 1 new, 0 reused   embed requests: [1]
run 2:              exit=0  Embeddings: 0 new, 1 reused   embed requests: []
run 3 (--re-embed): exit=0  Embeddings: 1 new, 0 reused   embed requests: [1]
run 4 (no model named, isolated config): exit=0  Embeddings: 0 new, 1 reused
run 5 (model changed):                   exit=0  Embeddings: 1 new, 0 reused   embed requests: [1]

run 4 stderr: Warning: reused stored embedding vectors without a verifiable
model identity, so a change of embedding model cannot be detected. Run
sift analyze --re-embed to force a full re-embed.
```

Checks covered: all five runs exit 0; run 1 embeds and reports `0 reused`;
**run 2 makes zero embedding requests** and reports `0 new`; run 2 stays silent
when identity is verifiable; run 4 discloses when identity is genuinely
unverifiable on both sides *and still reuses*; run 5 (a proven model change)
re-embeds everything; `--re-embed` re-embeds and reports `0 reused`.

Two harness bugs were found and fixed during this verification, neither in
product code: `python -m sift.cli` produces no output (there is no
`__main__` guard, so the real console script must be used), and the env
override prefix is single-underscore `SIFT_EMBEDDINGS_BASE_URL`, not double.
Until the second was fixed the harness was silently exercising the operator's
**real** llama-server on 127.0.0.1:8080 rather than the stub — which is itself
incidental evidence that the reuse path works against a live backend.

---

## ROADMAP Success Criteria

| # | Criterion | Evidence |
|---|---|---|
| 1 | A second `analyze` on an unchanged case reports the split explicitly with zero new embeddings, assertable without inspecting mock call counts | `ClusterResult` dataclass + `Embeddings: 0 new, N reused`; `test_reuse_zero_embeds_on_unchanged_case`, `test_analyze_second_run_reports_reuse`, and e2e run 2 (zero server-side requests) |
| 2 | A mixed hit/miss run is byte-identical to a full re-embed | `test_reuse_mixed_hit_miss_matches_full_reembed`, non-vacuous (both counts asserted > 0) |
| 3 | Changing the embedding model or dimension forces a full re-embed rather than reusing stale vectors | `test_reuse_invalidated_on_model_change`, `test_dimension_change_without_re_embed_still_hard_raises`, `test_re_embed_rebuilds_at_new_dimension_and_announces`, and e2e run 5 |
| 4 | A batch-knob change does NOT invalidate reuse, and `--re-embed` is the escape hatch | `test_reuse_survives_batch_knob_change` (all three knobs), `test_re_embed_bypasses_cache_without_ddl`, e2e run 3 |

---

## Edge Coverage

All four edges surfaced by the deterministic edge probe against DET-01 are
covered by automated tests, none dismissed and none left to a backstop:

| Edge | Covered by |
|---|---|
| ordering | plan 20-01 — the order-preserving splice, `test_reuse_partial_cache_embeds_only_misses` |
| empty | plan 20-01 — first run, partial cache, zero groups, all-hit-no-embed |
| adjacency | plan 20-04 — `test_reuse_dedupes_identical_miss_texts`, `test_reuse_duplicate_stored_text_resolves_deterministically` |
| encoding | plan 20-04 — `test_reuse_key_is_exact_text_no_unicode_normalisation` |

---

## Non-Vacuity Proofs

Three assertions were verified destructively — the guard was disabled in-tree,
the test was confirmed to fail, then the guard was restored:

| Assertion | Disabled behaviour |
|---|---|
| Stored-width discard guard (T-20-08) | numpy `inhomogeneous shape` error instead of the clean STORE-03 message |
| `ctx_configured` short-circuit (D-10) | the props request count becomes 2, failing `test_analyze_issues_exactly_one_props_request` |
| Duplicate-text resolution | asserted against the specific higher-`chunk_id` vector *and its negation*, so an identically-seeded fixture cannot pass it |

---

## Threat Model Disposition

`T-20-03` (destructive `--re-embed` dimension rebuild) is the phase's only
**high**-rated threat. It is dispositioned `mitigate` with three independently
tested controls: the announced blast radius sourced from the drop's own return
value, single-transaction atomicity with a proven rollback
(`test_drop_vector_tables_rollback_restores_original_width`), and
unreachability without an explicit `--re-embed`. The block-on-high gate is
satisfied, not bypassed. All other threats are medium or below and mitigated or
explicitly accepted with rationale in the respective plans.

---

## Documentation and Requirement State

- `docs/decisions/0018-batch-knob-does-not-invalidate-vector-reuse.md` created,
  recording D-11, the model/dimension invalidation rules and the exact-text
  reuse key; its Consequences section states plainly that reuse closes ADR
  0014's exposure for run 2 onward but **not** for the first run.
- `CONTRIBUTING.md`'s determinism bullet gains the same qualified claim. The
  ADR 0014 qualification is intact and the claim was **not** upgraded to
  unconditional determinism.
- `DET-01` marked complete in `REQUIREMENTS.md`; **13/13 v1.3 requirements now
  complete**.
- Two folded todos moved to `.planning/todos/completed/`:
  `2026-07-21-embedding-batch-composition-determinism.md` (answered by ADR
  0018) and `2026-07-21-generation-context-unset.md` (closed by plan 20-05).
  `.planning/todos/pending/` is now empty.

---

## Open Items

One manual verification cannot be performed by an agent and is deferred to
human UAT: confirming against a **live Lemonade** endpoint that the D-10
estimated-budget stderr warning appears (Lemonade serves web-UI HTML rather
than a props document, which is the exact condition). The equivalent condition
was exercised against the stub endpoint in e2e run 4, where the warning did
appear, so this is a confirmation rather than an untested path.

---

## Conclusion

Phase 20 is **complete**. All 5 plans have SUMMARY files, every plan's
acceptance criteria pass (with three stale or unsatisfiable criteria replaced
by stronger direct tests, each recorded as a deviation in the relevant
summary), and v1.3 is ready for `/gsd-complete-milestone`.
