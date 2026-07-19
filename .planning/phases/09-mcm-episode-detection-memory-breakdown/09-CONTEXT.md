# Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown - Context

**Gathered:** 2026-07-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a **deterministic, no-LLM analyser** that scans an already-ingested
`dsserrors` case and:

1. **Detects every distinct MCM denial episode** non-interactively (all
   episodes, no prompts), each bounded by its denial banner
   (`IServer enters MCM denial state`) and its recovery (`State=normal`,
   resumed contract activity, or `AvailableMCM` climbing back), and captures
   the **full lifecycle** (memory-status-low handler, emergency working-set
   offload, recovery) as episode context — not just the denial banner.
2. **Parses each episode's denial-time memory breakdown** into a structured
   model: physical/virtual split, cube caches, cube growth/index, MMF,
   SmartHeap pool, working set, other memory, plus the MCM Settings block.

Requirements **MCM-01** and **MCM-02** only. The numeric core is strictly
separate from the LLM — figures are computed here, never authored by a model.

**Explicitly NOT in this phase** (later in milestone v1.1):
- Diagnostic flags, lead-up window selection, per-OID/Source/SID attribution,
  the `sift mcm` command, and the CSV export → **Phase 10** (MCM-03/04/05).
- Feeding MCM facts into `sift analyze` as cited evidence, and the MCM golden
  eval case → **Phase 11** (MCM-06/07).

The porting basis is the reference script `analyze_dss8.py`; Phase 9 ports and
**extends** its `prescan` (episode detection) and block parsers (breakdown),
**minus** its interactive prompts and window/attribution logic.

</domain>

<decisions>
## Implementation Decisions

### Data source (how the analyser reads the log)
- **D-01: Read ingested `Event` rows from the store; re-parse MCM tokens from
  `event.raw` inside the new analyser.** The adapter is left untouched. Every
  dsserrors line becomes an event whose `raw` preserves verbatim text and whose
  `event_id`/`line_start`/`line_end` are stable — so the analyser re-applies the
  reference regexes (`AvailableMCM=`, `HWM(...)=`, `Size=`, `Source=`, `SID`,
  the denial banner, `State=normal`, and the memory-dump detail block) to
  `event.raw`.
- **Rationale:** keeps every episode signal mapped to a real `event_id`, which
  is the load-bearing citation path for **Phase 11** (`cited ⊆ prompted ⊆
  store`). No disk re-read; all MCM logic stays isolated in one new module.
- **Rejected:** *enrich the dsserrors adapter* to emit AvailableMCM/HWM/Size/
  Source/SID as attrs (touches the near-frozen adapter and forces re-ingest of
  existing cases); *raw-file re-parse from disk* (yields line numbers, no
  `event_id` — a citation dead-end for MCM-06).

### Lifecycle signal capture (criterion #2)
- **D-02: Pin the exact marker strings by research against the real Hartford
  deny log.** The three lifecycle signal types — memory-status-low handler,
  emergency working-set offload, recovery — are captured as **episode
  annotations that reference the `event_id`** of the line that carries them,
  within the episode's line span.
- **D-03: Tolerate absence.** A given episode/log may not contain all three
  signals (the Hartford deny log has **no** `State=normal` at all). Missing
  signals are recorded as absent, never fabricated, and never cause a crash or a
  dropped episode.
- The reference `prescan` only tracks denial / `State=normal` / `Succeeded`;
  these lifecycle markers are a **new extension** on top of it. Candidate
  anchors to confirm against the log: `memory-status-low`, an emergency
  working-set/offload string, and `AvailableMCM`-climbing-back as an implicit
  recovery signal.

### Memory-breakdown model shape
- **D-04: Hybrid — faithful verbatim map + typed named accessors.** Retain the
  full `label → (value_mb, unit)` map exactly as parsed (nothing lost), AND
  expose typed named accessors for the known components (physical total /
  IServer / other; virtual IServer; cube caches; cube index/growth; MMF;
  working set; SmartHeap unused pool; other memory; plus the `Current Memory
  Info` and `MCM Settings` blocks).
- **Rationale:** auditability (verbatim labels survive) + typed downstream
  access, and it tolerates MStr label drift the way the reference's fuzzy
  `_get(substr)` lookup does — implemented as typed accessors over the map.
- **Rejected:** *typed-fields-only* (brittle to label changes, drops
  fuzzy-matched labels); *verbatim-map-only* (forces every consumer to
  string-match labels).

### Output shape & episode scope
- **D-05: Pure deterministic function over stored events — no new store table
  in Phase 9.** The analyser computes episodes on demand; Phase 10 (report/CSV)
  and Phase 11 (analyze feed) call the same function. Determinism is inherent
  because no model is involved (satisfies criterion #5 byte-identical re-run
  without a persistence layer). Avoids a migration, a write path, and
  cache-staleness questions that nothing yet needs.
- **D-06: Order events by UTC `ts` across source files (multi-node safe).**
  Episode detection walks dsserrors events in UTC-timestamp order (tie-break by
  `source_file`, then `line_start`). An MCM dump block **fragmented across a
  rotation boundary** (per ADR 0006, the adapter never stitches across `.bak`
  siblings) is **flagged as fragmented/partial**, not silently merged. Hartford
  is single-file so this is a design guard, not a Hartford-specific need.
- **D-07: Open/truncated episodes are first-class.** A log ending mid-episode
  with no recovery line (the Hartford case) is reported as an
  **open/truncated** episode with `recovery=None`, distinct from an
  implicit-recovery (resumed-activity) close — never dropped, never crashed
  (criterion #4).

### Claude's Discretion
- Module placement and naming (expected: a new `src/sift/pipeline/mcm.py`
  analyser + typed models, mirroring how `pipeline/salience.py` consumes stored
  events), the exact typed-model field set, and the internal regex/parse
  structure are the planner's/executor's call, provided D-01…D-07 hold.
- No public CLI surface is required in Phase 9 (the `sift mcm` command is
  Phase 10). A thin internal entry point + tests is sufficient.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & scope (authoritative)
- `.planning/ROADMAP.md` § "Phase 9: MCM Episode Detection & Denial-Time Memory
  Breakdown" — goal, dependencies, and the 5 success criteria this phase is
  graded against.
- `.planning/REQUIREMENTS.md` § "v1.1 Requirements — MCM Analysis" — **MCM-01**
  and **MCM-02** are this phase; MCM-03…07 define what is deliberately deferred
  to Phases 10–11.

### Reference implementation (the porting basis)
- `/home/oliverh/Downloads/analyze_dss8.py` — **lives OUTSIDE the repo.** The
  deterministic logic to port/extend: `prescan()` (episode detection incl.
  same-burst collapse, implicit recovery, open-episode-at-EOF),
  `parse_detail_block()` / `parse_abbrev_block()` (breakdown + Current Memory
  Info + MCM Settings), and the regex/marker constants. **Discard** its
  interactive `prompt_event`/`prompt_window`, window selection, and per-OID
  attribution (those are Phase 10). **Action for planning:** vendor a copy into
  the repo (e.g. `docs/reference/analyze_dss8.py` or the phase dir) so the
  provenance is durable and citable.

### Contracts & prior decisions the analyser must respect
- `src/sift/models.py` — the **frozen** `Event` dataclass (`event_id`, `raw`,
  `line_start`/`line_end`, `attrs`, `session`, `component`). Do not modify it.
- `src/sift/adapters/dsserrors.py` — what the source events actually contain:
  every timestamped line is one event; MCM Info Dump blocks are one multi-line
  event with the verbatim dump in `raw`; attrs currently expose `node`,
  `error_code`, `oid`, `source_loc`, `byte_offset`/`byte_len` — but **not**
  AvailableMCM/HWM/Size/Source (hence D-01's re-parse from `raw`).
- `src/sift/store.py` — read API: `query_events() -> list[Event]`,
  `get_events_by_ids(ids)`, `iter_event_rows(...)`. Use these; add no schema.
- `docs/decisions/0006-configurable-adapter.md` — per-file parsing; MCM blocks
  fragment across rotated `.bak` siblings (basis for D-06's fragment flag).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`store.query_events()` / `get_events_by_ids()`** (`src/sift/store.py:563,590`):
  the analyser's input — pull dsserrors events, filter by `source == "dsserrors"`,
  order by `ts` then `source_file`/`line_start`.
- **Reference regexes/markers** in `analyze_dss8.py` (`TIMESTAMP_RE`, `SID_RE`,
  `OID_RE`, `SIZE_RE`, `SOURCE_RE`, `AVAIL_MCM_RE`, `HWM_RE`, and the
  `DENIAL_MARKER`/`NORMAL_MARKER`/`SUCCESS_MARKER`/`CURRENT_INFO_MARKER`/
  `MCM_SETTINGS_MARKER`/`DETAIL_LINE_RE`/`ABBREV_LINE_RE` constants) — port
  verbatim, applied to `event.raw`.
- **Existing dsserrors regexes** in `src/sift/adapters/dsserrors.py`
  (`_MCM_SOURCE_RE`, `_MCM_SIZE_RE`, `_MCM_START`/`_MCM_END` sentinels) — align
  with, don't duplicate divergently.

### Established Patterns
- **Pipeline-stage-reads-store**: `src/sift/pipeline/salience.py:126`
  (`rank_clusters`) is the closest analog for a deterministic stage that
  consumes stored events + a UTC-parsing helper (`_parse`/`_as_utc`) — the new
  `pipeline/mcm.py` should follow the same shape.
- **Typed output models**: `src/sift/models.py` uses frozen dataclasses /
  Pydantic models with `extra="forbid"`; the episode + breakdown models should
  match that convention (D-04).
- **Determinism & "nothing disappears"**: unparseable/absent regions are
  recorded, never dropped (criteria #4/#5, and project invariants).

### Integration Points
- New module (expected `src/sift/pipeline/mcm.py`) reads from `store.py`, emits
  typed episode/breakdown models. No CLI wiring this phase; Phase 10 will attach
  `sift mcm`, Phase 11 will feed `analyze`.

</code_context>

<specifics>
## Specific Ideas

- Validate against the **real Hartford deny log** (it has **no** `State=normal`,
  so the open/truncated-episode path — D-07 — is exercised on real data, not
  just a fixture).
- Thresholds and windows are **% of HWM**, never absolute GB (machine-
  independent) — locked at the milestone level; relevant here only insofar as
  HWM is captured per episode for Phase 10 to consume.

</specifics>

<deferred>
## Deferred Ideas

- **Diagnostic flags, lead-up window, per-OID/Source/SID attribution, `sift mcm`
  report + CSV** — Phase 10 (MCM-03/04/05).
- **MCM facts into `sift analyze` as cited evidence + MCM golden eval case** —
  Phase 11 (MCM-06/07).
- **Adapter enrichment** (emitting MCM numeric tokens as structured attrs at
  ingest) — considered and rejected for now (D-01); revisit only if re-parsing
  `event.raw` proves a measured bottleneck.
- **Persisting episodes to a store table** — considered and rejected for now
  (D-05); revisit if a consumer needs durable/queryable episodes.
- **DSSPerformanceMonitor CSV time-series correlation (PERF-01)** — deferred to
  v2 (SEED-001).

</deferred>

---

*Phase: 9-mcm-episode-detection-memory-breakdown*
*Context gathered: 2026-07-19*
