# Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV - Context

**Gathered:** 2026-07-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Turn the Phase-9 deterministic analyser into a **complete forensics command**,
`sift mcm <case>`, that for every detected denial episode:

1. **Emits deterministic diagnostic flags** with machine-independent thresholds
   (working-set % of IServer virtual, other-processes % of physical,
   cube-cache/MMF coverage, SmartHeap releasability, system-free headroom) —
   every threshold expressed as **% of HWM/total, never absolute GB** (MCM-03).
2. **Auto-selects a lead-up window** non-interactively from `AvailableMCM`-descent
   thresholds (as % of HWM) — no manual start-line picking (MCM-04).
3. **Attributes the memory granted in the window** by **OID**, by **`Source=`
   request type**, and by **SID (session)** — SID resolves the one-OID/many-session
   fan-out in the Hartford case (MCM-04).
4. **Ships a human-readable report and a CSV export** of the attribution via a
   dedicated `sift mcm <case>` command (MCM-05).

Requirements **MCM-03, MCM-04, MCM-05** only. Still zero-LLM and deterministic —
figures are computed, never model-authored.

**Explicitly NOT in this phase:**
- Feeding MCM facts into `sift analyze` as cited evidence, and the MCM golden
  eval case → **Phase 11** (MCM-06/07).

The porting basis remains `analyze_dss8.py`: this phase ports the parts Phase 9
deliberately discarded — the **window selection** (`prompt_window` logic, minus
the prompt) and the **per-OID/Source/SID attribution** — and adds diagnostic
flags and the report/CSV rendering on top of the Phase-9 episode models.
</domain>

<decisions>
## Implementation Decisions

### Command surface & output routing
- **D-10: Standalone `sift mcm <case>` command that always writes a bundle.**
  A new Typer subcommand (alongside `new/ingest/analyze/report/show/eval/doctor`).
  It **always** writes the report + CSV as artifacts into a `<case>/mcm/` subdir
  and prints a **short summary** to stdout (episode count, top flags). The report
  artifact honours `--format` (Markdown default → `mcm_report.md`; `--format json`
  → `mcm_report.json`).
- **Rationale:** a one-shot "forensics bundle" is the intended UX — the engineer
  runs one command and gets durable, shareable artifacts in the case directory.
- **Rejected:** *flag on `sift report` (`--mcm`)* — couples MCM to the general
  report/render path and its assumptions; *opt-in `--csv PATH` only* — the user
  wants the CSV produced by default as part of the bundle, not opt-in.

### Report layout & emphasis
- **D-11: Timeline-first per episode.** Each episode section leads with its
  **lifecycle timeline** (denial banner → `memory-status-low` → emergency
  working-set offload → recovery / open-truncated), then the **graded diagnostic
  flags**, then the **denial-time memory breakdown** table, then the **attribution
  tables**. Percentage-of-HWM/total framing throughout (never absolute GB in the
  headline figures).
- **Rationale:** the narrative (what happened, in order) orients the reader before
  the verdict and the numbers — matches how an engineer reads a denial post-mortem.

### Diagnostic-flag model
- **D-12: Graded severity (info / warn / critical), thresholds configurable via
  config only.** Flags carry a severity level and show the triggering % inline.
  The %-of-HWM/total thresholds are **documented constants in code**, overridable
  via a `[mcm.thresholds]` block in `~/.config/sift/config.toml` (standard config
  precedence: CLI > `SIFT_*` env > config.toml > defaults). **No per-run CLI
  threshold knobs** — keeps two runs' flags reproducible and determinism obvious.
- **Default cut-points are deferred to RESEARCH** — the researcher proposes
  evidence-based defaults for each dimension (working-set % of IServer virtual,
  other-processes % of physical, cube-cache/MMF coverage, SmartHeap releasability,
  system-free headroom) **validated against the real Hartford deny figures**, so
  the Hartford episode lands at a sensible severity.
- **Rejected:** *named booleans only* (no severity nuance); *CLI-overridable
  thresholds* (per-run flags make flag output harder to reproduce).

### Lead-up window
- **D-13: Fully automatic, non-interactive, no override.** The window is
  auto-selected from `AvailableMCM`-descent thresholds (as % of HWM) per MCM-04.
  The descent thresholds are **not** user-overridable in this phase — out-of-the-box
  determinism is preferred over a tuning knob.
- **Rejected:** *config-overridable descent thresholds* — considered, deferred;
  revisit only if a real case needs a different window and the defaults prove wrong.

### Attribution shape & CSV schema
- **D-14: Attribute by OID, by `Source=` request type, and by SID (session).**
  Three per-dimension views. SID resolves the one-OID/many-session fan-out. In the
  human report these render as **three per-dimension tables** per episode.
- **D-15: One CSV file with a `dimension` column.** A single
  `<case>/mcm/mcm_attribution.csv` with a `dimension` column (`oid` | `source` |
  `sid`) tagging each row; per-dimension views come from filtering. Suggested
  columns (final names are planner's call): `episode_id, dimension, key,
  granted_mb, request_count, event_ids`. One file loads cleanly in a spreadsheet.
- **D-16: Every attribution row carries the owning `event_id`(s).** Each row
  records the `event_id`(s) of the grant line(s) it aggregates, so the CSV **and**
  the in-memory model preserve the **cited ⊆ store** provenance end-to-end. This
  makes Phase 11's "MCM figures are cited, never model-authored" guarantee trivial
  to honour — the citation set is already attached to every attributed figure.

### Claude's Discretion
- Exact CLI flag names, module placement (expected: attribution/flag/window
  computation extending `src/sift/pipeline/mcm.py` or a sibling module; a report
  renderer under `src/sift/render/`; the command wired in `src/sift/cli.py`), the
  precise CSV column names/order, the report's Markdown structure, and the
  `[mcm.thresholds]` config schema — planner's/executor's call, provided
  D-10…D-16 and the locked constraints hold.
- Attribution/window logic reads the **Phase-9 episode models** and re-parses
  `Source=`/`SID`/`OID`/`Size=`/`AvailableMCM=` from `event.raw` (D-01 continues —
  no adapter change). The `hwm_bytes` / `avail_timeline` headroom fields
  **deliberately deferred from Phase 9** land in this phase (they feed window
  selection and the % thresholds).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & scope (authoritative)
- `.planning/ROADMAP.md` § "Phase 10: Diagnostic Flags, Lead-Up Attribution &
  `sift mcm` Report + CSV" — goal, dependency (Phase 9), and the 5 success
  criteria this phase is graded against (note criterion #5: identical flags on two
  differently-sized machines under the same relative pressure — a **scaled fixture**
  test).
- `.planning/REQUIREMENTS.md` § MCM Analysis — **MCM-03, MCM-04, MCM-05** are this
  phase; MCM-06/07 are Phase 11.

### Prior phase decisions that carry forward
- `.planning/phases/09-mcm-episode-detection-memory-breakdown/09-CONTEXT.md` —
  **D-01** (re-parse `event.raw`, no adapter change; every signal keeps its
  `event_id`), **D-04** (verbatim map + typed accessors), **D-05** (pure function,
  no store table), **D-06** (UTC order, fragment flag), **D-07** (open/truncated
  episodes). These remain locked.

### The Phase-9 code this phase builds on
- `src/sift/pipeline/mcm.py` — `detect_episodes(events) -> list[McmEpisode]` and the
  frozen models `McmEpisode` / `MemoryBreakdown` / `LifecycleSignal`. This phase's
  window/flags/attribution consume these episodes. The deferred `hwm_bytes` /
  `avail_timeline` headroom fields are added here.
- `tests/test_mcm.py` and `tests/fixtures/mcm/` — existing golden tests + the
  Hartford single-episode and two-episode fixtures to extend.

### Reference implementation (the porting basis for the new logic)
- `/home/oliverh/Downloads/analyze_dss8.py` (OUTSIDE the repo) and its vendored
  copy `docs/reference/analyze_dss8.py` — port the **window selection**
  (`prompt_window` logic minus the interactive prompt) and the **per-OID/Source/SID
  attribution** that Phase 9 discarded. Reuse the already-vendored regex/marker
  constants (`AVAIL_MCM_RE`, `HWM_RE`, `SIZE_RE`, `SOURCE_RE`, `SID_RE`, `OID_RE`).

### Contracts & integration points
- `src/sift/cli.py` — Typer CLI; add the `sift mcm <case>` subcommand mirroring the
  existing subcommand pattern.
- `src/sift/render/` — Markdown (primary) / JSON renderers; analog for the report
  bundle output.
- `src/sift/store.py` — `query_events()`, `get_events_by_ids()`; read-only, no schema.
- Config precedence (CLAUDE.md): CLI > `SIFT_*` env > `~/.config/sift/config.toml`
  > defaults — the `[mcm.thresholds]` override block follows this.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase-9 `mcm.py`** — `detect_episodes` + `McmEpisode`/`MemoryBreakdown`/
  `LifecycleSignal` are the input; the vendored regex/marker constants there
  (`AVAIL_MCM_RE`, `HWM_RE`, `SIZE_RE`, `SOURCE_RE`, `SID_RE`, `OID_RE`) already
  parse the tokens attribution needs — reuse, don't duplicate.
- **`analyze_dss8.py` window + attribution logic** (`docs/reference/`) — the
  `prompt_window`/window-selection and per-OID attribution the port must extend
  (drop the interactive prompt; the window is auto-selected per D-13).
- **Renderers** in `src/sift/render/` (Markdown/JSON) — analog for the report;
  the CSV writer is a small new deterministic emitter.
- **Typer CLI** in `src/sift/cli.py` — the `new/ingest/analyze/report/show/eval/
  doctor` subcommand pattern to mirror for `mcm`.

### Established Patterns
- **Pipeline-stage-reads-store + pure/deterministic** (`src/sift/pipeline/
  salience.py`, and Phase-9 `mcm.py`) — window/flags/attribution stay pure over the
  stored events; no I/O except the CLI command's file writes.
- **Typed frozen models** (`src/sift/models.py`, `extra="forbid"`) — new
  attribution/flag models match this convention.
- **Determinism & "nothing disappears"** — absent signals recorded, never
  fabricated; byte-identical re-run (no model involved).

### Integration Points
- New computation extends/sits beside `src/sift/pipeline/mcm.py`; the `sift mcm`
  command wires into `src/sift/cli.py`; the report renders via `src/sift/render/`;
  the CSV + report artifacts land in `<case>/mcm/`. Phase 11 will feed the same
  computed facts into `sift analyze`.
</code_context>

<specifics>
## Specific Ideas

- **Machine-independence is testable and load-bearing:** success criterion #5
  requires a **scaled fixture** — two differently-sized machines under the same
  *relative* pressure must produce **identical flags**. Research/planning must
  design this scaled-fixture test (halve/double the absolute MB, hold the %s).
- **Validate against the real Hartford deny case** — it has the genuine
  one-OID/many-SID fan-out that SID attribution (D-14) must resolve, and real
  denial-time figures to calibrate the default flag thresholds (D-12) against.
- **Thresholds and windows are % of HWM/total, never absolute GB** (milestone-locked).
- **Citation provenance (D-16)** is the bridge to Phase 11 — keep every attributed
  figure tied to its `event_id`(s) so `cited ⊆ prompted ⊆ store` holds for MCM-06.
</specifics>

<deferred>
## Deferred Ideas

- **MCM facts into `sift analyze` as cited evidence + MCM golden eval case** —
  Phase 11 (MCM-06/07).
- **Per-run CLI threshold overrides** — rejected for now (D-12); config-only.
- **User-overridable lead-up window / descent thresholds** — rejected for now
  (D-13); revisit only if the automatic window proves wrong on a real case.
- **Adapter enrichment / persisting episodes to a store table** — still deferred
  (Phase 9 D-01/D-05).
- **DSSPerformanceMonitor CSV time-series correlation (PERF-01)** — v2 (SEED-001).
</deferred>

---

*Phase: 10-diagnostic-flags-lead-up-attribution-sift-mcm-report-csv*
*Context gathered: 2026-07-19*
