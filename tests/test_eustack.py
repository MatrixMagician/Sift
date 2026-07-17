"""eustack adapter tests: per-thread grouping, condensed top frames, single
dump-time timestamp stamping every thread, the 256-line safety cap, and the
bounded parse-coverage / span-partition invariants.

The confirmed format is native elfutils ``eu-stack`` (05-02
"proceed-on-assumed-shapes"): ``TID <n>:`` thread headers, ``#N 0xADDR symbol``
frames, and NO lock / blocked-on info — so the "lock info in attrs" portion of
INGST-09 is satisfied by asserting ABSENCE, never by fabricating locks.

Fixture: tests/fixtures/eustack/threaddump.txt (plan 05-05 Task 1).
"""

from datetime import datetime
from pathlib import Path

from sift.adapters.base import ParseStats
from sift.adapters.eustack import (
    MAX_EVENT_LINES,
    EustackAdapter,
)
from sift.models import Event

FIXTURES = Path(__file__).parent / "fixtures" / "eustack"


def run_parse(
    root: Path,
    relname: str,
    tz_overrides: dict[str, str] | None = None,
) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = EustackAdapter()
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


def _thread_events(events: list[Event]) -> list[Event]:
    """Events that correspond to a real thread block (thread id populated)."""
    return [e for e in events if e.thread is not None]


# ------------------------------------------------------------------- sniff ---


def test_sniff_eustack_head_high() -> None:
    adapter = EustackAdapter()
    assert adapter.sniff(FIXTURES / "threaddump.txt") == 0.8


def test_sniff_plain_text_zero(tmp_path: Path) -> None:
    path = write(tmp_path, "plain.txt", b"just some prose\nno threads here\n")
    adapter = EustackAdapter()
    assert adapter.sniff(path) == 0.0


def test_sniff_partial_no_frames_zero(tmp_path: Path) -> None:
    # A "TID" mention without eu-stack frames must not sniff as ours.
    path = write(tmp_path, "notmine.txt", b"TID list follows:\nalpha\nbeta\n")
    adapter = EustackAdapter()
    assert adapter.sniff(path) == 0.0


# ------------------------------------------------------ per-thread grouping ---


def test_one_event_per_thread_clean_dump(tmp_path: Path) -> None:
    body = (
        b"TID 100:\n#0  0x00007f0000000001 alpha\n#1  0x00007f0000000002 beta\n"
        b"TID 200:\n#0  0x00007f0000000010 gamma\n#1  0x00007f0000000011 delta\n"
    )
    write(tmp_path, "clean.txt", body)
    events, _ = run_parse(tmp_path, "clean.txt")
    # No preamble, no oversized block -> exactly one event per thread header.
    assert len(events) == 2
    assert [e.thread for e in events] == ["100", "200"]


def test_thread_count_matches_thread_headers_on_fixture() -> None:
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    # The fixture has four TID headers; each yields exactly one thread event
    # (preamble and cap-overflow are non-thread events).
    assert len(_thread_events(events)) == 4
    assert [e.thread for e in _thread_events(events)] == [
        "715821",
        "715822",
        "715823",
        "715824",
    ]


def test_condensed_frames_in_message_full_block_in_raw() -> None:
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    t1 = next(e for e in _thread_events(events) if e.thread == "715821")
    # message = condensed top frame symbols (lib/source suffix stripped).
    assert "clock_nanosleep@@GLIBC_2.17" in t1.message
    assert "castor_worker_wait" in t1.message
    assert "libcastor.so" not in t1.message  # condensed: no lib/source noise
    # raw = verbatim thread block (header + all frames, suffix intact).
    assert t1.raw.startswith("TID 715821:")
    assert "libcastor.so worker.cpp:412" in t1.raw
    assert "start_thread" in t1.raw


def test_no_lock_attrs_native_format() -> None:
    # Native eu-stack carries no lock/blocked-on info: assert ABSENCE, never a
    # fabricated empty value (INGST-09 contingent-lock clause).
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    for e in _thread_events(events):
        assert "waiting_on" not in e.attrs
        assert "locked" not in e.attrs
        assert "state" not in e.attrs
        assert e.component is None
        assert e.session is None


# --------------------------------------------------------------- timestamp ---


def test_single_dump_ts_stamps_all_threads() -> None:
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    threads = _thread_events(events)
    # One dump-time header ts (offset-bearing -> exact) stamps every thread.
    expected = datetime.fromisoformat("2026-07-18T09:15:30+00:00")
    assert {e.ts for e in threads} == {expected}
    assert {e.ts_confidence for e in threads} == {"exact"}


def test_absent_dump_ts_is_missing(tmp_path: Path) -> None:
    body = b"TID 100:\n#0  0x00007f0000000001 alpha\n#1  0x00007f0000000002 beta\n"
    write(tmp_path, "nots.txt", body)
    events, _ = run_parse(tmp_path, "nots.txt")
    # No dump-time header -> never invent a per-thread time.
    assert events[0].ts is None
    assert events[0].ts_confidence == "missing"


def test_naive_dump_ts_inferred_via_to_utc(tmp_path: Path) -> None:
    body = (
        b"2026-01-15 10:00:00 eu-stack backtrace\n"
        b"TID 100:\n#0  0x00007f0000000001 alpha\n"
    )
    write(tmp_path, "naive.txt", body)
    events, _ = run_parse(tmp_path, "naive.txt", {"naive.txt": "America/New_York"})
    thread = _thread_events(events)[0]
    # Naive dump ts normalised through the shared base.to_utc -> inferred.
    assert thread.ts_confidence == "inferred"
    assert thread.ts == datetime.fromisoformat("2026-01-15T15:00:00+00:00")


# --------------------------------------------------------------- cap / DoS ---


def test_oversized_thread_caps_to_unknown_continuation() -> None:
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    big = next(e for e in _thread_events(events) if e.thread == "715824")
    big_lines = big.line_end - big.line_start + 1
    assert big_lines <= MAX_EVENT_LINES  # covered thread event bounded by the cap
    # The frames beyond the cap force-close into a severity="unknown"
    # continuation event immediately after the big thread event.
    idx = events.index(big)
    cont = events[idx + 1]
    assert cont.severity == "unknown"
    assert cont.thread is None
    assert "castor_deep_frame" in cont.raw


def test_never_terminated_thread_is_bounded(tmp_path: Path) -> None:
    body = b"TID 100:\n" + b"#0  0x00007f0000000001 deep_frame\n" * 400
    write(tmp_path, "monster.txt", body)
    events, _ = run_parse(tmp_path, "monster.txt")
    thread = _thread_events(events)[0]
    assert (thread.line_end - thread.line_start + 1) <= MAX_EVENT_LINES
    assert any(e.severity == "unknown" and e.thread is None for e in events)


# ---------------------------------------------------------------- coverage ---


def test_coverage_bounded_non_vacuous() -> None:
    events, stats = run_parse(FIXTURES, "threaddump.txt")
    # Bounded: the unparseable preamble + the cap overflow are fallback bytes,
    # the thread blocks are covered.
    assert 0.95 <= stats.coverage < 1.0
    assert stats.unknown_fallback_bytes > 0
    assert_span_partition(events, stats.total_bytes)


def test_preamble_is_unknown_ts_none() -> None:
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    preamble = events[0]
    assert preamble.severity == "unknown"
    assert preamble.ts is None
    assert preamble.thread is None
    assert "sanitised eu-stack capture" in preamble.message


def test_no_emitted_severity_outside_check_set() -> None:
    allowed = {"fatal", "error", "warn", "info", "debug", "unknown"}
    events, _ = run_parse(FIXTURES, "threaddump.txt")
    assert {e.severity for e in events} <= allowed
