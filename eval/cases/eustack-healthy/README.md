# Golden case: `eustack-healthy`

The real, observed healthy reference capture, mechanically reduced to a small,
thread-proportion-faithful derivative and scored entirely offline against
`analyse_eustack_bundle` — no LLM, no client, no HTTP endpoint touched at all
(EUS-12, D-19-06/D-19-16). This is the negative half of EUS-12: the half that
can be proven against observed evidence rather than an authored scenario.

## Provenance

`input/threaddump.txt` is derived from the real reference capture (the earlier,
`160739`, dump of the two; its directory and filename carry an environment
identifier and are deliberately not recorded here — supply the path locally
when re-deriving) via
`tests/fixtures/eustack/derive_reference_capture_derivative.py`'s `--scale`
mode, added in this plan (19-03). The tool is deliberately meaning-blind — no
role, rule, pool or dependency concept, only per-signature block counts — so
the derivative cannot have been shaped to agree with anything downstream that
assigns meaning to a stack (the failure mode `PITFALLS.md` Pitfall 5 names).

Recorded invocation (the out-of-repo input path is a placeholder — the real
capture's filename carries an environment identifier and is never written
into this repository):

```
uv run python tests/fixtures/eustack/derive_reference_capture_derivative.py \
    <path-to-out-of-repo-capture> \
    eval/cases/eustack-healthy/input/threaddump.txt \
    --scale 26
```

`--scale 26` keeps `round(count / 26)` thread blocks per signature — a
signature whose population rounds to zero contributes no blocks, which is
what makes the result thread-PROPORTION-faithful rather than merely
signature-preserving (unlike the older, committed
`tests/fixtures/eustack/reference_capture_derivative.txt`, whose two-tier cap
policy inflates its unclassified share to a measured 38.1% and grades
`critical` — that fixture cannot serve as this case's input unchanged).

## The scale factor and the resulting thread count

| | Real capture | This derivative |
|---|---|---|
| Threads | 3,902 | 144 |
| Signatures | 93 | 93 |
| Unclassified share | 1.3% | 0.0% (rounds down at this scale) |

144 threads is well above the case's own 100-thread floor, and — because the
tool keeps every signature's *proportion* of the population rather than a
flat per-signature cap — the derivative's shape stays representative of the
real capture's composition rather than merely its signature set.

## The measured flag list

Measured by calling `load_rules(None)` and `analyse_eustack_bundle` over the
committed `input/threaddump.txt` (the exact command is in
`19-03-PLAN.md`'s acceptance criteria and `tests/test_eval_cases.py`):

| Dimension | Severity | Value |
|---|---|---|
| `unclassified_thread_pct` | info | 0.0% |
| `no_resolvable_frame_pct` | info | 0.0% |

Zero lock sites. No flag reaches `warn` or `critical` — this is the whole
point of the negative case: the analyser does not raise a false alarm on a
healthy, near-idle server.

## What this case does — and does NOT — prove

This case proves the analyser stays quiet on real, healthy evidence. It
proves nothing about hang-detection **recall**: a healthy capture cannot
demonstrate that the analyser correctly flags an actual hang, because it
contains no hang. The only evidence for recall is the authored, clearly
labelled synthetic fixtures in `eustack-hang-*` (Plan 19-04) — this case's
`expect_eustack.provenance` is `observed`, and it is the *only* case in the
suite marked that way (D-19-10), so the synthetic-versus-observed evidence
gap stays visible inside the harness itself, not only in planning documents.
