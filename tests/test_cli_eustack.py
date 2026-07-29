"""``sift eustack`` CLI integration tests (EUS-09).

Covers the D-12 standalone contract mirrored verbatim from ``sift mcm``/
``sift perfmon``: exit codes, an empty case, partial-write cleanup, and
byte-identical re-runs, plus the phase's own named blocker — a case built
from eu-stack dumps and NOTHING ELSE (no DSSErrors log at all) still exits 0
with a written bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift.adapters.eustack import EustackAdapter
from sift.cli import app
from sift.config import load_config
from sift.store import CaseStore, case_db_path

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "eustack"
THREADDUMP = "threaddump.txt"
PROGRESSION_FIXTURES = FIXTURES / "progression"
PROGRESSION_DUMPS = ("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")


def _build_eustack_case(case: str = "eustackonly") -> Path:
    """Ingest ONLY ``threaddump.txt`` into a real ``case.db``; return the case
    dir.

    Exactly one adapter is instantiated: instantiating a second here would
    destroy the very property ``test_eustack_no_dsserrors_log`` exists to
    assert.
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = EustackAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / THREADDUMP, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
    finally:
        store.close()
    return db_path.parent


def _build_progression_case(case: str = "eustackmulti") -> Path:
    """Ingest all three timestamped ``progression/`` fixtures into a real
    ``case.db`` — a genuine multi-dump case, not the single-dump ``THREADDUMP``
    fixture the rest of this module uses."""
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = EustackAdapter()
    adapter.input_root = PROGRESSION_FIXTURES
    events = []
    for name in PROGRESSION_DUMPS:
        events.extend(adapter.parse(PROGRESSION_FIXTURES / name, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
    finally:
        store.close()
    return db_path.parent


def _build_empty_case(case: str = "eustackempty") -> Path:
    """A real ``case.db`` with zero ingested events at all."""
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = CaseStore(db_path)
    store.close()
    return db_path.parent


def test_eustack_writes_bundle() -> None:
    """D-12: the command always writes BOTH the report and the signatures CSV
    under ``<case>/eustack/``, prints a summary and exits 0."""
    case_dir = _build_eustack_case()
    result = runner.invoke(app, ["eustack", "eustackonly"])
    assert result.exit_code == 0, result.output
    report = case_dir / "eustack" / "eustack_report.md"
    csv_path = case_dir / "eustack" / "eustack_signatures.csv"
    assert report.exists()
    assert report.stat().st_size > 0
    assert csv_path.exists()
    assert csv_path.stat().st_size > 0
    assert "eustack_signatures.csv" in result.output


def test_eustack_no_dsserrors_log() -> None:
    """EUS-09's named blocker: a case built from eu-stack dumps and NO
    DSSErrors log at all still yields a written bundle, exit 0."""
    case_dir = _build_eustack_case()
    store = CaseStore(case_dir / "case.db")
    try:
        events = store.query_events()
    finally:
        store.close()
    assert len(events) > 0
    assert all(e.source == "eustack" for e in events)
    assert len([e for e in events if e.source == "dsserrors"]) == 0

    result = runner.invoke(app, ["eustack", "eustackonly"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output


def test_eustack_json_format() -> None:
    """``--format json`` writes the JSON report alongside the CSV, and it
    parses as JSON."""
    case_dir = _build_eustack_case()
    result = runner.invoke(app, ["eustack", "eustackonly", "--format", "json"])
    assert result.exit_code == 0, result.output
    report = case_dir / "eustack" / "eustack_report.json"
    assert report.exists()
    assert not (case_dir / "eustack" / "eustack_report.md").exists()
    assert (case_dir / "eustack" / "eustack_signatures.csv").exists()
    json.loads(report.read_text(encoding="utf-8"))


def test_eustack_empty_case() -> None:
    """A case with zero ingested events at all still exits 0 with both
    artefacts written, and the CSV still carries its header row."""
    case_dir = _build_empty_case()
    result = runner.invoke(app, ["eustack", "eustackempty"])
    assert result.exit_code == 0, result.output

    report = case_dir / "eustack" / "eustack_report.md"
    csv_path = case_dir / "eustack" / "eustack_signatures.csv"
    assert report.exists()
    assert csv_path.exists()
    text = report.read_text(encoding="utf-8")
    assert "No eu-stack dumps were present" in text
    header_line = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert "role" in header_line
    assert "thread_count" in header_line


def test_eustack_missing_case_exit_one() -> None:
    """An unknown case exits 1 with a helpful message, never a traceback."""
    result = runner.invoke(app, ["eustack", "ghost"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_eustack_bad_format_exit_two() -> None:
    """An unknown ``--format`` is a Typer usage error (exit 2), rejected
    before the command body runs and therefore before any filesystem
    access."""
    case_dir = _build_eustack_case()
    result = runner.invoke(app, ["eustack", "eustackonly", "--format", "xml"])
    assert result.exit_code == 2
    assert not (case_dir / "eustack").exists()


def test_eustack_write_failure_removes_partial_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CSV write failure AFTER the report was written must not leave a
    valid-looking report next to a missing/truncated CSV."""
    case_dir = _build_eustack_case()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(
        "sift.render.eustack_report.write_eustack_signatures_csv", _boom
    )
    result = runner.invoke(app, ["eustack", "eustackonly"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "cannot write eustack bundle" in result.output
    eustack_dir = case_dir / "eustack"
    assert not (eustack_dir / "eustack_report.md").exists()
    assert not (eustack_dir / "eustack_signatures.csv").exists()


def test_eustack_byte_identical_rerun() -> None:
    """D-13: two runs produce byte-identical report and CSV."""
    case_dir = _build_eustack_case()
    runner.invoke(app, ["eustack", "eustackonly"])
    report = (case_dir / "eustack" / "eustack_report.md").read_bytes()
    csv_bytes = (case_dir / "eustack" / "eustack_signatures.csv").read_bytes()
    runner.invoke(app, ["eustack", "eustackonly"])
    assert (case_dir / "eustack" / "eustack_report.md").read_bytes() == report
    assert (case_dir / "eustack" / "eustack_signatures.csv").read_bytes() == csv_bytes


def test_eustack_byte_identical_rerun_json() -> None:
    """D-13 holds for the JSON report as well as the Markdown one."""
    case_dir = _build_eustack_case()
    runner.invoke(app, ["eustack", "eustackonly", "--format", "json"])
    report = (case_dir / "eustack" / "eustack_report.json").read_bytes()
    csv_bytes = (case_dir / "eustack" / "eustack_signatures.csv").read_bytes()
    runner.invoke(app, ["eustack", "eustackonly", "--format", "json"])
    assert (case_dir / "eustack" / "eustack_report.json").read_bytes() == report
    assert (case_dir / "eustack" / "eustack_signatures.csv").read_bytes() == csv_bytes


def test_eustack_multi_dump_byte_identical_rerun() -> None:
    """D-13 over a GENUINE multi-dump case (not the single-dump N=1 shape
    ``test_eustack_byte_identical_rerun`` already covers): two runs produce
    byte-identical Markdown, JSON and CSV."""
    case_dir = _build_progression_case()
    runner.invoke(app, ["eustack", "eustackmulti"])
    report = (case_dir / "eustack" / "eustack_report.md").read_bytes()
    csv_bytes = (case_dir / "eustack" / "eustack_signatures.csv").read_bytes()
    runner.invoke(app, ["eustack", "eustackmulti"])
    assert (case_dir / "eustack" / "eustack_report.md").read_bytes() == report
    assert (case_dir / "eustack" / "eustack_signatures.csv").read_bytes() == csv_bytes

    runner.invoke(app, ["eustack", "eustackmulti", "--format", "json"])
    json_report = (case_dir / "eustack" / "eustack_report.json").read_bytes()
    json_csv = (case_dir / "eustack" / "eustack_signatures.csv").read_bytes()
    runner.invoke(app, ["eustack", "eustackmulti", "--format", "json"])
    assert (case_dir / "eustack" / "eustack_report.json").read_bytes() == json_report
    assert (case_dir / "eustack" / "eustack_signatures.csv").read_bytes() == json_csv


def test_eustack_multi_dump_bundle_reports_progression() -> None:
    """A genuine 3-dump case exits 0, names more than one changed signature
    in its stdout summary, and its written report carries the progression
    section heading plus the warehouse population figures."""
    case_dir = _build_progression_case("eustackprogression")
    result = runner.invoke(app, ["eustack", "eustackprogression"])
    assert result.exit_code == 0, result.output
    assert "changed signature" in result.output

    text = (case_dir / "eustack" / "eustack_report.md").read_text(encoding="utf-8")
    assert "## Progression" in text
    assert "CDSSQueryEngine::WaitUntilFinished" in text
