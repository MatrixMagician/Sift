# ADR 0005: `sift analyze` exit-code contract (0 / 3 / 1 / 2)

**Status:** Accepted (implementation lands in Phase 4 / M4)
**Date:** 2026-07-17 (Phase 4 context; recorded per SPEC §10 open-question rule)
**Answers:** CLI-04 — what exit code does `sift analyze` return for a run that
completed but produced flagged/unvalidated output, versus one that failed
outright? Cross-refs SPEC.md §5.8 (CLI exit-code contract) and Phase 4 RESEARCH
Pattern 4.

## Context

`sift analyze` is the scriptable entry point to the whole triage slice
(embed → cluster → label → salience → citation-gated hypotheses). An on-call
engineer wiring it into automation needs three outcomes to be distinguishable
from the exit code alone, without parsing stdout:

1. **Success** — hypotheses were generated and every citation is valid
   (`cited ⊆ prompted`).
2. **Degraded** — the run ran to completion, but the model output could not be
   fully validated (malformed JSON survived one repair round-trip) OR some
   citations were still invalid after one regeneration. The flagged/raw output
   is persisted and marked, never silently accepted as clean.
3. **Failure** — the run could not complete: an inference transport error, the
   SSRF guard refusing a non-local endpoint, a corrupt/absent `case.db`, or an
   unexpected exception. Nothing (or nothing new) is persisted.

Typer/Click already own exit code **2** for usage errors (unknown flag, bad
argument, and — in Sift — a malformed `--since`/`--until` or `--filter` value).
Reusing 2 for a degraded run would make "the operator typed the command wrong"
indistinguishable from "the model produced flagged output", so 2 is off-limits
for a semantic outcome.

The incident-time anchor is a related contract decision (RESEARCH Q3). Rather
than add a separate `--incident-time` flag, **`--until` doubles as the salience
incident-time anchor**: salience scores clusters by proximity to that moment.
When `--until` is omitted, the anchor falls back to the case-end timestamp (the
latest member `last_ts`), so a run with no temporal flags still ranks by a
sensible incident time. This keeps the flag surface minimal and makes
success-criterion-4's "user-supplied incident time" a first-class, documented
input rather than an implicit one.

## Decision

`sift analyze` maps its run `Outcome` to this exit-code contract:

| Exit | Meaning | When |
|------|---------|------|
| `0`  | success  | hypotheses generated; all citations valid (`cited ⊆ prompted`) |
| `3`  | degraded | ran to completion but repair failed or citations still invalid — output persisted and FLAGGED |
| `1`  | failure  | inference transport error, SSRF refusal, corrupt/absent `case.db`, or unexpected exception — nothing new persisted |
| `2`  | usage    | Typer/Click usage error, incl. a malformed `--since`/`--until` — **untouched, never reused** |

Rationale for **3**: it is the lowest free code that does not collide with
Typer's usage-error 2, keeps success (0) and hard failure (1) conventional, and
gives automation a distinct "review this — it's flagged, not clean, not broken"
signal.

The contract is surfaced in `sift analyze --help` (the exit-code table plus the
`--until` incident-time note) so it is discoverable without reading source, and
a CLI test asserts the wording is present.

## Consequences

- Automation can branch on three semantic outcomes (`0`/`3`/`1`) without parsing
  stdout, and can still tell a usage mistake (`2`) apart from a degraded run.
- A degraded run is never presented as a clean success: exit 3 plus a FLAGGED
  marker in `sift show hypotheses` keeps an invalid citation visible (T-04-02).
- `--until` carries two responsibilities (window bound + incident anchor). This
  is deliberate and documented; a future phase may split them if a use case
  needs an incident time outside the window, but v1 keeps the flag surface
  minimal.
- Exit 2 stays reserved for Typer/Click; Sift never raises `typer.Exit(2)` for a
  semantic (non-usage) outcome.
