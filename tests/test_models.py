"""Contract tests: canonical event_id, frozen Event, decompression seam."""

import dataclasses
import gzip
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import zstandard

from sift.adapters.base import ParseStats, open_bytes, read_head
from sift.models import Event, event_id


def test_event_id_golden_value() -> None:
    # FROZEN contract — this exact value is pinned forever (research-verified).
    assert event_id("app.log", 12345) == "f7fdcb4b3de90265"


def test_event_id_shape_is_16_lowercase_hex() -> None:
    for source_file, offset in [("a", 0), ("path/to/file.log", 999_999), ("x.gz", 1)]:
        assert re.fullmatch(r"[0-9a-f]{16}", event_id(source_file, offset))


def test_event_id_nul_separator_disambiguates() -> None:
    assert event_id("a1", 1) != event_id("a", 11)


def _make_event() -> Event:
    return Event(
        event_id=event_id("app.log", 0),
        case_id="demo",
        ts=datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC),
        ts_confidence="exact",
        source="genericlog",
        source_file="app.log",
        line_start=1,
        line_end=1,
        severity="info",
        component=None,
        thread=None,
        session=None,
        message="service started",
        attrs={},
        raw="2026-07-16T10:00:00+00:00 INFO service started",
    )


def test_event_is_frozen() -> None:
    e = _make_event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.severity = "error"  # pyright: ignore[reportAttributeAccessIssue]


def test_open_bytes_gzip_matches_plain(tmp_path: Path) -> None:
    payload = b"2026-07-16T10:00:00Z INFO one\nplain continuation\n"
    plain = tmp_path / "plain.log"
    plain.write_bytes(payload)
    gz = tmp_path / "same.log.gz"
    gz.write_bytes(gzip.compress(payload))
    with open_bytes(plain) as a, open_bytes(gz) as b:
        assert a.read() == b.read() == payload


def test_open_bytes_zstd_reads_across_frames(tmp_path: Path) -> None:
    part1 = b"frame one\n"
    part2 = b"frame two\n"
    cctx = zstandard.ZstdCompressor()
    zst = tmp_path / "log.zst"
    zst.write_bytes(cctx.compress(part1) + cctx.compress(part2))
    with open_bytes(zst) as stream:
        assert stream.read() == part1 + part2


def test_read_head_returns_decompressed_content(tmp_path: Path) -> None:
    payload = b"2026-07-16T10:00:00Z INFO hello\n"
    gz = tmp_path / "head.log.gz"
    gz.write_bytes(gzip.compress(payload))
    assert read_head(gz) == payload


def test_parse_stats_coverage_empty_file_is_full() -> None:
    assert ParseStats(path="empty.log").coverage == 1.0


def test_parse_stats_coverage_formula() -> None:
    stats = ParseStats(path="x.log", total_bytes=100, unknown_fallback_bytes=25)
    assert stats.coverage == 0.75
