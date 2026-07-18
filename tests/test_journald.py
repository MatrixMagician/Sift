"""journald adapter tests: PRIORITY→severity mapping, µs-epoch timestamps,
field mapping, _field_to_str value normalisation, malformed-line accounting,
bounded coverage, span partition, gzip determinism, and sniff.

Fixtures are built with local helpers (some handcrafted on disk under
tests/fixtures/journald/, some inline) — tests/conftest.py is owned by plan
01-01 and must not grow fixtures for this module.
"""

import gzip
from datetime import UTC, datetime
from pathlib import Path

from sift.adapters.base import ParseStats
from sift.adapters.journald import (
    JournaldAdapter,
    _field_to_str,  # pyright: ignore[reportPrivateUsage] — normaliser under test
)
from sift.models import Event

FIXTURES = Path(__file__).parent / "fixtures" / "journald"


def write(root: Path, relname: str, data: bytes) -> Path:
    """Write fixture bytes at root/relname, creating parent directories."""
    path = root / relname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def run_parse(root: Path, relname: str) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = JournaldAdapter()
    adapter.input_root = root
    events = list(adapter.parse(root / relname, "case1"))
    assert adapter.last_stats is not None
    return events, adapter.last_stats


def parse_lines(root: Path, lines: list[str]) -> tuple[list[Event], ParseStats]:
    """Write JSONL lines to root/data.json and parse."""
    data = ("\n".join(lines) + "\n").encode("utf-8")
    write(root, "data.json", data)
    return run_parse(root, "data.json")


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


# --- PRIORITY → severity -----------------------------------------------------


def test_priority_full_range_maps_to_six_value_set(tmp_path: Path) -> None:
    lines = [
        f'{{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"{p}",'
        f'"MESSAGE":"m{p}"}}'
        for p in range(8)
    ]
    events, _ = parse_lines(tmp_path, lines)
    got = [e.severity for e in events]
    assert got == [
        "fatal",  # 0 emerg
        "fatal",  # 1 alert
        "fatal",  # 2 crit
        "error",  # 3 err
        "warn",  # 4 warning
        "info",  # 5 notice
        "info",  # 6 info
        "debug",  # 7 debug
    ]


def test_priority_invalid_or_missing_maps_to_unknown(tmp_path: Path) -> None:
    lines = [
        '{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"9","MESSAGE":"a"}',
        '{"__REALTIME_TIMESTAMP":"1784160001000000","PRIORITY":"x","MESSAGE":"b"}',
        '{"__REALTIME_TIMESTAMP":"1784160002000000","MESSAGE":"c"}',
    ]
    events, _ = parse_lines(tmp_path, lines)
    assert [e.severity for e in events] == ["unknown", "unknown", "unknown"]


def test_priority_array_takes_most_severe(tmp_path: Path) -> None:
    # A repeated PRIORITY field (merged journals) is delivered as a JSON array;
    # take the most-severe (lowest-numbered) entry per journald semantics
    # rather than dropping the severity to unknown (IN-02).
    lines = [
        '{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":["6","3"],'
        '"MESSAGE":"a"}',
        '{"__REALTIME_TIMESTAMP":"1784160001000000","PRIORITY":["4","6"],'
        '"MESSAGE":"b"}',
    ]
    events, _ = parse_lines(tmp_path, lines)
    # 3=err (most severe of 6,3) → error; 4=warning (most severe of 4,6) → warn.
    assert [e.severity for e in events] == ["error", "warn"]


def test_no_emitted_severity_outside_check_set(tmp_path: Path) -> None:
    allowed = {"fatal", "error", "warn", "info", "debug", "unknown"}
    events, _ = run_parse_fixture(tmp_path, "basic.json")
    assert {e.severity for e in events} <= allowed


# --- timestamps --------------------------------------------------------------


def test_realtime_timestamp_becomes_utc_exact(tmp_path: Path) -> None:
    # 1784160000000000 µs = 1784160000 s since epoch.
    events, _ = parse_lines(
        tmp_path,
        ['{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"6","MESSAGE":"m"}'],
    )
    (e,) = events
    assert e.ts == datetime.fromtimestamp(1784160000, tz=UTC)
    assert e.ts is not None and e.ts.tzinfo is not None
    assert e.ts_confidence == "exact"


def test_missing_timestamp_is_covered_not_fallback(tmp_path: Path) -> None:
    events, stats = parse_lines(
        tmp_path,
        ['{"PRIORITY":"6","MESSAGE":"no timestamp here"}'],
    )
    (e,) = events
    assert e.ts is None
    assert e.ts_confidence == "missing"
    # Its bytes parsed successfully — covered, never unknown_fallback.
    assert stats.unknown_fallback_bytes == 0
    assert stats.coverage == 1.0


# --- field mapping -----------------------------------------------------------


def test_field_mapping(tmp_path: Path) -> None:
    line = (
        '{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"3",'
        '"MESSAGE":"boom","_SYSTEMD_UNIT":"nginx.service","_PID":"4242",'
        '"_COMM":"nginx","_SYSTEMD_INVOCATION_ID":"deadbeef"}'
    )
    events, _ = parse_lines(tmp_path, [line])
    (e,) = events
    assert e.component == "nginx.service"
    assert e.session == "deadbeef"
    assert e.attrs["pid"] == "4242"
    assert e.attrs["comm"] == "nginx"
    assert e.message == "boom"
    assert e.source == "journald"


def test_absent_unit_is_none(tmp_path: Path) -> None:
    events, _ = parse_lines(
        tmp_path,
        ['{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"4","MESSAGE":"k"}'],
    )
    (e,) = events
    assert e.component is None
    assert e.session is None
    assert "pid" not in e.attrs


# --- _field_to_str -----------------------------------------------------------


def test_field_to_str_string_and_none_and_int() -> None:
    assert _field_to_str("hello") == "hello"
    assert _field_to_str(None) is None
    assert _field_to_str(4242) == "4242"


def test_field_to_str_int_array_with_nul_decodes() -> None:
    # "Hi\x00World" — the embedded NUL must not become a Python list repr.
    out = _field_to_str([72, 105, 0, 87, 111, 114, 108, 100])
    assert out == "Hi\x00World"
    assert "[" not in out


def test_field_to_str_value_array_joins() -> None:
    assert _field_to_str(["one", "two"]) == "one\ntwo"


def test_message_nul_from_fixture(tmp_path: Path) -> None:
    events, _ = run_parse_fixture(tmp_path, "field_types.json")
    messages = [e.message for e in events]
    # int-array line decodes to text, never "[72, 105, ...]".
    assert any("Hi\x00World" == m for m in messages)
    assert not any(m.startswith("[") for m in messages)
    # value-array joined with newlines.
    assert "first repeated line\nsecond repeated line" in messages
    # null MESSAGE → empty string, never the literal "None".
    assert "" in messages
    assert "None" not in messages


# --- malformed / coverage ----------------------------------------------------


def test_malformed_line_becomes_unknown_and_byte_accounted(tmp_path: Path) -> None:
    lines = [
        '{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"6","MESSAGE":"ok"}',
        "this is not json {",
    ]
    events, stats = parse_lines(tmp_path, lines)
    assert len(events) == 2
    bad = events[1]
    assert bad.severity == "unknown"
    assert bad.ts is None
    assert stats.unknown_fallback_bytes == len(b"this is not json {\n")
    assert 0.0 < stats.coverage < 1.0


def test_non_object_json_line_is_unknown(tmp_path: Path) -> None:
    # A valid JSON value that is not an object (a bare number) → unknown.
    events, stats = parse_lines(tmp_path, ["12345"])
    (e,) = events
    assert e.severity == "unknown"
    assert stats.unknown_fallback_bytes == len(b"12345\n")


def test_basic_fixture_coverage_bounded(tmp_path: Path) -> None:
    events, stats = run_parse_fixture(tmp_path, "basic.json")
    pct = stats.coverage * 100
    assert 95.0 <= pct < 100.0, f"coverage {pct} outside bounded band"
    assert_span_partition(events, stats.total_bytes)


def test_basic_fixture_covers_priority_range(tmp_path: Path) -> None:
    events, _ = run_parse_fixture(tmp_path, "basic.json")
    severities = {e.severity for e in events}
    # PRIORITY 0-7 present → every non-unknown bucket exercised.
    assert {"fatal", "error", "warn", "info", "debug"} <= severities


# --- determinism -------------------------------------------------------------


def test_event_id_plain_vs_gzip_identical(tmp_path: Path) -> None:
    data = (FIXTURES / "basic.json").read_bytes()
    plain_root = tmp_path / "plain"
    gz_root = tmp_path / "gz"
    write(plain_root, "data.json", data)
    write(gz_root, "data.json", gzip.compress(data))
    ev_plain, _ = run_parse(plain_root, "data.json")
    ev_gz, _ = run_parse(gz_root, "data.json")
    assert [e.event_id for e in ev_plain] == [e.event_id for e in ev_gz]
    assert len(ev_plain) == len(ev_gz)


# --- sniff -------------------------------------------------------------------


def test_sniff_journald_head_high(tmp_path: Path) -> None:
    write(tmp_path, "j.json", (FIXTURES / "basic.json").read_bytes())
    assert JournaldAdapter().sniff(tmp_path / "j.json") == 0.95


def test_sniff_plain_text_zero(tmp_path: Path) -> None:
    write(tmp_path, "p.log", b"2026-07-16T10:00:00Z INFO not journald at all\n")
    assert JournaldAdapter().sniff(tmp_path / "p.log") == 0.0


def test_sniff_non_signature_json_zero(tmp_path: Path) -> None:
    write(tmp_path, "o.json", b'{"foo":"bar","baz":1}\n')
    assert JournaldAdapter().sniff(tmp_path / "o.json") == 0.0


def test_sniff_journald_with_leading_noise(tmp_path: Path) -> None:
    # A stray non-JSON preamble line (a banner / "--" marker) before the first
    # signature object must not defeat detection: sniff samples a few head
    # lines rather than giving up on the first non-signature line (IN-04).
    body = (
        b"-- Journal begins at Mon 2026-07-13 09:00:00 UTC. --\n"
        b'{"__REALTIME_TIMESTAMP":"1784160000000000","PRIORITY":"6",'
        b'"MESSAGE":"m"}\n'
    )
    write(tmp_path, "j.json", body)
    assert JournaldAdapter().sniff(tmp_path / "j.json") == 0.95


def test_sniff_plain_multiline_log_zero(tmp_path: Path) -> None:
    # Several plain non-JSON lines must stay a firm 0.0 — sampling more lines
    # must not manufacture a false positive on ordinary logs.
    write(
        tmp_path,
        "p.log",
        b"2026-07-16T10:00:00Z INFO start\n2026-07-16T10:00:01Z INFO tick\n"
        b"2026-07-16T10:00:02Z WARN slow\n",
    )
    assert JournaldAdapter().sniff(tmp_path / "p.log") == 0.0


# --- helpers -----------------------------------------------------------------


def run_parse_fixture(tmp_path: Path, name: str) -> tuple[list[Event], ParseStats]:
    """Copy a committed fixture into an isolated root and parse it."""
    write(tmp_path, name, (FIXTURES / name).read_bytes())
    return run_parse(tmp_path, name)
