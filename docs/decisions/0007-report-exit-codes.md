# ADR 0007: `sift report` exit-code contract (0 / 1 / 2)

**Status:** Accepted (implementation lands in Phase 6 / M6)
**Date:** 2026-07-18 (Phase 6 context; recorded per SPEC §10 open-question rule)
**Answers:** REPT-01 — what exit code does `sift report` return for a render of a
degraded case, a case with no hypotheses, an I/O or render failure, and a bad
`--format` value? Cross-refs SPEC.md §5.7 (renderers) / §5.8 (CLI exit-code
contract), Phase 6 RESEARCH Open Question 3 and Pitfall 7, and the contrasted
sibling ADR 0005 (`sift analyze` 0/3/1/2).

## Context

`sift report` turns a persisted analysis into a self-contained artefact. It is a
**pure function of `case.db`** — it constructs no `InferenceClient` and makes no
network call — so it can never itself produce a "degraded run": degradation is a
property of the *analyze* run that already happened and is recorded in
`triage_degraded` / per-row `citations_valid`.

That is the key difference from `sift analyze` (ADR 0005), which owns the 0/3/1/2
contract where **3 = degraded**. A report of a degraded case still *rendered
successfully* — the degradation is communicated inside the document (a degraded
banner plus FLAGGED rows surfaced from the persisted verdict, never recomputed),
not by the exit code. Propagating exit 3 from `report` would wrongly tell
automation "the render is flagged/broken" when the render is in fact complete and
correct; the flagging belongs to the analyze step that produced the data.

Typer/Click already own exit code **2** for usage errors. `--format` is a
`StrEnum` option, so an unknown value (`--format xml`) is rejected by Typer as a
usage error (exit 2) before any Sift code runs — 2 stays reserved for usage and
is never raised for a semantic outcome.

## Decision

`sift report` maps outcomes to this exit-code contract:

| Exit | Meaning | When |
|------|---------|------|
| `0`  | rendered | the report was produced — **including a degraded case** (the banner + FLAGGED rows communicate degradation; exit 3 is NOT propagated from report — RESEARCH Open Q3) |
| `1`  | failure  | no persisted hypotheses (analyze not run); a render or `--out` write failure; a `--format pdf` request when the `sift[pdf]` extra / pango is unavailable (D-10) — a helpful message, never a traceback |
| `2`  | usage    | Typer/Click usage error, incl. an unknown `--format` value — **untouched, never reused** |

Rationale:

- **Degraded → 0** (not 3): the renderer is byte-deterministic given identical
  `case.db` (REPT-03, scoped by ADR — see D-07); a successful render of any valid
  case is a success. Degradation is surfaced *in* the report, not in the code
  (RESEARCH Open Q3, Pitfall 6).
- **Missing `sift[pdf]` → 1, not 2** (RESEARCH Pitfall 7): an absent optional
  extra is a runtime failure with a remediation message, not the operator typing
  the command wrong. Both `ImportError` (extra not installed) and the WeasyPrint
  runtime/`OSError` (pango absent) map to the same D-10 message.
- **No 3**: unlike `sift analyze`, `report` has no "ran but flagged" outcome of
  its own — it only reads a prior verdict.

## Consequences

- Automation can treat a `report` exit 0 as "artefact produced" for any analysed
  case, degraded or clean, and branch on 1 for "nothing to report / render or
  PDF-extra failure".
- A degraded case is never presented as broken: exit 0 plus the in-document
  DEGRADED banner and FLAGGED rows keep the anti-hallucination signal visible
  (T-04-02 / T-06 register) without conflating it with a CLI failure.
- Exit 2 stays reserved for Typer/Click; `sift report` never raises
  `typer.Exit(2)` for a semantic (non-usage) outcome — the `StrEnum --format`
  gives usage-error 2 for free.
- This contract is deliberately narrower than ADR 0005's (no code 3), and the two
  ADRs together document why analyze and report differ on degraded handling.
