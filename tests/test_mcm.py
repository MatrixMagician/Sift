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
from sift.config import McmThresholdsConfig  # RED: built in 10-02 (GREEN)
from sift.models import Event
from sift.pipeline.mcm import (  # RED: this module is built in 09-02 (GREEN)
    Attribution,  # RED: attribution API built in 10-03 (GREEN)
    AttributionRow,  # RED: attribution API built in 10-03 (GREEN)
    DiagnosticFlag,  # RED: flag API built in 10-02 (GREEN)
    EpisodeAnalysis,  # RED: orchestration API built in 10-03 (GREEN)
    EpisodeWindow,  # RED: window API built in 10-01 (GREEN)
    LifecycleSignal,
    McmAnalysis,  # RED: orchestration API built in 10-03 (GREEN)
    McmEpisode,
    MemoryBreakdown,
    analyse_mcm,  # RED: built in 10-03 (GREEN)
    attribute_window,  # RED: built in 10-03 (GREEN)
    compute_flags,  # RED: built in 10-02 (GREEN)
    detect_episodes,
    select_window,
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


# ------------------------------------------------ MCM-04 / D-13 / D-16 (window)


def test_avail_timeline_populated(tmp_path: Path) -> None:
    """detect_episodes populates avail_timeline (event_id, avail_bytes, hwm_bytes)
    over the lead-up succeeded lines, every entry keyed to a real store event_id
    (D-16 provenance — a line number is never fabricated in its place), and
    hwm_bytes = the last lead-up sample's HWM."""
    episodes, ids = _episodes_from_fixture(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    ep = episodes[0]
    assert ep.avail_timeline  # non-empty tuple
    span_ids = set(ep.event_ids)
    for eid, avail, hwm in ep.avail_timeline:
        assert eid in ids
        assert eid in span_ids
        assert isinstance(avail, int)
        assert isinstance(hwm, int)
    # Lead-up order: the descending AvailableMCM fixture, verbatim.
    assert [av for _e, av, _h in ep.avail_timeline] == [
        300000000000,
        200000000000,
        150000000000,
        80000000000,
        40000000000,
    ]
    assert ep.hwm_bytes == ep.avail_timeline[-1][2] == 400000000000


def test_select_window_descent(tmp_path: Path) -> None:
    """select_window auto-selects the 25%-of-HWM descent window non-interactively
    (D-13 — no input(), no CLI knob): start is the first lead-up sample that fell
    below 25% of HWM in the FINAL descent (last-crossing-downward), keyed to a
    real event_id (D-16); request_count = samples at/after that start."""
    episodes, ids = _episodes_from_fixture(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    ep = episodes[0]
    win = select_window(ep)
    assert isinstance(win, EpisodeWindow)
    assert win.threshold_pct == 25

    # Independently re-derive last-crossing-downward from the timeline.
    timeline = ep.avail_timeline
    assert ep.hwm_bytes is not None
    threshold = ep.hwm_bytes * 25 / 100
    last_above = max(
        i for i, (_e, av, _h) in enumerate(timeline) if av >= threshold
    )
    expected_start = next(
        i for i in range(last_above + 1, len(timeline)) if timeline[i][1] < threshold
    )
    assert win.start_event_id == timeline[expected_start][0]
    assert win.start_event_id in ids
    assert win.request_count == len(timeline) - expected_start


def test_select_window_always_below_hartford(tmp_path: Path) -> None:
    """Over the real Hartford slice (AvailableMCM=0 throughout — always below 25%
    of HWM), select_window anchors start to the FIRST timeline entry, not line 1
    of the log (D-16), still at threshold_pct 25, and runs to completion with no
    input() (D-13 — fully automatic)."""
    episodes, ids = _episodes_from_fixture(tmp_path)  # hartford_deny_slice.log
    ep = episodes[0]
    assert ep.avail_timeline  # the single pre-denial AvailableMCM=0 grant
    win = select_window(ep)
    assert win.threshold_pct == 25
    assert win.start_event_id == ep.avail_timeline[0][0]
    assert win.start_event_id in ids


def test_select_window_empty_leadup() -> None:
    """An episode whose lead-up is empty (partial-recovery span_start == denial_idx)
    yields the full-lead-up fallback — threshold_pct 0, start_event_id None — never
    a crash and never a fabricated start (D-13/D-16)."""
    ep = McmEpisode(
        denial_event_id="deadbeefdeadbeef",
        denial_ts=None,
        recovery=None,
        open_truncated=True,
        fragmented=False,
        event_ids=("deadbeefdeadbeef",),
        lifecycle=(),
        breakdown=MemoryBreakdown(
            raw_map={}, current_memory_info={}, mcm_settings={}
        ),
        hwm_bytes=None,
        avail_timeline=(),
    )
    win = select_window(ep)
    assert win.threshold_pct == 0
    assert win.start_event_id is None
    assert win.request_count == 0


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


# ------------------------------------------------ WR-01 regression / multi-episode


def test_two_episode_partial_recovery_disjoint(tmp_path: Path) -> None:
    """Two denial episodes closed by partial recovery (denial -> success ->
    denial, no ``State=normal``) yield exactly two episodes whose lifecycle and
    denial event_ids are DISJOINT sets — the WR-01 overlapping-span regression.

    Fails against the pre-fix ``prev_recovery_idx = start_idx`` (episode 2's span
    reaches back over episode 1); passes once spans are kept disjoint.
    """
    episodes, ids = _episodes_from_fixture(
        tmp_path, "hartford_two_episode_partial.log"
    )
    assert len(episodes) == 2
    ep1, ep2 = episodes

    # Episode 2 is the still-open denial at EOF (no State=normal).
    assert ep2.open_truncated is True
    assert ep2.recovery is None

    # No lifecycle signal is double-attributed across episodes.
    life1 = {s.event_id for s in ep1.lifecycle}
    life2 = {s.event_id for s in ep2.lifecycle}
    assert life1 and life2
    assert life1.isdisjoint(life2)
    assert {s.kind for s in ep1.lifecycle} == {"memory-status-low"}
    assert {s.kind for s in ep2.lifecycle} == {"emergency-offload-complete"}

    # Citation sets are disjoint: no event_id belongs to both episodes, and every
    # denial anchor is a distinct real store row (cited ⊆ store).
    assert set(ep1.event_ids).isdisjoint(set(ep2.event_ids))
    assert ep1.denial_event_id != ep2.denial_event_id
    assert ep1.denial_event_id in ids
    assert ep2.denial_event_id in ids


def test_two_episode_own_predenial_settings(tmp_path: Path) -> None:
    """Each episode carries its OWN pre-denial MCM Settings dump: the backward
    Info-Dump lookup reaches the block preceding this denial without crossing
    into the previous episode (widened window, disjoint spans preserved)."""
    episodes, _ids = _episodes_from_fixture(
        tmp_path, "hartford_two_episode_partial.log"
    )
    ep1, ep2 = episodes
    assert ep1.breakdown.mcm_settings.get("Memory Reserve") == "1048576"
    assert ep2.breakdown.mcm_settings.get("Memory Reserve") == "2097152"
    # Distinct dumps — no cross-episode contamination of the pre-denial picture.
    assert (
        ep1.breakdown.mcm_settings["Memory Reserve"]
        != ep2.breakdown.mcm_settings["Memory Reserve"]
    )


def test_two_episode_determinism_byte_identical(tmp_path: Path) -> None:
    """Multi-episode detection is deterministic: two runs over the same stored
    events produce byte-identical JSON (no set iteration in ordered output)."""
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(
        adapter.parse(FIXTURES / "hartford_two_episode_partial.log", "case1")
    )
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    queried = store.query_events()
    first = [e.model_dump_json() for e in detect_episodes(queried)]
    second = [e.model_dump_json() for e in detect_episodes(queried)]
    assert first == second


# ------------------------------------------------ MCM-03 / D-12 (diagnostic flags)


def _detect_only(tmp_path: Path, rel: str) -> list[McmEpisode]:
    """Detect episodes from a fixture into a per-fixture case.db (distinct db name
    so two fixtures can be compared inside one test without event collision)."""
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, "case1"))
    store = CaseStore(tmp_path / f"{Path(rel).stem}.db")
    store.insert_events(events)
    return detect_episodes(store.query_events())


def _episode_with_cmi(available: int, total: int) -> McmEpisode:
    """A synthetic open episode carrying only a Current Memory Info headroom pair
    (all Format-A accessors None) — exercises the inverted headroom grader alone."""
    return McmEpisode(
        denial_event_id="deadbeefdeadbeef",
        denial_ts=None,
        recovery=None,
        open_truncated=True,
        fragmented=False,
        event_ids=("deadbeefdeadbeef",),
        lifecycle=(),
        breakdown=MemoryBreakdown(
            raw_map={},
            current_memory_info={
                "System Available": str(available),
                "System Total": str(total),
            },
            mcm_settings={},
        ),
        hwm_bytes=None,
        avail_timeline=(),
    )


def test_flags_five_dimensions(tmp_path: Path) -> None:
    """compute_flags over the Hartford slice returns five graded flags, each a
    ratio (part/whole*100) with a severity in {info,warn,critical} and each citing
    the denial event (D-16 provenance — the breakdown came from that banner)."""
    ep = _detect_only(tmp_path, "hartford_deny_slice.log")[0]
    flags = compute_flags(ep, McmThresholdsConfig())
    assert len(flags) == 5
    assert len({f.dimension for f in flags}) == 5
    for f in flags:
        assert isinstance(f, DiagnosticFlag)
        assert f.severity in {"info", "warn", "critical"}
        assert isinstance(f.value_pct, float)
        assert f.event_ids == (ep.denial_event_id,)


def test_hartford_flags_calibration(tmp_path: Path) -> None:
    """The RESEARCH calibration anchor: the real Hartford episode reads CRITICAL,
    driven by working-set = 65.4% of IServer virtual; other-processes and
    system-free headroom WARN; cube/MMF and SmartHeap INFO."""
    ep = _detect_only(tmp_path, "hartford_deny_slice.log")[0]
    flags = {f.dimension: f for f in compute_flags(ep, McmThresholdsConfig())}
    ws = flags["working_set_pct_virtual"]
    assert ws.severity == "critical"
    assert abs(ws.value_pct - 65.4) < 0.2
    assert flags["other_processes_pct_physical"].severity == "warn"
    assert flags["system_free_headroom_pct"].severity == "warn"
    assert flags["cube_mmf_coverage"].severity == "info"
    assert flags["smartheap_releasable"].severity == "info"
    # Episode overall severity = the max tier across its flags -> CRITICAL.
    order = {"info": 0, "warn": 1, "critical": 2}
    assert max(order[f.severity] for f in flags.values()) == order["critical"]


def test_headroom_inverted_grading() -> None:
    """system_free_headroom_pct grades DOWNWARD (lower free-% is worse): free=50%
    is info, free=3% is critical (the inverted-metric special case — a uniform
    upward comparison would mis-grade high headroom as critical)."""
    t = McmThresholdsConfig()
    hi = {f.dimension: f for f in compute_flags(_episode_with_cmi(50, 100), t)}
    lo = {f.dimension: f for f in compute_flags(_episode_with_cmi(3, 100), t)}
    assert hi["system_free_headroom_pct"].value_pct == 50.0
    assert hi["system_free_headroom_pct"].severity == "info"
    assert lo["system_free_headroom_pct"].value_pct == 3.0
    assert lo["system_free_headroom_pct"].severity == "critical"


def test_flags_empty_breakdown_no_crash() -> None:
    """An episode with an empty breakdown (open/truncated, every accessor None)
    returns flags without crashing — a dimension whose inputs are None emits no
    flag (nothing fabricated, D-03)."""
    ep = McmEpisode(
        denial_event_id="deadbeefdeadbeef",
        denial_ts=None,
        recovery=None,
        open_truncated=True,
        fragmented=False,
        event_ids=("deadbeefdeadbeef",),
        lifecycle=(),
        breakdown=MemoryBreakdown(
            raw_map={}, current_memory_info={}, mcm_settings={}
        ),
        hwm_bytes=None,
        avail_timeline=(),
    )
    assert compute_flags(ep, McmThresholdsConfig()) == ()


# ----------------------------------------------- crit #5 (machine-independence)


def test_machine_independence_scaled(tmp_path: Path) -> None:
    """Success criterion #5: because every flag metric is a ratio (part/whole),
    the ×2-scaled fixture yields byte-identical (dimension, severity,
    round(value_pct,3)) tuples AND identical window threshold_pct/request_count
    versus the original — absolute breakdown MB legitimately differ."""
    t = McmThresholdsConfig()
    slice_ep = _detect_only(tmp_path, "hartford_deny_slice.log")[0]
    double_ep = _detect_only(tmp_path, "hartford_deny_double.log")[0]

    def sig(ep: McmEpisode) -> tuple[tuple[str, str, float], ...]:
        return tuple(
            (f.dimension, f.severity, round(f.value_pct, 3))
            for f in compute_flags(ep, t)
        )

    assert sig(slice_ep) == sig(double_ep)

    w_slice, w_double = select_window(slice_ep), select_window(double_ep)
    assert w_slice.threshold_pct == w_double.threshold_pct
    assert w_slice.request_count == w_double.request_count

    # Pitfall 3 guard: the ×2 fixture parses the SAME number of Format-A labels.
    assert (
        len(slice_ep.breakdown.raw_map) == len(double_ep.breakdown.raw_map) == 23
    )


# ---------------------------------------- MCM-04 / D-14 / D-16 (attribution)
#
# Attribution walks the lead-up window ``[window.start_event_id … denial)`` and
# aggregates the succeeded grants into THREE independent dimensions — by OID, by
# ``Source=`` request type and by SID/session (D-14) — every figure carrying the
# owning grant-line ``event_id``s (D-16, the ``cited ⊆ store`` bridge for Phase 11).
#
# Note on the fan-out fixture and window width: ``select_window`` narrows
# ``hartford_deny_predenial_multisid.log`` to a 2-grant 25%-of-HWM DESCENT window
# (see ``test_select_window_descent``). The one-OID/many-SID fan-out (4 distinct
# SIDs across all 5 lead-up grants) is only visible over the FULL lead-up, so the
# fan-out / three-dimension / provenance assertions drive a full-lead-up window
# (``start_event_id=None``); the ``test_attribution_window_narrows_descent`` case
# separately proves the ``[window.start … denial)`` narrowing on the descent
# window. Both are legitimate ``EpisodeWindow``s ``select_window`` itself emits.


def _analysis_inputs(
    tmp_path: Path, rel: str
) -> tuple[list[McmEpisode], list[Event], set[str]]:
    """Ingest a fixture through the real adapter + store and return
    (episodes, queried events, store id set) — attribution and analyse_mcm both
    consume the queried events, so this hands all three back in one shot."""
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, "case1"))
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    queried = store.query_events()
    return detect_episodes(queried), queried, {e.event_id for e in queried}


def _full_leadup_window(ep: McmEpisode) -> EpisodeWindow:
    """The full-lead-up ``EpisodeWindow`` (``start_event_id=None``) — the span in
    which the multi-SID fan-out is visible; identical in shape to the fallback
    ``select_window`` emits for an empty/None-HWM lead-up."""
    return EpisodeWindow(
        threshold_pct=0,
        start_event_id=None,
        hwm_bytes=ep.hwm_bytes,
        request_count=len(ep.avail_timeline),
        label="full available lead-up",
    )


# The five lead-up grants of hartford_deny_predenial_multisid.log, verbatim.
_FANOUT_OID = "A3EDD9C7A24367D7CBEA259E1A9A91C0"
_LEADUP_SIZES = [19283968, 17285120, 14729216, 22093824, 11333632]


def test_attribution_three_dimensions(tmp_path: Path) -> None:
    """attribute_window over the multi-SID lead-up returns an Attribution whose
    by_oid / by_source / by_sid are each non-empty; the single fan-out OID's row
    aggregates the summed lead-up Size= bytes and lists its >=3 distinct sessions
    (D-14 three independent dimensions)."""
    episodes, events, _ids = _analysis_inputs(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    ep = episodes[0]
    attr = attribute_window(ep, _full_leadup_window(ep), events)
    assert isinstance(attr, Attribution)
    assert attr.by_oid and attr.by_source and attr.by_sid

    oid_rows = [r for r in attr.by_oid if r.key == _FANOUT_OID]
    assert len(oid_rows) == 1
    row = oid_rows[0]
    assert isinstance(row, AttributionRow)
    assert row.dimension == "oid"
    assert row.granted_bytes == sum(_LEADUP_SIZES)
    assert row.request_count == len(_LEADUP_SIZES)
    assert len(row.sids) >= 3


def test_sid_fanout_resolved(tmp_path: Path) -> None:
    """The one-OID/many-SID fan-out is resolved by the by_sid table: >=3 rows,
    one per distinct pre-denial SID, all for the single fan-out OID (D-14). The
    per-SID granted bytes sum back to the OID's total (no double counting)."""
    episodes, events, _ids = _analysis_inputs(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    ep = episodes[0]
    attr = attribute_window(ep, _full_leadup_window(ep), events)
    assert len(attr.by_sid) >= 3
    assert all(r.dimension == "sid" for r in attr.by_sid)
    assert sum(r.granted_bytes for r in attr.by_sid) == sum(_LEADUP_SIZES)
    # by_oid also records the same distinct SIDs on the fan-out row.
    oid_row = next(r for r in attr.by_oid if r.key == _FANOUT_OID)
    assert set(oid_row.sids) == {r.key for r in attr.by_sid}


def test_attribution_event_id_provenance(tmp_path: Path) -> None:
    """Every AttributionRow.event_ids is a non-empty, deduped, insertion-ordered
    tuple whose ids are all in the store AND in ep.event_ids (D-16 provenance —
    the cited ⊆ ep.event_ids ⊆ store bridge Phase 11 reuses)."""
    episodes, events, ids = _analysis_inputs(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    ep = episodes[0]
    attr = attribute_window(ep, _full_leadup_window(ep), events)
    span = set(ep.event_ids)
    all_rows = (*attr.by_oid, *attr.by_source, *attr.by_sid)
    assert all_rows
    for r in all_rows:
        assert r.event_ids  # non-empty
        assert list(r.event_ids) == list(dict.fromkeys(r.event_ids))  # deduped/ordered
        for eid in r.event_ids:
            assert eid in ids  # cited ⊆ store
            assert eid in span  # cited ⊆ ep.event_ids
    # unmatched (none here) stays a tuple, also ⊆ store.
    for eid in attr.unmatched_event_ids:
        assert eid in ids


def _synthetic_leadup() -> tuple[McmEpisode, list[Event]]:
    """A synthetic open episode: two matched pre-denial grants, one succeeded
    line missing its SID (unmatched), a denial banner carrying a *failed*-request
    ``Source=`` (Pitfall 5), then a post-denial recovery grant (Pitfall 1)."""
    base = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)

    def line(i: int, body: str) -> Event:
        ts = base.replace(second=i)
        raw = f"{ts.isoformat()} [HOST:h][SERVER:CastorServer] {body}"
        return _ev(f"{i:016x}", "node1/DSSErrors.log", raw, ts)

    events = [
        line(0, "Contract Request Succeeded: Source=Alpha, Size=1000 "
                "[SID:0][OID:0]"),
        line(1, "Contract Request Succeeded: Source=Beta, Size=2000 "
                "[SID:0][OID:0]"),
        line(2, "Contract Request Succeeded: Source=NoSid, Size=50 [OID:0]"),
        line(3, "IServer enters MCM denial state. Contract Request Failed: "
                "Source=DeniedReq, Size=9999 [SID:0][OID:0]"),
        line(4, "Contract Request Succeeded: Source=PostDenial, Size=999 "
                "[SID:0][OID:0]"),
    ]
    episodes = detect_episodes(events)
    assert len(episodes) == 1
    return episodes[0], events


def test_attribution_excludes_post_denial() -> None:
    """Only lead-up grants are attributed: the denial line's own failed-request
    Source= (Pitfall 5) and the post-denial recovery grant (Pitfall 1) appear in
    NO dimension, and the totals equal only the pre-denial grants."""
    ep, events = _synthetic_leadup()
    attr = attribute_window(ep, _full_leadup_window(ep), events)
    sources = {r.key for r in attr.by_source}
    assert sources == {"Alpha", "Beta"}
    assert "DeniedReq" not in sources
    assert "PostDenial" not in sources
    assert sum(r.granted_bytes for r in attr.by_source) == 3000
    # Post-denial / denial-line bytes never leak into by_oid either.
    assert sum(r.granted_bytes for r in attr.by_oid) == 3000


def test_attribution_unmatched_recorded() -> None:
    """A succeeded line missing SID/OID/Size lands in unmatched_event_ids, never
    dropped silently and never counted in a dimension (nothing disappears)."""
    ep, events = _synthetic_leadup()
    attr = attribute_window(ep, _full_leadup_window(ep), events)
    nosid_id = f"{2:016x}"
    assert nosid_id in attr.unmatched_event_ids
    counted = {
        eid
        for r in (*attr.by_oid, *attr.by_source, *attr.by_sid)
        for eid in r.event_ids
    }
    assert nosid_id not in counted


def test_attribution_window_narrows_descent(tmp_path: Path) -> None:
    """attribute_window over the select_window DESCENT window attributes only the
    grants inside [window.start … denial): a strict subset of the full lead-up,
    proving the [window.start … denial) narrowing (must_have truth #4)."""
    episodes, events, _ids = _analysis_inputs(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    ep = episodes[0]
    narrow = attribute_window(ep, select_window(ep), events)
    full = attribute_window(ep, _full_leadup_window(ep), events)
    narrow_oid = next(r for r in narrow.by_oid if r.key == _FANOUT_OID)
    full_oid = next(r for r in full.by_oid if r.key == _FANOUT_OID)
    # The descent window is the final 2 grants only -> strictly fewer bytes/SIDs.
    assert narrow_oid.granted_bytes < full_oid.granted_bytes
    assert set(narrow_oid.event_ids) < set(full_oid.event_ids)
    assert len(narrow.by_sid) < len(full.by_sid)


def test_attribution_empty_window() -> None:
    """An episode with an empty lead-up (denial is the first line) yields empty
    by_oid/by_source/by_sid and unmatched, and does not raise."""
    banner = (
        "2026-04-07 12:39:47.230 [HOST:h][SERVER:CastorServer] "
        "IServer enters MCM denial state. The breakdown of memory usage is:"
    )
    denial = _ev(
        "deadbeefdeadbeef",
        "node1/DSSErrors.log",
        banner,
        datetime(2026, 4, 7, 12, 39, 47, tzinfo=UTC),
    )
    ep = detect_episodes([denial])[0]
    attr = attribute_window(ep, select_window(ep), [denial])
    assert attr.by_oid == ()
    assert attr.by_source == ()
    assert attr.by_sid == ()
    assert attr.unmatched_event_ids == ()


def test_analyse_mcm_orchestration(tmp_path: Path) -> None:
    """analyse_mcm composes detect_episodes + select_window + compute_flags +
    attribute_window into a McmAnalysis with one EpisodeAnalysis per episode,
    each bundling the episode, its window, its flags and its attribution; an
    events list with no dsserrors episodes returns an empty McmAnalysis."""
    _episodes, events, _ids = _analysis_inputs(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    analysis = analyse_mcm(events, McmThresholdsConfig())
    assert isinstance(analysis, McmAnalysis)
    assert len(analysis.episodes) == 1
    ea = analysis.episodes[0]
    assert isinstance(ea, EpisodeAnalysis)
    assert isinstance(ea.episode, McmEpisode)
    assert isinstance(ea.window, EpisodeWindow)
    assert isinstance(ea.attribution, Attribution)
    assert all(isinstance(f, DiagnosticFlag) for f in ea.flags)
    # The window used is select_window(ep); attribution is bounded by it.
    assert ea.window.start_event_id == select_window(ea.episode).start_event_id

    # No dsserrors -> empty analysis, not a crash.
    assert analyse_mcm([], McmThresholdsConfig()).episodes == ()


def test_analyse_mcm_determinism(tmp_path: Path) -> None:
    """Two analyse_mcm runs over the same events are byte-identical
    (model_dump_json equal); attribution rows are sorted granted_bytes desc,
    key asc (no set iteration in ordered output)."""
    _episodes, events, _ids = _analysis_inputs(
        tmp_path, "hartford_deny_predenial_multisid.log"
    )
    t = McmThresholdsConfig()
    first = [ea.model_dump_json() for ea in analyse_mcm(events, t).episodes]
    second = [ea.model_dump_json() for ea in analyse_mcm(events, t).episodes]
    assert first == second

    attr = attribute_window(
        analyse_mcm(events, t).episodes[0].episode,
        _full_leadup_window(analyse_mcm(events, t).episodes[0].episode),
        events,
    )
    for dim in (attr.by_oid, attr.by_source, attr.by_sid):
        keys = [(r.granted_bytes, r.key) for r in dim]
        assert keys == sorted(keys, key=lambda p: (-p[0], p[1]))
