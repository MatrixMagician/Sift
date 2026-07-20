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


def assert_span_partition(
    events: list[Event], total_bytes: int, start: int = 0
) -> None:
    """Event byte spans must partition the file: contiguous from ``start``,
    non-overlapping, reaching the total decompressed byte count.

    ``start`` is non-zero for PDH-CSV because the header line is metadata, not
    an Event (D-01), so its bytes precede the first span. Every byte after it
    is still accounted for — nothing disappears silently.
    """
    pos = start
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


# Synthetic two-counter PDH file: the real artefact has no malformed cells
# (D-17), so every fallback case below is authored inline where the defect
# under test is visible in the test body rather than hidden in a fixture.
SYN_HEADER = (
    b'"(PDH-CSV 4.0) (Eastern Standard Time)(300)",'
    b'"\\\\host1\\MSTR Server\\Working set cache RAM usage(MB)",'
    b'"\\\\host1\\MSTR Server\\Total MCM Denial"\n'
)
SYN_NO_ZONE = b'"(PDH-CSV 4.0)",' + SYN_HEADER.split(b",", 1)[1]
GOOD_ROW = b'"04/07/2026 12:39:39.397","266042","1"\n'
CACHE = "Working set cache RAM usage(MB)"


def syn(root: Path, *rows: bytes, header: bytes = SYN_HEADER) -> tuple[Path, int]:
    """Write a synthetic PDH file; return (path, header byte length)."""
    return write(root, "syn.csv", header + b"".join(rows)), len(header)


def run_syn(
    root: Path, *rows: bytes, header: bytes = SYN_HEADER
) -> tuple[list[Event], ParseStats, int]:
    _, header_bytes = syn(root, *rows, header=header)
    events, stats = run_parse(root, "syn.csv")
    assert_span_partition(events, stats.total_bytes, start=header_bytes)
    return events, stats, header_bytes


# --------------------------------------------------- unknown-row fallbacks ---


def test_blank_cell_unknown_fallback(tmp_path: Path) -> None:
    """A blank counter cell degrades the row, it does not drop it (D-14)."""
    row = b'"04/07/2026 12:39:39.397","","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    assert events[0].attrs["unparsed_columns"] == CACHE
    assert events[0].raw == row.decode().rstrip("\n")
    # A bad cell never costs the row its timestamp.
    assert events[0].ts is not None


def test_non_numeric_cell_unknown_fallback(tmp_path: Path) -> None:
    """A non-numeric counter cell takes the same path as a blank one (D-14)."""
    row = b'"04/07/2026 12:39:39.397","N/A","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    assert events[0].attrs["unparsed_columns"] == CACHE
    # The float() attempt is a validity probe only: attrs keep the raw string.
    assert events[0].attrs[CACHE] == "N/A"


def test_bad_timestamp_survives(tmp_path: Path) -> None:
    """An unparseable stamp yields ts None / 'missing', never an exception (D-15)."""
    row = b'"not a timestamp","266042","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    assert events[0].ts is None
    assert events[0].ts_confidence == "missing"
    assert events[0].raw == row.decode().rstrip("\n")
    # Columns that did parse still populate attrs.
    assert events[0].attrs[CACHE] == "266042"


def test_column_drift_unknown(tmp_path: Path) -> None:
    """Column drift is disclosed, not realigned — and keeps a good ts (D-16)."""
    row = b'"04/07/2026 12:39:39.397","266042"\n'
    events, stats, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    # D-16 asks for the unknown severity, not for the loss of a recoverable ts:
    # Phase 13 still needs somewhere to place this evidence on the timeline.
    assert events[0].ts == datetime(2026, 4, 7, 12, 39, 39, 397000, tzinfo=UTC)
    assert any("expected 3" in note and "2" in note for note in stats.notes)


def test_embedded_newline_two_unknown_events(tmp_path: Path) -> None:
    """A quoted embedded newline splits into two unknown rows, offsets intact.

    Reassembly is deliberately NOT implemented: it would require buffering
    across byte_lines and so compromise the byte-offset contract that
    event_id depends on, for a case the PDH writer cannot actually emit.
    """
    row = b'"04/07/2026 12:39:39.397","2660\n42","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 2
    assert [e.severity for e in events] == ["unknown", "unknown"]


def test_header_without_bias_still_parses(tmp_path: Path) -> None:
    """A header declaring no zone/bias omits the attrs rather than inventing them."""
    events, stats, _ = run_syn(tmp_path, GOOD_ROW, header=SYN_NO_ZONE)
    assert len(events) == 1
    assert events[0].severity == "info"
    assert events[0].ts_confidence == "inferred"
    assert "tz_name" not in events[0].attrs
    assert "tz_offset_min" not in events[0].attrs
    assert any("no timezone" in note for note in stats.notes)


def test_parse_coverage(tmp_path: Path) -> None:
    """Unknown-row bytes reach ParseStats, so coverage reflects the loss (PERF-02)."""
    bad = b'"04/07/2026 12:39:40.397","","1"\n'
    events, stats, _ = run_syn(tmp_path, GOOD_ROW, GOOD_ROW, bad)
    assert len(events) == 3
    assert stats.unknown_fallback_bytes == len(bad)
    assert stats.coverage < 1.0


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
    header_bytes = len((FIXTURES / SLICE).read_bytes().split(b"\n", 1)[0]) + 1
    assert_span_partition(events, stats.total_bytes, start=header_bytes)
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
