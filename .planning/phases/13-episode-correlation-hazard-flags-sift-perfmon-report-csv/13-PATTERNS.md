# Phase 13: Episode Correlation, Hazard Flags & `sift perfmon` Report + CSV - Pattern Map

**Mapped:** 2026-07-20
**Files analysed:** 6 (3 new, 3 modified) + 3 test targets
**Analogs found:** 8 / 9 (one explicit no-analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/pipeline/perfmon.py` (new) | pipeline analyser | batch transform (events → frozen models) | `src/sift/pipeline/mcm.py` | exact |
| `src/sift/render/perfmon_report.py` (new) | renderer | transform + file-I/O | `src/sift/render/mcm_report.py` | exact |
| `src/sift/cli.py` — new `perfmon` command | CLI command | request-response (argv → files + stdout) | `cli.py:1003-1071` `mcm` | exact |
| `src/sift/adapters/dssperfmon.py` (WR-02/03/05) | adapter | streaming parse | itself (in-file precedents) | in-file |
| `tests/test_perfmon.py` (new) | unit test | — | `tests/test_mcm.py` idiom | role-match |
| `tests/test_cli_perfmon.py` (new) | integration test | — | `tests/test_cli_mcm.py` | exact |
| `tests/fixtures/dssperfmon/` synthetic (collision / drift / non-finite) | fixture | — | **none** | see § No Analog Found |

---

## Pattern Assignments

### `src/sift/pipeline/perfmon.py` (pipeline analyser, batch transform)

**Analog:** `src/sift/pipeline/mcm.py`

**Frozen-model shape** — clone verbatim (`mcm.py:221-238`, `DiagnosticFlag`). This is the shape D-12 copies but deliberately does *not* reuse:

```python
class DiagnosticFlag(BaseModel):
    """One graded MCM diagnostic signal (D-12 / MCM-03).

    ``value_pct`` is ALWAYS a ratio ``part / whole * 100`` — never an absolute GB
    ...
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str  # "working_set_pct_virtual" | ... (the config key it grades)
    severity: str  # "info" | "warn" | "critical"
    value_pct: float  # the triggering ratio, *100, rounded deterministically (1 dp)
    message: str  # British-English one-liner with the % inline
    event_ids: tuple[str, ...]
```

Note the convention the planner must carry into `PerfmonHazard`: `model_config` first, one inline `#` comment per field naming its allowed values and its rounding, and a docstring that states the invariant. `PerfmonHazard`'s docstring must additionally state *why* `_grade` is not used (D-13 categorical severities) so the omission does not read as an oversight.

**Flag emission pattern** (`mcm.py:638-658`, `compute_flags`) — the shape each hazard builder mirrors: bind the citation tuple once, guard the denominator/None *before* computing, append a fully-built frozen model, message carries the figure inline:

```python
    b = ep.breakdown
    cite = (ep.denial_event_id,)
    flags: list[DiagnosticFlag] = []

    # 1. Working set as % of IServer virtual — the denial driver (65.4% at Hartford).
    ws, virt = b.working_set_mb, b.iserver_virtual_mb
    if ws is not None and virt:
        pct = round(ws / virt * 100, 1)
        flags.append(
            DiagnosticFlag(
                dimension="working_set_pct_virtual",
                severity=_grade(...),
                value_pct=pct,
                message=f"Working set is {pct:.1f}% of IServer virtual memory",
                event_ids=cite,
            )
        )
```

`_grade` (`mcm.py:609-624`) is the two-cut-point grader. **Do not call it** — D-13's severities are categorical string literals. Read it only to confirm the divergence is deliberate.

**Orchestration entry point** (`mcm.py:956-976`, `analyse_mcm`) — the signature and determinism docstring `analyse_perfmon` should mirror:

```python
def analyse_mcm(events: list[Event], thresholds: McmThresholdsConfig) -> McmAnalysis:
    """Compose the full MCM analysis — the single entry the CLI (Plan 04) calls.

    ...No episodes → ``McmAnalysis(episodes=())`` (never a
    crash). Pure and deterministic: ``model_dump_json`` is byte-identical on
    re-run (no ``set`` iteration anywhere on the path).
    """
    analyses: list[EpisodeAnalysis] = []
    for ep in detect_episodes(events):
        window = select_window(ep)
        analyses.append(EpisodeAnalysis(episode=ep, window=window, ...))
    return McmAnalysis(episodes=tuple(analyses))
```

Per RESEARCH A7 the perfmon correlator takes `(analysis: McmAnalysis, events: list[Event])` and never calls `select_window` itself — the window arrives on `EpisodeAnalysis.window`.

**Boundary-resolution + dedup-ordering precedent** (`mcm.py:903`, `attribute_window`):

```python
    head = window.start_event_id or (ep.event_ids[0] if ep.event_ids else None)
```

D-03 differs: scan for the first `event_ids` entry whose resolved `Event.ts is not None`, hazard (D-04) if none. Note the shipped code takes `event_ids[0]` unconditionally — **do not copy it as-is**, it is the shape not the rule.

Deterministic dedup idiom, used on every output path (`mcm.py:940-941`, `mcm.py:952`) — this is what D-21's no-`set` rule means concretely:

```python
                event_ids=tuple(dict.fromkeys(acc.event_ids)),
                ...
        unmatched_event_ids=tuple(dict.fromkeys(unmatched)),
```

Deterministic sort with an explicit tie-breaker (`mcm.py:945`): `out.sort(key=lambda r: (-r.granted_bytes, r.key))`.

**Model layering to mirror** — `McmEpisode` → `EpisodeWindow` → `EpisodeAnalysis` (`mcm.py:280-294`) → `McmAnalysis` (`mcm.py:297-306`). Each is `frozen=True, extra="forbid"`, tuples never lists. Note `McmAnalysis`'s docstring explicitly guarantees the empty case: *"An empty case (no MCM denial episodes) yields `episodes=()` — never a crash."* `PerfmonAnalysis` needs the equivalent sentence for D-20.

---

### `src/sift/render/perfmon_report.py` (renderer, transform + file-I/O)

**Analog:** `src/sift/render/mcm_report.py`

**Module docstring convention** (`:1-26`) — enumerates each public function, names the security control it carries, and closes with the purity statement: *"Pure `McmAnalysis -> str` / `-> file`: no store re-read, no recompute, no network, no LLM. The only I/O is the CSV file write."*

**Imports + TYPE_CHECKING discipline** (`:28-50`):

```python
from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

from sift.render.markdown import _field  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path

    from sift.pipeline.mcm import (
        AttributionRow, DiagnosticFlag, EpisodeAnalysis, ...
    )
```

All pipeline model imports are under `if TYPE_CHECKING`. `_field` (which wraps `render._util.sanitise` plus Markdown/HTML escaping) is imported, never reimplemented — the comment at `:34-37` calls this "the sanctioned cross-module reuse".

**Round-at-source precedent** (`:79-81`) — the D-08 template:

```python
def _mb_bytes(granted_bytes: int) -> float:
    """Convert bytes to megabytes, rounded deterministically to 3 dp."""
    return round(granted_bytes / 1024**2, 3)
```

**Graded-flag table** (`:99-115`) — the hazard table's direct template, including the empty early-return and the every-cell-through-`_field` rule:

```python
def _flags_table(flags: tuple[DiagnosticFlag, ...]) -> list[str]:
    lines = ["### Diagnostic flags", ""]
    if not flags:
        lines.append("_No diagnostic flags raised._")
        lines.append("")
        return lines
    lines.append("| Dimension | Severity | Value | Detail |")
    lines.append("| --- | --- | --- | --- |")
    for f in flags:
        lines.append(
            f"| {_field(f.dimension)} | {_field(f.severity)} "
            f"| {f.value_pct:.1f}% | {_field(f.message)} |"
        )
    lines.append("")
    return lines
```

Note `PerfmonHazard.value` is `float | None` (D-12), so the value cell needs an `—` branch; `_lifecycle_table` at `:93` shows the house spelling: `ts = _field(s.ts) if s.ts else "—"`.

**Empty-case early return** (`:206-219`) — the exact shape D-20 clones:

```python
def render_mcm_markdown(analysis: McmAnalysis) -> str:
    """Render the deterministic, timeline-first MCM report (D-11, MCM-05)."""
    out: list[str] = ["# MCM Denial Analysis", ""]
    count = len(analysis.episodes)
    if count == 0:
        out.append("_No MCM denial episodes detected._")
        out.append("")
        return "\n".join(out)
    plural = "episode" if count == 1 else "episodes"
    out.append(f"_{count} denial {plural} detected._")
    out.append("")
    for i, ea in enumerate(analysis.episodes, start=1):
        out.extend(_episode_section(i, ea))
    return "\n".join(out)
```

**JSON canonicalisation** (`:222-230`) — copy verbatim, `ensure_ascii=True` is a security control:

```python
def render_mcm_json(analysis: McmAnalysis) -> str:
    """Serialise the analysis to canonical, key-sorted, ASCII-safe JSON.

    ``ensure_ascii=True`` backslash-u-escapes every non-ASCII code point so the
    JSON report carries no raw C1/Cf terminal-injection byte (the ``json_out``
    precedent); ``sort_keys`` + trailing newline make it byte-identical on re-run.
    """
    doc = analysis.model_dump(mode="json")
    return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"
```

**CSV writer** (`:52-60` header + `:233-264` writer):

```python
CSV_HEADER: tuple[str, ...] = (
    "episode_id", "dimension", "key", "granted_bytes",
    "granted_mb", "request_count", "event_ids",
)

def write_attribution_csv(analysis: McmAnalysis, path: Path) -> None:
    """...stdlib ``csv.writer(newline="")`` quotes embedded delimiters/quotes/newlines
    (T-10-13); the keys are structurally hex (SID/OID) or ``Source=`` ``[\\w:]+``
    values which cannot begin with a spreadsheet formula trigger, so the quoting
    is the complete mitigation — never a manual join. ... ``event_ids`` is
    ';'-joined (a semicolon avoids CSV comma-quoting) and never empty (D-16).
    """
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for ea in analysis.episodes:
            episode_id = ea.episode.denial_event_id
            for rows in (ea.attribution.by_oid, ...):
                for r in rows:
                    writer.writerow((episode_id, r.dimension, r.key, ..., ";".join(r.event_ids)))
```

Copy the mechanics (module-level header tuple, `newline=""`, `;`-joined event_ids, header row written before any iteration so an empty analysis still yields a valid file). **Do not copy the security argument** — see § Shared Patterns / CSV formula injection.

---

### `src/sift/cli.py` — new `perfmon` command (CLI command, request-response)

**Analog:** `cli.py:995-1071` (`McmFormat` + `mcm`). Clone clause-for-clause per D-17.

**Format enum** (`:995-1001`):

```python
class McmFormat(StrEnum):
    """Report format for ``sift mcm`` (an unknown value is a Typer usage error,
    exit 2 — mirrors ``ReportFormat``; ADR 0007). The CSV is always written."""

    md = "md"
    json = "json"
```

**Command body** (`:1003-1071`) — the full pattern, every clause load-bearing:

```python
@app.command()
def mcm(
    case: str,
    fmt: Annotated[
        McmFormat,
        typer.Option("--format", help="Report format: md (default) or json"),
    ] = McmFormat.md,
    data_dir: DataDirOption = None,
) -> None:
    """...Exit-code contract (ADR 0007):
    0 = bundle written (including an empty case), 1 = missing case / write
    failure, 2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        from sift.pipeline.mcm import analyse_mcm            # deferred imports
        from sift.render.mcm_report import (...)

        # T-10-14: the bundle dir is derived from the SAME resolved case path
        # _case_store validated (case_db_path asserts containment) — only
        # <case>/mcm/ beneath it is ever created, never a user-supplied path.
        mcm_dir = case_db_path(config.data_dir, case).parent / "mcm"
        analysis = analyse_mcm(store.query_events(), config.mcm.thresholds)
        if fmt is McmFormat.json:
            report_name = "mcm_report.json"
            report_text = render_mcm_json(analysis)
        else:
            report_name = "mcm_report.md"
            report_text = render_mcm_markdown(analysis)
        try:
            mcm_dir.mkdir(parents=True, exist_ok=True)
            (mcm_dir / report_name).write_text(report_text, encoding="utf-8")
            write_attribution_csv(analysis, mcm_dir / "mcm_attribution.csv")
        except OSError as exc:
            print(f"Error: cannot write MCM bundle to {mcm_dir}: {_sanitise(str(exc))}")
            raise typer.Exit(1) from None

        n = len(analysis.episodes)
        plural = "episode" if n == 1 else "episodes"
        print(f"Analysed {n} MCM denial {plural}; wrote {report_name} + ...")
        _sev_rank = {"critical": 0, "warn": 1, "info": 2}
        for i, ea in enumerate(analysis.episodes, start=1):
            flags = sorted(ea.flags, key=lambda f: _sev_rank.get(f.severity, 3))
            if flags:
                top = flags[0]
                # T-10-15: log-derived message text through _sanitise before echo.
                print(f"  Episode {i}: {top.severity} — {_sanitise(top.message)}")
            else:
                print(f"  Episode {i}: no diagnostic flags raised")
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring report.
        store.close()
```

**Exit codes, concretely:** `0` = fall off the end of the function. `1` = `raise typer.Exit(1) from None` after a sanitised `print` (missing case comes free from `_case_store` at `cli.py:96`). `2` = never written by hand — it falls out of the `StrEnum` parameter type. `from None` suppresses the traceback chain and is not optional.

**Single-query rule (RESEARCH Pitfall 3):** `store.query_events()` is called exactly once at `:1037` and its result flows onward. The perfmon command must bind it to a local and pass the same list to both `analyse_mcm` and the correlator.

---

### `src/sift/adapters/dssperfmon.py` (adapter, streaming parse) — WR-02 / WR-03 / WR-05

**Analog:** the file's own in-place precedents. No external analog needed.

**WR-03 — collision qualification.** The reserved-key precedent to mirror (`:298-309`):

```python
                # Reserved keys win: a counter named "byte_offset" must not be
                # able to rewrite the provenance event_id derives from. The
                # colliding counter keeps its value under a prefix rather than
                # being dropped, so neither the provenance nor the counter
                # disappears silently.
                for counter_name, counter_value in values.items():
                    key = (
                        f"{_COUNTER_PREFIX}{counter_name}"
                        if counter_name in _RESERVED_ATTRS
                        else counter_name
                    )
                    attrs[key] = counter_value
```

The collision site is `:286` `values = dict(zip(counter_names, row[1:], strict=False))`. Detection belongs in `_parse_header` (`:154-183`), which already returns a `notes` list — so the disclosure note costs nothing:

```python
def _parse_header(columns: list[str]) -> tuple[str, str, str, list[str], list[str]]:
    """Return (host, tz_name, tz_offset_min, short_counter_names, notes).
    ...When either is absent the empty string is returned and the caller omits
    the attr rather than inventing a value; ``notes`` carries the disclosure
    either way.
    """
    counters = columns[1:]
    names = [_short_counter_name(c) for c in counters]
```

`_short_counter_name` (`:93-98`) is the two-line function that discards the qualifier; qualify-on-collision-only means keeping more of `path` for the duplicated names only.

**WR-05 — per-event drift marker.** Insertion point is `:314-320`, immediately after `drifted` is computed and before the `_fallback_event` yield at `:332`:

```python
                # D-16: column drift is disclosed, never realigned, padded or
                # truncated. Surviving drift is this phase's job; diagnosing it
                # is PERF-05's, in Phase 13.
                drifted = len(row) != header_width
                if drifted:
                    stats.notes.append(
                        _DRIFT_NOTE.format(
                            line=line_no, seen=len(row), expected=header_width
                        )
                    )
```

The comment literally names Phase 13 as the consumer. The new `attrs` marker key **must** be added to `_RESERVED_ATTRS` (`:75-85`) — otherwise a counter of the same name shadows the evidence D-15 reads, which is the exact attack the reserved set exists to block.

**WR-02 — note capping.** Two identical unbounded shapes: `:316` (`_DRIFT_NOTE`) and `:235-237` (`_CSV_ERROR_NOTE`):

```python
                except csv.Error as exc:
                    stats.notes.append(
                        _CSV_ERROR_NOTE.format(line=line_no, detail=exc)
                    )
```

Both live inside the per-row loop. Cap both in one pass. Downstream consumers to check: `cli.py:383` (persisted into the `parse_coverage` meta row) and `cli.py:390-391` (printed).

---

### `tests/test_cli_perfmon.py` (integration test)

**Analog:** `tests/test_cli_mcm.py` — exact match.

**Case-builder fixture idiom** (`:28-46`) — clone with `DssperfmonAdapter`:

```python
runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"


def _build_mcm_case(
    case: str = "hartford", rel: str = "hartford_deny_predenial_multisid.log"
) -> Path:
    """Ingest a Hartford dsserrors fixture into a real ``case.db`` (no network).

    Returns the case directory (``<data_dir>/cases/<case>/``) so tests can assert
    the ``<case>/mcm/`` bundle written beside it.
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
    finally:
        store.close()
    return db_path.parent
```

For criterion 5 (perfmon CSV, no DSSErrors log) this helper is used with **only** the perfmon adapter — no second ingest call. That is the whole fixture.

**Assertion patterns to mirror:**

- Bundle written (`:49-59`): `assert result.exit_code == 0, result.output` (the `, result.output` is the house idiom for a readable failure), then `.exists()` on both artefacts.
- Format + usage exit (`:62-74`): assert `.json` exists, assert `.md` does **not**, assert the CSV exists regardless of format, then `runner.invoke(app, [..., "--format", "xml"])` → `assert bad.exit_code == 2`.
- Determinism (`:77-85`) — criterion 2's direct test:

```python
def test_mcm_determinism(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two runs produce byte-identical report + CSV (no model involved)."""
    case_dir = _build_mcm_case()
    runner.invoke(app, ["mcm", "hartford"])
    report1 = (case_dir / "mcm" / "mcm_report.md").read_bytes()
    csv1 = (case_dir / "mcm" / "mcm_attribution.csv").read_bytes()
    runner.invoke(app, ["mcm", "hartford"])
    assert (case_dir / "mcm" / "mcm_report.md").read_bytes() == report1
    assert (case_dir / "mcm" / "mcm_attribution.csv").read_bytes() == csv1
```

- Empty case (`:88+`): a case with no episodes exits 0 and writes a valid empty bundle — this test already exists for `mcm` and is the direct template for the D-20 no-episodes test.

---

## Shared Patterns

### Sanitisation — A5 RESOLVED

**Source:** `src/sift/render/_util.py:11-30`
**Apply to:** every stdout echo (via `cli._sanitise`) and every Markdown cell (via `render.markdown._field`)

```python
def sanitise(text: str) -> str:
    """Strip control characters (except newline and tab) from rendered text.

    T-04-01: hostile log bytes must never drive the operator's terminal.
    Removes C0 controls (below 0x20), DEL (0x7f), C1 controls (0x80-0x9f,
    e.g. the single-byte CSI) and Unicode format characters (category Cf:
    bidi overrides like U+202E, zero-width characters) ...
    """
    return "".join(
        ch
        for ch in text
        if ch in "\n\t"
        or (ord(ch) >= 0x20 and not (0x7F <= ord(ch) <= 0x9F)
            and unicodedata.category(ch) != "Cf")
    )
```

**Plain answer to RESEARCH assumption A5: `sanitise` does NOT escape a leading `=`.** It is a control-character and Cf-category *strip* only — every printable ASCII character including `=`, `+`, `-`, `@` passes through untouched. It cannot serve as the CSV formula-injection guard. A separate guard is required if the planner adopts RESEARCH Pitfall 4 / A3. The module docstring also records why it lives in `render/`: it is the single implementation shared by CLI and renderers, and `render` never imports `cli`.

### CSV formula injection — the divergence the planner must decide

**Source of the non-transferable argument:** `mcm_report.py:236-242` — quoting is "the complete mitigation" **because** MCM keys are structurally hex or `[\w:]+`. Perfmon counter names come from the customer CSV header and are attacker-influenceable — `dssperfmon.py:70-74` states this explicitly in its own reserved-key comment. Whatever the planner decides, the new writer's docstring must state the divergence, mirroring how `write_attribution_csv` states its own reasoning.

### Path containment

**Source:** `cli.py:1033-1036`
**Apply to:** the `perfmon` command

`case_db_path(config.data_dir, case).parent / "perfmon"` — derived from the path `_case_store` already validated, never from user input. `store.validate_case_name` / `case_db_path` (`store.py:124`, `:133`) do the asserting; the CLI just consumes them.

### Store access

**Source:** `store.py:573-597` `query_events` (no filtering, `ORDER BY ts IS NULL, ts, source_file, line_start` — this clause *is* D-05's canonical ordering); `store.py:600-638` `get_events_by_ids`; `store.py:335` `EXCLUDED_FROM_RANKING = frozenset({"dssperfmon"})` which touches only `iter_event_summaries`.
**Apply to:** correlator and CLI. Call `query_events()` once. Filter perfmon in-memory on `event.source == "dssperfmon"` — do not import `EXCLUDED_FROM_RANKING` (different concept; RESEARCH A2).

### WAL discipline

**Source:** `cli.py:1069-1071` — `finally: store.close()` wraps the entire command body including every `typer.Exit` path. Present on `report` (`:990-992`) too; it is universal for store-touching commands.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/fixtures/dssperfmon/` — colliding-instance CSV (WR-03), mid-file drift CSV (WR-05), `nan`/`inf` cell CSV (D-11) | fixture | — | Verified in RESEARCH: the Hartford CSV has 22 unique short names, uniform width 23 across 13,596 rows and zero non-numeric cells. **None of the three conditions is derivable from real data** and no existing fixture in `tests/fixtures/dssperfmon/` exercises them. These must be hand-authored; there is no pattern to copy beyond the PDH header shape of the existing fixtures. The WR-03 collision specifically needs the same *counter* under two *instances* (e.g. `\\host\Process(MSTRSvr)\Size(MB)` and `\\host\Process(other)\Size(MB)`) — note Hartford's `Process(MSTRSvr)\Size(MB)` + `Process(MSTRSvr)\RSS(MB)` pair is the same object with different counters and does **not** collide. |

Partial-only note on `tests/test_perfmon.py`: `tests/test_cli_mcm.py:28-45` supplies the ingest helper idiom, but the correlator's own unit tests (span resolution, trend maths, hazard grading) have no per-function analog in `test_mcm.py` worth copying wholesale — the assertion style transfers, the test bodies do not.

## Metadata

**Analog search scope:** `src/sift/pipeline/`, `src/sift/render/`, `src/sift/adapters/`, `src/sift/cli.py`, `src/sift/store.py`, `tests/`
**Files read this session:** 7 (`mcm.py` three targeted non-overlapping ranges; `mcm_report.py`, `_util.py`, `test_cli_mcm.py`, `cli.py` and `dssperfmon.py` two ranges each)
**Pattern extraction date:** 2026-07-20 (pinned to commit `7bf59a8`)
