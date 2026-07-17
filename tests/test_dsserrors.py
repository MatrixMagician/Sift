"""dsserrors adapter tests: token extraction, MCM grouping + safety caps, node
tagging, rotation-ordered-by-ts, and the criterion-4 mixed-timezone timeline
(selectable via ``pytest -k token/mcm/node/rotation/timezone/coverage/sniff``).

Fixtures live under tests/fixtures/dsserrors/ (plan 05-04 Task 1). The record
layout and SID token shape are the 05-02 "proceed-on-assumed-shapes" defaults.
"""

from datetime import datetime
from pathlib import Path

from sift.adapters.base import ParseStats
from sift.adapters.dsserrors import (
    MAX_EVENT_LINES,
    DsserrorsAdapter,
)
from sift.models import Event

FIXTURES = Path(__file__).parent / "fixtures" / "dsserrors"


def run_parse(
    root: Path,
    relname: str,
    tz_overrides: dict[str, str] | None = None,
) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = DsserrorsAdapter()
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


def _real_ts_events(events: list[Event]) -> list[Event]:
    """Events carrying a real UTC ts, sorted chronologically."""
    return sorted((e for e in events if e.ts is not None), key=lambda e: e.ts)  # type: ignore[arg-type,return-value]


def write(root: Path, relname: str, data: bytes) -> Path:
    path = root / relname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ------------------------------------------------------------------- sniff ---


def test_sniff_dsserrors_head_high() -> None:
    adapter = DsserrorsAdapter()
    assert adapter.sniff(FIXTURES / "node1" / "DSSErrors.log") == 0.8


def test_sniff_plain_text_zero(tmp_path: Path) -> None:
    path = write(tmp_path, "plain.txt", b"just some prose\nno tokens here\n")
    adapter = DsserrorsAdapter()
    assert adapter.sniff(path) == 0.0


# ------------------------------------------------------------------- token ---


def _error_event(events: list[Event]) -> Event:
    return next(e for e in events if e.severity == "error")


def test_token_extraction_error_record() -> None:
    events, _ = run_parse(FIXTURES, "node1/DSSErrors.log")
    err = _error_event(events)
    assert err.component == "ContractManagerImpl"
    assert err.attrs["source_loc"] == "ContractManagerImpl.cpp:1235"
    assert err.attrs["error_code"] == "0xC0000017"
    assert err.attrs["oid"] == "6f3a1b2c-4d5e-6f70-8192-a3b4c5d6e7f8"
    assert err.session == "A1B2C3D4E5F60718"
    assert err.thread == "12346"


def test_token_severity_tags_map_to_six_value_set() -> None:
    events, _ = run_parse(FIXTURES, "node1/DSSErrors.log")
    by_msg = {e.message.split(" [")[0]: e.severity for e in events}
    # Bracketed severity tags -> six-value map.
    assert {e.severity for e in events if e.ts is not None} == {
        "info",
        "warn",
        "error",
        "fatal",
        "debug",
    }
    assert any(v == "debug" for v in by_msg.values())  # [Trace] -> debug


def test_token_no_emitted_severity_outside_check_set() -> None:
    allowed = {"fatal", "error", "warn", "info", "debug", "unknown"}
    for rel in ("node1/DSSErrors.log", "node2/DSSErrors.log"):
        events, _ = run_parse(FIXTURES, rel)
        assert {e.severity for e in events} <= allowed


# --------------------------------------------------------------------- mcm ---


def test_mcm_full_block_is_one_event() -> None:
    events, _ = run_parse(FIXTURES, "node1/DSSErrors.log")
    mcm = [e for e in events if e.component == "MCM"]
    # One full block (closed by End sentinel) + one truncated block at EOF.
    assert len(mcm) == 2
    full = mcm[0]
    assert "Start of Info Dump" in full.raw
    assert "End of Info Dump" in full.raw
    assert "Source=CastorServer" in full.message
    assert "Size=2147483648" in full.message
    assert full.severity == "unknown"  # never fabricated
    assert full.ts is None


def test_mcm_truncated_at_eof_is_one_event() -> None:
    events, _ = run_parse(FIXTURES, "node1/DSSErrors.log")
    truncated = [e for e in events if e.component == "MCM"][-1]
    assert "Start of Info Dump" in truncated.raw
    assert "End of Info Dump" not in truncated.raw
    assert truncated.ts is None


def test_mcm_cap_forces_unknown_continuation(tmp_path: Path) -> None:
    # A never-terminated MCM block: the 256-line cap force-closes it into a
    # severity="unknown" continuation event (bounded memory, T-05-20).
    body = b"***** Start of Info Dump *****\n" + b"filler continuation\n" * 300
    write(tmp_path, "node1/DSSErrors.log", body)
    events, _ = run_parse(tmp_path, "node1/DSSErrors.log")
    assert len(events) == 2
    assert events[0].component == "MCM"
    mcm_lines = events[0].line_end - events[0].line_start + 1
    assert mcm_lines <= MAX_EVENT_LINES
    assert events[1].severity == "unknown"
    assert events[1].ts is None


# -------------------------------------------------------------------- node ---


def test_node_tagging_distinct_per_subdirectory() -> None:
    n1, _ = run_parse(FIXTURES, "node1/DSSErrors.log")
    n2, _ = run_parse(FIXTURES, "node2/DSSErrors.log")
    assert {e.attrs["node"] for e in n1} == {"node1"}
    assert {e.attrs["node"] for e in n2} == {"node2"}


# ---------------------------------------------------------------- rotation ---


def test_rotation_ordered_by_ts_not_filename() -> None:
    # .bak00 (07:00) is chronologically NEWER than .bak01 (06:00) — reversed vs
    # the numeric filename order. Parse each independently, merge, sort by ts.
    bak00, _ = run_parse(FIXTURES, "node1/DSSErrors.bak00")
    bak01, _ = run_parse(FIXTURES, "node1/DSSErrors.bak01")
    markers = ("entry A", "entry B", "entry C", "entry D")

    def marker(e: Event) -> str:
        return next(m for m in markers if m in e.message)

    merged = _real_ts_events([*bak00, *bak01])
    ts_order = [marker(e) for e in merged]
    assert ts_order == ["entry A", "entry B", "entry C", "entry D"]
    # Offset-bearing stamps -> exact, never inferred.
    assert {e.ts_confidence for e in merged} == {"exact"}
    # The ts order is NOT the filename-concatenation order (bak00 then bak01).
    filename_order = [marker(e) for e in [*bak00, *bak01]]
    assert ts_order != filename_order


# ---------------------------------------------------------------- timezone ---


def test_timezone_mixed_tz_timeline_not_causally_inverted() -> None:
    # node1 naive New-York-local, node2 naive London-local. Wall-clock order
    # (node1 10:00 < node2 14:00) is the OPPOSITE of the true UTC order once
    # each node's tz override is applied through the shared base.to_utc.
    n1, _ = run_parse(
        FIXTURES, "node1/DSSErrors.log", {"node1/*": "America/New_York"}
    )
    n2, _ = run_parse(FIXTURES, "node2/DSSErrors.log", {"node2/*": "Europe/London"})
    merged = _real_ts_events([*n1, *n2])
    # node2's 14:00:04 London (=14:00:04 UTC) precedes node1's 10:00:01 New York
    # (=15:00:01 UTC): causality is preserved, not inverted.
    assert merged[0].attrs["node"] == "node2"
    assert merged[1].attrs["node"] == "node2"
    assert merged[2].attrs["node"] == "node1"
    # Naive stamps normalised through the tz override -> inferred confidence.
    assert {e.ts_confidence for e in merged} == {"inferred"}


def test_timezone_naive_inferred_offset_exact() -> None:
    naive, _ = run_parse(
        FIXTURES, "node1/DSSErrors.log", {"node1/*": "America/New_York"}
    )
    offset, _ = run_parse(FIXTURES, "node1/DSSErrors.bak00")
    assert {e.ts_confidence for e in naive if e.ts is not None} == {"inferred"}
    assert {e.ts_confidence for e in offset} == {"exact"}
    # First node1 record: 2026-01-15 10:00:01.100 New York = 15:00:01.100 UTC.
    first = _real_ts_events(naive)[0]
    assert first.ts == datetime.fromisoformat("2026-01-15T15:00:01.100+00:00")


# ---------------------------------------------------------------- coverage ---


def test_coverage_bounded_non_vacuous() -> None:
    events, stats = run_parse(FIXTURES, "node1/DSSErrors.log")
    assert 0.95 <= stats.coverage < 1.0
    assert stats.unknown_fallback_bytes > 0  # the leading "-- corrupt --" line
    assert_span_partition(events, stats.total_bytes)


def test_coverage_unparseable_line_is_unknown_ts_none() -> None:
    events, _ = run_parse(FIXTURES, "node1/DSSErrors.log")
    corrupt = events[0]
    assert corrupt.severity == "unknown"
    assert corrupt.ts is None
    assert "corrupt" in corrupt.message
