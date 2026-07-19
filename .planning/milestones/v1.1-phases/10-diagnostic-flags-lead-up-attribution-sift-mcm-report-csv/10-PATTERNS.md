# Phase 10: Diagnostic Flags, Lead-Up Attribution & `sift mcm` Report + CSV - Pattern Map

**Mapped:** 2026-07-19
**Files analyzed:** 6 (4 code, 2 test/fixture)
**Analogs found:** 6 / 6 (all in-repo; this is a port over existing patterns, no greenfield)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/pipeline/mcm.py` (EXTEND: window/flags/attribution models + pure fns; +`hwm_bytes`/`avail_timeline` on `McmEpisode`) | pipeline (pure compute) | transform / batch | `src/sift/pipeline/mcm.py` (Phase-9 self), `docs/reference/analyze_dss8.py:293-394,678-773` | exact |
| new frozen models (`DiagnosticFlag`, `EpisodeWindow`, `AttributionRow`, `Attribution`, `McmAnalysis`) — in `mcm.py` | model | — | `mcm.py:105-188` (`LifecycleSignal`/`MemoryBreakdown`/`McmEpisode`) | exact |
| `src/sift/render/mcm_report.py` (NEW: `render_mcm_markdown`/`render_mcm_json` + `write_attribution_csv`) | renderer | transform (→str/→file) | `src/sift/render/markdown.py`, `src/sift/render/json_out.py` | role+flow match |
| `src/sift/config.py` (EXTEND: `McmThresholdsConfig`, `[mcm.thresholds]`) | config | — | `config.py:23-106` (`GenerationConfig`/`SiftConfig`/`_ENV_SCALARS`) | exact |
| `src/sift/cli.py` (EXTEND: `@app.command() def mcm(...)`) | route/command (only I/O tier) | request-response (CLI) | `cli.py:908-991` (`report`), `cli.py:96-113` (`_case_store`) | exact |
| `tests/test_mcm.py` (EXTEND) + `tests/test_mcm_report.py` (NEW opt) + `tests/fixtures/mcm/` | test / fixture | — | `tests/test_mcm.py:36-58,176-193` | exact |

## Pattern Assignments

### `src/sift/pipeline/mcm.py` — window / flags / attribution (pipeline, transform)

**Analog:** Phase-9 self + `docs/reference/analyze_dss8.py`. Module is typer-free, print-free, SQL-free, I/O-free (docstring lines 1-24) — new functions MUST keep that. Regex constants already ported at `mcm.py:41-53` (`SID_RE`, `OID_RE`, `SIZE_RE`, `SOURCE_RE`, `AVAIL_MCM_RE`, `HWM_RE`, `SUCCESS_MARKER`, `DENIAL_MARKER`) — **reuse, do not redefine**.

**Frozen-model idiom to copy** (`mcm.py:105-114`):
```python
class LifecycleSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: str
    event_id: str
    ts: str | None
    text: str
```
Apply verbatim shape to `DiagnosticFlag`, `EpisodeWindow`, `AttributionRow`, `Attribution`, `McmAnalysis` (RESEARCH §Deliverable 1/2/3 give exact fields). Every model carries `event_id`(s) for D-16 provenance — mirror how every Phase-9 signal keeps its owning id.

**Typed accessors already exist** on `MemoryBreakdown` (`mcm.py:131-171`): `working_set_mb`, `iserver_virtual_mb`, `cube_caches_mb`, `mmf_mb`, `smartheap_unused_pool_mb`, `other_processes_mb`, `physical_total`. `compute_flags` reads these directly — do NOT re-extract from `raw_map`. Each returns `float | None`; guard `None`/zero-denominator before dividing (RESEARCH Code Example lines 438-454).

**Model extension** — add to `McmEpisode` (`mcm.py:174-188`), populated in `detect_episodes` (`mcm.py:446-485`):
```python
hwm_bytes: int | None
avail_timeline: tuple[tuple[str, int, int], ...]  # (event_id, available_mcm_bytes, hwm_bytes)
```
Build `avail_timeline` in the existing `detect_episodes` loop by walking `stream[ep.span_start … denial_idx-1]`, matching `SUCCESS_MARKER` lines and pulling `AVAIL_MCM_RE`/`HWM_RE` — carry `stream[i][1]` (event_id) not line number (RESEARCH Deliverable 2). `hwm_bytes = avail_timeline[-1][2] if avail_timeline else None`.

**Window port** of `prompt_window` (`analyze_dss8.py:678-773`), minus `input()`: only the widest threshold (25% of HWM = `WINDOW_THRESHOLDS_PCT[0]`, the Enter-default `options[0]`). Last-crossing-downward logic; always-below ⇒ first timeline entry (Hartford case). Return `EpisodeWindow`, event_id-based not lineno.

**Attribution port** of `parse_log` (`analyze_dss8.py:293-394`) — but **three independent top-level dicts** `by_oid`/`by_source`/`by_sid` (reference nests source under oid). Walk `[window.start_event_id … denial)` exclusive; only lines containing `SUCCESS_MARKER`; require `sid AND oid AND size` else append to `unmatched` ("nothing disappears silently"). Insertion-ordered dicts / `dict.fromkeys` for event_id dedup — **never `set` iteration in ordered output** (`mcm.py:466-470` shows the `dict.fromkeys` idiom already in use). Sort each dimension `granted_bytes` desc, tie-break `key` asc.

---

### `src/sift/render/mcm_report.py` (renderer, transform)

**Analog:** `render/markdown.py` (MD) + `render/json_out.py` (JSON) + `render/_util.py` (sanitise).

**Security-critical — every log-sourced field MUST route through `_field`** (`markdown.py:52-68`): hostile `Source=`/SID/OID/raw bytes are attacker-controlled (RESEARCH §Security V5). Reuse `sanitise` from `render/_util.py` and the `_escape`/`_field`/`_fence` helpers — either import or mirror. Table cells must escape `|` (`markdown.py:172-189` cluster table shows the pattern):
```python
lines.append(f"| {c.cluster_id} | {c.count} | {_field(c.severity_max)} | {_field(name)} |")
```

**Renderer signature = pure `→str`, no store re-read, no recompute** (`markdown.py:192` / `json_out.py:49`). Phase-10 renderer takes the already-computed `McmAnalysis` (not the store): `render_mcm_markdown(analysis: McmAnalysis) -> str`. Layout order is D-11: timeline → flags → breakdown table → 3 attribution tables per episode.

**JSON determinism idiom** (`json_out.py:82`): `json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"`. `ensure_ascii=True` neutralises C1/Cf terminal-injection bytes — keep it.

**CSV writer** (NEW, stdlib only) — RESEARCH Code Example lines 458-473 is the target shape:
```python
with path.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["episode_id","dimension","key","granted_bytes","granted_mb","request_count","event_ids"])
    ...  # rows already sorted; event_ids ";"-joined (semicolon avoids CSV comma-quoting)
```
`newline=""` is mandatory (correct quoting). `episode_id = ep.denial_event_id` (stable/citable, RESEARCH Open Q2). Note: absolute `granted_bytes` is legitimately absolute here — the %-of-HWM machine-independence rule applies to **flags only**, not attribution.

---

### `src/sift/config.py` — `McmThresholdsConfig` (config)

**Analog:** `config.py:23-34` (`GenerationConfig`) + `SiftConfig` (67-76) + `_ENV_SCALARS` (96-106).

```python
class McmThresholdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")   # typo'd key fails loudly (T-04-02)
    working_set_pct_virtual: ... = ...   # defaults = RESEARCH Deliverable 1 table
```
Register on `SiftConfig` as `mcm: McmThresholdsConfig = McmThresholdsConfig()` (mirrors `generation`/`embeddings`/`clustering` at 74-76). Absent `[mcm.thresholds]` block ⇒ documented-constant defaults. Nested per-dimension `{warn, critical}` mappings stay **TOML/flag-only** like `timezones`/`adapters` (config.py:72-73,93-95) — do NOT add them to `_ENV_SCALARS` (that's scalars only); a scalar like a global on/off could be added there if wanted. **Inverted-metric caveat:** `system_free_headroom_pct` grades downward — special-case direction or store as `100 - free%` (RESEARCH Pitfall 2).

---

### `src/sift/cli.py` — `@app.command() def mcm` (command, only I/O tier)

**Analog:** `report` (`cli.py:908-991`) for the whole shape; `_case_store` (96-113); `ReportFormat` StrEnum (899-905).

**Copy:**
- `class McmFormat(StrEnum): md="md"; json="json"` (mirror `ReportFormat` 899-905 — an unknown value is Typer exit 2).
- Signature `def mcm(case: str, fmt: Annotated[McmFormat, typer.Option("--format", ...)] = McmFormat.md, data_dir: DataDirOption = None)` — `DataDirOption` alias exists (90-93).
- `config = load_config({"data_dir": data_dir})` then `store = _case_store(case, config)` (929-930) — `_case_store` handles missing-case exit 1 and sanitises sqlite errors.
- `try: … finally: store.close()` (WAL checkpoint, 989-991).
- Query read-only: `store.query_events()` → `detect_episodes(...)` → pure pipeline → renderer → writes.
- **File writes are the ONLY thing this tier does** that pipeline/render don't. Create `<case>/mcm/` under the resolved case dir (derive from `case_db_path(config.data_dir, case).parent` — do NOT follow user paths outside it, RESEARCH §Security V12). Write `mcm_report.md`/`.json` per `--format` + always `mcm_attribution.csv`, then print short stdout summary (episode count, top flags).
- OSError on write ⇒ `print(f"Error: cannot write … {_sanitise(str(exc))}")` + `raise typer.Exit(1)` (985-986 pattern). `_sanitise` imported as at `cli.py:40`.

---

### `tests/test_mcm.py` (extend) + `tests/fixtures/mcm/` + `tests/test_mcm_report.py` (new, optional)

**Analog:** `tests/test_mcm.py:36-58` (`_episodes_from_fixture` ingest-through-real-adapter helper), `:176-193` (byte-identical determinism via `model_dump_json`).

**Fixture-load idiom to reuse** (`test_mcm.py:50-57`): `DsserrorsAdapter().parse(FIXTURES/rel) → CaseStore(tmp_path/"case.db").insert_events → query_events → detect_episodes`. New tests call `compute_flags`/`select_window`/`attribute_window` on top of that.

**Determinism idiom** (`test_mcm.py:185-186`): `first = [e.model_dump_json() ...]; second = [...]; assert first == second`. Reuse for the new models. Pitfall 4: confirm no Phase-9 test pins a literal JSON string before adding `hwm_bytes`/`avail_timeline` (grep confirms tests are run-to-run, not golden-string — safe).

**New fixtures required (RESEARCH Deliverable 3/4):**
1. **Pre-denial multi-SID lead-up** fixture (highest priority) — the slice's fan-out (lines 55-61) is *post-denial* so by-SID isn't exercised. Add pre-denial multi-SID succeeded lines from the fuller Hartford log (or check `hartford_two_episode_partial.log` episode-2 lead-up spans ≥2 SIDs).
2. **Scaled fixture** `hartford_deny_double.log` — every absolute MB/byte token ×2 (guarantees integers; ×0.5 risks non-integral drop through `DETAIL_LINE_RE`, Pitfall 3). Machine-independence assert: `(dimension, severity, round(value_pct,3))` tuple + window `threshold_pct`/`request_count` **equal** across original and scaled runs (flags/percentages invariant; absolute breakdown/`granted_bytes` legitimately differ).

## Shared Patterns

### Frozen typed models
**Source:** `src/sift/pipeline/mcm.py:105-114`, `src/sift/config.py:23-27`
**Apply to:** every new model + config class
`model_config = ConfigDict(frozen=True, extra="forbid")` (models) / `ConfigDict(extra="forbid")` (config). Type hints everywhere; British English in any user-facing string (flag messages, report headings, window labels).

### Determinism discipline
**Source:** `mcm.py:20-24, 466-470`; `json_out.py:82`
**Apply to:** pipeline output, renderer, CSV
Insertion-ordered dicts / `dict.fromkeys`; never `set` iteration in ordered output (a bare `set` in row order is non-deterministic; `sorted(...)` is fine). Sort attribution `granted_bytes` desc, key asc.

### Field sanitisation / escaping (security)
**Source:** `src/sift/render/_util.py:11-30` (`sanitise`), `src/sift/render/markdown.py:52-68` (`_escape`/`_field`)
**Apply to:** every log-sourced field in the MD report; CSV relies on `csv.writer` quoting (never manual join). Optional leading-`=+-@` guard on CSV `key` cells (CSV-formula-injection, low risk — keys are hex/known Source names).

### event_id provenance (D-16, cited ⊆ store)
**Source:** `mcm.py` docstring lines 6-9; every Phase-9 signal keeps its owning id
**Apply to:** every attribution row (`event_ids` tuple), every flag (`event_ids=(ep.denial_event_id,)`), window (`start_event_id`). This is the Phase-11 citation bridge — non-negotiable.

### CLI command lifecycle
**Source:** `cli.py:96-113` (`_case_store`), `:929-991` (`report` body + `finally: store.close()`)
**Apply to:** `sift mcm` — load_config → _case_store → try/finally close → sanitise all error text → Typer exit codes (1 = missing case / IO failure, 2 = bad `--format`).

## No Analog Found

None. Every target has a close in-repo analog — this phase is a faithful port of `docs/reference/analyze_dss8.py` over Phase-9 typed models plus mirrors of the existing render/config/cli/test patterns. No RESEARCH-only fallback patterns needed.

## Metadata

**Analog search scope:** `src/sift/pipeline/`, `src/sift/render/`, `src/sift/config.py`, `src/sift/cli.py`, `tests/`, `docs/reference/analyze_dss8.py`, `tests/fixtures/mcm/`
**Files scanned:** 8 read in full/targeted; reference functions `parse_log` (293-394) and `prompt_window` (678-773) extracted
**Pattern extraction date:** 2026-07-19
