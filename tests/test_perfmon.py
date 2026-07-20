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

import csv
import math
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from _perfmon_fixtures import write_drift_csv, write_non_finite_csv
from pydantic import ValidationError

from sift.adapters.dssperfmon import (
    _DRIFT_ATTR,  # pyright: ignore[reportPrivateUsage] — the ingest-time marker the drift hazard cites (D-15)
    DssperfmonAdapter,
)
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
    HAZARD_COUNTER_SET_DRIFT,
    HAZARD_DENIAL_ALWAYS_ZERO,
    HAZARD_NON_OVERLAP,
    MCM_DENIAL_COUNTER,
    SLOPE_DP,
    CounterTrend,
    PerfmonAnalysis,
    PerfmonHazard,
    _cited,  # pyright: ignore[reportPrivateUsage] — the order-preserving citation builder D-21 turns on
    _find_counter_key,  # pyright: ignore[reportPrivateUsage] — the qualification-proof lookup T-13-EVADE turns on
    _numeric,  # pyright: ignore[reportPrivateUsage] — the finite-only gate D-11 turns on
    analyse_perfmon,
)
from sift.store import CaseStore, case_db_path

FIXTURES = Path(__file__).parent / "fixtures" / "dssperfmon"

SLICE = "hartford_deny_slice.csv"


def ingest_perfmon_slice(
    case: str = "hartford", csv_path: Path | None = None
) -> list[Event]:
    """Ingest a PDH-CSV into a real ``case.db``; return its events.

    Defaults to the shipped Hartford cut. ``csv_path`` lets a test drive the same
    real ingest path with a synthetic fixture from ``_perfmon_fixtures`` rather
    than hand-building Events, so the correlator is always fed adapter output.
    Mirrors the ``tests/test_cli_mcm.py`` build-a-real-case idiom but drives the
    ``dssperfmon`` adapter. Network-free: the autouse conftest guards are active.
    """
    path = csv_path if csv_path is not None else FIXTURES / SLICE
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = DssperfmonAdapter()
    adapter.input_root = path.parent
    events = list(adapter.parse(path, case))
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
    assert PerfmonAnalysis(groups=()).groups == ()
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


# --------------------------------------------------- Task 3: trend figures ---


def _correlate(samples: list[Event], start: Event, end: Event) -> PerfmonAnalysis:
    """Run the correlator over one hand-built span (see the module docstring)."""
    ea = _episode_analysis(end.event_id, start_event_id=start.event_id)
    return analyse_perfmon(McmAnalysis(episodes=(ea,)), [*samples, start, end])


def _trend(analysis: PerfmonAnalysis, counter: str) -> CounterTrend:
    return next(c for c in analysis.groups[0].counters if c.counter == counter)


def test_golden_trend_figures() -> None:
    """The Hartford milestone figures, reproduced exactly from the slice (D-07/D-09)."""
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    analysis = _correlate(samples, start, denial)

    expected_at_denial = {
        "Working set cache RAM usage(MB)": 266042.0,
        "RAM used(MB)": 463915.0,
        "Size(MB)": 401603.0,
        "Open Sessions": 1488.0,
        "Total MCM Denial": 0.0,
    }
    for counter, value in expected_at_denial.items():
        trend = _trend(analysis, counter)
        assert trend.at_denial == value, counter
        # D-09: the figure cites the sample it came from — the LAST in-span one.
        assert trend.at_denial_event_id == samples[-1].event_id, counter

    # Working set climbs monotonically over the cut, so its peak IS the last value.
    assert _trend(analysis, "Working set cache RAM usage(MB)").peak == 266042.0

    # D-08, computed by hand from the two boundary samples, NOT from the code
    # under test. The cut is two 10-sample blocks five days apart, NOT twenty
    # consecutive 30 s samples:
    #   first  04/02/2026 19:21:38.236, Working set = 27
    #   last   04/07/2026 12:39:39.397, Working set = 266042
    #   elapsed = 5 d (432000 s) - 6h41m58.839s (24118.839 s) = 407881.161 s
    #   (266042 - 27) / 407881.161 = 266015 / 407881.161 = 0.65218752... -> 0.6522
    assert SLOPE_DP == 4
    assert _trend(analysis, "Working set cache RAM usage(MB)").slope_per_second == (
        0.6522
    )
    # Flat counter over the same span: zero numerator, so exactly 0.0.
    assert _trend(analysis, "Total MCM Denial").slope_per_second == 0.0

    # D-21: identical inputs, byte-identical output.
    assert (
        analysis.model_dump_json()
        == _correlate(samples, start, denial).model_dump_json()
    )


def test_single_sample_no_zero_division() -> None:
    """A one-sample span yields ``slope=None``, not a ``ZeroDivisionError``.

    Normal at a 30 s sampling interval against a short MCM descent — a narrow
    window is not a correlation failure, so no hazard is raised either.
    """
    samples = ingest_perfmon_slice()
    edge = log_boundary_event("s" * 16, samples[3].ts)
    denial = log_boundary_event("d" * 16, samples[3].ts)
    analysis = _correlate(samples, edge, denial)

    group = analysis.groups[0]
    assert group.sample_count == 1
    trend = _trend(analysis, "Working set cache RAM usage(MB)")
    assert trend.slope_per_second is None
    assert trend.at_denial is not None
    assert trend.peak == trend.at_denial
    # A narrow window is not a correlation failure: no span or non-overlap
    # hazard. The always-zero denial flag DOES fire here — the Hartford cut's
    # Total MCM Denial reads 0 on every sample — and is asserted separately.
    assert [h for h in group.hazards if h.dimension != HAZARD_DENIAL_ALWAYS_ZERO] == []


def test_non_finite_excluded(tmp_path: Path) -> None:
    """A ``nan`` cell excludes ONE counter for ONE sample, and is counted (D-11)."""
    samples = ingest_perfmon_slice(
        case="nonfinite", csv_path=write_non_finite_csv(tmp_path)
    )
    # Span the first two rows only: RAM used carries the nan there, Open Sessions
    # does not — so the sibling counter on the same rows must stay untouched.
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[1].ts)
    analysis = _correlate(samples, start, denial)

    ram = _trend(analysis, "RAM used(MB)")
    assert ram.sample_count == 2
    assert ram.excluded_samples == 1
    assert ram.at_denial == 463915.0  # the surviving row, never interpolated
    assert _trend(analysis, "Open Sessions").excluded_samples == 0

    for counter in analysis.groups[0].counters:
        for figure in (counter.at_denial, counter.slope_per_second, counter.peak):
            assert figure is None or math.isfinite(figure), counter.counter


def test_peak_tie_takes_earliest_sample() -> None:
    """Equal-valued samples resolve the peak to the EARLIEST one (D-10).

    ``Total MCM Denial`` is 0 across the whole cut — 20 samples tied at the
    maximum — so the citation must be the first sample, not the last.
    """
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    analysis = _correlate(samples, start, denial)

    trend = _trend(analysis, "Total MCM Denial")
    assert trend.peak == 0.0
    assert trend.peak_event_id == samples[0].event_id


# ------------------------------------------- Task 1 (13-04): non-overlap ---


def _non_overlap(analysis: PerfmonAnalysis) -> list[PerfmonHazard]:
    """Every non-overlap hazard anywhere in the analysis."""
    return [
        hazard
        for group in analysis.groups
        for hazard in group.hazards
        if hazard.dimension == HAZARD_NON_OVERLAP
    ]


def test_non_overlap_hazard() -> None:
    """A span containing zero samples is a CRITICAL flag, never an empty table.

    D-06: zero-in-span IS the wrong-timezone / wrong-host / wrong-day symptom,
    so it is the loud hazard rather than a silently empty trend table. The two
    shipped fixtures genuinely do not overlap (see the module docstring); the
    span here is pushed a decade out to make the mismatch unambiguous.
    """
    samples = ingest_perfmon_slice()
    assert samples[-1].ts is not None
    far = samples[-1].ts + timedelta(days=3650)
    start = log_boundary_event("s" * 16, far)
    denial = log_boundary_event("d" * 16, far + timedelta(hours=1))
    analysis = _correlate(samples, start, denial)

    group = analysis.groups[0]
    assert group.counters == ()
    assert len(group.hazards) == 1
    hazard = group.hazards[0]
    assert hazard.severity == "critical"
    assert hazard.dimension == HAZARD_NON_OVERLAP
    # Both ranges named side by side, so the reader can diagnose WHICH mismatch
    # it is — a message reading only "no overlap" is not actionable.
    assert samples[0].ts is not None
    for moment in (start.ts, denial.ts, samples[0].ts, samples[-1].ts):
        assert moment is not None
        assert moment.isoformat() in hazard.message
    # Time non-overlap only: a wrong host whose clock overlaps will not trip it.
    assert "host" in hazard.message
    # The two span boundaries plus the first and last perfmon sample.
    assert len(hazard.event_ids) >= 4

    # An OVERLAPPING span raises no hazard of this dimension at all.
    ok_start = log_boundary_event("s" * 16, samples[0].ts)
    ok_denial = log_boundary_event("d" * 16, samples[-1].ts)
    assert _non_overlap(_correlate(samples, ok_start, ok_denial)) == []


def test_non_overlap_hazard_with_no_perfmon_events() -> None:
    """Zero perfmon events in the case: no ``samples[0]``, so no ``IndexError``.

    The message must name the ABSENCE of samples rather than an empty range —
    indexing a bare list to build the message is the failure this guards.
    """
    start = log_boundary_event("s" * 16, datetime.fromisoformat("2026-04-07T12:00:00"))
    denial = log_boundary_event("d" * 16, datetime.fromisoformat("2026-04-07T13:00:00"))
    analysis = _correlate([], start, denial)

    hazards = _non_overlap(analysis)
    assert len(hazards) == 1
    assert hazards[0].severity == "critical"
    assert "no perfmon samples" in hazards[0].message
    assert hazards[0].event_ids == (start.event_id, denial.event_id)


# ----------------------------- Task 2 (13-04): always-zero Total MCM Denial ---


def _of_dimension(analysis: PerfmonAnalysis, dimension: str) -> list[PerfmonHazard]:
    """Every hazard of one dimension anywhere in the analysis."""
    return [
        hazard
        for group in analysis.groups
        for hazard in group.hazards
        if hazard.dimension == dimension
    ]


def _write_denial_csv(tmp_path: Path, readings: list[str], name: str) -> Path:
    """A minimal PDH-CSV whose ``Total MCM Denial`` column takes ``readings``.

    Hand-written rather than added to ``_perfmon_fixtures``: the numeric-vs-string
    zero test needs cells (``0.0``, ``0.0000001``) that no other test wants, and
    a shared builder parameterised for one caller is not a shared builder.
    """
    stamps = [
        "04/07/2026 12:39:09.397",
        "04/07/2026 12:39:39.397",
        "04/07/2026 12:40:09.397",
    ]
    host = "env-325602laio1use1"
    header = [
        "(PDH-CSV 4.0) (Eastern Standard Time)(300)",
        f"\\\\{host}\\MicroStrategy Server Jobs(CastorServer)\\{MCM_DENIAL_COUNTER}",
        f"\\\\{host}\\System\\RAM used(MB)",
    ]
    rows = [[stamps[i], reading, str(463900 + i)] for i, reading in enumerate(readings)]
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_mcm_denial_always_zero() -> None:
    """A real denial contradicted by a flat-zero counter is a WARN flag (D-14).

    The Hartford cut reads ``0`` on all 20 samples, matching the real file's
    single distinct value across all 13,596 rows — the counter is not wired.
    """
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    analysis = _correlate(samples, start, denial)

    hazards = _of_dimension(analysis, HAZARD_DENIAL_ALWAYS_ZERO)
    assert len(hazards) == 1
    assert hazards[0].severity == "warn"
    assert hazards[0].value == 0.0
    assert hazards[0].event_ids
    # The denial itself is cited: the flag exists because it CONTRADICTS one.
    assert denial.event_id in hazards[0].event_ids
    assert MCM_DENIAL_COUNTER in hazards[0].message


def test_no_episodes_no_zero_hazard() -> None:
    """No episodes means no denial to contradict, so no hazard at all (D-14).

    A zero counter with nothing to contradict is just a zero counter; firing on
    every healthy case trains the reader to ignore the flag that matters.
    """
    samples = ingest_perfmon_slice()
    analysis = analyse_perfmon(McmAnalysis(episodes=()), samples)

    all_hazards = [h for group in analysis.groups for h in group.hazards]
    assert [h for h in all_hazards if h.dimension == HAZARD_DENIAL_ALWAYS_ZERO] == []
    # The counter still reads zero throughout — absence of the flag is the point.
    assert all(s.attrs[MCM_DENIAL_COUNTER] == "0" for s in samples)


def test_mcm_denial_zero_test_is_numeric_not_string(tmp_path: Path) -> None:
    """``"0.0"`` counts as zero; ``"0.0000001"`` does not (no ``v == "0"``).

    A string shortcut gets both wrong in different directions: ``"0.0" == "0"``
    is False so the real flag would be missed, and a prefix test would fire on
    ``"0.0000001"`` where the counter is demonstrably live.
    """
    for readings, expected in (
        (["0.0", "0.0", "0.0"], 1),
        (["0.0", "0.0000001", "0.0"], 0),
    ):
        name = f"denial_{len(readings)}_{expected}.csv"
        events = ingest_perfmon_slice(
            case=f"denialzero{expected}",
            csv_path=_write_denial_csv(tmp_path, readings, name),
        )
        start = log_boundary_event("s" * 16, events[0].ts)
        denial = log_boundary_event("d" * 16, events[-1].ts)
        analysis = _correlate(events, start, denial)
        hazards = _of_dimension(analysis, HAZARD_DENIAL_ALWAYS_ZERO)
        assert len(hazards) == expected, readings


def test_find_counter_key_survives_qualification() -> None:
    """The lookup resolves the bare name AND every collision-qualified key.

    Plan 13-03 rewrites only COLLIDING short names to their last two backslash
    segments, so both spellings are live in shipped data. Returning every match
    is what stops a crafted duplicate counter masking a genuinely non-zero
    instance behind a zero one (T-13-EVADE).
    """
    assert _find_counter_key({MCM_DENIAL_COUNTER: "0"}) == (MCM_DENIAL_COUNTER,)
    qualified = {
        f"Jobs(B)\\{MCM_DENIAL_COUNTER}": "1",
        f"Jobs(A)\\{MCM_DENIAL_COUNTER}": "0",
        "RAM used(MB)": "463915",
    }
    # Sorted, so the order cannot vary with dict insertion order (D-21).
    assert _find_counter_key(qualified) == (
        f"Jobs(A)\\{MCM_DENIAL_COUNTER}",
        f"Jobs(B)\\{MCM_DENIAL_COUNTER}",
    )
    assert _find_counter_key({"RAM used(MB)": "463915"}) == ()


# --------------------- Task 3 (13-04): counter-set drift + stable ordering ---


def _write_drift_and_zero_csv(tmp_path: Path) -> Path:
    """A PDH-CSV carrying BOTH defects: a mid-file short row and a zero denial.

    ``test_hazards_deterministic_order`` needs two hazards of EQUAL severity in
    one group so the tie-break path is actually exercised; drift and always-zero
    are both ``warn``. ``_perfmon_fixtures.write_drift_csv`` has no denial
    column, so it cannot raise the second one.
    """
    host = "env-325602laio1use1"
    header = [
        "(PDH-CSV 4.0) (Eastern Standard Time)(300)",
        f"\\\\{host}\\MicroStrategy Server Jobs(CastorServer)\\{MCM_DENIAL_COUNTER}",
        f"\\\\{host}\\System\\RAM used(MB)",
        f"\\\\{host}\\Process(MSTRSvr)\\Size(MB)",
    ]
    rows = [
        ["04/07/2026 12:39:09.397", "0", "463915", "401603"],
        ["04/07/2026 12:39:39.397", "0", "463920"],  # drifted, mid-file
        ["04/07/2026 12:40:09.397", "0", "463925", "401620"],
    ]
    path = tmp_path / "drift_and_zero.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_counter_set_drift_hazard(tmp_path: Path) -> None:
    """Drifted rows in the span raise one warn hazard citing those events (D-15)."""
    events = ingest_perfmon_slice(case="drift", csv_path=write_drift_csv(tmp_path))
    start = log_boundary_event("s" * 16, events[0].ts)
    denial = log_boundary_event("d" * 16, events[-1].ts)
    analysis = _correlate(events, start, denial)

    hazards = _of_dimension(analysis, HAZARD_COUNTER_SET_DRIFT)
    assert len(hazards) == 1
    assert hazards[0].severity == "warn"
    assert hazards[0].value == 1.0  # one drifted row in the fixture
    assert hazards[0].event_ids
    # Every cited id belongs to an event that actually carries the marker.
    marked = {e.event_id for e in events if _DRIFT_ATTR in e.attrs}
    assert set(hazards[0].event_ids) <= marked


def test_no_drift_no_drift_hazard() -> None:
    """Hartford is uniformly 23 columns wide, so nothing drifts and nothing fires."""
    samples = ingest_perfmon_slice()
    start = log_boundary_event("s" * 16, samples[0].ts)
    denial = log_boundary_event("d" * 16, samples[-1].ts)
    analysis = _correlate(samples, start, denial)

    assert _of_dimension(analysis, HAZARD_COUNTER_SET_DRIFT) == []
    assert not any(_DRIFT_ATTR in s.attrs for s in samples)


def test_drift_hazard_reads_marker_not_row_widths(tmp_path: Path) -> None:
    """Strip the marker, keep the ragged rows: the hazard must go silent.

    Proof that drift is detected ONCE at ingest and never re-derived here — a
    second detector could disagree with the adapter about what drifted (D-15).
    """
    events = ingest_perfmon_slice(case="driftbare", csv_path=write_drift_csv(tmp_path))
    assert any(_DRIFT_ATTR in e.attrs for e in events), "fixture stopped drifting"
    # The underlying rows stay ragged — only the marker is removed.
    stripped = [
        replace(e, attrs={k: v for k, v in e.attrs.items() if k != _DRIFT_ATTR})
        for e in events
    ]
    assert len({len(e.attrs) for e in stripped}) > 1, "rows are no longer ragged"

    start = log_boundary_event("s" * 16, stripped[0].ts)
    denial = log_boundary_event("d" * 16, stripped[-1].ts)
    analysis = _correlate(stripped, start, denial)
    assert _of_dimension(analysis, HAZARD_COUNTER_SET_DRIFT) == []


def test_hazards_deterministic_order(tmp_path: Path) -> None:
    """Two runs over identical inputs produce byte-identical output (D-21).

    The fixture raises TWO ``warn`` hazards — drift and always-zero denial — so
    the equal-severity tie-break is genuinely exercised rather than assumed.
    """
    events = ingest_perfmon_slice(
        case="driftzero", csv_path=_write_drift_and_zero_csv(tmp_path)
    )
    start = log_boundary_event("s" * 16, events[0].ts)
    denial = log_boundary_event("d" * 16, events[-1].ts)

    # Re-running in ONE process cannot catch set iteration — hash order is fixed
    # for a process lifetime, so both runs would agree on the same wrong order.
    # The order-preservation contract is therefore asserted directly: dict
    # .fromkeys keeps first-seen order and deduplicates; set() does neither.
    ids = ["c" * 16, "a" * 16, "b" * 16, "a" * 16, "d" * 16, "e" * 16]
    assert _cited(ids) == (("c" * 16, "a" * 16, "b" * 16, "d" * 16, "e" * 16), 5)

    first = _correlate(events, start, denial)
    hazards = first.groups[0].hazards
    assert [h.severity for h in hazards] == ["warn", "warn"]
    assert {h.dimension for h in hazards} == {
        HAZARD_DENIAL_ALWAYS_ZERO,
        HAZARD_COUNTER_SET_DRIFT,
    }
    assert (
        first.model_dump_json() == _correlate(events, start, denial).model_dump_json()
    )
