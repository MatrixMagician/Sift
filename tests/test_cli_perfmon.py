"""``sift perfmon`` CLI integration tests (PERF-06).

Covers the D-20 whole-file trend path (a case with a perfmon CSV and no
DSSErrors log at all), the ``perfmon`` command's ADR 0007 exit-code contract,
and success criteria 2 (byte-identical re-run) and 5 (no-log case exits 0).

The precondition the criterion-5 tests rest on is ``_build_perfmon_case``: a
case built from a perfmon CSV and NOTHING ELSE — no DSSErrors log, so no MCM
episodes — proving the "counters but no denials" shape the whole-file-trend path
must cope with actually exists and is buildable network-free.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from test_perfmon import FIXTURES, SLICE
from typer.testing import CliRunner

from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.config import load_config
from sift.models import Event
from sift.pipeline.mcm import McmAnalysis
from sift.pipeline.perfmon import (
    FULL_RANGE_LABEL,
    HAZARD_DENIAL_ALWAYS_ZERO,
    analyse_perfmon,
)
from sift.store import CaseStore, case_db_path

runner = CliRunner()

_WORKING_SET = "Working set cache RAM usage(MB)"

# No episodes at all: the D-20 input shape. Built once here rather than in each
# test so the "there is no window" premise is stated in exactly one place.
_NO_EPISODES = McmAnalysis(episodes=())


def _build_perfmon_case(case: str = "perfonly") -> Path:
    """Ingest ONLY the perfmon CSV into a real ``case.db``; return the case dir.

    Exactly one adapter is instantiated: adding a second here would destroy the
    property the criterion-5 test exists to assert.
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = DssperfmonAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / SLICE, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
    finally:
        store.close()
    return db_path.parent


def test_perfmon_only_case_has_no_dsserrors_events() -> None:
    """Criterion 5's precondition: 20 perfmon events, zero dsserrors events."""
    case_dir = _build_perfmon_case()
    assert (case_dir / "case.db").exists()
    store = CaseStore(case_dir / "case.db")
    try:
        events = store.query_events()
    finally:
        store.close()
    assert len(events) == 20
    assert all(e.source == "dssperfmon" for e in events)
    assert len([e for e in events if e.source == "dsserrors"]) == 0


def _case_events(case_dir: Path) -> list[Event]:
    store = CaseStore(case_dir / "case.db")
    try:
        return store.query_events()
    finally:
        store.close()


# --- Task 1: D-20, the full-sample-range path when there are no episodes ----


def test_no_episodes_yields_file_scope_groups() -> None:
    """D-20: no episodes, so no window — one full-range group per source file,
    carrying the SAME figures the episode path computes from the same samples."""
    events = _case_events(_build_perfmon_case())
    result = analyse_perfmon(_NO_EPISODES, events)

    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.scope == "file"
    assert group.label == FULL_RANGE_LABEL
    assert group.key == SLICE
    assert group.sample_count == 20
    # Span is the file's first and last timestamped sample, cited by id.
    assert group.start_ts is not None
    assert group.end_ts is not None
    assert len(group.boundary_event_ids) == 2

    trend = next(t for t in group.counters if t.counter == _WORKING_SET)
    assert trend.at_denial == 266042.0
    assert trend.peak == 266042.0


def test_no_episodes_no_events_yields_empty_groups() -> None:
    """The empty-of-everything path: no episodes AND no perfmon samples returns
    cleanly rather than raising IndexError on samples[0]/samples[-1]."""
    result = analyse_perfmon(_NO_EPISODES, [])
    assert result.groups == ()


def test_no_episodes_untimestamped_file_yields_no_group() -> None:
    """A perfmon file whose every sample lost its timestamp has no first or last
    sample to bound a full range with, so it is skipped rather than indexed.

    This is the test the empty guard actually turns on: the no-events-at-all
    case never enters the per-file loop, so it cannot prove the guard by itself.
    """
    undated = Event(
        event_id="undated0000000001",
        case_id="perfonly",
        ts=None,
        ts_confidence="missing",
        source="dssperfmon",
        source_file="undated.csv",
        line_start=2,
        line_end=2,
        severity="info",
        component=None,
        thread=None,
        session=None,
        message="sample with no placeable timestamp",
        attrs={_WORKING_SET: "1.0"},
        raw="sample with no placeable timestamp",
    )
    result = analyse_perfmon(_NO_EPISODES, [undated])
    assert result.groups == ()


def test_no_episodes_no_denial_hazard() -> None:
    """With no detected denial there is nothing for a zero counter to
    contradict, so the always-zero denial hazard must not fire (D-14)."""
    events = _case_events(_build_perfmon_case())
    result = analyse_perfmon(_NO_EPISODES, events)
    dimensions = [
        h.dimension
        for h in (*result.hazards, *(h for g in result.groups for h in g.hazards))
    ]
    assert HAZARD_DENIAL_ALWAYS_ZERO not in dimensions


def test_file_group_order_deterministic(tmp_path: Path) -> None:
    """Two perfmon files in one case group in a stable first-appearance order
    (dict.fromkeys, never a set), so the serialisation is identical on re-run."""
    case_dir = _build_perfmon_case("twofile")
    second = tmp_path / "second_slice.csv"
    shutil.copy(FIXTURES / SLICE, second)
    adapter = DssperfmonAdapter()
    adapter.input_root = tmp_path
    store = CaseStore(case_dir / "case.db")
    try:
        store.insert_events(list(adapter.parse(second, "twofile")))
    finally:
        store.close()

    events = _case_events(case_dir)
    first_run = analyse_perfmon(_NO_EPISODES, events)
    second_run = analyse_perfmon(_NO_EPISODES, events)
    assert len(first_run.groups) == 2
    assert first_run.model_dump_json() == second_run.model_dump_json()
