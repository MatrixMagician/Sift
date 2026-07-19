---
seed_id: SEED-001
idea: DSSPerformanceMonitor PDH-CSV adapter + MCM-episode correlation
planted_during: v1.1 (MCM Memory-Pressure Analysis)
trigger_when: A milestone extends DSSErrors/MCM analysis, adds time-series correlation, or adds a new CSV/perfmon input type
---

# SEED-001: DSSPerformanceMonitor PDH-CSV adapter + MCM-episode correlation

## Idea

Ingest MicroStrategy DSSPerformanceMonitor PDH-CSV exports (e.g.
`hartford_Linux_DenyDSSPerformanceMonitor16234.csv`) as a time-series input and
correlate their counters with the MCM denial episodes detected from the
DSSErrors.log in the same case.

The CSV is a PDH 4.0 export with a leading timestamp column and per-counter
columns, including: `System\Total CPU`, `System\RAM used(MB)`,
`Process(MSTRSvr)\Size(MB)` / `RSS(MB)` / `% CPU time`,
`Server Users\Working set cache RAM usage(MB)`, `Open Sessions` /
`Open Project Sessions`, `cubes loaded in memory`,
`Total Memory Mapped Files Size (MB)`, **`Total MCM Denial`** counter, cache
swap counts, and cube rowmap/index/element memory (KB).

## Why This Matters

The DSSErrors.log gives the *point-in-time* denial breakdown; the PerfMon CSV
gives the *trend* leading in and out of it (working-set-cache RAM climbing, the
`Total MCM Denial` counter incrementing, session counts, cube memory growth).
Overlaying the two turns a single-snapshot forensic report into a corroborated
timeline — "working-set cache was already at X MB and climbing N MB/min for the
20 minutes before the denial banner".

## Why Deferred from v1.1

v1.1 is scoped to the DSSErrors/MCM *log* analysis (the `analyze_dss8.py`
integration). The PerfMon CSV is a *different input type* — it needs a new
adapter (PDH-CSV parsing, per-counter time-series), and the correlation is a
separate join across two artefacts in a case. Bundling it would roughly double
the milestone. Kept deterministic-first, same as the MCM analyser.

## Scope Sketch (when picked up)

- New `dssperfmon` adapter: parse PDH-CSV header → counter set, rows → timestamped samples (EST/tz from the header's `(… Time)` token)
- Time-series stored as events or a dedicated table (decide: does it fit the Event contract, or is it a separate numeric series confined to store.py?)
- Correlation: align denial-episode timestamps (from MCM analysis) against the `Total MCM Denial` / working-set-cache trend; annotate episodes with lead-in slope
- Report: episode timeline gains a "corroborating perfmon trend" section
- Reference data: `/home/oliverh/Downloads/hartford/hartford_Linux_DenyDSSPerformanceMonitor16234.csv`

See [[mcm-memory-pressure-analysis]] (v1.1) for the episode-detection output this consumes.
