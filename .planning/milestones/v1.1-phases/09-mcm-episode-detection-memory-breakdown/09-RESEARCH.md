# Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown - Research

**Researched:** 2026-07-19
**Domain:** Deterministic log-forensics port (no LLM, no network, no new deps) over stored `dsserrors` events
**Confidence:** HIGH (every marker, regex, and label below was verified against the real Hartford deny log and the live repo source in this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01: Read ingested `Event` rows from the store; re-parse MCM tokens from `event.raw` inside the new analyser.** Adapter untouched. Re-apply the reference regexes (`AvailableMCM=`, `HWM(...)=`, `Size=`, `Source=`, `SID`, the denial banner, `State=normal`, the memory-dump detail block) to `event.raw`. Rationale: keeps every episode signal mapped to a real `event_id` (the load-bearing citation path for Phase 11: `cited ⊆ prompted ⊆ store`). Rejected: adapter enrichment (touches near-frozen adapter, forces re-ingest); raw-file re-parse from disk (line numbers, no `event_id` — a citation dead-end).
- **D-02: Pin the exact lifecycle marker strings by research against the real Hartford deny log.** The three lifecycle signal types (memory-status-low handler, emergency working-set offload, recovery) are captured as **episode annotations that reference the `event_id`** of the line that carries them, within the episode's line span.
- **D-03: Tolerate absence.** A given episode/log may not contain all three signals (Hartford has **no** `State=normal`). Missing signals recorded as absent, never fabricated, never crash or drop an episode.
- **D-04: Hybrid memory model — faithful verbatim map + typed named accessors.** Retain the full `label → (value_mb, unit)` map exactly as parsed AND expose typed accessors for known components (physical total/IServer/other; virtual IServer; cube caches; cube index/growth; MMF; working set; SmartHeap unused pool; other memory; plus `Current Memory Info` and `MCM Settings` blocks). Accessors tolerate label drift via the reference's fuzzy `_get(substr)` lookup. Rejected: typed-fields-only (brittle); verbatim-map-only (forces every consumer to string-match).
- **D-05: Pure deterministic function over stored events — no new store table in Phase 9.** Analyser computes episodes on demand; Phase 10/11 call the same function. Determinism inherent (no model). Avoids migration, write path, cache-staleness.
- **D-06: Order events by UTC `ts` across source files (multi-node safe).** Walk dsserrors events in UTC-ts order (tie-break `source_file`, then `line_start`). An MCM dump block fragmented across a rotation boundary (per ADR 0006, adapter never stitches across `.bak` siblings) is **flagged fragmented/partial**, not silently merged. Hartford is single-file so this is a design guard.
- **D-07: Open/truncated episodes are first-class.** A log ending mid-episode with no recovery line (Hartford) is reported **open/truncated** with `recovery=None`, distinct from an implicit-recovery close — never dropped, never crashed.

### Claude's Discretion
- Module placement and naming (expected: new `src/sift/pipeline/mcm.py` analyser + typed models, mirroring `pipeline/salience.py`), the exact typed-model field set, and the internal regex/parse structure — planner/executor's call provided D-01…D-07 hold.
- No public CLI surface required in Phase 9 (the `sift mcm` command is Phase 10). A thin internal entry point + tests is sufficient.

### Deferred Ideas (OUT OF SCOPE)
- Diagnostic flags, lead-up window selection, per-OID/Source/SID attribution, the `sift mcm` command, CSV export → **Phase 10** (MCM-03/04/05).
- Feeding MCM facts into `sift analyze`, the MCM golden eval case → **Phase 11** (MCM-06/07).
- Adapter enrichment (MCM tokens as attrs at ingest) — considered and **rejected** (D-01).
- Persisting episodes to a store table — considered and **rejected** (D-05).
- DSSPerformanceMonitor CSV time-series correlation (PERF-01) — deferred to v2 (SEED-001).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCM-01 | Deterministic, non-interactive detection of every distinct denial episode, bounded by denial banner and recovery (`State=normal`, resumed contract activity, or `AvailableMCM` climbing back), capturing full lifecycle signals (`memory-status-low`, emergency working-set offload, recovery) as episode context | Ported `prescan()` (validated below) + exact lifecycle marker strings pinned against Hartford (§Lifecycle Markers). Hartford = exactly 1 open/truncated episode. |
| MCM-02 | Parse the denial-time memory breakdown (physical/virtual split, cube caches, cube growth/index, MMF, SmartHeap pool, working set, other memory) and MCM settings from the memory-dump block | Ported `parse_detail_block()` + `parse_abbrev_block()` + `_get()` fuzzy accessor (validated: all 23 denial-block labels + 4 MCM-settings labels present in Hartford, §Memory Breakdown). |
</phase_requirements>

## Summary

Phase 9 is a **port, not a research problem**: the entire deterministic algorithm already exists in `/home/oliverh/Downloads/analyze_dss8.py`. The task is to lift `prescan()` (episode detection), `parse_detail_block()` / `parse_abbrev_block()` (memory breakdown), `_get()` (fuzzy label lookup), and the regex/marker constants into a new `src/sift/pipeline/mcm.py` that reads stored `Event` rows instead of a flat file, and to **extend** it with lifecycle-signal capture (D-02) and open/truncated handling (D-07). Everything is stdlib (`re`, `dataclasses`/Pydantic already in deps) — **no new packages**.

I validated every marker string, every regex, and every memory-breakdown label against the **real Hartford deny log** (`hartford_linux_deny_.log`, 6517 lines) and against the live `src/sift/` source. Three findings materially shape the plan and are the highest-value output of this research:

1. **Two distinct memory-dump formats coexist in the real log.** The *denial-time* breakdown (the banner + tab-indented detail block, 1 occurrence) is a different shape from the 107 *Info Dump* blocks that carry `Current Memory Info:` / `MCM Settings:`. The reference script's forward-scan for MCM Settings *after* the denial line finds **nothing** on Hartford (all Info Dumps precede the banner) — a real gap the port must close.
2. **The dsserrors adapter does NOT group Hartford's Info Dump blocks into single events**, because its `_MCM_START` sentinel expects a *standalone* `***** Start of Info Dump *****` line, but Hartford embeds that marker inside a timestamped `Contract Request Failed. ***** Start of Info Dump *****.` line. D-01 (re-parse `event.raw`) still works, but the analyser must NOT assume Info Dumps are pre-grouped MCM events — it scans event raws for the markers.
3. **The candidate lifecycle marker `memory-status-low` is not a literal in the log.** The real anchors are `Memory status changes to low (...)` (`ContractManagerImplSH.cpp:81`) and `MsiSessionManager::MemoryStatusHandler() : ...` (`MsiSessionManager.cpp:2608/2638/2645`). Pinned verbatim below.

**Primary recommendation:** Reconstruct a `(line_text, event_id, source_file)` stream by iterating `store.query_events()` filtered to `source == "dsserrors"` (already emitted in UTC `ts`, `source_file`, `line_start` order — exactly D-06) and splitting each `event.raw` on newlines; run the ported `prescan`/parsers over that stream, tagging every detected signal with its owning `event_id`. Model the output as a frozen Pydantic `MemoryBreakdown` (verbatim map + typed accessors, D-04) and `McmEpisode` (open/truncated first-class, D-07), mirroring `pipeline/salience.py`'s pure-function-over-stored-rows shape.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read stored dsserrors events (ordered) | Store (`store.query_events`) | — | D-01/D-05: read-only, no new schema; ordering already done in SQL |
| Reconstruct line stream from `event.raw` | Pipeline (`pipeline/mcm.py`) | — | D-01: MCM tokens live in verbatim `raw`, not attrs |
| Episode detection (`prescan` port) | Pipeline | — | Pure function, deterministic, no I/O — mirrors `salience.rank_clusters` |
| Memory-breakdown parse (`parse_*` port) | Pipeline | — | Pure text→typed-model transform |
| Typed episode/breakdown models | Models layer (`pipeline/mcm.py` local or `models.py`) | — | Additive; must follow frozen/`extra="forbid"` convention |
| CLI surface / report / CSV | **NONE THIS PHASE** | Phase 10 | Explicitly deferred (D-05, CONTEXT) |
| Citation feed into analyze | **NONE THIS PHASE** | Phase 11 | Deferred; but `event_id` provenance is preserved now so Phase 11 works |

## Project Constraints (from CLAUDE.md / .claude/CLAUDE.md)

- **Boring tech only** — stdlib (`re`), Pydantic (already a dep), frozen dataclasses. No new dependency needs justification because none is required.
- **Determinism invariant** — identical case + config → byte-identical output. No sets in ordered output; rely on insertion-ordered dicts and the SQL `ORDER BY`.
- **"Nothing disappears silently"** — unparseable/absent regions recorded, never dropped (drives D-03/D-07 and the `Memory Reserve = 0 (0Bytes)` regex fix below).
- **Type hints everywhere; British English** in docs/user-facing strings; **Apache-2.0**.
- **Only `llm/` talks HTTP** — this module makes zero network calls; tests need no fake server.
- **"Done" = `ruff check` + `pyright` + `pytest` all clean** (strict pyright). TDD: RED (failing test committed) → GREEN → gate → docs, per atomic commit.
- **Prompts are versioned files** — N/A this phase (no prompts).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `re` (stdlib) | — | All token/marker/block regexes | Reference already uses it; adapter's ReDoS-safe anchored-scan discipline applies [CITED: src/sift/adapters/dsserrors.py:50] |
| `dataclasses` (stdlib) or `pydantic` | Pydantic 2.13.x (already a dep) | Typed episode/breakdown models | Repo uses BOTH: frozen `@dataclass` for `Event`, `BaseModel(extra="forbid")` for `Hypothesis` [VERIFIED: src/sift/models.py] |

**No installation required.** This phase adds zero packages.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pydantic `BaseModel(frozen=True, extra="forbid")` for episode models | Frozen `@dataclass` | Pydantic gives `model_dump_json()` for Phase 11 feed + validation; dataclass is lighter. Recommend Pydantic to match the `Hypothesis` convention and because Phase 11 will serialise these — but either honours D-04. |
| Parse the tab-indented denial detail block (Format A) | Parse the JSON `memoryBreakdown` blob (line 6360) | The JSON blob (§Format C below) is a complete structured alternative but is a *separate later event*, uses different keys, and is NOT what the reference parses. Stick with the reference's Format-A detail block for a faithful port; note the JSON as a future robustness option, do not build it now (YAGNI). |

## Package Legitimacy Audit

**N/A — this phase installs no external packages.** The analyser is pure stdlib `re` plus Pydantic/dataclasses already vendored in `pyproject.toml` since Phase 1. No registry lookup needed; nothing to flag.

## The Port: What to Keep, Extend, and Discard

Source: `/home/oliverh/Downloads/analyze_dss8.py` (read in full this session). **Planning action (from CONTEXT):** vendor a copy into the repo (`docs/reference/analyze_dss8.py`) so provenance is durable and citable.

### KEEP verbatim (validated against Hartford — see §Regex/Marker Constants)
| Symbol | Lines | Role |
|--------|-------|------|
| `TIMESTAMP_RE, SID_RE, OID_RE, SIZE_RE, SOURCE_RE, AVAIL_MCM_RE, HWM_RE` | 38–44 | Token regexes |
| `SUCCESS_MARKER, DENIAL_MARKER, NORMAL_MARKER, CURRENT_INFO_MARKER, MCM_SETTINGS_MARKER` | 46–50 | Marker substrings |
| `DETAIL_LINE_RE` | 55 | Tab-indented `Label(UNIT): value` detail lines |
| `ABBREV_LINE_RE` | 58–61 | `Label = value (human UNIT)` abbreviated lines |
| `UNIT_TO_MB, to_mb()` | 63–66 | Unit normalisation to MB |
| `prescan()` | 112–238 | **Episode detection** — same-burst collapse, implicit recovery, open-episode-at-EOF |
| `parse_detail_block()` | 247–267 | Denial-time breakdown (Format A) |
| `parse_abbrev_block()` | 270–286 | Current Memory Info + MCM Settings (Format B) |
| `_get(data, substr)` | 500–504 | **Fuzzy label lookup** — the D-04 typed-accessor mechanism |

### EXTEND (new in Phase 9, on top of the reference)
- **Lifecycle-signal capture (D-02):** the reference `prescan` tracks only denial / `State=normal` / `Succeeded`. Add detection of the memory-status-low, memory-status-critical, and emergency-offload markers (pinned below), each recorded as an annotation referencing the owning `event_id`.
- **Event-stream input adapter (D-01):** replace file `readlines()` with a reconstruction from `store.query_events()` that carries `event_id` per line (see §Architecture Patterns).
- **Open/truncated flagging (D-07):** the reference already emits an open episode at EOF with `recovery_lineno=None`; surface it explicitly as `open_truncated=True` on the typed model and never crash when the detail block / MCM Settings are absent (D-03).
- **Denial-time MCM Settings association fix:** the reference scans *forward* from the denial line for `MCM Settings:` — on Hartford that finds nothing (all Info Dumps precede the banner). Associate the **nearest Info Dump block within the episode span** instead (see Open Questions Q1).
- **`Memory Reserve = 0 (0Bytes)` regex fix:** widen `ABBREV_LINE_RE` so the `Bytes` unit is not silently dropped ("nothing disappears").
- **Fragmentation flag (D-06):** if a denial event's detail block is empty and the next dsserrors event is a different `source_file`, mark `fragmented=True`.

### DISCARD (Phase 10, do NOT port now)
`prompt_event()` (645), `prompt_window()` (678), `WINDOW_THRESHOLDS_PCT` (76), `THRESHOLDS` (79–85), the per-OID/Source/SID attribution inside `parse_log()` (`oid_size`/`oid_sources`/`oid_sids`, 293–394), `write_report()`/CSV (401–493), all `_write_*` diagnostic-flag logic (507–638), and `main()` (780–840). These are diagnostic flags, window selection, attribution, and reporting — all Phase 10/11.

## Regex/Marker Constants — VERIFIED against Hartford

Every pattern below was run against `/home/oliverh/Downloads/hartford/hartford_linux_deny_.log` this session.

| Constant | Pattern / string | Hartford evidence | Status |
|----------|------------------|-------------------|--------|
| `DENIAL_MARKER` | `IServer enters MCM denial state` | line 5843, 1 occurrence | [VERIFIED] |
| `SUCCESS_MARKER` | `Contract Request Succeeded` | 2932 occurrences | [VERIFIED] |
| `NORMAL_MARKER` | `State=normal` | **0 occurrences** (D-07 path) | [VERIFIED absent] |
| `CURRENT_INFO_MARKER` | `Current Memory Info:` | 107 occurrences (line 5820 nearest pre-denial) | [VERIFIED] |
| `MCM_SETTINGS_MARKER` | `MCM Settings:` | 107 occurrences (real line has trailing space `MCM Settings: `; `in`-substring match unaffected) | [VERIFIED] |
| `AVAIL_MCM_RE` | `\bAvailableMCM=(\d+)` | `AvailableMCM=15626096055` | [VERIFIED] |
| `HWM_RE` | `\bHWM\(\w+\)=(\d+)` | `HWM(PB)=468400222208` (`\w+` matches `PB`) | [VERIFIED] |
| `SIZE_RE` | `\bSize=(\d+)` | `Size=12124160` | [VERIFIED] |
| `SOURCE_RE` | `\bSource=([\w:]+)` | `Source=GovernedObject`, `Source=CDSSXTabColumn::SetWorkingBuffer` (matches `::`) | [VERIFIED] |
| `SID_RE` | `\[SID:(0|[A-Fa-f0-9]{32})\]` | `[SID:2AB16B9C8C7F809EC1028D3907DA0B0D]` and `[SID:0]` | [VERIFIED] |
| `OID_RE` | `\[OID:(0|[A-Fa-f0-9]{32})\]` | `[OID:A3EDD9C7A24367D7CBEA259E1A9A91C0]` | [VERIFIED] |
| `DETAIL_LINE_RE` | `^\t*(.+?)\((GB|MB|KB)\):\s*(-?\d+)\s*$` | matches lines 5844–5866 (tab-indented) | [VERIFIED] |
| `ABBREV_LINE_RE` | `^([A-Za-z][A-Za-z0-9 /\-]*?)\s*=\s*(unlimited|true|false|-?\d+)\s*(?:\(([\d.]+)\s*(TB|GB|MB|KB)\))?\s*$` | matches lines 5821–5833, 5835/5837/5838 — **FAILS on `Memory Reserve = 0 (0Bytes)` (5836)** | [VERIFIED + 1 gap] |

**Note on `SID_RE`/`OID_RE` vs the adapter:** the reference's bracketed `[SID:...]`/`[OID:...]` forms are the correct fit for Hartford. The adapter's own `_SID_RE = \bSID[=:]\s*([0-9A-Fa-f]{12,})` also happens to match the bracketed 32-hex, but the analyser re-parses `event.raw` (D-01) and should use the reference's precise bracketed forms. Confirms [ASSUMED→now VERIFIED] the Hartford bracket-token format noted in prior project memory.

**Note on `TIMESTAMP_RE`:** the reference uses a space-separated stamp `^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)` which matches Hartford (`2026-04-07 12:39:47.230`). The analyser mostly does not need it: after D-01 reconstruction, each event's `ts` is already parsed by the adapter, and only the *first* physical line of an event is timestamped (the rest are continuation). Use `event.ts` for ordering/annotation timestamps rather than re-matching.

## Lifecycle Markers (D-02) — PINNED verbatim against Hartford

This is the highest-value research output. The reference script does **not** capture these; Phase 9 adds them. Each string below is an exact substring quoted from the real log with its line number and `.cpp` anchor.

| Signal kind | EXACT verbatim substring (anchor for detection) | Line | `.cpp` anchor | Timing |
|-------------|--------------------------------------------------|------|---------------|--------|
| **denial banner** | `IServer enters MCM denial state` | 5843 | `MSIServerStateLogger.cpp:964` | episode start |
| **memory-status-critical** (handler, pre-denial) | `MsiSessionManager::MemoryStatusHandler() : Memory status is critical` | 4262 | `MsiSessionManager.cpp:2608` | before denial |
| (handler no-op, pre-denial) | `MsiSessionManager::MemoryStatusHandler() : Do nothing since MCM denial will block working set serialization` | 4263 | `MsiSessionManager.cpp:2621` | before denial |
| **memory-status-low** (MCM banner) | `Memory status changes to low (available memory is less than 20% of total memory but memory contract manager is still accepting requests)` | 5878 | `ContractManagerImplSH.cpp:81` | after denial (same episode) |
| **memory-status-low** (handler) | `MsiSessionManager::MemoryStatusHandler() : Memory status is low` | 5879 | `MsiSessionManager.cpp:2608` | after denial |
| **emergency offload — start** | `MsiSessionManager::MemoryStatusHandler() : Initiating emergency memory offload for Working Set due to low memory` | 5880 | `MsiSessionManager.cpp:2638` | after denial |
| **emergency offload — complete** | `MsiSessionManager::MemoryStatusHandler() : Working set emergency offload completed` | 5881 | `MsiSessionManager.cpp:2645` | after denial |
| **recovery — State=normal** | `State=normal` | — | — | **ABSENT (D-07)** |
| **recovery — AvailableMCM climbing** | `AvailableMCM=` value rising from `0` (line 5870, at denial) back to `~10.2 GB` (`AvailableMCM=10221216831`, line 5873) and oscillating 10–15 GB | 5870→5873+ | `ContractManagerImpl.cpp:464` | after denial, but log ends still failing |

**Recommended detection anchors (robust to sub-state text):**
- `MemoryStatusHandler()` — the stable anchor for the whole memory-status handler family; the sub-state (`critical` / `low` / `Initiating emergency memory offload` / `Working set emergency offload completed`) is the tail text used to classify the signal kind.
- `Memory status changes to low` — the MCM-side low banner.
- `AvailableMCM=(\d+)` — track the value across succeeded lines within the episode span to observe the climb-back (recovery *candidate*).

**Critical timing nuance for D-07 correctness:** On Hartford, `AvailableMCM` *does* climb back after the denial (0 → ~10 GB at 5873), yet there is **no `State=normal`** and the log ends at line 6517 **still emitting `Contract Request Failed`** (214 failures total). Per the reference `prescan`, an implicit-recovery close only fires when a *second* denial banner appears after intervening successes; a lone denial with oscillating `AvailableMCM` and no following denial, ending mid-pressure, stays **OPEN**. So Hartford = **exactly one open/truncated episode**. Do not "improve" the port to treat AvailableMCM-climb as a close — that would break criterion #4. Record the climb-back as a lifecycle observation/annotation, not an episode boundary. (See Open Question Q2.)

## Memory Breakdown (MCM-02) — the real denial block shape

### Format A — denial-time detail block (parsed by `parse_detail_block` / `DETAIL_LINE_RE`)
Line 5843 is the timestamped denial banner; lines 5844–5866 are **continuation lines (no timestamp)**, so the dsserrors adapter groups the entire block into **one event** whose `raw` holds all of it — D-01 works perfectly here. The block terminates on `Note:` (5867) / `Working set includes` (5868) / `SmartHeap cache memory` (5869) — exactly the three break conditions in `parse_detail_block` (lines 252–254).

All 23 verbatim labels present in Hartford (the `_get` fuzzy substrings the D-04 accessors use are shown in **bold**):

```
Total System Physical Memory(GB): 499
	Total In Use Physical Memory For Intelligence Server(MB): 373392
		Total Size Of Physical Memory Used For Memory Mapped Files(MB): 308
	Total In Use Physical Memory For Other Processes(MB): 94516
	Total Physical Memory For File Cache(MB): 14807
Total System Virtual Memory(GB): 499
	Max memory Available to the Intelligence Server Based On Memory Contract Manager(MB): 0
	Total In Use Virtual Memory(Including MMF) For Intelligence Server(MB): 410325   <- _get("Total In Use Virtual Memory")
		Total Stack Size Used by Intelligence Server(MB): 5642
		Total Buffer Size Used by Intelligence Server(MB): 370220
		Report Caches In Memory(MB): 14
		Document Caches In Memory(MB): 0
		Cube Caches In Memory(MB): 27923                                             <- _get("Cube Caches In Memory")
			Cube Size Growth In Memory Including Indexes(MB): 31057                   <- _get("Cube Size Growth In Memory Including Indexes")
			MMF Virtual Memory Size(MB): 365                                         <- _get("MMF Virtual Memory Size")
		Object Server Caches In Memory(MB): 1341
		Element Server Caches In Memory(MB): 0
		Working Set Cache RAM Usage Of Report/Document/Dashboard Instances(MB): 268502  <- _get("Working Set Cache RAM Usage")
		Transient Memory Used By Report Instance ...(KB): 0
		Transient Memory Used By Document Instance ...(KB): 0
		Unused Memory Pool In SmartHeap(MB): 5221                                    <- _get("Unused Memory Pool In SmartHeap")
			Total SmartHeap Cached Memory Utilization(MB): 215
		Other Memory In Intelligence Server(MB): 101682                             <- _get("Other Memory In Intelligence Server")
```

**All reference `_get(substr)` accessors resolve on the real log** — the D-04 typed-accessor design is directly portable. Note `Cube Size Growth (31057) > Cube Caches (27923)` and `Other Memory (101682) > Total In Use Virtual (410325)?` no — these are sub-components; percentages are Phase-10 concern.

### Format B — Info Dump abbreviated blocks (parsed by `parse_abbrev_block` / `ABBREV_LINE_RE`)
These carry `Current Memory Info:` and `MCM Settings:`. In Hartford they attach to `Contract Request Failed. ***** Start of Info Dump *****.` lines (107 of them). The nearest one **before** the denial banner is lines 5817–5839. **There is no Info Dump after the banner** — so the reference's forward-scan from the denial line yields empty MCM Settings on Hartford (the gap the port must fix, Q1).

`Current Memory Info:` block (lines 5821–5833), all match `ABBREV_LINE_RE`:
```
System Total = 535325863936 (498.6GB)
System Available = 52691341312 (49.1GB)
I-Server Private Memory Size = 417200287744 (388.5GB)
I-Server Memory Oscillator = 407406687184 (379.4GB)
All Other Process Data = 65050796032 (60.6GB)
System Total Physical Memory = 535325863936 (498.6GB)
System Available Physical Memory = 52691341312 (49.1GB)
I-Server In-Use Physical Memory = 383156236288 (356.8GB)
All Other Process In-Use Physical Memory = 99478286336 (92.6GB)
System Cache/Buffer Size = 15534309376 (14.5GB)
SmartHeap Cache Size = 1081822112 (1.0GB)
High Watermark = 469891629056 (437.6GB)          <- HWM for %-of-HWM scaling (Phase 10)
Low Watermark = 446397047550 (415.7GB)
```

`MCM Settings:` block (lines 5835–5838):
```
Single Alloc Limit = unlimited
Memory Reserve = 0 (0Bytes)          <- **FAILS ABBREV_LINE_RE** — unit "Bytes" not in (TB|GB|MB|KB) and no space before it
Doubling Limit = 1048576 (1.0MB)
SmartHeap Cache Releasable = true    <- D-04 accessor; reference uses this for SmartHeap flag (Phase 10)
```

**Regex fix required (MCM-02 + "nothing disappears"):** widen `ABBREV_LINE_RE`'s optional unit group to accept `Bytes` (and be robust to a missing space), e.g. `(?:\s*\(([\d.]+)\s*(TB|GB|MB|KB|Bytes)\))?`. Without this, `Memory Reserve` is silently dropped from the MCM Settings map. A test must assert `Memory Reserve` survives.

### Format C — structured JSON blob (line 6360) — DO NOT build now
A single line `{"currentContractInfo":null,"currentMemoryInfo":{...},"mcmSettings":{...},"memoryBreakdown":{...}}` carries the *entire* breakdown as JSON with camelCase keys (`cubeCachesInMemoryInMb`, `smartHeapCacheReleasable`, `highWatermarkInBytes`, etc.). It is a *separate later event* (~500 lines after the banner) and is NOT what the reference parses. Note it as a future robustness option; **YAGNI — do not parse it in Phase 9.**

## Architecture Patterns

### System Architecture Diagram (data flow)

```
store.query_events()                     [store.py:563 — ORDER BY ts IS NULL, ts, source_file, line_start]
        |  (all events, canonical UTC order = D-06 order for free)
        v
filter source == "dsserrors"             [pipeline/mcm.py]
        |
        v
reconstruct line stream:                 for each event: for each line in event.raw.split("\n"):
   (line_text, event_id, source_file)        yield (line, event.event_id, event.source_file)
        |
        v
prescan(stream)  ---> [McmEpisode boundaries: denial_event_id, recovery|None, open_truncated, fragmented]
        |                       |
        |                       +--> lifecycle scan (D-02): tag memory-status/offload/climb signals -> event_id
        v
per episode: parse_detail_block (Format A, from denial event.raw)
             parse_abbrev_block (Format B, from nearest Info-Dump event.raw in span)   [Q1]
        |
        v
MemoryBreakdown { raw_map: {label:(mb,unit)}, typed accessors, current_memory_info, mcm_settings }
        |
        v
list[McmEpisode]   -->  (Phase 10 report/CSV, Phase 11 analyze feed — NOT this phase)
```

### Recommended Project Structure
```
src/sift/pipeline/
  mcm.py              # NEW: ported prescan + parsers + typed models + detect_episodes()
docs/reference/
  analyze_dss8.py     # NEW: vendored copy of the reference (provenance, per CONTEXT)
tests/
  test_mcm.py         # NEW: golden-episode assertions against a Hartford slice fixture
  fixtures/mcm/hartford_deny_slice.log   # NEW: trimmed representative slice (denial + Info Dump + lifecycle + a few succeeded)
```

### Pattern 1: Pure function over stored rows (mirror `salience.rank_clusters`)
**What:** typer-free, print-free, SQL-free function; caller passes already-queried events; returns typed list. No I/O, no LLM.
**When:** the whole analyser (D-05 pure-function, criterion #5 determinism).
**Example (shape to follow):**
```python
# Source: src/sift/pipeline/salience.py:126 (rank_clusters) — the analog
def detect_episodes(events: list[Event]) -> list[McmEpisode]:
    dss = [e for e in events if e.source == "dsserrors"]   # events already UTC-ordered (store.py:567)
    stream = [(line, e.event_id, e.source_file)
              for e in dss for line in e.raw.split("\n")]
    ...  # ported prescan + parsers over `stream`
```
Caller (Phase 10/11, or a test) does `detect_episodes(store.query_events())`. `query_events()` already sorts by `ts IS NULL, ts, source_file, line_start` — this IS the D-06 order, so no re-sort is needed. [VERIFIED: src/sift/store.py:563-568]

### Pattern 2: Verbatim map + typed accessors (D-04)
**What:** keep `raw_map: dict[str, tuple[float, str]]` exactly as parsed; expose typed accessors implemented via the reference `_get(substr)` fuzzy lookup.
**Example:**
```python
class MemoryBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    raw_map: dict[str, tuple[float, str]]          # label -> (value_mb, unit) — verbatim, nothing lost
    current_memory_info: dict[str, str]            # Format B abbreviated
    mcm_settings: dict[str, str]                   # Format B abbreviated (incl. fixed Memory Reserve)

    def _get(self, substr: str) -> float | None:   # reference analyze_dss8.py:500
        s = substr.lower()
        return next((mb for lbl, (mb, _u) in self.raw_map.items() if s in lbl.lower()), None)

    @property
    def cube_caches_mb(self) -> float | None: return self._get("Cube Caches In Memory")
    @property
    def working_set_mb(self) -> float | None: return self._get("Working Set Cache RAM Usage")
    # ... iserver_virtual_mb, mmf_mb, cube_growth_index_mb, smartheap_unused_pool_mb,
    #     other_memory_mb, physical_total, iserver_physical_mb, other_processes_mb
```

### Anti-Patterns to Avoid
- **Assuming Info Dumps are pre-grouped MCM events.** They are NOT on Hartford (adapter sentinel mismatch, §Finding 2). Scan event raws for `Current Memory Info:` / `MCM Settings:` markers.
- **Treating AvailableMCM-climb as an episode close.** Breaks criterion #4 (§Lifecycle timing nuance).
- **Forward-scanning for MCM Settings only *after* the denial line.** Empty on Hartford; associate the nearest in-span Info Dump instead (Q1).
- **Using `set()` in any ordered output** — nondeterministic iteration would break criterion #5. Insertion-ordered dicts + SQL order only.
- **Re-matching timestamps across event boundaries** — use `event.ts` (already parsed).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reading events in multi-node UTC order | A custom sort of events by ts/file/line | `store.query_events()` (already `ORDER BY ts IS NULL, ts, source_file, line_start`) | Order is exactly D-06; re-sorting risks divergence [VERIFIED: store.py:567] |
| Episode boundary logic | Fresh state machine | Port `prescan()` (same-burst collapse, implicit recovery, EOF-open all solved) | Reference is battle-tested and matches criteria 1/4/5 |
| Fuzzy label matching for drifting MStr labels | Exact-label dicts | Port `_get(substr)` substring lookup | D-04; survives label drift the reference already handles |
| Unit conversion | Ad-hoc math | `UNIT_TO_MB` + `to_mb()` | Reference constant, includes TB |
| Timestamp→UTC parsing (if ever needed) | New parser | `salience._parse` / adapter `_match_ts` | Consistent UTC handling already in repo [CITED: salience.py:70] |

**Key insight:** the deterministic core is *already written and correct*. The value-add of Phase 9 is (a) sourcing lines from the store with `event_id` provenance and (b) the lifecycle-signal extension — not re-deriving the algorithm.

## Runtime State Inventory

**Not applicable — greenfield module, not a rename/refactor/migration.** No stored data, live-service config, OS-registered state, secrets, or build artifacts change. The one adjacent asset is the **out-of-repo reference script** `/home/oliverh/Downloads/analyze_dss8.py`, which the plan should **vendor into `docs/reference/`** (a file add, not a state migration). Nothing else. Verified: no new store schema (D-05), no CLI registration this phase (Discretion).

## Common Pitfalls

### Pitfall 1: The `_MCM_START` sentinel does not group Hartford Info Dumps
**What goes wrong:** you assume `Current Memory Info:` / `MCM Settings:` arrive as one tidy MCM event.
**Why:** adapter matches `stripped == "***** Start of Info Dump *****"` (standalone) [CITED: dsserrors.py:69,270], but Hartford embeds it in `Contract Request Failed. ***** Start of Info Dump *****.` — a timestamped line. The abbreviated blocks become continuation lines of the timestamped lines at 5820 (`...Current Memory Info:`) and 5834 (`...MCM Settings:`), spread across several events.
**How to avoid:** re-parse `event.raw` line-by-line scanning for the marker substrings; do not rely on adapter grouping. D-01 already mandates this.
**Warning sign:** `mcm_settings` empty on a log that visibly has `MCM Settings:`.

### Pitfall 2: MCM Settings empty because the scan only looks *after* the denial
**What goes wrong:** faithful port of `parse_log`'s forward scan → empty MCM Settings on Hartford.
**Why:** all 107 Info Dumps precede the banner; none follow it.
**How to avoid:** associate the nearest Info Dump block *within the episode's line span* (which extends before the banner via the lead-up), or the last Info Dump before the banner. See Q1.

### Pitfall 3: `Memory Reserve = 0 (0Bytes)` silently dropped
**What goes wrong:** `ABBREV_LINE_RE` rejects the `Bytes` unit → the label vanishes, violating "nothing disappears."
**How to avoid:** widen the unit alternation to include `Bytes`; add a regression asserting `Memory Reserve` is present.

### Pitfall 4: Breaking the open-episode contract by over-detecting recovery
**What goes wrong:** treating AvailableMCM-climb or resumed successes as a close → Hartford reported as recovered → criterion #4 fails.
**How to avoid:** keep the reference semantics — implicit close only on a *following* denial banner; a lone denial ending mid-pressure stays open (`open_truncated=True`, `recovery=None`).

### Pitfall 5: ReDoS / unbounded scan on adversarial dump text
**What goes wrong:** `DETAIL_LINE_RE`'s `(.+?)` backtracking, or an unterminated block, spins.
**Why:** malformed logs exist; the adapter already caps events at 256 lines / 64 KB [CITED: dsserrors.py:47-48], and the reference caps block scans at 60 lines (`idx - start_idx > 60`, line 265).
**How to avoid:** keep the reference's 60-line block cap; regexes stay `^`-anchored with a required terminator (mirrors the adapter's "no ReDoS" discipline, dsserrors.py:50).

## Code Examples

### Reconstructing the line stream with event_id provenance (D-01/D-02)
```python
# Source: src/sift/store.py:563 (query_events) + src/sift/models.py:18 (Event.raw)
def _line_stream(events: list[Event]) -> list[tuple[str, str, str]]:
    """(line_text, event_id, source_file) in canonical UTC order, MCM tokens intact in raw."""
    return [
        (line, e.event_id, e.source_file)
        for e in events
        if e.source == "dsserrors"
        for line in e.raw.split("\n")
    ]
```

### Detail-block parse (faithful port, Format A)
```python
# Source: analyze_dss8.py:247 parse_detail_block — terminators verified at Hartford lines 5867-5869
DETAIL_LINE_RE = re.compile(r'^\t*(.+?)\((GB|MB|KB)\):\s*(-?\d+)\s*$')
UNIT_TO_MB = {'KB': 1/1024, 'MB': 1, 'GB': 1024, 'TB': 1024*1024}
# _get("Cube Caches In Memory") -> 27923.0 ; _get("Working Set Cache RAM Usage") -> 268502.0
```

## State of the Art

| Old Approach (reference script) | Phase 9 Approach | Why |
|---------------------------------|------------------|-----|
| `open(path).readlines()` flat file | `store.query_events()` + `event.raw` split | D-01 citation provenance; no disk re-read |
| Interactive `prompt_event`/`prompt_window` | Non-interactive, all episodes | Criterion #1 (no prompts) |
| Forward-scan MCM Settings after denial | Nearest in-span Info Dump | Empty on Hartford otherwise |
| Only denial/`State=normal`/`Succeeded` tracked | + memory-status/offload lifecycle signals | D-02, criterion #2 |
| `Memory Reserve` dropped by regex | Regex widened for `Bytes` | "Nothing disappears" |

**Deprecated/outdated:** none — this is a first port.

## Validation Architecture

> `nyquist_validation` is enabled (`.planning/config.json` → `workflow.nyquist_validation: true`). This section seeds the phase VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest`) — established across Phases 1–8 |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `addopts` markers per Phase 8) |
| Quick run command | `uv run pytest tests/test_mcm.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req / Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------------|----------|-----------|-------------------|--------------|
| Crit #1 / MCM-01 | Exactly **1** episode detected on Hartford slice, non-interactively; denial anchored at the banner event_id | unit | `uv run pytest tests/test_mcm.py::test_hartford_single_episode -x` | ❌ Wave 0 |
| Crit #2 / MCM-01 | Episode lifecycle contains memory-status-low, emergency-offload-start, emergency-offload-complete, each referencing a real `event_id` in span | unit | `... ::test_lifecycle_signals -x` | ❌ Wave 0 |
| Crit #2 / D-03 | `State=normal` recovery is `None`; missing signals recorded absent, no crash | unit | `... ::test_absent_signals_tolerated -x` | ❌ Wave 0 |
| Crit #3 / MCM-02 | Typed accessors return known values (cube=27923, working_set=268502, mmf=365, other_memory=101682, iserver_virtual=410325, physical_total from GB=499); verbatim map has all 23 labels | unit | `... ::test_breakdown_values -x` | ❌ Wave 0 |
| Crit #3 / MCM-02 | MCM Settings parsed incl. `SmartHeap Cache Releasable=true` AND `Memory Reserve` NOT dropped | unit | `... ::test_mcm_settings_complete -x` | ❌ Wave 0 |
| Crit #4 / D-07 | Log with no `State=normal` ending mid-episode → `open_truncated=True`, `recovery=None`, not dropped, no exception | unit | `... ::test_open_truncated_episode -x` | ❌ Wave 0 |
| Crit #5 / D-05 | Two `detect_episodes()` runs on same events → byte-identical `model_dump_json()` | unit | `... ::test_determinism_byte_identical -x` | ❌ Wave 0 |
| D-06 (guard) | Denial event with empty detail block whose neighbour is a different `source_file` → `fragmented=True` (synthetic 2-file fixture) | unit | `... ::test_fragmented_flag -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_mcm.py -x`
- **Per wave merge:** `uv run pytest` (full suite green, plus `ruff check` + `pyright`)
- **Phase gate:** full suite + ruff + pyright green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_mcm.py` — the 8 assertions above (covers MCM-01, MCM-02, criteria 1–5, D-03/06/07)
- [ ] `tests/fixtures/mcm/hartford_deny_slice.log` — trimmed representative slice: the denial banner + tab-indented detail block (Format A), one preceding Info Dump (Format B, incl. `Memory Reserve = 0 (0Bytes)`), the lifecycle lines (memory-status-low, offload start/complete), and a handful of `Contract Request Succeeded` with `AvailableMCM`/`HWM(PB)`. Slice ends **without** `State=normal` (preserves the open/truncated path). Keep verbatim so `event_id`s are stable.
- [ ] Test helper to ingest the fixture into a temp `case.db` via the existing `DsserrorsAdapter` + `CaseStore` (reuse existing Phase-5 test ingest patterns — check `tests/` for the established fixture-ingest helper before writing a new one).
- [ ] `docs/reference/analyze_dss8.py` — vendor the reference (provenance).
- No framework install needed (pytest already present).

## Security Domain

> `security_enforcement: true`, ASVS level 1. This module is fully offline, read-only over already-stored data, no auth, no secrets, no network.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | no auth surface |
| V3 Session Management | no | — |
| V4 Access Control | no | reads local `case.db` only |
| V5 Input Validation | **yes** | Anchored, linear-scan regexes (no ReDoS); 60-line block cap; adapter's 256-line/64 KB event caps already bound input [CITED: dsserrors.py:47] |
| V6 Cryptography | no | none |

### Known Threat Patterns for {stdlib-regex log parser}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Catastrophic backtracking (`DETAIL_LINE_RE` `(.+?)`) on malformed dump lines | Denial of Service | `^`-anchored with required terminator; 60-line block cap (reference line 265); keep patterns non-nested |
| Unbounded memory on never-terminated block | Denial of Service | Adapter already caps events (256 lines / 64 KB); analyser operates on already-bounded `event.raw` |
| Crash on absent/garbled breakdown | Denial of Service (availability) | D-03/D-07 "tolerate absence, never crash" — return `breakdown=None` / `open_truncated=True` |
| No egress path | (Info disclosure) | Module makes zero network/file-write calls; tests need no fake server |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The nearest **pre-denial** Info Dump (lines 5817–5839) is the correct source for the episode's `Current Memory Info` / `MCM Settings` on Hartford (since none follow the banner) | Format B / Q1 | Wrong block associated → MCM Settings reflect a slightly earlier instant. Low risk (48 ms before denial); planner should confirm the association rule (Q1). |
| A2 | Pydantic `BaseModel(frozen=True, extra="forbid")` is the preferred model base (vs frozen dataclass) | Standard Stack | Either satisfies D-04; only affects Phase 11 serialisation ergonomics. |
| A3 | A trimmed Hartford slice fixture is acceptable vs ingesting the full 2 MB log in tests | Validation | If byte-exact `event_id`s must match a full-log golden, slice offsets differ — but Phase 9 asserts values/structure, not specific ids, so low risk. |

## Open Questions

1. **Which Info Dump supplies the episode's `Current Memory Info` / `MCM Settings`?**
   - What we know: Hartford has no Info Dump after the denial banner; the nearest is 5817–5839 (48 ms before). The denial detail block (Format A) itself contains no MCM Settings.
   - What's unclear: association rule — "last Info Dump before the banner" vs "nearest within the whole episode span."
   - Recommendation: use the **last Info Dump block at or before the denial banner, within the episode span**; if none exists in span, `mcm_settings={}` (D-03 absence). Deterministic and matches the denial instant closely.

2. **Does AvailableMCM-climb ever *close* an episode, or is it only an annotation?**
   - What we know: criterion #1 lists it as a recovery signal; criterion #4 requires Hartford (which has the climb) reported open.
   - What's unclear: the general close rule vs the Hartford-specific open outcome.
   - Recommendation: record climb-back as a lifecycle annotation; **close only on `State=normal` or a following denial banner** (reference semantics). This satisfies both criteria for Hartford. Revisit in Phase 10 if a multi-episode log needs finer close logic.

3. **Model base: Pydantic vs frozen dataclass** (A2) — recommend Pydantic for Phase 11 JSON feed; planner's call under Discretion.

## Environment Availability

**SKIPPED — no external dependencies.** The analyser reads an existing local `case.db` via the in-process `CaseStore` and makes no network, subprocess, or external-tool calls. The only inputs are stdlib `re` and already-vendored Pydantic. (Reference script and Hartford fixtures are local files, confirmed present this session.)

## Sources

### Primary (HIGH confidence — verified in this session)
- `/home/oliverh/Downloads/analyze_dss8.py` (read in full) — `prescan`, `parse_detail_block`, `parse_abbrev_block`, `_get`, all regex/marker constants.
- `/home/oliverh/Downloads/hartford/hartford_linux_deny_.log` (grepped + read) — every marker string, regex match, memory-breakdown label, and the absence of `State=normal`, verified against real data.
- `src/sift/models.py` — frozen `Event` dataclass fields; `Hypothesis` `extra="forbid"` convention.
- `src/sift/adapters/dsserrors.py` — event grouping, MCM sentinels (`_MCM_START` standalone-match gap), token regexes, 256-line/64 KB caps.
- `src/sift/store.py:563-667` — `query_events()` (ORDER BY ts,source_file,line_start), `get_events_by_ids()`, `iter_event_rows()`.
- `src/sift/pipeline/salience.py` — the pure-function-over-stored-rows analog (`rank_clusters`, `_parse`/`_as_utc`).
- `.planning/REQUIREMENTS.md` — MCM-01/MCM-02 exact text; `.planning/ROADMAP.md` Phase 9; `.planning/config.json` (nyquist + security flags).

### Secondary (MEDIUM confidence)
- Prior project memory: Hartford bracket-token format and adapter reconciliation flag (now upgraded to VERIFIED by direct grep).

### Tertiary (LOW confidence)
- None. All claims were tool-verified this session.

## Metadata

**Confidence breakdown:**
- Port targets (which functions/constants to lift) — HIGH — read the reference in full.
- Marker/regex/label correctness — HIGH — every one grepped/matched against the real Hartford log.
- Repo contract alignment (Event/store/salience) — HIGH — read the live source.
- Info Dump association rule (Q1) — MEDIUM — one defensible rule recommended; planner to confirm.
- Model-base choice (Q3) — MEDIUM — either option satisfies D-04.

**Research date:** 2026-07-19
**Valid until:** 2026-08-18 (stable — pins to a fixed reference script, a fixed real log, and frozen repo contracts; no fast-moving external deps)
