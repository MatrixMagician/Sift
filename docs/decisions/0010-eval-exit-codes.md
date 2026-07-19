# ADR 0010: `sift eval` exit-code contract + determinism-direction gate

**Status:** Accepted (implemented in Phase 7 / M7, Plan 07-03)
**Date:** 2026-07-19 (Phase 7 context; recorded per SPEC §10 open-question rule)
**Answers:** EVAL-03 — what exit code does `sift eval` return for a clean suite, a
regression below a threshold floor, a case that could not run, and a usage
error? And: which direction does the fourth ("determinism") metric take in the
gate, given the SPEC's "determinism drift" wording? Cross-refs SPEC.md §6
(determinism) / §8 (CI-friendly acceptance), D-06 (N=2 determinism check), D-07
(regression gate), D-08 (LLM-as-judge advisory only), and the sibling exit-code
ADRs 0005 (`sift analyze`) and 0007 (`sift report`).

## Context

`sift eval` runs the committed golden-case suite through the real ingest →
cluster → hypothesise pipeline, scores four keyword metrics against each case's
frozen `truth.yaml`, and compares the suite aggregates against the lower-bound
floors in `eval/thresholds.toml`. Its whole reason to exist (SPEC §8) is to be a
**CI gate**: a planted regression must fail the build, a clean suite must pass.
The exit code is therefore the integrity signal, and it must be
non-suppressible.

Two questions were open.

**1. What is the exit-code contract?** ADR 0005 gives `sift analyze` a 0/3/1/2
contract where 3 = degraded; ADR 0007 gives `sift report` a 0/1/2 contract with
no degraded tier. `sift eval` has no "degraded" outcome of its own — a case
either meets the floors or it does not — so the minimal `{0,1,2}` (the spirit of
0005/0007 without an invented tier) is the right shape. SPEC §8 only requires
*non-zero on regression*.

**2. Which direction is the determinism metric gated?** Three metrics are
naturally "higher is better" (retrieval hit rate, hypothesis hit@k, citation
validity). SPEC §6 speaks of "determinism **drift**", which is naturally "lower
is better" — a direction mismatch that would force the gate to special-case one
of its four comparisons. That asymmetry is the only genuinely ambiguous part of
the metric design.

A third, load-bearing hazard surfaced during Wave 2: `SuiteResult`'s aggregate
helpers **exclude** `run_failed` and `expect_no_incident` cases, and an *empty*
positive set averages to a vacuous `1.0`. Left unguarded, a total pipeline
failure (every case `run_failed`) would produce a perfect `1.00` aggregate and
**pass** the gate with exit 0 — silently, defeating both EVAL-03 and Sift's
"nothing disappears silently" invariant.

## Decision

**Exit-code contract** (`sift eval`):

| Exit | Meaning | When |
|------|---------|------|
| `0`  | pass | every keyword-metric aggregate meets its floor AND every case ran AND no negative case emitted a confident hypothesis |
| `1`  | regression / harness failure | any keyword metric regressed below its floor; OR any case could not run (`run_failed`); OR an `expect_no_incident` case emitted a confident hypothesis (a false positive); OR there is no scorable positive case (the vacuous-`1.0` trap) — the CI-friendly fail (SPEC §8) |
| `2`  | usage | Typer/Click usage error, incl. a missing/invalid `--suite` path or an unreadable/malformed `--thresholds` file — reserved for usage, never a semantic outcome |

The command **owns `typer.Exit(1)`**: the non-zero exit is raised by `eval_()`
after the table is printed and is never swallowed, so CI observes the regression.

**Determinism direction.** The gate compares **`determinism_stability`**
(fraction of cases whose N=2 repeated runs are byte-identical, higher-is-better,
floor `1.00`) so all four floors share one uniform comparison, `value >= floor`.
The report continues to **display** `drift = 1 − stability`, preserving SPEC §6's
"determinism drift" wording. One direction internally, two labels on the surface.

**The three anti-vacuity rules** are part of the gate itself, not just the CLI:
a `run_failed` case, a negative false positive, or an empty positive set each
force `passed = False` regardless of the (possibly vacuous) aggregates. A crashed
run is a regression, never silently excluded.

**Judge scores never gate** (D-08). The LLM-as-judge (Plan 05) is advisory: its
score is reported alongside the keyword metrics but is never consulted by
`gate()` and can never satisfy or veto the exit code.

## Consequences

- CI can treat `sift eval` exit 0 as "hypothesis quality holds" and branch on 1
  for "a metric regressed or a case failed" — a single, trustworthy signal.
- The vacuous-`1.0` failure mode is closed: a suite where every case crashed
  exits 1, not 0, so a broken pipeline can never masquerade as a perfect score.
- The four floors in `eval/thresholds.toml` stay uniformly directioned
  (`value >= floor`); adding a metric later needs no direction special-casing as
  long as it is expressed higher-is-better.
- Exit 2 stays reserved for Typer/Click and unreadable config; `sift eval` never
  raises `typer.Exit(2)` for a semantic (non-usage) outcome.
- This contract is narrower than ADR 0005's (no degraded tier 3) and mirrors ADR
  0007's `{0,1,2}` shape; together the three ADRs document why analyze, report,
  and eval differ on their middle tiers.
