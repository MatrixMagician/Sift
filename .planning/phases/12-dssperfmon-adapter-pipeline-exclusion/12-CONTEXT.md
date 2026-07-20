# Phase 12: `dssperfmon` Adapter & Pipeline Exclusion - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning
**Mode:** `--auto` (all gray areas auto-resolved to the recommended option; see DISCUSSION-LOG.md)

<domain>
## Phase Boundary

Ingest a DSSPerformanceMonitor PDH-CSV export as deterministic, individually citable,
UTC-normalised time-series events — and hold those events out of template dedup, embedding,
clustering and salience by source kind, so a case's cluster output is byte-identical whether or
not a perfmon CSV was ingested.

**In scope:** new `dssperfmon` adapter module + registry line; PDH header sniff; UTC
normalisation from the declared header zone/offset; per-sample-row `Event` emission with
deterministic `event_id`; `severity="unknown"` fallback for malformed rows; per-file parse
coverage; a single source-kind exclusion predicate applied at one seam.

**Out of scope (belongs to Phases 13/14):** any correlation against MCM episodes, slope/peak
computation, hazard flags, the `sift perfmon` command, prompt/fact injection, golden eval case.
Also out of scope project-wide: downsampling on ingest, binary `.blg` input, charts, timezone
inference by window-overlap maximisation.

</domain>

<decisions>
## Implementation Decisions

### Event shape & granularity

- **D-01:** One `Event` per sample row — locked by roadmap criterion 1. `event_id =
  sha256(source_file, byte_offset)[:16]` where `byte_offset` is the 0-based offset of the row's
  first byte in the DECOMPRESSED stream, exactly as `dsserrors`/`genericlog` already compute it.
  The header line is not an event.
- **D-02:** `raw` holds the verbatim CSV line (citation evidence, byte-for-byte). `message` holds
  a compact deterministic `name=value` rendering using **short counter names** — the leaf segment
  after the final `\` of the PDH column path, including its instance qualifier (e.g.
  `Working set cache RAM usage(MB)=266042`). The repeated `\\host\Category(Instance)\` prefix is
  NOT repeated per row; the host is recorded once per event in `component` and `attrs`.
- **D-03:** `attrs` carries the full parsed row as `{short_counter_name: value_string}` for all
  columns, plus `host`, `pdh_version` (`"4.0"`), `tz_name` (verbatim header zone string) and
  `tz_offset_min` (the declared numeric bias). Values stay strings — `attrs` is `dict[str, str]`
  on the frozen `Event` contract; numeric parsing belongs to Phase 13's correlator.
- **D-04:** `source = "dssperfmon"` (the adapter/registry name, matching the phase title).
  `component` = the host from the PDH column paths (e.g. `env-325602laio1use1`).
  `thread` / `session` = `None`. `line_start == line_end` (a sample row is one line).
- **D-05:** A fully-parsed row is `severity="info"`. Perfmon rows are observations, not
  diagnostics — the adapter never infers severity from counter magnitude. Threshold judgement is
  the correlator's job (Phase 13), never the parser's.

### Pipeline exclusion seam (PERF-03 — the phase's main hazard)

- **D-06:** **The exclusion lives in exactly one place: `CaseStore.iter_event_summaries()`**
  (`src/sift/store.py:631`). Scouting confirmed this single method is the sole read seam feeding
  every stage PERF-03 names:
  - `pipeline/dedup.py:102` — `rebuild_template_groups`
  - `pipeline/cluster.py:113` — `_exemplar_messages`
  - `pipeline/hypothesise.py:191` — excerpt gathering
  - `eval/runner.py:63`

  Salience (`pipeline/salience.py`) ranks `Cluster`/`TemplateGroup` rows built from those groups
  and never touches events directly, so exclusion at this seam cascades to it automatically.
  Filtering here means **one edit**, not four — satisfying the roadmap's "exclusion predicate
  should live in one place rather than being re-implemented per stage" constraint literally.

- **D-07:** Implement as a `WHERE source NOT IN (...)` on that one query, driven by a
  module-level `EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon"})` constant.
  Prefer a single named constant over a per-call parameter: the exclusion is a property of the
  source kind, not of the caller, and a parameter would let a future caller silently opt out and
  reintroduce the regression criterion 4 guards against.

- **D-08:** **`iter_event_rows()` (`store.py:644`), `get_events`, and every by-`event_id`
  retrieval path stay UNFILTERED.** This is the load-bearing half of criterion 5: perfmon samples
  are excluded from *ranking*, never from *citation* or `sift show events`. The two methods sit
  adjacent in `store.py` and read almost identically — the plan must guard against "tidying" them
  into a shared filtered helper. A test asserting `iter_event_rows` still yields perfmon rows
  belongs beside the exclusion test.

- **D-09:** Criterion 4's guard (byte-identical cluster output with and without the perfmon CSV)
  is a **test**, not a manual check: ingest a fixture case twice — once with the CSV, once
  without — and assert the `sift show clusters` output and the `template_groups` table are
  byte-identical. This is the phase's primary regression gate against v1.0/v1.1 output.

### Timezone & UTC normalisation

- **D-10:** Trust the PDH header's declared numeric bias verbatim. The header
  `"(PDH-CSV 4.0) (Eastern Standard Time)(300)"` declares 300 = minutes WEST of UTC, so
  `UTC = local + 300 min`. Apply that offset directly. Do **not** map the Windows zone name
  (`Eastern Standard Time`) to an IANA zone — that needs a mapping table plus DST resolution, and
  the declared offset already answers the question.
- **D-11:** `ts_confidence = "exact"` for rows whose timestamp parses and whose header offset is
  present — the offset is *declared by the artefact*, not inferred by Sift. If the header carries
  no parseable offset, fall back to UTC with `ts_confidence = "inferred"` and record a
  `ParseStats.notes` disclosure (the D-05 tz-disclosure convention `base.py` already establishes).
- **D-12:** Route through `base.to_utc` / `base.tz_override_for` so a `--tz glob=Zone` override
  still wins, consistent with every other adapter. Timestamp format is
  `MM/DD/YYYY HH:MM:SS.fff` (US, from the observed reference file).
- **D-13:** ⚠ **VERIFY DURING PLANNING — 1-hour DST risk.** PDH's declared bias is the
  *standard-time* bias (300), but the reference file spans 2026-04-02 → 04-07, which is Eastern
  *Daylight* Time (actual offset 240). If PDH writes local wall-clock timestamps while declaring
  the standard bias, every sample lands 1 hour off, which would silently break Phase 13's
  correlation. The roadmap's own claim that "the CSV ends 6 s before the denial banner" implies
  the current interpretation aligns — the researcher must confirm this against the real CSV/log
  pair before the parser freezes. **Resolution rule if it does not hold:** disclose in
  `ParseStats.notes` and flag loudly (Phase 13's non-overlap flag) — never silently DST-correct,
  because inferring an alignment that isn't declared is exactly what REQUIREMENTS.md § Out of
  Scope forbids.

### Nothing-disappears fallback (PERF-02 / criterion 3)

- **D-14:** Follow criterion 3 literally at row granularity: if **any** counter cell in a row is
  blank, non-numeric, or otherwise malformed, that row's event is emitted with
  `severity="unknown"` — never dropped — with the offending column names recorded in `attrs`
  (e.g. `unparsed_columns`). The row's bytes count into `ParseStats.unknown_fallback_bytes`, so
  per-file coverage reflects the loss.
- **D-15:** A row whose **timestamp** is unparseable gets `severity="unknown"`, `ts=None`,
  `ts_confidence="missing"`, `raw` preserved verbatim. A missing timestamp never suppresses the
  event.
- **D-16:** A row whose **column count differs from the header** is emitted as
  `severity="unknown"` with `raw` preserved and a `ParseStats.notes` entry. Phase 12 must survive
  counter-set drift; *flagging* drift as a diagnostic hazard is Phase 13's PERF-05 and is not
  implemented here.
- **D-17:** Note for the researcher: the reference deny CSV (13,596 samples) contains **zero**
  blank or non-numeric counter cells — every value parses. The unknown-fallback paths therefore
  need **synthetic fixtures**; they cannot be exercised by the reference artefact alone.

### Sniffing & registration

- **D-18:** Sniff on the literal `(PDH-CSV 4.0)` token at the start of the decompressed head via
  `base.read_head`. This is unambiguous — no other adapter can match it — so return a high
  confidence (well above `SNIFF_THRESHOLD` 0.5) and 0.0 otherwise. Criterion 2 requires detection
  with no `--adapter` override.
- **D-19:** Registration is one line in `src/sift/adapters/__init__.py` `REGISTRY`. Subclass
  `base.ConfigurableAdapter` (per ADR 0006) so the ingest orchestrator delivers
  `input_root`/`tz_overrides` and reads back `last_stats` uniformly.
- **D-20:** Use stdlib `csv` for parsing — the format is genuinely quoted CSV with embedded
  backslashes and parens. **Constraint:** byte offsets must still be computed on the raw byte
  stream (`offset += len(byte_line)`), so the parser reads byte lines for offset accounting and
  hands decoded text to `csv.reader` per row. Do not let `csv`'s own file iteration own the read
  loop, or `event_id` determinism breaks. This mirrors how `dsserrors` reuses
  `genericlog.byte_lines`.

### Claude's Discretion

Auto-mode selected the recommended option throughout. The planner retains discretion on:
module-internal decomposition of `adapters/dssperfmon.py`; exact `attrs` key spellings; fixture
file naming; whether the exclusion constant lives in `store.py` or a small shared module imported
by it.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § Phase 12 — goal, 5 success criteria, cross-cutting integration-risk note
- `.planning/REQUIREMENTS.md` § Ingestion (PERF-01, PERF-02, PERF-03) — requirement text
- `.planning/REQUIREMENTS.md` § Out of Scope — no downsampling, no `.blg`, no tz inference by overlap
- `.planning/REQUIREMENTS.md` § Reference Data — artefact paths, 23-counter set, observed lead-in trend
- `.planning/STATE.md` § Blockers/Concerns — the Phase 12 cross-cutting-regression entry

### Architecture decisions
- `docs/decisions/0006-configurable-adapter.md` — the `ConfigurableAdapter` pattern every adapter subclasses
- `docs/decisions/0003-hand-rolled-masking-over-drain3.md` — dedup masking the exclusion bypasses

### Code the phase touches or mirrors
- `src/sift/adapters/base.py` — frozen `Adapter` Protocol, `ConfigurableAdapter`, `ParseStats`, `open_bytes`, `read_head`, `to_utc`, `tz_override_for`
- `src/sift/adapters/__init__.py` — `REGISTRY`, `detect()`, `SNIFF_THRESHOLD`
- `src/sift/adapters/dsserrors.py` — closest structural analog (byte-offset accounting, unknown-fallback, tz path)
- `src/sift/models.py:18-47` — frozen `Event` dataclass + `event_id()`
- `src/sift/store.py:631` `iter_event_summaries` — **the exclusion seam (D-06)**
- `src/sift/store.py:644` `iter_event_rows` — **must stay unfiltered (D-08)**
- `src/sift/pipeline/dedup.py:102`, `src/sift/pipeline/cluster.py:113`, `src/sift/pipeline/hypothesise.py:191`, `src/sift/eval/runner.py:63` — the four consumers of the seam
- `src/sift/pipeline/salience.py:126` `rank_clusters` — consumes clusters/groups only; inherits exclusion transitively

### Reference artefacts (real data, read-only)
- `/home/oliverh/Downloads/hartford/hartford_Linux_DenyDSSPerformanceMonitor16234.csv` — 13,596 samples, 23 counters, header `"(PDH-CSV 4.0) (Eastern Standard Time)(300)"`
- `/home/oliverh/Downloads/hartford/hartford_linux_deny_.log` — the paired DSSErrors log (denials 2026-04-07 12:39:45)
- `/home/oliverh/Downloads/hartford/hartford_linux_snapshot.csv` — 6,803 samples, same counter set

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `base.ConfigurableAdapter` — per-run `input_root` / `tz_overrides` / `last_stats`; subclass it (ADR 0006)
- `base.open_bytes` / `base.read_head` — decompression + sniff over DECOMPRESSED bytes, gzip/zstd handled
- `base.to_utc` / `base.tz_override_for` — the single shared UTC path (D-05 convention); use it, don't hand-roll
- `base.ParseStats` — `total_bytes` / `unknown_fallback_bytes` / `event_count` / `notes`, with a `coverage` property; PERF-02's coverage requirement needs no new machinery
- `genericlog.byte_lines` — byte-line splitter with `MAX_EVENT_BYTES` force-split, already reused by `dsserrors`
- `models.event_id(source_file, byte_offset)` — frozen; call it, never reimplement

### Established Patterns
- **Adapter self-containment (SPEC §5.2):** new module + one `REGISTRY` line. Phase 12 deliberately
  breaks this once, for the exclusion — that break must be confined to the single seam in D-06.
- **Byte offsets on the decompressed byte stream** (`offset += len(byte_line)`) — determinism contract
- **Anchored, linear-scan regexes only** — no nested quantifiers (the no-ReDoS discipline in `dedup.py` and `dsserrors.py`)
- **Recompute-from-store idempotence:** `rebuild_template_groups` recomputes ALL groups from the store, so
  the exclusion takes effect on the next rebuild with no migration
- **Canonical ordering** `ORDER BY ts IS NULL, ts, source_file, line_start` — byte-stable output across runs
- **`store.py` owns all SQL**; pipeline modules are SQL-free, typer-free, print-free

### Integration Points
1. `src/sift/adapters/dssperfmon.py` — new module (the only genuinely new file)
2. `src/sift/adapters/__init__.py` `REGISTRY` — one registration line
3. `src/sift/store.py` `iter_event_summaries` — the one-line-ish `WHERE source NOT IN (...)` exclusion + its constant
4. Tests: sniff/parse/idempotence, unknown-fallback (synthetic fixtures per D-17), tz/UTC,
   cluster-byte-identity regression (D-09), and `iter_event_rows`-still-unfiltered (D-08)

</code_context>

<specifics>
## Specific Ideas

- Real header verified this session:
  `"(PDH-CSV 4.0) (Eastern Standard Time)(300)","\\env-325602laio1use1\System\Total CPU",...`
- Real sample row shape verified: `"04/02/2026 19:21:38.236","0","186503",...` — 23 counters, all
  numeric, no blanks anywhere in the file; ~30 s interval; 13,596 data rows.
- Counter names carry instance qualifiers in parens (`Process(MSTRSvr)`,
  `MicroStrategy Server Users(CastorServer)`) and units in the leaf (`(MB)`, `(KB)`) — the short-name
  extraction in D-02 must keep both.
- `Total MCM Denial` is present in the counter set and reads 0 throughout. Phase 12 ingests it like
  any other counter; treating it as a flag/hazard is Phase 13's PERF-05.

</specifics>

<deferred>
## Deferred Ideas

- **Counter-set drift *flagging*** — Phase 12 only survives it (D-16); PERF-05 flags it in Phase 13
- **`Total MCM Denial` always-zero hazard flag** — Phase 13 (PERF-05)
- **Any slope/peak/at-denial computation** — Phase 13 (PERF-04)
- **`sift perfmon` command + CSV export** — Phase 13 (PERF-06)
- **Perfmon facts in `sift analyze`, golden eval case** — Phase 14 (PERF-07, PERF-08)
- **Perfmon fact-block size cap** — Phase 14; 13,596 samples per file needs a bound equivalent to
  Phase 11's 8-episode MCM cap

### Reviewed Todos (not folded)
- **Phase 11 code-review INFO follow-ups (non-blocking)**
  (`.planning/todos/pending/2026-07-20-phase11-code-review-info.md`) — matched Phase 12 at score 0.9
  on the `pipeline` area, but its own frontmatter carries `resolves_phase: 14` and both items
  (IN-01 shared granted-MB formatter in `mcm_facts.py`; IN-03 cosmetic regex/whitespace tidy in
  `hypothesise.py`) touch MCM fact-splicing code Phase 12 does not modify. **Not folded** — left
  for Phase 14 as tagged. The keyword match was a false positive on the shared word "pipeline".

</deferred>

---

*Phase: 12-dssperfmon-adapter-pipeline-exclusion*
*Context gathered: 2026-07-20*
