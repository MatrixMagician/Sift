"""Sift command-line interface.

Seven flat subcommands per SPEC.md §5.8. new/ingest/show are implemented in
Phase 1; analyze/report/eval/doctor arrive in later phases. Config resolution
follows D-08 precedence (flags > SIFT_* env > config.toml > defaults) — every
implemented command exposes ``--data-dir`` as the flags layer.
"""

import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from sift import adapters
from sift.adapters.genericlog import GenericLogAdapter
from sift.config import SiftConfig, load_config
from sift.store import CaseStore, case_db_path

app = typer.Typer(no_args_is_help=True)

DataDirOption = Annotated[
    Path | None,
    typer.Option("--data-dir", help="Override the case data directory"),
]


def _sanitise(text: str) -> str:
    """Strip control characters (except newline and tab) from rendered text.

    T-04-01: hostile log bytes must never drive the operator's terminal.
    Removes C0 controls (below 0x20), DEL (0x7f), C1 controls (0x80-0x9f,
    e.g. the single-byte CSI) and Unicode format characters (category Cf:
    bidi overrides like U+202E, zero-width characters) that can visually
    reorder or hide rendered triage output. Applied at render time only —
    stored raw and message text stay verbatim for citation fidelity.
    """
    return "".join(
        ch
        for ch in text
        if ch in "\n\t"
        or (
            ord(ch) >= 0x20
            and not (0x7F <= ord(ch) <= 0x9F)
            and unicodedata.category(ch) != "Cf"
        )
    )


def _case_store(case: str, config: SiftConfig) -> CaseStore:
    """Open an existing case or exit 1 with a helpful message."""
    try:
        db_path = case_db_path(config.data_dir, case)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from None
    if not db_path.exists():
        print(f"Error: case {case!r} does not exist; create it with 'sift new'")
        raise typer.Exit(1)
    return CaseStore(db_path)


@app.command()
def new(
    case_name: str,
    input: Annotated[str, typer.Option("--input", help="Directory of artefacts")],
    # Typer reads the default once at import time, so the shared list is safe here.
    adapter: Annotated[
        list[str], typer.Option("--adapter", help="glob=name adapter override")
    ] = [],  # noqa: B006
    data_dir: DataDirOption = None,
) -> None:
    """Create a new case from a directory of artefacts."""
    config = load_config({"data_dir": data_dir})
    try:
        db_path = case_db_path(config.data_dir, case_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from None
    if db_path.exists():
        # A case is one snapshot: silently repointing input_dir would mix
        # events from two snapshots and poison the coverage meta.
        print(f"Error: case {case_name!r} already exists at {db_path.parent}")
        raise typer.Exit(1)
    try:
        # Validate glob=name specs now so a typo fails at `new`, not mid-ingest.
        adapters.parse_adapter_overrides(adapter)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(2) from None
    input_dir = Path(input).expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Error: input directory does not exist: {input_dir}")
        raise typer.Exit(1)
    if not any(input_dir.iterdir()):
        print(f"Warning: input directory is empty: {input_dir}")
    store = CaseStore(db_path)
    store.set_meta("input_dir", str(input_dir))
    store.set_meta("created_at", datetime.now(tz=UTC).isoformat())
    # Raw --adapter specs persist so `sift ingest` reuses them (flags win over
    # config.adapters per glob at ingest time).
    store.set_meta("adapter_overrides", json.dumps(adapter))
    store.close()
    print(f"Created case {case_name!r} for {input_dir}")


@app.command()
def ingest(case: str, data_dir: DataDirOption = None) -> None:
    """Parse the case's input directory and store canonical events.

    A case is one snapshot of artefacts: re-ingesting the same snapshot adds
    zero events (idempotent); re-collect changed inputs into a new case.
    New files appearing in the directory simply add events, and renamed
    files produce duplicate events (a documented limitation — event identity
    is source_file + byte_offset within one snapshot).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    input_dir_s = store.get_meta("input_dir")
    if input_dir_s is None:
        print(f"Error: case {case!r} has no recorded input directory")
        raise typer.Exit(1)
    input_dir = Path(input_dir_s)
    if not input_dir.is_dir():
        print(f"Error: input directory no longer exists: {input_dir}")
        raise typer.Exit(1)

    raw_specs: list[str] = json.loads(store.get_meta("adapter_overrides") or "[]")
    try:
        flag_overrides = adapters.parse_adapter_overrides(raw_specs)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(2) from None
    # D-08 flags > config: detect() picks the FIRST matching glob in insertion
    # order, so flag globs must come first — merging config first would let an
    # overlapping (non-identical) config glob shadow the flag.
    overrides = dict(flag_overrides) | {
        g: n for g, n in config.adapters.items() if g not in flag_overrides
    }
    unknown = sorted(
        {name for name in overrides.values() if name not in adapters.REGISTRY}
    )
    if unknown:
        print(
            f"Error: unknown adapter(s) {unknown}; "
            f"known adapters: {sorted(adapters.REGISTRY)}"
        )
        raise typer.Exit(2)

    files = [p for p in sorted(input_dir.rglob("*")) if p.is_file()]
    if not files:
        print(f"0 files found in {input_dir}; nothing to ingest")
        return
    failed: list[str] = []
    coverage: dict[str, dict[str, object]] = {}
    total_new = 0
    # One transaction for all inserts plus the coverage meta write: an
    # interrupted ingest leaves either the complete result or nothing.
    with store.transaction():
        for path in files:
            relpath = path.relative_to(input_dir).as_posix()
            if path.is_symlink():
                # Trust boundary: a hostile bundle must never select files
                # outside itself for ingestion. Skip loudly and record it so
                # the persisted coverage meta shows the file existed.
                print(f"SKIP {_sanitise(relpath)}: symlink (not followed)")
                coverage[relpath] = {
                    "skipped": "symlink (not followed)",
                    "event_count": 0,
                    "coverage": 0.0,
                }
                continue
            try:
                # Detection reads (and decompresses) file heads, so a corrupt
                # archive can raise here too — it must hit the same loud
                # per-file error path as a parse failure, never abort the run.
                file_adapter = adapters.detect(path, relpath, overrides)
                # Per-run configuration travels on the adapter instance — the
                # frozen Protocol has no config attributes (01-02 pattern).
                # D-05: config.timezones reaches the adapter here.
                if isinstance(file_adapter, GenericLogAdapter):
                    file_adapter.input_root = input_dir
                    file_adapter.tz_overrides = dict(config.timezones)
                events = list(file_adapter.parse(path, case))
                new_count = store.insert_events(events)
            except Exception as exc:
                # A bad file never silently vanishes: loud error, keep going.
                # T-04-01: relpath and exception text carry untrusted bundle
                # bytes (filenames may contain ESC) — sanitise at render time.
                # The failure is also persisted so a report generated later
                # still shows the file existed and failed.
                failed.append(relpath)
                coverage[relpath] = {
                    "error": str(exc),
                    "event_count": 0,
                    "coverage": 0.0,
                }
                print(f"ERROR {_sanitise(relpath)}: {_sanitise(str(exc))}")
                continue
            stats = (
                file_adapter.last_stats
                if isinstance(file_adapter, GenericLogAdapter)
                else None
            )
            cov = stats.coverage if stats else 1.0
            event_count = stats.event_count if stats else len(events)
            coverage[relpath] = {
                "total_bytes": stats.total_bytes if stats else 0,
                "unknown_fallback_bytes": stats.unknown_fallback_bytes if stats else 0,
                "event_count": event_count,
                "coverage": cov,
                "notes": stats.notes if stats else [],
            }
            total_new += new_count
            print(
                f"{_sanitise(relpath)}  coverage {cov * 100:.1f}%  "
                f"{event_count} events  {new_count} new"
            )
            for note in stats.notes if stats else []:
                print(f"  note: {note}")
        store.set_meta("parse_coverage", json.dumps(coverage, sort_keys=True))
    print(f"Total: {total_new} new events")
    if failed:
        print(f"Error: {len(failed)} file(s) failed to parse")
        raise typer.Exit(1)


@app.command()
def show(case: str, what: str, data_dir: DataDirOption = None) -> None:
    """Show events, clusters or hypotheses for a case."""
    if what == "clusters":
        print("show clusters arrives in Phase 2 (M2)")
        raise typer.Exit(1)
    if what == "hypotheses":
        print("show hypotheses arrives in Phase 4 (M4)")
        raise typer.Exit(1)
    if what != "events":
        print(f"Error: unknown target {what!r}; expected events|clusters|hypotheses")
        raise typer.Exit(1)
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    for e in store.query_events():
        ts = e.ts.isoformat() if e.ts is not None else "-"
        message = _sanitise(e.message.replace("\n", " "))[:120]
        print(
            f"{e.event_id}  {ts}  {e.severity:<7}  "
            f"{_sanitise(e.source_file)}:{e.line_start}  {message}"
        )


@app.command()
def analyze() -> None:
    """Cluster events and generate ranked root-cause hypotheses."""
    print("analyze arrives in Phase 4 (M4)")
    raise typer.Exit(1)


@app.command()
def report() -> None:
    """Render the triage report."""
    print("report arrives in Phase 6 (M6)")
    raise typer.Exit(1)


@app.command("eval")
def eval_() -> None:
    """Run the golden-case evaluation suite."""
    print("eval arrives in Phase 7 (M7)")
    raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Check the local environment and inference endpoint."""
    print("doctor arrives in Phase 3 (M3)")
    raise typer.Exit(1)
