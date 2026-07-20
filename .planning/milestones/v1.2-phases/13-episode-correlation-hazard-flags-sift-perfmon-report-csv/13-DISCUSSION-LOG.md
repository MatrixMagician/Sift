# Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-20
**Phase:** 13-episode-correlation-hazard-flags-sift-perfmon-report-csv
**Areas discussed:** Window → time span, Trend figures & slope, Hazard flag shape, `sift perfmon` bundle & CSV, folded Phase 12 warnings
**Mode:** interactive (`discuss`) — user selected all four offered gray areas

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Window → time span | EpisodeWindow is event-id-keyed with no timestamps | ✓ |
| Trend figures & slope | Counter scope, slope definition, determinism, non-finite guard | ✓ |
| Hazard flag shape | Model choice, grading, hazard scoping and evidence | ✓ |
| perfmon bundle & CSV | Command surface, CSV rows, report body, no-log degraded mode | ✓ |

**User's choice:** all four.

---

## Deferred Phase 12 warnings (todo cross-reference)

`.planning/todos/pending/2026-07-20-dssperfmon-review-warnings.md` (tagged `resolves_phase: 13`).

| Option | Description | Selected |
|--------|-------------|----------|
| WR-03 (attrs key collision) | Short-name collision silently drops a counter; this phase reads those keys | ✓ |
| WR-02 (unbounded notes) | 13,596 printed lines / ~1 MB meta row on one header mismatch | ✓ |
| WR-05 (per-event drift reason) | Reason survives WR-02's note cap only if it lives on the event | ✓ |
| None — leave all three | Keep scope to PERF-04/05/06 only | |

**User's choice:** all three folded.
**Notes:** WR-05 became the evidence source for the counter-set-drift hazard (CONTEXT D-15), so
the three warnings and PERF-05 are one coherent piece of work rather than three patches.

---

## Window → time span

### How EpisodeWindow becomes the [start, end] span

| Option | Description | Selected |
|--------|-------------|----------|
| Resolve both ends by event_id | `window.start_event_id` and `episode.denial_event_id` → `Event.ts`; symmetric, no string parsing, both ends key to real stored events | ✓ |
| Resolve start by id, parse denial_ts | Uses the field named "denial timestamp", but adds a parse path that can disagree with the stored `Event.ts` | |
| Widen EpisodeWindow with ts fields | Cleanest for consumers, but edits a shipped v1.1 frozen model and its golden tests | |

**User's choice:** Resolve both ends by event_id.

### Fallback when `start_event_id` is None

| Option | Description | Selected |
|--------|-------------|----------|
| Episode's first timestamped event → denial | Mirrors `select_window`'s own "full available lead-up" fallback; keeps a real correlation | ✓ |
| No trend, explicit reason | Maximally honest, but loses corroboration on degraded episodes | |
| Whole perfmon file | Breaks criterion 1's identical-span guarantee | |

**User's choice:** Episode's first event → denial.

### Boundary event with `ts=None`

| Option | Description | Selected |
|--------|-------------|----------|
| Hazard flag, no fabricated span | Episode still appears, annotated with why it could not be corroborated | ✓ |
| Walk to nearest timestamped event | Salvages more episodes but silently shifts the span away from MCM-04's selection | |
| You decide | | |

**User's choice:** Hazard flag, no fabricated span.

### Sample matching and the empty case

| Option | Description | Selected |
|--------|-------------|----------|
| Closed interval; zero → hazard | `start <= ts <= end`; zero-in-span is the non-overlap symptom, so it gets the loud flag | ✓ |
| Closed interval; zero → silent empty | Makes the likeliest real failure look like an absence of data | |
| Half-open interval | Would exclude a sample landing exactly on the denial instant | |

**User's choice:** Closed interval; zero → hazard.

---

## Trend figures & slope

### Counter scope

| Option | Description | Selected |
|--------|-------------|----------|
| All numeric counters | No allowlist; customer CSVs won't carry Hartford's exact 22 | ✓ |
| Curated memory-pressure subset | Smaller output, but silently drops what a real artefact carries | |
| All, config-orderable | Full generality plus deterministic display order, at the cost of a new config surface | |

**User's choice:** All numeric counters.

### Slope definition and rounding

| Option | Description | Selected |
|--------|-------------|----------|
| (last−first)/seconds, fixed dp | Reproducible by hand from two cited rows; rounds at source per MCM-03 discipline | ✓ |
| Least-squares fit | Better on noisy series, but not hand-checkable and risks cross-machine float drift | |
| Both, endpoint headline | More information, doubles the determinism surface | |

**User's choice:** (last−first)/seconds, fixed dp.

### "Value at denial time"

| Option | Description | Selected |
|--------|-------------|----------|
| Last sample in the window | A real stored row with an `event_id`; on Hartford, the 266,042 MB sample the milestone quotes | ✓ |
| Nearest sample either side | Could cite a sample from after the event it describes | |
| Interpolated to denial instant | Cites no real event; unverifiable against the CSV | |

**User's choice:** Last sample in the window.

### Non-finite values

| Option | Description | Selected |
|--------|-------------|----------|
| Reject via `math.isfinite`, flag it | Per-counter-per-sample exclusion; where Phase 12's audit said the guard belongs | ✓ |
| Reject the whole sample | Discards good data for every other counter over one bad cell | |
| You decide | | |

**User's choice:** Reject via isfinite, flag it.

---

## Hazard flag shape

### Model

| Option | Description | Selected |
|--------|-------------|----------|
| New `PerfmonHazard` model | Same frozen/provenance shape, optional numeric figure; leaves shipped `mcm.py` untouched | ✓ |
| Reuse `DiagnosticFlag` as-is | Would need a sentinel `value_pct`, contradicting its locked "always part/whole*100" meaning | |
| Relax `DiagnosticFlag` | Shared vocabulary, but loosens the constraint encoding MCM-03's machine-independence | |

**User's choice:** New PerfmonHazard model.

### Grading

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed severities in code | Categorical facts, not threshold crossings — no number to tune | ✓ |
| Config-driven severities | Consistent with `config.mcm.thresholds`, but the values would be labels not measurements | |
| You decide | | |

**User's choice:** Fixed severities in code (non-overlap critical; zero-counter warn; drift warn).

### Zero-counter hazard scope

| Option | Description | Selected |
|--------|-------------|----------|
| No episodes → no hazard | Matches PERF-05's wording; avoids firing on every healthy case | ✓ |
| Always flag if zero throughout | Surfaces the fact earlier but detaches it from the contradiction that gives it meaning | |

**User's choice:** No episodes → no hazard.

### Drift evidence source

| Option | Description | Selected |
|--------|-------------|----------|
| Per-event `attrs` marker (WR-05) | Survives WR-02's cap; carries citable `event_ids` | ✓ |
| File-level `parse_coverage` notes | Available today, but WR-02 will truncate exactly this source and it has no `event_ids` | |
| Re-detect at correlation time | Re-derives what ingest already knew; can disagree with the adapter | |

**User's choice:** Per-event attrs marker (WR-05).

---

## `sift perfmon` bundle & CSV

### Bundle shape

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror `sift mcm` exactly | Carries across the proven path-containment guard, OSError→1 handling and WAL discipline | ✓ |
| Report only, `--csv` opt-in | Diverges from a learned contract; PERF-06 names the CSV as part of the deliverable | |
| Single combined JSON | Drops the Markdown primary output | |

**User's choice:** Mirror sift mcm exactly.

### CSV rows

| Option | Description | Selected |
|--------|-------------|----------|
| One row per counter per episode | A few hundred summary rows; raw samples are already citable via `sift show events` | ✓ |
| One row per sample | ~300k-cell re-dump of the store; buries the computed figures | |
| Both files | Serves both readers at the cost of a second large deterministic artefact | |

**User's choice:** One row per counter per episode.

### Report body

| Option | Description | Selected |
|--------|-------------|----------|
| Figures only, no series | Matches `mcm_report.md`'s figures-and-citations shape | ✓ |
| Figures plus sampled series | "Evenly-spaced" is a display heuristic needing its own determinism defence | |
| You decide | | |

**User's choice:** Figures only, no series.

### No-DSSErrors degraded mode (criterion 5)

| Option | Description | Selected |
|--------|-------------|----------|
| Whole-file trend, stated plainly | Engineer still gets the counter story; report never implies a correlation not performed | ✓ |
| Header saying no episodes, no figures | Trivially correct, but PERF-06 promises a counter-trend report | |
| You decide | | |

**User's choice:** Whole-file trend, stated plainly.

---

## WR-03 disambiguation (folded warning, needed before the correlator reads the keys)

| Option | Description | Selected |
|--------|-------------|----------|
| Qualify on collision only | Mirrors the existing `counter.` reserved-key approach; leaves Hartford's 22 keys byte-identical so Phase 12 fixtures stay green | ✓ |
| Always keep full qualifier | Collisions impossible by construction, but changes every existing key and invalidates Phase 12 fixtures | |
| Keep short, record collisions | Smaller change, but the counter is still lost and per-instance counters are normal in real exports | |

**User's choice:** Qualify on collision only.

---

## Claude's Discretion

Module layout and internal decomposition; how the correlator obtains events; exact `PerfmonHazard`
field and `dimension` spellings; the fixed decimal place for slope; hazard message wording; fixture
naming and the no-DSSErrors test strategy; render layout within the figures-and-citations
convention.

## Deferred Ideas

- Perfmon facts in `sift analyze` (PERF-07) and the golden perfmon eval case (PERF-08) — Phase 14
- Perfmon fact-block size cap — Phase 14
- Recovery-trend analysis (PERFV2-01), multi-host correlation (PERFV2-02), perfmon-only anomaly
  detection (PERFV2-03) — beyond v1.2
- Raw per-sample CSV export — rejected for D-18 as a re-dump of the store; revisit only if an
  external-plotting workflow is actually asked for
- Config-driven hazard severities — rejected for D-13 as a knob with nothing behind it
- Phase 11 code-review INFO follow-ups — reviewed, not folded (tagged `resolves_phase: 14`)
