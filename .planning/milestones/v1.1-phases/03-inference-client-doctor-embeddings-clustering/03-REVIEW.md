---
phase: 03-inference-client-doctor-embeddings-clustering
reviewed: 2026-07-17T12:54:16Z
depth: deep
files_reviewed: 12
files_reviewed_list:
  - src/sift/llm/client.py
  - src/sift/llm/budget.py
  - src/sift/llm/__init__.py
  - src/sift/store.py
  - src/sift/pipeline/cluster.py
  - src/sift/prompts/cluster_label.md
  - src/sift/prompts/__init__.py
  - src/sift/cli.py
  - src/sift/config.py
  - pyproject.toml
  - docs/decisions/0004-cluster-label-timing.md
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues
---

# Phase 3: Code Review Report

**Reviewed:** 2026-07-17T12:54:16Z
**Depth:** deep (cross-file: SSRF boundary, transaction atomicity, label index-mapping trace)
**Files Reviewed:** 12 (source only; tests + planning docs read for context, not scored)
**Status:** issues_found (advisory — phase gate already green)

## Summary

This phase adds the project's first network boundary (`InferenceClient`), the
first untrusted-server-response parsing surface, the sqlite-vec vector store, the
clustering/label pipeline, `sift doctor`, and the WR-07 disk-full fix. I reviewed
adversarially against the highlighted security surface.

**The security-sensitive core is sound.** The SSRF guard (`_assert_local`) is
correct in the egress-prevention direction: it accepts only the `localhost`
name, `*.localhost`, and literal loopback/RFC1918/link-local IPs; it never
resolves DNS; string-encoded decimal/hex/octal IPs and userinfo/trailing-dot
tricks all *fail closed* (refused, not bypassed); IPv4-mapped public addresses
(`::ffff:8.8.8.8`) are refused. The guard runs at construction and
`--i-know-what-im-doing` is the only override. Untrusted responses are parsed
defensively (`_json_object`, `_coerce_vector`, `_order_by_index` — index range,
duplicate, and count checks all present; content length-capped). Cluster labels
and signatures are whole-line `_sanitise`'d before display, the label prompt
instructs data-not-instructions treatment, and label parsing degrades to `{}`
(signature fallback) on any failure without crashing. Float32 serialisation is
explicitly little-endian both ways (no endianness bug). The dimension-mismatch
guard hard-errors before any write. The WR-07 handler is correctly ordered
before the generic handler, duplicates the recoverable path inline (no
sibling-except re-raise), and guarantees zero committed events for insert-time
`SQLITE_FULL`/`SQLITE_IOERR`.

No Critical findings. Five Warnings and four Info items below — the two most
material are a broken finite-number contract on embedding vectors (WR-01) and a
pre-transaction dimension lock that can wedge a case after a transient failure
(WR-02).

## Warnings

### WR-01: `_coerce_vector` accepts NaN / ±Infinity despite its "finite" contract

**Status:** fixed (03-fix, commit 1bee0a0) — `math.isfinite` guard added; NaN/±Infinity now rejected.
**File:** `src/sift/llm/client.py:106-116`
**Issue:** The docstring states "Validate one embedding is a non-empty list of
**finite** numbers (T-03-06)", but the code only rejects `bool` and non-`int/float`
types — it never checks `math.isfinite`. Python's `json.loads` parses the bare
tokens `NaN`, `Infinity`, `-Infinity` into float `nan`/`inf` by default (verified
in-repo: `json.loads('[NaN, Infinity, -Infinity]')` → `[nan, inf, -inf]`). A
malicious or buggy local server can therefore return non-finite embeddings that
pass validation. Blast radius: `sift doctor`'s probe reports "embedding
round-trip OK: dimension N" on an all-NaN vector (the `not vectors[0]` check
sees a non-empty list), giving a false-healthy verdict; and non-finite values
flow into `normalize`/HDBSCAN in `cluster_and_label` (they raise there and are
caught, so no persist — but the contract is still violated and the doctor
false-OK is real).
**Fix:**
```python
import math
# in _coerce_vector, per value:
if isinstance(value, bool) or not isinstance(value, (int, float)) \
        or not math.isfinite(value):
    raise ValueError("embedding contains a non-finite or non-numeric value")
```

### WR-02: embedding dimension is committed outside the transaction — a transient failure permanently locks a zero-vector case

**Status:** fixed (03-fix, commit eaa48bd) — `ensure_vectors_table` folded into the persistence `store.transaction()`; the dim lock now rolls back on any mid-run failure.
**File:** `src/sift/pipeline/cluster.py:300-342` and `src/sift/store.py:594-620`
**Issue:** `cluster_and_label` calls `store.ensure_vectors_table(dim)` *before*
`with store.transaction():`. `ensure_vectors_table` runs `CREATE VIRTUAL TABLE`
(DDL) plus `set_meta("embedding_dim", …)` / `set_meta("embedding_metric", …)`,
which auto-commit (they must — otherwise the subsequent `BEGIN IMMEDIATE` in
`transaction()` would raise "cannot start a transaction within a transaction"; the
passing tests confirm these writes commit before the explicit BEGIN). If anything
between the embed call and the transaction fails — e.g. `_cluster_labels`/HDBSCAN
raises (WR-01 non-finite input, or any sklearn error) — `meta.embedding_dim` is
already committed with **zero vectors persisted**. On the next `analyze` with a
different embedding model, `ensure_vectors_table` hits the mismatch guard and
hard-errors "embedding dimension mismatch" even though the case holds no vectors,
wedging the case until the operator manually edits `meta`. This also contradicts
the `cli.py:647-650` comment claiming "an interrupted embed … nothing survives."
**Fix:** Fold the dimension record and DDL into the same `store.transaction()` as
the vector writes so a failed run leaves `embedding_dim` unset:
```python
with store.transaction():
    store.ensure_vectors_table(dim)   # DDL + dim meta now atomic with the writes
    store.upsert_vectors(vector_rows)
    store.replace_chunks(chunks)
    store.replace_clusters(clusters)
    ...
```
(Verify vec0 `CREATE VIRTUAL TABLE IF NOT EXISTS` inside an open transaction on
the pinned sqlite-vec 0.1.9 — it is supported; the M4 live UAT can confirm.)

### WR-03: embedding-model provenance is never persisted on the production path

**Status:** fixed (03-fix, commit 62e2437) — `InferenceClient.embedding_model` captures the server-reported model; `cluster_and_label` records it via `record_embedding_identity` inside the persistence transaction.
**File:** `src/sift/store.py:622-638` and `src/sift/pipeline/cluster.py:300-302`
**Issue:** `record_embedding_identity(model, dim)` is the STORE-03 method meant to
record the embedding model for provenance/determinism, but it is called *only from
tests* (`tests/test_store_vectors.py`) — never from `cluster_and_label`, which
records the dimension (via `ensure_vectors_table`) but never `embedding_model`. So
`meta.embedding_model` stays unset in every real run, and (per the determinism
invariant) a report can never state which embedding model produced the index. The
method is effectively dead outside tests.
**Fix:** In `cluster_and_label`, after `dim = len(vectors[0])`, record the model
inside the transaction: `store.record_embedding_identity(cfg-or-endpoint model, dim)`
— passing `client._embeddings.model` (or thread the resolved model id through).
Prefer wiring this into the same atomic block proposed in WR-02.

### WR-04: `InferenceClient.models()` egresses to an arbitrary endpoint without re-running the SSRF guard

**File:** `src/sift/llm/client.py:261-286`
**Issue:** `_assert_local` runs only at construction against `self._generation`
and `self._embeddings`. `models(self, endpoint: Endpoint)` then issues a live
`GET {endpoint.base_url}/models` to whatever endpoint the caller passes — the
guard is not enforced per-call. It is currently safe *only by convention*
(`doctor` happens to pass the two constructor-validated endpoints), which is
exactly the "enforced at construction, not per-call" gap the threat model warns
about: a future caller passing an unvalidated/public endpoint would bypass the
SSRF guard entirely.
**Fix:** Either drop the parameter and iterate the two stored endpoints, or
re-assert inside the method — the endpoint is already known-good in the only
current caller, so the cheap defence-in-depth is:
```python
def models(self, endpoint: Endpoint) -> list[str]:
    _assert_local(endpoint.base_url, self._allow_public)  # store allow_public in __init__
    ...
```

### WR-05: commit-time `SQLITE_FULL` escapes the WR-07 handler as a raw traceback

**File:** `src/sift/cli.py:236-373` (loop handler at 296-313) and `src/sift/store.py:390-404`
**Issue:** The WR-07 `sqlite3.Error` handler only wraps the *per-file* insert body
inside the loop. If the disk fills at the final `COMMIT` (`transaction.__exit__`,
`store.py:404`) — the classic point a large ingest exhausts space — the raised
`sqlite3.OperationalError` (SQLITE_FULL maps to `OperationalError`) propagates out
of `with store.transaction():`, past the loop's try/except, and out of `_ingest`.
`ingest` catches only `DiskFullError`, so the operator gets an unsanitised Python
traceback instead of the loud "disk full … no events committed" message. The
data invariant still holds (a failed COMMIT commits nothing), so this is a
robustness/UX defect, not data loss.
**Fix:** Classify the failure where the transaction is driven. Simplest: in
`ingest`, add a `sqlite3.Error` arm that reuses the disk-full test and raises
`DiskFullError`, or have `transaction()`'s `else` branch wrap COMMIT:
```python
else:
    try:
        self._conn.execute("COMMIT")
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", None)
        if code == sqlite3.SQLITE_FULL or (code is not None and code & 0xFF == sqlite3.SQLITE_IOERR):
            raise  # let ingest translate; or raise a shared storage-exhaustion error
        raise
```

## Info

### IN-01: `PromptBudget.fit` ignores template + numbering overhead and the exact tokenizer

**File:** `src/sift/llm/budget.py:49-64`
**Issue:** `fit` budgets only the excerpts (`max_chars = per_excerpt * 4`) and
uses the `//4` char heuristic even when `has_tokenize` is true, ignoring the
~200-token `cluster_label.md` preamble and the `"N. "` numbering that
`build_label_prompt` prepends. For the 4096-token label slice this cannot
overflow in practice and is a self-declared `ponytail:` deferral to Phase 4, so
it is informational — but the deferral should be tracked so full triage-prompt
budgeting (Phase 4) actually accounts for prompt scaffolding.
**Fix:** In Phase 4, subtract the estimated template/scaffold tokens from
`budget` before the per-excerpt division, and honour the exact tokenizer in the
truncation loop.

### IN-02: `_sanitise` preserves tab, so a label/signature tab misaligns `show clusters` columns

**File:** `src/sift/cli.py:505-521` (render) and `_sanitise` at `cli.py:55-75`
**Issue:** `show clusters` only strips `\n` from the name (`.replace("\n", " ")`)
and relies on `_sanitise`, which intentionally keeps `\t`. A cluster signature
carrying a tab from log content (or an LLM label containing one) will jump the
fixed-width columns. Cosmetic only — no injection risk (the terminal-hostile
bytes are already stripped).
**Fix:** Extend the newline replacement to whitespace-fold the rendered name:
`name = re.sub(r"\s", " ", c.label or c.signature)[:100]`.

### IN-03: `SIFT_*` scalar env map omits `backoff_base` and every `[clustering]` key

**File:** `src/sift/config.py:87-96` (`_ENV_SCALARS`)
**Issue:** The docstring frames Phase 3 as adding "the generalised `SIFT_*` ->
nested-key scalar mapping", but `_ENV_SCALARS` covers only 8 of the
generation/embeddings scalars — `SIFT_GENERATION_BACKOFF_BASE` and all five
`clustering` scalars (`algorithm`, `min_cluster_size`, `min_samples`, `epsilon`,
`distance_threshold`) are TOML/flag-only. This is a documented-but-uneven surface,
not a bug; flag/TOML precedence still works. Worth noting so the gap is
intentional rather than an oversight.
**Fix:** Add the missing scalars to `_ENV_SCALARS` (they are all pydantic-coerced
from strings already), or narrow the module docstring to say which sections the
env mechanism currently covers.

### IN-04: `show clusters` queries the clusters table twice

**File:** `src/sift/cli.py:511-518`
**Issue:** The command runs `store.query_clusters()` (unfiltered, to decide the
view) and then `store.query_clusters(parsed or None)` (filtered, to render) — two
full scans of the clusters table. The two-query design is deliberate (decide the
view on the unfiltered table so an all-excluding filter still shows the clusters
view), but the *existence* check does not need the full row payload.
**Fix:** Add a cheap `has_clusters()` (`SELECT 1 FROM clusters LIMIT 1`) for the
view decision and reserve `query_clusters(filters)` for rendering.

---

_Reviewed: 2026-07-17T12:54:16Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
