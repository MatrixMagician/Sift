---
phase: 3
slug: inference-client-doctor-embeddings-clustering
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-17
---

# Phase 3 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Phase 3 introduces the only network surface in Sift: `src/sift/llm/client.py` (the
sole HTTP module, SPEC §5.6), the `sift doctor` diagnostic, embeddings + vector
storage (sqlite-vec), and LLM-generated cluster labels. The register below was
authored at plan time across all six PLAN.md `<threat_model>` blocks and verified
against the implementation at ASVS L1 (grep-depth mitigation presence).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| config.toml / `SIFT_*` env → SiftConfig | User/host-controlled scalars (base_urls, params) become typed config | endpoint URLs, tuning params |
| user/config → base_url | An attacker-influenced endpoint could point at internal/metadata hosts (SSRF) | HTTP target host |
| inference server → client | Every response body (embeddings, chat text, `/props`) is untrusted input | vectors, model text, server props |
| client / DB text → terminal | Server model IDs, error text, and model-generated labels may carry hostile control bytes when rendered | strings printed to TTY |
| shared case.db → query reads | A tampered case.db can hold hostile JSON / vector blobs | cluster/chunk JSON, vec blobs |
| sqlite-vec extension → process | Native extension loading is a code-execution surface | compiled extension |
| storage medium → ingest loop | A full/failing disk raises SQLite errors that must not corrupt atomicity | SQLITE_FULL/IOERR |
| log content → label LLM call | Ingested exemplar text flows into the label prompt (prompt-injection surface) | untrusted log text |
| PyPI → pyproject / uv.lock | Third-party package code (httpx, sqlite-vec, scikit-learn, numpy, respx) enters the trust base | dependency code |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-03-01 | Tampering | disk-full mid-ingest (WR-07) | high | mitigate | `DiskFullError` on SQLITE_FULL/IOERR aborts before the generic per-file handler, zero committed events — `cli.py:41,301-309` | closed |
| T-03-02 | Tampering | malformed config.toml / unknown key | low | mitigate | `ConfigDict(extra="forbid")` on every config model — `config.py:27,39,50,63` | closed |
| T-03-03 | Spoofing | `SIFT_*` env injecting a hostile base_url | low | accept | env only stores the string; `_assert_local` (T-03-04) refuses non-local endpoints at client construction | closed |
| T-03-04 | Information Disclosure / Elevation | base_url pointed at public/metadata/internal host (SSRF/exfil) | high | mitigate | `_assert_local` refuses non-loopback/non-RFC1918 literals at construction, never DNS-resolves; override explicit via `allow_public` — `client.py:54,80,174` | closed |
| T-03-05 | Denial of Service | hostile server streams a huge body / hangs | high | mitigate | explicit httpx timeouts + manual backoff over connect/timeout/5xx; dimension validation; length caps — `client.py:156,191` | closed |
| T-03-06 | Tampering | malformed/empty embeddings response (dimension spoof) | medium | mitigate | each embedding validated as non-empty consistent-length float list; ValueError on mismatch — `client.py:205,239` | closed |
| T-03-07 | Spoofing | server text (model IDs / errors) with control bytes reaches the terminal | medium | mitigate | client returns raw strings; callers `_sanitise` at render — `cli.py:55,93,159,494` | closed |
| T-03-08 | Tampering | reload with mismatched embedding dimension | high | mitigate | `ensure_vectors_table` raises ValueError before any write when `meta.embedding_dim != dim` (STORE-03) — `store.py:594-619` | closed |
| T-03-09 | Elevation | native extension loading (`sqlite_vec.load`) | medium | mitigate | only the vetted `sqlite_vec` loaded; `enable_load_extension(True)→load→(False)` immediately, lazily — `store.py:53-66,363` | closed |
| T-03-10 | Tampering | hostile JSON in clusters/chunks columns | medium | mitigate | defensive coerce to `list[str]` mirroring the exemplar read guard; render-time sanitisation downstream — `pipeline/cluster.py` | closed |
| T-03-11 | Denial of Service | oversized vec blob from a tampered db | low | accept | dim recorded + validated; vec0 enforces `FLOAT[dim]` width; BLOB/numpy escape hatch documented | closed |
| T-03-12 | Information Disclosure | doctor pointed at a public endpoint | high | mitigate | doctor constructs the client → `_assert_local`; refusal unless `--i-know-what-im-doing`; tested — `client.py:174` | closed |
| T-03-13 | Integrity | silent embedding failure (OGA/ONNX recipe) misleads triage | high | mitigate | real `/v1/embeddings` round-trip with named failure message `_OGA_ONNX_MSG`; never inferred from `/v1/models` — `cli.py:686-804` | closed |
| T-03-14 | Spoofing | hostile server text with control bytes to terminal (doctor) | medium | mitigate | `_sanitise` every server string before printing (whole-line) — `cli.py` | closed |
| T-03-15 | Integrity | determinism-breaking multi-slot config unnoticed | low | mitigate | `/props` check emits WARNING on `n_parallel>1` / missing seed (non-fatal) — `cli.py:839-857` | closed |
| T-03-16 | Tampering | prompt-injection from log content into the label call | medium | mitigate | exemplars only (no echoed commands); labels freeform + length-capped + sanitised; no tool-calling / schema execution — `pipeline/cluster.py:205` | closed |
| T-03-17 | Spoofing | adversarial label text with control bytes rendered to user | medium | mitigate | labels capped by code points; downstream `_sanitise` strips control/bidi bytes (WR-01 precedent) | closed |
| T-03-18 | Denial of Service | oversized label / prompt blows the context budget | medium | mitigate | `PromptBudget` breadth-first truncation; per-label code-point cap; one batched call — `llm/budget.py` | closed |
| T-03-19 | Integrity | label-parse failure corrupts cluster state | low | mitigate | lenient `_parse_labels`; on failure labels stay NULL, clusters degrade to signature, never crash — `pipeline/cluster.py:217-271` | closed |
| T-03-20 | Spoofing | adversarial cluster label with control/bidi bytes rendered by `show clusters` | medium | mitigate | whole-line `_sanitise` on the rendered line (WR-01 precedent); label length-capped upstream — `cli.py:520` | closed |
| T-03-21 | Information Disclosure | analyze pointed at a public endpoint | high | mitigate | client construction runs `_assert_local`; refusal unless `--i-know-what-im-doing`; tested — `client.py:174` | closed |
| T-03-22 | Integrity | interrupted embed leaves partial vectors/clusters | medium | mitigate | all persistence inside one `store.transaction()`; test asserts unchanged state after a mid-embed raise — `pipeline/cluster.py:333` | closed |
| T-03-23 | Denial of Service | untrusted filename/label in a rich renderable | low | mitigate | static progress description only; DB/server text flows through `_sanitise`'d plain prints (T-02-06) | closed |
| T-03-SC | Tampering | pip supply chain (4 new deps) | high | mitigate | RESEARCH Package Legitimacy Audit approved httpx, sqlite-vec, scikit-learn, numpy, respx; sqlite-vec pre-accepted with store.py-confinement + BLOB/numpy escape hatch; no new `[ASSUMED]`/`[SLOP]` packages | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-03 | `SIFT_*` env can set a base_url string, but the SSRF guard (`_assert_local`) refuses non-local endpoints at client construction regardless of source. Config layer only stores the string; no network use bypasses the guard. Low severity, below the high block threshold. | O Hingst | 2026-07-17 |
| AR-03-02 | T-03-11 | An oversized vector blob from a tampered case.db is bounded: dimension is recorded in `meta` and validated on reload (STORE-03), and vec0 enforces `FLOAT[dim]` column width. Documented BLOB/numpy escape hatch remains if sqlite-vec is dropped. Low severity, below the high block threshold. | O Hingst | 2026-07-17 |

*Accepted risks do not resurface in future audit runs.*

---

## Residual Notes (non-blocking)

Advisory code review (03-REVIEW.md) closed WR-01/02/03 via gap-closure. Two
Warning-severity hardening items remain tracked as backlog — both below the `high`
block threshold, neither reopening a register threat:

- **WR-04** — cluster-label column tab misalignment in `show clusters` (cosmetic).
- **WR-05** — a narrow SQLITE_FULL path can escape the T-03-01 `DiskFullError`
  handler as a raw traceback. The all-or-nothing atomicity guarantee still holds
  (zero committed events); only the error presentation degrades. Tracked for a
  future hardening pass.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-17 | 23 | 23 | 0 | gsd-secure-phase (L1, orchestrator grep-depth) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-17
