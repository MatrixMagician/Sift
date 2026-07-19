# smtp-rejection-storm

A synthetic SMTP relay-rejection storm (SPEC §6 exemplar). The outbound relay
`smtp-out` starts returning permanent relay-access-denied replies (`554`/`550
5.7.1`) to every delivery attempt, so the mail node cannot hand off any message
and its outbound queue climbs from a handful to several hundred until delivery
throughput collapses to zero. The planted root cause is the relay rejection; the
rising queue depth and stalled delivery are the loud downstream symptoms a good
triage run must trace back to the rejection rather than blaming the queue
itself. All hostnames, message IDs and recipients are synthetic (no real data —
REPT-05 redaction is deferred). No special shape — this is a straight positive
case.
