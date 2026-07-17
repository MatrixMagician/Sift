---
phase: 03-inference-client-doctor-embeddings-clustering
plan: 06
subsystem: cli
tags: [cli, analyze, show-clusters, clustering, embeddings, llm-labels, clus-03, eval-05, cli-03]
status: complete

# Dependency graph
requires:
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 05
    provides: cluster_and_label(store, client, cfg, *, label=True)
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 04
    provides: _make_http_client seam, doctor client-construction + --i-know-what-im-doing/--model flags
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 03
    provides: store.query_clusters, Cluster dataclass (label/signature/severity_max/count)
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 02
    provides: InferenceClient + Endpoint + SSRF guard
  - phase: 03-inference-client-doctor-embeddings-clustering
    plan: 01
    provides: GenerationConfig/EmbeddingsConfig/ClusteringConfig sections
  - phase: 02-case-store-template-dedup
    provides: _ingest Progress block, _sanitise, _case_store, template groups
provides:
  - "sift analyze <case> [--no-label] [--model] [--i-know-what-im-doing] [--data-dir]: embed->cluster->label leg, transient stderr progress, scriptable stdout summary, atomic persistence"
  - "sift show clusters: renders clusters.label (signature fallback), whole-line _sanitise, template-groups pre-cluster fallback"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "analyze mirrors ingest: _case_store open + try/finally store.close() (WAL checkpoint, Pitfall 4); delegates to the print/SQL/typer-free pipeline.cluster module"
    - "Embedding-leg progress reuses the ingest Progress block: static TextColumn('Embedding'), MofNCompleteColumn, console=Console(stderr=True), transient=True, disable=not is_terminal (CLI-03/T-03-23)"
    - "show clusters decides label-view vs template-groups-view on the UNFILTERED clusters table so an excluding --filter still renders the clusters view (zero matches), never silently reverts"
    - "Interrupted-embed atomicity is free: client.embed is cluster_and_label's first step and precedes every DB write, so a raise leaves zero clusters (one store.transaction())"

key-files:
  created:
    - tests/test_analyze.py
  modified:
    - src/sift/cli.py

decisions:
  - "analyze always constructs the client (embedding needs it) and passes label=not no_label — the 03-05 `label` kwarg supersedes the plan's literal client=None branch; there is no 'no endpoint' path since config always defaults an endpoint"
  - "Zero template groups short-circuits BEFORE building the client ('Nothing to cluster; run sift ingest first', exit 0) — groups>0 always yields >=1 cluster (auto-singleton), so a client round-trip is never wasted on an empty case"
  - "analyze catches (httpx.HTTPError, ValueError) around cluster_and_label and exits 1 with a sanitised message rather than letting a traceback escape (fail-loud convention); the transaction has already rolled back by then"

metrics:
  tasks: 2
  files_created: 1
  files_modified: 1
  new_tests: 9
  full_suite: "260 passed, 2 deselected"
  completed: 2026-07-17
---

# Phase 3 Plan 06: sift analyze + show clusters Summary

`sift analyze` is now the user-visible completion of the M3 slice: it opens a case, constructs the SSRF-guarded inference client, runs the Plan-05 `cluster_and_label` embed→cluster→label leg under a transient stderr-only progress bar, persists atomically, and prints a scriptable stdout summary — and `sift show clusters` surfaces the eager LLM labels (falling back to the raw signature until a label exists), all provable offline against a fake OpenAI-compatible server with zero sockets.

## What was built

- **`src/sift/cli.py` — `analyze` command** (replaced the Phase-4 stub). Signature `analyze(case, --i-know-what-im-doing, --no-label, --model, --data-dir)`. Resolves config with `--model` feeding both roles (D-03), opens the case via `_case_store` inside `try/finally: store.close()` (WAL checkpoint, Pitfall 4). Short-circuits zero template groups with a clean "Nothing to cluster; run 'sift ingest' first" (exit 0). Otherwise builds `Endpoint`s + `_make_http_client` + `InferenceClient(allow_public=i_know_what_im_doing)` — the SSRF guard runs at construction (LLM-02) and a public endpoint without the override exits 1. Calls `cluster_and_label(store, client, config.clustering, label=not no_label)` inside a Progress block copied from `_ingest`: static `TextColumn("Embedding")`, `MofNCompleteColumn`, `console=Console(stderr=True)`, `transient=True`, `disable=not err_console.is_terminal` (CLI-03/T-03-23 — untrusted text never enters a rich renderable; non-TTY renders nothing). Prints `Clusters: N (M labelled)` to stdout. No salience/hypothesis logic (Phase 4 scope).
- **`src/sift/cli.py` — `show clusters` branch.** Once clustering has run, renders the `clusters` table: label-or-signature + count + severity_max, whole-line `_sanitise` (WR-01/T-03-20). The view is decided on the *unfiltered* `query_clusters()` so an excluding `--filter` still renders the clusters view (zero matches) rather than reverting. Until analyze runs, keeps the existing template-groups rendering as the pre-cluster view; the `template_groups_stale` warning is untouched.
- **`tests/test_analyze.py`** — 9 tests, all against an `httpx.MockTransport`-backed client injected through the `_make_http_client` seam (EVAL-05, zero sockets): cluster+label happy path (3 clusters, embed+chat both called), `--no-label` skips the chat call, empty case → "Nothing to cluster" with no client contact, missing case exits 1, public endpoint refused without override, show clusters renders labels after analyze, signature fallback after `--no-label`, hostile control/bidi label bytes stripped at render (T-03-20), and interrupted embed (client raises) leaves zero clusters (T-03-22 atomicity) with show clusters reverting to the template-groups view.

## Deviations from Plan

### Design clarifications (no user decision required)

**1. [Rule 3 - Signature reconciliation] analyze always constructs the client; the plan's `client=None` branch is expressed as `label=not no_label`.**
- **Why:** embedding *requires* a client, so a nullable client cannot both cluster and skip labelling. The 03-05 `cluster_and_label(..., *, label: bool = True)` kwarg is the implemented contract; `--no-label` maps to `label=False` (skips the chat call, clusters keep signatures). There is no "no endpoint configured" path because config always defaults an endpoint (`http://localhost:13305/v1`). This matches the 03-05 "For the next plan" guidance exactly.
- **Files:** src/sift/cli.py

**2. [Rule 2 - Fail-loud] analyze catches `(httpx.HTTPError, ValueError)` around `cluster_and_label`.**
- **Why:** an embed/cluster failure would otherwise escape as a traceback, violating the fail-loud "never a Python traceback" convention. The handler prints a sanitised error and exits 1; because `cluster_and_label` persists inside one `store.transaction()` and `client.embed` is its first step, the rollback (or the pre-write raise) has already left zero clusters by the time the handler runs — atomicity is preserved, tested directly.
- **Files:** src/sift/cli.py, tests/test_analyze.py

## Threat model coverage

- **T-03-20 (adversarial cluster label bytes):** `show clusters` runs the COMPLETE rendered line through `_sanitise` (WR-01 whole-line precedent); labels are code-point-capped upstream (Plan 05). Tested with a C1 CSI byte (U+009B) and a bidi override (U+202E) — neither reaches the terminal, printable text survives. Hazardous bytes are stored in the test as explicit `\x9b`/`\u202e` escapes, never raw.
- **T-03-21 (analyze pointed at a public endpoint):** client construction runs `_assert_local` on both base_urls; refusal unless `--i-know-what-im-doing`. Tested — construction refuses before the transport is reached.
- **T-03-22 (interrupted embed leaves partial state):** all persistence inside one `store.transaction()`; `client.embed` precedes every write. Tested — a mid-embed `ConnectError` leaves `query_clusters()` empty.
- **T-03-23 (untrusted text in a rich renderable):** the progress description is the static string `"Embedding"`; every server/DB string flows through `_sanitise`'d plain prints. stdout stays scriptable; non-TTY renders nothing.

## Verification

- `uv run pytest tests/test_analyze.py` → 9 passed, zero sockets.
- Full suite: `260 passed, 2 deselected` (perf + live excluded). `uv run ruff check` and `uv run pyright` clean repo-wide — end-of-phase gate green.
- `grep -c 'no_label' src/sift/cli.py` ≥ 1; analyze no longer prints "analyze arrives in Phase 4".

## Known Stubs

None. `analyze` and `show clusters` are fully wired to `cluster_and_label` and `query_clusters`; no hardcoded empty values reach a rendering path.

## Manual UAT (deferred to /gsd-verify-work)

- `sift analyze <case>` + `sift show clusters` against a live llama-server / Lemonade on :13305 (real embeddings + labels, real TTY progress bar). Flagged in the plan's verification block.

## Self-Check: PASSED

- tests/test_analyze.py present on disk; src/sift/cli.py modified.
- Task commits present: `d2f5c3e` (analyze leg), `2d04d3b` (show clusters + full-flow tests).
