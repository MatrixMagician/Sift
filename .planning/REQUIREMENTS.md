# Requirements: Sift — v1.2 DSSPerformanceMonitor Correlation

**Defined:** 2026-07-20
**Core Value:** Turn a directory of raw diagnostics into a structured, evidence-cited triage report — entirely offline, with every claim citing verifiable event IDs.

## v1.2 Requirements

Requirements for the DSSPerformanceMonitor Correlation milestone. Each maps to exactly one roadmap phase.

### Ingestion

- [x] **PERF-01**: Engineer can ingest a DSSPerformanceMonitor PDH-CSV through a `dssperfmon` adapter that sniffs the `(PDH-CSV 4.0)` header, turns every sample row into a canonical `Event` with deterministic `event_id = sha256(source_file, byte_offset)[:16]`, and re-ingests idempotently
- [x] **PERF-02**: Engineer gets UTC-normalised sample timestamps derived from the PDH header's declared zone and offset (e.g. `(Eastern Standard Time)(300)`) with `ts_confidence` recorded, and no sample is silently dropped — blank, malformed, or non-numeric counter values are preserved as `severity="unknown"` and reflected in per-file parse coverage
- [x] **PERF-03**: Engineer sees perfmon events excluded from template dedup, embedding, clustering, and salience by source kind — a case's cluster output is byte-identical whether or not a perfmon CSV was ingested, while every perfmon sample remains individually citable by `event_id`

### Correlation

- [ ] **PERF-04**: Engineer sees each detected MCM denial episode annotated with its corroborating perfmon trend — counter values at denial time, slope across the window, and peak — computed over the **same auto-selected lead-up window MCM-04 already produces**, so the trend and the OID/Source/SID attribution describe an identical time span
- [ ] **PERF-05**: Engineer receives deterministic, machine-independent diagnostic flags for correlation hazards, including CSV/log time-window non-overlap (wrong timezone, host, or day), an always-zero `Total MCM Denial` counter across a window containing detected denials, and counter-set drift within a file

### Reporting

- [ ] **PERF-06**: Engineer can run `sift perfmon <case>` to get a standalone counter-trend report plus CSV export, working correctly when the case contains a perfmon CSV and no DSSErrors log at all

### Analysis Integration

- [ ] **PERF-07**: Engineer sees perfmon figures injected into `sift analyze` as **cited** evidence — figures computed before generation so the model cannot alter or invent them, `cited ⊆ prompted ⊆ store` preserved, and the prompt byte-identical to today's when no perfmon data is present
- [ ] **PERF-08**: Engineer is protected by a regression-gated golden perfmon eval case, so `sift eval` exits non-zero if correlation output degrades

## Future Requirements

Deferred beyond v1.2. Tracked, not in this roadmap.

### Correlation

- **PERFV2-01**: Recovery-trend analysis — counter behaviour *after* an episode resolves (blocked: no post-denial evidence exists in the current reference data; the Hartford CSV ends 6 s before the denial banner)
- **PERFV2-02**: Multi-host correlation across perfmon CSVs from several nodes in a cluster
- **PERFV2-03**: Perfmon-only anomaly detection independent of any MCM episode (trend breaks with no corresponding denial)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Charts, plots, or graphical trend rendering | Sift's outputs are Markdown/JSON/PDF text artefacts; a plotting dependency is unjustified against the boring-technology constraint |
| Binary PDH `.blg` input | The exported CSV is the artefact engineers actually collect and ship; binary PDH would need a Windows-only parser |
| Live/streaming perfmon tailing | v1 is batch analysis of collected artefacts — consistent with the project-level exclusion of `tail -f` ingestion |
| Correlating on the `Total MCM Denial` counter as a primary signal | Reads 0 across all 13,596 Hartford samples despite confirmed denials; it is reported as a flag (PERF-05), never trusted as an input |
| Downsampling perfmon samples on ingest | Breaks the byte-offset determinism contract and loses the resolution slope analysis needs |
| Inferring timezone by maximising CSV/log window overlap | A heuristic that can silently invent an alignment that isn't real; misalignment is flagged loudly instead (PERF-05) |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PERF-01 | Phase 12 | Complete |
| PERF-02 | Phase 12 | Complete |
| PERF-03 | Phase 12 | Complete |
| PERF-04 | Phase 13 | Pending |
| PERF-05 | Phase 13 | Pending |
| PERF-06 | Phase 13 | Pending |
| PERF-07 | Phase 14 | Pending |
| PERF-08 | Phase 14 | Pending |

**Coverage:**

- v1.2 requirements: 8 total
- Mapped to phases: 8 ✓
- Unmapped: 0 ✓

Phase numbering continues from v1.1 (which ended at Phase 11). Every requirement maps to exactly
one phase; no requirement appears in two phases.

## Reference Data

| Artefact | Path | Notes |
|----------|------|-------|
| Deny-case perfmon CSV | `/home/oliverh/Downloads/hartford/hartford_Linux_DenyDSSPerformanceMonitor16234.csv` | 13,596 samples, 22 counters (23 CSV fields incl. timestamp), ~30 s interval, 2026-04-02 19:21 → 2026-04-07 12:39 Eastern; ends 6 s before the denial banner |
| Deny-case log | `/home/oliverh/Downloads/hartford/hartford_linux_deny_.log` | MCM denials at 2026-04-07 12:39:45; same host `env-325602laio1use1`, PID 16234 |
| Snapshot-case perfmon CSV | `/home/oliverh/Downloads/hartford/hartford_linux_snapshot.csv` | 6,803 samples, same 23-counter set — second golden-case candidate |
| Snapshot/shutdown logs | `/home/oliverh/Downloads/hartford/hartford_Linux_snapshotDSSErrors (3).log`, `hartford_Linux_Shutdown_DSSErrors (3).log` | Pairs with the snapshot CSV |

**Observed lead-in trend (deny case), first sample → last sample:**

| Counter | Start | End (6 s pre-denial) |
|---------|-------|----------------------|
| `Working set cache RAM usage(MB)` | 27 | 266,042 |
| `System\RAM used(MB)` | 186,503 | 463,915 |
| `Process(MSTRSvr)\Size(MB)` | 104,821 | 401,603 |
| `Open Sessions` | 3 | 1,488 |
| `Total MCM Denial` | 0 | 0 (never increments) |

---
*Requirements defined: 2026-07-20*
*Last updated: 2026-07-20 — traceability populated by roadmap creation (Phases 12–14)*
