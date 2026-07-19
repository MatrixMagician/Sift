---
phase: 3
slug: inference-client-doctor-embeddings-clustering
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: true
created: 2026-07-17
validated: 2026-07-17
---

# Phase 3 — Validation Strategy

> Per-phase validation contract. Reconstructed retroactively from phase artifacts
> (03-01..06 SUMMARY.md, COVERAGE.md, 03-VERIFICATION.md) — all seven phase test
> files already existed and pass; no gaps required new test generation.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.x (via `uv run`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `addopts = -m 'not perf and not live'`) |
| **Quick run command** | `uv run pytest tests/test_llm_client.py tests/test_budget.py tests/test_store_vectors.py tests/test_cluster.py tests/test_doctor.py tests/test_analyze.py tests/test_disk_full.py -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~0.7 s (phase files) · ~0.6 s (full suite, 267 tests) |

---

## Sampling Rate

- **After every task commit:** Run the quick command (7 phase test files, ~0.7 s)
- **After every plan wave:** Run `uv run pytest` (full suite)
- **Before `/gsd-verify-work`:** Full suite green + `ruff check` + `pyright` clean
- **Max feedback latency:** ~1 second

---

## Per-Task Verification Map

| Requirement | Plan | Test Type | Automated Command | Status |
|-------------|------|-----------|-------------------|--------|
| LLM-01 — single httpx client, per-role base_urls, backoff, batched embeddings, no vendor SDK | 01, 02 | unit | `uv run pytest tests/test_llm_client.py -q` | ✅ green |
| LLM-02 — `_assert_local` SSRF guard + `--i-know-what-im-doing` override | 02, 04 | unit | `uv run pytest tests/test_llm_client.py -k assert_local -q` | ✅ green |
| LLM-03 — `doctor` real embedding round-trip, model IDs, dim check, determinism warn | 04 | unit (fake) + **live (manual)** | `uv run pytest tests/test_doctor.py -q` · live: `uv run pytest -m live` | ✅ green (fakes) · ⬜ manual-only (live) |
| LLM-04 — `/props` / `/tokenize` feature-detected, degrade gracefully | 02 | unit | `uv run pytest tests/test_llm_client.py tests/test_budget.py -q` | ✅ green |
| STORE-03 — embedding identity + dim in `meta`; reload mismatch = hard error | 03 | unit | `uv run pytest tests/test_store_vectors.py -q` | ✅ green |
| CLUS-02 — HDBSCAN L2 `min_cluster_size=2` merges synonyms; noise→singleton; agglomerative fallback | 01, 05 | unit | `uv run pytest tests/test_cluster.py -q` | ✅ green |
| CLUS-03 — eager LLM label from exemplars, versioned prompt, code-point cap, signature fallback | 05, 06 | unit | `uv run pytest tests/test_cluster.py tests/test_analyze.py -q` | ✅ green |
| RAG-05 — `PromptBudget` tokenize-or-//4, breadth-first truncation | 02 | unit | `uv run pytest tests/test_budget.py -q` | ✅ green |
| CLI-02 — label prompt is a template file (`prompts/cluster_label.md`); hash in `meta` | 05 | unit | `uv run pytest tests/test_cluster.py -k prompt -q` | ✅ green |
| EVAL-05 — injectable client + fake server; autouse socket-block; zero network in tests | 02–06 | infra | `uv run pytest` (autouse `conftest._no_network`) | ✅ green |
| WR-07 — `SQLITE_FULL`/`IOERR` mid-ingest → `DiskFullError`, exit non-zero, zero committed events | 03 | unit | `uv run pytest tests/test_disk_full.py -q` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.* All seven phase test
files (`test_llm_client`, `test_budget`, `test_store_vectors`, `test_cluster`,
`test_doctor`, `test_analyze`, `test_disk_full`) plus the autouse
`conftest._no_network` socket-block fixture were delivered inside the phase.
pytest and the `live`/`perf` markers are registered in `pyproject.toml`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live inference-server round-trip: real `/v1/embeddings` dims, real model recipes (Lemonade OGA/ONNX named failure), live `/props` determinism, LLM label quality | LLM-03 / SC1 | The entire default suite runs socket-blocked against a fake OpenAI-compatible server (EVAL-05). Real-server dims/recipes/props/label quality cannot be exercised in-process. | Start a real `llama-server` (generation + `--embeddings`) or Lemonade on `:13305`; run `uv run sift doctor <case>`, then `uv run pytest -m live`, then `uv run sift analyze <case>` and `uv run sift show clusters`. **Signed off 2026-07-17** on Fedora Strix Halo vs Lemonade v10.4.0 (dim 1024, vec_version v0.1.9) — see 03-UAT.md / 03-VERIFICATION.md resolution. |

---

## Validation Sign-Off

- [x] All requirements have `<automated>` verify (default suite) or an explicit manual-only entry
- [x] Sampling continuity: no 3 consecutive requirements without automated verify
- [x] Wave 0 covers all MISSING references (none — infrastructure pre-existed)
- [x] No watch-mode flags
- [x] Feedback latency < ~1 s
- [ ] `nyquist_compliant: true` — **not set**: LLM-03 live-server round-trip is inherently manual-only (satisfied via signed-off UAT + `-m live`), so the phase is PARTIAL by design, not by gap.

**Approval:** approved 2026-07-17 (PARTIAL — 10/10 requirements automated in default suite; 1 manual-only live-server confirmation, signed off)

---

## Validation Audit 2026-07-17

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated (manual-only) | 1 (LLM-03 live-server round-trip — pre-existing, signed off) |

Existing VALIDATION.md was the unfilled draft template; reconstructed from phase
artifacts. All 10 requirements COVERED by passing automated tests (88 phase-file
tests green, 267 full-suite green, 2 deselected = perf + live). No test
generation required; nyquist auditor not spawned (no MISSING gaps).
