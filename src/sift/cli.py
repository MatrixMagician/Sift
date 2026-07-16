"""Sift command-line interface.

Seven flat subcommands per SPEC.md §5.8. new/ingest/show are implemented in
plan 01-02; analyze/report/eval/doctor arrive in later phases.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from sift import adapters
from sift.adapters.genericlog import GenericLogAdapter
from sift.config import load_config
from sift.store import CaseStore, case_db_path

app = typer.Typer(no_args_is_help=True)


def _printable(text: str) -> str:
    """Strip control characters so hostile log content cannot drive the terminal."""
    return "".join(ch for ch in text if ch.isprintable() or ch == "\t")


def _case_store(case: str) -> CaseStore:
    """Open an existing case or exit 1 with a helpful message."""
    config = load_config()
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
) -> None:
    """Create a new case from a directory of artefacts."""
    config = load_config()
    try:
        db_path = case_db_path(config.data_dir, case_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from None
    input_dir = Path(input).expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Error: input directory does not exist: {input_dir}")
        raise typer.Exit(1)
    if not any(input_dir.iterdir()):
        print(f"Warning: input directory is empty: {input_dir}")
    store = CaseStore(db_path)
    store.set_meta("input_dir", str(input_dir))
    store.set_meta("created_at", datetime.now(tz=UTC).isoformat())
    store.close()
    print(f"Created case {case_name!r} for {input_dir}")


@app.command()
def ingest(case: str) -> None:
    """Parse the case's input directory and store canonical events."""
    store = _case_store(case)
    input_dir_s = store.get_meta("input_dir")
    if input_dir_s is None:
        print(f"Error: case {case!r} has no recorded input directory")
        raise typer.Exit(1)
    input_dir = Path(input_dir_s)
    if not input_dir.is_dir():
        print(f"Error: input directory no longer exists: {input_dir}")
        raise typer.Exit(1)
    files = [p for p in sorted(input_dir.rglob("*")) if p.is_file()]
    failed: list[str] = []
    coverage: dict[str, dict[str, object]] = {}
    total_new = 0
    # One transaction for all inserts plus the coverage meta write: an
    # interrupted ingest leaves either the complete result or nothing.
    with store.transaction():
        for path in files:
            relpath = path.relative_to(input_dir).as_posix()
            file_adapter = adapters.detect(path, relpath, overrides={})
            # v0: detect always returns genericlog; plan 01-04 generalises
            # per-run adapter configuration with the full sniff algorithm.
            assert isinstance(file_adapter, GenericLogAdapter)
            file_adapter.input_root = input_dir
            file_adapter.tz_overrides = {}
            try:
                events = list(file_adapter.parse(path, case))
                new_count = store.insert_events(events)
            except Exception as exc:
                # A bad file never silently vanishes: loud error, keep going.
                failed.append(relpath)
                print(f"ERROR {relpath}: {exc}")
                continue
            stats = file_adapter.last_stats
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
                f"{relpath}  coverage {cov * 100:.1f}%  "
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
def show(case: str, what: str) -> None:
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
    store = _case_store(case)
    for e in store.query_events():
        ts = e.ts.isoformat() if e.ts is not None else "-"
        message = _printable(e.message.replace("\n", " "))[:120]
        print(
            f"{e.event_id}  {ts}  {e.severity:<7}  "
            f"{e.source_file}:{e.line_start}  {message}"
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
