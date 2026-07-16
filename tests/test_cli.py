"""Walking-skeleton end-to-end test.

Deliberately RED at the end of plan 01-01: the CLI bodies are stubs that exit 1.
Plan 01-02 implements new/ingest/show and turns this green. Do not xfail/skip.
Plan 01-04 adds the CLI hardening tests (precedence, sanitisation, empty-input,
adapter overrides, tz wiring).
"""

import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift.adapters import REGISTRY
from sift.adapters.genericlog import GenericLogAdapter
from sift.cli import app

runner = CliRunner()

# Three ISO 8601 timestamped entries (mixed severities in the message text),
# with one indented continuation line under the second entry.
FIXTURE_LOG = (
    "2026-07-16T10:00:00+00:00 INFO service started\n"
    "2026-07-16T10:00:01+00:00 ERROR connection pool exhausted\n"
    "    at pool.acquire (worker thread 7)\n"
    "2026-07-16T10:00:02+00:00 WARN retrying with backoff\n"
)


def _make_case(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(FIXTURE_LOG, encoding="utf-8")
    return input_dir


def test_reingest_adds_zero_events(tmp_path: Path) -> None:
    input_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert result.exit_code == 0, result.output

    first = runner.invoke(app, ["ingest", "demo"])
    assert first.exit_code == 0, first.output
    assert "3 new" in first.output

    second = runner.invoke(app, ["ingest", "demo"])
    assert second.exit_code == 0, second.output
    assert "0 new" in second.output

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    event_ids = set(re.findall(r"\b[0-9a-f]{16}\b", shown.output))
    assert len(event_ids) == 3, "row count changed after re-ingest"


def test_walking_skeleton_happy_path(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(FIXTURE_LOG, encoding="utf-8")

    result = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert "app.log" in result.output
    assert re.search(r"\d+(?:\.\d+)?\s*%", result.output), (
        f"expected a coverage percentage in ingest output: {result.output!r}"
    )

    result = runner.invoke(app, ["show", "demo", "events"])
    assert result.exit_code == 0, result.output
    event_ids = set(re.findall(r"\b[0-9a-f]{16}\b", result.output))
    assert len(event_ids) == 3, (
        f"expected three 16-char hex event IDs, got {sorted(event_ids)}"
    )
    assert "connection pool exhausted" in result.output


# --- plan 01-04: CLI hardening -------------------------------------------


def test_data_dir_flag_beats_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-01 flags layer end-to-end: --data-dir wins over SIFT_DATA_DIR."""
    input_dir = _make_case(tmp_path)
    env_dir = tmp_path / "env-data"
    flag_dir = tmp_path / "flag-data"
    monkeypatch.setenv("SIFT_DATA_DIR", str(env_dir))

    result = runner.invoke(
        app,
        ["new", "demo", "--input", str(input_dir), "--data-dir", str(flag_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (flag_dir / "cases" / "demo" / "case.db").exists()
    assert not (env_dir / "cases" / "demo" / "case.db").exists()

    result = runner.invoke(app, ["ingest", "demo", "--data-dir", str(flag_dir)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app, ["show", "demo", "events", "--data-dir", str(flag_dir)]
    )
    assert result.exit_code == 0, result.output
    assert "connection pool exhausted" in result.output


def test_show_strips_terminal_escapes(tmp_path: Path) -> None:
    """T-04-01: an ESC byte in log content never reaches the terminal."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(
        "2026-07-16T10:00:00+00:00 ERROR \x1b[31mred alert\x1b[0m\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "\x1b" not in shown.output
    assert "red alert" in shown.output


def test_new_warns_but_creates_on_empty_input_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty-input"
    empty.mkdir()
    result = runner.invoke(app, ["new", "demo", "--input", str(empty)])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.output


def test_ingest_empty_input_dir_reports_zero_files_exit_0(tmp_path: Path) -> None:
    empty = tmp_path / "empty-input"
    empty.mkdir()
    assert runner.invoke(app, ["new", "demo", "--input", str(empty)]).exit_code == 0
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert "0 files" in result.output


def test_new_missing_input_dir_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["new", "demo", "--input", str(tmp_path / "does-not-exist")]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_unknown_adapter_name_fails_listing_registered(tmp_path: Path) -> None:
    input_dir = _make_case(tmp_path)
    result = runner.invoke(
        app,
        ["new", "demo", "--input", str(input_dir), "--adapter", "*.log=nope"],
    )
    assert result.exit_code != 0
    assert "genericlog" in result.output


def test_config_timezones_reach_adapter_and_events(tmp_path: Path) -> None:
    """D-05 wiring: config.timezones -> adapter.tz_overrides -> event UTC value."""
    cfg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        '[timezones]\n"node1/*" = "Europe/Berlin"\n', encoding="utf-8"
    )
    input_dir = tmp_path / "input"
    (input_dir / "node1").mkdir(parents=True)
    # Naive timestamp, January: Berlin is UTC+1, so 10:00 local == 09:00 UTC.
    (input_dir / "node1" / "app.log").write_text(
        "2026-01-15 10:00:00 INFO naive line under tz override\n", encoding="utf-8"
    )

    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output

    generic = REGISTRY["genericlog"]
    assert isinstance(generic, GenericLogAdapter)
    assert generic.tz_overrides == {"node1/*": "Europe/Berlin"}

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "2026-01-15T09:00:00+00:00" in shown.output
