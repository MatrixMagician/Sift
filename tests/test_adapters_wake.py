"""Tests for the Wake snapshot adapter.

The fixtures here are built by hand from Wake's ``docs/snapshot-format.md``
rather than copied from Wake's own test data. That is deliberate: the adapter's
whole reason for existing in this shape is the claim that the format document is
complete enough to implement against, and a test seeded from Wake's internals
would quietly stop testing that claim.

``test_reads_wake_reference_fixture`` is the exception, and the counterpart: it
runs against the reference snapshot Wake ships precisely so that a drift between
Wake's output and this reader is caught.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import zstandard

from sift.adapters import REGISTRY
from sift.adapters.wake import WakeAdapter

# Wake's reference fixture, shipped in its repo for exactly this purpose.
WAKE_REFERENCE = (
    Path(__file__).parents[2]
    / "Wake"
    / "testdata"
    / "fixtures"
    / "reference-snapshot"
)


def _zero_drops() -> dict[str, dict[str, int]]:
    """A full, all-zero drop report.

    Every boundary and every class is present, because the contract is explicit
    that a reader must be able to tell "nothing was lost here" from "this was
    never reported".
    """
    classes = ["exec", "exit", "signal", "oom", "open", "connect", "generic"]
    return {
        boundary: dict.fromkeys(classes, 0)
        for boundary in ("kernel_ringbuf", "decode", "userspace_ring", "watch_fanout")
    }


def write_snapshot(
    root: Path,
    events: Sequence[Mapping[str, object]],
    *,
    snapshot_id: str = "20260802T142007Z-watched-process",
    manifest_overrides: dict[str, object] | None = None,
    omit_manifest: bool = False,
) -> Path:
    """Write a snapshot directory and return its ``events.jsonl.zst`` path."""
    snap = root / snapshot_id
    snap.mkdir(parents=True, exist_ok=True)

    body = "\n".join(json.dumps(e) for e in events)
    if body:
        body += "\n"
    compressed = zstandard.ZstdCompressor().compress(body.encode("utf-8"))
    events_path = snap / "events.jsonl.zst"
    events_path.write_bytes(compressed)

    if not omit_manifest:
        manifest: dict[str, object] = {
            "schema_version": 1,
            "id": snapshot_id,
            "wake_version": "v0.9.2",
            "generated_at": "2026-08-02T14:20:07.512Z",
            "trigger": {
                "type": "watched-process",
                "reason": "exit code 137",
                "rule": "mstr-crash",
                "pid": 4321,
                "unit": "mstr.service",
                "fired_at": "2026-08-02T14:20:06.998Z",
            },
            "host": {
                "hostname": "mstr-prod-07",
                "kernel_release": "6.10.0-1.fc42.x86_64",
                "machine": "x86_64",
            },
            "capture_window": {},
            "event_count": len(events),
            "event_counts": dict.fromkeys(
                ["exec", "exit", "signal", "oom", "open", "connect", "generic"], 0
            ),
            "drops": _zero_drops(),
            "config_hash": "3f9a1c",
        }
        manifest.update(manifest_overrides or {})
        (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    return events_path


@pytest.fixture
def adapter() -> WakeAdapter:
    return WakeAdapter()


# --- sniffing ---------------------------------------------------------------


def test_sniff_claims_a_real_snapshot(adapter: WakeAdapter, tmp_path: Path) -> None:
    path = write_snapshot(tmp_path, [])
    assert adapter.sniff(path) == 1.0


def test_sniff_ignores_unrelated_files(adapter: WakeAdapter, tmp_path: Path) -> None:
    other = tmp_path / "server.log"
    other.write_text("nothing to do with wake", encoding="utf-8")
    assert adapter.sniff(other) == 0.0


def test_sniff_is_weak_without_a_manifest(adapter: WakeAdapter, tmp_path: Path) -> None:
    """The right filename in the wrong place is not a snapshot."""
    path = write_snapshot(tmp_path, [], omit_manifest=True)
    assert adapter.sniff(path) < 0.5


def test_sniff_survives_a_corrupt_manifest(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    path = write_snapshot(tmp_path, [])
    (path.parent / "manifest.json").write_text("{ not json", encoding="utf-8")
    assert adapter.sniff(path) < 0.5  # degraded, but no exception


def test_registered_for_auto_detection() -> None:
    assert "wake" in REGISTRY


# --- event conversion -------------------------------------------------------


def test_exec_event(adapter: WakeAdapter, tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        [
            {
                "ts": "2026-08-02T14:20:07.123456789Z",
                "class": "exec",
                "pid": 4321,
                "uid": 987,
                "comm": "smtpd",
                "unit": "mstr.service",
                "filename": "/usr/sbin/smtpd",
                "argv": ["smtpd", "-d"],
            }
        ],
    )
    body = [e for e in adapter.parse(path, "c") if e.line_start > 0]
    assert len(body) == 1
    ev = body[0]

    assert ev.source == "wake"
    assert ev.severity == "info"
    assert ev.component == "mstr.service"
    assert "smtpd -d" in ev.message
    assert ev.attrs["argv"] == "smtpd -d"
    # Nanosecond precision must not cost the event its timestamp.
    assert ev.ts == datetime(2026, 8, 2, 14, 20, 7, 123456, tzinfo=UTC)


def test_exit_severity_reflects_the_outcome(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """A clean exit is background; a bad one is what somebody is looking for."""
    path = write_snapshot(
        tmp_path,
        [
            {"ts": "2026-08-02T14:20:01Z", "class": "exit", "pid": 1, "uid": 0,
             "exit_code": 0},
            {"ts": "2026-08-02T14:20:02Z", "class": "exit", "pid": 2, "uid": 0,
             "exit_code": 137},
            {"ts": "2026-08-02T14:20:03Z", "class": "exit", "pid": 3, "uid": 0,
             "exit_signal": 9, "signal_name": "SIGKILL"},
        ],
    )
    body = [e for e in adapter.parse(path, "c") if e.line_start > 0]
    assert [e.severity for e in body] == ["info", "error", "error"]
    assert "killed by SIGKILL" in body[2].message


def test_failed_syscalls_outrank_successful_ones(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """This is what makes "show me what failed" a single severity filter."""
    path = write_snapshot(
        tmp_path,
        [
            {"ts": "2026-08-02T14:20:01Z", "class": "open", "pid": 1, "uid": 0,
             "path": "/etc/passwd", "ret": 3},
            {"ts": "2026-08-02T14:20:02Z", "class": "open", "pid": 1, "uid": 0,
             "path": "/etc/shadow", "ret": -13, "errno": "EACCES"},
            {"ts": "2026-08-02T14:20:03Z", "class": "connect", "pid": 1, "uid": 0,
             "daddr": "10.0.4.7", "dport": 587, "ret": -110, "errno": "ETIMEDOUT"},
        ],
    )
    body = [e for e in adapter.parse(path, "c") if e.line_start > 0]
    assert [e.severity for e in body] == ["info", "warn", "warn"]
    assert "EACCES" in body[1].message
    assert "10.0.4.7:587" in body[2].message


def test_oom_is_fatal(adapter: WakeAdapter, tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        [
            {"ts": "2026-08-02T14:20:01Z", "class": "oom", "pid": 99, "uid": 0,
             "comm": "hungry", "anon_rss_kb": 8192000}
        ],
    )
    ev = [e for e in adapter.parse(path, "c") if e.line_start > 0][0]
    assert ev.severity == "fatal"
    assert "OOM killer" in ev.message


def test_crash_signals_outrank_orderly_ones(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """A SIGTERM is somebody asking politely; a SIGSEGV never is."""
    path = write_snapshot(
        tmp_path,
        [
            {"ts": "2026-08-02T14:20:01Z", "class": "signal", "pid": 1, "uid": 0,
             "signal": 15, "signal_name": "SIGTERM"},
            {"ts": "2026-08-02T14:20:02Z", "class": "signal", "pid": 1, "uid": 0,
             "signal": 11, "signal_name": "SIGSEGV"},
        ],
    )
    body = [e for e in adapter.parse(path, "c") if e.line_start > 0]
    assert [e.severity for e in body] == ["warn", "error"]


def test_generic_events_are_kept_not_dropped(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Wake's decode-is-total rule has to survive the crossing into Sift."""
    path = write_snapshot(
        tmp_path,
        [
            {
                "ts": "2026-08-02T14:20:01Z",
                "class": "generic",
                "pid": 7,
                "uid": 0,
                "raw_kind": 99,
                "raw": "3q2+7w==",
                "decode_error": "unknown kind 99",
            }
        ],
    )
    ev = [e for e in adapter.parse(path, "c") if e.line_start > 0][0]
    assert ev.severity == "unknown"
    assert "unknown kind 99" in ev.message
    assert ev.attrs["raw_kind"] == "99"


def test_unknown_fields_are_preserved(adapter: WakeAdapter, tmp_path: Path) -> None:
    """The contract requires tolerating new fields; dropping them loses evidence."""
    path = write_snapshot(
        tmp_path,
        [
            {"ts": "2026-08-02T14:20:01Z", "class": "exec", "pid": 1, "uid": 0,
             "some_future_field": "matters to a later Wake"}
        ],
    )
    ev = [e for e in adapter.parse(path, "c") if e.line_start > 0][0]
    assert ev.attrs["some_future_field"] == "matters to a later Wake"


def test_unknown_class_does_not_crash(adapter: WakeAdapter, tmp_path: Path) -> None:
    """A new event class must read as an event, not as an exception."""
    path = write_snapshot(
        tmp_path,
        [{"ts": "2026-08-02T14:20:01Z", "class": "mmap", "pid": 1, "uid": 0}],
    )
    ev = [e for e in adapter.parse(path, "c") if e.line_start > 0][0]
    assert ev.severity == "unknown"
    assert "mmap" in ev.message


# --- the context events -----------------------------------------------------


def test_trigger_event_explains_why_the_snapshot_exists(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    path = write_snapshot(tmp_path, [])
    events = list(adapter.parse(path, "c"))

    assert len(events) == 1
    trigger = events[0]
    assert trigger.severity == "error"
    assert "watched-process" in trigger.message
    assert "exit code 137" in trigger.message
    assert trigger.attrs["hostname"] == "mstr-prod-07"
    assert trigger.attrs["rule"] == "mstr-crash"
    assert trigger.ts == datetime(2026, 8, 2, 14, 20, 6, 998000, tzinfo=UTC)


def test_drops_are_surfaced_as_a_warning(adapter: WakeAdapter, tmp_path: Path) -> None:
    """The single most important behaviour in this adapter.

    Wake goes to real trouble to count what it lost. A consumer that ignored
    those counters would turn an honest partial record into a silently
    incomplete one, and then reason confidently about the gap.
    """
    drops = _zero_drops()
    drops["userspace_ring"]["open"] = 412
    drops["kernel_ringbuf"]["exec"] = 3

    path = write_snapshot(tmp_path, [], manifest_overrides={"drops": drops})
    events = list(adapter.parse(path, "c"))

    warnings = [e for e in events if e.component == "wake-drops"]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.severity == "warn"
    assert "415" in warning.message  # 412 + 3, the total actually lost
    assert "incomplete" in warning.message
    assert warning.attrs["userspace_ring.open"] == "412"


def test_no_drop_warning_when_nothing_was_lost(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """A clean snapshot must not be cluttered with a zero-drop notice."""
    path = write_snapshot(tmp_path, [])
    assert not [e for e in adapter.parse(path, "c") if e.component == "wake-drops"]


def test_watch_fanout_drops_do_not_impugn_the_snapshot(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Per the contract, watch losses say nothing about snapshot completeness."""
    drops = _zero_drops()
    drops["watch_fanout"]["exec"] = 9999
    path = write_snapshot(tmp_path, [], manifest_overrides={"drops": drops})
    assert not [e for e in adapter.parse(path, "c") if e.component == "wake-drops"]


# --- robustness -------------------------------------------------------------


def test_unparseable_line_becomes_an_event(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Nothing disappears silently, on either side of the contract."""
    snap = tmp_path / "20260802T142007Z-manual"
    snap.mkdir(parents=True)
    body = (
        json.dumps({"ts": "2026-08-02T14:20:01Z", "class": "exec", "pid": 1, "uid": 0})
        + "\n{ this is not json\n"
    )
    (snap / "events.jsonl.zst").write_bytes(
        zstandard.ZstdCompressor().compress(body.encode())
    )
    (snap / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "wake_version": "v1", "trigger": {},
                    "drops": _zero_drops()}),
        encoding="utf-8",
    )

    body_events = [
        e for e in adapter.parse(snap / "events.jsonl.zst", "c") if e.line_start > 0
    ]
    assert len(body_events) == 2
    assert body_events[1].severity == "unknown"
    assert "{ this is not json" in body_events[1].raw
    assert adapter.stats[0].unknown_fallback_bytes > 0


def test_missing_manifest_still_yields_events(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Losing context should not cost the events themselves."""
    path = write_snapshot(
        tmp_path,
        [{"ts": "2026-08-02T14:20:01Z", "class": "exec", "pid": 1, "uid": 0}],
        omit_manifest=True,
    )
    events = list(adapter.parse(path, "c"))
    assert len(events) == 1
    assert adapter.stats[0].notes  # the loss is disclosed, not swallowed


def test_future_schema_version_degrades_rather_than_refuses(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Wake's versioning policy says compatible changes do not bump this."""
    path = write_snapshot(tmp_path, [], manifest_overrides={"schema_version": 99})
    events = list(adapter.parse(path, "c"))
    assert events  # parsed anyway
    assert any("schema_version" in n for n in adapter.stats[0].notes)


def test_event_ids_are_deterministic_and_unique(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Re-ingesting the same snapshot must be idempotent."""
    events = [
        {"ts": "2026-08-02T14:20:01Z", "class": "exec", "pid": 1, "uid": 0},
        {"ts": "2026-08-02T14:20:02Z", "class": "exec", "pid": 2, "uid": 0},
    ]
    path = write_snapshot(tmp_path, events)

    first = [e.event_id for e in WakeAdapter().parse(path, "c")]
    second = [e.event_id for e in WakeAdapter().parse(path, "c")]
    assert first == second
    assert len(set(first)) == len(first)


def test_two_snapshots_in_one_case_do_not_collide(
    adapter: WakeAdapter, tmp_path: Path
) -> None:
    """Every snapshot contains a file with the same name; ids must still differ."""
    ev = [{"ts": "2026-08-02T14:20:01Z", "class": "exec", "pid": 1, "uid": 0}]
    a = write_snapshot(tmp_path, ev, snapshot_id="20260802T142007Z-manual")
    b = write_snapshot(tmp_path, ev, snapshot_id="20260802T150000Z-oom")

    ids_a = {e.event_id for e in WakeAdapter().parse(a, "c")}
    ids_b = {e.event_id for e in WakeAdapter().parse(b, "c")}
    assert not (ids_a & ids_b)


def test_empty_snapshot_is_valid(adapter: WakeAdapter, tmp_path: Path) -> None:
    """A manual trigger with a quiet ring is well-formed, not an error."""
    path = write_snapshot(tmp_path, [])
    events = list(adapter.parse(path, "c"))
    assert [e.line_start for e in events] == [0]  # the trigger event only


# --- interoperability with Wake itself --------------------------------------


@pytest.mark.skipif(
    not (WAKE_REFERENCE / "events.jsonl.zst").is_file(),
    reason="Wake's reference snapshot is not checked out alongside this repo",
)
def test_reads_wake_reference_fixture() -> None:
    """Read the snapshot Wake ships, as written by Wake's own writer.

    Every other test here builds its fixtures from the format document, which
    tests the document. This one tests the *implementation* on the other side of
    the contract, so that a drift between them cannot pass unnoticed.
    """
    adapter = WakeAdapter()
    path = WAKE_REFERENCE / "events.jsonl.zst"

    assert adapter.sniff(path) == 1.0
    events = list(adapter.parse(path, "reference"))

    assert events, "the reference snapshot produced no events"
    assert adapter.stats[0].coverage == 1.0, (
        "some of the reference snapshot did not parse"
    )
    assert all(e.source == "wake" for e in events)

    body = [e for e in events if e.line_start > 0]
    assert body, "no snapshot events, only synthetic context"
    assert all(e.ts is not None for e in body), "an event lost its timestamp"

    # The contract guarantees oldest-first ordering; relying on it is the whole
    # point of it being a contract.
    stamps = [e.ts for e in body if e.ts is not None]
    assert stamps == sorted(stamps)
