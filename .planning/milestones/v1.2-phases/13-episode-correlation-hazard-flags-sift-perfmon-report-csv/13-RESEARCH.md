# Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV - Research

**Researched:** 2026-07-20
**Domain:** Deterministic time-series correlation over an existing SQLite event store; stdlib-only maths; Typer CLI + renderer bundle mirroring a shipped command
**Confidence:** HIGH — this phase is integration of shipped code; every seam below was read from source at the line cited, and every claim about the Hartford artefacts was re-derived from the file with stdlib `csv`.

## Summary

Phase 13 adds **no new algorithms and no new dependencies**. Everything it needs already exists and
was verified in place: `select_window` returns a timestamp-free `EpisodeWindow` keyed by
`start_event_id`; `Event.ts` is a UTC `datetime | None`; `store.query_events()` returns every event
including perfmon (the `EXCLUDED_FROM_RANKING` seam only touches `iter_event_summaries`); `sift mcm`
is a 70-line command whose path-containment, `OSError → exit 1` and `store.close()` discipline
transfer verbatim; and `render_mcm_markdown` already ships the empty-analysis early-return that
success criterion 5 needs as its template.

The work is therefore: (1) a pure module resolving `EpisodeWindow` + `McmEpisode` into a
`[start_ts, end_ts]` span by two `event_id` lookups, (2) three stdlib arithmetic figures per counter
per episode, (3) a `PerfmonHazard` model with three categorically-graded flags, (4) a
`render/perfmon_report.py` cloned in shape from `render/mcm_report.py`, (5) a `perfmon` Typer command
cloned from `mcm`, and (6) three surgical `adapters/dssperfmon.py` fixes (WR-02/03/05).

Three pitfalls found in source that the CONTEXT could not have known and the planner must design
around: **`_bad_cells` does not reject `nan`/`inf`** (they parse as floats and land in `attrs` on a
`severity="info"` row), **a single-sample or zero-duration span divides by zero** in D-08's slope,
and **`query_events()` hydrates and zstd-decompresses all 13,596 perfmon rows** on every invocation.

**Primary recommendation:** Write `src/sift/pipeline/perfmon.py` as a pure stdlib module taking
`(analysis: McmAnalysis, events: list[Event])` — the exact analog of `analyse_mcm`'s signature — and
returning a frozen `PerfmonAnalysis`. Use `math.isfinite` + `round()` + `datetime` subtraction only.
Do not import numpy: it is a *transitive* scikit-learn dependency, not a declared one, and plain
Python is both determinate and sufficient at 13,596 rows.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Window → time span (PERF-04, criterion 1)**

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

**Trend figures (PERF-04)**

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

**Hazard flags (PERF-05)**

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

**`sift perfmon` bundle (PERF-06)**

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

**Determinism (criterion 2 — milestone-locked)**

- **D-21:** The correlator is pure and deterministic: no `set` iteration on any output path, all
  rounding at source (D-08), all ordering explicit, no model involvement anywhere. Same
  `model_dump_json`-is-byte-identical-on-re-run standard `analyse_mcm` already meets
  (`mcm.py:956`).

**Folded todos** (`.planning/todos/pending/2026-07-20-dssperfmon-review-warnings.md`, tagged
`resolves_phase: 13`) — all three warnings folded:

- **WR-03 — colliding counter short names silently lose a counter** (`dssperfmon.py:76`,
  `dict(zip(...))` at `:227`). **Decision: qualify on collision only** — detect duplicate short
  names at header-parse time and keep the object/instance qualifier **only on the colliding ones**,
  mirroring the `counter.` prefix approach already used for reserved-key collisions. This leaves
  Hartford's 22 non-colliding keys **byte-identical**, so Phase 12's fixtures and golden assertions
  stay green. Must land **before** the correlator reads these keys.
- **WR-02 — drift notes are unbounded** (`dssperfmon.py:246`, `cli.py:383,390`). Cap repeats: emit
  the first N, then one "and X more" summary line. Cap `_CSV_ERROR_NOTE` (added in `7a2ce84`) the
  same way in the same pass — it now has the identical unbounded-append shape.
- **WR-05 — drift reason recorded only at file level.** Add a **per-event drift marker in
  `attrs`** so the reason survives WR-02's note capping. **This is D-15's evidence source.**

### Claude's Discretion

The planner retains discretion on: module layout (a new `pipeline/perfmon.py` vs extending an
existing module) and its internal decomposition; how the correlator obtains events (mirroring
`analyse_mcm`'s `list[Event]` parameter is the obvious analog); exact field and `dimension`
spellings on `PerfmonHazard`; the fixed decimal place in D-08; the hazard `message` wording
(British English); fixture naming and the test strategy for the no-DSSErrors case; and the exact
render layout within D-19's figures-and-citations convention.

### Deferred Ideas (OUT OF SCOPE)

- **Perfmon facts spliced into `sift analyze`** — Phase 14 (PERF-07), MCM-06 pattern
- **Golden perfmon eval case** — Phase 14 (PERF-08)
- **Perfmon fact-block size cap** — Phase 14; 13,596 samples needs a bound equivalent to Phase 11's
  8-episode MCM cap
- **Recovery-trend analysis** — PERFV2-01, blocked: no post-denial evidence exists in the reference
  data
- **Multi-host correlation** — PERFV2-02
- **Perfmon-only anomaly detection** (trend breaks with no corresponding denial) — PERFV2-03
- **Raw per-sample CSV export** — considered for D-18 and rejected as a re-dump of the store
- **Config-driven hazard severities** — considered for D-13 and rejected as a knob with nothing
  behind it
- **Phase 11 code-review INFO follow-ups** (IN-01, IN-03) — tagged `resolves_phase: 14`, not folded
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-04 | Per-episode counter-trend correlation over MCM-04's existing lead-up window | § Verified Seam Map rows 1–4 (window/episode/event/store signatures, all confirmed at line); § Counter-Trend Maths (stdlib-only, zero-duration guard); § Pitfall 1 (`_bad_cells` non-finite gap) |
| PERF-05 | Graded hazard flags: non-overlap, always-zero `Total MCM Denial`, counter-set drift | § Hazard Detection (three detection sites verified against source); § `DiagnosticFlag` shape at `mcm.py:221` as the model template D-12 clones rather than reuses; § WR-05 marker placement at `dssperfmon.py:312-319` |
| PERF-06 | `sift perfmon <case>` report + CSV bundle, working with zero episodes | § `sift mcm` Command Anatomy (`cli.py:1003-1069`, every clause enumerated); § Zero-Episode Traceback Audit (all five candidate paths traced) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Span resolution (event_id → `datetime`) | `pipeline/perfmon.py` | — | Pure function over `McmAnalysis` + `list[Event]`; pipeline modules are SQL-free by convention |
| Sample selection in span | `pipeline/perfmon.py` | `store.query_events()` supplies the ordered list | Store owns all SQL; the pipeline filters an already-ordered in-memory list |
| Trend maths (at-denial / slope / peak) | `pipeline/perfmon.py` | — | Deterministic, stdlib, rounded at source |
| Hazard grading | `pipeline/perfmon.py` | — | Categorical, fixed in code (D-13) — no config tier involved |
| Drift evidence | `adapters/dssperfmon.py` (WR-05 marker) | `pipeline/perfmon.py` reads it | Ingest already knows; re-detecting at read time invites disagreement (D-15) |
| Markdown / JSON / CSV emission | `render/perfmon_report.py` | — | Renderers are the only tier that formats; figures arrive pre-rounded |
| Command wiring, paths, exit codes | `cli.py` | `store.case_db_path` for containment | CLI is the only tier allowed `print`/`typer` |

## Verified Seam Map

Every row below was read from source at the line cited on 2026-07-20.

### 1. Phase 10 / MCM-04 window reuse — VERIFIED

| Symbol | Location | Signature / shape |
|--------|----------|-------------------|
| `select_window` | `src/sift/pipeline/mcm.py:541` | `def select_window(ep: McmEpisode) -> EpisodeWindow` — pure, takes only the episode |
| `EpisodeWindow` | `mcm.py:204-218` | `threshold_pct: int`, `start_event_id: str \| None`, `hwm_bytes: int \| None`, `request_count: int`, `label: str`. **Carries no timestamps** — confirmed, this is what forces D-01 |
| `McmEpisode` | `mcm.py:181-202` | `denial_event_id: str`, `denial_ts: str \| None`, `recovery: str \| None`, `open_truncated: bool`, `fragmented: bool`, `event_ids: tuple[str, ...]`, `lifecycle`, `breakdown`, `hwm_bytes: int \| None`, `avail_timeline: tuple[tuple[str,int,int], ...]` |
| `EpisodeAnalysis` | `mcm.py:280-294` | `episode`, `window`, `flags: tuple[DiagnosticFlag, ...]`, `attribution` — the per-episode bundle |
| `McmAnalysis` | `mcm.py:297-306` | `episodes: tuple[EpisodeAnalysis, ...]`. Docstring states explicitly: "An empty case (no MCM denial episodes) yields `episodes=()` — never a crash." |
| `analyse_mcm` | `mcm.py:956` | `def analyse_mcm(events: list[Event], thresholds: McmThresholdsConfig) -> McmAnalysis` |
| `DiagnosticFlag` | `mcm.py:221-239` | `dimension: str`, `severity: str`, `value_pct: float`, `message: str`, `event_ids: tuple[str, ...]`. Docstring locks `value_pct` as "ALWAYS a ratio `part / whole * 100`". D-12's refusal to reuse is **correct as written** — confirmed at source |

**Fallback branch confirmed** [VERIFIED: `mcm.py:558-566`]: `if not timeline or not hwm_bytes:` returns
`threshold_pct=0, start_event_id=None, label="full available lead-up"`. D-03's handling is the only
option that does not invent a bound.

**Existing precedent for D-03's fallback resolution** [VERIFIED: `mcm.py:902-906`]: `attribute_window`
already does exactly this — `head = window.start_event_id or (ep.event_ids[0] if ep.event_ids else None)`.
The planner should note D-03 differs slightly: it takes the earliest event *that has a `ts`*, not
simply `event_ids[0]`. `event_ids` is documented as "ordered", so in practice `event_ids[0]` is the
earliest — but it may carry `ts=None`, which is why D-03's qualification exists. Recommend
implementing as a scan for the first `ts is not None` over `event_ids`, with a hazard (D-04) if none has one.

**Recommendation:** `select_window` is *already called* inside `analyse_mcm` and its result is on
`EpisodeAnalysis.window`. The correlator should take an `McmAnalysis` and never call `select_window`
itself — that is the most literal possible reading of "do not re-derive a window here."

### 2. Phase 12 / perfmon events in the store — VERIFIED

| Fact | Location | Detail |
|------|----------|--------|
| `EXCLUDED_FROM_RANKING` | `store.py:335` | `frozenset({"dssperfmon"})`. The comment at `:326-334` states directly: "They stay FULLY retrievable by identifier, so citation and `show events` are unaffected." |
| `query_events()` | `store.py:573-597` | `def query_events(self) -> list[Event]` — **no filtering whatsoever**; `SELECT ... FROM events ORDER BY ts IS NULL, ts, source_file, line_start`. Perfmon events **are** included. D-05's ordering claim is exactly this clause |
| `get_events_by_ids()` | `store.py:600-638` | `def get_events_by_ids(self, ids: Sequence[str]) -> dict[str, Event]` — `?`-bound `IN (...)`, unknown ids simply absent, empty `ids` returns `{}` without a query |
| `Event.ts` | `models.py:21` (per CONTEXT; consistent with `store.py:578`) | `datetime.fromisoformat(r[2]) if r[2] is not None else None` — a UTC-aware `datetime` or `None` |
| Perfmon `attrs` keys | `dssperfmon.py:286-309` | Always: `byte_offset`, `byte_len`, `host`, `pdh_version`. Conditionally: `tz_name`, `tz_offset_min` (ADR 0012 — recorded, never applied), `unparsed_columns`. Then one key per counter, short name, value as an **unconverted string** |
| Perfmon row `severity` | `dssperfmon.py:352` | `"info"` for a clean row; `"unknown"` via `_fallback_event` when `drifted or bad or ts is None` |
| Perfmon `component` | `dssperfmon.py:349` | `host` from the PDH header — useful for the wrong-host non-overlap narrative |
| `message` field | `dssperfmon.py:356` | `" ".join(f"{k}={v}" for k, v in values.items())` — a re-derivable string; **do not parse it**, read `attrs` |

**Recommendation for identifying perfmon events in the correlator:** filter on `event.source ==
"dssperfmon"`. Do **not** import `EXCLUDED_FROM_RANKING` — that constant means "held out of ranking",
which is a different concept from "is a perfmon sample", and coupling them would make a future
exclusion of another source silently change correlation. [ASSUMED: this is a design recommendation,
not a codebase fact.]

### 3. `sift mcm` command anatomy — the D-17 template, VERIFIED

`src/sift/cli.py:1003-1069`. Every clause the planner must clone:

| Clause | Line | Detail |
|--------|------|--------|
| Format enum | `cli.py:995-1001` | `class McmFormat(StrEnum): md = "md"; json = "json"` — an unknown value is Typer exit 2 |
| Signature | `cli.py:1004-1011` | `def mcm(case: str, fmt: Annotated[McmFormat, typer.Option("--format", ...)] = McmFormat.md, data_dir: DataDirOption = None) -> None` |
| Config + store | `cli.py:1022-1023` | `config = load_config({"data_dir": data_dir})` then `store = _case_store(case, config)` (`_case_store` at `cli.py:96` owns the missing-case → exit 1 path) |
| Deferred imports | `cli.py:1025-1030` | Pipeline and render imports are **inside** the function body, not module-level |
| Path containment | `cli.py:1035` | `mcm_dir = case_db_path(config.data_dir, case).parent / "mcm"` — never a user-supplied path |
| Analysis call | `cli.py:1036` | `analysis = analyse_mcm(store.query_events(), config.mcm.thresholds)` |
| Write + `OSError` | `cli.py:1043-1053` | `mkdir(parents=True, exist_ok=True)`, `write_text(..., encoding="utf-8")`, CSV writer; `except OSError as exc: print(f"Error: cannot write ... {_sanitise(str(exc))}"); raise typer.Exit(1) from None` |
| Summary | `cli.py:1055-1068` | Count + plural + filenames, then per-episode top flag sorted by `_sev_rank = {"critical": 0, "warn": 1, "info": 2}`, message through `_sanitise` before echo |
| WAL discipline | `cli.py:1069-1071` | `finally: store.close()` |

`_sanitise` is imported at `cli.py:40` as `from sift.render._util import sanitise as _sanitise`.

**`config.mcm.thresholds`** is threaded in for MCM grading. Per D-13 the perfmon command needs **no
config knob** — but it *does* need `config.mcm.thresholds` if it calls `analyse_mcm` to obtain the
episodes. Recommend: `sift perfmon` calls `analyse_mcm(events, config.mcm.thresholds)` to get
`McmAnalysis`, then passes both to the correlator. One `store.query_events()` call feeds both.

### 4. Renderer conventions — the D-18/D-19 template, VERIFIED

`src/sift/render/mcm_report.py`:

| Symbol | Line | Note |
|--------|------|------|
| `CSV_HEADER` | `:52-60` | Module-level `tuple[str, ...]`. Clone the pattern with a `PERFMON_CSV_HEADER` |
| `_mb_bytes` | `:79-80` | "Convert bytes to megabytes, rounded deterministically to 3 dp" — **the round-at-source precedent D-08 cites**, alongside `DiagnosticFlag.value_pct` at 1 dp |
| `_flags_table` | `:99` | The graded-flag table builder to mirror for hazards |
| `render_mcm_markdown` | `:206-219` | **Empty-case path already exists**: `if count == 0: out.append("_No MCM denial episodes detected._")` and returns early. This is the exact shape D-20 needs |
| `render_mcm_json` | `:222-230` | `json.dumps(analysis.model_dump(mode="json"), sort_keys=True, ensure_ascii=True, indent=2) + "\n"` — `ensure_ascii=True` is a **security control** (escapes C1/Cf terminal-injection bytes), not cosmetic. Clone verbatim |
| `write_attribution_csv` | `:233-264` | `path.open("w", newline="", encoding="utf-8")` + `csv.writer`; `event_ids` joined with `";"` to avoid comma-quoting |
| Type imports | `:40-50` | All pipeline model imports are under `if TYPE_CHECKING:` — follow this |

**Security note on the CSV writer** [VERIFIED: `mcm_report.py:236-242`]: the existing docstring argues
csv quoting is "the complete mitigation" *because* the keys are structurally hex (SID/OID) or
`Source=` `[\w:]+` values "which cannot begin with a spreadsheet formula trigger". **That argument
does not transfer.** Perfmon counter names come from the customer's CSV header — attacker-influenceable,
per the `dssperfmon.py` module docstring and the `_RESERVED_ATTRS` guard at `:75-85`. A counter named
`=cmd|'...'!A1` would be written into the `counter` column. See Pitfall 4.

### 5. Adapter fix sites (WR-02 / WR-03 / WR-05) — VERIFIED

| Warning | Site | Current code |
|---------|------|--------------|
| WR-03 | `dssperfmon.py:91-96` `_short_counter_name` | `return path.rsplit("\\", 1)[-1]` — two counters differing only by object/instance collapse to one key |
| WR-03 | `dssperfmon.py:154-165` `_parse_header` | `names = [_short_counter_name(c) for c in counters]` — **this is where collision detection belongs**; the function already returns `notes`, so a disclosure note costs nothing |
| WR-03 | `dssperfmon.py:286` | `values = dict(zip(counter_names, row[1:], strict=False))` — a duplicate key silently overwrites, losing a counter |
| WR-02 | `dssperfmon.py:311-316` | `stats.notes.append(_DRIFT_NOTE.format(...))` inside the per-row loop — unbounded |
| WR-02 | `dssperfmon.py:234-236` | `stats.notes.append(_CSV_ERROR_NOTE.format(...))` — identical unbounded shape |
| WR-02 | `cli.py:383` | `"notes": stats.notes if stats else []` persisted into the `parse_coverage` meta row |
| WR-02 | `cli.py:390-391` | `for note in stats.notes...: print(f"  note: {note}")` — 13,596 printed lines in the worst case |
| WR-05 | `dssperfmon.py:308-319` | `drifted = len(row) != header_width` is computed but recorded **only** in `stats.notes`. The per-event `attrs` marker goes here, before the `_fallback_event` yield at `:328` |

**Reserved-key precedent for WR-03's prefix approach** [VERIFIED: `dssperfmon.py:75-86, 299-309`]:
`_RESERVED_ATTRS` + `_COUNTER_PREFIX = "counter."`, applied as
`key = f"{_COUNTER_PREFIX}{counter_name}" if counter_name in _RESERVED_ATTRS else counter_name`.
CONTEXT's "mirroring the `counter.` prefix approach" is accurate.

**WR-05 marker key naming caution:** the new drift marker key must be added to `_RESERVED_ATTRS`
(`dssperfmon.py:75-85`) or a counter literally named e.g. `drift` could overwrite it — the exact
attack the reserved set exists to block. This is a real, easy-to-miss step.

## Counter-Trend Maths

### Dependency verdict: stdlib only

[VERIFIED: `pyproject.toml:7-19`] Declared runtime dependencies are `httpx`, `pydantic`, `pyyaml`,
`rich`, `scikit-learn`, `sqlite-vec`, `typer`, `zstandard`. **numpy is not declared** — it arrives
transitively via scikit-learn. Do not import it for this phase: it is not a declared contract, it
is not needed at 13,596 rows, and float reduction over an array offers no determinism benefit over
two-point arithmetic.

**Required imports:** `math` (for `isfinite`), `csv`, `datetime` (already in the event model). That is all.

### The three figures

| Figure | Formula | Determinism note |
|--------|---------|------------------|
| At-denial value | `samples[-1]` value for the counter, where `samples` are the in-span rows in canonical order | No arithmetic → exactly reproducible. Cite `samples[-1].event_id` |
| Slope | `(last - first) / (last.ts - first.ts).total_seconds()`, then `round(x, N)` | Two IEEE-754 float ops on identical inputs → identical result on any conforming platform. **Contrast with a least-squares fit**, which sums 13,596 terms and is order-sensitive. D-08 is well-founded |
| Peak | `max` over accepted values; on ties take the **earliest** sample | `max()` on a list returns the first maximal element, so plain `max(samples, key=...)` already yields earliest-wins. Make this explicit in a comment so a later refactor to `sorted(...)[-1]` does not silently flip it |

### Zero-duration guard — NOT covered by any locked decision

`(last.ts - first.ts).total_seconds()` is `0.0` when the span contains exactly **one** sample, or
when several samples share a timestamp. `x / 0.0` on floats raises `ZeroDivisionError` in Python
(it does not produce `inf`). This is a plain crash on a legitimate input — a case with a single
in-window perfmon sample.

**Recommendation:** slope is `None` when `seconds_elapsed == 0`, rendered as `—`. Do not raise a
hazard for it: one sample in a narrow window is normal at a 30 s sampling interval against a short
MCM descent, not a correlation failure. At-denial and peak remain computable and meaningful from the
single sample. [ASSUMED — this is a design recommendation; the planner should confirm with the user,
since it is arguably in D-06's neighbourhood but the CONTEXT does not decide it.]

**Verified relevance:** the Hartford CSV samples at ~30 s. If MCM-04's descent window is under
~30 s wide, single-sample spans are reachable on the reference data.

### Rounding place

`_mb_bytes` uses 3 dp; `DiagnosticFlag.value_pct` uses 1 dp. Slope in counter-units-per-second on
Hartford's working-set counter is roughly `(266042 − 27) / span_seconds`. Over a several-hour
descent that is O(0.01–1) MB/s. **Recommend 4 dp** so a slow but real climb does not round to
`0.0`. Discretionary per CONTEXT.

## Hazard Detection

### Hazard 1: non-overlap (`critical`)

**Trigger** (D-06): zero perfmon samples fall in `[start_ts, end_ts]`.

**Evidence to cite:** the span is defined by two log event_ids — cite both, plus (recommended) the
first and last perfmon `event_id` in the case so the reader sees both ranges side by side and can
diagnose *which* mismatch it is. A hazard reading "CSV covers 02/04 19:21 – 07/04 12:39; window is
09/04 03:00 – 09/04 03:40" is actionable; "no overlap" alone is not.

**Verified real-data context:** the Hartford deny CSV spans `04/02/2026 19:21:38.236` →
`04/07/2026 12:39:39.397` — **nearly five days, 13,596 samples**. The last sample is ~5.6 s before
the `12:39:45` denial. Both artefacts are naive-stamped-UTC (ADR 0012), which is what makes the join
hold; a five-hour EST shift would move the CSV end to `17:39` and blow the window entirely.

**Warning on wrong-host detection:** a *wrong host* whose clock overlaps produces samples in span
and will **not** trip this hazard. `Event.component` carries the PDH host (`dssperfmon.py:349`) and
`McmEpisode` events carry no host field to compare against — so cross-host mismatch is not
detectable from what is stored today. PERFV2-02 (multi-host) is deferred; be explicit in the report
that the hazard covers time non-overlap only, not host identity.

### Hazard 2: always-zero `Total MCM Denial` (`warn`)

**Trigger** (D-14): episodes exist AND every in-span sample's `Total MCM Denial` reads `0`.

**Verified on real data:** all 13,596 Hartford rows have exactly one distinct value for this
counter: `'0'`. The milestone claim is confirmed empirically.

**Implementation caution:** the counter name must be matched as an `attrs` key. After WR-03 lands,
a *collision-qualified* header would give this counter a qualified key — so match on the short name
first, then fall back to a suffix match, or read the key list rather than assuming the literal
string. Hartford's key is the bare `Total MCM Denial` (verified: 22 unique short names, no
collisions).

**Do not use `float(v) == 0.0`** for the zero test — use the stored string. `"0"`, `"0.0"` and
`"-0"` all compare equal as floats, which is fine, but `"0.0000001"` is not zero and must not be
reported as such. Float comparison is correct here; the string is only a caution against a
`v == "0"` shortcut that would miss `"0.0"`.

### Hazard 3: counter-set drift (`warn`)

**Trigger** (D-15): read the per-event marker WR-05 adds to `attrs`. Do **not** re-detect.

**Verified:** zero drift on the Hartford deny CSV — all 13,596 data rows have width 23, matching the
header. Like WR-03, this hazard **needs a synthetic fixture**; the reference data cannot exercise it.

### Hazard model shape

Clone `DiagnosticFlag`'s config and provenance, per D-12:

```python
class PerfmonHazard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str          # "non_overlap" | "mcm_denial_always_zero" | "counter_set_drift"
    severity: str           # fixed in code (D-13), not graded from a threshold
    message: str            # British English, figure inline
    event_ids: tuple[str, ...]
    value: float | None = None   # optional numeric figure (D-12)
```

`_grade` (`mcm.py:626`) is **not** used — D-13's severities are categorical. Note this explicitly in
a docstring so a reviewer does not read the omission as an oversight.

## Zero-Episode Traceback Audit (success criterion 5)

Every path traced. Verified state:

| Path | Verdict |
|------|---------|
| `analyse_mcm([...perfmon only...])` | **Safe.** `detect_episodes` yields nothing → `McmAnalysis(episodes=())`. Docstring at `mcm.py:299-302` guarantees it |
| `render_mcm_markdown` on empty | **Safe.** `mcm_report.py:210-214` early-returns `"_No MCM denial episodes detected._"` |
| `write_attribution_csv` on empty | **Safe.** Header row written, `for ea in analysis.episodes` iterates zero times |
| `cli.mcm` summary loop on empty | **Safe.** `n = 0`, plural correct, `for i, ea in enumerate(...)` iterates zero times |
| **New perfmon code** | **The only risk surface.** No shipped code needs fixing for criterion 5 |

**The three new-code traps the planner must name as explicit tasks:**

1. `samples[-1]` / `samples[0]` on an empty in-span list → `IndexError`. Every figure computation
   must be gated on a non-empty sample list.
2. D-20's full-range fallback: with no episodes there is no span, so figures come from each source
   file's full sample range. **If the case has neither episodes nor perfmon events**, that list is
   also empty — the report must still render and exit 0.
3. Grouping "per file" for D-20 uses `Event.source_file`. Iterate in sorted order, never over a
   `set` (D-21). `dict.fromkeys` over the canonically-ordered `query_events()` result preserves
   file first-appearance order deterministically and is the existing idiom (`mcm.py:936`,
   `mcm.py:949`).

## Common Pitfalls

### Pitfall 1: `_bad_cells` does not reject `nan` / `inf` — D-11 is load-bearing, not belt-and-braces

[VERIFIED: `dssperfmon.py:138-151`]

```python
def _bad_cells(names: list[str], values: list[str]) -> list[str]:
    for name, value in zip(names, values, strict=False):
        try:
            float(value)
        except ValueError:
            bad.append(name)
```

`float("nan")`, `float("inf")`, `float("-Infinity")` and `float("NAN")` all succeed. A row
containing them is therefore **not** flagged `unparsed_columns`, **not** degraded to
`severity="unknown"`, and lands in the store as a clean `severity="info"` sample with the string
`"nan"` in `attrs`.

**Why it goes wrong:** `nan` propagates silently through every comparison — `max()` returns garbage
because all `nan` comparisons are `False`, and slope becomes `nan`, which then serialises into the
JSON report as the literal token `NaN` (invalid JSON per RFC 8259, though `json.dumps` emits it by
default).

**How to avoid:** D-11's `math.isfinite(float(v))` at conversion time, exactly as decided. Exclude
that counter for that sample only, keep the row.

**Warning sign:** a slope or peak rendering as `nan`, or `json.loads` on the report failing.

**Recommendation:** the correlator's converter should be one small function returning `float | None`,
used everywhere a counter string becomes a number. Do not scatter `float()` calls.

### Pitfall 2: single-sample span divides by zero

See § Counter-Trend Maths. `ZeroDivisionError`, not `inf`. Reachable on real data at a 30 s interval.

### Pitfall 3: `query_events()` decompresses the entire case on every call

[VERIFIED: `store.py:573-597`] The method hydrates every row and calls `_decode_raw` (zstd
decompression for raw > 4 KB) for all of them — including all 13,596 perfmon rows. `sift mcm`
already pays this cost, so it is a known, accepted profile, not a regression.

**How to avoid making it worse:** call `store.query_events()` **once** in the `perfmon` command and
pass the same list to both `analyse_mcm` and the correlator. Do not call it twice.

**Not recommended for this phase:** adding a source-filtered query to `store.py`. It would be a new
public store method with new SQL for a cost the shipped sibling command already accepts —
speculative optimisation. Revisit if `sift perfmon` measurably drags.

### Pitfall 4: CSV formula injection through counter names

[VERIFIED: `mcm_report.py:236-242` argues csv-quoting suffices *because MCM keys are structurally
constrained*. Perfmon counter names are not.]

Counter names originate in the customer's CSV header. `csv.writer` quoting prevents *delimiter*
injection but does **not** neutralise a leading `=`, `+`, `-` or `@`, which Excel and LibreOffice
interpret as a formula on open.

**Recommendation:** prefix any counter-name cell beginning with `=`, `+`, `-` or `@` with a single
quote, or reuse the existing `render/_util.sanitise` if it already covers this (the planner should
read `_util.sanitise` before choosing — it is used for terminal-injection sanitising at
`cli.py:40`, and its scope was not verified in this session). Note it explicitly in the writer's
docstring so the divergence from `write_attribution_csv`'s reasoning is deliberate and visible.
[ASSUMED — a security recommendation, not a locked decision; flag to the user.]

### Pitfall 5: WR-03's fix must not perturb Hartford's 22 keys

[VERIFIED empirically] The Hartford deny CSV's 22 counters yield 22 **unique** short names —
`Total CPU`, `RAM used(MB)`, `Size(MB)`, `RSS(MB)`, `% CPU time`, `Working set cache RAM usage(MB)`,
`Open Sessions`, `Open Project Sessions`, `Total size (in MB) of document caches loaded in memory`,
`Total size (in MB) of cubes loaded in memory`, `Total Memory Mapped Files Size (MB)`,
`Total MCM Denial`, `Object Server Cache(MB)`, `Number of Intelligent Cube Cache Swaps`,
`Number of Document Cache Swaps`, `Number Of Report Cache Swaps`,
`Memory Used by Report Caches (MB)`, `Memory Used by Cube Rowmaps (KB)`,
`Memory Used by Cube Index Keys (KB)`, `Memory Used by Cube Element Blocks (KB)`,
`Memory Used by Change Journal Search (KB)`, `Element Server Cache(MB)`.

CONTEXT's claim that WR-03 is unreachable on Hartford is **confirmed**. The qualify-on-collision-only
decision therefore leaves all 22 keys byte-identical and Phase 12's golden assertions green.

**The collision shape a synthetic fixture must produce:** two columns differing only left of the
final backslash, e.g. `\\host\Process(MSTRSvr)\Size(MB)` and `\\host\Process(other)\Size(MB)` →
both short to `Size(MB)`. Note Hartford *does* have `Process(MSTRSvr)\Size(MB)` and
`Process(MSTRSvr)\RSS(MB)` — same object, different counters, no collision. The fixture needs the
same *counter* under two *instances*.

### Pitfall 6: WR-05's marker key can be shadowed by a counter

The new `attrs` key must be added to `_RESERVED_ATTRS` (`dssperfmon.py:75-85`). Without it, a CSV
whose header names a counter identically overwrites the drift evidence D-15 reads — reintroducing
exactly the class of attack `_RESERVED_ATTRS` was created to block.

### Pitfall 7: `denial_ts` is a `str`, `Event.ts` is a `datetime`

D-01 already forbids parsing `denial_ts`, but the trap is easy to fall back into when the denial
event lookup returns nothing. If `get_events_by_ids([denial_event_id])` misses (a tampered or
partially-ingested store), that is D-04's hazard — **not** a cue to parse `denial_ts` as a
consolation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Window selection | Any span/threshold derivation | `EpisodeAnalysis.window` from `analyse_mcm` | D-02; roadmap note is literal |
| Event lookup by id | A new SQL query in the pipeline | `store.get_events_by_ids` (`store.py:600`) or an in-memory index over the single `query_events()` result | Store owns all SQL; pipeline modules are SQL-free |
| Event ordering | A sort in the correlator | `query_events()`'s `ORDER BY ts IS NULL, ts, source_file, line_start` | D-05 names this exact clause; re-sorting risks disagreeing with it |
| Linear regression | scipy/numpy `polyfit` | Two-point slope (D-08) | Reproducible by hand; no float-summation nondeterminism |
| CSV writing | Manual string joins | `csv.writer(newline="")` per `mcm_report.py:243-244` | Quoting correctness |
| JSON canonicalisation | Custom serialiser | `render_mcm_json`'s exact `json.dumps(..., sort_keys=True, ensure_ascii=True, indent=2) + "\n"` | `ensure_ascii=True` is a terminal-injection control |
| Path safety | `Path(user_input)` anywhere | `case_db_path(config.data_dir, case).parent / "perfmon"` | `case_db_path` asserts containment; already proven at `cli.py:1035` |
| Exit codes | `sys.exit` | `typer.Exit(1)` / Typer's own usage exit 2 | ADR 0007 |
| Deduped ordered sequences | `set` | `tuple(dict.fromkeys(xs))` (`mcm.py:936`) | D-21 forbids `set` iteration on output paths |

**Key insight:** this phase's failure mode is *rebuilding* rather than *reusing*. Every plan task
should name the shipped symbol it consumes.

## Code Examples

### Resolving the span (D-01 / D-03 / D-04)

```python
# Source pattern: mcm.py:902-906 (attribute_window's head resolution)
by_id = {e.event_id: e for e in events}   # events from store.query_events()

denial = by_id.get(ea.episode.denial_event_id)
if denial is None or denial.ts is None:
    # D-04: hazard, no trend. Never fall back to parsing episode.denial_ts.
    ...

if ea.window.start_event_id is not None:
    start_ev = by_id.get(ea.window.start_event_id)
else:
    # D-03: earliest episode event that actually carries a ts.
    start_ev = next(
        (by_id[eid] for eid in ea.episode.event_ids
         if eid in by_id and by_id[eid].ts is not None),
        None,
    )
```

### The non-finite converter (D-11 / Pitfall 1)

```python
def _numeric(value: str) -> float | None:
    """Accept a counter cell only if it is a finite number (D-11).

    ``_bad_cells`` (dssperfmon.py:138) probes with bare ``float()``, which
    ACCEPTS nan/inf — so a non-finite cell reaches the store on a clean
    severity="info" row. This is the guard that stops it poisoning slope,
    peak and at-denial.
    """
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None
```

### The empty-report early return (D-20)

```python
# Source: mcm_report.py:210-214 — clone this shape verbatim.
if not analysis.episodes:
    out.append("_No MCM denial episodes detected; trend computed over the "
               "full sample range._")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `stats.notes` as the only drift record | Per-event `attrs` marker | This phase (WR-05) | Drift evidence becomes citable and survives note capping |
| Unbounded note append | First-N + summary line | This phase (WR-02) | Bounds a ~1 MB meta row and 13,596 print lines |
| `dict(zip(...))` silently dropping colliding short names | Qualify on collision only | This phase (WR-03) | No counter lost; Hartford keys unchanged |

**Deprecated/outdated:** nothing. No shipped API in this phase's blast radius is deprecated.

## Package Legitimacy Audit

**No external packages are added by this phase.** Every import required is either stdlib (`math`,
`csv`, `datetime`, `json`) or an already-declared dependency (`pydantic`, `typer`).

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| — | — | — | No new packages |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** none.

**Explicit non-addition:** numpy. [VERIFIED: `pyproject.toml:7-19`] It is not a declared dependency —
only transitive via `scikit-learn==1.9.0`. Importing it would create an undeclared runtime coupling.
Do not add it; stdlib arithmetic is sufficient and more deterministic.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python stdlib `math`, `csv`, `datetime`, `json` | All new code | ✓ | 3.12+ | — |
| pydantic | `PerfmonHazard` and analysis models | ✓ | `>=2.13.4` declared | — |
| typer | `sift perfmon` command | ✓ | `>=0.27.0` declared | — |
| Hartford reference artefacts | Golden figure tests | ✓ | Verified readable, 13,596 rows | Synthetic fixture (already required for WR-03 and drift) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (per `pyproject.toml:44-54`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`; `testpaths = ["tests"]` |
| Quick run command | `uv run pytest tests/test_perfmon.py -x` |
| Full suite command | `uv run pytest` |

`addopts = "-m 'not perf and not live and not packaging'"` — the default suite excludes those three
markers. New Phase 13 tests should carry **no marker** so they run by default.

**Zero-network rule** [VERIFIED: `tests/conftest.py:34-54`]: an autouse `_no_network` fixture
monkeypatches `socket.socket.connect` to raise. Nothing in this phase needs network, so no
interaction — but note that `@pytest.mark.live` tests are exempted only by explicit `-m live`.

**Filesystem isolation** [VERIFIED: `tests/conftest.py:15-32`]: an autouse `_isolate_dirs` fixture
redirects data/config dirs to tmp. `load_config().data_dir` in a test therefore points at tmp — this
is what lets CLI tests assert on written bundle paths.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-04 | Span resolves from `start_event_id` + `denial_event_id` | unit | `uv run pytest tests/test_perfmon.py -k span_from_event_ids` | ❌ Wave 0 |
| PERF-04 | D-03 fallback when `start_event_id is None` | unit | `... -k span_full_leadup_fallback` | ❌ Wave 0 |
| PERF-04 | D-04 hazard when a boundary has `ts=None` | unit | `... -k span_missing_ts_hazard` | ❌ Wave 0 |
| PERF-04 | At-denial / slope / peak match hand-computed golden figures | unit | `... -k golden_trend_figures` | ❌ Wave 0 |
| PERF-04 | Single-sample span yields `slope=None`, no crash | unit | `... -k single_sample_no_zero_division` | ❌ Wave 0 |
| PERF-04 | `nan`/`inf` cell excluded, row retained, reported | unit | `... -k non_finite_excluded` | ❌ Wave 0 |
| PERF-05 | Zero in-span samples → `critical` non-overlap hazard | unit | `... -k non_overlap_hazard` | ❌ Wave 0 |
| PERF-05 | All-zero `Total MCM Denial` with episodes → `warn` | unit | `... -k mcm_denial_always_zero` | ❌ Wave 0 |
| PERF-05 | No episodes → no always-zero hazard (D-14) | unit | `... -k no_episodes_no_zero_hazard` | ❌ Wave 0 |
| PERF-05 | Drift marker in `attrs` → `warn` drift hazard | unit | `... -k counter_set_drift_hazard` | ❌ Wave 0 |
| PERF-06 | Bundle written: report + CSV, exit 0 | integration | `uv run pytest tests/test_cli_perfmon.py -k bundle_written` | ❌ Wave 0 |
| PERF-06 | `--format json` writes `perfmon_report.json` | integration | `... -k json_format` | ❌ Wave 0 |
| PERF-06 | Missing case → exit 1; bad `--format` → exit 2 | integration | `... -k exit_codes` | ❌ Wave 0 |
| PERF-06 | Perfmon CSV, **no DSSErrors log**, exit 0, no traceback | integration | `... -k no_dsserrors_log` | ❌ Wave 0 |
| Crit. 2 | Byte-identical bundle on re-run | integration | `... -k byte_identical_rerun` | ❌ Wave 0 |
| WR-03 | Colliding short names both retained | unit | `uv run pytest tests/test_dssperfmon.py -k collision_qualified` | ⚠️ file exists, test new |
| WR-03 | Hartford's 22 keys unchanged (regression guard) | unit | `... -k hartford_keys_byte_identical` | ⚠️ file exists, test new |
| WR-02 | Note list capped, summary line emitted | unit | `... -k notes_capped` | ⚠️ file exists, test new |
| WR-05 | Drifted event carries the `attrs` marker | unit | `... -k drift_marker_in_attrs` | ⚠️ file exists, test new |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_perfmon.py tests/test_cli_perfmon.py tests/test_dssperfmon.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** `uv run ruff check && uv run pyright && uv run pytest` all clean before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_perfmon.py` — correlator unit tests (PERF-04, PERF-05)
- [ ] `tests/test_cli_perfmon.py` — bundle/exit-code integration tests (PERF-06)
- [ ] `tests/fixtures/dssperfmon/` synthetic fixtures — **three needed, none derivable from Hartford**:
      (a) colliding instance short names (WR-03), (b) mid-file column drift (WR-05/hazard 3),
      (c) a `nan`/`inf` cell (D-11). Verified: the Hartford deny CSV has 22 unique short names,
      uniform width 23 across all 13,596 rows, and zero non-numeric cells
- [ ] A perfmon-only case fixture (perfmon CSV, no DSSErrors log) for criterion 5
- [ ] No framework install needed — pytest already configured

**Existing fixture layout to follow** [VERIFIED]: `tests/fixtures/{dsserrors,dssperfmon,eustack,journald,mcm}/`.
The build-a-real-case helper idiom is at `tests/test_cli_mcm.py:28-45` — set `adapter.input_root`,
`list(adapter.parse(...))`, `CaseStore(db_path).insert_events(events)`, `store.close()` in `finally`.
Clone it with `DssperfmonAdapter`.

**Golden-figure test recommendation:** cut a small slice of the real Hartford CSV (a few dozen rows
around the denial) rather than shipping all 13,596. Assert exact rounded values so a maths
regression is unmissable. Pair with a byte-identity assertion on `render_perfmon_json` output across
two runs — that is criterion 2's direct test.

**Project TDD convention** [from project memory, not verified in source this session]: when a test
passes on its first run, inject a counterfactual break to confirm it actually fails without the
implementation, then restore byte-identically before committing. Applies to every RED step here.

## Security Domain

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI, no auth surface |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Filesystem permissions only |
| V5 Input Validation | **yes** | `case` name via `validate_case_name` (`store.py:124`); output path via `case_db_path` containment (`store.py:133`); counter values via D-11's `math.isfinite` gate; `--format` via `StrEnum` → Typer exit 2 |
| V6 Cryptography | no | None involved |
| V7 Error Handling / Logging | **yes** | `OSError → exit 1` with `_sanitise(str(exc))`, never a raw traceback (`cli.py:1049-1053`) |
| V12 Files & Resources | **yes** | Bundle dir derived from the validated case path only; never a user-supplied path |
| V14 Configuration | no | D-13 adds no config surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `case` argument | Tampering | `case_db_path(...).parent / "perfmon"` — proven at `cli.py:1035` |
| Terminal escape injection via counter names / log text into stdout | Tampering | `_sanitise` before every echo (`cli.py:40`, precedent `cli.py:1066`) |
| Terminal escape injection into the JSON report | Tampering | `ensure_ascii=True` in `json.dumps` (`mcm_report.py:230`) |
| **CSV formula injection via counter names** | Tampering | **Gap — see Pitfall 4.** `mcm_report.py`'s quoting-suffices argument does not transfer to attacker-influenceable counter names |
| Reserved-`attrs`-key shadowing by a crafted counter name | Tampering | `_RESERVED_ATTRS` + `_COUNTER_PREFIX` (`dssperfmon.py:75-86`) — **the WR-05 marker key must be added to this set** |
| Resource exhaustion via unbounded notes | DoS | WR-02's cap (folded into this phase) |
| `nan`/`inf` poisoning computed figures | Tampering | D-11's `math.isfinite` gate — **required**, since `_bad_cells` does not catch it |
| Tampered `case.db` yielding non-str `attrs` values | Tampering | `_coerce_str_list` precedent (`store.py:398`); `attrs` is `dict[str, str]` by Phase 12 D-03, but a tampered DB can hold otherwise — the converter's `float()` in a `try` already degrades safely |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Zero-duration span should yield `slope=None` rather than a hazard | Counter-Trend Maths | If the user wants a hazard, the report under-reports a real correlation gap. **Needs user confirmation** — the CONTEXT does not decide this and it is reachable on real data |
| A2 | Filter perfmon events on `event.source == "dssperfmon"` rather than importing `EXCLUDED_FROM_RANKING` | Verified Seam Map §2 | Coupling the two would make a future ranking-exclusion silently change correlation; low risk either way |
| A3 | CSV formula-injection prefixing is needed for counter-name cells | Pitfall 4 / Security | If skipped, a crafted counter name executes on spreadsheet open. **Recommend raising to the user** — it is a new control, not covered by a locked decision |
| A4 | Slope at 4 dp | Counter-Trend Maths | Too few dp rounds a slow real climb to `0.0`; explicitly discretionary per CONTEXT |
| A5 | `render/_util.sanitise`'s exact scope (does it cover leading `=`?) was not read this session | Pitfall 4 | The planner must read it before deciding whether to reuse or add a separate CSV guard |
| A6 | Golden test should use a cut slice of the Hartford CSV, not all 13,596 rows | Validation Architecture | Larger fixture slows the suite; no correctness risk |
| A7 | The correlator should consume `McmAnalysis` rather than calling `select_window` itself | Verified Seam Map §1 | Calling `select_window` directly would still satisfy D-02 literally, but duplicates work `analyse_mcm` already did |

## Open Questions

1. **Zero-duration / single-sample span handling (A1)**
   - What we know: `ZeroDivisionError` is a real crash on a reachable input; D-06 covers *zero*
     samples but not *one*.
   - What's unclear: whether one sample in span is a hazard or merely an un-computable slope.
   - Recommendation: `slope=None`, no hazard, rendered as `—`. Surface to the user at plan review.

2. **CSV formula injection (A3)**
   - What we know: counter names are attacker-influenceable; `write_attribution_csv`'s security
     argument explicitly rests on MCM keys being structurally constrained, which perfmon names are not.
   - What's unclear: whether the project wants a formula-prefix guard or accepts the risk as
     out-of-threat-model for a local forensics tool.
   - Recommendation: add the guard; it is four lines. Raise as a decision.

3. **Counter-name matching for `Total MCM Denial` after WR-03**
   - What we know: Hartford's key is the bare short name; a collision-qualified header would change it.
   - What's unclear: the exact qualified-key spelling WR-03 produces (a planner decision).
   - Recommendation: decide the WR-03 key format first, then write the hazard's lookup against it.
     Sequence WR-03 before the hazard task, as CONTEXT already requires.

## Sources

### Primary (HIGH confidence)
- `src/sift/pipeline/mcm.py` — `select_window:541`, `EpisodeWindow:204`, `McmEpisode:181`,
  `DiagnosticFlag:221`, `EpisodeAnalysis:280`, `McmAnalysis:297`, `analyse_mcm:956`,
  `attribute_window:902-949`, `_grade:626` — read directly
- `src/sift/store.py` — `EXCLUDED_FROM_RANKING:335`, `query_events:573`, `get_events_by_ids:600`,
  `validate_case_name:124`, `case_db_path:133`, `_coerce_str_list:398` — read directly
- `src/sift/cli.py` — `mcm:1003-1071`, `McmFormat:995`, `_case_store:96`, `_sanitise` import `:40`,
  note printing `:383,390` — read directly
- `src/sift/render/mcm_report.py` — `CSV_HEADER:52`, `_mb_bytes:79`, `render_mcm_markdown:206`,
  `render_mcm_json:222`, `write_attribution_csv:233` — read directly
- `src/sift/adapters/dssperfmon.py` — `_short_counter_name:91`, `_bad_cells:138`, `_parse_header:154`,
  `_RESERVED_ATTRS:75`, `parse:201-359` — read directly
- `tests/conftest.py:15-54`, `tests/test_cli_mcm.py:1-45`, `pyproject.toml:7-54` — read directly
- `/home/oliverh/Downloads/hartford/hartford_Linux_DenyDSSPerformanceMonitor16234.csv` — parsed with
  stdlib `csv`: 23 header columns / 22 counters / 22 unique short names / 13,596 data rows / uniform
  width 23 / `Total MCM Denial` single distinct value `'0'` / span `04/02/2026 19:21:38.236` →
  `04/07/2026 12:39:39.397` / working-set `27 → 266042`, RAM used `186503 → 463915`,
  Size(MB) `104821 → 401603`, Open Sessions `3 → 1488`

### Secondary (MEDIUM confidence)
- `.planning/phases/13-.../13-CONTEXT.md` — locked decisions, copied verbatim above
- Project memory (graphmind/claude-smart) — TDD counterfactual convention, ADR 0012 rationale

### Tertiary (LOW confidence)
- None. No web search was performed; this phase required no external research.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; `pyproject.toml` read directly, numpy confirmed transitive-only
- Architecture: HIGH — every consumed symbol read at its cited line
- Pitfalls: HIGH for 1, 2, 3, 5, 6 (derived from source or real data); MEDIUM for 4 (a security
  judgement about a control the codebase does not currently apply here)
- Hazard/report design: MEDIUM — constrained by locked decisions, but three points (A1, A3, A4) remain open

**Research date:** 2026-07-20
**Valid until:** indefinite for the codebase facts (they are pinned to commit `7bf59a8`); re-verify
line numbers if `mcm.py`, `store.py`, `cli.py` or `dssperfmon.py` change before planning
