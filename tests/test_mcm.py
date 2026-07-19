"""Golden MCM episode-detection tests (MCM-01, MCM-02) — the RED half of Phase 9.

These 8 assertions pin the executable acceptance contract for the yet-to-exist
``sift.pipeline.mcm`` analyser (built GREEN in plan 09-02). Until that module
lands, this suite fails at COLLECTION with ``No module named
'sift.pipeline.mcm'`` — that is the intended Wave-1 RED state, not a bug.

Values are pinned against the real Hartford deny log
(``tests/fixtures/mcm/hartford_deny_slice.log``, a verbatim slice of source
lines 5816-5881). The slice carries exactly one open/truncated denial episode
(no ``State=normal``), its pre-denial Info Dump, the Format-A denial detail
block, and the memory-status-low / emergency-offload lifecycle tail.

Pure-function shape mirrors ``tests/test_salience.py``; the fixture-ingest helper
mirrors ``tests/test_dsserrors.py:22`` (run_parse) + ``tests/test_dedup.py:221``
(CaseStore + insert_events). No network, no ``input()``, no sleeps — the
conftest network guard and dir-isolation fixtures are autouse.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.models import Event
from sift.pipeline.mcm import (  # RED: this module is built in 09-02 (GREEN)
    LifecycleSignal,
    McmEpisode,
    MemoryBreakdown,
    detect_episodes,
)
from sift.store import CaseStore

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"


def _episodes_from_fixture(
    tmp_path: Path, rel: str = "hartford_deny_slice.log"
) -> tuple[list[McmEpisode], set[str]]:
    """Ingest the Hartford slice through the real adapter + store, then detect.

    Mirrors the established ingest pattern (test_dsserrors.run_parse +
    test_dedup CaseStore round-trip): parse the fixture via a fresh
    ``DsserrorsAdapter``, insert into a temp ``case.db``, and run
    ``detect_episodes`` over the canonically-ordered stored events. Returns the
    episodes and the set of event_ids present in the store (so citation
    assertions can check ``cited ⊆ store``).
    """
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, "case1"))
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    queried = store.query_events()
    episodes = detect_episodes(queried)
    ids = {e.event_id for e in queried}
    return episodes, ids


def _ev(event_id: str, source_file: str, raw: str, ts: datetime) -> Event:
    """A minimal in-memory dsserrors Event for the synthetic fragmentation case."""
    return Event(
        event_id=event_id,
        case_id="case1",
        ts=ts,
        ts_confidence="exact",
        source="dsserrors",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="info",
        component="MCM",
        thread=None,
        session=None,
        message=raw,
        attrs={},
        raw=raw,
    )


# --------------------------------------------------------------- crit #1 / MCM-01


def test_hartford_single_episode(tmp_path: Path) -> None:
    """Exactly one episode is detected non-interactively, and its denial anchor
    is a real event_id present in the store (the load-bearing citation path)."""
    episodes, ids = _episodes_from_fixture(tmp_path)
    assert len(episodes) == 1
    ep = episodes[0]
    assert isinstance(ep, McmEpisode)
    assert ep.denial_event_id in ids


# --------------------------------------------------------------- crit #2 / MCM-01


def test_lifecycle_signals(tmp_path: Path) -> None:
    """The episode captures the memory-status-low, emergency-offload-start and
    emergency-offload-complete lifecycle signals, each referencing a real
    in-span event_id (D-02)."""
    episodes, ids = _episodes_from_fixture(tmp_path)
    ep = episodes[0]
    kinds = {s.kind for s in ep.lifecycle}
    assert {
        "memory-status-low",
        "emergency-offload-start",
        "emergency-offload-complete",
    } <= kinds
    for sig in ep.lifecycle:
        assert isinstance(sig, LifecycleSignal)
        assert sig.event_id in ids
        assert sig.event_id in ep.event_ids


# --------------------------------------------------------------- crit #2 / D-03


def test_absent_signals_tolerated(tmp_path: Path) -> None:
    """The fixture has no ``State=normal``: recovery is recorded absent (None),
    never fabricated, and detection does not raise."""
    episodes, _ids = _episodes_from_fixture(tmp_path)
    ep = episodes[0]
    assert ep.recovery is None
    assert all(s.kind != "recovery" for s in ep.lifecycle)


# --------------------------------------------------------------- crit #3 / MCM-02


def test_breakdown_values(tmp_path: Path) -> None:
    """Typed accessors return the pinned MB-native denial-time figures, and the
    verbatim map retains all 23 Format-A labels incl. the physical/virtual
    split."""
    episodes, _ids = _episodes_from_fixture(tmp_path)
    breakdown = episodes[0].breakdown
    assert isinstance(breakdown, MemoryBreakdown)
    assert breakdown.cube_caches_mb == 27923
    assert breakdown.working_set_mb == 268502
    assert breakdown.mmf_mb == 365
    assert breakdown.other_memory_mb == 101682
    assert breakdown.iserver_virtual_mb == 410325
    assert len(breakdown.raw_map) == 23
    assert any("Total System Physical Memory" in k for k in breakdown.raw_map)
    assert any("Total System Virtual Memory" in k for k in breakdown.raw_map)


# --------------------------------------------------------------- crit #3 / MCM-02


def test_mcm_settings_complete(tmp_path: Path) -> None:
    """MCM Settings are parsed from the pre-denial Info Dump: the SmartHeap
    releasable flag is captured AND ``Memory Reserve = 0 (0Bytes)`` is NOT
    dropped by the widened abbrev regex ("nothing disappears")."""
    episodes, _ids = _episodes_from_fixture(tmp_path)
    settings = episodes[0].breakdown.mcm_settings
    assert settings.get("SmartHeap Cache Releasable") == "true"
    assert "Memory Reserve" in settings


# --------------------------------------------------------------- crit #4 / D-07


def test_open_truncated_episode(tmp_path: Path) -> None:
    """A log ending mid-episode with no recovery line is first-class
    open/truncated — flagged, not dropped, not crashed."""
    episodes, _ids = _episodes_from_fixture(tmp_path)
    ep = episodes[0]
    assert ep.open_truncated is True
    assert ep.recovery is None


# --------------------------------------------------------------- crit #5 / D-05


def test_determinism_byte_identical(tmp_path: Path) -> None:
    """Two detect_episodes runs over the same stored events produce
    byte-identical JSON (determinism invariant — no model, no set iteration)."""
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / "hartford_deny_slice.log", "case1"))
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    queried = store.query_events()
    first = [e.model_dump_json() for e in detect_episodes(queried)]
    second = [e.model_dump_json() for e in detect_episodes(queried)]
    assert first == second


# --------------------------------------------------------------- D-06 (guard)


def test_fragmented_flag() -> None:
    """A denial event with an empty detail block whose neighbouring event is a
    different source_file is flagged fragmented (multi-node rotation guard) —
    not silently merged across the boundary."""
    banner = (
        "2026-04-07 12:39:47.230 [HOST:h][SERVER:CastorServer][PID:1][THR:2]"
        "[Kernel][Info][UID:0][SID:0][OID:0][MSIServerStateLogger.cpp:964] "
        "IServer enters MCM denial state. The breakdown of memory usage is: "
    )
    denial = _ev(
        "aaaaaaaaaaaaaaaa",
        "node1/DSSErrors.log",
        banner,
        datetime(2026, 4, 7, 12, 39, 47, tzinfo=UTC),
    )
    neighbour = _ev(
        "bbbbbbbbbbbbbbbb",
        "node2/DSSErrors.log",
        "2026-04-07 12:39:48.000 [HOST:h][Kernel][Info] Some later line.",
        datetime(2026, 4, 7, 12, 39, 48, tzinfo=UTC),
    )
    episodes = detect_episodes([denial, neighbour])
    assert len(episodes) == 1
    assert episodes[0].fragmented is True
