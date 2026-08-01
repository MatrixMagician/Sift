"""``run_report`` branch tests — rendering a report from a case (REPT-01).

ADR 0019: an unwritable ``--out`` is decided inside the body. The path is a
``run_report`` parameter and the failure is an ``OSError`` caught there, so
nothing about it lives in the translation layer — Typer would forward any path
at all. What stays in ``tests/test_cli_report.py`` is the ``--format`` enum,
which genuinely is Typer's (an unknown value never reaches the body), and the
assembled stdout path.

Cases are built network-free via ``_report_fixtures.build_analysed_case``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _report_fixtures import build_analysed_case

from sift.commands import ExitCode, run_report
from sift.config import load_config
from sift.store import open_case


def _report(case: str, out: Path) -> tuple[ExitCode, list[str]]:
    """Render ``case`` to ``out``; return the code and the stdout sink."""
    store = open_case(load_config().data_dir, case)
    lines: list[str] = []
    try:
        code = run_report(store, out=out, echo=lines.append)
    finally:
        store.close()
    return code, lines


def test_report_out_write_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # WR-01/ADR 0007: an unwritable --out (missing parent directory) is a clean
    # exit 1 with a helpful message. The OSError is mapped rather than raised —
    # were it not, it would propagate out of this direct call and fail the test
    # as itself.
    case = build_analysed_case(monkeypatch)
    out = tmp_path / "no_such_dir" / "report.md"
    code, lines = _report(case, out)
    assert code is ExitCode.ERROR
    assert any("cannot write report" in line for line in lines), lines
    # Nothing half-written was left behind for an operator to mistake for one.
    assert not out.exists()
