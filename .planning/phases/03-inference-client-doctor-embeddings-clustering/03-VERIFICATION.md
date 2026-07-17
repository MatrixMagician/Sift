---
phase: 03-inference-client-doctor-embeddings-clustering
verified: 2026-07-17T00:00:00Z
status: passed
resolution: "Live-server UAT signed off 2026-07-17 on Fedora Strix Halo (AMD Ryzen AI MAX+ 395) against Lemonade Server v10.4.0 on :13305. sift doctor passed with a real /v1/embeddings round-trip (dim 1024, vec_version v0.1.9), correctly named the embeddings-unsupported failure when no embedding model is loaded, and the case dim-vs-index check matched; sift analyze merged synonymous template groups into 3 labelled clusters offline, with graceful signature fallback when the model returned no parseable labels; loopback/RFC1918 refusal confirmed; embedding model identity + dim + metric persisted in meta. pytest -m live PASSES with LIVE_EMBEDDING_MODEL set (test made multi-model-server-aware). See 03-UAT.md."
score: 5/5 must-haves verified (code + automated tests) + live-server UAT confirmed
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Start a real llama-server (or Lemonade) generation + embedding endpoint on :13305 and run `uv run sift doctor <case>` (and the @pytest.mark.live suite: `uv run pytest -m live`)."
    expected: "doctor verifies both endpoints with real round-trips, reports model IDs, the real /v1/embeddings probe returns a dimension, the dim is checked against the case index, sqlite-vec vec_version loads, and a multi-slot/random-seed server prints a determinism WARNING without failing. Against a Lemonade OGA/ONNX-recipe embedding model it fails with the named 'embeddings unsupported on this model/recipe…' message. `sift analyze <case>` then embeds/clusters/labels and `sift show clusters` renders labels."
    why_human: "SC1 requires a pass against a *live* inference server; the entire default suite runs socket-blocked against a fake OpenAI-compatible server (EVAL-05). Real-server round-trip behaviour (actual embedding dims, real model recipes, live determinism props, LLM label quality) cannot be exercised in-process and is the phase's headline manual UAT item."
---

# Phase 3: Inference Client, Doctor, Embeddings & Clustering — Verification Report

**Phase Goal:** Sift talks to local inference safely and verifiably — endpoints health-checked, embeddings dimension-guarded, synonymous template groups merged into labelled clusters
**Verified:** 2026-07-17
**Status:** human_needed (all code-level truths VERIFIED; one live-server confirmation for a human)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria — the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | `sift doctor` verifies both endpoints with real round-trips (incl. a real embedding call), reports model IDs, checks dim vs existing index, warns on determinism-breaking config | ✓ VERIFIED (code/tests); live pass → human | `cli.py:706-866` runs a 7-step fail-fast sequence: construct→GET gen /v1/models→GET emb /v1/models→REAL POST /v1/embeddings (`client.embed([...])`, l.796)→dim-vs-index→`vec_version()`→`/props` determinism WARNINGs (stderr, non-fatal). Each critical exits non-zero. Tests `test_doctor.py::{test_oga_onnx_empty_embedding_fails_with_named_message, test_dimension_mismatch_names_both_dims, test_unreachable_generation_stops_before_embeddings}` pass. **Live-server pass is a human UAT item.** |
| SC2 | Embeddings persist model identity + dim in `meta`; mismatch on reload is a hard error; llama.cpp features feature-detected so Lemonade works unmodified | ✓ VERIFIED | `store.py::ensure_vectors_table` (l.594) raises `ValueError` naming both dims **before** loading the extension or writing; `record_embedding_identity` (l.622) records `embedding_model`; `embedding_dim`/`embedding_metric` set in meta. Feature detection in `client.py::has_tokenize/has_props/tokenize/props` degrades to `None`/`{}` on absent endpoint (never raises). Tests `test_store_vectors.py::{test_ensure_vectors_table_dim_mismatch_is_hard_error, test_record_embedding_identity_guards_dim}` pass. |
| SC3 | HDBSCAN (L2-normalised, min_cluster_size=2) merges planted synonymous groups; noise → singleton; config-driven agglomerative fallback works | ✓ VERIFIED | `cluster.py::_cluster_labels` uses `sklearn.cluster.HDBSCAN`, `metric="euclidean"` on `normalize(..., norm="l2")` output, `min_cluster_size` from config (default 2); `_assign_cluster_ids` turns `-1` noise into fresh singleton ids; agglomerative fallback (`metric="cosine"`, `linkage="average"`, `distance_threshold`) on `cfg.algorithm=="agglomerative"` OR `n<min_cluster_size`. Tests `test_cluster.py::{test_cluster_merges_synonyms_and_singletons_noise, test_cluster_agglomerative_fallback_routes_and_merges, test_cluster_single_group_is_one_singleton, test_cluster_zero_groups_returns_zero_no_embed}` pass. |
| SC4 | Each cluster gets a short LLM label from exemplars only, under a strict token budget, from versioned prompt files — changing a prompt touches no Python | ✓ VERIFIED | ONE batched `client.chat` over exemplars (`cluster.py::_label_clusters`), bounded by `PromptBudget.fit` (breadth-first, `budget.py`); prompt is `prompts/cluster_label.md` loaded via `importlib.resources.files` (l.191); prompt hash recorded to `meta.cluster_label_prompt_hash`; labels capped by code points (`_MAX_LABEL_CHARS`). Lenient parse degrades to signature. LLM label *quality* is a live-LLM concern folded into the SC1 human item; the mechanism is verified. |
| SC5 | Non-loopback/non-RFC1918 endpoint refused without `--i-know-what-im-doing`; entire suite passes with zero network via injectable client + fake server | ✓ VERIFIED | `client.py::_assert_local` (l.53) refuses public literals at construction unless `allow_public`; accepts `localhost`/loopback/RFC1918/link-local; never DNS-resolves. Wired through the CLI `--i-know-what-im-doing` flag on doctor+analyze. `conftest.py::_no_network` (autouse) monkeypatches `socket.socket.connect` to block. Gate: 260 passed / 2 deselected. Tests `test_llm_client.py::{test_assert_local_refuses_public[8.8.8.8/172.32.0.1], test_assert_local_accepts_loopback_and_rfc1918}` pass. |
| WR-07 | A SQLITE_FULL/IOERR mid-ingest aborts with DiskFullError, exits non-zero, leaves zero committed events | ✓ VERIFIED | `cli.py:296-326` catches `sqlite3.Error` **before** the generic `except Exception`, detects `SQLITE_FULL`/`SQLITE_IOERR` (incl. extended low-byte), raises `DiskFullError`; ingest boundary (l.155) converts to `typer.Exit(1)`. Recoverable per-file path duplicated inline (a sibling except cannot catch a re-raise). Test `test_disk_full.py::test_disk_full_mid_ingest_aborts_with_zero_events` passes. |

**Score:** 5/5 success criteria verified at code + automated-test level (+ WR-07 carried-forward fix). 1 live-server confirmation (SC1) routed to human. 0 behavior-unverified (every behavior-dependent truth has a passing named test).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/llm/client.py` | Single hand-rolled httpx client, SSRF guard, backoff, feature-detect | ✓ VERIFIED | 342 lines; only vendor-free httpx; all controls present |
| `src/sift/llm/budget.py` | PromptBudget token seam, breadth-first truncation | ✓ VERIFIED | `estimate` (tokenize else //4), `fit` breadth-first |
| `src/sift/store.py` | Migration 3, lazy vec0, dim guard, confined (de)serialisation | ✓ VERIFIED | `_migration_3`, `ensure_vectors_table`, `_vec_to_blob/_blob_to_vec`, `upsert_vectors`, `replace_clusters`, `set_cluster_labels` |
| `src/sift/pipeline/cluster.py` | HDBSCAN + agglomerative, noise→singleton, lenient label | ✓ VERIFIED | typer/print/SQL-free; single `store.transaction()` |
| `src/sift/prompts/cluster_label.md` | Versioned label prompt (CLI-02) | ✓ VERIFIED | Loaded via importlib.resources; prompt-injection guard text present |
| `src/sift/config.py` | `[embeddings]`/`[clustering]`/generation sections, extra=forbid | ✓ VERIFIED | `EmbeddingsConfig`/`ClusteringConfig`/`GenerationConfig`; `model=None` default (D-03); clustering knobs present |
| `src/sift/cli.py` | doctor (fail-fast, real embed), analyze, show clusters, WR-07 | ✓ VERIFIED | doctor l.706, analyze l.557, show clusters l.499, disk-full l.296 |
| `docs/decisions/0004-cluster-label-timing.md` | ADR for D-01 | ✓ Present (declared artifact) | Referenced by plan 05 |
| Test files (7) | Fake-server, zero-socket coverage | ✓ VERIFIED | test_{llm_client,budget,store_vectors,cluster,doctor,analyze,disk_full}.py all present |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| config Endpoints | InferenceClient construction | doctor/analyze build `Endpoint` from config | ✓ WIRED |
| InferenceClient.embed/chat | cluster.py | `cluster_and_label(store, client, cfg)` | ✓ WIRED |
| store.ensure_vectors_table/upsert_vectors/replace_clusters | cluster.py | inside one `store.transaction()` | ✓ WIRED |
| meta.embedding_dim | doctor dim check | `store.get_meta("embedding_dim")` compared to server dim | ✓ WIRED |
| cluster_and_label | analyze command | called under transient stderr progress | ✓ WIRED |
| store.query_clusters | show clusters | label-or-signature rendering, whole-line `_sanitise` | ✓ WIRED |
| DiskFullError | ingest boundary | raised in `_ingest`, caught at `ingest`, `typer.Exit(1)` | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Synonym merge + noise singleton | `pytest test_cluster.py::test_cluster_merges_synonyms_and_singletons_noise` | passed | ✓ PASS |
| Agglomerative fallback merges | `pytest test_cluster.py::test_cluster_agglomerative_fallback_routes_and_merges` | passed | ✓ PASS |
| Label parse failure → signature | `pytest test_cluster.py::test_label_unparseable_keeps_signature` | passed | ✓ PASS |
| Dim mismatch hard error (store) | `pytest test_store_vectors.py::test_ensure_vectors_table_dim_mismatch_is_hard_error` | passed | ✓ PASS |
| Embedding identity dim guard | `pytest test_store_vectors.py::test_record_embedding_identity_guards_dim` | passed | ✓ PASS |
| Disk-full → zero committed events | `pytest test_disk_full.py::test_disk_full_mid_ingest_aborts_with_zero_events` | passed | ✓ PASS |
| SSRF refuse public / accept local | `pytest test_llm_client.py::test_assert_local_{refuses_public,accepts_loopback_and_rfc1918}` | passed | ✓ PASS |
| Doctor OGA/ONNX named failure | `pytest test_doctor.py::test_oga_onnx_empty_embedding_fails_with_named_message` | passed | ✓ PASS |
| Doctor dim mismatch names both | `pytest test_doctor.py::test_dimension_mismatch_names_both_dims` | passed | ✓ PASS |
| Doctor fail-fast stops early | `pytest test_doctor.py::test_unreachable_generation_stops_before_embeddings` | passed | ✓ PASS |

(19 selected tests passed in 0.61s. Full gate reported green: ruff clean, pyright 0 errors, pytest 260 passed / 2 deselected.)

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| LLM-01 | 03-01, 03-02 | ✓ SATISFIED | Single httpx client, per-role base_urls, timeouts, backoff, batched embeddings, no vendor SDK |
| LLM-02 | 03-02, 03-04 | ✓ SATISFIED | `_assert_local` SSRF guard + `--i-know-what-im-doing` override wired |
| LLM-03 | 03-04 | ✓ SATISFIED (code); live pass → human | Real embedding round-trip, model IDs, dim check, determinism warn |
| LLM-04 | 03-02 | ✓ SATISFIED | `/props`/`/tokenize` feature-detected, degrade gracefully |
| STORE-03 | 03-03 | ✓ SATISFIED | Identity+dim in meta; mismatch = hard error before write |
| CLUS-02 | 03-01, 03-05 | ✓ SATISFIED | HDBSCAN L2 min_cluster_size=2, agglomerative fallback, noise→singleton |
| CLUS-03 | 03-05, 03-06 | ✓ SATISFIED | Eager LLM label, versioned prompt, code-point cap, signature fallback |
| RAG-05 | 03-02 | ✓ SATISFIED | PromptBudget tokenize-or-//4, breadth-first truncation |
| CLI-02 | 03-05 | ✓ SATISFIED | Prompt is a template file loaded via importlib.resources; hash in meta |
| EVAL-05 | 03-02..06 | ✓ SATISFIED | Injectable client + fake server; autouse socket-block fixture; 260 passing |

No orphaned requirements: all 10 phase IDs appear in plan frontmatter and are marked Complete in REQUIREMENTS.md.

### Anti-Patterns Found

None. No TBD/FIXME/XXX/HACK/PLACEHOLDER markers in any phase-modified source. One `ponytail:` intent comment in `budget.py` (documented char-cap simplification with named upgrade path — not debt). No vendor SDK (openai/langchain/llamaindex/instructor) imported anywhere in `src/`. httpx confined to `client.py` + `cli.py` (doctor/analyze construction seam). Vector bytes confined to `store.py`; `cli.py`'s only vector reference is reusing `store.vec_version()` for the doctor availability check (no serialisation). No standalone `hdbscan` package.

### Prohibitions (must-NOT — judgment tier)

| Prohibition | Status | Evidence |
|-------------|--------|----------|
| No vendor LLM SDK anywhere in src/ | ✓ HELD | grep for openai/langchain/llama_index/instructor: none |
| No test opens a real socket | ✓ HELD | autouse `_no_network` blocks `socket.connect`; MockTransport/respx used |
| Endpoint check never DNS-resolves | ✓ HELD | `_assert_local` accepts only literal IPs + `localhost` name |
| sqlite-vec never loaded eagerly in `__init__` | ✓ HELD | `_vec_loaded=False`; loaded only in `_ensure_vec_loaded` (first embed) |
| No vector bytes serialised outside store.py | ✓ HELD | `_vec_to_blob/_blob_to_vec` confined; cli only calls `vec_version()` |
| Dimension mismatch never silently re-indexes | ✓ HELD | hard ValueError before any write |
| doctor never infers embedding capability from /v1/models | ✓ HELD | real `client.embed([...])` probe (l.796); OGA/ONNX named message |
| doctor never continues past first critical | ✓ HELD | each critical raises `typer.Exit(1)` |
| No live-server test in default suite | ✓ HELD | `@pytest.mark.live` excluded by `addopts = -m 'not perf and not live'` |
| cluster.py: no typer/print/raw SQL | ✓ HELD | persistence only via CaseStore methods |
| Changing cluster_label.md needs no Python | ✓ HELD | template read verbatim into prompt |
| Label-parse failure never crashes | ✓ HELD | `_parse_labels` returns {} on any error → signature |
| No schema-constrained decoding for labels | ✓ HELD | plain chat + lenient JSON parse |
| Untrusted text never enters a rich renderable | ✓ HELD | progress uses static `TextColumn("Embedding")` |
| No salience/hypothesis/citation machinery added | ✓ HELD | analyze is clustering+label only; report/hypotheses still stubs |

All prohibitions are judgment-tier and observed HELD in the code. Formal human sign-off of the prohibition set is folded into the phase human checkpoint.

### Human Verification Required

**1. Live inference-server round-trip (SC1 / LLM-03 headline UAT + `@pytest.mark.live` suite)**

- **Test:** With a real llama-server (generation + `--embeddings`) or Lemonade on :13305, run `uv run sift doctor <case>`, then `uv run pytest -m live`, then `uv run sift analyze <case>` and `uv run sift show clusters`.
- **Expected:** doctor passes both endpoints with real round-trips, reports model IDs, the real `/v1/embeddings` probe returns a dimension checked against the case index, `vec_version` loads, and determinism-breaking config warns without failing; a Lemonade OGA/ONNX embedding model fails with the named "embeddings unsupported on this model/recipe…" message; analyze embeds/clusters/labels and show clusters renders human-readable labels.
- **Why human:** The whole automated suite runs socket-blocked against a fake server (EVAL-05); real-server behaviour (actual dims, real recipes, live `/props`, LLM label quality) is inherently un-automatable and is the phase's designed manual UAT item.

### Gaps Summary

No gaps. Every ROADMAP success criterion, every requirement ID, every declared artifact, key link, and prohibition is implemented and confirmed in the source, with the behaviour-dependent claims (synonym merge, noise singleton, dimension hard-error, disk-full rollback, SSRF boundary, doctor fail-fast, OGA/ONNX detection, label degradation) each backed by a passing named test. The single outstanding item is the deliberately-deferred confirmation that `sift doctor`/`analyze` pass against a *live* llama-server — flagged `human_needed`, not a defect.

---

_Verified: 2026-07-17_
_Verifier: Claude (gsd-verifier)_
