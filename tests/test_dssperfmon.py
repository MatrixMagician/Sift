"""dssperfmon adapter tests: PDH-CSV sniff, one-event-per-sample-row parsing,
deterministic byte-offset event ids, and the ADR-0012 recorded-not-applied
timezone rule (selectable via ``pytest -k sniff/row/id/timezone/coverage``).

Fixtures live under tests/fixtures/dssperfmon/. ``hartford_deny_slice.csv`` is
a byte-verbatim cut of a real DSSPerformanceMonitor artefact (header + first 10
and last 10 samples); the real file contains no blank or non-numeric cells, so
malformed cases are authored inline via ``write`` rather than checked in (D-17).
"""

from datetime import UTC, datetime
from pathlib import Path

from sift.adapters.base import ParseStats
from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.models import Event, event_id

FIXTURES = Path(__file__).parent / "fixtures" / "dssperfmon"

SLICE = "hartford_deny_slice.csv"
HOST = "env-325602laio1use1"


def run_parse(
    root: Path,
    relname: str,
    tz_overrides: dict[str, str] | None = None,
) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = DssperfmonAdapter()
    adapter.input_root = root
    if tz_overrides:
        adapter.tz_overrides = tz_overrides
    events = list(adapter.parse(root / relname, "case1"))
    assert adapter.last_stats is not None
    return events, adapter.last_stats


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


def write(root: Path, relname: str, data: bytes) -> Path:
    path = root / relname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ------------------------------------------------------------------- sniff ---


def test_sniff_pdh_header() -> None:
    adapter = DssperfmonAdapter()
    assert adapter.sniff(FIXTURES / SLICE) == 0.95


def test_sniff_plain_text_zero(tmp_path: Path) -> None:
    path = write(tmp_path, "plain.txt", b"just some prose\nno counters here\n")
    adapter = DssperfmonAdapter()
    assert adapter.sniff(path) == 0.0


# --------------------------------------------------------------------- row ---


def test_one_event_per_sample_row() -> None:
    events, stats = run_parse(FIXTURES, SLICE)
    # The PDH header line is not an Event; every sample row is (D-01).
    assert len(events) == 20
    assert stats.event_count == 20
    for i, e in enumerate(events):
        # Never downsampled, never severity-inferred from counter magnitude.
        assert e.severity == "info"
        assert e.component == HOST
        assert e.thread is None
        assert e.session is None
        assert e.line_start == e.line_end
        assert e.line_start == i + 2  # header is line 1
        assert e.source == "dssperfmon"
        assert e.source_file == SLICE
        assert all(isinstance(v, str) for v in e.attrs.values())


def test_counter_attrs_and_message() -> None:
    events, _ = run_parse(FIXTURES, SLICE)
    first = events[0]
    assert first.attrs["host"] == HOST
    assert first.attrs["pdh_version"] == "4.0"
    # Short counter names are the final backslash segment, unit included (D-02).
    assert "Working set cache RAM usage(MB)" in first.attrs
    assert "Total MCM Denial" in first.attrs
    # Values stay unconverted strings — numeric interpretation is Phase 13's job.
    last = events[-1]
    assert last.attrs["Working set cache RAM usage(MB)"] == "266042"
    assert "Working set cache RAM usage(MB)=266042" in last.message
    assert last.raw.startswith('"04/07/2026 12:39:39.397"')


def test_span_partition_and_coverage() -> None:
    events, stats = run_parse(FIXTURES, SLICE)
    assert stats.total_bytes == (FIXTURES / SLICE).stat().st_size
    assert_span_partition(events, stats.total_bytes)
    assert stats.coverage == 1.0


# ---------------------------------------------------------------------- id ---


def test_event_ids_stable_across_reparse() -> None:
    first, _ = run_parse(FIXTURES, SLICE)
    second, _ = run_parse(FIXTURES, SLICE)
    assert [e.event_id for e in first] == [e.event_id for e in second]
    # Ids are the canonical models.event_id over the byte offset, not reinvented.
    assert first[0].event_id == event_id(SLICE, int(first[0].attrs["byte_offset"]))


# ---------------------------------------------------------------- timezone ---


def test_timestamp_utc_and_confidence() -> None:
    """ADR 0012: the naive wall clock is stamped UTC verbatim — no bias shift."""
    events, _ = run_parse(FIXTURES, SLICE)
    last = events[-1]
    assert last.ts == datetime(2026, 4, 7, 12, 39, 39, 397000, tzinfo=UTC)
    assert last.ts_confidence == "inferred"


def test_tz_override_applies() -> None:
    """A --tz glob override reaches base.tz_override_for -> base.to_utc."""
    plain, _ = run_parse(FIXTURES, SLICE)
    shifted, _ = run_parse(FIXTURES, SLICE, {"*": "America/New_York"})
    assert plain[-1].ts != shifted[-1].ts
    # April 2026 is EDT (UTC-4), so the wall clock moves forward four hours.
    assert shifted[-1].ts == datetime(2026, 4, 7, 16, 39, 39, 397000, tzinfo=UTC)


def test_header_zone_recorded_not_applied() -> None:
    events, stats = run_parse(FIXTURES, SLICE)
    for e in events:
        assert e.attrs["tz_name"] == "Eastern Standard Time"
        assert e.attrs["tz_offset_min"] == "300"
    # The declared bias is disclosed once per file, never used in arithmetic.
    assert any("ADR 0012" in note for note in stats.notes)
