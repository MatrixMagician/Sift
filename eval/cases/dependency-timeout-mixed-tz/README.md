# dependency-timeout-mixed-tz

A synthetic upstream dependency-timeout scenario (SPEC §6 exemplar) carrying the
**mixed-timezone** special shape (D-01). Two nodes log the same incident with
different UTC offsets: the upstream `payment-gateway` on node `pay-b` records at
`+05:30`, and the dependent `order-service` on node `ord-a` records at `-05:00`.
The gateway loses its backend ledger connection pool and stops responding first;
the order-service then times out calling it, opens a circuit breaker, and returns
`503` dependency-unavailable. The planted root cause is the gateway outage — but
its causal precedence over the order-service timeouts only holds once the two
logs are normalised to UTC. By naïve wall-clock the order-service failures
(`07:00-05:00`) appear *before* the gateway failure (`17:30+05:30`), inverting
cause and effect; this case exists to exercise INGST-11's per-node UTC
normalisation so the timeline does not silently invert. All node names and IDs
are synthetic (no real data — REPT-05 redaction is deferred).
