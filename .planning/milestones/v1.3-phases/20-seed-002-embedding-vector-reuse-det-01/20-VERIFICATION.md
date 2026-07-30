# Phase 20 Verification — SEED-002 Embedding Vector Reuse (DET-01)

**Verified:** 2026-07-30
**Result:** PASS — all 5 plans complete, DET-01 closed, all four ROADMAP success
criteria proven.

---

## Automated Gate

| Gate | Command | Result |
|---|---|---|
| Full suite | `uv run pytest` | **873 passed**, 8 deselected (835 pre-phase baseline + 38 new) |
| Live backend | `sift doctor` against Lemonade 127.0.0.1:13305 | all checks passed — real embedding round-trip at dimension 1024, `sqlite-vec v0.1.9` |
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

## Live-Lemonade Validation (operator's real backend)

The stub-endpoint harness above proves the process boundary but not real backend
behaviour. `verify-det01-live-lemonade.py`, kept alongside this file, runs the
real `sift` console script against the operator's actual **Lemonade instance on
127.0.0.1:13305** (Qwen3-Embedding-0.6B-GGUF, real dimension **1024**,
generation `user.Qwen2.5-14B-Instruct`) through a transparent counting proxy, so
"no embedding work" is proven by **observed HTTP traffic to a genuine backend**
rather than inferred from printed output.

`sift doctor` against the same instance passes all checks, including a real
embedding round-trip at dimension 1024 and `sqlite-vec v0.1.9`.

**17/17 checks passed.** Observed:

```
Lemonade /props -> HTTP 200, starts '<!doctype html><html lang="en"><head><me'
  (HTTP 200 + HTML, not JSON: the exact D-10 condition)

run 1 (cold)      : exit=0  Embeddings: 2 new, 0 reused   /v1/embeddings observed: 1
run 2 (unchanged) : exit=0  Embeddings: 0 new, 2 reused   /v1/embeddings observed: 0
run 3 (--re-embed): exit=0  Embeddings: 2 new, 0 reused   /v1/embeddings observed: 1
run 4 (ctx pinned): exit=0  Embeddings: 0 new, 2 reused   /v1/embeddings observed: 0
run 5 (ctx unset) : exit=0  Embeddings: 0 new, 2 reused   /v1/embeddings observed: 0
    stderr: Warning: the generation prompt budget is estimated rather than
    discovered — the endpoint served no usable context size, so 8192 tokens
    is assumed. Set generation.context in config.toml to pin the real window.

case meta: embedding_dim=1024, embedding_model=Qwen3-Embedding-0.6B-GGUF,
           embedding_new_count=0, embedding_reused_count=2,
           embedding_context=32768, embedding_batch_size=64

all proxied paths: {'/v1/embeddings': 2, '/tokenize': 5,
                    '/v1/chat/completions': 13, '/props': 1}
```

**DET-01 is proven against a real backend:** run 2 on an unchanged case issued
**zero** `/v1/embeddings` requests while still producing a complete triage, and
`--re-embed` issued them again. The persisted meta shows the real 1024
dimension, the real model identity, and the reuse split.

**D-10 is confirmed on the exact reported condition.** Lemonade answers `/props`
with **HTTP 200 and web-UI HTML**, not JSON — which is why the budget cannot be
discovered. `InferenceClient.props()` already handles this correctly (the JSON
parse raises, is caught, and `{}` is returned), and:

- with `generation.context` **pinned**, no warning is emitted and the pinned
  value is used (the precedence fix);
- with it **unset**, the `estimated rather than discovered` warning reaches
  stderr and the run still completes at exit 0.

The proxied-path tally also independently confirms the one-request guarantee:
`/props` appears **once**, not once per run leg.

Two harness defects were found and fixed during this validation, neither in
product code. Lemonade's `/api/v1/stats` reports the **last** request's token
counts rather than cumulative totals, so an initial token-delta approach could
not measure embedding work (deltas went negative) and was replaced by the
counting proxy. And the first proxy forwarded `Accept-Encoding` upstream, so it
relayed a gzip body while advertising identity, producing
`inference server returned invalid JSON` — a defect in the measuring
instrument, which the exit code correctly surfaced rather than masked.

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

**None.** The one item previously deferred to human UAT — confirming the D-10
estimated-budget warning against a live Lemonade endpoint — was validated
directly against the operator's running instance (see the Live-Lemonade section
above) and passed, together with the full DET-01 reuse path measured by
server-side request counting.

---

## Conclusion

Phase 20 is **complete**. All 5 plans have SUMMARY files, every plan's
acceptance criteria pass (with three stale or unsatisfiable criteria replaced
by stronger direct tests, each recorded as a deviation in the relevant
summary), and v1.3 is ready for `/gsd-complete-milestone`.
