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

from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.config import load_config
from sift.models import Event
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
