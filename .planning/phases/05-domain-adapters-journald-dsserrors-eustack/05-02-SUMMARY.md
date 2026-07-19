---
plan: 05-02
phase: 5
type: checkpoint:human-verify
gate: blocking-human
status: resolved
resolution: proceed-on-assumed-shapes
resolved: 2026-07-18
---

# 05-02 — Human-Verify Checkpoint: Resolution

**Gate:** `blocking-human` — confirm the two proprietary MicroStrategy formats before the
dsserrors/eustack regexes freeze (RESEARCH Open Questions 1–2).

## Decision

The user re-invoked `/gsd-progress --next --auto` at this gate rather than supply a sanitised
sample. Per the 05-02 fallback contract, Wave 2 proceeds on the **RESEARCH-derived assumed shapes**,
each flagged as an assumption in the adapter docstring and refinable later against a real sample
(reversible; nothing merges to main).

### Frozen-for-now assumptions (to be revisited if a real sanitised sample surfaces)

**eustack (05-05):** assume **native elfutils `eu-stack`** output — `TID <n>:` thread headers,
`#N 0xADDR symbol` frames, **no lock / blocked-on info**. Consequently ROADMAP Criterion 3 /
INGST-09 "lock info in attrs" is satisfied by asserting **absence** (nothing fabricated), per the
W2 contingency note already in 05-05. If real dumps turn out JVM-style, add lock extraction later.

**dsserrors (05-04):** assume the RESEARCH structural anchors — `[*.cpp:NNNN]` source tags,
MCM `***** Start/End of Info Dump *****` sentinel blocks, `0x`-prefixed error codes → `attrs["error_code"]`,
GUID-shaped OIDs → `attrs["oid"]`, SIDs → `session`, multi-node tag → `attrs["node"]` from the input
sub-directory name, rotated `.bak00/.bak01` siblings ordered by content/ts (never filename). The exact
line layout + SID token shape are `[ASSUMED]`; the adapter docstring records this and the regexes are
anchored on stable structural tokens so a layout refinement is a localised change.

## Follow-up

If the user later provides a sanitised DSSErrors.log snippet and/or eustack dump, re-open via a small
gap-closure plan to pin the `[ASSUMED]` regexes to ground truth. No re-plan of 05-04/05-05 structure
is needed — only the token regexes change.
