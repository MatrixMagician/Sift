"""Sift command-line interface.

Seven flat subcommands per SPEC.md §5.8. new/ingest/show are implemented in
Phase 1; analyze/report/eval/doctor arrive in later phases. Config resolution
follows D-08 precedence (flags > SIFT_* env > config.toml > defaults) — every
implemented command exposes ``--data-dir`` as the flags layer.
"""

import json
import sqlite3
import sys
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from itertools import batched
from pathlib import Path
from typing import Annotated, cast

import httpx
import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from sift import adapters
from sift.adapters.base import ConfigurableAdapter
from sift.adapters.genericlog import GenericLogAdapter
from sift.config import SiftConfig, load_config
from sift.llm.client import Endpoint, InferenceClient
from sift.pipeline import dedup, retrieve
from sift.pipeline.cluster import cluster_and_label
from sift.pipeline.hypothesise import hypothesise
from sift.render._util import PdfExtraMissing
from sift.render._util import sanitise as _sanitise
from sift.store import CaseStore, case_db_path, vec_version

app = typer.Typer(no_args_is_help=True)


def _version_string() -> str:
    """Return the installed package version, or the source default off-tree."""
    try:
        return version("sift")
    except PackageNotFoundError:
        # Running from an uninstalled checkout (e.g. ``python -m sift.cli``):
        # no dist metadata exists, so fall back to the declared version.
        return "0.1.0"


def _version_callback(value: bool) -> None:
    """Eager ``--version`` handler: print the version and exit before dispatch.

    An eager Option callback fires during parsing, so it works even though the
    top-level group requires a subcommand (``no_args_is_help=True``).
    """
    if value:
        typer.echo(_version_string())
        raise typer.Exit()


@app.callback()
def _main(  # pyright: ignore[reportUnusedFunction] — registered via @app.callback
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the Sift version and exit.",
            is_eager=True,
            callback=_version_callback,
        ),
    ] = False,
) -> None:
    """Sift — a fully local, privacy-preserving incident triage engine."""


class DiskFullError(Exception):
    """A storage-exhaustion (SQLITE_FULL/IOERR) abort mid-ingest (WR-07).

    Distinct from a recoverable per-file parse failure: SQLite auto-rolls-back
    the whole transaction and destroys every savepoint, so the run must abort
    loudly with zero committed events, never be swallowed as one bad file.
    """

DataDirOption = Annotated[
    Path | None,
    typer.Option("--data-dir", help="Override the case data directory"),
]


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
    except DiskFullError as exc:
        # WR-07: abort loudly, non-zero, with zero events committed (the
        # transaction is already rolled back). Message text is already
        # sanitised at construction, but re-sanitise for defence in depth.
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(1) from None
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
                        # reaches EVERY ConfigurableAdapter, not just genericlog
                        # (05-01: dsserrors node-tagging + multi-node tz depend
                        # on this delivery).
                        if isinstance(file_adapter, ConfigurableAdapter):
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
                except sqlite3.Error as exc:
                    # WR-07: storage exhaustion is NOT a recoverable per-file
                    # error — SQLite has auto-rolled-back the whole transaction
                    # and destroyed every savepoint, so continuing would report
                    # a disk-full as one bad file and commit zero events. Detect
                    # the fatal codes (SQLITE_FULL=13, SQLITE_IOERR=10 + its
                    # extended codes share the low byte) and abort loudly. Catch
                    # order matters: sqlite3.Error is a subclass of Exception, so
                    # this handler MUST precede the generic one below.
                    code = getattr(exc, "sqlite_errorcode", None)
                    if code in (sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR) or (
                        code is not None and code & 0xFF == sqlite3.SQLITE_IOERR
                    ):
                        raise DiskFullError(
                            f"disk full / I/O error during ingest at "
                            f"{_sanitise(relpath)}: no events committed "
                            "(transaction rolled back)"
                        ) from exc
                    # Any other sqlite3.Error is a recoverable per-file failure:
                    # a sibling except cannot catch a re-raise, so record and
                    # continue here exactly as the generic handler does below.
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
                # Read the REAL per-file coverage for EVERY ConfigurableAdapter
                # (05-01): the stats=None -> cov=1.0 fallback must only apply to
                # a genuine non-ConfigurableAdapter, never fabricate 100% for a
                # domain adapter with unparseable regions (T-05-01).
                stats = (
                    file_adapter.last_stats
                    if isinstance(file_adapter, ConfigurableAdapter)
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
    # hypotheses: no filters yet (query_hypotheses returns the whole ranked set).
    # An empty allowlist means any --filter fails loudly (exit 2) rather than
    # being silently ignored — a richer filter set is out of scope for M4.
    "hypotheses": (),
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
    if what not in ("events", "clusters", "hypotheses"):
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
        if what == "hypotheses":
            # RAG-02: the persisted, ranked hypotheses (query_hypotheses orders
            # by hyp_index ASC). Nothing yet means analyze has not run — say so
            # and exit 0 (not the old Phase-4-pending stub).
            hyps = store.query_hypotheses()
            if not hyps:
                # WR-03: distinguish "analyze never ran" from a hard-degraded run
                # that persisted zero schema-valid rows but stored raw output —
                # the latter must not claim analyze never ran (nothing disappears
                # silently). triage_created_at is the "did analyze run" signal.
                if store.get_meta("triage_created_at") is not None:
                    print(
                        "No schema-valid hypotheses; the last analyze degraded "
                        "and persisted raw model output — run 'sift report' to "
                        "view the DEGRADED banner and raw output",
                        file=sys.stderr,
                    )
                    return
                print("No hypotheses yet; run 'sift analyze' first")
                return
            # A degraded run flagged rows or persisted raw output — warn on
            # stderr (mirrors the stale-groups warning) so stdout stays scriptable.
            if store.get_meta("triage_degraded") == "1":
                print(
                    "Warning: last analyze degraded — some hypotheses are FLAGGED "
                    "(invalid citations) or raw output was persisted; treat "
                    "flagged rows with care",
                    file=sys.stderr,
                )
            # WR-01: titles and cited ids are model-generated / DB-sourced and
            # attacker-controlled in a shared case.db — sanitise the COMPLETE
            # rendered line, never per field (T-04-03). FLAGGED marks a row whose
            # citations were not all shown to the model (never silently dropped).
            for h in hyps:
                marker = "OK" if h.citations_valid else "FLAGGED"
                title = h.title.replace("\n", " ")[:100]
                print(_sanitise(
                    f"{h.hyp_index}  {h.confidence:<6}  {marker:<7}  {title}"
                ))
                print(_sanitise(
                    f"    cites: {' '.join(map(str, h.supporting_event_ids))}"
                ))
            return
        if what == "clusters":
            # WR-03: events committed but groups never rebuilt (crash between
            # the event transaction and the rebuild) — warn, still render.
            if store.get_meta("template_groups_stale") == "1":
                print(
                    "Warning: template groups are stale (last ingest did not "
                    "complete); re-run 'sift ingest'",
                    file=sys.stderr,
                )
            # D-01: once `sift analyze` has run, the clusters table is populated
            # and IS the clusters view — render the label (else the signature
            # fallback) per row. Until then, fall back to the template groups as
            # the pre-cluster view. Decide on the unfiltered table so an applied
            # --filter that excludes every row still renders the clusters view
            # (zero matches), never silently reverting to template groups.
            if store.query_clusters():
                # STORE-04: clusters, count DESC then cluster_id ASC. Labels are
                # model-generated and signatures carry hostile log bytes — WR-01:
                # sanitise the COMPLETE rendered line, not per field (T-03-20).
                for c in store.query_clusters(parsed or None):
                    name = (c.label or c.signature).replace("\n", " ")[:100]
                    print(_sanitise(
                        f"{c.cluster_id}  {c.count:>7}  {c.severity_max:<7}  {name}"
                    ))
                return
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


# Triage-run defaults (CLI-04). Salience feeds at most this many top clusters to
# the hypothesiser; the ctx/reserve fallbacks apply only when /props is absent
# (Lemonade, LLM-04) — llama-server's n_ctx overrides ctx_fallback at runtime.
_DEFAULT_TOP_CLUSTERS = 12
_TRIAGE_CTX_FALLBACK = 8192
_TRIAGE_RESERVE_OUT = 1024


def _parse_moment(value: str | None, label: str) -> datetime | None:
    """Parse an ISO 8601 ``--since``/``--until`` value to a UTC datetime.

    Mirrors the ``_parse_filters`` datetime idiom: a naive value is treated as
    UTC then normalised to UTC. A bad value raises ``typer.Exit(2)`` — a usage
    error, never a silent ``None`` that would look like an absent window.
    ``--hint`` is NEVER routed through here: it is free operator text, not a
    timestamp, and reaches the prompt verbatim.
    """
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        # T-04-01: echo the untrusted flag value only after sanitising it.
        print(
            f"Error: invalid {label} value {_sanitise(value)!r}: "
            "not an ISO 8601 timestamp"
        )
        raise typer.Exit(2) from None
    if moment.tzinfo is None:
        # Naive input is treated as UTC (documented in --help).
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@app.command()
def analyze(
    case: str,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)",
        ),
    ] = False,
    no_label: Annotated[
        bool,
        typer.Option(
            "--no-label",
            help="Skip LLM cluster labels; clusters keep their signature (D-01)",
        ),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the generation+embeddings model id"),
    ] = None,
    hint: Annotated[
        str | None,
        typer.Option(
            "--hint",
            help="Operator context appended verbatim to the prompt (never a time)",
        ),
    ] = None,
    kb: Annotated[
        Path | None,
        typer.Option(
            "--kb",
            help="Index a directory of runbooks/RCAs and thread the nearest "
            "chunks into the triage prompt as non-citable reference material "
            "(RAG-07, D-01)",
        ),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Only rank clusters intersecting on/after this ISO 8601 time",
        ),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            "--until",
            help="Rank clusters on/before this ISO 8601 time; also the "
            "incident-time anchor (defaults to case end)",
        ),
    ] = None,
    top_clusters: Annotated[
        int,
        typer.Option(
            "--top-clusters",
            help="How many top-salience clusters to feed the hypothesiser",
        ),
    ] = _DEFAULT_TOP_CLUSTERS,
    data_dir: DataDirOption = None,
) -> None:
    """Embed, cluster and label the case, then generate cited hypotheses (M4).

    The full triage slice: synonymous template groups are embedded and clustered
    (HDBSCAN / agglomerative fallback) and eagerly labelled by the local LLM
    (D-01, skip with ``--no-label``), then ranked by salience and passed to the
    citation-gated hypothesiser (RAG-02) — every hypothesis must cite an event
    the model was actually shown, or the run degrades. ``--hint`` adds operator
    context verbatim (never parsed as a time); ``--since``/``--until`` scope the
    ranked clusters (``--until`` also anchors the incident time, defaulting to
    case end); ``--top-clusters`` caps how many clusters feed the prompt.
    ``--kb <dir>`` indexes a directory of runbooks/RCAs and threads the nearest
    chunks into the prompt as NON-citable reference material (RAG-07, D-01).
    ``sift show clusters`` / ``sift show hypotheses`` render the result.

    Exit-code contract (CLI-04, scriptable — see ADR 0005):

    \b
      0  success   hypotheses generated; every citation is valid
      3  degraded  ran to completion but repair failed or a citation was
                    invalid — output persisted and FLAGGED, not a clean success
      1  failure   inference transport error, SSRF refusal, or corrupt/absent
                    case.db — nothing new persisted
      2  usage     Typer/Click usage error (e.g. a malformed --since/--until)

    ``--until`` also sets the salience incident-time anchor (defaults to the
    case-end timestamp when omitted).
    """
    # A bad --since/--until is a usage error (exit 2); parse before touching the
    # store so it fails fast. --hint is never parsed as a time.
    since_dt = _parse_moment(since, "since")
    until_dt = _parse_moment(until, "until")
    # D-03 precedence: --model feeds BOTH roles' config (flags win, deep-merged).
    overrides: dict[str, object] = {"data_dir": data_dir}
    if model is not None:
        overrides["generation"] = {"model": model}
        overrides["embeddings"] = {"model": model}
    config = load_config(overrides)
    store = _case_store(case, config)
    try:
        # CLUS-01: zero template groups means ingest has not run (or produced
        # nothing) — there is nothing to embed, so skip the client entirely and
        # exit cleanly. groups > 0 always yields >= 1 cluster (auto-singleton).
        groups = store.query_template_groups()
        if not groups:
            print("Nothing to cluster; run 'sift ingest' first")
            return

        gen_ep = Endpoint(
            base_url=config.generation.base_url, model=config.generation.model
        )
        emb_ep = Endpoint(
            base_url=config.embeddings.base_url, model=config.embeddings.model
        )
        http = _make_http_client(
            max(config.generation.timeout, config.embeddings.timeout)
        )
        try:
            # Construct the client → runs the loopback/RFC1918 SSRF guard on BOTH
            # base_urls (LLM-02). A public endpoint without the override refuses.
            try:
                client = InferenceClient(
                    generation=gen_ep,
                    embeddings=emb_ep,
                    http=http,
                    allow_public=i_know_what_im_doing,
                    retries=config.generation.retries,
                    backoff_base=config.generation.backoff_base,
                    batch_size=config.embeddings.batch_size,
                    max_input_chars=config.embeddings.max_input_chars,
                )
            except ValueError as exc:
                print(f"Error: {_sanitise(str(exc))}")
                raise typer.Exit(1) from None

            # CLI-03: transient stderr-only progress with a STATIC description —
            # untrusted server/DB text never enters a rich renderable (T-03-23).
            # stdout stays scriptable; a non-TTY run renders nothing (disable=).
            # The embed + cluster + label + persist is one opaque call, so the
            # count column ticks from 0/N to N/N once it completes.
            err_console = Console(stderr=True)
            with Progress(
                TextColumn("Embedding"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=err_console,
                transient=True,
                disable=not err_console.is_terminal,
            ) as progress:
                ptask = progress.add_task("embed", total=len(groups))
                try:
                    # T-03-22: cluster_and_label persists everything inside ONE
                    # store.transaction(); an interrupted embed (client raises)
                    # rolls back to zero clusters/vectors — the embed call is the
                    # first step and precedes every write, so nothing survives.
                    n_clusters = cluster_and_label(
                        store, client, config.clustering, label=not no_label
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"Error: embedding/clustering failed: {_sanitise(str(exc))}")
                    raise typer.Exit(1) from None
                progress.update(ptask, completed=len(groups))

            # RAG-07: when --kb is given, index the runbook/RCA directory and
            # retrieve the nearest chunks against the top salient clusters, then
            # thread them into the triage prompt as NON-citable reference
            # material (D-01). KB embeds through the SAME injected client whose
            # SSRF guard already ran on both base_urls (LLM-02) — no new HTTP
            # path. An embed/index failure maps to exit 1 with a sanitised
            # message, mirroring the cluster-embed failure above (T-06-19).
            kb_context: list[str] | None = None
            if kb is not None:
                try:
                    retrieve.index_kb(store, client, kb)
                    query_texts = [
                        c.label or c.signature
                        for c in store.query_clusters()[:top_clusters]
                    ]
                    kb_context = retrieve.retrieve_kb(store, client, query_texts)
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"Error: KB indexing/retrieval failed: {_sanitise(str(exc))}")
                    raise typer.Exit(1) from None

            # RAG-02: salience + citation-gated hypotheses over the fresh
            # clusters, still inside the http lifecycle so the same client is
            # reused. hypothesise NEVER raises on bad model output — it degrades
            # and persists; a transport/SSRF error returns a failed Outcome.
            # --until doubles as the salience incident-time anchor (RESEARCH Q3);
            # None lets salience derive it from the case-end timestamp.
            outcome = hypothesise(
                store,
                client,
                top_clusters=top_clusters,
                incident_time=until_dt,
                since=since_dt,
                until=until_dt,
                hint=hint,
                kb_context=kb_context,
                mcm_thresholds=config.mcm.thresholds,
                ctx_fallback=config.generation.context or _TRIAGE_CTX_FALLBACK,
                reserve_out=_TRIAGE_RESERVE_OUT,
            )
        finally:
            http.close()

        # Counts are ints — no untrusted text. The labels themselves are only
        # rendered by `show clusters`, where the whole line is _sanitise'd.
        labelled = sum(1 for c in store.query_clusters() if c.label)
        print(f"Clusters: {n_clusters} ({labelled} labelled)")

        # CLI-04 exit-code contract: failed -> 1, degraded -> 3, success -> 0.
        # (Typer/Click usage errors stay 2; never reused here.)
        if outcome.failed:
            # Surface the real cause (a transport failure, OR a server-rejected
            # 200 body such as a context overflow — 'request (N tokens) exceeds
            # the available context size') instead of always blaming transport.
            # A context overflow is fixed by loading the model with a larger
            # context, lowering --top-clusters, or setting generation.context.
            reason = outcome.error or "the inference endpoint returned no output"
            print(
                f"Error: hypothesis generation failed ({_sanitise(reason)}); "
                "no hypotheses were persisted"
            )
            raise typer.Exit(1)
        count = len(outcome.hypotheses.hypotheses) if outcome.hypotheses else 0
        if outcome.degraded:
            # A degraded run RAN to completion but the model output could not be
            # fully validated or some citations were invalid — the flagged/raw
            # output is persisted, never presented as a clean success (T-04-02).
            print(
                "Warning: triage degraded — the model output could not be fully "
                "validated or some citations were invalid; the raw/flagged "
                "output was persisted (see 'sift show hypotheses')",
                file=sys.stderr,
            )
            print(f"Hypotheses: {count} (degraded)")
            raise typer.Exit(3)
        print(f"Hypotheses: {count}")
        print("Run 'sift show hypotheses' to view them")
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring
        # ingest — the case directory holds only case.db afterwards.
        store.close()


class ReportFormat(StrEnum):
    """Output formats for ``sift report`` (an unknown value is a Typer usage
    error, exit 2 — never a semantic outcome; ADR 0007)."""

    md = "md"
    json = "json"
    pdf = "pdf"


@app.command()
def report(
    case: str,
    fmt: Annotated[
        ReportFormat,
        typer.Option("--format", help="Output format: md (default), json or pdf"),
    ] = ReportFormat.md,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write to this file instead of stdout"),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Render a self-contained triage report from a case (REPT-01).

    A pure function of ``case.db``: no inference client is constructed and no
    network call is made (zero-egress invariant). Exit-code contract (ADR 0007):
    0 = rendered (including a degraded case — the banner communicates
    degradation), 1 = no hypotheses / render-or-IO failure / missing sift[pdf],
    2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        # WR-03/IN-04: gate on whether analyze RAN (triage_created_at present),
        # not on whether it produced schema-valid rows. A hard-degraded run
        # persists zero hypotheses but sets triage_created_at and triage_raw —
        # that is a reportable degraded run (banner + raw), never "run analyze
        # first". Reserve the no-triage message for the genuine never-analysed
        # case. Gating on run-meta also drops the redundant second
        # query_hypotheses (the renderer runs it once) — IN-04.
        if store.get_meta("triage_created_at") is None:
            print("No hypotheses to report; run 'sift analyze' first")
            raise typer.Exit(1)
        if fmt is ReportFormat.pdf:
            if out is None:
                print("Error: --format pdf requires --out <path>")
                raise typer.Exit(1)
            try:
                # Renderer delivered in 06-05 — lazy so md/json need no WeasyPrint.
                from sift.render.pdf import render_pdf  # type: ignore

                render_pdf(store, out)
            except (ImportError, PdfExtraMissing) as exc:
                print(
                    "Error: PDF rendering unavailable; install the sift[pdf] "
                    f"extra and pango ({_sanitise(str(exc))})"
                )
                raise typer.Exit(1) from None
            except OSError as exc:
                # WR-02: a write-target failure is NOT a missing-extra problem —
                # render_pdf renders to bytes first, so an OSError here can only
                # be the file write. Report it as such, not as "install pango".
                print(f"Error: cannot write report to {out}: {_sanitise(str(exc))}")
                raise typer.Exit(1) from None
            except ValueError as exc:
                # WR-04: the zero-egress url_fetcher raises ValueError on any
                # blocked fetch (e.g. an injected <img> in model text). Egress is
                # still blocked; surface a clean render failure, never a traceback.
                print(f"Error: PDF rendering failed: {_sanitise(str(exc))}")
                raise typer.Exit(1) from None
            return
        if fmt is ReportFormat.md:
            from sift.render.markdown import render_markdown

            text = render_markdown(store)
        else:  # ReportFormat.json
            from sift.render.json_out import render_json

            text = render_json(store)
        if out is not None:
            try:
                out.write_text(text, encoding="utf-8")
            except OSError as exc:
                # ADR 0007: a --out write failure (unwritable path, missing
                # parent, full disk) is exit 1 with a helpful message, never a
                # raw traceback — mirroring the pdf branch.
                print(f"Error: cannot write report to {out}: {_sanitise(str(exc))}")
                raise typer.Exit(1) from None
        else:
            print(text)
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4).
        store.close()


class McmFormat(StrEnum):
    """Report format for ``sift mcm`` (an unknown value is a Typer usage error,
    exit 2 — mirrors ``ReportFormat``; ADR 0007). The CSV is always written."""

    md = "md"
    json = "json"


@app.command()
def mcm(
    case: str,
    fmt: Annotated[
        McmFormat,
        typer.Option("--format", help="Report format: md (default) or json"),
    ] = McmFormat.md,
    data_dir: DataDirOption = None,
) -> None:
    """Write the MCM forensics bundle for a case (MCM-05, D-10).

    Runs the deterministic ``analyse_mcm`` over the stored events (no LLM, no
    network — the figures are computed from log text, never model-authored) and
    ALWAYS writes ``<case>/mcm/mcm_report.md`` (or ``mcm_report.json`` with
    ``--format json``) AND ``<case>/mcm/mcm_attribution.csv``, then prints a
    short stdout summary. Thresholds and the lead-up window are config-only —
    there is no per-run CLI knob (D-12/D-13). Exit-code contract (ADR 0007):
    0 = bundle written (including an empty case), 1 = missing case / write
    failure, 2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        from sift.pipeline.mcm import analyse_mcm
        from sift.render.mcm_report import (
            render_mcm_json,
            render_mcm_markdown,
            write_attribution_csv,
        )

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
            # WR-06: report is written before the CSV, so a mid-CSV failure would
            # leave a valid-looking report next to a truncated CSV. Unlink both so
            # a half-written bundle is never mistaken for a complete one.
            for partial in (
                mcm_dir / report_name,
                mcm_dir / "mcm_attribution.csv",
            ):
                partial.unlink(missing_ok=True)
            # WR-02: a write-target failure is exit 1 with a helpful, sanitised
            # message, never a raw traceback (mirrors report).
            print(f"Error: cannot write MCM bundle to {mcm_dir}: {_sanitise(str(exc))}")
            raise typer.Exit(1) from None

        n = len(analysis.episodes)
        plural = "episode" if n == 1 else "episodes"
        print(
            f"Analysed {n} MCM denial {plural}; wrote {report_name} + "
            f"mcm_attribution.csv to {mcm_dir}"
        )
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


class PerfmonFormat(StrEnum):
    """Report format for ``sift perfmon`` (an unknown value is a Typer usage
    error, exit 2 — mirrors ``McmFormat``; ADR 0007). The CSV is always
    written."""

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
    """Write the perfmon correlation bundle for a case (PERF-06, D-17).

    Correlates the stored DSSPerformanceMonitor samples with the MCM denial
    episodes ``analyse_mcm`` detects (no LLM, no network — the figures are
    computed from counter readings, never model-authored) and ALWAYS writes
    ``<case>/perfmon/perfmon_report.md`` (or ``perfmon_report.json`` with
    ``--format json``) AND ``<case>/perfmon/perfmon_trend.csv``, then prints a
    short stdout summary. With no DSSErrors log, and therefore no episodes,
    there is no window: the same figures are computed over each file's full
    sample range and the report says so plainly (D-20). Exit-code contract
    (ADR 0007): 0 = bundle written (including an empty case), 1 = missing case
    / write failure, 2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        from sift.pipeline.mcm import analyse_mcm
        from sift.pipeline.perfmon import analyse_perfmon
        from sift.render.perfmon_report import (
            render_perfmon_json,
            render_perfmon_markdown,
            write_perfmon_trend_csv,
        )

        # T-13-PATH: the bundle dir is derived from the SAME resolved case path
        # _case_store validated (case_db_path asserts containment) — only
        # <case>/perfmon/ beneath it is ever created, never a user-supplied path.
        perfmon_dir = case_db_path(config.data_dir, case).parent / "perfmon"
        # ONCE (T-13-DOUBLEREAD): the call hydrates and zstd-decompresses every
        # row in the case, so the same list feeds both analyses rather than
        # doubling an already-accepted cost. config.mcm.thresholds is threaded
        # in only because obtaining the episodes needs it — the perfmon hazards
        # themselves take no config knob.
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
            # WR-06: the report is written before the CSV, so a mid-CSV failure
            # would otherwise leave a valid-looking report next to a truncated
            # CSV. Unlink both so a later reader never mistakes a half-written
            # bundle for a complete one.
            for partial in (
                perfmon_dir / report_name,
                perfmon_dir / "perfmon_trend.csv",
            ):
                partial.unlink(missing_ok=True)
            # T-13-ERRLEAK: exit 1 with a sanitised message; `from None`
            # suppresses the traceback chain so no stack frame or internal path
            # reaches the operator.
            print(
                f"Error: cannot write perfmon bundle to {perfmon_dir}: "
                f"{_sanitise(str(exc))}"
            )
            raise typer.Exit(1) from None

        n = len(analysis.groups)
        plural = "span" if n == 1 else "spans"
        print(
            f"Correlated {n} {plural}; wrote {report_name} + "
            f"perfmon_trend.csv to {perfmon_dir}"
        )
        _sev_rank = {"critical": 0, "warn": 1, "info": 2}
        for i, group in enumerate(analysis.groups, start=1):
            hazards = sorted(group.hazards, key=lambda h: _sev_rank.get(h.severity, 3))
            if hazards:
                top = hazards[0]
                # T-13-STDOUTESC: counter names originate in the customer's CSV
                # header, so hazard text goes through _sanitise before echo.
                print(f"  Span {i}: {top.severity} — {_sanitise(top.message)}")
            else:
                print(f"  Span {i}: no correlation hazards raised")
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring mcm.
        store.close()


@app.command("eval")
def eval_(
    suite: Annotated[
        Path,
        typer.Option("--suite", help="Directory of golden cases (default eval/cases)"),
    ] = Path("eval/cases"),
    thresholds: Annotated[
        Path,
        typer.Option(
            "--thresholds",
            help="TOML of per-metric floors (default eval/thresholds.toml)",
        ),
    ] = Path("eval/thresholds.toml"),
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the machine-readable metric table as JSON"),
    ] = False,
    judge: Annotated[
        bool,
        typer.Option(
            "--judge",
            help="Add an advisory local-model judge score (never affects the gate)",
        ),
    ] = False,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)",
        ),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the generation+embeddings model id"),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Run the golden-case evaluation suite and print the metric table (EVAL-02).

    Each case under ``--suite`` runs through the real ingest → cluster →
    hypothesise pipeline against a temp case.db, then the four quality metrics
    (retrieval hit rate, hypothesis hit@k, citation validity, determinism drift)
    are scored against its frozen ``truth.yaml``. Offline runs inject a fake
    client via the ``_make_http_client`` seam (EVAL-05). ``--json`` emits the
    machine-readable table.

    The suite is gated against ``--thresholds`` (default ``eval/thresholds.toml``,
    ADR 0010): exit 0 when every keyword-metric aggregate clears its floor and no
    case failed; exit 1 when a metric regressed, a case could not run, or a
    negative case emitted a confident hypothesis (a non-suppressible CI signal).
    A missing/invalid ``--suite`` or unreadable ``--thresholds`` is a usage error
    (exit 2).
    """
    from sift.eval.metrics import SuiteResult
    from sift.eval.report import render_json_table, render_text_table
    from sift.eval.runner import run_case
    from sift.eval.thresholds import gate, load_thresholds

    if not suite.is_dir():
        print(f"Error: suite directory does not exist: {suite}")
        raise typer.Exit(2)
    case_dirs = sorted(
        d for d in suite.iterdir() if d.is_dir() and (d / "truth.yaml").exists()
    )
    if not case_dirs:
        print(f"Error: no golden cases (with truth.yaml) under {suite}")
        raise typer.Exit(2)
    try:
        floors = load_thresholds(thresholds)
    except ValueError as exc:
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(2) from None

    overrides: dict[str, object] = {"data_dir": data_dir}
    if model is not None:
        overrides["generation"] = {"model": model}
        overrides["embeddings"] = {"model": model}
    config = load_config(overrides)

    gen_ep = Endpoint(
        base_url=config.generation.base_url, model=config.generation.model
    )
    emb_ep = Endpoint(
        base_url=config.embeddings.base_url, model=config.embeddings.model
    )
    http = _make_http_client(
        max(config.generation.timeout, config.embeddings.timeout)
    )
    try:
        try:
            client = InferenceClient(
                generation=gen_ep,
                embeddings=emb_ep,
                http=http,
                allow_public=i_know_what_im_doing,
                retries=config.generation.retries,
                backoff_base=config.generation.backoff_base,
                batch_size=config.embeddings.batch_size,
            )
        except ValueError as exc:
            print(f"Error: {_sanitise(str(exc))}")
            raise typer.Exit(1) from None
        results = [
            run_case(case_dir, client, config, judge=judge) for case_dir in case_dirs
        ]
    finally:
        http.close()

    suite_result = SuiteResult(results)
    gate_result = gate(suite_result, floors)
    if as_json:
        print(render_json_table(suite_result, gate_result), end="")
    else:
        print(render_text_table(suite_result, gate_result, show_judge=judge), end="")
    # The command OWNS the non-zero exit so CI sees a regression (T-07-07);
    # it is never suppressed by an advisory judge score (D-08).
    if not gate_result.passed:
        raise typer.Exit(1)


# The exact, actionable failure message for the Lemonade OGA/ONNX-recipe case
# (D-02 / RESEARCH Pitfall 2): a model is listed but /v1/embeddings returns no
# usable vector. Never inferred from /v1/models — only a real round-trip reveals it.
_OGA_ONNX_MSG = (
    "embeddings unsupported on this model/recipe; load a llamacpp/flm-recipe "
    "embedding model (Lemonade) or start llama-server with --embeddings"
)


def _make_http_client(timeout: float) -> httpx.Client:
    """Build the injected httpx.Client for doctor/analyze (per-request timeouts).

    A module-level seam so tests bind an ``httpx.MockTransport`` and open no
    socket (EVAL-05) while the real SSRF guard still runs at ``InferenceClient``
    construction. Explicit timeouts treat the local server as untrusted (Pitfall
    4 / T-03-05): a hostile or misconfigured endpoint can never hang doctor.
    """
    return httpx.Client(timeout=httpx.Timeout(timeout))


@app.command()
def doctor(
    case: Annotated[
        str | None,
        typer.Argument(help="Optional case: check the server dim against its index"),
    ] = None,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)",
        ),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the generation+embeddings model id"),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Verify the local inference endpoints and vector support (fail-fast).

    D-02: checks run in dependency order and STOP at the first critical failure
    with a non-zero exit, naming the failure mode. The embedding check is a REAL
    round-trip (an actual ``/v1/embeddings`` call) — the only thing that catches
    a Lemonade OGA/ONNX-recipe model that lists but cannot embed. Determinism
    risks reached before any stop print as warnings without failing.
    """
    # D-03 precedence: --model feeds BOTH roles' config (flags win, deep-merged).
    overrides: dict[str, object] = {"data_dir": data_dir}
    if model is not None:
        overrides["generation"] = {"model": model}
        overrides["embeddings"] = {"model": model}
    config = load_config(overrides)
    gen_ep = Endpoint(
        base_url=config.generation.base_url, model=config.generation.model
    )
    emb_ep = Endpoint(
        base_url=config.embeddings.base_url, model=config.embeddings.model
    )

    http = _make_http_client(max(config.generation.timeout, config.embeddings.timeout))
    try:
        # 1. Construct the client → runs the loopback/RFC1918 SSRF guard on BOTH
        # base_urls (LLM-02). A public endpoint without the override is refused.
        try:
            client = InferenceClient(
                generation=gen_ep,
                embeddings=emb_ep,
                http=http,
                allow_public=i_know_what_im_doing,
                retries=config.generation.retries,
                backoff_base=config.generation.backoff_base,
                batch_size=config.embeddings.batch_size,
            )
        except ValueError as exc:
            print(f"Error: {_sanitise(str(exc))}")
            raise typer.Exit(1) from None

        # 2. GET /v1/models on the generation endpoint [CRITICAL if unreachable].
        try:
            gen_models = client.models(gen_ep)
        except (httpx.HTTPError, ValueError) as exc:
            print(
                f"Error: generation endpoint {gen_ep.base_url!r} unreachable: "
                f"{_sanitise(str(exc))}"
            )
            raise typer.Exit(1) from None
        print(
            "generation endpoint OK: "
            + _sanitise(", ".join(gen_models) or "(no models listed)")
        )

        # 3. GET /v1/models on the embeddings endpoint [CRITICAL if unreachable].
        try:
            emb_models = client.models(emb_ep)
        except (httpx.HTTPError, ValueError) as exc:
            print(
                f"Error: embeddings endpoint {emb_ep.base_url!r} unreachable: "
                f"{_sanitise(str(exc))}"
            )
            raise typer.Exit(1) from None
        print(
            "embeddings endpoint OK: "
            + _sanitise(", ".join(emb_models) or "(no models listed)")
        )

        # 4. REAL /v1/embeddings round-trip [CRITICAL]. An OGA/ONNX-recipe server
        # lists a model but returns an empty embedding — embed() raises. Never
        # infer capability from the /v1/models listing above (Pitfall 2, T-03-13).
        try:
            vectors = client.embed(["sift doctor embedding probe"])
        except (httpx.HTTPError, ValueError):
            print(f"Error: {_OGA_ONNX_MSG}")
            raise typer.Exit(1) from None
        if not vectors or not vectors[0]:
            print(f"Error: {_OGA_ONNX_MSG}")
            raise typer.Exit(1) from None
        dim = len(vectors[0])
        print(f"embedding round-trip OK: dimension {dim}")

        # 5. If a case is given, compare the returned dim against its recorded
        # index dimension [CRITICAL on mismatch] (LLM-03 + STORE-03). The dim is
        # an int on both sides — compared exactly, no rounding.
        if case is not None:
            store = _case_store(case, config)
            try:
                existing = store.get_meta("embedding_dim")
            finally:
                store.close()
            if existing is not None and int(existing) != dim:
                print(
                    f"Error: embedding dimension mismatch: case index has "
                    f"{int(existing)}, server returned {dim}"
                )
                raise typer.Exit(1) from None
            if existing is not None:
                print(f"case index dimension OK: {int(existing)} matches server")

        # 6. Load sqlite-vec on a throwaway connection and read vec_version()
        # [CRITICAL if it cannot load] (Pitfall 5). Names the enable_load_extension
        # caveat so a Python build without it is diagnosed by name.
        try:
            version = vec_version()
        except Exception as exc:  # noqa: BLE001 — any load failure is the same caveat
            print(
                "Error: cannot load the sqlite-vec extension; this Python's "
                "sqlite3 does not permit extension loading "
                f"(enable_load_extension): {_sanitise(str(exc))}"
            )
            raise typer.Exit(1) from None
        print(f"sqlite-vec OK: vec_version {_sanitise(version)}")

        # 7. Determinism WARNING (non-fatal): a multi-slot server or a random
        # seed breaks reproducibility (T-03-15). /props is feature-detected and
        # returns {} when absent (Lemonade), so an empty props warns nothing.
        props = client.props()
        n_parallel = props.get("n_parallel")
        if (
            isinstance(n_parallel, int)
            and not isinstance(n_parallel, bool)
            and n_parallel > 1
        ):
            print(
                f"Warning: server reports n_parallel={n_parallel} (multi-slot); "
                "results may be non-deterministic — run a single slot for "
                "reproducible triage",
                file=sys.stderr,
            )
        gen_settings = props.get("default_generation_settings")
        if isinstance(gen_settings, dict):
            seed = cast("dict[str, object]", gen_settings).get("seed")
            if isinstance(seed, int) and not isinstance(seed, bool) and seed < 0:
                print(
                    "Warning: server seed is random (< 0); set a fixed seed for "
                    "reproducible triage",
                    file=sys.stderr,
                )

        print("doctor: all checks passed")
    finally:
        http.close()
