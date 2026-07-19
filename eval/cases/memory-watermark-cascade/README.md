# memory-watermark-cascade

A synthetic quiet-cause golden case. The loudest signal in the log is a burst of
`oom-killer invoked` errors that kill most of the worker pool — the obvious,
high-count symptom. The true root cause is a single early low-severity warning,
`memory high-watermark exceeded`, which triggers progressive cache eviction that
cascades into the OOM kills. A good triage run must surface the quiet watermark
breach as the cause rather than stopping at the loud OOM symptom, which is why
this case exercises salience ranking and not merely parsing. All hostnames, IDs
and PIDs are synthetic (no real data — REPT-05 redaction is deferred).
