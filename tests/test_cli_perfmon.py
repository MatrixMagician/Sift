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

import pytest
from test_perfmon import FIXTURES, SLICE
from typer.testing import CliRunner

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.cli import app
from sift.config import load_config
from sift.models import Event
from sift.pipeline.mcm import McmAnalysis
from sift.pipeline.perfmon import (
    FULL_RANGE_LABEL,
    HAZARD_DENIAL_ALWAYS_ZERO,
    HAZARD_NON_OVERLAP,
    HAZARD_UNPLACEABLE_SAMPLES,
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


def test_no_episodes_untimestamped_file_yields_disclosure_group() -> None:
    """A perfmon file whose every sample lost its timestamp has no sample range
    to bound, but it must NOT vanish (WR-03): it yields one boundless disclosure
    group carrying an ``unplaceable_samples`` info hazard that cites the sample,
    rather than the silent drop the old ``continue`` produced.

    The empty guard stays load-bearing: this Case-B path must never index
    ``placeable`` — removing ``if not placeable`` makes ``placeable[0]`` raise
    IndexError, which is exactly why the group is built without a boundary.
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

    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.scope == "file"
    assert group.key == "undated.csv"
    assert group.sample_count == 0
    assert group.start_ts is None
    assert group.end_ts is None
    assert group.counters == ()
    assert group.boundary_event_ids == ()

    hazards = [h for h in group.hazards if h.dimension == HAZARD_UNPLACEABLE_SAMPLES]
    assert len(hazards) == 1
    assert hazards[0].severity == "info"
    assert "undated0000000001" in hazards[0].event_ids


def test_no_episodes_no_denial_hazard() -> None:
    """With no detected denial there is nothing for a zero counter to
    contradict, so the always-zero denial hazard must not fire (D-14)."""
    events = _case_events(_build_perfmon_case())
    result = analyse_perfmon(_NO_EPISODES, events)
    dimensions = [h.dimension for g in result.groups for h in g.hazards]
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


# --- Task 2: the sift perfmon command, mirroring sift mcm (D-17, ADR 0007) --


def test_bundle_written() -> None:
    """D-17: the command always writes BOTH the report and the trend CSV under
    ``<case>/perfmon/``, prints a summary and exits 0."""
    case_dir = _build_perfmon_case()
    result = runner.invoke(app, ["perfmon", "perfonly"])
    assert result.exit_code == 0, result.output
    assert (case_dir / "perfmon" / "perfmon_report.md").exists()
    assert (case_dir / "perfmon" / "perfmon_trend.csv").exists()
    assert "perfmon_trend.csv" in result.output


def test_json_format() -> None:
    """``--format json`` writes the JSON report and not the Markdown one; the
    CSV is written regardless of report format."""
    case_dir = _build_perfmon_case()
    result = runner.invoke(app, ["perfmon", "perfonly", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert (case_dir / "perfmon" / "perfmon_report.json").exists()
    assert not (case_dir / "perfmon" / "perfmon_report.md").exists()
    assert (case_dir / "perfmon" / "perfmon_trend.csv").exists()


def test_exit_codes() -> None:
    """An unknown ``--format`` is a Typer usage error (exit 2), rejected before
    the command body runs and therefore before any filesystem access."""
    case_dir = _build_perfmon_case()
    result = runner.invoke(app, ["perfmon", "perfonly", "--format", "xml"])
    assert result.exit_code == 2
    assert not (case_dir / "perfmon").exists()


def test_missing_case_exit_one() -> None:
    """An unknown case exits 1 with a helpful message, never a traceback."""
    result = runner.invoke(app, ["perfmon", "ghost"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_write_failure_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A write failure under the bundle directory exits 1 with a sanitised
    message and no traceback chain (``raise ... from None``)."""
    _build_perfmon_case()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_text", _boom)
    result = runner.invoke(app, ["perfmon", "perfonly"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "cannot write perfmon bundle" in result.output


def test_csv_write_failure_removes_partial_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WR-06/IN-02: a CSV write failure AFTER the report was written must not
    leave a valid-looking report next to a missing/truncated CSV.

    ``write_perfmon_trend_csv`` goes through ``path.open``, not ``write_text``,
    so the report succeeds first — the failure mode WR-06 names. Exit 1, and
    neither bundle file survives on disk.
    """
    case_dir = _build_perfmon_case()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr("sift.render.perfmon_report.write_perfmon_trend_csv", _boom)
    result = runner.invoke(app, ["perfmon", "perfonly"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "cannot write perfmon bundle" in result.output
    perfmon_dir = case_dir / "perfmon"
    assert not (perfmon_dir / "perfmon_report.md").exists()
    assert not (perfmon_dir / "perfmon_trend.csv").exists()


# --- Task 3: criterion 5 end-to-end and criterion 2 byte-identity ----------


def test_no_dsserrors_log() -> None:
    """Criterion 5 and the phase's named blocker: a perfmon CSV with NO
    DSSErrors log at all still yields a counter story, exit 0, no traceback.

    The report must state plainly that the figures came from the full sample
    range rather than a denial window, so a reader cannot mistake it for a
    correlation that was never performed (D-20).
    """
    case_dir = _build_perfmon_case()
    result = runner.invoke(app, ["perfmon", "perfonly"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output

    report = case_dir / "perfmon" / "perfmon_report.md"
    assert report.exists()
    assert (case_dir / "perfmon" / "perfmon_trend.csv").exists()

    text = report.read_text(encoding="utf-8")
    assert FULL_RANGE_LABEL in text
    # The engineer still gets the milestone figure with no log present.
    assert "266042" in text


def test_byte_identical_rerun() -> None:
    """Criterion 2: two runs produce byte-identical report and CSV."""
    case_dir = _build_perfmon_case()
    runner.invoke(app, ["perfmon", "perfonly"])
    report = (case_dir / "perfmon" / "perfmon_report.md").read_bytes()
    trend = (case_dir / "perfmon" / "perfmon_trend.csv").read_bytes()
    runner.invoke(app, ["perfmon", "perfonly"])
    assert (case_dir / "perfmon" / "perfmon_report.md").read_bytes() == report
    assert (case_dir / "perfmon" / "perfmon_trend.csv").read_bytes() == trend


def test_byte_identical_rerun_json() -> None:
    """Criterion 2 holds for the JSON report as well as the Markdown one."""
    case_dir = _build_perfmon_case()
    runner.invoke(app, ["perfmon", "perfonly", "--format", "json"])
    report = (case_dir / "perfmon" / "perfmon_report.json").read_bytes()
    trend = (case_dir / "perfmon" / "perfmon_trend.csv").read_bytes()
    runner.invoke(app, ["perfmon", "perfonly", "--format", "json"])
    assert (case_dir / "perfmon" / "perfmon_report.json").read_bytes() == report
    assert (case_dir / "perfmon" / "perfmon_trend.csv").read_bytes() == trend


def test_non_overlap_end_to_end() -> None:
    """Both shipped fixtures in one case exits 0 and raises the CRITICAL
    non-overlap hazard — which is the honest expectation, not a defect.

    The MCM log slice spans 12:39:47.142 to 12:39:47.356 while the perfmon
    CSV's last sample is 12:39:39.397, 7.7 s earlier, so no sample falls inside
    any window the log can define. Golden trend figures are therefore asserted
    at correlator-unit level in tests/test_perfmon.py with hand-built boundary
    events; this test must NOT be weakened into a golden-figure assertion.
    """
    case_dir = _build_perfmon_case("both")
    log_fixtures = Path(__file__).parent / "fixtures" / "mcm"
    adapter = DsserrorsAdapter()
    adapter.input_root = log_fixtures
    store = CaseStore(case_dir / "case.db")
    try:
        store.insert_events(
            list(adapter.parse(log_fixtures / "hartford_deny_slice.log", "both"))
        )
    finally:
        store.close()

    result = runner.invoke(app, ["perfmon", "both"])
    assert result.exit_code == 0, result.output
    text = (case_dir / "perfmon" / "perfmon_report.md").read_text(encoding="utf-8")
    # _field Markdown-escapes the underscore in the dimension string.
    assert HAZARD_NON_OVERLAP.replace("_", r"\_") in text
