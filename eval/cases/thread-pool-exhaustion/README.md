# thread-pool-exhaustion

A synthetic thread-pool exhaustion scenario (SPEC §6 exemplar). A fixed 32-thread
request executor saturates under sustained load: active-thread count climbs to
its ceiling, the backlog queue grows from single digits into the thousands, and
once the queue is full the pool starts rejecting work with
`RejectedExecutionException` and serving `503`s until the executor stops
completing tasks altogether. The planted root cause is pool saturation reaching
exhaustion; the rejected tasks and timed-out requests are the loud symptoms a
good triage run must attribute to the exhausted pool rather than to the
individual failed requests. All node names and request IDs are synthetic (no real
data — REPT-05 redaction is deferred). No special shape — this is a straight
positive case.
