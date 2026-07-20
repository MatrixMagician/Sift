# Golden case: `perfmon-denial`

An MCM (Memory Contract Manager) denial episode paired with an **overlapping**
DSSPerformanceMonitor CSV, so the deterministic perfmon correlator
(`sift.pipeline.perfmon.analyse_perfmon`) resolves counter trends inside the
denial window. This is the 8th golden case (PERF-08); it exercises the
deterministic perfmon fact injection built in Phase 14 end-to-end through the
eval harness.

## Origin

The `input/` pair was authored in Plan 14-01, within D-07's reuse-synthetic /
real-slice discretion (the raw Hartford CSV+log pair does **not** overlap in
time, so a verbatim copy would yield a vacuous, zero-citation case):

- `input/perfmon_denial.log` — the shipped, validated
  `tests/fixtures/mcm/hartford_deny_slice.log` denial slice with three prepended
  real-format `Contract Request Succeeded` lead-up lines carrying descending
  `AvailableMCM` (200 GB → 90 GB → 30 GB). Those lead-up lines move the resolved
  denial-window start back to `12:39:35.000`, widening the window to ~12.2 s so
  the CSV samples fall inside it. It auto-sniffs as `dsserrors` (Contract Request
  Failed / Info Dump / `[*.cpp:NNNN]` markers), so `sift eval` ingests it with no
  `--adapter` override.
- `input/perfmon_overlap.csv` — a 6-sample PDH-CSV over the five D-04 salient
  counters (`Working set cache RAM usage(MB)`, `System\RAM used(MB)`,
  `Process(MSTRSvr)\Size(MB)`, `Open Sessions`, `Total MCM Denial`). Every sample
  stamp falls strictly inside the resolved window, and values rise toward the
  denial (working set 180000 → 266042 MB). Naive PDH wall-clock is stamped UTC
  verbatim (ADR 0012), so the CSV and denial clocks are directly comparable.

The non-overlapping raw Hartford snapshot pair stays a documented future second
candidate; it is not built this phase.

## The incident

At `2026-04-07 12:39:47.230` the server logs `IServer enters MCM denial state`
with `AvailableMCM = 0`. The perfmon correlator resolves an **episode-scope**
trend group whose counters climb into that denial window; each salient counter
carries a citable `at_denial_event_id` naming the real `dssperfmon` sample at the
denial boundary. The root cause is working-set-driven memory exhaustion; the
repeated `Contract Request Failed` errors are the loud symptom, and the rising
counter trend is the corroborating evidence.

## What the gate checks — and the perfmon-sensitivity guard

`truth.yaml` is **frozen** (authored before any prompt tuning): a regression must
turn `sift eval` red, never be edited away.

The four eval metrics score differently here, and the perfmon-sensitive one is
deliberately chosen:

- `required_evidence` (retrieval_hit_rate) is matched by `run_case` against the
  **cluster exemplars** — the raw log text fed to the model. Those regexes
  (`Contract Request Failed`, `MCM denial state`, `memory is running low`) match
  whether or not perfmon correlation injection runs, so retrieval is **not** the
  perfmon-sensitive metric (Assumption A2: required_evidence/retrieval is matched
  against raw exemplars and is insensitive to injection by construction).
- **`citation_validity_rate` is the perfmon-sensitive metric.** A hypothesis may
  cite a perfmon counter `event_id` only because `render_perfmon_facts` unions
  that id into `prompted_ids` (the citation-gate's allowed set). Those ids name
  `dssperfmon` samples that are disjoint from the MCM denial boundary ids, so the
  perfmon citation is valid via the perfmon injection **alone**. Remove that
  injection and the same citation is FLAGGED — `citation_validity_rate` drops
  below its `1.0` floor and the case regresses.

This sensitivity is proved by
`test_perfmon_denial_citation_validity_is_perfmon_sensitive` in
`tests/test_eval_cases.py`: it runs the case once with injection (valid perfmon
citation, rate `1.0`) and once with `render_perfmon_facts` stripped (flagged
citation, rate `< 1.0`) — removing the perfmon injection turns this case red.
Because the cited id is a `dssperfmon` sample not shared with the MCM block,
stripping the perfmon renderer alone is sufficient to demonstrate the gate (unlike
the `mcm-denial` case, whose denial id is citable via either fact block).

Offline test runs bind an `httpx.MockTransport` (EVAL-05, zero network); a live
`sift eval` against a local inference endpoint is the operator's CI gate
(EVAL-03).
