# Golden case: `mcm-denial`

An MCM (Memory Contract Manager) denial episode from a real MicroStrategy
Intelligence Server (CastorServer), redacted. This is the 7th golden case
(MCM-07); it exercises the deterministic MCM fact injection built in Phase 11
end-to-end through the eval harness.

## Origin

`input/hartford_deny_slice.log` is the committed, validated denial slice
`tests/fixtures/mcm/hartford_deny_slice.log` copied verbatim (D-18 — reuse the
already-shippable, real-episode slice; no synthetic authoring). It auto-sniffs as
`dsserrors` (Contract Request Failed / Info Dump / `[*.cpp:NNNN]` markers), so
`sift eval` ingests it with no `--adapter` override.

## The incident

At `2026-04-07 12:39:47.230` the server logs `IServer enters MCM denial state`.
The deterministic analyser (`sift.pipeline.mcm.analyse_mcm`) reads the following
figures verbatim from the denial-time breakdown (all machine-independent):

- **AvailableMCM = 0** — the memory contract manager had no headroom to grant.
- **Working set = 65.4% of IServer virtual memory** — the dominant consumer
  (graded `critical`).
- Other processes = 18.5% of physical, system free headroom = 9.8% (`warn`).
- Denial window: `AvailableMCM < 25% of HWM (437.6 GB)`.

The root cause is working-set-driven memory exhaustion; the repeated
`Contract Request Failed` errors are the loud symptom.

## What the gate checks — and the MCM-sensitivity guard

`truth.yaml` is **frozen** (authored before any prompt tuning): a regression must
turn `sift eval` red, never be edited away.

The four eval metrics score differently here, and the MCM-sensitive one is
deliberately chosen:

- `required_evidence` (retrieval_hit_rate) is matched by `run_case` against the
  **cluster exemplars** — the raw log text fed to the model. Those regexes
  (`Contract Request Failed`, `MCM denial state`, `memory is running low`) match
  whether or not MCM injection runs, so retrieval is **not** the MCM-sensitive
  metric.
- **`citation_validity_rate` is the MCM-sensitive metric.** A hypothesis may cite
  the MCM denial `event_id` only because injection unions that id into
  `prompted_ids` (the citation-gate's allowed set). Remove the injection and the
  same citation is FLAGGED — `citation_validity_rate` drops below its `1.0` floor
  and the case regresses.

This sensitivity is proved by
`test_mcm_denial_citation_validity_is_mcm_sensitive` in
`tests/test_eval_cases.py`: it runs the case once with injection (valid citation,
rate `1.0`) and once with `render_mcm_facts` stripped (flagged citation, rate
`< 1.0`) — removing the MCM injection turns this case red.

Offline test runs bind an `httpx.MockTransport` (EVAL-05, zero network); a live
`sift eval` against a local inference endpoint is the operator's CI gate
(EVAL-03).
