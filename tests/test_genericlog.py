"""genericlog adapter tests: format, timezone, multiline, coverage, encoding,
compressed groups (selectable via ``pytest -k <group>``).

Fixture logs are built with local helpers — tests/conftest.py is owned by
plan 01-01 and must not grow fixtures for this module.
"""

import gzip
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import zstandard

from sift.adapters.base import ParseStats
from sift.adapters.genericlog import (
    MAX_EVENT_BYTES,
    MAX_EVENT_LINES,
    GenericLogAdapter,
)
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


def assert_span_partition(events: list[Event], total_bytes: int) -> None:
    """Event byte spans must partition the file: contiguous from 0,
    non-overlapping, summing to the total decompressed byte count."""
    pos = 0
    for e in events:
        assert int(e.attrs["byte_offset"]) == pos, (
            f"gap/overlap at {e.event_id}: span starts at "
            f"{e.attrs['byte_offset']}, expected {pos}"
        )
        pos += int(e.attrs["byte_len"])
    assert pos == total_bytes


# Two-event ASCII log reused across encoding variants.
BASE_LOG = "2026-07-16T10:00:00Z INFO alpha\n2026-07-16T10:00:01Z ERROR beta\n"

ENCODED_FIXTURES: dict[str, bytes] = {
    "utf-8": BASE_LOG.encode("utf-8"),
    "utf-8-sig": BASE_LOG.encode("utf-8-sig"),
    "utf-16-le-bom": b"\xff\xfe" + BASE_LOG.encode("utf-16-le"),
    "utf-16-be-bom": b"\xfe\xff" + BASE_LOG.encode("utf-16-be"),
    "cp1252": "2026-07-16T10:00:00Z INFO caf\xe9\n".encode("cp1252"),
    "invalid-bytes": b"2026-07-16T10:00:00Z INFO bad \x81\xffx\n",
    "crlf": BASE_LOG.replace("\n", "\r\n").encode("utf-8"),
}


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


# ------------------------------------------------------------- multiline ---


def test_multiline_stack_trace_is_one_event(tmp_path: Path) -> None:
    trace = "".join(
        f"\tat com.example.Worker.run(Worker.java:{n})\n" for n in range(11)
    )
    write_log(
        tmp_path,
        "app.log",
        ("2026-07-16T10:00:00Z ERROR boom\n" + trace).encode("utf-8"),
    )
    events, stats = run_parse(tmp_path, "app.log")
    assert len(events) == 1
    assert events[0].line_end - events[0].line_start == 11
    assert "com.example.Worker" in events[0].message
    assert stats.coverage == 1.0  # continuation lines count as covered
    assert_span_partition(events, stats.total_bytes)


def test_multiline_cap_256_lines_splits(tmp_path: Path) -> None:
    body = "".join(f"  continuation {n}\n" for n in range(299))
    write_log(
        tmp_path,
        "app.log",
        ("2026-07-16T10:00:00Z ERROR start\n" + body).encode("utf-8"),
    )
    events, stats = run_parse(tmp_path, "app.log")
    assert len(events) == 2
    first, spill = events
    assert (first.line_start, first.line_end) == (1, MAX_EVENT_LINES)
    assert (spill.line_start, spill.line_end) == (MAX_EVENT_LINES + 1, 300)
    assert spill.ts is None
    assert spill.ts_confidence == "missing"
    assert spill.severity == "unknown"
    assert_span_partition(events, stats.total_bytes)


def test_multiline_cap_64kb_splits(tmp_path: Path) -> None:
    # 70 continuation lines of 1 KiB each: byte cap trips before the line cap.
    line = "x" * 1023 + "\n"
    write_log(
        tmp_path,
        "app.log",
        ("2026-07-16T10:00:00Z ERROR big\n" + line * 70).encode("utf-8"),
    )
    events, stats = run_parse(tmp_path, "app.log")
    assert len(events) == 2
    assert int(events[0].attrs["byte_len"]) <= MAX_EVENT_BYTES
    assert events[1].ts is None
    assert events[1].severity == "unknown"
    assert_span_partition(events, stats.total_bytes)


# -------------------------------------------------------------- coverage ---


def test_coverage_leading_unknown_region_hand_computed(tmp_path: Path) -> None:
    junk = b"no timestamp here\nstill nothing\n"
    parsed = b"2026-07-16T10:00:00Z INFO fine\n"
    write_log(tmp_path, "app.log", junk + parsed)
    events, stats = run_parse(tmp_path, "app.log")
    assert len(events) == 2
    assert events[0].ts is None
    assert events[0].severity == "unknown"
    total = len(junk) + len(parsed)
    assert stats.total_bytes == total
    assert stats.unknown_fallback_bytes == len(junk)
    assert stats.coverage == 1.0 - len(junk) / total
    assert_span_partition(events, stats.total_bytes)


def test_coverage_empty_file(tmp_path: Path) -> None:
    write_log(tmp_path, "empty.log", b"")
    events, stats = run_parse(tmp_path, "empty.log")
    assert events == []
    assert stats.total_bytes == 0
    assert stats.coverage == 1.0


def test_coverage_fully_parsed_file_is_one(tmp_path: Path) -> None:
    write_log(tmp_path, "app.log", ENCODED_FIXTURES["utf-8"])
    _, stats = run_parse(tmp_path, "app.log")
    assert stats.coverage == 1.0


@pytest.mark.parametrize("name", sorted(ENCODED_FIXTURES))
def test_coverage_span_partition_invariant_all_encodings(
    tmp_path: Path, name: str
) -> None:
    data = ENCODED_FIXTURES[name]
    write_log(tmp_path, "app.log", data)
    events, stats = run_parse(tmp_path, "app.log")
    assert stats.total_bytes == len(data)
    assert_span_partition(events, stats.total_bytes)


# -------------------------------------------------------------- encoding ---


def test_encoding_utf16le_bom_offsets_differ_messages_match(
    tmp_path: Path,
) -> None:
    write_log(tmp_path, "u8.log", ENCODED_FIXTURES["utf-8"])
    write_log(tmp_path, "u16.log", ENCODED_FIXTURES["utf-16-le-bom"])
    u8_events, _ = run_parse(tmp_path, "u8.log")
    u16_events, _ = run_parse(tmp_path, "u16.log")
    assert [e.message for e in u16_events] == [e.message for e in u8_events]
    assert [e.line_start for e in u16_events] == [e.line_start for e in u8_events]
    # ASCII content: 2-byte units plus the 2-byte BOM shift every offset.
    assert int(u16_events[0].attrs["byte_offset"]) == 0  # BOM in first span
    assert int(u16_events[1].attrs["byte_offset"]) == (
        2 * int(u8_events[1].attrs["byte_offset"]) + 2
    )


def test_encoding_utf16le_fake_newline_across_char_boundary_not_split(
    tmp_path: Path,
) -> None:
    """WR-07: a ``0A 00`` byte pair straddling two UTF-16-LE characters
    (U+0A41 then U+0100 encodes ``... 41 0A 00 01 ...``) is NOT a newline —
    matching it would misalign every subsequent line of the file."""
    text = (
        "2026-07-16T10:00:00Z INFO a\u0a41\u0100b\n"
        "2026-07-16T10:00:01Z ERROR beta\n"
    )
    data = b"\xff\xfe" + text.encode("utf-16-le")
    write_log(tmp_path, "u16-fake-nl.log", data)
    events, stats = run_parse(tmp_path, "u16-fake-nl.log")
    assert len(events) == 2
    assert events[0].message.endswith("a\u0a41\u0100b")
    assert events[1].message.endswith("beta")
    assert events[1].ts == datetime(2026, 7, 16, 10, 0, 1, tzinfo=UTC)
    assert_span_partition(events, stats.total_bytes)


def test_encoding_utf16be_bom_parses(tmp_path: Path) -> None:
    write_log(tmp_path, "u8.log", ENCODED_FIXTURES["utf-8"])
    write_log(tmp_path, "u16be.log", ENCODED_FIXTURES["utf-16-be-bom"])
    u8_events, _ = run_parse(tmp_path, "u8.log")
    be_events, be_stats = run_parse(tmp_path, "u16be.log")
    assert [e.message for e in be_events] == [e.message for e in u8_events]
    assert [e.ts for e in be_events] == [e.ts for e in u8_events]
    assert_span_partition(be_events, be_stats.total_bytes)


def test_encoding_utf8_sig_bom_stripped_from_text(tmp_path: Path) -> None:
    write_log(tmp_path, "sig.log", ENCODED_FIXTURES["utf-8-sig"])
    events, stats = run_parse(tmp_path, "sig.log")
    assert len(events) == 2
    assert "﻿" not in events[0].message
    assert events[0].ts == datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC)
    assert stats.total_bytes == len(ENCODED_FIXTURES["utf-8-sig"])


def test_encoding_cp1252_fallback(tmp_path: Path) -> None:
    write_log(tmp_path, "cp.log", ENCODED_FIXTURES["cp1252"])
    events, stats = run_parse(tmp_path, "cp.log")
    assert len(events) == 1
    assert "caf\xe9" in events[0].message  # 0xE9 decoded as é via cp1252
    assert_span_partition(events, stats.total_bytes)


def test_encoding_invalid_bytes_replaced_after_offsets_fixed(
    tmp_path: Path,
) -> None:
    data = ENCODED_FIXTURES["invalid-bytes"]
    write_log(tmp_path, "bad.log", data)
    events, stats = run_parse(tmp_path, "bad.log")
    assert len(events) == 1
    assert events[0].ts == datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC)
    assert "�" in events[0].message  # 0x81 has no cp1252 mapping
    assert stats.total_bytes == len(data)  # replacement never shifts offsets
    assert_span_partition(events, stats.total_bytes)


def test_encoding_crlf_bytes_counted_text_stripped(tmp_path: Path) -> None:
    data = ENCODED_FIXTURES["crlf"]
    write_log(tmp_path, "crlf.log", data)
    events, stats = run_parse(tmp_path, "crlf.log")
    assert len(events) == 2
    assert all("\r" not in e.message for e in events)
    assert stats.total_bytes == len(data)
    assert_span_partition(events, stats.total_bytes)


# ------------------------------------------------------------ compressed ---

# Three events, one with a continuation line — enough structure to expose a
# truncated decompression (Pitfall 3: a lost frame would drop events).
PLAIN_CONTENT = (
    b"2026-07-16T10:00:00Z INFO service started\n"
    b"2026-07-16T10:00:01Z ERROR pool exhausted\n"
    b"    at pool.acquire (worker 7)\n"
    b"2026-07-16T10:00:02Z WARN retrying\n"
)


def fingerprint(events: list[Event]) -> list[tuple[int, int, str]]:
    """Per-event (byte_offset, line_start, message) on the decompressed stream."""
    return [
        (int(e.attrs["byte_offset"]), e.line_start, e.message) for e in events
    ]


def parse_variant(tmp_path: Path, relname: str, data: bytes) -> tuple[
    list[Event], ParseStats
]:
    write_log(tmp_path, relname, data)
    return run_parse(tmp_path, relname)


def test_compressed_gzip_matches_plain(tmp_path: Path) -> None:
    plain, plain_stats = parse_variant(tmp_path, "app.log", PLAIN_CONTENT)
    gz, gz_stats = parse_variant(tmp_path, "app.log.gz", gzip.compress(PLAIN_CONTENT))
    assert fingerprint(gz) == fingerprint(plain)
    assert gz_stats.coverage == plain_stats.coverage
    assert gz_stats.total_bytes == plain_stats.total_bytes  # decompressed bytes
    # Only source_file (and therefore event_id) differs (D-07).
    assert [e.event_id for e in gz] != [e.event_id for e in plain]
    assert all(e.source_file == "app.log.gz" for e in gz)


def test_compressed_gzip_multi_member_matches_plain(tmp_path: Path) -> None:
    # Two concatenated gzip members, split mid-line: stdlib gzip must read
    # across members transparently.
    part1, part2 = PLAIN_CONTENT[:50], PLAIN_CONTENT[50:]
    data = gzip.compress(part1) + gzip.compress(part2)
    plain, _ = parse_variant(tmp_path, "app.log", PLAIN_CONTENT)
    multi, stats = parse_variant(tmp_path, "app-multi.gz", data)
    assert fingerprint(multi) == fingerprint(plain)
    assert stats.total_bytes == len(PLAIN_CONTENT)
    assert_span_partition(multi, stats.total_bytes)


def test_compressed_zstd_matches_plain(tmp_path: Path) -> None:
    data = zstandard.ZstdCompressor().compress(PLAIN_CONTENT)
    plain, plain_stats = parse_variant(tmp_path, "app.log", PLAIN_CONTENT)
    zst, zst_stats = parse_variant(tmp_path, "app.log.zst", data)
    assert fingerprint(zst) == fingerprint(plain)
    assert zst_stats.coverage == plain_stats.coverage
    assert zst_stats.total_bytes == plain_stats.total_bytes


def test_compressed_zstd_multi_frame_matches_plain(tmp_path: Path) -> None:
    # Two concatenated zstd frames: without read_across_frames=True the
    # second frame's events would vanish silently (Pitfall 3).
    cctx = zstandard.ZstdCompressor()
    part1, part2 = PLAIN_CONTENT[:50], PLAIN_CONTENT[50:]
    data = cctx.compress(part1) + cctx.compress(part2)
    plain, _ = parse_variant(tmp_path, "app.log", PLAIN_CONTENT)
    multi, stats = parse_variant(tmp_path, "app-multi.zst", data)
    assert fingerprint(multi) == fingerprint(plain)
    assert len(multi) == 3
    assert stats.total_bytes == len(PLAIN_CONTENT)
    assert_span_partition(multi, stats.total_bytes)


def test_compressed_magic_bytes_not_extension(tmp_path: Path) -> None:
    # gzip content under a plain .log name still decompresses (D-07).
    plain, _ = parse_variant(tmp_path, "app.log", PLAIN_CONTENT)
    disguised, _ = parse_variant(tmp_path, "plain.log", gzip.compress(PLAIN_CONTENT))
    assert fingerprint(disguised) == fingerprint(plain)


def test_compressed_corrupt_zstd_raises(tmp_path: Path) -> None:
    # Valid zstd magic followed by garbage: parse must raise loudly, never
    # return a partial silent result (surfaced by the CLI per-file error path).
    data = b"\x28\xb5\x2f\xfd" + b"this is not a valid zstd frame body"
    path = write_log(tmp_path, "corrupt.zst", data)
    adapter = GenericLogAdapter()
    adapter.input_root = tmp_path
    with pytest.raises((zstandard.ZstdError, ValueError)):
        list(adapter.parse(path, "case1"))


def test_compressed_sniff_on_decompressed_content(tmp_path: Path) -> None:
    # Pitfall 4: a gzipped timestamped log must sniff as genericlog.
    path = write_log(tmp_path, "app.log.gz", gzip.compress(PLAIN_CONTENT))
    adapter = GenericLogAdapter()
    assert adapter.sniff(path) == 0.1
