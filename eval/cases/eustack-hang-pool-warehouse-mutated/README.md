# Golden case: `eustack-hang-pool-warehouse-mutated`

The cosmetic-mutation twin of `eustack-hang-pool-warehouse` (D-19-11). Shipped
as a hand-authored, committed fixture — never generated at test time, so the
mutation itself stays auditable.

## The three mutations (all three, nothing else)

1. **Renumbered TIDs** — a disjoint synthetic range (`800001`–`800025`
   warehouse, `800101`–`800110` idle) sharing no value with the original's
   `900001`–`901010` range.
2. **Reordered thread blocks** — the original groups all 25 warehouse blocks
   then all 10 idle blocks; this twin interleaves them (warehouse, idle,
   warehouse, idle, …) so population order differs.
3. **Every instruction address changed** — every `0x...` value in the
   original is offset by `+0x1000000000000` before being re-printed, so no
   address token is shared between the two files.

The dump header's `PID` line differs (`800000` vs. `900000`); every frame
symbol is byte-identical to the original (verified: the multiset of frame
symbol strings between the two files is equal).

## Non-vacuity proof (measured, not assumed)

`tests/test_eval_cases.py::test_eustack_hang_twin_reproduces_identical_figures`
asserts, before any figure comparison:
- the two input files are not byte-identical;
- they share zero `0x...` address tokens;
- they share zero `TID` values.

Only then does it assert the measured figures — `analysis.total_threads`, the
`(subsystem, total_threads, idle_threads, busy_threads, occupancy)` tuples of
`bundle.saturation.pools`, and the `(subsystem, thread_count,
signature_count)` tuples of `bundle.saturation.dependencies` — are IDENTICAL
between the two fixtures. Under D-19-17, identical figures is the stronger and
more meaningful invariance check: "still raises a flag" would not catch a
mutation that quietly changed which pool or dependency the population landed
in.

## The measured figures

Identical to `eustack-hang-pool-warehouse`'s (measured independently against
this fixture's own `input/threaddump.txt`, not copied):

| Figure | Value |
|---|---|
| `total_threads` | 35 |
| `pools["warehouse"]` | total 25, idle 0, busy 25, occupancy 1.0 |
| `pools["job-queue"]` | total 10, idle 10, busy 0, occupancy 0.0 |
| `dependencies["warehouse"]` | thread_count 25, signature_count 1 |
| `flags` | `unclassified_thread_pct` info 0.0%, `no_resolvable_frame_pct`
  info 0.0% — zero `warn`/`critical` |

## What this case proves

A fixture that stops matching after a cosmetic mutation was overfit to string
equality, not to the scenario (`.planning/research/PITFALLS.md` Pitfall 5,
point 2). This twin proves `eustack-hang-pool-warehouse`'s detection survives
exactly that class of mutation — TID renumbering, block reordering and
address changes, none of which the analyser's signature semantics are
supposed to be sensitive to by construction (instruction addresses are
excluded from a signature; `@@GLIBC_x.y.z` suffixes and library/source tails
are stripped before comparison).
