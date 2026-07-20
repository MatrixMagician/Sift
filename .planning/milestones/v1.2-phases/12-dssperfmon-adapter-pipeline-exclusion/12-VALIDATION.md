---
phase: 12
slug: dssperfmon-adapter-pipeline-exclusion
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-20
audited: 2026-07-20
gaps_filled: 1
warnings: 3
---

# Phase 12 — Validation Record

Adversarial audit of PERF-01/02/03 automated coverage. Starting hypothesis: each requirement is
uncovered until a non-vacuous passing test proves otherwise.

## Gate at audit time

`uv run ruff check` clean · `uv run pyright` 0 errors · `uv run pytest` **567 passed, 8 deselected**
(was 566 — this audit adds one test).

The 8 deselected were enumerated rather than assumed: `test_100mb_ingest_under_60s`,
`test_live_marked_tests_bypass_socket_guard`, `test_doctor_against_live_server`,
`test_judge_live_round_trip`, `test_offline_wheel_install_yields_working_console_script`,
`test_deploy_base_urls_are_guard_clean`, `test_quadlet_generator_dry_run_validates_or_skips`,
`test_render_pdf_live_writes_real_pdf_without_external_fetch`. All carry pre-existing
`live`/`perf`/`packaging` marks; none is a phase-12 behaviour.

---

## Per-requirement verdict

| Req | Verdict | Basis |
|-----|---------|-------|
| PERF-01 | ✅ COVERED | Sniff, one-event-per-row, deterministic id, idempotent re-ingest, span partition — unit + CLI. |
| PERF-02 | ✅ COVERED | All four declared degradation modes exercised; coverage arithmetic pinned. |
| PERF-03 | ✅ COVERED (1 gap filled, 1 caveat) | Exclusion seam + citation paths proven in both directions; see W-1. |

### PERF-02 — the four degradation modes (assessed individually)

The concern was that fixture-only coverage would cover *some* modes. It covers all four, plus two:

| Mode | Test | Non-trivial? |
|------|------|--------------|
| Bad cell (blank) | `test_blank_cell_unknown_fallback` | Yes — asserts `unparsed_columns`, `raw` preserved, **and that ts survives** |
| Bad cell (non-numeric) | `test_non_numeric_cell_unknown_fallback` | Yes — asserts `attrs` keeps the raw `"N/A"`, so `float()` is a probe not a coercion |
| Bad timestamp | `test_bad_timestamp_survives` | Yes — `ts=None`, `ts_confidence="missing"`, event still emitted, good columns still populated |
| Column drift | `test_column_drift_unknown` | Yes — pins the *contested* reading (drift keeps a good ts) plus a `stats.notes` entry |
| Embedded newline | `test_embedded_newline_two_unknown_events` | Yes — pins non-reassembly as deliberate |
| No declared bias | `test_header_without_bias_still_parses` | Yes — asserts attrs are **absent**, not invented |

Every synthetic case additionally runs `assert_span_partition` via `run_syn`, so a degraded row that
lost or duplicated bytes fails even if its own assertions pass. That is a structural anti-vacuity
property, not a hand check. `test_parse_coverage` pins `unknown_fallback_bytes == len(bad)` exactly,
not merely `coverage < 1.0`.

**Verdict: not nominal.** Synthetic-only is a necessity (D-17), not a shortcut, and the fixtures are
authored inline where the defect is visible in the test body.

### PERF-03 — byte-identity and citation

`test_cluster_output_identical_with_and_without_perfmon` is genuine, not weak: it compares derived
`show clusters` output (correctly *not* the two `case.db` files, which legitimately differ) and
carries a real non-vacuity guard — `n_b - n_a == _PERFMON_ROWS` — so the equality cannot pass
because the CSV failed to ingest. Reinforced at store level by `test_template_groups_exclude_perfmon`
and at exemplar level by `test_exemplars_exclude_perfmon`.

**Citation retrievability was the one disproportionate gap** and has been filled — see below.

---

## Gap filled

**G-1 — citation proven only for one hand-seeded event.** Before this audit the citation half of
PERF-03 rested on `test_get_events_returns_perfmon` / `test_iter_event_rows_unfiltered` (both against
a single synthetic `_seed_mixed_sources` event) and `test_show_events_includes_perfmon`, which
asserts only that the CSV *filename* appears in `show events` output. None asserted that **every**
ingested sample resolves by `event_id` — which is the literal wording of PERF-03 and the
anti-hallucination invariant.

Added `tests/test_cli.py::test_every_perfmon_sample_citable_and_none_ranked`: after a real CLI
ingest, asserts all 20 perfmon `event_id`s resolve through `get_events_by_ids` (the path the evidence
appendix uses), that none appear in `iter_event_summaries`, and — non-vacuity — that the ranking seam
yielded something at all.

Counterfactual proof performed, not assumed: with `EXCLUDED_FROM_RANKING` emptied the test **fails**;
`src/sift/store.py` was restored byte-identically (`git diff` clean) and the full gate re-run.

Command: `uv run pytest tests/test_cli.py::test_every_perfmon_sample_citable_and_none_ranked -x`

---

## Warnings

**W-1 — byte-identity is asserted on the pre-`analyze` path.** `_ingest_case` deliberately skips
`analyze`, so `show clusters` falls back to template groups; no test compares post-`analyze` cluster
output ± CSV. The exclusion is a single `store.py` seam that all four ranking stages route through,
and `test_exemplars_exclude_perfmon` covers the embed path with a fake embedder, so the residual risk
is low — but the strongest possible form of criterion 4 is not what is asserted.

**W-2 — executor counterfactuals are one-shot, not structural.** The break-and-restore proofs for
12-02/12-03/12-04 were hand-performed once and leave nothing behind that would stop a future edit
making those tests vacuous. G-1's test is likewise proven by a one-shot counterfactual (recorded
above so it is at least reproducible). The exceptions are the tests carrying in-test non-vacuity
guards — the `n_b - n_a == _PERFMON_ROWS` delta, the `assert_span_partition` call in every synthetic
case, and the `assert ranked` line in G-1 — which are structural and survive refactoring.

**W-3 — REQUIREMENTS.md PERF-02 wording is stale** (carried from 12-VERIFICATION.md advisory).
"derived from the PDH header's declared zone and offset" describes the behaviour ADR 0012 rejected;
the code records rather than applies. `test_header_zone_recorded_not_applied` pins the shipped,
correct behaviour. Documentation defect only.

## Manual-only, no automated test

| Behaviour | Req | Why |
|-----------|-----|-----|
| Full-scale ingest of the real 13,596-sample CSV (100% coverage, second ingest adds zero) | PERF-01 | Artefact lives outside the repo and is too large to vendor. The 20-row slice is byte-verbatim, so format fidelity *is* automated; only scale is not. |

---

## Sign-off

- [x] Every criterion has an automated command
- [x] All four declared PERF-02 degradation modes exercised, plus two more
- [x] Criterion 4 byte-identity test present, green, non-vacuous (W-1 caveat)
- [x] Citation retrievability proven over the whole ingested population (G-1)
- [x] Gate clean after the added test
- [x] `nyquist_compliant: true`

**Approval:** validated with 3 warnings.
