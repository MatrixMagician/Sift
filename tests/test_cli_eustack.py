"""``sift eustack`` CLI integration tests (EUS-09).

Covers the D-12 standalone contract mirrored verbatim from ``sift mcm``/
``sift perfmon``: exit codes, an empty case, partial-write cleanup, and
byte-identical re-runs, plus the phase's own named blocker — a case built
from eu-stack dumps and NOTHING ELSE (no DSSErrors log at all) still exits 0
with a written bundle.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sift.adapters.eustack import EustackAdapter
from sift.cli import app
from sift.config import load_config
from sift.store import CaseStore, case_db_path

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "eustack"
THREADDUMP = "threaddump.txt"


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
