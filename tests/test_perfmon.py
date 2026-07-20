"""Perfmon correlator suite: slice ingest, boundary events, hazard analysis.

This module holds the Phase 13 correlator tests. It ships two helpers the later
plans build on: ``ingest_perfmon_slice`` (a real ``case.db`` built from the
shipped Hartford CSV cut, no network) and ``log_boundary_event`` (a synthetic
non-perfmon Event standing in for a resolved episode span boundary).

LOAD-BEARING NOTE ON THE SHIPPED FIXTURES — the MCM log fixtures
(``tests/fixtures/mcm/hartford_deny_slice.log``,
``hartford_deny_predenial_multisid.log``) span only 12:39:47.142-12:39:47.356,
while this CSV's LAST sample is 12:39:39.397 — 7.7 s earlier. The two fixtures
therefore do NOT overlap in time: an MCM window resolved from either log contains
ZERO samples from this CSV. Golden trend figures must consequently be asserted at
correlator-unit level using ``log_boundary_event`` to hand-build the span, never
by ingesting the two fixtures together and reading the figures back out. That
non-overlap is real customer data, not a fixture defect, and is itself the
natural integration test for the D-06 no-samples-in-window hazard.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.config import load_config
from sift.models import Event
from sift.pipeline.mcm import (
    Attribution,
    EpisodeAnalysis,
    EpisodeWindow,
    McmAnalysis,
    McmEpisode,
    MemoryBreakdown,
)
from sift.pipeline.perfmon import (
    SLOPE_DP,
    CounterTrend,
    PerfmonAnalysis,
    PerfmonHazard,
    _numeric,  # pyright: ignore[reportPrivateUsage] — the finite-only gate D-11 turns on
    analyse_perfmon,
)
from sift.store import CaseStore, case_db_path

FIXTURES = Path(__file__).parent / "fixtures" / "dssperfmon"

SLICE = "hartford_deny_slice.csv"


def ingest_perfmon_slice(case: str = "hartford") -> list[Event]:
    """Ingest the shipped PDH-CSV cut into a real ``case.db``; return its events.

    Mirrors the ``tests/test_cli_mcm.py`` build-a-real-case idiom but drives the
    ``dssperfmon`` adapter. Network-free: the autouse conftest guards are active.
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = DssperfmonAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / SLICE, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
        return store.query_events()
    finally:
        store.close()


def log_boundary_event(
    event_id: str,
    ts: datetime | None,
    source_file: str = "synthetic.log",
) -> Event:
    """A synthetic non-perfmon Event standing in for a resolved span boundary.

    ``ts=None`` is deliberately permitted: a boundary event can resolve to a real
    stored id and still carry no timestamp (D-04), and the correlator must handle
    that rather than assume every resolved boundary is placeable on the timeline.
    """
    return Event(
        event_id=event_id,
        case_id="hartford",
        ts=ts,
        ts_confidence="exact" if ts is not None else "missing",
        source="dsserrors",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="error",
        component="MCM",
        thread=None,
        session=None,
        message="synthetic span boundary",
        attrs={},
        raw="synthetic span boundary",
    )


def test_slice_ingests_twenty_samples() -> None:
    """The shipped cut is 20 PDH sample rows, all from the dssperfmon adapter."""
    events = ingest_perfmon_slice()
    assert len(events) == 20
    assert {e.source for e in events} == {"dssperfmon"}
    # log_boundary_event must produce something the correlator can distinguish.
    boundary = log_boundary_event("0" * 16, None)
    assert boundary.source == "dsserrors"
    assert boundary.ts is None


def test_slice_carries_milestone_figures() -> None:
    """The first and last samples carry the milestone-quoted memory trend.

    Counter cells stay unconverted strings in ``attrs`` (D-03), so these are
    string comparisons by design — a numeric assertion here would silently
    tolerate the adapter starting to coerce.
    """
    events = ingest_perfmon_slice()
    first, last = events[0].attrs, events[-1].attrs
    assert first["Working set cache RAM usage(MB)"] == "27"
    assert first["RAM used(MB)"] == "186503"
    assert last["Working set cache RAM usage(MB)"] == "266042"
    assert last["RAM used(MB)"] == "463915"
    assert last["Size(MB)"] == "401603"
    assert last["Open Sessions"] == "1488"
    # Zero denials inside this window: the denial itself lands 7.7 s later, in
    # the MCM log fixtures this CSV does not overlap (see the module docstring).
    assert last["Total MCM Denial"] == "0"


# ------------------------------------------------- Task 1: models + _numeric ---


def test_numeric_rejects_non_finite() -> None:
    """``_numeric`` accepts only finite reals; everything else is ``None`` (D-11).

    ``float("nan")``/``float("inf")`` both succeed, so the adapter's bare-``float``
    ``_bad_cells`` probe lets such a cell reach the store on a clean row. This is
    the gate that stops it reaching slope, peak and at-denial.
    """
    assert _numeric("266042") == 266042.0
    for token in ("nan", "NAN", "inf", "-Infinity", "N/A", ""):
        assert _numeric(token) is None, token


def test_hazard_model_frozen_and_strict() -> None:
    """``PerfmonHazard`` forbids unknown fields and rejects mutation (D-12/D-21)."""
    with pytest.raises(ValidationError):
        PerfmonHazard(
            dimension="x",
            severity="warn",
            message="m",
            event_ids=(),
            extra_field=1,  # pyright: ignore[reportCallIssue] — extra="forbid" is the assertion
        )
    hazard = PerfmonHazard(dimension="x", severity="warn", message="m", event_ids=())
    with pytest.raises(ValidationError):
        hazard.severity = "critical"  # pyright: ignore[reportAttributeAccessIssue]
    assert SLOPE_DP == 4


def test_empty_analysis_constructs() -> None:
    """The empty case is a value, never an error — and partial counters are too."""
    assert PerfmonAnalysis(groups=(), hazards=()).groups == ()
    partial = CounterTrend(
        counter="Size(MB)",
        at_denial=None,
        at_denial_event_id=None,
        slope_per_second=None,
        peak=None,
        peak_event_id=None,
        sample_count=0,
        excluded_samples=0,
    )
    assert partial.at_denial is None


# ------------------------------------------------- Task 2: span resolution ---


_WRONG_DENIAL_TS = "1999-01-01 00:00:00.000"


def _episode_analysis(
    denial_event_id: str,
    event_ids: tuple[str, ...] = (),
    start_event_id: str | None = None,
) -> EpisodeAnalysis:
    """One minimal ``EpisodeAnalysis`` carrying only the span inputs.

    ``denial_ts`` is deliberately a WRONG date: the correlator must resolve the
    end bound from the denial event's ``Event.ts`` and never parse this string
    (D-01), so a span contaminated by it is visibly wrong rather than plausible.
    """
    return EpisodeAnalysis(
        episode=McmEpisode(
            denial_event_id=denial_event_id,
            denial_ts=_WRONG_DENIAL_TS,
            recovery=None,
            open_truncated=False,
            fragmented=False,
            event_ids=event_ids,
            lifecycle=(),
            breakdown=MemoryBreakdown(
                raw_map={}, current_memory_info={}, mcm_settings={}
            ),
            hwm_bytes=None,
            avail_timeline=(),
        ),
        window=EpisodeWindow(
            threshold_pct=0,
            start_event_id=start_event_id,
            hwm_bytes=None,
            request_count=0,
            label="full available lead-up",
        ),
        flags=(),
        attribution=Attribution(
            by_oid=(), by_source=(), by_sid=(), unmatched_event_ids=()
        ),
    )


def test_span_from_event_ids() -> None:
    """Both bounds come from resolved ``Event.ts``, never from ``denial_ts`` (D-01)."""
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    ea = _episode_analysis(denial.event_id, start_event_id=start.event_id)
    analysis = analyse_perfmon(McmAnalysis(episodes=(ea,)), [*samples, start, denial])

    group = analysis.groups[0]
    assert samples[0].ts is not None
    assert samples[-1].ts is not None
    assert group.start_ts == samples[0].ts.isoformat()
    assert group.end_ts == samples[-1].ts.isoformat()
    # The wrong denial_ts year must appear nowhere: proof it was never parsed.
    assert "1999" not in f"{group.start_ts}{group.end_ts}"


def test_span_full_leadup_fallback() -> None:
    """``start_event_id=None`` scans for the first TIMESTAMPED entry (D-03).

    ``attribute_window`` takes ``event_ids[0]`` unconditionally; here the first
    entry carries no timestamp, so taking it would leave the span unplaceable.
    """
    samples = ingest_perfmon_slice()
    untimed = log_boundary_event("u" * 16, None)
    timed = log_boundary_event("t" * 16, samples[5].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    ea = _episode_analysis(
        denial.event_id,
        event_ids=(untimed.event_id, timed.event_id),
        start_event_id=None,
    )
    analysis = analyse_perfmon(
        McmAnalysis(episodes=(ea,)), [*samples, untimed, timed, denial]
    )

    assert samples[5].ts is not None
    assert analysis.groups[0].start_ts == samples[5].ts.isoformat()


def test_span_missing_ts_hazard() -> None:
    """A boundary with ``ts=None`` yields a hazard and NO trend (D-04).

    No neighbouring event's timestamp is substituted and ``denial_ts`` is not
    consulted — an unresolvable span stays unresolved and says why.
    """
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, None)
    ea = _episode_analysis(denial.event_id, start_event_id=start.event_id)
    analysis = analyse_perfmon(McmAnalysis(episodes=(ea,)), [*samples, start, denial])

    group = analysis.groups[0]
    assert group.counters == ()
    assert group.start_ts is None
    assert group.end_ts is None
    assert group.sample_count == 0
    assert len(group.hazards) == 1
    assert group.hazards[0].event_ids


def test_span_boundaries_are_inclusive() -> None:
    """A sample landing exactly on either bound is INCLUDED (D-05)."""
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    ea = _episode_analysis(denial.event_id, start_event_id=start.event_id)
    analysis = analyse_perfmon(McmAnalysis(episodes=(ea,)), [*samples, start, denial])

    # Both edge samples counted, so all 20 fall in the closed interval.
    assert analysis.groups[0].sample_count == len(samples) == 20
