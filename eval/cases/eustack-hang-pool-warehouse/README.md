# Golden case: `eustack-hang-pool-warehouse`

The positive half of EUS-12: a synthetic warehouse connection-pool exhaustion
built from the documented hang scenario (`.planning/research/PITFALLS.md`
Pitfall 5, `.planning/REQUIREMENTS.md`'s "Known evidence gap", D-19-09), never
from `src/sift/rules/eustack_roles.toml`'s own pattern strings. Scored
entirely offline against `analyse_eustack_bundle` — no LLM, no client, no HTTP
endpoint touched at all (D-19-06/D-19-16).

## The scenario is authored. The stack frames are observed.

- **Scenario (authored):** every worker in the warehouse pool is parked on the
  same external-wait signature (`CDSSQueryEngine::WaitUntilFinished()`) so the
  pool has no worker left to service new work, alongside a smaller population
  of idle-parked job-queue noise threads — the composite shape
  `.planning/research/PITFALLS.md` Pitfall 5 and `19-CONTEXT.md` D-19-09
  specify.
- **Frames (observed):** copied byte-for-byte from the real reference capture
  (the earlier, `160739`, dump — the same capture `eustack-healthy`'s
  derivative is built from). The capture's own directory and filename carry an
  environment identifier and are never written into this repository; supply the
  path locally when re-deriving.
  - The warehouse-wait block (19 frames, `#0`–`#18`) is one of the two
    thread shapes measured among the capture's 79 genuinely
    `CDSSQueryEngine::WaitUntilFinished`-waiting threads (the majority
    variant, 76 of 79, differing from the minority variant only in one
    return address inside `RunAllSQLs`).
  - The idle-parked block (10 frames, `#0`–`#9`) is the single thread shape
    measured among the capture's 1,715 `MSIQTask::GetNextPreferredJob`-waiting
    threads.
  - Every distinct normalised frame symbol in this fixture was verified
    present in the source capture text (measured 2026-07-27): 21 distinct
    symbols, 0 missing.
- **Population (authored):** 25 warehouse-wait threads (clearly larger than
  the noise population, and enough to make the pool's occupancy unambiguous)
  plus 10 idle-parked noise threads (clearly more than a token handful, and
  clearly smaller than the saturated pool) — synthetic TIDs only
  (`900001`–`900025` warehouse, `901001`–`901010` idle), no TID or address
  reused from the real capture. `src/sift/rules/eustack_roles.toml` was never
  opened while authoring this fixture.

Fixture size: 38,460 bytes (well under the 64 KB cap), following the same
signature-preserving-and-small discipline as `tests/fixtures/eustack/`
(D-19-12).

## The measured figures (`analyse_eustack_bundle`)

Measured by parsing `input/threaddump.txt` through `EustackAdapter` and
calling `load_rules(None)` + `analyse_eustack_bundle` (the exact command is in
`19-04-PLAN.md`'s acceptance criteria and `tests/test_eval_cases.py`):

| Figure | Value |
|---|---|
| `total_threads` | 35 |
| `pools["warehouse"]` | total 25, idle 0, busy 25, occupancy 1.0 |
| `pools["job-queue"]` | total 10, idle 10, busy 0, occupancy 0.0 |
| `dependencies["warehouse"]` | thread_count 25, signature_count 1 |
| `lock_sites` | none — Rule 6 (`__lll_lock_wait`) is never matched by this
  fixture, per D-19-17/D-19-18: this case detects via figure reproduction of
  the pool/dependency rows, never via `bool(flags)` or a tripped
  `lock_convergence_count` |
| `flags` | `unclassified_thread_pct` info 0.0%, `no_resolvable_frame_pct`
  info 0.0% — the same two unconditional percentage flags every non-empty
  dump raises (D-19-18); zero `warn`/`critical` |

`hang_detected: true` in `truth.yaml` is declarative-only (D-19-17): Sift
computes no deterministic hang verdict — `PoolOccupancy`/`DependencyWait`
carry no threshold or severity at all. Detection here is proven by
`analyse_eustack_bundle` reproducing the declared pool and dependency figures
exactly, never by any flag being raised.

## What this case does — and does NOT — prove

This case proves the analyser reproduces a documented hang shape's
deterministic figures when they are present. It is authored, not observed —
weaker evidence than `eustack-healthy`'s real capture (D-19-10). Recall
against a genuine hung-server capture remains unproven; no such capture
exists yet (`.planning/REQUIREMENTS.md`'s "Known evidence gap"). The
cosmetic-mutation twin in `eustack-hang-pool-warehouse-mutated/` proves this
case is not overfit to string equality, but it is still evidence about one
authored scenario, not a corpus of real hangs.
