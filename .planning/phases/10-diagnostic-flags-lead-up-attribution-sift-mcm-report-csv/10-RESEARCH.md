# Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV - Research

**Researched:** 2026-07-19
**Domain:** Deterministic MicroStrategy MCM memory-pressure forensics (zero-LLM); Python stdlib + Pydantic + Typer
**Confidence:** HIGH (this is a *port* of a vendored, working reference over Phase-9 models — the algorithms exist and are validated against the real Hartford log; the only judgement calls are threshold cut-points, calibrated below against real figures)

## Summary

This phase turns the Phase-9 analyser (`detect_episodes → list[McmEpisode]`) into the complete `sift mcm <case>` forensics command. Almost every algorithm already exists in the vendored `docs/reference/analyze_dss8.py`: the window-selection (`prompt_window`), the per-OID/Source/SID attribution (`parse_log`), and the diagnostic-flag heuristics (`_write_detail`/`write_report`). The work is (1) porting those three, minus the interactive prompts, over the Phase-9 typed models; (2) landing the two deferred Phase-9 fields (`hwm_bytes`, `avail_timeline`) that feed window selection; (3) grading the flags info/warn/critical with config-overridable thresholds; and (4) wiring a Typer subcommand that writes a Markdown/JSON report + a single CSV into `<case>/mcm/`.

No new dependencies. `csv` is stdlib; the report renderer follows the existing `src/sift/render/` pure-`store→str` pattern; the flag/window/attribution logic extends `src/sift/pipeline/mcm.py` and stays I/O-free like `salience.py`. Determinism is inherent (no model), so success criterion #5 (machine-independence) reduces to: every threshold is a ratio (`part/whole`), so scaling every absolute MB by any factor leaves every percentage — and therefore every flag tier — byte-identical.

**Primary recommendation:** Port the three reference functions verbatim into `pipeline/mcm.py` as pure functions over `McmEpisode` + the event list; grade the reference's already-domain-tuned thresholds into info/warn/critical using the cut-points in the table below (calibrated so the real Hartford episode reads **CRITICAL**, driven by working-set = 65.4% of IServer virtual); auto-select the *widest* AvailableMCM-descent window (the reference's Enter-default); emit three attribution dimensions (OID/Source/SID) each carrying owning `event_id`s; write report + one dimension-tagged CSV.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-10:** Standalone `sift mcm <case>` command that **always** writes a bundle (report + CSV) into `<case>/mcm/` and prints a short stdout summary (episode count, top flags). Report honours `--format` (Markdown default → `mcm_report.md`; `--format json` → `mcm_report.json`). NOT a flag on `sift report`; CSV is not opt-in.
- **D-11:** Timeline-first per episode. Each episode section leads with its **lifecycle timeline** (denial banner → `memory-status-low` → emergency working-set offload → recovery/open-truncated), then **graded diagnostic flags**, then the **denial-time memory breakdown** table, then the **attribution tables**. Percentage-of-HWM/total framing throughout; never absolute GB in headline figures.
- **D-12:** Graded severity (info / warn / critical). Flags carry a severity level and show the triggering % inline. %-of-HWM/total thresholds are **documented constants in code**, overridable via a `[mcm.thresholds]` block in `config.toml` (precedence: CLI > `SIFT_*` env > config.toml > defaults). **No per-run CLI threshold knobs.** Default cut-points proposed in this RESEARCH, validated against real Hartford figures.
- **D-13:** Lead-up window is **fully automatic, non-interactive, no override.** Auto-selected from `AvailableMCM`-descent thresholds (as % of HWM). Descent thresholds NOT user-overridable this phase.
- **D-14:** Attribute by **OID**, by **`Source=` request type**, and by **SID (session)**. Three per-dimension views; in the human report, three per-dimension tables per episode. SID resolves the one-OID/many-session fan-out.
- **D-15:** One CSV file `<case>/mcm/mcm_attribution.csv` with a `dimension` column (`oid` | `source` | `sid`). Suggested columns (final names planner's call): `episode_id, dimension, key, granted_mb, request_count, event_ids`.
- **D-16:** Every attribution row carries the owning `event_id`(s) of the grant line(s) it aggregates — the `cited ⊆ store` bridge to Phase 11.

### Claude's Discretion
- Exact CLI flag names; module placement (expected: attribution/flag/window computation extending `src/sift/pipeline/mcm.py` or a sibling; a report renderer under `src/sift/render/`; the command wired in `src/sift/cli.py`); precise CSV column names/order; the report's Markdown structure; the `[mcm.thresholds]` config schema.
- Attribution/window logic reads the Phase-9 episode models and re-parses `Source=`/`SID`/`OID`/`Size=`/`AvailableMCM=` from `event.raw` (D-01 continues — no adapter change). The deferred `hwm_bytes` / `avail_timeline` headroom fields land in this phase.

### Deferred Ideas (OUT OF SCOPE)
- MCM facts into `sift analyze` as cited evidence + MCM golden eval case → **Phase 11** (MCM-06/07).
- Per-run CLI threshold overrides — rejected (config-only).
- User-overridable lead-up window / descent thresholds — rejected (fully automatic).
- Adapter enrichment / persisting episodes to a store table — still deferred (Phase 9 D-01/D-05).
- DSSPerformanceMonitor CSV time-series correlation (PERF-01) — v2 (SEED-001).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCM-03 | Deterministic diagnostic flags with machine-independent thresholds (working-set % IServer virtual, other-processes % physical, cube-cache/MMF coverage, SmartHeap releasability, system-free headroom) — % of HWM/total, never absolute GB | § Deliverable 1 (threshold table, Hartford calibration) + § Architecture Patterns (flag model + `compute_flags`) |
| MCM-04 | Attribute memory granted in each episode's auto-selected lead-up window (AvailableMCM-descent thresholds as % of HWM) by OID, by `Source=`, by SID | § Deliverable 2 (window algorithm) + § Deliverable 3 (attribution algorithm) |
| MCM-05 | Deterministic report + CSV export of the per-OID/Source/SID attribution via `sift mcm <case>` | § Architecture Patterns (renderer + CSV writer + CLI wiring) |

## Project Constraints (from CLAUDE.md)

- **Boring tech only:** stdlib (`csv`), Pydantic, Typer — no new deps. Justify anything else (nothing else needed).
- **Zero-LLM this phase:** figures are computed, never model-authored. No prompt template files (those are Phase 11).
- **Determinism:** identical case + config → byte-identical output (modulo timestamps). No `set` iteration in ordered output; insertion-ordered dicts/tuples (Phase-9 `mcm.py` already establishes this discipline).
- **Nothing disappears silently:** absent breakdown fields → `None`, never fabricated; grant lines that match the success marker but fail SID/OID/Size parse are recorded as `unmatched`, surfaced in the report (reference already does this).
- **British English** in docs and user-facing strings (report headings, flag messages).
- **Type hints everywhere;** `pyright` strict + `ruff` + `pytest` all green is "done". No M(n+1) while M(n) red.
- **Config precedence:** CLI > `SIFT_*` env > `config.toml` > defaults (existing `config.py` layered-dict mechanism).
- **`event_id = sha256(source_file, byte_offset)[:16]`** unchanged; attribution rows cite these existing IDs.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Episode detection (input) | `pipeline/mcm.py` (Phase 9) | — | Already built; consumed read-only |
| Window selection | `pipeline/mcm.py` (extend) | — | Pure function over episode + events; needs `hwm_bytes`/`avail_timeline` |
| Diagnostic flags | `pipeline/mcm.py` (extend) | `config.py` (thresholds) | Pure ratios over `MemoryBreakdown`; thresholds injected from config |
| Attribution (OID/Source/SID) | `pipeline/mcm.py` (extend) | `store.py` (read-only `query_events`) | Re-parse `event.raw` in the window span; aggregate 3 dicts |
| Report rendering (MD/JSON) | `render/` (new module) | — | Pure `episodes → str`, mirrors `render/markdown.py` |
| CSV export | `render/` or CLI (new, stdlib `csv`) | — | Deterministic dimension-tagged rows |
| Command orchestration + file writes | `cli.py` (`sift mcm`) | `config.py`, `store.py` | Only tier permitted I/O — reads store, calls pure pipeline, writes `<case>/mcm/` |
| Config `[mcm.thresholds]` | `config.py` (new `McmThresholdsConfig`) | — | Layered dict + Pydantic, `extra="forbid"` |

**Tier discipline:** the pure `pipeline/mcm.py` functions do the numeric work (SQL-free, print-free, I/O-free — the Phase-9 module docstring already commits to this); the renderer is a pure `→str`; only `cli.py` touches the filesystem (the `<case>/mcm/` writes). This mirrors how `analyze`/`report` already split compute from I/O.

## Standard Stack

No new packages. Everything is already in the project.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `csv` | 3.12+ | Deterministic CSV export (D-15) | `[VERIFIED: codebase]` reference `analyze_dss8.py` uses `csv.writer`; project convention is stdlib-first. `newline=""` + explicit column order = byte-stable |
| Pydantic | 2.13.x | New frozen flag/window/attribution models | `[VERIFIED: codebase]` `pipeline/mcm.py` already uses `BaseModel`/`ConfigDict(frozen=True, extra="forbid")` |
| Typer | 0.27.x | `sift mcm` subcommand | `[VERIFIED: codebase]` `cli.py` uses `@app.command()` for `new/ingest/analyze/report/show/eval/doctor` |
| `tomllib` (stdlib) | 3.12+ | `[mcm.thresholds]` parse | `[VERIFIED: codebase]` `config.py` already parses `config.toml` via `tomllib` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `csv` | pandas / manual string join | pandas is a heavy dep the project bans; manual join risks quoting bugs on `event_ids`/`Source=` values with commas. `csv.writer` handles quoting correctly, deterministically |
| Extend `McmEpisode` with `hwm_bytes`/`avail_timeline` | Recompute window inputs in a separate Phase-10 pass | Extending the model is one pass, matches the reference (fields live on the event dict), and the porting brief explicitly says these fields "land in THIS phase". Recompute would duplicate the `_line_stream` rebuild |

**Installation:** none.

## Runtime State Inventory

> This is an additive, port-based phase. No rename/migration, but two model-shape changes and one new config section warrant an explicit inventory.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — D-05 holds: no store table, no migration, no persisted episodes. The `<case>/mcm/` artifacts are derived outputs, regenerated each run. Verified: `store.py` is read-only here (`query_events`, `get_events_by_ids`). | none |
| Live service config | None — offline CLI, no services | none |
| OS-registered state | None | none |
| Secrets/env vars | New `SIFT_*` scalar keys *may* be added for `[mcm.thresholds]` if the planner wants env overrides; existing `_ENV_SCALARS` mechanism in `config.py` covers this. Nested-mapping thresholds are TOML/flag-only (same as `[timezones]`/`[adapters]`). | optional: register keys in `_ENV_SCALARS` |
| Build artifacts | None | none |
| **Model-contract change** | `McmEpisode` gains `hwm_bytes: int \| None` and `avail_timeline: tuple[tuple[str,int,int],...]` (event_id, avail, hwm). Phase-9 `test_determinism_byte_identical` compares run-to-run (not to a frozen golden string), so added deterministic fields stay equal. **Verify** no Phase-9 test pins a literal `model_dump_json` string. | RED test update in Phase 10; re-baseline any pinned JSON |

## Architecture Patterns

### System Architecture Diagram

```
sift mcm <case>  [cli.py]  ── only tier that does I/O ──
     │
     │ load_config({...})            [config.py]  → SiftConfig + McmThresholdsConfig
     │ CaseStore(db_path)            [store.py]   → query_events()  (read-only, source=="dsserrors")
     ▼
events: list[Event] ────────────────────────────────────────────────┐
     │                                                                │
     ▼   [pipeline/mcm.py — pure, I/O-free]                           │
detect_episodes(events) ──► list[McmEpisode]   (Phase 9, now also     │
     │                       populates hwm_bytes + avail_timeline)    │
     │                                                                │
     ├─► for each episode:                                            │
     │     select_window(ep)            ──► EpisodeWindow             │  (AvailableMCM-descent,
     │        (widest %-of-HWM descent, deterministic)                │   widest threshold = 25%)
     │     compute_flags(ep, thresholds)──► tuple[DiagnosticFlag,...] │  (5 dims, info/warn/critical,
     │        (pure ratios over MemoryBreakdown + mcm_settings)       │   ratios only)
     │     attribute_window(ep, window, events) ──► Attribution       │  (re-parse event.raw in span:
     │        {by_oid, by_source, by_sid}, each row carries event_ids │   SID/OID/Size/Source)
     ▼                                                                │
McmAnalysis (episodes + windows + flags + attributions) ◄────────────┘
     │
     ├─► render_mcm_markdown(analysis) / render_mcm_json(analysis)   [render/mcm_report.py — pure →str]
     │        timeline → flags → breakdown → attribution tables (D-11)
     └─► write_attribution_csv(analysis, path)                        [stdlib csv, dimension column]
     ▼
<case>/mcm/mcm_report.md   (or .json)
<case>/mcm/mcm_attribution.csv
+ short stdout summary (episode count, top flags)
```

### Recommended Project Structure
```
src/sift/pipeline/mcm.py       # EXTEND: window + flags + attribution models & functions
src/sift/render/mcm_report.py  # NEW: render_mcm_markdown / render_mcm_json (pure →str)
src/sift/config.py             # EXTEND: McmThresholdsConfig ([mcm.thresholds]) with extra="forbid"
src/sift/cli.py                # EXTEND: @app.command() def mcm(...) — orchestrate + write <case>/mcm/
tests/test_mcm.py              # EXTEND: window/flags/attribution + scaled-fixture + determinism
tests/test_mcm_report.py       # NEW (optional): renderer + CSV golden tests
tests/fixtures/mcm/            # EXTEND: pre-denial multi-SID lead-up + scaled fixture
```

### Pattern 1: Grade the reference's single-bound flags into info/warn/critical
**What:** The reference emits binary `[WATCH]`/`[REVIEW]` flags from `THRESHOLDS`. D-12 wants three tiers. Model each flag as a computed ratio compared to two cut-points `(warn, critical)`.
**When to use:** all five diagnostic dimensions.
**Example (shape, not final code):**
```python
# Source: ported from docs/reference/analyze_dss8.py:79-85, 524-605 ; graded per D-12
class DiagnosticFlag(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dimension: str        # "working_set_pct_virtual" | ...
    severity: str         # "info" | "warn" | "critical"
    value_pct: float      # the triggering ratio, already *100, rounded deterministically
    message: str          # British-English one-liner with the % inline
    event_ids: tuple[str, ...]  # the breakdown/settings event(s) the figure came from

def _grade(value_pct: float, warn: float, crit: float) -> str:
    return "critical" if value_pct >= crit else "warn" if value_pct >= warn else "info"
```

### Pattern 2: Auto-window = the reference's Enter-default (widest descent)
**What:** `prompt_window` builds descent options for thresholds `[25,15,10,5,2]`% of HWM and, on Enter, returns `options[0]` — the widest (25%) window. Port that default; drop the `input()`.
**When to use:** every episode, non-interactively (D-13).

### Pattern 3: Three independent attribution dicts, all citing event_ids
**What:** The reference nests `Source` under `OID` (`oid_sources[oid][source]`). D-14 wants three *independent* top-level dimensions. Accumulate `by_oid`, `by_source`, `by_sid` in one forward pass over the window span, each mapping `key → (granted_bytes, request_count, event_ids)`.
**When to use:** attribution stage.

### Anti-Patterns to Avoid
- **Absolute-GB thresholds:** every flag cut-point MUST be a ratio (`part/whole * 100`). A GB threshold breaks success criterion #5. (This is the one milestone-locked invariant.)
- **`set` iteration in ordered output:** use insertion-ordered dicts / `dict.fromkeys` for `event_ids` and SID sets rendered to CSV — matches Phase-9 determinism discipline. The reference's `', '.join(sorted(sids))` is fine (sorted is deterministic); a bare `set` in row order is not.
- **Recomputing the citation verdict / re-reading the store in the renderer:** the renderer is a pure function of the computed `McmAnalysis`, like `render_markdown` is of persisted state.
- **Attributing post-denial requests:** the window is the *lead-up* (`span_start … denial`), not the whole episode. The reference's `parse_log` stops **at** the denial line — post-denial succeeded lines are recovery-phase, not attributed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV quoting/escaping | manual `",".join(...)` | stdlib `csv.writer(f, ...)` with `newline=""` | `Source=` values and `event_ids` lists contain no commas today but the writer is correct-by-construction and deterministic |
| MCM token regexes | new patterns | the **already-ported** constants in `pipeline/mcm.py` (`SID_RE`, `OID_RE`, `SIZE_RE`, `SOURCE_RE`, `AVAIL_MCM_RE`, `HWM_RE`) | Phase 9 vendored these verbatim from the reference; divergent copies would drift |
| Window descent logic | new algorithm | port `prompt_window`'s "last crossing downward" logic | It already handles the always-below case (machine near-capacity all log) and dedups identical start lines |
| Breakdown accessors | new field extraction | Phase-9 `MemoryBreakdown` typed properties (`working_set_mb`, `iserver_virtual_mb`, `cube_caches_mb`, `mmf_mb`, `smartheap_unused_pool_mb`, `other_processes_mb`, `physical_total`) | Already fuzzy-match label drift via `_get`; flags read these directly |
| Config layering/precedence | new loader | existing `config.py` layered-dict + Pydantic | `[mcm.thresholds]` is just another section with `extra="forbid"` |

**Key insight:** ~90% of this phase is already written in `analyze_dss8.py` and validated against the real Hartford log. The risk is not algorithm design — it is (a) porting faithfully onto typed models while preserving `event_id` provenance, and (b) the *one* genuinely new judgement: the info/warn/critical cut-points, calibrated below.

---

## CRITICAL DELIVERABLE 1 — Evidence-based default flag thresholds (D-12 / MCM-03)

### Hartford real denial-time figures (from `tests/fixtures/mcm/hartford_deny_slice.log`, Format-A block lines 29-51 + Current Memory Info lines 6-18)

`[VERIFIED: codebase]` — figures read directly from the committed fixture; percentages computed this session:

| Raw figure | Value | Source line |
|------------|-------|-------------|
| Total System Physical Memory | 499 GB (=510976 MB) | 29 |
| Total In Use Physical Memory For Other Processes | 94516 MB | 32 |
| Total In Use Virtual Memory (Including MMF) For IServer | 410325 MB | 36 |
| Cube Caches In Memory | 27923 MB | 41 |
| MMF Virtual Memory Size | 365 MB | 43 |
| Working Set Cache RAM Usage | 268502 MB | 46 |
| Unused Memory Pool In SmartHeap | 5221 MB | 49 |
| Other Memory In Intelligence Server | 101682 MB | 51 |
| SmartHeap Cache Releasable | `true` | 23 (MCM Settings) |
| System Available / System Total | 49.1 / 498.6 GB | 6-7 |
| HWM(PB) (from succeeded lines) | 469891629056 B = 437.6 GB | 1 |

### Computed Hartford ratios (the calibration anchors)

| Diagnostic dimension | Metric | Hartford value |
|----------------------|--------|----------------|
| Working-set % of IServer virtual | `working_set / iserver_virtual` | **65.4%** |
| Other-processes % of physical | `other_processes / physical_total` | **18.5%** |
| Cube-cache share of virtual | `cube_caches / iserver_virtual` | **6.8%** |
| MMF coverage of cube cache | `mmf / cube_caches` | **1.3%** |
| SmartHeap unused pool % of virtual | `smartheap_pool / iserver_virtual` | 1.3% (releasable=`true`) |
| System-free headroom | `system_available / system_total` | **9.85%** |
| (context) Other-memory % of virtual | `other_memory / iserver_virtual` | 24.8% |

### Proposed default cut-points (all % of HWM/total; `[mcm.thresholds]` overridable)

| Dimension (config key) | info | warn | critical | Hartford → tier | Justification |
|------------------------|------|------|----------|-----------------|---------------|
| `working_set_pct_virtual` | <20% | 20–40% | **≥40%** | **65.4% → CRITICAL** | Working set = transient per-execution report/dashboard RAM; a healthy IServer keeps it a minority of virtual. Reference uses a single 20% upper bound `[CITED: analyze_dss8.py:81]` — adopt 20% as the warn floor, 40% as critical (working set dominating virtual is *the* denial driver; the log shows the emergency working-set offload firing — the server's own escalation). |
| `other_processes_pct_physical` | <10% | 10–20% | **≥20%** | **18.5% → WARN** | Reference's calibrated `(watch, review) = (10, 20)` `[CITED: analyze_dss8.py:80]` mapped directly to `(warn, critical)`. ISPerfDiag: IServer is meant to be the dominant tenant; large non-IServer physical use = cohabitation problem `[CITED: ISPerfDiag SKILL]`. Hartford's other-processes is real but secondary → WARN, not critical. |
| `cube_mmf` (conditional) | cube <25% of virtual | cube ≥25% of virtual **and** MMF <10% of cube | cube ≥40% of virtual **and** MMF≈0 | **6.8% cube → INFO** | Reference gates the MMF flag on `cube ≥ 40%` of virtual and `mmf < 10%` of cube `[CITED: analyze_dss8.py:83-84,586-600]`. MMF offloads cube data to disk; low coverage only matters when cubes dominate memory. Hartford's cube is small (6.8%) → the 1.3% MMF coverage is informational only. ISPerfDiag: "high MMF with modest RSS is normal and healthy" `[CITED: ISPerfDiag SKILL]`. |
| `smartheap_releasable` (conditional) | `Releasable=true` **or** pool <5% of virtual | `Releasable=false` and pool ≥5% of virtual | `Releasable=false` and pool ≥15% of virtual | **releasable=true → INFO** | Reference only flags when `SmartHeap Cache Releasable = false` `[CITED: analyze_dss8.py:430-438]`; a releasable pool is reclaimed by MCM automatically, so its size is not actionable. ISPerfDiag: "true means MCM can ask SmartHeap to give back its reserve" `[CITED: ISPerfDiag SKILL]`. Hartford is `true` → INFO regardless of the 5221 MB size. |
| `system_free_headroom_pct` | ≥20% | 5–20% | **<5%** | **9.85% → WARN** | Anchored on the server's own semantics: the MSTR memory-status handler declares "low" at **<20% available** (quoted verbatim in the log: line 63 `[VERIFIED: codebase]`). Reference flags `<5%` as `[REVIEW]` `[CITED: analyze_dss8.py:623-624]`. So info ≥20% (server considers healthy), warn 5–20% (server has declared low), critical <5% (near-exhaustion). Hartford 9.85% → WARN (and indeed the low-memory handler fired). |

**Episode overall severity** = the max tier across its flags. Hartford profile: **CRITICAL** (working set) + WARN (other-processes, headroom) + INFO (cube/MMF, SmartHeap). This is the sensible verdict D-12 asks for: a genuine denial reads CRITICAL, driven by the correct root cause (working-set blowout), with the headroom/cohabitation signals as supporting WARNs — matching how ISPerfDiag would triage this case.

**Config schema (suggested — planner finalises):**
```toml
[mcm.thresholds]
working_set_pct_virtual        = { warn = 20, critical = 40 }
other_processes_pct_physical   = { warn = 10, critical = 20 }
cube_pct_virtual               = { warn = 25, critical = 40 }   # cube share gate
mmf_pct_of_cube_low            = 10                              # MMF coverage floor
smartheap_pool_pct_virtual     = { warn = 5, critical = 15 }    # only when releasable=false
system_free_headroom_pct       = { warn = 20, critical = 5 }    # note: lower = worse (inverted)
```
Pydantic model: `McmThresholdsConfig(BaseModel, extra="forbid")` with defaults equal to the table above, so an absent `[mcm.thresholds]` block yields the documented constants. **Inverted metric caveat:** `system_free_headroom_pct` grades *downward* (smaller % = worse) — the grader must special-case direction, or store it as "headroom deficit" (`100 - free%`) so `≥` comparisons are uniform. Flag this to the planner explicitly.

---

## CRITICAL DELIVERABLE 2 — Window-selection algorithm (D-13 / MCM-04)

### Inputs (the deferred Phase-9 fields, landing now)
Per episode, `detect_episodes` must additionally populate:
- `hwm_bytes: int | None` — HWM from the last succeeded `Contract Request Succeeded` line before denial (reference: `avail_timeline[-1][2]`) `[CITED: analyze_dss8.py:182,206,228]`.
- `avail_timeline: tuple[tuple[str, int, int], ...]` — one entry `(event_id, available_mcm_bytes, hwm_bytes)` per succeeded line in the episode's lead-up, i.e. between the previous recovery and this denial. In Phase-9's disjoint-span model this is the succeeded lines from `span_start … denial_idx-1`. Reference filters `prev_recovery_lineno < ln < denial_lineno` `[CITED: analyze_dss8.py:178-181,202-205,224-227]`. Carry `event_id` instead of line number (D-16 provenance).

### Algorithm (port of `prompt_window`, minus `input()`)
`[CITED: analyze_dss8.py:678-773]`

1. If `avail_timeline` is empty or `hwm_bytes` is `None`: window = the full lead-up span (`span_start`); label "full available lead-up". (Reference "defaulting to line 1".)
2. For the **widest** descent threshold — **25% of HWM** (the reference's `WINDOW_THRESHOLDS_PCT[0]` and Enter-default) `[CITED: analyze_dss8.py:76,762-764]`:
   - `threshold_bytes = hwm_bytes * 0.25`.
   - **Last-crossing-downward:** find the last timeline sample with `available ≥ threshold_bytes` (`last_above`); then the first sample after it with `available < threshold_bytes` — that sample's `event_id` is the window start.
   - If `last_above` is `None` (AvailableMCM was **always below** 25% — the near-capacity-all-log case, which is exactly Hartford where AvailableMCM=0 at line 1): window start = the **first** timeline entry. This anchors to final pressure descent, not the first-ever crossing, avoiding "line 1 of a busy log always wins."
3. **Deterministic; no tie-break needed** beyond "first timeline entry on always-below." Only the single widest threshold is used (the other thresholds `[15,10,5,2]` exist in the reference solely to populate the interactive menu — with no user to choose, the Enter-default is the whole algorithm). Record the chosen `threshold_pct=25`, the window-start `event_id`, and the request count in the window.

### Hartford worked example
The slice's only pre-denial succeeded line is line 1 (`AvailableMCM=0`, `HWM(PB)=469891629056`). `avail_timeline = [(evt_of_line1, 0, 469891629056)]`. `0 < 25% × HWM`, so always-below → window start = line 1's event. Window = the single pre-denial request (OID `A3EDD9C7…`, SID `228F6335…`, Source `CDSSXTabIndices::GenDistinctC`, Size 19283968). HWM at denial = **437.6 GB**. Deterministic, no prompt. *(Note: the tiny slice has only one pre-denial grant; see Deliverable 3 fixture action for exercising the multi-SID fan-out.)*

### Proposed model
```python
class EpisodeWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    threshold_pct: int                 # 25 (widest); or 0 for full-lead-up fallback
    start_event_id: str | None
    hwm_bytes: int | None
    request_count: int
    label: str                         # British-English, e.g. "AvailableMCM < 25% of HWM (109.4 GB)"
```

---

## CRITICAL DELIVERABLE 3 — Attribution algorithm (D-14 / D-16 / MCM-04)

### Algorithm (port of `parse_log`, three independent dimensions)
`[CITED: analyze_dss8.py:293-394]`

Walk the events whose lines fall in the window span (`window.start_event_id … denial_event_id`, exclusive of denial). For each line containing `SUCCESS_MARKER` (`"Contract Request Succeeded"`), re-parse from `event.raw` (D-01):
- `sid = SID_RE`, `oid = OID_RE`, `size = SIZE_RE`, `source = SOURCE_RE or "Unknown"`.
- Require `sid AND oid AND size`; otherwise append to `unmatched` (surfaced in report — "nothing disappears silently").

Accumulate **three** dicts, each `key → AttributionRow`:
- `by_oid[oid]`: `granted_bytes += size`, `request_count += 1`, `event_ids += (event_id,)`, plus a `sids` set for the report's fan-out note.
- `by_source[source]`: `granted_bytes += size`, `request_count += 1`, `event_ids += (event_id,)`.
- `by_sid[sid]`: `granted_bytes += size`, `request_count += 1`, `event_ids += (event_id,)`.

**Provenance (D-16):** each row's `event_ids` is the deduped, insertion-ordered tuple of the events whose grant lines it aggregated. Since each dsserrors succeeded line is a single-line event, `event_id` = that event. This is the `cited ⊆ store` set Phase 11 will reuse verbatim.

### Proposed models
```python
class AttributionRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dimension: str                 # "oid" | "source" | "sid"
    key: str
    granted_bytes: int
    request_count: int
    event_ids: tuple[str, ...]     # D-16: owning grant-line events
    sids: tuple[str, ...] = ()     # populated for dimension="oid" (fan-out note); else empty

class Attribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    by_oid: tuple[AttributionRow, ...]
    by_source: tuple[AttributionRow, ...]
    by_sid: tuple[AttributionRow, ...]
    unmatched_event_ids: tuple[str, ...]
```
**Deterministic ordering:** within each dimension sort by `granted_bytes` desc, tie-break `key` asc. Across dimensions in the CSV: fixed order `oid`, `source`, `sid`.

### CSV schema (D-15) — one file, dimension column
`<case>/mcm/mcm_attribution.csv`, stdlib `csv.writer(f, newline="")`:

| Column | Notes |
|--------|-------|
| `episode_id` | e.g. the episode's `denial_event_id` (stable, citable) |
| `dimension` | `oid` \| `source` \| `sid` |
| `key` | the OID / Source string / SID |
| `granted_bytes` | integer (machine-independent-agnostic; the raw grant) |
| `granted_mb` | `bytes / 1024**2`, rounded deterministically (e.g. 3 dp) |
| `request_count` | integer |
| `event_ids` | `;`-joined (semicolon avoids CSV comma quoting) — D-16 |

*(Note: absolute grant sizes are legitimately absolute in the attribution CSV — the %-of-HWM machine-independence rule applies to the **diagnostic flags**, not to the attribution table, whose job is to show what actually consumed memory.)*

### Hartford SID fan-out — fixture action required
The one-OID/many-SID fan-out (OID `A3EDD9C7…` across SIDs `228F6335…`, `E6843C86…`, `FEDE6980…`, `9243DD3F…`) appears in the fixture on lines **55-61 — after the denial banner (line 28)**, so those are *recovery-phase*, not in the lead-up window. **The current slice's lead-up window has only one pre-denial grant, so SID attribution is not meaningfully exercised by it.** Planner must extend a fixture with **pre-denial** multi-SID succeeded lines (the fuller Hartford log has them) so the by-SID table resolves a real fan-out. The two-episode fixture (`hartford_two_episode_partial.log`) has pre-denial grants for episode 2 — check whether its lead-up already spans multiple SIDs; if not, add them. This is the highest-value test-data task in the phase.

---

## CRITICAL DELIVERABLE 4 — Scaled-fixture machine-independence test (success criterion #5)

### Principle
Every flag metric is a ratio `part/whole`. Multiply every absolute memory figure in a fixture by any constant `k>0` and each ratio — hence each flag tier and each displayed % — is **identical**. That is the whole proof.

### Concrete test design
1. **Build a scaled fixture deterministically.** Take `hartford_deny_slice.log` and produce `hartford_deny_scaled_half.log` by multiplying every absolute memory quantity by 0.5:
   - Format-A detail block values: `...(MB): N` → `N/2`, `...(GB): N` → `N/2` (keep integers; the reference/`to_mb` uses ints — pick `k` and figures so halved values stay integral, or scale by a factor that divides cleanly, e.g. use the *doubled* direction to stay integral: `×2` is always integral).
   - Current Memory Info byte figures (`System Total`, `System Available`, `HWM`, `Low Watermark`, `I-Server…`).
   - Succeeded-line `Size=`, `AvailableMCM=`, `HWM(PB)=` (so the window descent scales too).
   - **Recommendation:** scale by **×2** (guarantees integers) into `hartford_deny_double.log`; optionally also ×0.5 where divisible. A tiny committed generator script (or a `@pytest.fixture` transform that regex-substitutes the numeric tokens) keeps it auditable and regenerable.
2. **Assert flag-tier + %-invariance.** Run `detect_episodes` + `compute_flags` on both original and scaled fixtures; assert:
   - the tuple of `(dimension, severity, round(value_pct, 3))` is **equal** across the two runs (the flags and their displayed percentages are byte-identical);
   - the window `threshold_pct` and `request_count` are equal (window selection is HWM-relative, so it also scales).
3. **What legitimately differs:** absolute figures in the breakdown table and the attribution `granted_bytes`/`granted_mb` (they scale with `k`). The test must compare **flags/percentages**, not absolute MB — that is precisely the machine-independence claim.

### Guard
Also assert the two runs' *own* re-run is byte-identical (determinism), so the scaled test isn't masking nondeterminism. Reuse the Phase-9 `model_dump_json` run-to-run equality pattern.

---

## Validation Architecture (Critical Deliverable 5)

> nyquist_validation is enabled (config key absent = enabled). This anchor seeds VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 `[VERIFIED: codebase]` (confirmed Phase 6) |
| Config file | `pyproject.toml` (existing `[tool.pytest]`; perf tests behind `@pytest.mark.perf` excluded by addopts) |
| Quick run command | `uv run pytest tests/test_mcm.py -x` |
| Full suite command | `uv run pytest` |
| Gate | `uv run ruff check` + `uv run pyright` + `uv run pytest` all clean (project "done" definition) |

### Phase Requirements → Test Map
| Req / Criterion | Behaviour | Test Type | Automated Command | File Exists? |
|-----------------|-----------|-----------|-------------------|-------------|
| MCM-03 / Crit 1 | 5 flags emitted, each a ratio, graded info/warn/critical | unit + golden | `uv run pytest tests/test_mcm.py -k flags` | ❌ Wave 0 |
| MCM-03 / Crit 1 | Hartford lands CRITICAL (working set 65.4%), WARN (other-proc, headroom), INFO (cube, SmartHeap) | golden (calibration) | `pytest -k hartford_flags` | ❌ Wave 0 |
| MCM-04 / Crit 2 | Window auto-selected from AvailableMCM descent (25% of HWM), non-interactive | unit | `pytest -k window` | ❌ Wave 0 |
| MCM-04 / Crit 2 | Hartford always-below → window = full lead-up, no prompt | golden | `pytest -k window_hartford` | ❌ Wave 0 |
| MCM-04 / Crit 3 | Attribution by OID/Source/SID; each row carries event_ids (D-16) | unit + golden | `pytest -k attribution` | ❌ Wave 0 |
| MCM-04 / Crit 3 | one-OID/many-SID fan-out resolved by SID | golden (needs pre-denial multi-SID fixture) | `pytest -k sid_fanout` | ❌ Wave 0 (fixture) |
| MCM-05 / Crit 4 | `sift mcm <case>` writes `<case>/mcm/mcm_report.md` + `mcm_attribution.csv`; stdout summary | integration (CLI, no network) | `pytest -k mcm_command` | ❌ Wave 0 |
| MCM-05 / Crit 4 | `--format json` → `mcm_report.json`; report is deterministic | golden + determinism | `pytest -k mcm_report_json` | ❌ Wave 0 |
| Crit 5 | scaled fixture → identical flags + percentages | scaled-fixture | `pytest -k machine_independence` | ❌ Wave 0 |
| REPT-03 analogue | byte-identical report/CSV re-run (modulo timestamps) | determinism | `pytest -k mcm_determinism` | ❌ Wave 0 |
| CSV integrity | CSV loads with correct dimension rows, sorted, event_ids present | golden | `pytest -k mcm_csv` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_mcm.py -x` (+ `tests/test_mcm_report.py` once it exists).
- **Per wave merge:** `uv run pytest` (full suite) + `ruff` + `pyright`.
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] Extend `tests/fixtures/mcm/` with a **pre-denial multi-SID** lead-up (fan-out) — highest priority.
- [ ] Add scaled fixture `hartford_deny_double.log` (×2, integral) + generator/transform.
- [ ] `tests/test_mcm.py` — window/flags/attribution/scaled/determinism cases (RED first).
- [ ] `tests/test_mcm_report.py` (optional) — renderer + CSV goldens.
- [ ] No framework install needed — pytest infra exists; conftest network guard + dir-isolation fixtures are autouse.

---

## Common Pitfalls

### Pitfall 1: Attributing post-denial requests
**What goes wrong:** including succeeded lines after the denial banner (the Hartford fan-out lines 55-61) inflates attribution with recovery-phase activity.
**Why it happens:** the open/truncated episode span extends past the denial to EOF; naive "walk the episode span" includes them.
**How to avoid:** the window is `[window_start … denial)`, exclusive of denial — mirror the reference's `parse_log` stop-at-denial. Attribution consumes the *window*, not the episode span.
**Warning signs:** by-SID table shows more SIDs than pre-denial grants; totals exceed the denial-time contracted figure.

### Pitfall 2: Inverted headroom metric mis-graded
**What goes wrong:** `system_free_headroom_pct` grades downward (lower = worse), but a uniform `value ≥ critical` comparison would flag *high* headroom as critical.
**Why it happens:** the other four metrics grade upward; copy-paste of `_grade` breaks the fifth.
**How to avoid:** store as a deficit (`100 - free%`) or special-case direction in the grader; unit-test with free=50% → info and free=3% → critical.

### Pitfall 3: Non-integral scaled fixture
**What goes wrong:** ×0.5 on an odd MB value yields a non-integer the `DETAIL_LINE_RE` (`-?\d+`) won't match → the line silently drops → different flags → false test failure.
**How to avoid:** scale by ×2 (always integral) for the machine-independence fixture; assert the scaled fixture parses the same number of breakdown labels as the original.

### Pitfall 4: Phase-9 determinism test regression from new model fields
**What goes wrong:** adding `hwm_bytes`/`avail_timeline` to `McmEpisode` changes `model_dump_json`.
**Why it happens:** if any Phase-9 test pins a literal JSON string (it does not appear to — `test_determinism_byte_identical` is run-to-run), it would break.
**How to avoid:** confirm no golden-string pin before extending; the run-to-run determinism tests stay green because both runs gain the same deterministic fields.

### Pitfall 5: `Source=` regex and the denial-block `Source=` line
**What goes wrong:** the Info-Dump denial block also contains `Source= TableJoin, Handle=1, Size=45056.` (fixture line 3) — a *failed* request, not a succeeded grant.
**Why it happens:** `SOURCE_RE`/`SIZE_RE` match it, but attribution only accumulates lines containing `SUCCESS_MARKER`, so the guard is the marker check, not the regex.
**How to avoid:** only parse SID/OID/Size/Source on lines containing `"Contract Request Succeeded"` (reference does this) — the failed-request Info-Dump line is correctly excluded.

## Code Examples

### Flag computation (grading the reference heuristic)
```python
# Source: ported from docs/reference/analyze_dss8.py:507-606 (graded per D-12)
def compute_flags(ep: McmEpisode, t: McmThresholdsConfig) -> tuple[DiagnosticFlag, ...]:
    b = ep.breakdown
    flags: list[DiagnosticFlag] = []
    cite = (ep.denial_event_id,)  # breakdown parsed from the denial banner's block

    ws, virt = b.working_set_mb, b.iserver_virtual_mb
    if ws is not None and virt:
        p = ws / virt * 100
        flags.append(DiagnosticFlag(
            dimension="working_set_pct_virtual",
            severity=_grade(p, t.working_set_pct_virtual.warn, t.working_set_pct_virtual.critical),
            value_pct=round(p, 1),
            message=f"Working set is {p:.1f}% of IServer virtual memory",
            event_ids=cite,
        ))
    # ... other four dimensions, same shape; headroom uses inverted grading ...
    return tuple(flags)
```

### CSV export (deterministic, dimension-tagged)
```python
# Source: ported from docs/reference/analyze_dss8.py:477-493 (D-15 single-file, dimension column)
import csv
def write_attribution_csv(analysis: "McmAnalysis", path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["episode_id", "dimension", "key", "granted_bytes",
                    "granted_mb", "request_count", "event_ids"])
        for ep in analysis.episodes:
            attr = ep.attribution
            for rows in (attr.by_oid, attr.by_source, attr.by_sid):
                for r in rows:  # already sorted granted_bytes desc, key asc
                    w.writerow([ep.denial_event_id, r.dimension, r.key,
                                r.granted_bytes, round(r.granted_bytes / 1024**2, 3),
                                r.request_count, ";".join(r.event_ids)])
```

## State of the Art

| Old (reference script) | Current (Sift Phase 10) | Why |
|------------------------|-------------------------|-----|
| Interactive `input()` event + window prompts | Fully non-interactive, auto-widest-window | D-13; CI/scriptable; determinism |
| Flat file, line numbers | `event.raw` re-parse over stored events, `event_id` provenance | D-01/D-16; Phase-11 citation bridge |
| Binary `[WATCH]`/`[REVIEW]` flags | Graded info/warn/critical, config-overridable | D-12 |
| Source nested under OID only | Three independent dimensions (OID/Source/SID) | D-14; SID fan-out |
| Two output files, fixed names | `<case>/mcm/` bundle, `--format md\|json` + single dimension CSV | D-10/D-15 |

**Deprecated/outdated:** nothing — the reference is the source of truth being ported, not replaced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The default cut-points (40% working-set critical, 20% headroom warn, etc.) are the right calibration | Deliverable 1 | LOW — they are config-overridable (D-12) and Hartford lands sensibly; a real second case may retune. These are *defaults*, not locked policy. |
| A2 | Auto-select = the reference's Enter-default (widest, 25%-of-HWM descent) is the intended "auto" per D-13 | Deliverable 2 | LOW-MED — D-13 says "auto-selected from AvailableMCM-descent thresholds," singular algorithm; widest is the natural port. If planner/user wants a narrower default window, it's a one-constant change. Flag at plan-phase. |
| A3 | `system_available/system_total` (Current Memory Info) is the headroom metric, vs Format-A `File Cache`/free | Deliverable 1 | LOW — matches reference `_write_current_info` `[CITED: analyze_dss8.py:617-624]`. |
| A4 | Extending `McmEpisode` with two fields won't break a pinned Phase-9 golden JSON | Runtime State Inventory / Pitfall 4 | LOW — Phase-9 determinism tests are run-to-run; verify no literal-string pin before editing (RED step catches it). |
| A5 | `granted_bytes` in the attribution CSV may be absolute (machine-independence rule applies only to flags) | Deliverable 3 | LOW — the attribution table's purpose is actual consumption; the ROADMAP criterion #5 is scoped to *flags*. |

**These are LOW-risk and mostly self-correcting (config-overridable or RED-test-caught). No blocking assumptions.**

## Open Questions

1. **Which fixture carries the pre-denial multi-SID fan-out for the by-SID golden?**
   - What we know: the slice's fan-out is post-denial; the two-episode fixture has episode-2 pre-denial grants.
   - What's unclear: whether episode-2's lead-up already spans ≥2 SIDs.
   - Recommendation: at plan-phase, grep the two-episode fixture's episode-2 lead-up for distinct `[SID:...]`; if <2, add pre-denial multi-SID lines from the real fuller Hartford log. This is a fixture task, not an algorithm risk.

2. **`episode_id` value for the CSV/report.**
   - What we know: episodes have no stable ordinal; `denial_event_id` is stable and citable.
   - Recommendation: use `denial_event_id` as `episode_id` (also serves Phase-11 citation). Planner's call per Claude's Discretion.

## Environment Availability

> Purely code/config changes with no external tools/services. Per Step 2.6 skip rule: **SKIPPED (no external dependencies)** — the phase uses only the existing Python venv, stdlib `csv`, and already-installed Pydantic/Typer.

## Security Domain

> `security_enforcement` default (absent = enabled). This phase reads a local SQLite case store and writes derived files into the case directory; it takes no network input and executes no model. The relevant surface is **untrusted log content flowing into a report/CSV**.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation / Output Encoding | **yes** | Log text (`Source=`, SID/OID, raw lines) is attacker-influenced. The Markdown renderer MUST pass every rendered field through the existing `render/_util.sanitise` + `_field` escaping (WR-01/WR-04/T-06-01) exactly as `render/markdown.py` does — hostile log bytes must not inject Markdown structure or HTML. The CSV writer MUST use `csv.writer` (not manual join) so embedded delimiters/quotes/newlines are quoted, preventing CSV-injection/row-break. Consider prefixing formula-triggering leading chars (`= + - @`) in `key` cells if the CSV is opened in a spreadsheet (CSV-formula-injection) — low risk here (keys are hex IDs / known Source names) but note it. |
| V12 File / Resource | yes | `<case>/mcm/` writes stay inside the resolved case dir; reuse the existing case-dir resolution in `cli.py`; do not follow user-supplied paths outside it. |
| V2/V3/V4 Auth/Session/Access | no | Local single-user CLI, no auth surface. |
| V6 Cryptography | no | No crypto beyond the existing `event_id` sha256 (unchanged). |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Markdown/HTML injection via hostile log text into report | Tampering | Existing `sanitise` + `_field` escaping + fenced-code raw (render/markdown.py precedent) |
| CSV injection / row-break via `Source=`/raw fields | Tampering | stdlib `csv.writer` quoting; optional leading-`=+-@` guard on `key` cells |
| Path traversal on output write | Tampering | Write only inside resolved `<case>/mcm/` |
| ReDoS on ported regexes | DoS | Regexes are anchored/linear with required terminators (Phase-9 already vetted; reuse, don't rewrite) |

## Sources

### Primary (HIGH confidence)
- `docs/reference/analyze_dss8.py` (vendored reference) — `prescan` (112-238), `parse_log`/attribution (293-394), `write_report`/CSV (401-493), flag heuristics + `THRESHOLDS` (79-85, 507-606), `prompt_window` (678-773) — the ported algorithms.
- `src/sift/pipeline/mcm.py` (Phase 9) — `detect_episodes`, `McmEpisode`/`MemoryBreakdown`/`LifecycleSignal`, ported regex constants, typed accessors — the input contract.
- `tests/fixtures/mcm/hartford_deny_slice.log` — real denial-time figures (calibration anchors), verified this session.
- `.claude/CLAUDE.md` "Technology Stack" — stack + no-new-deps constraint.
- ISPerfDiag SKILL (`~/.claude/skills/ISPerfDiag/`) — HWM/Low Watermark semantics, SmartHeap releasable meaning, working-set spill mechanism, MMF healthy-when-in-use, cohabitation (other-processes) diagnosis, <20% memory-status-low semantics — domain justification for cut-points.

### Secondary (MEDIUM confidence)
- Phase-9 & Phase-10 CONTEXT.md / DISCUSSION-LOG.md — locked decisions D-01…D-16.
- ROADMAP.md Phase 10 — 5 success criteria.

### Tertiary (LOW confidence)
- None — no WebSearch used; this phase is fully internal (port + calibration against committed real data).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all patterns exist in the codebase.
- Architecture/algorithms: HIGH — direct port of a validated reference over Phase-9 models.
- Threshold cut-points: MEDIUM-HIGH — calibrated against real Hartford figures and the reference's already-tuned numbers + ISPerfDiag domain semantics; config-overridable so low blast radius.
- Scaled-fixture / determinism: HIGH — machine-independence is a mathematical property of ratio-based flags.

**Research date:** 2026-07-19
**Valid until:** stable (internal port; no external moving parts) — revisit only if a second real case retunes thresholds.
