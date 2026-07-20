# Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning
**Mode:** interactive (`discuss`) — see DISCUSSION-LOG.md

<domain>
## Phase Boundary

Turn the perfmon events Phase 12 stored into per-episode corroborating trend figures computed over
**MCM-04's existing auto-selected lead-up window**, grade three correlation hazards
deterministically, and ship both as a standalone `sift perfmon <case>` report + CSV bundle that
works on a case containing a perfmon CSV and **no DSSErrors log at all**.

**In scope:** window→time-span resolution; per-counter at-denial/slope/peak figures; a
`PerfmonHazard` model with the three PERF-05 hazards; the `sift perfmon` command and its
report/CSV bundle; the degraded no-episode path; and the three folded Phase 12 code-review
warnings (WR-02, WR-03, WR-05).

**Out of scope (Phase 14):** perfmon facts spliced into `sift analyze` (PERF-07), the golden
perfmon eval case (PERF-08), and the fact-block size cap that PERF-07 will need.

**Out of scope (project-wide, unchanged):** new window logic of any kind — the window is
*reused*, never re-derived; recovery-trend analysis (PERFV2-01); charts or plotting; timezone
inference by window-overlap maximisation; binary `.blg` input; downsampling on ingest.

</domain>

<decisions>
## Implementation Decisions

### Window → time span (PERF-04, criterion 1)

- **D-01:** The correlation span is `[start_ts, end_ts]` obtained by resolving **both ends by
  `event_id`**: `window.start_event_id` and `episode.denial_event_id`, each looked up in the store
  and read off `Event.ts` (already a UTC `datetime`, `models.py:21`). Symmetric, no string parsing,
  and both ends provably key to real stored events — the same D-16 provenance discipline MCM-04
  uses. Do **not** parse `McmEpisode.denial_ts` (a `str`) for the end bound; it can disagree with
  the stored `Event.ts` of the same row.
- **D-02:** **No new window logic.** `select_window` (`mcm.py:541`) is called as-is; this phase
  only *resolves* what it returns into a time span. The roadmap note is literal: "do not re-derive
  a window here."
- **D-03:** When `window.start_event_id` is `None` (the full-lead-up fallback — empty lead-up or
  absent HWM, `mcm.py:560`), the span starts at the **earliest event in `episode.event_ids` that
  has a `ts`**, and still ends at the denial. This mirrors `select_window`'s own intent — its
  fallback label is literally `"full available lead-up"` — and the window label already tells the
  reader the span was the full lead-up rather than a threshold descent.
- **D-04:** When a resolved boundary event has `ts=None` (or the denial has no timestamp at all),
  emit **no trend for that episode and raise a graded hazard naming the reason**. Never walk
  outward to the nearest timestamped event: that silently shifts the span away from what MCM-04
  selected — the same class of quiet invention the timezone rule already bans. The episode still
  appears in the report, annotated with why it could not be corroborated (nothing disappears
  silently).
- **D-05:** Sample selection is the **closed interval** `start_ts <= sample.ts <= end_ts`
  (inclusive both ends, so Hartford's last-sample-6 s-before-denial case is unambiguous), ordered
  by the store's canonical ordering (`ORDER BY ts IS NULL, ts, source_file, line_start`).
- **D-06:** **Zero samples in span raises the non-overlap hazard** (criterion 3), never a silently
  empty trend table. Zero-in-span *is* the wrong-timezone / wrong-host / wrong-day symptom, so it
  is the loud flag, not an absence of data.

### Trend figures (PERF-04)

- **D-07:** Compute figures for **every counter that parses numerically** — no allowlist. A
  customer CSV will not carry Hartford's exact 22 counters, an allowlist would silently drop what
  it does carry, and Phase 14's fact injection can then pick its own subset without re-running
  anything.
- **D-08:** **Slope = `(last − first) / seconds_elapsed`** in counter-units per second, **rounded
  to a fixed decimal place at source** — the MCM-03 `value_pct` discipline: round deterministically
  where the figure is produced, never at render. Chosen over a least-squares fit because the figure
  must be reproducible by hand from two cited sample rows; accumulated float summation across
  13,596 samples also makes bit-identical cross-machine results a risk rather than a given
  (criterion 2 is milestone-locked).
- **D-09:** **"Value at denial time" = the last sample at or before the denial boundary**, carrying
  its `event_id` as the citation. On Hartford that is the sample 6 s before the banner — precisely
  the figure the milestone quotes (266,042 MB). **Never interpolate**: an interpolated figure cites
  no real event and cannot be verified against the CSV, breaking the computed-and-citable contract.
- **D-10:** **Peak** carries its own `event_id` (the sample the peak came from), same provenance
  rule as every other figure.
- **D-11:** **Non-finite guard at conversion.** A counter value is accepted only if
  `math.isfinite(float(v))`. A non-finite or otherwise unusable value excludes *that counter* for
  *that sample* (not the whole row) from all figures, and is reported — never silently propagated.
  A single `nan` otherwise poisons slope, peak and at-denial into meaningless output. This is where
  Phase 12's security audit explicitly said the guard belongs — storage keeps the value verbatim,
  conversion rejects it.

### Hazard flags (PERF-05)

- **D-12:** Hazards travel in a **new `PerfmonHazard` model** in the perfmon module — `dimension`,
  `severity`, `message`, `event_ids`, and an **optional** numeric figure — with the same
  `frozen=True, extra="forbid"` shape and the same `event_ids` provenance discipline as
  `DiagnosticFlag`. Do **not** reuse or relax `mcm.DiagnosticFlag`: its `value_pct` docstring locks
  it as "ALWAYS `part/whole*100`" (the machine-independence invariant), non-overlap and drift have
  no such ratio, and relaxing it edits shipped golden-tested v1.1 code this phase otherwise never
  touches.
- **D-13:** **Severities are fixed in code, not config:** non-overlap = `critical` (the correlation
  is not trustworthy at all); always-zero `Total MCM Denial` = `warn`; counter-set drift = `warn`.
  These are categorical facts, not threshold crossings — there is no number to tune, so unlike
  `config.mcm.thresholds` (which grades genuine ratios) a config surface here would be a knob with
  nothing behind it.
- **D-14:** The always-zero `Total MCM Denial` hazard fires **only when detected denials exist in
  the window**, exactly as PERF-05 is worded. No episodes → no hazard: without a denial to
  contradict, a zero counter is just a zero counter, and firing on every healthy case trains the
  reader to ignore the flag that matters.
- **D-15:** The counter-set-drift hazard reads the **per-event drift marker in `attrs` that WR-05
  adds** (folded below). It survives WR-02's note capping — the whole reason WR-05 exists — and
  gives each flag real citable `event_ids`, which the file-level `stats.notes` cannot. Do not
  re-detect drift at correlation time; that re-derives at read time what ingest already knew and
  makes disagreement with the adapter possible.
- **D-16:** `Total MCM Denial` remains a **reported flag, never a correlation input** (unchanged
  milestone lock). Timezone is trusted from the PDH header, never inferred by maximising overlap
  (ADR 0012 + REQUIREMENTS.md § Out of Scope).

### `sift perfmon` bundle (PERF-06)

- **D-17:** **Mirror `sift mcm` (`cli.py:1004`) exactly.** Always write BOTH
  `<case>/perfmon/perfmon_report.md` (or `perfmon_report.json` with `--format json`) AND
  `<case>/perfmon/perfmon_trend.csv`, then print a short stdout summary. Same exit-code contract
  (ADR 0007): `0` = bundle written including an empty case, `1` = missing case / write failure,
  `2` = Typer usage. Matching the shipped command line-for-line carries across its already-proven
  path-containment guard (`case_db_path(...).parent / "perfmon"`, never a user-supplied path), its
  `OSError → exit 1` sanitised-message handling, and its `store.close()` WAL discipline.
- **D-18:** **CSV rows = one row per counter per episode**: episode, counter, at-denial value,
  slope, peak, peak's `event_id`, sample count. A summary artefact of a few hundred rows. The raw
  samples are already citable and dumpable via `sift show events`, so re-exporting all 13,596 rows
  would duplicate the store rather than add anything.
- **D-19:** **Report body = computed figures only, no series** — a per-counter-per-episode table of
  at-denial / slope / peak with citations, plus the hazards, plus the window label and its resolved
  span. Matches `mcm_report.md`'s shape (tables of computed figures with citations, never raw
  dumps). The series lives in the store; the report's job is the conclusion drawn from it.
- **D-20 (criterion 5 — the phase's named blocker):** With **no DSSErrors log and therefore no
  episodes**, there is no window, so compute the same figures over **each file's full sample
  range** and say so plainly in the report — e.g. "no MCM episodes detected; trend computed over
  the full sample range." **Exit 0, no empty-episode traceback.** The engineer still gets the
  counter story, and the report never implies a correlation that was not performed.

### Determinism (criterion 2 — milestone-locked)

- **D-21:** The correlator is pure and deterministic: no `set` iteration on any output path, all
  rounding at source (D-08), all ordering explicit, no model involvement anywhere. Same
  `model_dump_json`-is-byte-identical-on-re-run standard `analyse_mcm` already meets
  (`mcm.py:956`).

### Claude's Discretion

The planner retains discretion on: module layout (a new `pipeline/perfmon.py` vs extending an
existing module) and its internal decomposition; how the correlator obtains events (mirroring
`analyse_mcm`'s `list[Event]` parameter is the obvious analog); exact field and `dimension`
spellings on `PerfmonHazard`; the fixed decimal place in D-08; the hazard `message` wording
(British English); fixture naming and the test strategy for the no-DSSErrors case; and the exact
render layout within D-19's figures-and-citations convention.

### Folded Todos

**`.planning/todos/pending/2026-07-20-dssperfmon-review-warnings.md`** — all three warnings
folded (the file is tagged `resolves_phase: 13`):

- **WR-03 — colliding counter short names silently lose a counter** (`dssperfmon.py:76`,
  `dict(zip(...))` at `:227`). **Decision: qualify on collision only** — detect duplicate short
  names at header-parse time and keep the object/instance qualifier **only on the colliding ones**,
  mirroring the `counter.` prefix approach already used for reserved-key collisions. This leaves
  Hartford's 22 non-colliding keys **byte-identical**, so Phase 12's fixtures and golden assertions
  stay green. Must land **before** the correlator reads these keys — that is why the todo asked for
  a deliberate decision rather than a cleanup pass.
- **WR-02 — drift notes are unbounded** (`dssperfmon.py:246`, `cli.py:383,390`). Cap repeats: emit
  the first N, then one "and X more" summary line. Cap `_CSV_ERROR_NOTE` (added in `7a2ce84`) the
  same way in the same pass — it now has the identical unbounded-append shape. Without this, one
  header-width mismatch on the Hartford file means 13,596 printed lines and ~1 MB in a single
  `parse_coverage` meta row.
- **WR-05 — drift reason recorded only at file level.** Add a **per-event drift marker in
  `attrs`** so the reason survives WR-02's note capping. **This is D-15's evidence source** — the
  three folded warnings and PERF-05 are one coherent piece of work, not three unrelated patches.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § Phase 13 — goal, 5 success criteria, the "reuses MCM-04's window" note
- `.planning/REQUIREMENTS.md` § Correlation (PERF-04, PERF-05) and § Reporting (PERF-06)
- `.planning/REQUIREMENTS.md` § Out of Scope — no charts, no `.blg`, no tz inference by overlap,
  `Total MCM Denial` never a primary signal
- `.planning/REQUIREMENTS.md` § Reference Data — artefact paths and the observed lead-in trend table
- `.planning/STATE.md` § Blockers/Concerns — the Phase 13 no-DSSErrors-log entry (criterion 5)

### Prior-phase context (the decisions this phase builds directly on)
- `.planning/phases/12-dssperfmon-adapter-pipeline-exclusion/12-CONTEXT.md` — **MUST READ.**
  D-03 (`attrs` is `dict[str,str]`, short counter names, "numeric parsing belongs to Phase 13"),
  D-05 (adapter never infers severity — threshold judgement is this phase's job), D-16 (drift
  survives at ingest; *flagging* it is PERF-05, i.e. here)
- `.planning/phases/12-dssperfmon-adapter-pipeline-exclusion/12-REVIEW.md` — origin of WR-02/03/05
- `.planning/todos/pending/2026-07-20-dssperfmon-review-warnings.md` — **folded into scope**; carries
  the fix shapes and the deferred `math.isfinite` note that became D-11

### Architecture decisions
- `docs/decisions/0012-perfmon-naive-timestamps.md` — **MUST READ before any timestamp code.**
  The declared PDH bias is recorded in `attrs`, never applied; both artefacts are naive-stamped-UTC,
  which is what makes the 6-second join hold
- `docs/decisions/0007-*.md` — the exit-code contract D-17 mirrors
- `docs/decisions/0013-*.md` — the `AvailableMCM`/`MCM Settings` sniff qualification (Phase 12)

### Code the phase reuses, mirrors, or touches
- `src/sift/pipeline/mcm.py:541` `select_window` — **reused as-is**, never re-derived (D-02)
- `src/sift/pipeline/mcm.py:204` `EpisodeWindow` — `start_event_id` / `threshold_pct` / `hwm_bytes`
  / `request_count` / `label`; **carries no timestamps** — the fact that shapes D-01
- `src/sift/pipeline/mcm.py:181` `McmEpisode` — `denial_event_id`, `denial_ts`, `event_ids`
- `src/sift/pipeline/mcm.py:221` `DiagnosticFlag` — the model D-12 deliberately does **not** reuse
- `src/sift/pipeline/mcm.py:956` `analyse_mcm` — the orchestration analog and determinism standard
- `src/sift/models.py:18-47` — frozen `Event`; `ts` is `datetime | None` (UTC)
- `src/sift/render/mcm_report.py` — `render_mcm_markdown` / `render_mcm_json` /
  `write_attribution_csv`; the renderer shape D-18/D-19 mirror
- `src/sift/cli.py:1004` `mcm` — the command D-17 mirrors line-for-line
- `src/sift/adapters/dssperfmon.py:76,227,246` — WR-03 / WR-02 sites
- `src/sift/cli.py:383,390` — WR-02's note persistence and printing
- `src/sift/store.py` — `EXCLUDED_FROM_RANKING` seam; by-`event_id` retrieval stays **unfiltered**,
  which is what makes perfmon samples citable here at all (Phase 12 D-08)

### Reference artefacts (real data, read-only)
- `/home/oliverh/Downloads/hartford/hartford_Linux_DenyDSSPerformanceMonitor16234.csv` — 13,596
  samples, 22 counters, ~30 s interval; ends 6 s before the denial banner
- `/home/oliverh/Downloads/hartford/hartford_linux_deny_.log` — paired log, denials
  2026-04-07 12:39:45, same host `env-325602laio1use1`, PID 16234
- `/home/oliverh/Downloads/hartford/hartford_linux_snapshot.csv` — 6,803 samples, same counter set

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `mcm.select_window` / `mcm.detect_episodes` / `mcm.analyse_mcm` — the window and episodes arrive
  ready-made; this phase consumes them, never reimplements them
- `mcm.to_mb`, `mcm._grade` — unit conversion and two-cut-point grading already exist and are
  golden-tested (though D-13 fixes severities rather than grading ratios)
- `render/mcm_report.py` — table builders, `CSV_HEADER` convention, and `write_attribution_csv`'s
  deterministic writer are the direct template for the perfmon bundle
- `cli.py:1004` `mcm` — path containment, `OSError → exit 1`, `_sanitise` before echo,
  `store.close()` in `finally`; copy the structure, not just the idea
- `store.query_events()` — returns all events **including** perfmon (only `iter_event_summaries` is
  rank-filtered), so the correlator can see both artefacts from one call

### Established Patterns
- **Figures computed, never model-authored**; every figure carries `event_ids` (`cited ⊆ store`)
- **Round deterministically at source**, never at render (MCM-03 `value_pct`)
- **Frozen Pydantic models**, `extra="forbid"`, tuples not lists, no `set` iteration on output paths
- **`store.py` owns all SQL**; pipeline modules are SQL-free, typer-free, print-free
- **Flag loudly, never infer** — the standing rule behind D-04, D-06 and the timezone lock
- **Nothing disappears silently** — degraded episodes are annotated, not omitted (D-04)
- British English in user-facing strings; RED→GREEN→gate (ruff + pyright + pytest) per task

### Integration Points
1. New correlator module (planner's call on placement) — episodes + window + perfmon events →
   per-episode trend figures + `PerfmonHazard`s
2. New renderer alongside `render/mcm_report.py` — Markdown / JSON / summary CSV
3. `cli.py` — new `perfmon` command mirroring `mcm`
4. `adapters/dssperfmon.py` — WR-02 (note caps), WR-03 (collision-qualified keys), WR-05 (per-event
   drift marker in `attrs`); the WR-05 marker is what D-15 reads
5. Tests: span resolution incl. both fallbacks (D-03/D-04), zero-in-span → hazard (D-06),
   determinism/byte-identity (criterion 2), no-DSSErrors bundle at exit 0 (criterion 5), WR-03
   collision fixture, and a guard that Hartford's 22 keys stay byte-identical under WR-03

</code_context>

<specifics>
## Specific Ideas

- The Hartford join holds **only** because both artefacts are naive-stamped-UTC (ADR 0012): CSV
  last sample `12:39:39Z`, log denial activity `12:39:40Z` — a 6-second gap. D-05's closed interval
  and D-09's last-sample rule are chosen so this exact case reads cleanly.
- The figures the milestone quotes, which the report must reproduce: `Working set cache RAM
  usage(MB)` 27 → 266,042; `System\RAM used(MB)` 186,503 → 463,915; `Process(MSTRSvr)\Size(MB)`
  104,821 → 401,603; `Open Sessions` 3 → 1,488; `Total MCM Denial` 0 → 0.
- `EpisodeWindow` carrying no timestamps is the single discovery that shaped the phase — it is why
  D-01 exists and why the researcher should not assume a span is available for free.
- WR-03 is not reachable on the Hartford file (22 unique short names, verified) — it needs a
  **synthetic per-instance fixture**, the same situation Phase 12 hit with its unknown-fallback
  paths (12-CONTEXT D-17).

</specifics>

<deferred>
## Deferred Ideas

- **Perfmon facts spliced into `sift analyze`** — Phase 14 (PERF-07), MCM-06 pattern
- **Golden perfmon eval case** — Phase 14 (PERF-08)
- **Perfmon fact-block size cap** — Phase 14; 13,596 samples needs a bound equivalent to Phase 11's
  8-episode MCM cap
- **Recovery-trend analysis** — PERFV2-01, blocked: no post-denial evidence exists in the reference
  data
- **Multi-host correlation** — PERFV2-02
- **Perfmon-only anomaly detection** (trend breaks with no corresponding denial) — PERFV2-03
- **Raw per-sample CSV export** — considered for D-18 and rejected as a re-dump of the store;
  revisit only if an external-plotting workflow is actually asked for
- **Config-driven hazard severities** — considered for D-13 and rejected as a knob with nothing
  behind it; revisit if a site genuinely needs to downgrade one

### Reviewed Todos (not folded)
- **Phase 11 code-review INFO follow-ups**
  (`.planning/todos/pending/2026-07-20-phase11-code-review-info.md`) — IN-01 (shared granted-MB
  formatter in `mcm_facts.py`) and IN-03 (cosmetic tidy in `hypothesise.py`). Own frontmatter says
  `resolves_phase: 14`, and both touch MCM fact-splicing code Phase 13 does not modify. **Not
  folded** — left for Phase 14 as tagged.

</deferred>

---

*Phase: 13-episode-correlation-hazard-flags-sift-perfmon-report-csv*
*Context gathered: 2026-07-20*
