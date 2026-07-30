# Phase 17: Multi-Dump Progression & `sift eustack` Report + CSV - Pattern Map

**Mapped:** 2026-07-25
**Files analyzed:** 8 (2 new source, 1 new leaf pipeline module, 1 fixture pair, 4 test files — 1 CONTEXT-decided, rest RESEARCH-recommended)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/sift/cli.py` (`eustack` command, after `perfmon` ~:1306) | controller (CLI command) | request-response (bundle write) | `src/sift/cli.py` `perfmon()` (:1215-1305) / `mcm()` (:1127-1202) | exact |
| `src/sift/pipeline/eustack_progression.py` (new leaf module) | service (pure transform) | batch/transform | `src/sift/pipeline/perfmon.py` `_file_scope_groups` (:578-666) | role-match (grouping shape); no exact deltas-over-time analog exists — closest secondary is `PerfmonHazard`/`SaturationFlag` for the flag record |
| `src/sift/render/eustack_report.py` | service (pure renderer) | transform (model → str/file) | `src/sift/render/perfmon_report.py` (whole file) | exact |
| — CSV writer inside `eustack_report.py` | utility | file-I/O | `write_perfmon_trend_csv` (`perfmon_report.py:242-297`) + `_csv_safe` (`:203-239`, reused not copied) | exact |
| `tests/test_eustack_progression.py` | test | batch/transform | `tests/test_perfmon.py` (grouping/ordering unit tests) | role-match |
| `tests/test_eustack_report.py` | test | transform | analog: `perfmon_report.py`'s own doctring/test pattern — no single `test_perfmon_report.py` file exists standalone; closest is CSV/markdown assertions embedded in `tests/test_cli_perfmon.py` (below) | partial |
| `tests/test_cli_eustack.py` | test | request-response (CliRunner) | `tests/test_cli_perfmon.py` (whole file) / `tests/test_cli_mcm.py` | exact |
| `tests/fixtures/eustack/*` (new synthetic 2-dump pair) | fixture/data | file-I/O | `tests/fixtures/eustack/reference_capture_derivative.txt` + `derive_reference_capture_derivative.py` | role-match (provenance-script pattern, not content) |

## Pattern Assignments

### `src/sift/cli.py` — new `eustack` command

**Analog:** `perfmon()` at `src/sift/cli.py:1214-1305` (mirror verbatim per D-12; `mcm()` at :1127-1202 is the same shape one level simpler).

**Command signature + docstring pattern** (`cli.py:1214-1235`):
```python
class PerfmonFormat(StrEnum):
    md = "md"
    json = "json"

@app.command()
def perfmon(
    case: str,
    fmt: Annotated[
        PerfmonFormat,
        typer.Option("--format", help="Report format: md (default) or json"),
    ] = PerfmonFormat.md,
    data_dir: DataDirOption = None,
) -> None:
    """... Exit-code contract (ADR 0007): 0 = bundle written (including an
    empty case), 1 = missing case / write failure, 2 = Typer usage (bad
    --format)."""
```
Mirror for `eustack`: `EustackFormat` StrEnum (`md`/`json`), same three params (`case`, `fmt`, `data_dir`), same docstring shape naming the exit-code contract and stating the empty-case (no DSSErrors log — D-12/EUS-09) behaviour explicitly, the way perfmon's docstring states its own D-20 no-log behaviour.

**Bundle-dir + write + cleanup pattern** (`cli.py:1247-1285`):
```python
perfmon_dir = case_db_path(config.data_dir, case).parent / "perfmon"
events = store.query_events()
analysis = analyse_perfmon(analyse_mcm(events, config.mcm.thresholds), events)
if fmt is PerfmonFormat.json:
    report_name = "perfmon_report.json"
    report_text = render_perfmon_json(analysis)
else:
    report_name = "perfmon_report.md"
    report_text = render_perfmon_markdown(analysis)
try:
    perfmon_dir.mkdir(parents=True, exist_ok=True)
    (perfmon_dir / report_name).write_text(report_text, encoding="utf-8")
    write_perfmon_trend_csv(analysis, perfmon_dir / "perfmon_trend.csv")
except OSError as exc:
    for partial in (perfmon_dir / report_name, perfmon_dir / "perfmon_trend.csv"):
        partial.unlink(missing_ok=True)
    print(f"Error: cannot write perfmon bundle to {perfmon_dir}: {_sanitise(str(exc))}")
    raise typer.Exit(1) from None
```
Mirror for eustack: bundle dir `case_db_path(config.data_dir, case).parent / "eustack"`, filter `store.query_events()` to `e.source == "eustack"` (Pattern from RESEARCH Q2 — filter inline in cli.py, same as perfmon's `e.source == "dssperfmon"` at `perfmon.py:728`), then `analyse_eustack` → `analyse_saturation` → progression compute, write `eustack_report.{md,json}` + `eustack_signatures.csv` with the same report-before-CSV, unlink-both-on-OSError, sanitised-message, `raise typer.Exit(1) from None` shape. Always `finally: store.close()`.

**One-line stdout summary pattern** (`cli.py:1287-1302`):
```python
n = len(analysis.groups)
print(f"Correlated {n} {plural}; wrote {report_name} + perfmon_trend.csv to {perfmon_dir}")
_sev_rank = {"critical": 0, "warn": 1, "info": 2}
for i, group in enumerate(analysis.groups, start=1):
    hazards = sorted(group.hazards, key=lambda h: _sev_rank.get(h.severity, 3))
    if hazards:
        top = hazards[0]
        print(f"  Span {i}: {top.severity} — {_sanitise(top.message)}")
```
Mirror: summarise dump count / signature count, then highest-severity `SaturationFlag`/ordering-unresolved hazard per dump/analysis, `_sanitise`d exactly as above (log-derived text through `_sanitise` before any `print`).

---

### `src/sift/pipeline/eustack_progression.py` (new leaf module)

**Analog 1 — grouping shape:** `src/sift/pipeline/perfmon.py` `_file_scope_groups` (:578-666).

```python
# Source: src/sift/pipeline/perfmon.py:602-605
by_file: dict[str, list[Event]] = {}
for event in perfmon_events:
    by_file.setdefault(event.source_file, []).append(event)
```
Use verbatim for dump grouping (D-08/EUS-07): `by_file.setdefault(event.source_file, []).append(event)` over `[e for e in store.query_events() if e.source == "eustack"]` (RESEARCH Code Example, `perfmon.py:728` precedent) — dict-insertion order preserved, never a `set`.

**Ordering basis:** read `.ts` / `.ts_confidence` off any one thread event per group (`Event.thread is not None`) — do NOT special-case a preamble event (RESEARCH Pitfall 2, `adapters/eustack.py:172-223`). D-01 path: every group's representative event has `ts_confidence != "missing"` → order by `ts`. D-02 fallback: order by sorted `source_file`, and raise the "ordering unresolved" flag.

**Analog 2 — flag record shape (not `SaturationFlag`):** `PerfmonHazard` (`pipeline/perfmon.py:119-144`, reproduced via `SaturationFlag` at `pipeline/eustack.py` for contrast):
```python
class PerfmonHazard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dimension: str
    severity: Literal["info", "warn", "critical"]
    message: str
    event_ids: tuple[str, ...]
    value: float | None = None
```
Mirror this shape (not `SaturationFlag`'s `warn`/`critical`-graded shape) for the "ordering basis unresolved" structural flag — it has no threshold pair (RESEARCH Pattern 2 / Anti-Patterns).

**Frozen-model precedent for the new progression model:** `SignatureGroup` / `EustackAnalysis` / `SaturationAnalysis` in `src/sift/pipeline/eustack.py` — every model uses `model_config = ConfigDict(extra="forbid", frozen=True)`; consume `EustackAnalysis`/`SaturationAnalysis` read-only, never mutate, never add fields to them (explicit in both those classes' own docstrings). `SignatureGroup` carries `frames: tuple[str, ...]` — RESEARCH recommends the progression model join across dumps on this same `frames` tuple internally, applying the D-07 display projection (matched frame index + leaf frame only) at render time, not at model-storage time.

```python
# src/sift/pipeline/eustack.py:382-399 (SignatureGroup, the record shape to key progression joins on)
class SignatureGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    frames: tuple[str, ...]
    thread_count: int
    role: Role
    subsystem: str | None
    pattern: str | None
    frame_index: int | None
    reason: Reason | None
```

**Determinism discipline to copy:** `_file_scope_groups`'s own comment block — "no `set` iteration can vary the output between runs (D-21)"; samples/rows sorted on an explicit tuple key, never left to insertion order alone once more than one property matters. Apply identically to progression's changed-signatures ranking (D-09: ranked by absolute delta — sort key must be `(-abs(delta), frames)` or similar total order, never `sorted(..., key=abs_delta)` alone which is not a total order over ties).

---

### `src/sift/render/eustack_report.py`

**Analog:** `src/sift/render/perfmon_report.py` (whole file) — three-function shape (`render_X_markdown`, `render_X_json`, `write_X_csv`) plus `mcm_report.py:229-261` for the CSV-writer sibling.

**Imports pattern** (`perfmon_report.py:31-52`):
```python
from __future__ import annotations
import csv
import json
from typing import TYPE_CHECKING
from sift.render._util import sanitise
from sift.render.markdown import _field  # pyright: ignore[reportPrivateUsage]
if TYPE_CHECKING:
    from pathlib import Path
    from sift.pipeline.perfmon import CounterTrend, PerfmonAnalysis, PerfmonHazard, TrendGroup
```
Mirror for eustack_report.py, importing `EustackAnalysis`, `SaturationAnalysis`, `SignatureGroup` (TYPE_CHECKING) from `sift.pipeline.eustack`, plus the new progression model from `sift.pipeline.eustack_progression`.

**Reuse `_csv_safe` — import, do not reimplement** (D-06, explicit in CONTEXT):
```python
from sift.render.perfmon_report import _csv_safe
```

**Markdown table pattern** (`perfmon_report.py:113-153`, `_counter_table`/`_hazard_table`): build a `list[str]` of lines, `_field()`-wrap every dynamic string cell, `"—"` (`_ABSENT`) for missing figures, one blank-line-terminated Markdown pipe-table per section, "_No X._" italic sentence when a table would be empty. Mirror exactly for the signatures table and the progression (changed-only) table.

**JSON renderer — copy verbatim (byte-for-byte identical technique)** (`perfmon_report.py:187-200`):
```python
def render_perfmon_json(analysis: PerfmonAnalysis) -> str:
    doc = analysis.model_dump(mode="json")
    return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"
```
No `generated_at` field anywhere (RESEARCH Anti-Patterns — verified no `datetime.now()` in either sibling renderer); D-13 byte-identity depends on this.

**CSV writer pattern** (`perfmon_report.py:242-297`, header-first-even-if-empty, `';'`-joined multi-value cells, `_csv_safe` on every string cell, raw numeric on numeric cells):
```python
with path.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(HEADER)
    for row in ...:
        writer.writerow((_csv_safe(...), _csv_safe(...), raw_int_or_float, ...))
```
Header per D-05: `role, subsystem, matched_pattern, frame_index, reason, matched_frame, leaf_frame, thread_count` + one count column per dump + delta columns (D-08). Do not pass `lineterminator=` (RESEARCH Pitfall 3 — `csv.excel` default `\r\n` is a fixed dialect constant, not platform-dependent; match `write_perfmon_trend_csv`'s bare `csv.writer(fh)` call exactly).

---

## Shared Patterns

### Bundle-dir standalone CLI contract (D-12)
**Source:** `src/sift/cli.py` `mcm()` (:1127-1202) and `perfmon()` (:1214-1305)
**Apply to:** the new `eustack` command — bundle dir derivation, `--format`/`--out`-equivalent options, report-before-CSV write ordering, unlink-both-on-`OSError` cleanup, `finally: store.close()`, exit-code contract (0/1/2 per ADR 0007).

### Formula-injection / terminal-escape guard chain
**Source:** `_csv_safe` (`render/perfmon_report.py:203-239`, reused via import) + `sanitise`/`markdown._field` (`render/_util.py`, `render/markdown.py`)
**Apply to:** every C++ symbol string (matched pattern, matched frame, leaf frame) reaching the CSV, Markdown report, or a `print()` stdout summary line. Sanitise-then-quote ordering is load-bearing (do not reorder).

### Frozen-model / read-only-consumption discipline
**Source:** `pipeline/eustack.py` `EustackAnalysis`/`SaturationAnalysis`/`SignatureGroup`, all `ConfigDict(extra="forbid", frozen=True)`
**Apply to:** the new progression model in `pipeline/eustack_progression.py` — new frozen model, zero mutation of Phase 15/16 models, `extra="forbid"` on every new Pydantic class.

### Explicit total ordering (no `set`/`Counter.most_common()`)
**Source:** `_file_scope_groups` docstring (`perfmon.py:578-666`) and `EustackAnalysis.signatures`' own "-thread_count, frames" sort precedent
**Apply to:** dump grouping (dict-insertion order), dump ordering (D-01/D-02 explicit basis), and D-09's changed-signature ranking by absolute delta — every iteration order must be a stated, reproducible sort key for D-13 byte-identity.

### Byte-identical JSON / no wall-clock field
**Source:** `render_perfmon_json`/`render_mcm_json` (`perfmon_report.py:187-200`, `mcm_report.py:218-226`)
**Apply to:** `render_eustack_json` — `model_dump(mode="json")` → `json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"`, no `generated_at`.

## No Analog Found

None — every file in scope has a strong (exact or role-match) analog; see table above. The two weaker matches (`test_eustack_report.py`'s partial match, and the fixture-provenance analog) still have a clear precedent to follow (inline CSV/markdown assertions from `test_cli_perfmon.py`; `derive_reference_capture_derivative.py`'s "deliberately authored, not observed" fixture-building discipline, per RESEARCH Pitfalls 4/5).

## Metadata

**Analog search scope:** `src/sift/cli.py`, `src/sift/render/{perfmon_report,mcm_report}.py`, `src/sift/pipeline/{perfmon,eustack}.py`, `tests/test_cli_{perfmon,mcm}.py`, `tests/fixtures/eustack/`
**Files scanned:** 8 read in full or targeted ranges this session (plus RESEARCH.md's own prior full-file reads of the same set, cross-checked, not re-read where already covered)
**Pattern extraction date:** 2026-07-25
</content>
