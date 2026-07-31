"""Ingest orchestration: parse a case's input directory into canonical events.

Extracted from ``cli.py`` so the eval harness (``eval/runner.py``) can drive
the exact production ingest path without importing the CLI — this module is
typer-free, and error conditions surface as typed exceptions the CLI maps to
its exit-code contract (usage errors -> 2, ingest failures -> 1).

Unlike the other pipeline modules this one is deliberately NOT print-free: the
per-file coverage lines and the trailing totals ARE the ``sift ingest`` stdout
contract (scriptable, byte-stable), and the transient rich progress bar renders
on stderr only (CLI-03). The eval harness contains both streams with
``contextlib.redirect_stdout``/``redirect_stderr``.
"""

from __future__ import annotations

import json
import sqlite3
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from sift import adapters
from sift.adapters.base import ConfigurableAdapter
from sift.adapters.genericlog import GenericLogAdapter
from sift.pipeline import dedup
from sift.render._util import sanitise as _sanitise

if TYPE_CHECKING:
    from sift.config import SiftConfig
    from sift.store import CaseStore


class IngestError(RuntimeError):
    """A non-usage ingest failure (CLI exit 1): missing/vanished input
    directory, or one or more files failing to parse."""


class IngestUsageError(ValueError):
    """A usage-level ingest failure (CLI exit 2): malformed adapter override
    specs or an unknown adapter name."""


class DiskFullError(IngestError):
    """A storage-exhaustion (SQLITE_FULL/IOERR) abort mid-ingest (WR-07).

    Distinct from a recoverable per-file parse failure: SQLite auto-rolls-back
    the whole transaction and destroys every savepoint, so the run must abort
    loudly with zero committed events, never be swallowed as one bad file.
    """


def run_ingest(case: str, config: SiftConfig, store: CaseStore) -> None:
    """Ingest body; the caller owns the store lifecycle (clean close)."""
    input_dir_s = store.get_meta("input_dir")
    if input_dir_s is None:
        raise IngestError(f"case {case!r} has no recorded input directory")
    input_dir = Path(input_dir_s)
    if not input_dir.is_dir():
        raise IngestError(f"input directory no longer exists: {input_dir}")

    raw_specs: list[str] = json.loads(store.get_meta("adapter_overrides") or "[]")
    try:
        flag_overrides = adapters.parse_adapter_overrides(raw_specs)
    except ValueError as exc:
        raise IngestUsageError(str(exc)) from None
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
        raise IngestUsageError(
            f"unknown adapter(s) {unknown}; "
            f"known adapters: {sorted(adapters.REGISTRY)}"
        )

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
                except Exception as exc:
                    # WR-07: storage exhaustion is NOT a recoverable per-file
                    # error — SQLite has auto-rolled-back the whole transaction
                    # and destroyed every savepoint, so continuing would report
                    # a disk-full as one bad file and commit zero events. Detect
                    # the fatal codes (SQLITE_FULL=13, SQLITE_IOERR=10 + its
                    # extended codes share the low byte) and abort loudly; any
                    # other error — sqlite3 or not — falls through to the shared
                    # recoverable per-file body below.
                    if isinstance(exc, sqlite3.Error):
                        code = getattr(exc, "sqlite_errorcode", None)
                        if code in (sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR) or (
                            code is not None and code & 0xFF == sqlite3.SQLITE_IOERR
                        ):
                            raise DiskFullError(
                                f"disk full / I/O error during ingest at "
                                f"{_sanitise(relpath)}: no events committed "
                                "(transaction rolled back)"
                            ) from exc
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
        raise IngestError(f"{len(failed)} file(s) failed to parse")
