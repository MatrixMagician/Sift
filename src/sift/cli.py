"""Sift command-line interface.

Seven flat subcommands per SPEC.md §5.8. new/ingest/show are implemented in
Phase 1; analyze/report/eval/doctor arrive in later phases. Config resolution
follows D-08 precedence (flags > SIFT_* env > config.toml > defaults) — every
implemented command exposes ``--data-dir`` as the flags layer.
"""

import json
import sqlite3
import sys
import unicodedata
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from sift import adapters
from sift.adapters.genericlog import GenericLogAdapter
from sift.config import SiftConfig, load_config
from sift.pipeline import dedup
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
    try:
        return CaseStore(db_path)
    except sqlite3.Error as exc:
        # WR-02: corrupt or read-only evidence media fails loudly with a
        # message, never a Python traceback. Exception text can echo
        # attacker-controlled db bytes — sanitise (T-04-01).
        print(f"Error: cannot open case {case!r}: {_sanitise(str(exc))}")
        raise typer.Exit(1) from None


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
    try:
        _ingest(case, config, store)
    finally:
        # STORE-01 / Pitfall 4: a clean close checkpoints the WAL, so the
        # case directory holds only case.db afterwards — deleting the
        # directory is deleting the case.
        store.close()


def _ingest(case: str, config: SiftConfig, store: CaseStore) -> None:
    """Ingest body; the caller owns the store lifecycle (clean close)."""
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
    # CLI-03: live progress on stderr only — stdout stays scriptable and
    # byte-identical to Phase 1. disable= makes non-TTY runs (CliRunner, CI,
    # pipes) render nothing, deterministically.
    err_console = Console(stderr=True)
    sizes: dict[Path, int] = {}
    for path in files:
        try:
            sizes[path] = path.stat().st_size
        except OSError:
            # IN-04: a file vanishing between rglob and stat must fail loudly
            # in the per-file loop below, not abort the run with a traceback.
            sizes[path] = 0
    done_bytes = 0
    with Progress(
        # T-02-06: the description is a STATIC string — untrusted filenames
        # never enter rich renderables; per-file names keep flowing through
        # the existing _sanitise'd stdout prints.
        TextColumn("Ingesting"),
        BarColumn(),
        DownloadColumn(),
        TimeElapsedColumn(),
        console=err_console,
        transient=True,
        disable=not err_console.is_terminal,
    ) as progress:
        ptask = progress.add_task("ingest", total=sum(sizes.values()))
        # One transaction for all inserts plus the coverage meta write: an
        # interrupted ingest leaves either the complete result or nothing.
        with store.transaction():
            for path in files:
                file_size = sizes[path]
                relpath = path.relative_to(input_dir).as_posix()
                if path.is_symlink():
                    # Trust boundary: a hostile bundle must never select files
                    # outside itself for ingestion. Skip loudly and record it
                    # so the persisted coverage meta shows the file existed.
                    print(f"SKIP {_sanitise(relpath)}: symlink (not followed)")
                    coverage[relpath] = {
                        "skipped": "symlink (not followed)",
                        "event_count": 0,
                        "coverage": 0.0,
                    }
                    done_bytes += file_size
                    progress.update(ptask, completed=done_bytes)
                    continue
                try:
                    # CR-01: the whole per-file body runs inside a savepoint
                    # nested in the outer BEGIN IMMEDIATE transaction — a
                    # mid-stream parse failure rolls THIS file back to zero
                    # rows while earlier files' inserts survive.
                    with store.savepoint():
                        # Detection reads (and decompresses) file heads, so a
                        # corrupt archive can raise here too — it must hit the
                        # same loud per-file error path as a parse failure,
                        # never abort the run.
                        file_adapter = adapters.detect(path, relpath, overrides)
                        # Per-run configuration travels on the adapter
                        # instance — the frozen Protocol has no config
                        # attributes (01-02 pattern). D-05: config.timezones
                        # reaches the adapter.
                        if isinstance(file_adapter, GenericLogAdapter):
                            file_adapter.input_root = input_dir
                            file_adapter.tz_overrides = dict(config.timezones)
                        # T-02-05: stream events in bounded batches — a 100 MB
                        # file never materialises all its Event objects at
                        # once. Decompressed-stream offsets do not map to
                        # on-disk bytes for .gz/.zst, so those advance
                        # whole-file on completion.
                        track_offsets = isinstance(
                            file_adapter, GenericLogAdapter
                        ) and path.suffix not in (".gz", ".zst")
                        new_count = 0
                        parsed_count = 0
                        for batch in batched(
                            file_adapter.parse(path, case), 5000
                        ):
                            new_count += store.insert_events(batch)
                            parsed_count += len(batch)
                            if track_offsets:
                                attrs = batch[-1].attrs
                                offset = int(
                                    attrs.get("byte_offset", "0")
                                ) + int(attrs.get("byte_len", "0"))
                                progress.update(
                                    ptask,
                                    completed=done_bytes
                                    + min(offset, file_size),
                                )
                except Exception as exc:
                    # A bad file never silently vanishes: loud error, keep
                    # going. T-04-01: relpath and exception text carry
                    # untrusted bundle bytes (filenames may contain ESC) —
                    # sanitise at render time. The failure is also persisted
                    # so a report generated later still shows the file
                    # existed and failed.
                    failed.append(relpath)
                    coverage[relpath] = {
                        "error": str(exc),
                        "event_count": 0,
                        "coverage": 0.0,
                    }
                    print(f"ERROR {_sanitise(relpath)}: {_sanitise(str(exc))}")
                    done_bytes += file_size
                    progress.update(ptask, completed=done_bytes)
                    continue
                stats = (
                    file_adapter.last_stats
                    if isinstance(file_adapter, GenericLogAdapter)
                    else None
                )
                cov = stats.coverage if stats else 1.0
                event_count = stats.event_count if stats else parsed_count
                coverage[relpath] = {
                    "total_bytes": stats.total_bytes if stats else 0,
                    "unknown_fallback_bytes": (
                        stats.unknown_fallback_bytes if stats else 0
                    ),
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
                done_bytes += file_size
                progress.update(ptask, completed=done_bytes)
            store.set_meta("parse_coverage", json.dumps(coverage, sort_keys=True))
            # WR-03: mark the groups stale inside the same transaction as the
            # event inserts; rebuild_template_groups clears it — a crash in
            # between is detectable by `show clusters`.
            store.set_meta("template_groups_stale", "1")
    # Recompute template groups AFTER the event transaction commits, so the
    # groups always reflect the store's actual contents (CLUS-01, Pitfall 6).
    n_groups = dedup.rebuild_template_groups(store)
    print(f"Total: {total_new} new events")
    print(f"Template groups: {n_groups}")
    if failed:
        print(f"Error: {len(failed)} file(s) failed to parse")
        raise typer.Exit(1)


# The six-severity vocabulary (store CHECK constraint) for filter validation.
_SEVERITIES = ("fatal", "error", "warn", "info", "debug", "unknown")

# Valid --filter keys per show target (STORE-04). Mirrors the allowlist
# snippet dicts in store.py — the store re-validates as defence in depth.
_FILTER_KEYS: dict[str, tuple[str, ...]] = {
    "events": ("severity", "source", "file", "since", "until", "limit"),
    "clusters": ("severity", "min-count", "contains", "limit"),
}


def _parse_filters(specs: list[str], target: str) -> dict[str, str | int]:
    """Parse and validate repeated ``--filter key=value`` specs (typer-free).

    Splits on the FIRST '=': filter keys are allowlisted names that never
    contain '=', while values may (e.g. ``file=name=odd.log``). This is the
    deliberate opposite of parse_adapter_overrides' last-'=' split, where the
    '='-free side is the adapter name on the right. Raises ValueError on any
    invalid key or value — bad input fails loudly, never an empty result set
    that looks like 'no matches'. The CLI converts the error to exit 2.
    """
    valid_keys = _FILTER_KEYS[target]
    filters: dict[str, str | int] = {}
    for spec in specs:
        key, sep, value = spec.partition("=")
        if not sep or not key or not value:
            raise ValueError(f"invalid filter {spec!r}; expected key=value")
        if key not in valid_keys:
            raise ValueError(
                f"unknown filter key {key!r} for {target}; "
                f"valid keys: {', '.join(valid_keys)}"
            )
        if key in filters:
            # WR-05: never silent last-wins — a repeated key is a mistake the
            # operator must hear about (fail-loud prohibition).
            raise ValueError(
                f"duplicate filter key {key!r}; each key may appear once"
            )
        if key == "severity":
            if value not in _SEVERITIES:
                raise ValueError(
                    f"invalid severity {value!r}; "
                    f"valid severities: {', '.join(_SEVERITIES)}"
                )
            filters[key] = value
        elif key in ("limit", "min-count"):
            try:
                number = int(value)
            except ValueError:
                raise ValueError(
                    f"invalid {key} value {value!r}: not an integer"
                ) from None
            if number < 0:
                raise ValueError(
                    f"invalid {key} value {value!r}: must be non-negative"
                )
            filters[key] = number
        elif key in ("since", "until"):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                raise ValueError(
                    f"invalid {key} value {value!r}: not an ISO 8601 timestamp"
                ) from None
            if moment.tzinfo is None:
                # Naive input is treated as UTC (documented in --help).
                moment = moment.replace(tzinfo=UTC)
            # Stored ts strings are UTC isoformat — normalise before binding
            # so the string comparison in store.py is chronological.
            filters[key] = moment.astimezone(UTC).isoformat()
        else:
            filters[key] = value
    return filters


@app.command()
def show(
    case: str,
    what: str,
    # Typer reads the default once at import time; shared list is safe here.
    filters: Annotated[
        list[str], typer.Option("--filter", help="key=value filter (repeatable)")
    ] = [],  # noqa: B006
    data_dir: DataDirOption = None,
) -> None:
    """Show events, clusters or hypotheses for a case.

    Filters (repeatable, AND-combined): --filter key=value

    events keys: severity=<fatal|error|warn|info|debug|unknown>,
    source=<adapter>, file=<source-file substring>, since=<ISO 8601>,
    until=<ISO 8601>, limit=<N>.

    clusters keys: severity=<max severity>, min-count=<N>,
    contains=<template substring>, limit=<N>.

    Substring matches (file, contains) are literal — no wildcards. Naive
    since/until timestamps are treated as UTC; since/until exclude events
    without a timestamp (a documented filter semantic, not silent loss).
    """
    if what == "hypotheses":
        print("show hypotheses arrives in Phase 4 (M4)")
        raise typer.Exit(1)
    if what not in ("events", "clusters"):
        print(f"Error: unknown target {what!r}; expected events|clusters|hypotheses")
        raise typer.Exit(1)
    try:
        parsed = _parse_filters(filters, what)
    except ValueError as exc:
        # T-02-09: echoed filter values are untrusted input — sanitise.
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(2) from None
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        if what == "clusters":
            # WR-03: events committed but groups never rebuilt (crash between
            # the event transaction and the rebuild) — warn, still render.
            if store.get_meta("template_groups_stale") == "1":
                print(
                    "Warning: template groups are stale (last ingest did not "
                    "complete); re-run 'sift ingest'",
                    file=sys.stderr,
                )
            # STORE-04: template groups, count DESC then template ASC.
            # Templates and exemplar text carry hostile log bytes — sanitise
            # at render only (T-02-02); an empty table renders nothing, exit 0.
            # WR-01: EVERY DB-sourced field (ids, counts, timestamps,
            # severities, exemplars) is attacker-controlled in a shared
            # case.db — sanitise the COMPLETE rendered line, not per field.
            for g in store.query_template_groups(parsed or None):
                template = g.template.replace("\n", " ")[:100]
                print(_sanitise(
                    f"{g.template_id}  {g.count:>7}  {g.severity_max:<7}  "
                    f"{g.first_ts or '-'}  {g.last_ts or '-'}  {template}"
                ))
                print(_sanitise(
                    f"    exemplars: {' '.join(map(str, g.exemplar_event_ids))}"
                ))
            return
        # T-02-10: stream column-scoped rows — no raw column, no zstd
        # decompression, no full Event hydration. Lines stay byte-identical
        # to the Phase 1 rendering (stored ts strings ARE isoformat output).
        # WR-01: whole-line sanitisation covers event_id/ts/severity too.
        for event_id, ts, severity, source_file, line_start, message in (
            store.iter_event_rows(parsed or None)
        ):
            rendered = message.replace("\n", " ")[:120]
            print(_sanitise(
                f"{event_id}  {ts if ts is not None else '-'}  {severity:<7}  "
                f"{source_file}:{line_start}  {rendered}"
            ))
    finally:
        # Close so WAL sidecars checkpoint on every show path (Pitfall 4).
        store.close()


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
