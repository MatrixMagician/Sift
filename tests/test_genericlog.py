"""genericlog adapter tests: format, timezone, multiline, coverage, encoding,
compressed groups (selectable via ``pytest -k <group>``).

Fixture logs are built with local helpers — tests/conftest.py is owned by
plan 01-01 and must not grow fixtures for this module.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from sift.adapters.base import ParseStats
from sift.adapters.genericlog import GenericLogAdapter
from sift.models import Event


def write_log(root: Path, relname: str, data: bytes) -> Path:
    """Write fixture bytes at root/relname, creating parent directories."""
    path = root / relname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def run_parse(
    root: Path,
    relname: str,
    tz_overrides: dict[str, str] | None = None,
) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = GenericLogAdapter()
    adapter.input_root = root
    if tz_overrides:
        adapter.tz_overrides = tz_overrides
    events = list(adapter.parse(root / relname, "case1"))
    assert adapter.last_stats is not None
    return events, adapter.last_stats


def set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


# ---------------------------------------------------------------- format ---


def test_format_iso_variants(tmp_path: Path) -> None:
    write_log(
        tmp_path,
        "app.log",
        b"2026-07-16 14:02:03,123 ERROR naive comma millis\n"
        b"2026-07-16T14:02:03Z INFO zulu\n"
        b"2026-07-16T14:02:03+02:00 WARN offset\n",
    )
    events, _ = run_parse(tmp_path, "app.log")
    assert len(events) == 3
    naive, zulu, offset = events
    assert naive.ts == datetime(2026, 7, 16, 14, 2, 3, 123000, tzinfo=UTC)
    assert naive.ts_confidence == "inferred"
    assert zulu.ts == datetime(2026, 7, 16, 14, 2, 3, tzinfo=UTC)
    assert zulu.ts_confidence == "exact"
    assert offset.ts == datetime(2026, 7, 16, 12, 2, 3, tzinfo=UTC)
    assert offset.ts_confidence == "exact"
    assert naive.severity == "error"
    assert zulu.severity == "info"
    assert offset.severity == "warn"


def test_format_syslog_year_from_mtime(tmp_path: Path) -> None:
    path = write_log(tmp_path, "sys.log", b"Jul  9 03:14:15 host proc: msg\n")
    set_mtime(path, datetime(2026, 7, 16, tzinfo=UTC))
    events, _ = run_parse(tmp_path, "sys.log")
    assert len(events) == 1
    assert events[0].ts == datetime(2026, 7, 9, 3, 14, 15, tzinfo=UTC)
    assert events[0].ts_confidence == "inferred"
    assert events[0].message == "host proc: msg"


def test_format_syslog_previous_year(tmp_path: Path) -> None:
    # December log read in January: ts would land > mtime + 1 day, so the
    # inferred year steps back one (A3).
    path = write_log(tmp_path, "sys.log", b"Dec 31 23:59:59 host proc: late\n")
    set_mtime(path, datetime(2026, 1, 5, tzinfo=UTC))
    events, _ = run_parse(tmp_path, "sys.log")
    assert events[0].ts == datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert events[0].ts_confidence == "inferred"


def test_format_epoch_seconds_and_millis(tmp_path: Path) -> None:
    write_log(
        tmp_path, "app.log", b"1752674523 seconds msg\n1752674523123 millis msg\n"
    )
    events, _ = run_parse(tmp_path, "app.log")
    assert len(events) == 2
    secs, millis = events
    assert secs.ts == datetime.fromtimestamp(1752674523, tz=UTC)
    assert secs.ts_confidence == "exact"  # epoch is UTC by definition
    assert millis.ts == datetime.fromtimestamp(1752674523.123, tz=UTC)
    assert millis.ts_confidence == "exact"


def test_format_epoch_window_rejects_out_of_range(tmp_path: Path) -> None:
    # 5-digit, 16-digit, and a 10-digit value outside the 2000-2100 window:
    # none may parse as a timestamp — the file is one unknown region.
    write_log(
        tmp_path,
        "app.log",
        b"99999 too short\n9999999999999999 too long\n9999999999 out of window\n",
    )
    events, _ = run_parse(tmp_path, "app.log")
    assert len(events) == 1
    assert events[0].ts is None
    assert events[0].ts_confidence == "missing"


def test_format_iso_greedy_prefix_not_a_timestamp(tmp_path: Path) -> None:
    # fromisoformat would accept bare "20260716" — the anchored regex must not.
    write_log(
        tmp_path,
        "app.log",
        b"2026-07-16T10:00:00Z real event\n20260716 data continuation\n",
    )
    events, _ = run_parse(tmp_path, "app.log")
    assert len(events) == 1
    assert events[0].line_end == 2  # digit-prefixed line joined the event


def test_format_apache_clf(tmp_path: Path) -> None:
    write_log(tmp_path, "access.log", b"[16/Jul/2026:14:02:03 +0200] GET /\n")
    events, _ = run_parse(tmp_path, "access.log")
    assert events[0].ts == datetime(2026, 7, 16, 12, 2, 3, tzinfo=UTC)
    assert events[0].ts_confidence == "exact"


def test_format_all_ts_aware_utc_or_none(tmp_path: Path) -> None:
    # Pitfall 2 enforcement: every parsed ts is timezone-aware UTC or None.
    path = write_log(
        tmp_path,
        "mixed.log",
        b"leading junk line\n"
        b"2026-07-16 14:02:03 naive\n"
        b"Jul  9 03:14:15 host proc: syslog\n"
        b"1752674523 epoch\n"
        b"2026-07-16T14:02:03+02:00 offset\n",
    )
    set_mtime(path, datetime(2026, 7, 16, tzinfo=UTC))
    events, _ = run_parse(tmp_path, "mixed.log")
    assert len(events) == 5
    for e in events:
        assert e.ts is None or (
            e.ts.tzinfo is not None and e.ts.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
        )


# -------------------------------------------------------------- timezone ---


def test_timezone_override_glob_applies(tmp_path: Path) -> None:
    write_log(tmp_path, "node1/app.log", b"2026-07-16 14:02:03 INFO x\n")
    events, stats = run_parse(
        tmp_path, "node1/app.log", tz_overrides={"node1/*": "Europe/Berlin"}
    )
    # Berlin in July is CEST (+02:00): naive 14:02 local -> 12:02 UTC.
    assert events[0].ts == datetime(2026, 7, 16, 12, 2, 3, tzinfo=UTC)
    assert events[0].ts_confidence == "inferred"
    disclosure = [n for n in stats.notes if "Europe/Berlin" in n]
    assert len(disclosure) == 1
    assert "node1/*" in disclosure[0]


def test_timezone_no_override_assumes_utc_with_note(tmp_path: Path) -> None:
    write_log(
        tmp_path,
        "app.log",
        b"2026-07-16 14:02:03 INFO one\n2026-07-16 14:02:04 INFO two\n",
    )
    events, stats = run_parse(tmp_path, "app.log")
    assert events[0].ts == datetime(2026, 7, 16, 14, 2, 3, tzinfo=UTC)
    assert all(e.ts_confidence == "inferred" for e in events)
    utc_notes = [n for n in stats.notes if "assumed UTC" in n]
    assert len(utc_notes) == 1  # one disclosure per file, not per line


def test_timezone_exact_offset_ignores_override(tmp_path: Path) -> None:
    write_log(tmp_path, "node1/app.log", b"2026-07-16T14:02:03+02:00 INFO x\n")
    events, stats = run_parse(
        tmp_path, "node1/app.log", tz_overrides={"node1/*": "America/New_York"}
    )
    # Explicit offset wins over any override: 14:02+02:00 == 12:02 UTC.
    assert events[0].ts == datetime(2026, 7, 16, 12, 2, 3, tzinfo=UTC)
    assert events[0].ts_confidence == "exact"
    assert not any("America/New_York" in n for n in stats.notes)
