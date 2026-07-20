---
phase: 12-dssperfmon-adapter-pipeline-exclusion
verified: 2026-07-20T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: null
advisories:
  - item: "REQUIREMENTS.md PERF-02 text is stale relative to the ROADMAP criterion-2 amendment"
    detail: >-
      PERF-02 reads 'UTC-normalised sample timestamps derived from the PDH header's declared zone
      and offset'. ADR 0012 (and the dated 2026-07-20 amendment to ROADMAP criterion 2) deliberately
      RECORD the declared zone/offset as evidence and do NOT derive a shift from them. The shipped
      code matches the amended ROADMAP contract and ADR 0012; only the REQUIREMENTS.md sentence
      lags. Recommend a one-line reword of PERF-02 to match. Not a code gap.
---

# Phase 12: `dssperfmon` Adapter & Pipeline Exclusion — Verification Report

**Phase Goal:** An engineer can ingest a DSSPerformanceMonitor PDH-CSV into a case and get every
sample row back as a deterministic, individually citable, UTC-normalised event — without those
samples perturbing any existing clustering output.

**Verified:** 2026-07-20
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | One event per sample row, deterministic `event_id`, idempotent re-ingest | ✓ VERIFIED | Independent run of `DssperfmonAdapter.parse` on the fixture: 20 events for 20 data rows, all `event_id`s unique, second parse yields a byte-identical id list. `test_ingest_perfmon_full_coverage` + `test_ingest_perfmon_idempotent` pass at CLI level. |
| 2 | `(PDH-CSV 4.0)` sniffed without override; ts through `base.to_utc` with `ts_confidence`; declared zone recorded in `attrs`, **not** applied as a shift | ✓ VERIFIED | `sniff()` returns 0.95 via anchored `PDH_SNIFF_PREFIX`; independent run shows `ts_confidence='inferred'`, `attrs['tz_name']='Eastern Standard Time'`, `attrs['tz_offset_min']='300'`, and ts stamped verbatim (no +5 h). `test_csv_aligns_with_paired_log` is the executable guard: CSV final sample precedes the MCM denial by <10 s, matched on marker text not index. |
| 3 | Blank/malformed/non-numeric values become `severity="unknown"`; parse coverage reflects them | ✓ VERIFIED | Six fallback tests pass (blank cell, non-numeric, bad ts, column drift, embedded newline, no-bias header). `_fallback_event` is a single funnel; no branch returns/raises past emission. `stats.unknown_fallback_bytes` drives `coverage < 1.0` (`test_parse_coverage`). |
| 4 | Cluster output byte-identical with and without the perfmon CSV | ✓ VERIFIED | `test_cluster_output_identical_with_and_without_perfmon` passes, with a real non-vacuity guard: asserts `n_b - n_a == _PERFMON_ROWS`, so the equality cannot pass because the CSV failed to ingest. Reinforced by `test_template_groups_exclude_perfmon` and `test_exemplars_exclude_perfmon` (which itself asserts `exemplars` non-empty first). |
| 5 | Every perfmon sample remains individually retrievable by `event_id` | ✓ VERIFIED | `test_get_events_returns_perfmon`, `test_iter_event_rows_unfiltered`, `test_show_events_includes_perfmon` all pass. Consumer trace below confirms the citation path is genuinely unfiltered. |

**Score:** 5/5 truths verified (0 present, behaviour-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/sift/adapters/dssperfmon.py` | New adapter, 294 lines | ✓ VERIFIED | Subclasses `ConfigurableAdapter`; stdlib `csv` on one row at a time; `byte_lines` owns the read loop; no `re` import (ReDoS discharged by construction). |
| `src/sift/adapters/__init__.py` | One import + one REGISTRY entry | ✓ VERIFIED | `+2` lines, appended last (insertion order preserved). |
| `src/sift/store.py` | `EXCLUDED_FROM_RANKING` + `?`-bound exclusion + asymmetry comment | ✓ VERIFIED | Module constant at line 335; `sorted()` fixes parameter order; only the placeholder count interpolated. |
| `src/sift/adapters/dsserrors.py` | (out of plan — see §Scope) | ✓ VERIFIED | `_SNIFF_STRINGS` bare `"MCM"` replaced with `"AvailableMCM"` / `"MCM Settings"`. ADR 0013 records it. |
| `tests/fixtures/dssperfmon/hartford_deny_slice.csv` | Verbatim PDH header + real rows | ✓ VERIFIED | 5,173 bytes, 1,926-byte header + 20 sample rows. |

### Key Link Verification — the PERF-03 asymmetry

Traced every event-read consumer in `src/sift/`:

| Consumer | Method | Filtered? | Correct? |
|----------|--------|-----------|----------|
| `pipeline/dedup.py:102` | `iter_event_summaries` | Yes | ✓ ranking |
| `pipeline/cluster.py:113` | `iter_event_summaries` | Yes | ✓ ranking |
| `pipeline/hypothesise.py:191` | `iter_event_summaries` | Yes | ✓ ranking |
| `eval/runner.py:63` | `iter_event_summaries` | Yes | ✓ ranking |
| `cli.py:614` (`show events`) | `iter_event_rows` | **No** | ✓ citation |
| `render/markdown.py:197` (evidence appendix) | `get_events_by_ids` | **No** | ✓ citation |
| `pipeline/hypothesise.py:370`, `cli.py:1037` | `query_events` → `analyse_mcm` | No | ✓ immune — `mcm.py:815/891` filters `source == "dsserrors"` internally |

The asymmetry is exactly as designed: **all four ranking stages filtered from one seam; both citation
paths unfiltered.** `salience.rank_clusters` consumes Cluster/TemplateGroup rows only and inherits
the exclusion transitively — no edit there, as required. No file under `src/sift/pipeline/` and not
`src/sift/eval/runner.py` appears in `git diff --name-only`, satisfying the "never re-implemented
per stage" prohibition.

### Behavioural Spot-Checks

| Behaviour | Command | Result | Status |
|-----------|---------|--------|--------|
| Phase-12 test set | `uv run pytest tests/test_dssperfmon.py <9 named PERF tests>` | 26 passed in 0.59s | ✓ PASS |
| Span partition, independently recomputed | in-process `parse()` | header 1,926 + spans 3,247 = 5,173 = file size = `stats.total_bytes` | ✓ PASS |
| Determinism / idempotence | re-parse same file | id list identical, all unique | ✓ PASS |
| No shift applied | inspect first event | ts `2026-04-02 19:21:38.236+00:00`, tz recorded not applied | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| PERF-01 | 12-01, 12-03 | ✓ SATISFIED | Adapter + registry + sniff + deterministic id + idempotent re-ingest, all tested. |
| PERF-02 | 12-01, 12-02 | ✓ SATISFIED (against amended contract) | `ts_confidence` recorded, unknown-fallback + coverage verified. See advisory on the stale "derived from" wording. |
| PERF-03 | 12-04 | ✓ SATISFIED | Single-seam exclusion; byte-identity gate with non-vacuity guard; citation paths proven unfiltered. |

No orphaned requirements: REQUIREMENTS.md maps exactly PERF-01/02/03 to Phase 12, and all three are
claimed by plan frontmatter.

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX` in any file modified by this phase. No stubs, no empty returns, no
hardcoded-empty props.

---

## Adjudication of the Five Flagged Deviations

**1. 12-01 span partition (`start` parameter) — ACCEPTED, invariant genuinely intact.**
The plan's two must_haves were mutually unsatisfiable and the executor resolved the contradiction in
the right direction. I recomputed the accounting independently rather than trusting the helper:
`header_bytes = 1926` is *exactly* the first line's length, and `1926 + sum(byte_len) = 5173 =
file size = stats.total_bytes`. So there are no gaps, no overlaps, and total accounting reaches
`total_bytes`. The alternative the plan implied — folding header bytes into the first Event's
`byte_offset` — would have been strictly *worse*: it would make `event_id` a function of a
byte position the Event does not occupy, and it would corrupt the `attrs["byte_offset"]` provenance
the evidence appendix renders. The `start` parameter is a faithful encoding of D-01, not a
weakened assertion.

**2. 12-02 column drift retains its timestamp — ACCEPTED, correct reading of D-16.**
D-16 (12-CONTEXT.md:131) specifies only `severity="unknown"`, `raw` preserved, and a
`ParseStats.notes` entry — it says nothing about `ts`. `ts=None`/`ts_confidence="missing"` is
D-15's rule, and D-15 is scoped explicitly to "a row whose **timestamp** is unparseable". A drifted
row whose stamp parsed cleanly is not that case. Discarding a good timestamp would actively harm
PERF-02's "nothing disappears silently" intent and would strand the surviving evidence off Phase 13's
timeline. The code comment at `dssperfmon.py:209-213` states this reasoning explicitly, and
`test_column_drift_unknown` pins it. Correct as shipped.

**3. 12-03 scope widening into `dsserrors.py` — ACCEPTED, ADR 0013 is adequate.**
The collision is real and structural, not a fixture quirk: the bare `"MCM"` marker matched the
`Total MCM Denial` PDH counter path, which DSSPerformanceMonitor emits by default, so *every* real
perfmon CSV double-claimed. ADR 0013 is unusually good evidence: it names the failure, quotes the
colliding byte offset, tabulates the scores, and — critically — measures the fix against the full
real corpus (all 11 real DSSErrors logs still sniff 0.80 and still route correctly; one of them
contains no `"MCM"` substring at all, proving the marker was never load-bearing). It also records
the rejected alternatives, including the tempting one: relaxing the test to unique-maximum.

That last point is the one that matters for this verification, and it resolves in the phase's favour.
**The sole-claimancy must_have holds because the signature was fixed, not because the assertion was
weakened** — `test_phase5_no_cross_collision` is unchanged and still asserts
`claimants == ['dssperfmon']`. The scope note in ADR 0013 confirms the widening was escalated as a
blocking decision and approved before implementation rather than auto-applied.

**4. 12-04 test-helper deviation (`source` on `_ev` not `_seed`) — ACCEPTED, the executor is right.**
Verified the mechanics: `_seed` builds `_ev(i, m)` for `i` in `range(len(messages))`, and
`event_id = sha256("case.log", offset)`. A second `_seed` call for perfmon events would therefore
reuse offsets `0..4` and collide with the existing corpus's event_ids — the parameter the plan asked
for could not have had a working caller. Putting the default on `_ev` and inserting at offsets
`1000+` (test_cluster.py:155-156) is the only correct shape. Sound deviation.

**5. PERF-03's load-bearing asymmetry — VERIFIED, correct in both directions.**
This is the anti-hallucination invariant, so I traced it rather than grepping the docstrings. Both
halves hold (full table above): all four ranking consumers route through the filtered
`iter_event_summaries`, and both citation paths (`iter_event_rows` for `show events`,
`get_events_by_ids` for the evidence appendix) are genuinely unfiltered. I also checked the one
consumer that *looked* like a leak — `analyse_mcm(store.query_events(), ...)` receives every event
unfiltered — and confirmed it is immune because `mcm.py:815` and `mcm.py:891` both narrow to
`source == "dsserrors"` before doing anything. Perfmon events are excluded from ranking and remain
citable. No correctness bug.

---

## Advisory (no code change required)

**REQUIREMENTS.md PERF-02 wording is stale.** Its literal text — "UTC-normalised sample timestamps
*derived from* the PDH header's declared zone and offset" — describes the behaviour ADR 0012
explicitly rejected after measurement showed it puts the CSV five hours after the denial it precedes
by six seconds. ROADMAP criterion 2 carries a dated 2026-07-20 amendment stating the declared
zone is "**recorded in `attrs` as evidence, not applied as a shift**", and the code matches that
amended contract exactly. The requirement sentence simply was not re-worded when the criterion was.
Recommend a one-line edit to PERF-02 so the requirement and the criterion agree; nothing in the
implementation should change.

## Gaps Summary

None. Every ROADMAP success criterion is met in code with a passing, non-vacuous test behind it.
All five flagged deviations resolve in the phase's favour on their merits — three of them (the span
`start` parameter, the retained drift timestamp, the `_ev` default) are cases where the plan text was
wrong and the executor was right, and each is documented in-code at the point of divergence. The
one out-of-plan edit was escalated, approved, and recorded in an ADR that measures the fix against
the real corpus rather than asserting it.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
