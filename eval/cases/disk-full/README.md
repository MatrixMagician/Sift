# disk-full

A synthetic disk-exhaustion scenario (SPEC §6 exemplar). The `/data` volume on
node `store-01` fills steadily — usage rises past the low-space warning to 100% —
after which every segment write and the write-ahead-log rotation fails with
`ENOSPC` (no space left on device), the ingest writer halts, and the node starts
returning `507` insufficient-storage responses. The planted root cause is the
full volume; the cascade of failed writes and rejected requests are the loud
symptoms a good triage run must trace to disk exhaustion rather than treating
each write failure as an independent fault. All node names and paths are
synthetic (no real data — REPT-05 redaction is deferred). No special shape — this
is a straight positive case.
