---
phase: 03-inference-client-doctor-embeddings-clustering
plan: 05
subsystem: pipeline
tags: [clustering, hdbscan, agglomerative, embeddings, llm-labels, prompts, clus-02, clus-03, cli-02, eval-05]
status: complete

# Dependency graph
requires:
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 02
    provides: InferenceClient.embed/chat, PromptBudget label-slice seam
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 03
    provides: store chunks/clusters tables, ensure_vectors_table, upsert_vectors, replace_chunks, replace_clusters, set_cluster_labels, Cluster dataclass, lazy vec0 + dim guard
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 01
    provides: ClusteringConfig ([clustering] section, D-04 tuned defaults)
  - phase: 02-case-store-template-dedup
    provides: template groups + exemplars (dedup.rebuild_template_groups), typer/print/SQL-free pipeline module contract
provides:
  - "cluster_and_label(store, client, cfg, *, label=True) -> int: embed one exemplar message per template group, HDBSCAN / agglomerative fallback, noise->singleton, eager LLM labels, single-transaction persistence"
  - "exemplar_text / build_label_prompt / _parse_labels: reusable clustering + label-prompt helpers"
  - "src/sift/prompts package + cluster_label.md versioned template (importlib.resources loader)"
  - "ADR 0004: cluster-label timing (D-01) recorded per SPEC §10 #3"
affects: [03-06-cli-analyze-show]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pipeline module mirrors dedup.py: typer/print/SQL-free, reads store, persists via one store.transaction() (caller-owns-transaction)"
    - "HDBSCAN(metric=euclidean) on sklearn.preprocessing.normalize(L2) vectors == cosine; agglomerative fallback uses linkage=average (A2: cosine forbids ward)"
    - "n_groups < min_cluster_size auto-routes to singletons (Open Question 2); HDBSCAN noise -1 -> distinct singleton cluster ids, nothing dropped"
    - "Deterministic cluster ids by first-appearance in canonical query_template_groups order (count DESC, template ASC)"
    - "Versioned prompt via importlib.resources.files(sift.prompts) — editing cluster_label.md changes label output with zero Python change (CLI-02); prompt hash in meta"
    - "Lenient {index: label} JSON parse; any chat/parse failure degrades to signature, never crashes (T-03-19); labels capped by Unicode code points (CLUS-03)"
    - "sklearn ships no stubs: partially-unknown types funnelled through np.asarray + narrow pyright: ignore at the clustering boundary"

key-files:
  created:
    - src/sift/pipeline/cluster.py
    - src/sift/prompts/__init__.py
    - src/sift/prompts/cluster_label.md
    - docs/decisions/0004-cluster-label-timing.md
    - tests/test_cluster.py
  modified: []

decisions:
  - "D-01 recorded as ADR 0004: cluster labels generated eagerly, persisted to clusters.label; show clusters shows label else signature"
  - "cluster_and_label gained a `label: bool = True` kwarg — the --no-label / no-endpoint path skips the chat call and keeps signatures (reconciles the plan's client=None behaviour with the fact embedding always needs a client)"
  - "Embedded text is the first exemplar event MESSAGE (Open Question 1 / A3), gathered via store.iter_event_summaries, degrading to the masked template when absent"
  - "Label budget uses in-module constants (_LABEL_CTX_TOKENS=4096, _LABEL_RESERVE_OUT=512) rather than a /props probe — avoids an extra HTTP round-trip; full triage budgeting is Phase 4"

metrics:
  tasks: 3
  files_created: 5
  files_modified: 0
  new_tests: 15
  full_suite: "251 passed, 2 deselected"
  completed: 2026-07-17

status: complete
---

# Phase 3 Plan 05: Semantic Clustering & LLM Cluster Labels Summary

Synonymous template groups now merge into labelled semantic clusters: one exemplar message per group is embedded, HDBSCAN (or the config-selected agglomerative fallback) clusters the L2-normalised vectors with noise turned into singletons, and one batched local-LLM call labels every cluster from a versioned, editable prompt — all persisted eagerly through the store in a single transaction, proven with injected deterministic vectors and a fake chat (zero network).

## What was built

- **`src/sift/pipeline/cluster.py`** — `cluster_and_label(store, client, cfg, *, label=True) -> int`. Reads `query_template_groups`, gathers each group's first exemplar message (streamed via `iter_event_summaries`), embeds them batched (`client.embed`), lazily sizes the vec0 table (`ensure_vectors_table`), L2-normalises, then clusters:
  - default `HDBSCAN(min_cluster_size, min_samples, cluster_selection_epsilon, metric="euclidean")` (euclidean == cosine on normalised vectors);
  - `AgglomerativeClustering(metric="cosine", linkage="average", distance_threshold=…)` when `cfg.algorithm == "agglomerative"`;
  - `n_groups < min_cluster_size` → auto-singletons (Open Question 2); HDBSCAN noise `-1` → distinct singleton cluster ids.
  - Cluster ids are assigned by first appearance in canonical group order — deterministic across runs. Vectors, chunks and clusters persist inside one `store.transaction()`. Module stays typer/print/SQL-free.
- **`src/sift/prompts/{__init__.py, cluster_label.md}`** — a versioned British-English label template loaded via `importlib.resources`. `build_label_prompt` inlines the template verbatim plus numbered exemplar excerpts, so editing the `.md` changes label output with no Python change (CLI-02). The template hash is written to `meta` (`cluster_label_prompt_hash`).
- **Labelling** — one batched `client.chat` over exemplars only, under a `PromptBudget` breadth-first slice. `_parse_labels` reads `{index: label}` leniently; any chat or parse failure returns `{}` so clusters degrade to their signature (never crashes, T-03-19). Each label is capped at 80 Unicode code points so British/non-ASCII spelling survives.
- **`docs/decisions/0004-cluster-label-timing.md`** — records D-01 (eager labelling) per SPEC §10 #3, mirroring ADR 0001-0003.
- **`tests/test_cluster.py`** — 15 tests: synonyms merge / noise singleton / zero-groups-no-embed / single-group singleton / determinism / agglomerative route / vector+chunk persistence (CLUS-02); labels land on right clusters / unparseable degrades / `--no-label` skips / client=None no-op / British round-trip / code-point cap / prompt-hash meta / template drives prompt / lenient parse (CLUS-03, CLI-02). All via `httpx.MockTransport` — zero sockets (EVAL-05).

## Deviations from Plan

### Design clarifications (no user decision required)

**1. [Rule 3 - Signature clarity] `cluster_and_label` gained a `label: bool = True` keyword.**
- **Why:** the plan behaviour asks for a "client=None skips labelling, clusters keep signature" path, but embedding *requires* a client, so a nullable client cannot both cluster and skip labelling. The `--no-label` / no-endpoint intent is expressed as `label=False`, which skips the chat call and keeps signatures. The literal client=None guard is preserved and unit-tested at the label helper (`_label_clusters(None, …) == {}`).
- **Files:** src/sift/pipeline/cluster.py, tests/test_cluster.py

**2. [Rule 3 - Budget seam] Label budget uses in-module constants, not a `/props` probe.**
- **Why:** avoids an extra HTTP round-trip and keeps the test fake simple; the `PromptBudget` breadth-first truncation still runs. Exact context budgeting is Phase-4 triage work.

### Type-checking notes

- scikit-learn ships no type stubs; `normalize` / `HDBSCAN` / `AgglomerativeClustering` are partially-unknown or carry inaccurate inline stubs (`n_clusters` typed `int`, `copy` typed `str`). Contained with `np.asarray` re-typing at the clustering boundary and narrow, commented `# pyright: ignore` on the exact lines.
- `PromptBudget`'s `_Tokenizer.has_tokenize` is a plain (invariant) attribute while `InferenceClient.has_tokenize` is a read-only property — a pyright false mismatch; the runtime protocol is satisfied. Suppressed narrowly with a comment at the one construction site.

## Threat model coverage

- **T-03-16 (prompt injection from log content):** template instructs the model to treat every excerpt as untrusted data, not instructions; labels are freeform, length-capped, and cannot alter control flow (no tool-calling / schema execution).
- **T-03-17 (adversarial label bytes):** labels capped by code points; downstream `_sanitise` (Plan 06 `show clusters`) strips control/bidi bytes at render.
- **T-03-18 (oversized label/prompt DoS):** `PromptBudget` breadth-first truncation + per-label code-point cap + one batched call.
- **T-03-19 (label-parse failure corrupts state):** lenient parse; on failure labels stay NULL and clusters degrade to signature — never crashes.

## Verification

- `uv run pytest tests/test_cluster.py` → 15 passed (merge, singleton, fallback, labelling, degrade, budget, CLI-02) with zero network.
- Full suite: `251 passed, 2 deselected`. `uv run ruff check` and `uv run pyright` clean across the repo.
- `grep -c 'import typer\|print('` on cluster.py → 0; `linkage="ward"` → 0; `importlib.resources` refs → 3.
- ADR 0004 present, records D-01 eager labelling.

## Known Stubs

None. No hardcoded empty values reach a rendering path; `cluster_and_label` is fully wired to be called by `cli.py analyze` (Plan 06).

## For the next plan (03-06)

- Call `cluster_and_label(store, client, cfg.clustering, label=not no_label)` from `sift analyze` after `rebuild_template_groups`; thread `--no-label` and no-endpoint → `label=False`.
- `sift show clusters` renders `label` when present else `signature`; apply the existing whole-line `_sanitise` to both (T-03-17).

## Self-Check: PASSED

- All 5 created files present on disk (cluster.py, prompts/__init__.py, cluster_label.md, ADR 0004, test_cluster.py).
- All 3 task commits present in git log: `aaef5d6` (cluster), `67f5cb1` (labels + prompt), `ad6559f` (ADR 0004).
