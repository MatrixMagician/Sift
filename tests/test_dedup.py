"""Template dedup tests (CLUS-01, ADR 0003): masking, grouping, determinism."""

import random
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.store import CaseStore

_BASE = datetime(2026, 7, 16, 8, 0, 0, tzinfo=UTC)


def _dev(
    offset: int,
    message: str,
    *,
    severity: str = "info",
    with_ts: bool = True,
) -> Event:
    ts = _BASE + timedelta(seconds=offset) if with_ts else None
    return Event(
        event_id=event_id("gen.log", offset),
        case_id="demo",
        ts=ts,
        ts_confidence="exact" if with_ts else "missing",
        source="genericlog",
        source_file="gen.log",
        line_start=offset + 1,
        line_end=offset + 1,
        severity=severity,
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw=message,
    )


def _corpus() -> list[str]:
    """Seeded inline reduction fixture: ~20 template shapes x 200 lines.

    Volatile tokens (numbers, hex, UUIDs, SIDs, paths, timestamps) are the
    only variation, so masking must collapse the corpus to ~20 groups.
    """
    rng = random.Random(42)

    def _ts() -> str:
        return (_BASE + timedelta(seconds=rng.randrange(86_400))).isoformat()

    shapes: list[Callable[[], str]] = [
        lambda: f"connection pool exhausted after {rng.randrange(1_000)} retries",
        lambda: (
            f"request {uuid.UUID(int=rng.getrandbits(128))} "
            f"completed in {rng.randrange(5_000)} ms"
        ),
        lambda: (
            f"MCM contract 0x{rng.getrandbits(32):08x} denied "
            f"for session {rng.getrandbits(128):032x}"
        ),
        lambda: f"worker thread {rng.randrange(64)} started",
        lambda: f"cache miss for key {rng.getrandbits(64):016x}",
        lambda: (
            f"wrote {rng.randrange(1 << 20)} bytes "
            f"to /var/spool/job{rng.randrange(100)}/out.dat"
        ),
        lambda: f"GC pause {rng.randrange(500)} ms",
        lambda: (
            f"user {rng.randrange(10_000)} logged in "
            f"from 10.0.{rng.randrange(256)}.{rng.randrange(256)}"
        ),
        lambda: f"scheduled backup at {_ts()}",
        lambda: f"heartbeat missed for node-{rng.randrange(32)}",
        lambda: (
            f"disk usage at {rng.randrange(100)} percent "
            f"on /dev/sda{rng.randrange(1, 9)}"
        ),
        lambda: (
            f"retrying rpc call id {rng.getrandbits(64):016x} "
            f"attempt {rng.randrange(10)}"
        ),
        lambda: f"session {rng.getrandbits(128):032x} expired",
        lambda: f"queue depth {rng.randrange(1_000_000)} exceeds threshold",
        lambda: (
            f"loaded configuration "
            f"from /etc/app/conf.d/{rng.randrange(50)}-main.toml"
        ),
        lambda: (
            f"TLS handshake with peer "
            f"10.1.{rng.randrange(256)}.{rng.randrange(256)} failed"
        ),
        lambda: (
            f"checkpoint {rng.randrange(1 << 30)} flushed "
            f"in {rng.randrange(2_000)} ms"
        ),
        lambda: f"lock contention on shard {rng.randrange(128)}",
        lambda: (
            f"deprecated api call from client {uuid.UUID(int=rng.getrandbits(128))}"
        ),
        lambda: (
            f"batch {rng.randrange(1 << 16)} "
            f"contains {rng.randrange(5_000)} records"
        ),
        lambda: f"trace {rng.getrandbits(64):016x} sampled at {_ts()}",
    ]
    return [shape() for shape in shapes for _ in range(200)]


def _tg_rows(db: Path) -> list[Any]:
    """Raw byte-level snapshot of template_groups for idempotency checks."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT * FROM template_groups ORDER BY template_id"
        ).fetchall()
    finally:
        conn.close()


# --- mask token classes ----------------------------------------------------


def test_mask_timestamp() -> None:
    mask = dedup.mask
    assert (
        mask("started at 2026-07-16T10:00:01+00:00 ok") == "started at <TS> ok"
    )
    assert mask("at 2026-07-16 10:00:02.123Z done") == "at <TS> done"


def test_mask_uuid() -> None:
    mask = dedup.mask
    assert (
        mask("id 550e8400-e29b-41d4-a716-446655440000 done") == "id <UUID> done"
    )


def test_mask_0x_hex() -> None:
    mask = dedup.mask
    assert mask("code 0xDEADBEEF raised") == "code <HEX> raised"


def test_mask_bare_long_hex_sid() -> None:
    mask = dedup.mask
    sid = "0123456789abcdef0123456789abcdef"  # 32-hex MSTR SID shape
    assert mask(f"session {sid} end") == "session <HEX> end"


def test_mask_path_posix_and_windows() -> None:
    mask = dedup.mask
    assert mask("read /var/log/app.log now") == "read <PATH> now"
    assert mask(r"open C:\Windows\System32 now") == "open <PATH> now"


def test_mask_plain_number() -> None:
    mask = dedup.mask
    assert mask("retried 17 times") == "retried <NUM> times"


def test_mask_pure_decimal_long_runs_are_num_not_hex() -> None:
    """WR-04: pure-decimal 8+ digit runs (epoch seconds/millis, large ids)
    are numbers, not hex — templates must not shatter by magnitude."""
    mask = dedup.mask
    assert mask("id 1234567890123 end") == "id <NUM> end"  # 13-digit epoch ms
    assert mask("retried 12345678 times") == "retried <NUM> times"  # 8 digits


def test_mask_letter_bearing_hex_still_hex() -> None:
    """A hex run containing at least one letter still masks to <HEX>; the
    0x prefix always masks to <HEX> regardless of letters."""
    mask = dedup.mask
    assert mask("token deadbeef01 raised") == "token <HEX> raised"
    assert mask("code 0xDEADBEEF raised") == "code <HEX> raised"
    assert mask("code 0x12345678 raised") == "code <HEX> raised"


def test_mask_compound_timestamp_not_shattered() -> None:
    """Pitfall 1: a timestamp full of digits must mask to ONE <TS> token."""
    mask = dedup.mask
    assert (
        mask("at 2026-07-16T10:00:02+00:00 attempt 3") == "at <TS> attempt <NUM>"
    )


def test_mask_path_with_hex_segments_stays_path() -> None:
    mask = dedup.mask
    out = mask("load /opt/0123456789abcdef/data end")
    assert out == "load <PATH> end"
    assert "<HEX>" not in out


def test_mask_deterministic() -> None:
    mask = dedup.mask
    msgs = _corpus()[:200]
    assert [mask(m) for m in msgs] == [mask(m) for m in msgs]


def test_mask_redos_pathological_input() -> None:
    """T-02-03: 64 KB of hostile runs must complete well under a second."""
    mask = dedup.mask
    line = ("a" * 512 + "1" * 512) * 64  # 64 KiB
    start = time.perf_counter()
    mask(line)
    assert time.perf_counter() - start < 1.0


# --- grouping via the store ------------------------------------------------


def test_reduction(tmp_path: Path) -> None:
    """CLUS-01 / M2 gate: distinct groups / events <= 0.10 on the fixture,
    and every group's count/first_ts/last_ts/exemplars are correct."""
    messages = _corpus()
    events = [_dev(i, m) for i, m in enumerate(messages)]
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    n_groups = dedup.rebuild_template_groups(store)

    groups = store.query_template_groups()
    assert n_groups == len(groups)
    assert len(groups) / len(events) <= 0.10

    # Independent expected aggregation in canonical order (ts is strictly
    # ascending with offset, so insertion order == canonical order).
    expected: dict[str, dict[str, Any]] = {}
    for e in events:
        template = dedup.mask(e.message)
        agg = expected.setdefault(
            template, {"count": 0, "first": None, "last": None, "ex": []}
        )
        agg["count"] += 1
        ts = e.ts.isoformat() if e.ts is not None else None
        if agg["first"] is None:
            agg["first"] = ts
        agg["last"] = ts
        if len(agg["ex"]) < 5:
            agg["ex"].append(e.event_id)

    assert len(groups) == len(expected)
    for g in groups:
        agg = expected[g.template]
        assert g.template_id == dedup.template_id(g.template)
        assert (g.count, g.first_ts, g.last_ts, g.exemplar_event_ids) == (
            agg["count"],
            agg["first"],
            agg["last"],
            agg["ex"],
        )
    store.close()


def test_reingest_rebuild_idempotent(tmp_path: Path) -> None:
    """Pitfall 6: ingest twice + rebuild twice -> byte-identical rows."""
    events = [_dev(i, m) for i, m in enumerate(_corpus()[:400])]
    db = tmp_path / "case.db"
    store = CaseStore(db)
    assert store.insert_events(events) == len(events)
    dedup.rebuild_template_groups(store)
    first = _tg_rows(db)
    assert store.insert_events(events) == 0
    dedup.rebuild_template_groups(store)
    second = _tg_rows(db)
    store.close()
    assert first
    assert first == second


def test_accounting_every_event_counted_once(tmp_path: Path) -> None:
    """Nothing disappears silently: sum of group counts == events row count,
    including severity='unknown' rows."""
    events = [
        _dev(0, "alpha 1"),
        _dev(1, "alpha 2"),
        _dev(2, "stack frame gibberish", severity="unknown", with_ts=False),
        _dev(3, "beta done", severity="warn"),
    ]
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    dedup.rebuild_template_groups(store)
    groups = store.query_template_groups()
    assert sum(g.count for g in groups) == len(events)
    store.close()


def test_exemplar_cap(tmp_path: Path) -> None:
    """min(count, 5) exemplar ids in canonical store order."""
    small = [_dev(i, "small group event") for i in range(3)]
    big = [_dev(10 + i, "big group event") for i in range(8)]
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(small + big)
    dedup.rebuild_template_groups(store)
    by_template = {
        g.template: g for g in store.query_template_groups()
    }
    assert by_template["small group event"].exemplar_event_ids == [
        e.event_id for e in small
    ]
    assert by_template["big group event"].exemplar_event_ids == [
        e.event_id for e in big[:5]
    ]
    store.close()


def test_severity_max_uses_rank_not_lexicographic(tmp_path: Path) -> None:
    """A group holding info+error+unknown reports 'error' (rank order,
    never string comparison — 'unknown' > 'error' lexicographically)."""
    events = [
        _dev(0, "same event text", severity="info"),
        _dev(1, "same event text", severity="error"),
        _dev(2, "same event text", severity="unknown"),
    ]
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    dedup.rebuild_template_groups(store)
    groups = store.query_template_groups()
    assert len(groups) == 1
    assert groups[0].severity_max == "error"
    store.close()
