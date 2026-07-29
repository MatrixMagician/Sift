---
phase: 20
slug: seed-002-embedding-vector-reuse-det-01
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-28
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by `/gsd-plan-phase` from `20-RESEARCH.md` §Validation Architecture.
> Per-task rows are filled once PLAN.md task IDs exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (confirmed via `uv run pytest --version`, 2026-07-28) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`; default `addopts` excludes the `perf` / `live` / `packaging` markers |
| **Quick run command** | `uv run pytest tests/test_cluster.py tests/test_store_vectors.py tests/test_cli.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | quick ~15 s · full suite ~3–5 min (measure and correct at Wave 0) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_cluster.py tests/test_store_vectors.py tests/test_cli.py -x`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** `uv run ruff check && uv run pyright && uv run pytest` all green — the project's "done" gate (CLAUDE.md)
- **Max feedback latency:** ~15 s (quick run)

---

## Per-Task Verification Map

Task IDs land when the planner writes PLAN.md. The behaviours below are the
DET-01 obligations each task must map onto — no behaviour may be left without
an automated command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 20-01-T1 | 20-01 | 1 | DET-01 | — | Second `cluster_and_label` on an unchanged case: zero new embeds, split visible in the returned dataclass | unit | `uv run pytest tests/test_cluster.py -k reuse_zero_embeds -x` | ❌ W0 | ⬜ pending |
| 20-01-T1 | 20-01 | 1 | DET-01 | — | `cluster_and_label` returns a frozen dataclass exposing cluster / embedded / reused counts (D-05) | unit | `uv run pytest tests/test_cluster.py -k returns_result_dataclass -x` | ❌ W0 | ⬜ pending |
| 20-01-T1 | 20-01 | 1 | DET-01 | T-20-07 | Empty edge: first run with no `vectors` table embeds everything and raises nothing | unit | `uv run pytest tests/test_cluster.py -k empty_on_first_run -x` | ❌ W0 | ⬜ pending |
| 20-01-T1 | 20-01 | 1 | DET-01 | — | Empty edge: a partial cache after an interrupted run embeds only the misses | unit | `uv run pytest tests/test_cluster.py -k partial_cache -x` | ❌ W0 | ⬜ pending |
| 20-01-T2 | 20-01 | 1 | DET-01 | — | `sift analyze` prints `Embeddings: {N} new, {M} reused` on every run, including a first run where M is 0 (D-06) | unit | `uv run pytest tests/test_cli.py -k "embedding_split or second_run_reports_reuse" -x` | ❌ W0 | ⬜ pending |
| 20-02-T1 | 20-02 | 2 | DET-01 | — | Model change (both sides known and differing) forces a full re-embed (D-03) | unit | `uv run pytest tests/test_cluster.py -k model_change -x` | ❌ W0 | ⬜ pending |
| 20-02-T1 | 20-02 | 2 | DET-01 | T-20-02 | Unknown model identity on either side: reuse proceeds, warning emitted through the un-swallowable announce seam, never a silent claim of verified identity (D-04) | unit | `uv run pytest tests/test_cluster.py -k unknown_identity -x` | ❌ W0 | ⬜ pending |
| 20-02-T1 | 20-02 | 2 | DET-01 | T-20-08 | Stored vectors of a different width are discarded rather than spliced into a ragged clustering input; the clean STORE-03 error still surfaces | unit | `uv run pytest tests/test_cluster.py -k stored_vector_width -x` | ❌ W0 | ⬜ pending |
| 20-02-T2 | 20-02 | 2 | DET-01 | T-20-09 | `--re-embed` at an unchanged dimension bypasses the cache, embeds everything, performs no DDL (D-07) | unit | `uv run pytest tests/test_cluster.py -k re_embed_bypasses_cache -x` | ❌ W0 | ⬜ pending |
| 20-03-T2 | 20-03 | 3 | DET-01 | T-20-03 | Dimension change WITHOUT `--re-embed` still hard-raises — STORE-03 contract unchanged | unit | `uv run pytest tests/test_store_vectors.py -k dim_mismatch -x` | ✅ (must keep passing unmodified) | ⬜ pending |
| 20-03-T2 | 20-03 | 3 | DET-01 | T-20-03 | Dimension change WITH `--re-embed` drops `vectors` **and** `kb_vectors` in one transaction, announcing the blast radius (D-08 / D-09) | unit | `uv run pytest tests/test_cluster.py -k re_embed_rebuilds -x` | ❌ W0 | ⬜ pending |
| 20-03-T1 | 20-03 | 3 | DET-01 | T-20-10 | After a rebuild, `ensure_kb_vectors_table(new_dim)` creates `kb_vectors` at the NEW width, not a no-op against a surviving old-width table | unit | `uv run pytest tests/test_store_vectors.py -k clears_dim_and_allows_new_width -x` | ❌ W0 | ⬜ pending |
| 20-03-T1 | 20-03 | 3 | DET-01 | T-20-03 | Rollback safety: an interrupted rebuild restores the original vec0 table at its original width | unit | `uv run pytest tests/test_store_vectors.py -k rollback_restores_original_width -x` | ❌ W0 | ⬜ pending |
| 20-04-T1 | 20-04 | 4 | DET-01 | — | Adjacency edge (write side): distinct miss texts deduplicated before embedding; identical text always yields an identical vector (D-02) | unit | `uv run pytest tests/test_cluster.py -k dedupes_identical -x` | ❌ W0 | ⬜ pending |
| 20-04-T1 | 20-04 | 4 | DET-01 | T-20-06 | Adjacency edge (read side): duplicate stored texts resolve deterministically to the highest `chunk_id`, never to unspecified SQLite row order | unit | `uv run pytest tests/test_cluster.py -k duplicate_stored_text -x` | ❌ W0 | ⬜ pending |
| 20-04-T1 | 20-04 | 4 | DET-01 | T-20-13 | Encoding edge: reuse-key equality is exact `str` equality — NFC vs NFD misses and is re-embedded; no normalisation, folding, trimming or `COLLATE` | unit | `uv run pytest tests/test_cluster.py -k exact_text -x` | ❌ W0 | ⬜ pending |
| 20-04-T2 | 20-04 | 4 | DET-01 | — | Ordering edge: mixed hit/miss run byte-identical to a full re-embed, original group order preserved (fake transport only — D-12) | unit | `uv run pytest tests/test_cluster.py -k mixed_hit_miss -x` | ❌ W0 | ⬜ pending |
| 20-04-T2 | 20-04 | 4 | DET-01 | — | Batch-knob change (`context` / `batch_size` / `max_input_chars`) does NOT invalidate reuse (D-11) | unit | `uv run pytest tests/test_cluster.py -k batch_knob -x` | ❌ W0 | ⬜ pending |
| 20-04-T3 | 20-04 | 4 | DET-01 | T-20-14 | ADR 0018 records D-11 and the exact-text key; CONTRIBUTING.md states the run-1 residual rather than overclaiming | doc | `test -f docs/decisions/0018-batch-knob-does-not-invalidate-vector-reuse.md && grep -q 0018 CONTRIBUTING.md` | ❌ W0 | ⬜ pending |
| 20-05-T1 | 20-05 | 3 | DET-01 | T-20-11 | D-10: an explicitly configured `generation.context` wins over a server-reported `/props` `n_ctx`; unconfigured still discovers it | unit | `uv run pytest tests/test_hypothesise.py -k ctx -x` | ❌ W0 | ⬜ pending |
| 20-05-T2 | 20-05 | 3 | DET-01 | T-20-12 | D-10: absent `/props` falls back to the built-in default **and warns** that the budget is estimated rather than discovered | unit | `uv run pytest tests/test_cli.py -k resolve_generation_ctx -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cluster.py` — add the reuse / invalidation / splice-order / dedup cases above. Extends the existing file; reuses the `_client` / `_embed_handler` / `_seed` helpers already present. No new fixture module.
- [ ] `tests/test_store_vectors.py` — add the dim-rebuild-under-`--re-embed` and rebuild-rollback cases. Extends the existing file; reuses the `_tables()` helper already present.
- [ ] `tests/test_cli.py` — add `--re-embed` flag and `Embeddings: N new, M reused` output cases. Check for an existing `analyze` CLI fixture to extend rather than duplicating client-mocking boilerplate.
- [ ] **Update, do not add** — the four `cluster_and_label` call sites that capture the `int` return value must be migrated to the D-05 dataclass: `tests/test_cluster.py:127`, `:181`, `:195`, `:225`, plus `src/sift/cli.py:943`. The discard-the-return call sites (`tests/test_kb_analyze.py:177`, `tests/test_mcm_analyze.py:131`, `tests/test_hypothesise.py:175`, `src/sift/eval/runner.py:86`) need no change but must keep passing.
- [ ] No new test framework or config needed — pytest plus the existing `httpx.MockTransport` fake transport covers everything (EVAL-05 compliant, zero network egress).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-backend cost reduction on a large case | DET-01 | The measured baseline (case `CS1066664`, 1781 template groups, ~1.45 MB of exemplar text) requires a live Lemonade endpoint, which tests may never contact | Run `sift analyze` twice on an unchanged case against the live endpoint; the second run must print `reused` equal to the exemplar count and `new` of 0, and complete substantially faster |

**Note:** DET-01 success criterion 2 (byte-identical mixed hit/miss output) is
**deliberately not** a manual live-backend check. Per D-12, a full re-embed
against a real backend is precisely what perturbs the vectors — asserting byte
identity there would assert the opposite of ADR 0014's measured finding. It is
automated on the deterministic fake transport only.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20 s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
