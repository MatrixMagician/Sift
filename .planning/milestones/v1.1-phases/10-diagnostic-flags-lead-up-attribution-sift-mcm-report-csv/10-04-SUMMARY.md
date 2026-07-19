---
phase: 10-diagnostic-flags-lead-up-attribution-sift-mcm-report-csv
plan: 04
subsystem: render/mcm_report + cli
status: complete
tags: [mcm, mcm-05, report, csv, d-10, d-11, d-15, d-16, determinism, security]
requires:
  - "sift.pipeline.mcm.analyse_mcm / McmAnalysis / EpisodeAnalysis (Plan 10-03)"
  - "sift.pipeline.mcm.DiagnosticFlag / Attribution / AttributionRow (Plans 10-02/10-03)"
  - "sift.render.markdown._field/_escape/_fence + render._util.sanitise (Phase 6)"
  - "sift.store.case_db_path / query_events ; sift.config.McmConfig.thresholds"
provides:
  - "sift.render.mcm_report.render_mcm_markdown (McmAnalysis -> str, D-11 layout)"
  - "sift.render.mcm_report.render_mcm_json (deterministic, ensure_ascii)"
  - "sift.render.mcm_report.write_attribution_csv (single dimension-tagged CSV, D-15/D-16)"
  - "sift.cli.mcm command + McmFormat StrEnum — writes <case>/mcm/ bundle (D-10)"
affects:
  - "Phase 11 may reuse the same McmAnalysis; the bundle is the operator deliverable"
tech-stack:
  added: []
  patterns:
    - "Renderer mirrors render/markdown.py: pure ->str, every log field via the shared _field escaping (no second escaping impl)"
    - "CSV via stdlib csv.writer(newline='') — never a manual join (correct quoting)"
    - "CLI mirrors report: load_config -> _case_store -> analyse -> write -> summary -> finally store.close()"
key-files:
  created:
    - src/sift/render/mcm_report.py
  modified:
    - src/sift/cli.py
    - tests/test_mcm_report.py
    - tests/test_cli_mcm.py
decisions:
  - "Reused markdown._field (a private symbol) rather than duplicating escaping — sanctioned by the plan ('import them, do not reimplement'); one pyright reportPrivateUsage ignore documents the intentional cross-module reuse"
  - "Dropped a direct render._util.sanitise import — _field already wraps sanitise, so a direct import would be dead code (ruff F401); the load-bearing reuse is via _field"
  - "Breakdown/attribution MB figures render in tables (allowed absolutes); only flags + the lead-up window are %-framed (T-10-16), with any GB kept as a parenthetical human aid inside the window label"
metrics:
  duration: ~25min
  completed: 2026-07-19
  tasks: 3
  files: 4
---

# Phase 10 Plan 04: MCM Forensics Bundle (`sift mcm`) Summary

Shipped MCM-05: the `sift mcm <case>` command that turns the Plan-03
`McmAnalysis` into a durable, deterministic forensics bundle. Three pure
renderer functions in a new `render/mcm_report.py` — a timeline-first Markdown
report (D-11), a canonical ASCII-safe JSON report, and a single
dimension-tagged CSV whose every row carries its owning `event_id`s (D-15/D-16)
— plus the CLI tier (`sift mcm`, the only I/O layer) that always writes
`<case>/mcm/mcm_report.md|json` **and** `<case>/mcm/mcm_attribution.csv` and
prints a short stdout summary (D-10). This is the phase's security boundary:
hostile DSSErrors text flowing into shareable Markdown and a spreadsheet-openable
CSV, mitigated by reusing the load-bearing markdown escaping and stdlib
`csv.writer` quoting.

## What was built

- **`render_mcm_markdown(analysis)`** — pure `McmAnalysis -> str`. Per episode, in
  D-11 order: lifecycle timeline → graded diagnostic flags → denial-time memory
  breakdown → three attribution tables (by OID with the SID fan-out count, by
  request source, by SID). Every log-sourced field (SID/OID keys, `Source=`
  values, lifecycle text, flag messages) routes through the shared
  `markdown._field` escaping so hostile bytes cannot inject Markdown/HTML
  structure (T-10-12). Flags and the lead-up window are framed as percentages,
  never an absolute-GB headline (T-10-16). Empty analysis renders a valid
  "_No MCM denial episodes detected._" document.
- **`render_mcm_json(analysis)`** — `json.dumps(analysis.model_dump(mode="json"),
  sort_keys=True, ensure_ascii=True, indent=2) + "\n"`. Byte-identical on re-run;
  `ensure_ascii` neutralises C1/Cf terminal-injection bytes (the `json_out`
  precedent).
- **`write_attribution_csv(analysis, path)`** — stdlib `csv.writer(newline="")`,
  header `episode_id,dimension,key,granted_bytes,granted_mb,request_count,event_ids`;
  rows per episode in dimension order oid → source → sid (each already sorted),
  `granted_mb = round(bytes/1024**2, 3)`, `event_ids` `;`-joined and never empty,
  `episode_id = denial_event_id`. Empty analysis writes a header-only CSV.
- **`McmFormat` StrEnum** (`md`|`json`) + **`sift mcm`** command: `load_config`
  → `_case_store` (missing-case exit 1) → `analyse_mcm(store.query_events(),
  config.mcm.thresholds)` → write bundle under `<case>/mcm/` (dir derived from
  `case_db_path(...).parent`, path-confined, T-10-14) → stdout summary (episode
  count + per-episode top flag, log text via `_sanitise`, T-10-15) → `finally
  store.close()`. No `--threshold`/`--window` knob (config-only, D-12/D-13).

## Tasks

| Task | Name | Type | Commit |
|------|------|------|--------|
| 1 | RED: renderer/CSV goldens + CLI integration tests | auto | 2acbc45 |
| 2 | GREEN: render_mcm_markdown / render_mcm_json / write_attribution_csv | auto (tdd) | 98ab94f |
| 3 | GREEN: sift mcm command — analyse + write bundle + summary | auto (tdd) | 996b087 |

## Verification

- `uv run pytest tests/test_mcm_report.py tests/test_cli_mcm.py` — 14 passed
  (8 renderer/CSV goldens + 6 CLI integration).
- `uv run pytest` — **515 passed, 8 deselected** (full-suite regression clean;
  Phases 1-9 and Plans 10-01..03 unaffected).
- `uv run ruff check` — clean; `uv run pyright` — 0 errors, 0 warnings.
- Determinism proven by both a renderer test (`test_json_deterministic`,
  `test_csv_deterministic`) and a CLI test (`test_mcm_determinism`: two runs →
  byte-identical `mcm_report.md` + `mcm_attribution.csv`).

## Threat register — mitigations satisfied

- **T-10-12** (Markdown/HTML injection): `test_markdown_sanitises_hostile_fields`
  proves a hostile key/lifecycle text with `|`, `#`, `<img`, `<script` and a bidi
  control byte renders escaped — no raw injection reaches the report. Achieved by
  reusing `markdown._field`, not a second escaping implementation.
- **T-10-13** (CSV/formula injection): stdlib `csv.writer` quoting; keys are
  structurally hex or `Source=` `[\w:]+`; never a manual join.
- **T-10-14** (path traversal): bundle dir is `case_db_path(...).parent / "mcm"` —
  the same containment-asserting resolution `_case_store` validates; only
  `<case>/mcm/` is created.
- **T-10-15** (terminal injection via stdout): summary text through `_sanitise`.
- **T-10-16** (absolute-GB headline leak): `test_markdown_no_absolute_gb_headline`
  guards that flag lines are %-framed; absolute MB/bytes live only in the
  breakdown/attribution tables and the CSV.
- **T-10-17 / T-10-SC**: pure bounded pass; no package installs (stdlib
  `csv`/`json` + already-present Pydantic/Typer only).

## Success criteria

- `sift mcm <case>` writes a deterministic report + per-OID/Source/SID CSV into
  `<case>/mcm/` with a stdout summary (MCM-05, D-10) — met.
- Report is timeline-first per episode (D-11); every log-sourced field is
  injection-sanitised; CSV rows carry their `event_id`s (D-15/D-16) — met.
- Thresholds and the lead-up window stay config-only — no per-run CLI knob
  (D-12/D-13), verified by `test_mcm_no_threshold_or_window_flag`; writes confined
  to the resolved case dir — met.

## Deviations from Plan

Two small implementation choices, neither a behaviour change:

1. **[Rule 3 — blocking] Dropped the direct `render._util.sanitise` import.** The
   plan's Task-2 prose says "Import `sanitise` from `render/_util`". In practice
   every rendered field goes through `markdown._field`, which itself wraps
   `sanitise` — a direct import was unused and tripped `ruff` F401 (dead code).
   Reuse of the shared sanitisation is preserved transitively via `_field`; the
   load-bearing "no second escaping implementation" requirement is fully met.
2. **[Rule 3 — blocking] One `pyright: ignore[reportPrivateUsage]` on the
   `_field` import.** `markdown._field` is underscore-private; the plan
   explicitly sanctions "import them … do not write a second escaping
   implementation". Importing a private symbol trips pyright strict, so a single
   documented ignore records the intentional, plan-mandated cross-module reuse
   rather than duplicating the escaping. No other production code imports it, so
   the private surface stays contained.

## Known Stubs

None. The renderers are pure passes over the real `McmAnalysis`; the CLI wires
`analyse_mcm` to stored events end-to-end. An empty case yields a valid empty
bundle (a legitimate recorded absence, not a placeholder).

## Self-Check: PASSED
