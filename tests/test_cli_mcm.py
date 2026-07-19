"""``sift mcm`` CLI integration tests (MCM-05, D-10, ADR 0007 exit codes).

RED half: pins the executable contract for the yet-to-exist ``mcm`` command —
it ALWAYS writes ``<case>/mcm/mcm_report.md`` (or ``.json`` with ``--format
json``) AND ``<case>/mcm/mcm_attribution.csv`` (D-10), prints a short stdout
summary, and is byte-identical on re-run. Cases are built network-free by
ingesting a Hartford dsserrors fixture straight into ``case.db`` (mirrors the
test_mcm ingest helper); the conftest network guard + dir-isolation are autouse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.cli import app
from sift.config import load_config
from sift.store import CaseStore, case_db_path

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"


def _build_mcm_case(
    case: str = "hartford", rel: str = "hartford_deny_predenial_multisid.log"
) -> Path:
    """Ingest a Hartford dsserrors fixture into a real ``case.db`` (no network).

    Returns the case directory (``<data_dir>/cases/<case>/``) so tests can assert
    the ``<case>/mcm/`` bundle written beside it.
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
    finally:
        store.close()
    return db_path.parent


def test_mcm_writes_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-10: ``sift mcm <case>`` exits 0, writes the Markdown report + the CSV
    under ``<case>/mcm/`` and prints an episode count + top-flag summary."""
    case_dir = _build_mcm_case()
    result = runner.invoke(app, ["mcm", "hartford"])
    assert result.exit_code == 0, result.output
    assert (case_dir / "mcm" / "mcm_report.md").exists()
    assert (case_dir / "mcm" / "mcm_attribution.csv").exists()
    # Summary names the episode count.
    assert "1" in result.output
    assert "episode" in result.output.lower()


def test_mcm_format_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--format json`` writes ``mcm_report.json`` (not ``.md``); an unknown
    ``--format`` is a Typer usage error (exit 2)."""
    case_dir = _build_mcm_case()
    result = runner.invoke(app, ["mcm", "hartford", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert (case_dir / "mcm" / "mcm_report.json").exists()
    assert not (case_dir / "mcm" / "mcm_report.md").exists()
    # The CSV is written regardless of report format (D-10).
    assert (case_dir / "mcm" / "mcm_attribution.csv").exists()

    bad = runner.invoke(app, ["mcm", "hartford", "--format", "xml"])
    assert bad.exit_code == 2


def test_mcm_determinism(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two runs produce byte-identical report + CSV (no model involved)."""
    case_dir = _build_mcm_case()
    runner.invoke(app, ["mcm", "hartford"])
    report1 = (case_dir / "mcm" / "mcm_report.md").read_bytes()
    csv1 = (case_dir / "mcm" / "mcm_attribution.csv").read_bytes()
    runner.invoke(app, ["mcm", "hartford"])
    assert (case_dir / "mcm" / "mcm_report.md").read_bytes() == report1
    assert (case_dir / "mcm" / "mcm_attribution.csv").read_bytes() == csv1


def test_mcm_empty_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """A case with no dsserrors/MCM episodes exits 0, writes a valid empty
    bundle and reports zero episodes."""
    db_path = case_db_path(load_config().data_dir, "empty")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    CaseStore(db_path).close()
    result = runner.invoke(app, ["mcm", "empty"])
    assert result.exit_code == 0, result.output
    assert (db_path.parent / "mcm" / "mcm_report.md").exists()
    assert (db_path.parent / "mcm" / "mcm_attribution.csv").exists()
    assert "0" in result.output


def test_mcm_missing_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown case exits 1 with a helpful message (no traceback)."""
    result = runner.invoke(app, ["mcm", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_mcm_no_threshold_or_window_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-12/D-13: there is no per-run threshold or lead-up-window CLI knob."""
    help_result = runner.invoke(app, ["mcm", "--help"])
    assert help_result.exit_code == 0
    assert "--threshold" not in help_result.output
    assert "--window" not in help_result.output
