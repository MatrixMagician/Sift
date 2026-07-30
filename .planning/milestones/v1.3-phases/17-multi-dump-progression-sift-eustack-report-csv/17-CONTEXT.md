# Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV - Context

**Gathered:** 2026-07-25
**Status:** Ready for planning

<domain>
## Phase Boundary

One standalone command, `sift eustack <case>`, that renders the deterministic
analysis already computed in Phases 15–16 as a Markdown report plus a CSV
export, and — when a case holds more than one thread dump — reports
per-signature population progression across those dumps.

Delivers EUS-07 (single-dump full analysis; multi-dump per-signature deltas),
EUS-08 (ordering basis stated, unresolvable ordering flagged not assumed) and
EUS-09 (`sift eustack <case>` works with no DSSErrors log in the case).

**Not in this phase:** eu-stack figures inside `sift analyze` (Phase 18,
EUS-10), ranking exclusion and golden eval (Phase 19), any new analysis. The
`EustackAnalysis` and `SaturationAnalysis` models are frozen and consumed
read-only — this phase renders and compares, it does not compute new
diagnostics.
</domain>

<decisions>
## Implementation Decisions

### Dump ordering (EUS-08)

- **D-01:** Order dumps by the adapter's dump-time header timestamp when
  **every** dump in the case carries one. The report states the basis
  explicitly ("ordered by dump-time timestamp").
- **D-02:** When any dump lacks a header timestamp, fall back to sorted
  `source_file` order, state **that** basis explicitly in the report, and
  raise a loud flag that the ordering is unverified. Progression still
  renders under the flag — it is not suppressed. No timestamp is ever
  invented or inferred (ADR 0012 "record, don't apply" precedent).
- **D-03:** No operator `--order` override in this phase. The fallback is
  automatic-but-declared, not operator-authorised.

### CSV export (EUS-09)

- **D-04:** Exactly one CSV, `<case>/eustack/eustack_signatures.csv`, one row
  per signature — matching the shipped single-CSV-per-command precedent
  (`mcm_attribution.csv`, `perfmon_trend.csv`). — **Reversibility:** costly —
  the file name and column set become an operator-facing contract the moment
  it ships; adding a second CSV later is additive, but renaming or reshaping
  this one breaks scripts built on it.
- **D-05:** Columns: role, subsystem, matched pattern, frame index, reason,
  matched frame, leaf frame, thread count. In a multi-dump case, one count
  column per dump plus the delta columns from D-08.
- **D-06:** Every string cell carrying C++ symbol text goes through the
  existing `_csv_safe` guard (`src/sift/render/perfmon_report.py:203`) — it
  is reused, not reimplemented.

### Signature identity in output

- **D-07:** The report and CSV carry the **matched frame (with its index) and
  the leaf frame** — the two frames that explain the classification — never
  the full frames tuple. This preserves the "why did this thread read as
  idle-parked?" answer from the output alone (the Phase 16 `SignatureGroup`
  intent) without exporting cells full of C++ symbol text. No signature hash
  column.

### Progression (EUS-07)

- **D-08:** With 3+ dumps the report carries **both** consecutive-pair deltas
  (d1→d2, d2→d3, …) **and** an overall first→last delta, so a population
  that grew then shrank is visible in the report rather than only in the
  export.
- **D-09:** The Markdown progression section lists **only signatures whose
  thread count changed**, ranked by absolute delta, with newly-appeared and
  vanished signatures called out. Unchanged signatures remain in the CSV. No
  cap — the changed set is the natural bound.
- **D-10:** Progression is phrased strictly as signature-population change
  ("the blocked-on-warehouse population grew 79 → 141"). No per-TID claim,
  qualified or otherwise, appears anywhere — TID reuse is measured (9 exited
  / 10 new in 60 s on an idle server), so per-TID continuity is not
  establishable from the evidence.

### Multi-dump snapshot scope

- **D-11:** The classification and saturation sections (role composition,
  per-pool occupancy, lock convergence, dependency waits) are computed on the
  **last** dump — the state being diagnosed. Per-dump thread counts remain
  available in the CSV. One analysis section per report, never one per dump,
  and never a union of dumps (a union would read a 3,900-thread server as
  11,700).

### Carried forward (not re-decided here)

- **D-12:** Standalone contract, output directory `<case>/eustack/`,
  `--format json`, `--out` — follow the shipped `sift mcm` / `sift perfmon`
  CLI pattern verbatim (`src/sift/cli.py:1127`, `:1215`), including exit-0
  behaviour with no DSSErrors log present.
- **D-13:** Ownership-blind language throughout; the word "deadlock" never
  appears. Re-running on an unchanged case produces byte-identical report and
  CSV.

### Claude's Discretion

- Exact Markdown section ordering and table headings.
- How dumps are grouped out of the store (grouping thread events by
  `source_file` is the obvious seam, but the planner owns it).
- Whether progression lives in `pipeline/eustack.py` or a new leaf module —
  subject to the existing frozen-model constraint.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Prior-phase decisions this phase builds on
- `.planning/phases/16-saturation-contention-signature-collapse/16-CONTEXT.md` — pool/lock-site/dependency definitions, composition-only flags
- `.planning/phases/15-thread-role-taxonomy-rules-file/15-CONTEXT.md` — taxonomy and rules-file decisions
- `docs/decisions/0015-eustack-thread-role-taxonomy.md` — role taxonomy, rules file, classification contract
- `docs/decisions/0016-eustack-saturation-analysis.md` — per-pool occupancy, ownership-blind lock convergence, dependency split, flag grading

### Precedent this phase must follow
- `docs/decisions/0012-perfmon-naive-timestamps.md` — "record, don't apply": the precedent D-01/D-02 follow for ordering
- `src/sift/cli.py` §`mcm` (:1127), §`perfmon` (:1215) — standalone command contract, output dir, `--format`, `--out`, exit codes
- `src/sift/render/perfmon_report.py` — `_csv_safe` (:203), `write_perfmon_trend_csv` (:242), markdown/json renderers
- `src/sift/render/mcm_report.py` — `write_attribution_csv` (:229), flag/table rendering

### Contracts consumed read-only
- `src/sift/pipeline/eustack.py` — `EustackAnalysis` (:401), `SignatureGroup` (:382), `SaturationAnalysis` (:597), `analyse_eustack` (:419), `analyse_saturation` (:618)
- `src/sift/adapters/eustack.py` — dump-time header timestamp handling (:20, :58), `source_file` stamping (:178)

### Requirements
- `.planning/REQUIREMENTS.md` — EUS-07, EUS-08, EUS-09
- `.planning/ROADMAP.md` § Phase 17 — five success criteria
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_csv_safe` (`render/perfmon_report.py:203`): formula-injection guard that
  sanitises C1/bidi bytes before testing the first significant character —
  exactly the guard Phase 17 success criterion 5 requires for C++ symbol
  text. Reuse; do not reimplement.
- `write_attribution_csv` / `write_perfmon_trend_csv`: the shipped shape for
  a command that writes one CSV beside its report.
- `render_perfmon_markdown` / `render_perfmon_json` and their `mcm_report`
  twins: the two-renderer-per-analysis pattern.

### Established Patterns
- Analyses are frozen Pydantic models with `extra="forbid"`; renderers are
  pure functions over them. Phase 17 adds a renderer and (for progression) a
  new frozen model — it does not mutate Phase 15/16 models.
- Total ordering is explicit everywhere (`signatures` are already sorted
  `-thread_count, frames`); no set iteration, no `Counter.most_common()`.
  Progression ordering must be equally explicit for byte-identical re-runs.
- Standalone commands write `<case>/<name>/` and print a one-line summary.

### Integration Points
- New `sift eustack` command in `src/sift/cli.py`, alongside `mcm` and
  `perfmon`.
- New `src/sift/render/eustack_report.py` (markdown + json + CSV writer),
  mirroring `perfmon_report.py`.
- Dump grouping reads thread events from the case store by `source_file`; the
  adapter already stamps it.
</code_context>

<specifics>
## Specific Ideas

- Reference capture for validation: `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`
  — a real 3,902-thread, multi-file eu-stack capture taken a minute apart.
  This is the natural multi-dump progression case and the source of the
  measured TID-reuse figure (9 exited / 10 new in 60 s) behind D-10.
- Phrasing model for progression, from the discussion: "the
  blocked-on-warehouse population grew 79 → 141" — population-level, never
  thread-level.
</specifics>

<deferred>
## Deferred Ideas

- Operator-supplied ordering override (`--order file,file,...`) — considered
  and rejected for this phase (D-03); revisit only if a real case shows the
  declared filename fallback misleading an engineer.
- A stable per-signature hash column for joining rows across runs —
  considered and rejected (D-07); additive later if operators ask.
- Signature-count caps in the progression section — not needed while only
  changed signatures are listed (D-09).

### Reviewed Todos (not folded)
- `.planning/todos/pending/2026-07-21-embedding-batch-composition-determinism.md`
  — matched on keywords only; it is SEED-002/DET-01, already scoped as
  Phase 20. Not folded.
- `.planning/todos/pending/2026-07-21-generation-context-unset.md` — LLM
  generation config, unrelated to the deterministic eu-stack renderer. Not
  folded.
</deferred>

---

*Phase: 17-Multi-Dump Progression & `sift eustack` Report + CSV*
*Context gathered: 2026-07-25*
