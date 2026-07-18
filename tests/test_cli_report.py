"""`sift report` CLI tests (REPT-01, ADR 0007 exit codes).

Cases are built network-free via ``_report_fixtures.build_analysed_case``.
"""

from __future__ import annotations

import pytest
from _report_fixtures import REAL_ID, build_analysed_case
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.store import CaseStore, case_db_path

runner = CliRunner()


def test_report_md_prints_report_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch)
    result = runner.invoke(app, ["report", case])
    assert result.exit_code == 0, result.output
    assert "Executive summary" in result.output
    assert f"[evt:{REAL_ID}](#evt-{REAL_ID})" in result.output


def test_report_no_hypotheses_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # A case that exists but has no persisted hypotheses (analyze never ran).
    store = CaseStore(case_db_path(load_config().data_dir, "bare"))
    store.close()
    result = runner.invoke(app, ["report", "bare"])
    assert result.exit_code == 1
    assert "analyze" in result.output.lower()


def test_report_absent_case_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(app, ["report", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_report_bad_format_is_usage_exit_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_analysed_case(monkeypatch)
    result = runner.invoke(app, ["report", case, "--format", "xml"])
    assert result.exit_code == 2


def test_report_out_writes_file_and_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from pathlib import Path

    case = build_analysed_case(monkeypatch)
    out = Path(str(tmp_path)) / "report.md"
    result = runner.invoke(app, ["report", case, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").find("Executive summary") != -1
    assert result.output.strip() == ""


def test_report_out_write_failure_exits_one_no_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    # WR-01: an unwritable --out (missing parent directory) is a clean exit 1
    # with a helpful message (ADR 0007), never a raw OSError traceback.
    from pathlib import Path

    case = build_analysed_case(monkeypatch)
    out = Path(str(tmp_path)) / "no_such_dir" / "report.md"
    result = runner.invoke(app, ["report", case, "--out", str(out)])
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "cannot write report" in result.output


def test_report_degraded_case_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # Degradation is communicated by the banner, NOT the exit code (ADR 0007).
    case = build_analysed_case(monkeypatch, degraded=True)
    result = runner.invoke(app, ["report", case])
    assert result.exit_code == 0, result.output
    assert "DEGRADED" in result.output
