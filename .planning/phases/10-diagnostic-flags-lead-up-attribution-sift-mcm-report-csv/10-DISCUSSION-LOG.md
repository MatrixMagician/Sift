# Phase 10 — Discussion Log

**Date:** 2026-07-19
**Mode:** discuss (interactive), ADVISOR_MODE off
**For human reference only** — downstream agents read CONTEXT.md, not this log.

Areas offered (multiSelect): CLI surface & output routing · Report layout & emphasis · Diagnostic-flag model · Lead-up window & attribution shape.
User selected: **all four**.

## Decisions

### 1. CLI surface & output routing → D-10
- Options: (a) standalone cmd + opt-in CSV; (b) **standalone cmd, always bundle**; (c) flag on `sift report`.
- **Chosen: (b)** — `sift mcm <case>` always writes report + CSV into `<case>/mcm/`, stdout shows a short summary. Report honours `--format md|json`.

### 2. Report layout & emphasis → D-11
- Options: (a) flags-first; (b) breakdown-first; (c) **timeline-first**.
- **Chosen: (c)** — per episode lead with the lifecycle timeline (denial → memory-status-low → offload → recovery/open), then flags, then breakdown, then attribution.

### 3. Diagnostic-flag model → D-12
- Options: (a) **graded + config override**; (b) named booleans, fixed; (c) graded + CLI override.
- **Chosen: (a)** — graded severity (info/warn/critical); %-of-HWM thresholds are constants overridable via `[mcm.thresholds]` in config.toml; no per-run CLI knobs. Default cut-points handed to RESEARCH to propose against the real Hartford figures.

### 4. Lead-up window + attribution shape → D-13, D-14
- Options: (a) auto window, unified table; (b) **auto window, three tables**; (c) overridable window, unified.
- **Chosen: (b)** — fully-automatic non-interactive window (no override); attribution split by OID / Source / SID as three per-dimension views.

### Follow-up A — CSV layout → D-15
- Options: (a) three files in `case/mcm/`; (b) **one file, dimension column**; (c) three files, episode-scoped.
- **Chosen: (b)** — single `<case>/mcm/mcm_attribution.csv` with a `dimension` column (oid|source|sid).

### Follow-up B — Citation provenance → D-16
- Options: (a) **yes — event_id column**; (b) no, keep CSV lean.
- **Chosen: (a)** — each attribution row carries the owning event_id(s); preserves cited ⊆ store end-to-end for Phase 11.

## Handed to research (not decided here)
- Default flag threshold cut-points per dimension, validated against the real Hartford deny figures (D-12).
- The scaled-fixture design proving machine-independence (success criterion #5).

## Deferred / redirected
- Per-run CLI threshold overrides (config-only chosen).
- User-overridable lead-up window / descent thresholds (fully-automatic chosen).
- MCM facts → `sift analyze` + golden eval case → Phase 11.
