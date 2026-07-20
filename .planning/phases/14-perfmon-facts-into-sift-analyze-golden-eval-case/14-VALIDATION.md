---
phase: 14
slug: perfmon-facts-into-sift-analyze-golden-eval-case
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-20
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_perfmon_facts.py tests/test_perfmon_analyze.py -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~1 second (perfmon subset); full suite ~60 s |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_perfmon_facts.py tests/test_perfmon_analyze.py -q`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green (plus `ruff check` and `pyright` clean)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01 | 01 | 0 | PERF-08 | — | Overlapping fixture is non-vacuous: ≥1 episode-scope counter carries a citable `at_denial_event_id` resolving to a `dssperfmon` store event (`cited ⊆ store`) | unit | `uv run pytest tests/test_perfmon_analyze.py -k test_fixture_overlaps -q` | ✅ | ✅ green |
| 14-02 | 02 | 1 | PERF-07 | — | Untimestamped perfmon sample on episodes-present branch disclosed (not silently dropped); disclosure byte-identical across runs; Hartford reference unaffected | unit | `uv run pytest tests/test_perfmon.py -k "unattributed" -q` | ✅ | ✅ green |
| 14-03 | 03 | 1 | PERF-07 | T-14-05 (injection), T-14-06 (figure authoring) | Renderer citable set == printed `[evt:]` tokens; fragment zero authored digits; log-derived values sanitised; group cap severity-sorted | unit | `uv run pytest tests/test_perfmon_facts.py -q` | ✅ | ✅ green |
| 14-04 | 04 | 2 | PERF-07 | T-14-07 (fabricated figure/citation), T-14-08 (baseline drift) | Four-combination byte-identity (NEITHER/MCM-ONLY frozen to pre-phase hashes); `cited ⊆ prompted ⊆ store`; fabricated perfmon id FLAGGED; model cannot alter a figure (block built pre-generation) | unit | `uv run pytest tests/test_perfmon_analyze.py -q` | ✅ | ✅ green |
| 14-05 | 05 | 2 | PERF-08 | T-14-10 (vacuous gate) | `perfmon-denial` discovered & positively scored as 8th golden case; citation-sensitivity gate non-vacuous (stripping `render_perfmon_facts` drops `citation_validity_rate` below 1.0) | unit | `uv run pytest tests/test_eval_cases.py -k perfmon_denial -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] Overlapping perfmon golden fixture (CSV+log with in-span samples) — `eval/cases/perfmon-denial/input/{perfmon_overlap.csv, perfmon_denial.log}` (6 in-span samples over the five salient counters; ~12.2 s resolved window)
- [x] Self-verifying overlap guard — `tests/test_perfmon_analyze.py::test_fixture_overlaps` asserts ≥1 citable `at_denial_event_id` resolving to a `dssperfmon` store event; RED counterfactual proven against the non-overlapping Hartford pair
- [x] Shared ingest helper — `tests/test_perfmon_analyze.py::_ingest_perfmon_case` (the `write_overlapping_csv` builder in `_perfmon_fixtures.py` was correctly skipped as YAGNI — the CSV is a static verbatim artifact)

Wave 0 dependency satisfied — the PERF-08 gate is non-vacuous, not hollow.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | — |

*All phase behaviours have automated verification (byte-identity golden hashes, anti-hallucination `cited ⊆ prompted ⊆ store`, no-authored-digit guard, citable-subset, non-vacuous eval regression gate). The authoritative eval gate is the offline MockTransport harness (EVAL-05, green). Live `sift eval` (EVAL-03) against a real endpoint is an operator condition, not a phase behaviour: it exits non-zero in the current sandbox because the loaded Lemonade ONNX/OGA model lacks `/v1/embeddings` — a pre-existing environmental caveat affecting all 8 cases identically (logged in `deferred-items.md`), not a validation gap.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated — 5/5 tasks COVERED by passing automated tests (0 gaps)

---

## Validation Audit 2026-07-20

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed the Per-Task Verification Map from the five plan SUMMARY files (the seeded stub carried only the `{N}-01-01` template placeholder). Independently re-ran the targeted subset — `tests/test_perfmon_facts.py tests/test_perfmon_analyze.py tests/test_perfmon.py tests/test_eval_cases.py tests/test_hypothesise.py` → **67 passed, 0 failed** — confirming every requirement (PERF-07, PERF-08) maps to a passing automated test. No auditor spawn or gap-fill required; phase is Nyquist-compliant.
