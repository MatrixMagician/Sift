# negative-no-incident

The suite's **negative** golden case (D-04). The input is a healthy,
steady-state log: successful `200` responses, passing health checks and routine
scheduled cache refreshes across two nodes, with no error burst, latency
degradation or anomaly of any kind. There is no planted root cause — this case
exists to prove the harness does *not* manufacture one. It sets
`expect_no_incident: true` and is scored by the no-confident-hypothesis
predicate (`negative_case_pass`): a run passes when it emits zero hypotheses or
only low-confidence ones. Any confident root-cause hypothesis here is a false
positive, and the case is excluded from the positive retrieval / hit@k
aggregates so a correct "nothing to see" outcome cannot be read as a keyword
miss. All node names and request IDs are synthetic (no real data — REPT-05
redaction is deferred).
