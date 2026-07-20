---
type: todo
created: 2026-07-20
source: .planning/phases/12-dssperfmon-adapter-pipeline-exclusion/12-REVIEW.md
resolves_phase: 13
status: pending
---

# dssperfmon: three deferred code-review warnings (WR-02, WR-03, WR-05)

Raised by the Phase 12 code review. WR-01 and WR-04 were fixed in `7a2ce84`;
these three were deliberately deferred — none breaks a stated invariant, and
WR-03 changes `attrs` key shape, which Phase 13's correlator will read, so it
wants a deliberate decision rather than a cleanup pass.

## WR-02 — drift notes are unbounded

`src/sift/adapters/dssperfmon.py:246` appends `_DRIFT_NOTE` per drifted row.
`src/sift/cli.py:383` persists every note into the `parse_coverage` meta row and
`cli.py:390` prints each one. A single header-width mismatch on the Hartford file
(13,596 rows) means 13,596 printed lines and roughly 1 MB in one meta row.

Fix shape: cap repeats — emit the first N, then one "and X more" summary line.
Note the same unbounded-append shape now exists for `_CSV_ERROR_NOTE`
(added in `7a2ce84`); cap both together.

## WR-03 — colliding counter short names silently lose a counter

`_short_counter_name` (`dssperfmon.py:76`) drops the object/instance segment, so
two columns like `Process(A)\% CPU time` and `Process(B)\% CPU time` collapse to
one short name. `dict(zip(...))` at line 227 keeps the last, and the loss sets
neither `unparsed_columns` nor `drifted` — the row ships as a clean
`severity="info"` event having silently lost a counter.

Not reachable on the Hartford reference file (22 unique short names, verified),
but per-instance counters are normal in PDH exports, so real customer artefacts
will hit it.

Fix shape: detect duplicate short names at header-parse time and disambiguate
(keep the instance qualifier on collision only, mirroring the `counter.` prefix
approach used for reserved-key collisions). Decide before Phase 13 reads these
keys.

## WR-05 — drift reason recorded only at file level

Bad-cell degrades record their reason on the event (`attrs["unparsed_columns"]`);
drift degrades record it only in file-level `stats.notes`. Asymmetric, and it gets
worse once WR-02 caps the notes list — the per-event reason would then be the only
record, and it does not exist.

Fix shape: add a per-event drift marker in `attrs` so the reason survives note
capping.

## Also noted (info, no action decided)

- The `float()` validity probe accepts `nan` / `inf` / `1_0`, so such a row is
  classed `severity="info"` rather than degraded. The security audit's view is
  that the guard belongs in Phase 13's correlator at conversion time
  (`math.isfinite`), not here at storage — storage keeps the value verbatim.
- An emptied `EXCLUDED_FROM_RANKING` would build `WHERE source NOT IN ()`, a
  SQLite syntax error rather than a no-op.
