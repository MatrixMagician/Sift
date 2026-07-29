# Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV - Research

**Researched:** 2026-07-25
**Domain:** Deterministic report/CSV rendering over frozen Pydantic analysis models; multi-file
grouping and ordering of already-ingested `Event` rows; stdlib CSV export with formula-injection
guarding.
**Confidence:** HIGH — every claim below was checked against the actual Sift source tree
(graphmind-indexed, 3270 symbols / 149 files, last build 2026-07-25) and its test suite, not
training-data recall. This is an internal-codebase-pattern phase, not a new-library phase.

## Summary

Phase 17 wires two things that already exist (`analyse_eustack`/`analyse_saturation` from Phases
15–16) into a third CLI command, following the `sift mcm` / `sift perfmon` command shape verbatim.
Nothing here needs a new dependency: it is `csv` (stdlib) + Pydantic + Typer, exactly as the
existing `mcm_report.py`/`perfmon_report.py` pair does. The two genuinely new pieces of logic are
(1) grouping already-ingested `Event` rows by `source_file` into per-dump populations and ordering
those dumps, and (2) a population-delta computation across that ordered sequence. Both have direct
precedent in `perfmon.py`'s `_file_scope_groups` (per-file grouping with a declared-vs-resolved
label) and in the shipped `SaturationFlag`/`PerfmonHazard` "graded structural condition" pattern.

Critically, `analyse_eustack`/`analyse_saturation` currently have **no CLI caller at all** — they
are exercised only by `tests/test_eustack_rules.py`. Phase 17 is the first time this pipeline gets
wired into `cli.py`, so the planner should treat the CLI-integration task as net-new work, not a
small addition to existing wiring.

The dump-time header timestamp is **already captured on every thread `Event`**, not just a
preamble record: `EustackAdapter.parse()` stamps `dump_ts`/`dump_ts_confidence` onto every
`_Record` at thread-header time (`adapters/eustack.py:215-223`) and `finish()` copies it straight
onto `Event.ts`/`Event.ts_confidence` (`adapters/eustack.py:172-191`). So "does every dump in the
case carry a header timestamp" is answerable by checking `ts_confidence != "missing"` on any one
thread event per `source_file` group — no new adapter work, no `raw`-text re-parsing needed.

**Primary recommendation:** Add `src/sift/render/eustack_report.py` (markdown + json + CSV writer,
mirroring `perfmon_report.py`'s three-function shape) and a `sift eustack` command in `cli.py`
placed after `perfmon` (~line 1306), reusing `_csv_safe` verbatim. Add one new frozen leaf module
`src/sift/pipeline/eustack_progression.py` for the dump-grouping/ordering/delta computation — a
new module rather than growing `pipeline/eustack.py` further, because progression consumes
`EustackAnalysis`/`SaturationAnalysis` read-only and operates on a different input shape (multiple
per-dump `Event` groups, not one flat list), and Phase 18 will import it independently of the
Phase 15/16 models.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dump grouping (partition events by `source_file`) | Pipeline (new leaf module) | Store (read-only `query_events()`) | Grouping is pure computation over already-hydrated events, not a store concern — mirrors `perfmon.py:_file_scope_groups` doing the identical partition in the pipeline layer, not `store.py` |
| Dump ordering + "unresolved" flag | Pipeline (new leaf module) | — | Pure function of per-dump `ts`/`ts_confidence`; no I/O |
| Progression (population deltas) | Pipeline (new leaf module) | — | New frozen model consuming `EustackAnalysis` read-only, one per dump |
| Markdown/JSON/CSV rendering | Render (`render/eustack_report.py`) | — | Pure `Analysis -> str`/`-> file`, no recompute — exact `perfmon_report.py`/`mcm_report.py` precedent |
| CLI orchestration, exit codes, bundle-dir write | CLI (`cli.py` `eustack` command) | — | Mirrors `mcm`/`perfmon` verbatim: `_case_store`, bundle dir under `case_db_path(...).parent / "eustack"`, partial-write cleanup on `OSError` |
| Formula-injection guard | Render (`_csv_safe`, reused) | — | Already exists at `perfmon_report.py:203`; do not reimplement |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EUS-07 | Full analysis from a single dump; per-signature population deltas with 2+ dumps | Dump-grouping seam (Q1), progression model shape (Q7) — both fully mapped to existing store/pipeline surfaces |
| EUS-08 | Dumps ordered without invented timestamps; basis stated; unresolvable ordering flagged loudly | Ordering source confirmed VERIFIED at `adapters/eustack.py:172-223`; flag-mechanism precedent from `SaturationFlag`/`PerfmonHazard` (Q2) |
| EUS-09 | `sift eustack <case>` — deterministic report + CSV, works with no DSSErrors log | Standalone contract precedent VERIFIED via `test_mcm_empty_case`/`test_no_dsserrors_log` (Q5); CSV/determinism contract (Q3/Q4) |
</phase_requirements>

## Standard Stack

### Core
No new dependencies. This phase is stdlib `csv` + Pydantic (already a dependency) + Typer (already
a dependency), exactly matching `render/perfmon_report.py` and `render/mcm_report.py`.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `csv` (stdlib) | 3.12+ | CSV writer | `write_perfmon_trend_csv`/`write_attribution_csv` precedent; `csv.excel.lineterminator` is fixed `'\r\n'` regardless of platform — [VERIFIED: python3 -c "import csv; print(repr(csv.excel.lineterminator))"], confirmed in this session |
| Pydantic | 2.13.x (already pinned) | Frozen progression model | Matches `EustackAnalysis`/`SaturationAnalysis`/`PerfmonAnalysis` `ConfigDict(frozen=True, extra="forbid")` convention |
| Typer | 0.27.0 (already pinned) | `sift eustack` command | Matches `mcm`/`perfmon` command shape |

### Supporting
None beyond what `mcm_report.py`/`perfmon_report.py` already import: `sift.render._util.sanitise`,
`sift.render.markdown._field`.

### Alternatives Considered
Not applicable — this phase's tooling is entirely fixed by existing project convention; there is no
library choice to make.

**Installation:** none — no `pyproject.toml` change.

## Package Legitimacy Audit

No external packages are introduced by this phase. Table omitted per the "required whenever this
phase installs external packages" rule — it does not.

## Architecture Patterns

### System Architecture Diagram

```
CaseStore.query_events()            (existing; ALL events, ts-ordered)
        |
        v
[filter e.source == "eustack"]      (new, in cli.py `eustack` command — mirrors
        |                            mcm's/perfmon's own store.query_events() +
        |                            in-Python source filter, e.g. perfmon.py:728)
        v
group_by_source_file(events)        (new leaf: pipeline/eustack_progression.py
        |                            mirrors perfmon.py:_file_scope_groups'
        |                            by_file.setdefault(event.source_file, [])
        |                            dict-order grouping, D-21 determinism)
        v
resolve_dump_order(dumps)  ---------+--> D-01: every dump's ts_confidence != "missing"
        |                           |         -> order by ts, state "ordered by
        |                           |            dump-time timestamp"
        |                           +--> D-02: any dump ts_confidence == "missing"
        |                                      -> order by sorted source_file,
        |                                         state that basis + raise a
        |                                         loud "ordering unverified" flag
        v
for each dump: analyse_eustack(dump_events, rules, rules_hash)   (existing, per-dump)
        |
        +--> analyse_saturation(LAST dump's EustackAnalysis, thresholds)  (D-11:
        |    classification/saturation computed on last dump ONLY)
        |
        v
compute_progression(ordered_analyses)   (new: consecutive-pair deltas D-08,
        |                                 overall first->last delta, changed-only
        |                                 filter D-09, newly-appeared/vanished)
        v
render_eustack_markdown / _json / write_eustack_signatures_csv   (new:
        render/eustack_report.py, mirrors render_perfmon_markdown/_json/
        write_perfmon_trend_csv three-function shape verbatim)
        |
        v
<case>/eustack/eustack_report.{md,json} + eustack_signatures.csv   (D-04/D-12)
```

### Recommended Project Structure
```
src/sift/
├── pipeline/
│   ├── eustack.py                 # UNCHANGED — Phase 15/16 frozen models, read-only
│   └── eustack_progression.py     # NEW — dump grouping, ordering, ProgressionAnalysis
├── render/
│   └── eustack_report.py          # NEW — markdown/json/csv, mirrors perfmon_report.py
└── cli.py                         # NEW `eustack` command, after `perfmon` (~:1306)
```

### Pattern 1: Per-file grouping with declared-vs-resolved label
**What:** `perfmon.py:_file_scope_groups` (lines 578-666) groups events by `Event.source_file`
into a `dict[str, list[Event]]` via `by_file.setdefault(event.source_file, []).append(event)`,
preserving first-appearance order (never a `set`), then computes figures per group and labels the
group with a constant (`FULL_RANGE_LABEL`) stating plainly what basis the figures rest on.
**When to use:** Directly reusable shape for Phase 17's dump grouping — swap the per-group figure
computation for `analyse_eustack(dump_events, rules, rules_hash)`.
**Example:**
```python
# Source: src/sift/pipeline/perfmon.py:602-605 (existing, verbatim pattern to mirror)
by_file: dict[str, list[Event]] = {}
for event in perfmon_events:
    by_file.setdefault(event.source_file, []).append(event)
```

### Pattern 2: Graded structural-condition record (not threshold-graded)
**What:** `PerfmonHazard` (`pipeline/perfmon.py:119-144`) — `dimension: str`, `severity: Literal`
fixed in code (not derived from a warn/critical cut-point pair), `message: str`, `event_ids`,
`value: float | None`. Contrast with `SaturationFlag` (`pipeline/eustack.py:486-521`), which is
explicitly a *graded-against-two-cut-points* record (`warn: float`, `critical: float` are required
fields) for a config-thresholded ratio or count.
**When to use:** "Ordering basis unresolved" is a structural fact (a dump either has a timestamp or
it doesn't), not a ratio against a configurable threshold — it has no natural `warn`/`critical`
pair. It is the `PerfmonHazard` shape, not the `SaturationFlag` shape. Do not force it into
`SaturationFlag` by inventing a fake `warn`/`critical` pair.
**Example:**
```python
# Source: src/sift/pipeline/perfmon.py:119-144
class PerfmonHazard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dimension: str
    severity: Literal["info", "warn", "critical"]
    message: str
    event_ids: tuple[str, ...]
    value: float | None = None
```

### Pattern 3: Standalone bundle-dir CLI command
**What:** `mcm()` (`cli.py:1127-1202`) and `perfmon()` (`cli.py:1215-1305`) both: load config, open
the store via `_case_store`, derive the bundle dir as
`case_db_path(config.data_dir, case).parent / "<name>"`, run the analysis, write report + CSV,
unlink both on `OSError` (report-before-CSV ordering means a mid-CSV failure could otherwise leave
a valid-looking report beside a truncated CSV), print a one-line summary, `finally: store.close()`.
**When to use:** `sift eustack` should follow this shape verbatim per D-12 (explicitly carried
forward, not re-decided).
**Example:**
```python
# Source: src/sift/cli.py:1159-1183 (mcm(), the pattern to mirror)
mcm_dir = case_db_path(config.data_dir, case).parent / "mcm"
analysis = analyse_mcm(store.query_events(), config.mcm.thresholds)
...
try:
    mcm_dir.mkdir(parents=True, exist_ok=True)
    (mcm_dir / report_name).write_text(report_text, encoding="utf-8")
    write_attribution_csv(analysis, mcm_dir / "mcm_attribution.csv")
except OSError as exc:
    for partial in (mcm_dir / report_name, mcm_dir / "mcm_attribution.csv"):
        partial.unlink(missing_ok=True)
    print(f"Error: cannot write MCM bundle to {mcm_dir}: {_sanitise(str(exc))}")
    raise typer.Exit(1) from None
```

### Anti-Patterns to Avoid
- **Re-deriving thread-dump-carries-a-timestamp logic from `Event.raw`:** the header timestamp is
  already on `Event.ts`/`Event.ts_confidence` for every thread event in the dump (see Q1 below).
  Do not re-scan `raw` text with a second regex.
- **Forcing "ordering unresolved" into `SaturationFlag`:** it has no threshold pair; use the
  `PerfmonHazard` shape (a new, phase-local equivalent) instead. See Pattern 2.
- **Growing `pipeline/eustack.py` for progression:** the file's own docstring states Phase 16 added
  a NEW frozen model consuming `EustackAnalysis` read-only, and `EustackAnalysis`/`SaturationAnalysis`
  are documented as "frozen and consumed read-only" (17-CONTEXT.md domain section). Progression's
  input shape (multiple per-dump analyses, not one) is different enough, and Phase 18's own note
  ("`eustack_facts.py` must stay a leaf module") signals the project's preference for leaf modules
  over one ever-growing `eustack.py`.
- **Embedding a wall-clock `generated_at` in the eustack report:** neither `mcm_report.py` nor
  `perfmon_report.py` embeds one — [VERIFIED via grep: no `datetime.now()`/`utcnow()` call in
  `render/mcm_report.py` or `render/perfmon_report.py`]. The only `generated_at` field in the
  codebase is `render/json_out.py:79`, which is for `sift report` and is explicitly excluded from
  the determinism hash (`DETERMINISM_EXCLUDED = ("generated_at",)`, `json_out.py:38`). Adding a
  timestamp to the eustack report would break D-13's byte-identical-rerun requirement outright —
  don't add one.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| C++ symbol text in a CSV cell reaching a spreadsheet as a formula | A second escaping function | `perfmon_report._csv_safe` (`render/perfmon_report.py:203-239`), imported | It is the exact guard D-06 names; reimplementing risks drifting from its `sanitise`-then-quote ordering, which is load-bearing (sanitise first, else a stripped-to-empty trigger sits behind the quote) |
| Markdown/HTML injection from log-sourced strings (matched pattern text, leaf frame) | A third escaping function | `render.markdown._field` (wraps `sanitise` + `_escape`), imported exactly as `mcm_report.py`/`perfmon_report.py` do | Single load-bearing escape path; two independent copies is exactly the drift risk IN-01 closed in Phase 11 |
| CSV row/field quoting | Manual string joins with commas | `csv.writer` | Already the house rule (`write_attribution_csv`'s own docstring: "never a manual join, so embedded delimiters/quotes are quoted correctly — T-10-13") |

**Key insight:** Every rendering primitive this phase needs (escaping, CSV writing, formula
guarding, bundle-dir write-then-cleanup) already exists and is imported by two prior renderers.
The phase's only genuinely new code is the dump-grouping/ordering/progression pipeline layer.

## Common Pitfalls

### Pitfall 1: Treating `analyse_eustack`/`analyse_saturation` as already CLI-wired
**What goes wrong:** Assuming a small integration diff because "the analysis already exists".
**Why it happens:** Phases 15/16 built the full pipeline and it is 100% test-covered — but
[VERIFIED via grep across `src/sift/` and `tests/`]: `analyse_eustack`/`analyse_saturation` have
**zero callers outside `tests/test_eustack_rules.py`**. No `cli.py` import, no `EustackConfig`
consumption anywhere except the config schema itself.
**How to avoid:** Plan the CLI wiring (config load, rules load via `load_rules(config.eustack.rules_path)`,
thresholds via `config.eustack.thresholds`, event filtering, bundle-dir write) as net-new work with
its own task, not a one-line addition.
**Warning signs:** A plan that estimates the CLI command as "trivial" because the analysis exists.

### Pitfall 2: Assuming the dump-time timestamp lives only in a preamble/fallback event
**What goes wrong:** Writing a query that looks for `ts` only on the fallback/preamble `Event`
(`thread is None`) and missing it on thread events, or re-parsing `raw` text for a timestamp.
**Why it happens:** The adapter docstring talks about "the preamble" carrying the timestamp scan,
which reads like the *timestamp lives on the preamble event only*.
**How to avoid:** `finish()` (`adapters/eustack.py:164-191`) builds every `Event` — thread and
fallback alike — from `rec.ts`/`rec.ts_confidence`, and `_Record` construction at a `TID` header
(`adapters/eustack.py:215-223`) sets `ts=dump_ts, ts_confidence=dump_ts_confidence` explicitly —
the dump-time value captured while scanning the preamble is copied onto every subsequent thread
record. So: pick any one thread event per `source_file` group and read `.ts`/`.ts_confidence`
directly; do not special-case the preamble event.
**Warning signs:** A plan step that says "find the preamble event for each dump".

### Pitfall 3: A `.csv` byte-identity break from platform-dependent line endings
**What goes wrong:** Explicitly setting `lineterminator="\n"` or `os.linesep` "to be safe",
inadvertently making CSV output diverge from `write_perfmon_trend_csv`'s established byte shape,
or — worse — worrying about a genuine platform-dependence risk that does not actually exist.
**Why it happens:** `csv.writer`'s default (`excel` dialect) uses `\r\n`, which superficially looks
platform-dependent but is actually fixed by the dialect, not by `os.linesep`.
**How to avoid:** [VERIFIED this session: `python3 -c "import csv; print(repr(csv.excel.lineterminator))"` → `'\r\n'`
on this Linux runtime, same as it would be on any platform — it is a dialect constant]. Do not pass
a `lineterminator=` override; match `write_perfmon_trend_csv`'s existing `csv.writer(fh)` call
exactly (`render/perfmon_report.py:254`), with `path.open("w", newline="", encoding="utf-8")`.
**Warning signs:** Any `lineterminator=` kwarg appearing in the new CSV writer that isn't in the
two existing ones.

### Pitfall 4: Building the two-dump-progression test fixture from the shipped derivative
**What goes wrong:** Reusing `tests/fixtures/eustack/reference_capture_derivative.txt` as one half
of a two-dump progression fixture without accounting for its known non-properties.
**Why it happens:** It's the only large committed eustack fixture, so it's the obvious reach.
**How to avoid:** [VERIFIED]: `reference_capture_derivative.txt` was derived from only the
**earlier** of two real reference dumps (`derive_reference_capture_derivative.py:23`, "run this
script against the earlier ('160739') of the two reference dumps") and is signature-preserving but
NOT thread-weight-preserving (16-04-PLAN.md §S-8: 105 threads vs the real capture's 3,902 — a
28x-inflated unclassified share). It also carries **no dump-time header timestamp** — its preamble
is synthetic dashed-comment lines, not an ISO-8601 stamp `_TS_RE` would match — [VERIFIED: `head -5
tests/fixtures/eustack/reference_capture_derivative.txt` shows `-- derived, sanitised eu-stack
fixture --`, not a timestamp]. `tests/fixtures/eustack/threaddump.txt`, by contrast, DOES carry a
real header timestamp (`2026-07-18T09:15:30+00:00`, line 2). Neither of these on its own is a
second dump — a genuine multi-dump fixture must be authored fresh (see Environment/Fixtures below).
**Warning signs:** A plan step that says "split the derivative into two dumps" — it is one dump's
worth of data derived from one file; there is no second dump's data to split out of it.

### Pitfall 5: Assuming the real captured reference dumps carry header timestamps
**What goes wrong:** Designing the two-dump progression logic around the D-01 (timestamp-ordered)
path as the "normal" case, with D-02 (fallback) treated as an edge case.
**Why it happens:** It reads as the more complete/happy path.
**How to avoid:** [VERIFIED: `head -5` of the real out-of-repo reference capture at
`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/stack_env-...-160739....txt` shows the file
opens directly with `PID <n> - process` / `TID <n>:` — **no ISO-8601 preamble line at all**]. The
two real reference dumps (filenames encode `160739`/`160837`, one minute apart per the CONTEXT
doc's own framing) are the D-02 fallback case, not D-01. Any manual validation pass against the
real capture (per the CONTEXT `<specifics>` reference) will exercise D-02, sorted-`source_file`
ordering and the loud unresolved-ordering flag — not D-01. Plan and test D-02 as the primary path
demonstrated by real data, D-01 as the alternate path that needs its own synthetic fixture.
**Warning signs:** A plan that only builds a synthetic fixture for D-01 and validates D-02 solely
by code inspection.

## Code Examples

### Filtering to eustack-sourced events before analysis
```python
# Source: src/sift/pipeline/perfmon.py:728 (existing, the source-filter precedent)
groups = _file_scope_groups([e for e in events if e.source == "dssperfmon"])
# Mirror for eustack:
eustack_events = [e for e in store.query_events() if e.source == "eustack"]
```

### CSV writer shape to mirror exactly
```python
# Source: src/sift/render/perfmon_report.py:253-255
with path.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(HEADER)
```

### `_csv_safe` — reuse verbatim, do not reimplement
```python
# Source: src/sift/render/perfmon_report.py:203-239 — import this function,
# do not copy its body. Sanitise-then-quote ordering is load-bearing (see
# its own docstring for why quoting-first would be wrong).
from sift.render.perfmon_report import _csv_safe
```

## State of the Art

Not applicable — no external ecosystem shift is relevant here. The only "state of the art" fact is
internal: this is the first CLI wiring of a pipeline stage that has existed, fully tested, since
Phase 15/16 (see Pitfall 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommending a new `pipeline/eustack_progression.py` leaf module (rather than extending `pipeline/eustack.py`) is the right call, given CONTEXT.md explicitly leaves this to "Claude's Discretion" | Recommended Project Structure, Anti-Patterns | Low — it is an internal code-organisation choice, reversible with a file move; no behavioural or contract impact either way, and CONTEXT.md itself frames it as open |
| A2 | A `PerfmonHazard`-shaped (not `SaturationFlag`-shaped) record is the right carrier for "ordering unresolved" | Pattern 2, Q2 discussion | Low-medium — if the planner instead threads a plain `bool`/`str` pair through the progression model without a dedicated record type, the report can still satisfy EUS-08's wording requirement; this is a structural preference, not a correctness requirement |

**If this table is empty:** N/A — two low-risk organisational assumptions are logged above; every
factual/behavioural claim in this document is `[VERIFIED]` against the actual source tree or test
suite in this session.

## Open Questions

1. **Exact progression-model field shape (thread-count-only vs richer per-signature identity).**
   - What we know: D-07 fixes the identity carried in report/CSV output (matched frame + index,
     leaf frame, no full frames tuple, no hash column). D-08/D-09/D-10 fix what's shown (changed
     signatures only, consecutive-pair + first→last deltas, population-phrased).
   - What's unclear: whether the progression model should carry the full `SignatureGroup` per dump
     (frames tuple included, for internal joining) or only the D-07-restricted projection, with the
     restriction applied at render time instead.
   - Recommendation: carry the frames tuple internally (needed to join the same signature across
     dumps — `frames` is the natural join key, not the D-07-restricted display fields, which are
     lossy/ambiguous as a join key) and apply the D-07 projection only in the renderer. This mirrors
     how `EustackAnalysis.signatures` already carries full `frames` while the CSV need not export
     the full tuple.

2. **Where the eustack-events-vs-DSSErrors-events filter should live: cli.py or a pipeline helper.**
   - What we know: `mcm`/`perfmon` both filter inline in `cli.py`/`analyse_perfmon` (`e.source ==
     "dssperfmon"` at `perfmon.py:728`), not via a store-level filter.
   - What's unclear: whether `store.query_events()` (no filter args) should gain a `source=` filter
     parameter, given three callers now do the same in-Python filter independently.
   - Recommendation: keep filtering in-Python at the call site, matching existing precedent exactly
     (D-12 says "follow the shipped CLI pattern verbatim"); do not add a new store filter parameter
     as an unrequested abstraction for a third occurrence of a two-line filter.

## Environment Availability

Skipped — this phase has no external tool/service dependency beyond what `mcm`/`perfmon` already
require (a working `CaseStore`/SQLite, already verified operational by every prior phase's test
suite). No new runtime, package manager, or network dependency is introduced.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already configured; `uv run pytest`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (existing) |
| Quick run command | `uv run pytest tests/test_cli_eustack.py tests/test_eustack_progression.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EUS-07 | Single-dump case yields full classification+saturation; two-dump case yields per-signature deltas | unit | `pytest tests/test_eustack_progression.py -x` | ❌ Wave 0 |
| EUS-08 | Ordering basis stated; D-01 (all-timestamped) vs D-02 (fallback + loud flag) paths | unit | `pytest tests/test_eustack_progression.py -k order -x` | ❌ Wave 0 |
| EUS-09 | `sift eustack <case>` standalone contract: exit 0, no DSSErrors log, empty-case exit 0 | integration (CliRunner) | `pytest tests/test_cli_eustack.py -x` | ❌ Wave 0 |
| D-06 (CSV safety) | C++ symbol text through `_csv_safe`; formula-injection guard | unit | `pytest tests/test_eustack_report.py -k csv_safe -x` | ❌ Wave 0 |
| D-13 (byte-identity) | Two runs produce byte-identical report + CSV | integration | `pytest tests/test_cli_eustack.py -k byte_identical -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_eustack_progression.py tests/test_eustack_report.py tests/test_cli_eustack.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** Full suite green (`ruff check`, `pyright`, `pytest`) before `/gsd-verify-work`, per project CLAUDE.md "done" definition.

### Wave 0 Gaps
- [ ] `tests/test_eustack_progression.py` — covers EUS-07/EUS-08 (dump grouping, ordering, D-01/D-02
      paths, delta computation, changed-only filter)
- [ ] `tests/test_eustack_report.py` — covers markdown/json/CSV rendering, `_csv_safe` reuse, D-07
      identity projection
- [ ] `tests/test_cli_eustack.py` — covers EUS-09 standalone contract (mirrors `test_cli_mcm.py` /
      `test_cli_perfmon.py` shape: `test_eustack_writes_bundle`, `test_eustack_empty_case`,
      `test_eustack_no_dsserrors_log`, `test_eustack_byte_identical_rerun`, `test_eustack_missing_case`)
- [ ] A genuine two-file (multi-dump) test fixture under `tests/fixtures/eustack/` — see Pitfall 4;
      neither existing fixture is a second dump of the same population. Needs at minimum: (a) a
      pair where BOTH dumps carry a header timestamp (exercises D-01), and (b) a pair where at
      least one lacks one (exercises D-02) — the real reference captures already demonstrate case
      (b) empirically (see Pitfall 5) but are not committed to the repo (2.4 MB each, customer
      environment identifiers) and must not be copied in verbatim; a small synthetic pair modelled
      on their shape (some signatures growing, some shrinking, some appearing/vanishing, TID reuse
      pattern) is the right fixture, built the same deliberate-authored-not-observed way
      `derive_reference_capture_derivative.py` built the existing one.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A — local CLI tool, no auth surface |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A — single-operator local case store |
| V5 Input Validation | yes | Bundle-dir path derived from `case_db_path` (already containment-checked, per `_case_store`), never from user-supplied path segments — mirrors mcm/perfmon's own `T-10-14`/`T-13-PATH` comments |
| V6 Cryptography | no | N/A — no crypto in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| CSV formula injection from C++ symbol text (matched/leaf frame strings originate in the customer's binary/log) | Tampering | `_csv_safe` — reused verbatim from `render/perfmon_report.py:203` (already the documented control for exactly this attacker-influenceable-cell scenario) |
| Terminal escape / bidi-override injection via stdout summary line or Markdown report (symbol text can carry arbitrary bytes) | Tampering | `render._util.sanitise` + `render.markdown._field`, reused verbatim, exactly as `mcm_report.py`/`perfmon_report.py` already do for their own log-sourced strings |
| Path traversal via a crafted `source_file`/case argument | Tampering | Already closed upstream by `_case_store`/`case_db_path`'s containment assertion (T-10-14 precedent) — the eustack command inherits this by construction, doing nothing new with the path |

## Sources

### Primary (HIGH confidence — direct source-tree inspection this session)
- `src/sift/adapters/eustack.py` (full file read) — dump-time timestamp capture and propagation onto every thread `Event`
- `src/sift/pipeline/eustack.py` (outline + `SignatureGroup`/`EustackAnalysis`/`SaturationFlag`/`SaturationAnalysis` read in full) — frozen models, `analyse_eustack`/`analyse_saturation` contracts
- `src/sift/pipeline/perfmon.py` (`_file_scope_groups`, `_unattributed_group`, `analyse_perfmon`, `PerfmonHazard`, `TrendGroup`, `PerfmonAnalysis` read in full) — per-file grouping precedent, structural-hazard record shape
- `src/sift/render/perfmon_report.py` (full file, lines 1-280) — `_csv_safe`, `write_perfmon_trend_csv`, three-function renderer shape
- `src/sift/render/mcm_report.py` (lines 1-80) — CSV header pattern, docstring conventions
- `src/sift/cli.py` (`mcm` :1127-1202, `perfmon` :1215-1305 read in full) — standalone command contract, exit-code/bundle-write pattern
- `src/sift/store.py` (`query_events` :573-598, full outline) — confirmed no source-filter parameter exists; all callers filter in Python
- `src/sift/config.py` (`EustackConfig` :149-156) — `rules_path`/`thresholds` config surface
- `src/sift/models.py` (`Event` dataclass :18-35) — field inventory (`ts`, `ts_confidence`, `source`, `source_file`, `thread`, `raw`)
- `docs/decisions/0012-perfmon-naive-timestamps.md` (full file) — the "record, don't apply" precedent D-01/D-02 explicitly follow
- `tests/test_cli_mcm.py:88-99` (`test_mcm_empty_case`), `tests/test_cli_perfmon.py:316-336` (`test_no_dsserrors_log`) — VERIFIED empirical proof of the standalone-no-source-artefact exit-0 contract
- `tests/fixtures/eustack/derive_reference_capture_derivative.py` (full file) + `reference_capture_derivative.txt`/`threaddump.txt` (headers read) — fixture provenance and known non-properties
- `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/*.txt` (headers read, `head -5`) — confirmed the real two-dump reference capture has no embedded header timestamp (exercises D-02, not D-01)
- `.planning/phases/16-saturation-contention-signature-collapse/16-04-PLAN.md` §S-8 (read) — derivative fixture's signature-preserving/thread-weight-not-preserving property
- Direct shell verification this session: `python3 -c "import csv; print(repr(csv.excel.lineterminator))"` → `'\r\n'`

### Secondary (MEDIUM confidence)
None used — every claim traced to a primary source above.

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; every tool already pinned and in use by the two sibling renderers
- Architecture: HIGH — every pattern cited has a direct file:line precedent read in full this session
- Pitfalls: HIGH — each pitfall is backed by a specific grep/read verification (zero CLI callers, real-capture header absence, csv dialect constant), not inference

**Research date:** 2026-07-25
**Valid until:** No expiry driver — internal codebase patterns, not an external library surface. Re-check only if Phase 15/16 models change before Phase 17 executes.
