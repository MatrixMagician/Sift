# Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-25
**Phase:** 17-Multi-Dump Progression & `sift eustack` Report + CSV
**Areas discussed:** Dump ordering basis, CSV export shape, Progression presentation, Three-or-more dumps, Signature identity in output, Multi-dump snapshot scope

---

## Dump ordering basis

| Option | Description | Selected |
|--------|-------------|----------|
| Timestamp, else flag + filename | Order by dump-time header timestamp when all dumps have one; otherwise sorted `source_file` order, basis stated, loud unverified-ordering flag, progression still renders | ✓ |
| Timestamp only, else refuse | No progression section at all when any timestamp is missing | |
| Timestamp, else operator must say | Fall back to nothing; require an explicit `--order` to authorise a basis | |

**User's choice:** Timestamp, else flag + filename
**Notes:** Keeps the report useful on captures lacking header timestamps while never inventing one — the ADR 0012 "record, don't apply" line. Rejecting the `--order` option also kept the CLI surface unchanged.

---

## CSV export shape

| Option | Description | Selected |
|--------|-------------|----------|
| One CSV, one row per signature | `eustack_signatures.csv`, per-dump count columns plus delta in multi-dump cases | ✓ |
| Two CSVs: signatures + progression | Separate long-format progression file, written only for 2+ dumps | |
| One CSV, long format | One row per (signature, dump) pair always | |

**User's choice:** One CSV, one row per signature
**Notes:** Matches the shipped single-CSV-per-command precedent (`mcm_attribution.csv`, `perfmon_trend.csv`).

---

## Progression presentation

| Option | Description | Selected |
|--------|-------------|----------|
| Changed only, ranked by \|delta\| | Only signatures whose count changed; new/vanished called out; population-level phrasing | ✓ |
| All signatures, ranked by \|delta\| | Every signature, mostly zero rows | |
| Changed only, capped top-N | Config-tunable cap with an omitted-count line | |

**User's choice:** Changed only, ranked by |delta|
**Notes:** The changed set is its own natural bound, so no cap was needed. Phrasing stays at population level because TID reuse is measured.

---

## Three or more dumps

| Option | Description | Selected |
|--------|-------------|----------|
| First→last, every dump columned | Single overall delta; trajectory only in the CSV | |
| Consecutive-pair chain | Per-adjacent-pair deltas | |
| Both: chain + overall | Per-pair deltas plus a first→last overall | ✓ |

**User's choice:** Both: chain + overall
**Notes:** Makes a grew-then-shrank population visible in the report itself rather than only in the export.

---

## Signature identity in output

| Option | Description | Selected |
|--------|-------------|----------|
| Matched frame + leaf | The two frames that explain the classification; no full frames tuple | ✓ |
| Matched frame + leaf + short hash | Adds a stable signature id for joining across runs | |
| Full frames, joined | Entire frames tuple in one cell | |

**User's choice:** Matched frame + leaf
**Notes:** Keeps the "why did this read as idle?" answer in the output without exporting long C++ symbol cells.

---

## Multi-dump snapshot scope

| Option | Description | Selected |
|--------|-------------|----------|
| Last dump, others in CSV | Full classification/saturation analysis on the most recent dump | ✓ |
| Every dump, one section each | Repeated near-identical analysis sections | |
| Union of all dumps | Analyse all dumps as one population | |

**User's choice:** Last dump, others in CSV
**Notes:** Union was rejected outright — summing snapshots would read a 3,900-thread server as 11,700.

---

## Claude's Discretion

- Markdown section ordering and table headings
- How dumps are grouped out of the case store (`source_file` is the obvious seam)
- Whether progression lives in `pipeline/eustack.py` or a new leaf module

## Deferred Ideas

- Operator `--order` override — rejected for this phase; revisit if the declared filename fallback proves misleading
- Stable per-signature hash column — rejected; additive later if operators ask
- Progression-section caps — unnecessary while only changed signatures are listed
