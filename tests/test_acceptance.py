"""M1 acceptance suite (SPEC.md §8).

Proves the milestone gate on a realistic fixture: new/ingest/show events work
end-to-end, parse coverage >= 99% (and strictly < 100%, so the metric cannot
pass vacuously), re-ingest is idempotent, and event_id is deterministic
across cases (identity is source_file + byte_offset only — never case_id).

Fixture builders stay local to this file; conftest.py is owned by plan 01-01.
"""

import gzip
import re
from pathlib import Path

from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.store import CaseStore, case_db_path

runner = CliRunner()

_COVERAGE_LINE = re.compile(
    r"^(?P<file>\S+)\s+coverage\s+(?P<pct>\d+(?:\.\d+)?)%\s+"
    r"(?P<events>\d+) events\s+(?P<new>\d+) new",
    re.MULTILINE,
)
_HEX_ID = re.compile(r"\b[0-9a-f]{16}\b")


def _build_fixture(input_dir: Path) -> None:
    """Write the acceptance fixture: one plain log, one gzipped log.

    app.log opens with a 2-line unparseable preamble whose byte size is well
    under 1% of the file — coverage is pinned strictly between 99% and 100%,
    so the >= 99% assertion cannot pass via a trivially clean file. The body
    is ~200 ISO 8601 lines across all five severity tokens, a handful of
    indented continuation lines, and one 12-line stack trace under a single
    timestamp (one event, per the nothing-disappears-silently invariant).
    """
    input_dir.mkdir(parents=True)
    lines: list[str] = [
        "=== support bundle collected from node-a ===\n",
        "collector: manual copy, no manifest\n",
    ]
    severities = ["FATAL", "ERROR", "WARN", "INFO", "DEBUG"]
    for i in range(200):
        ts = f"2026-07-16T08:{i // 60:02d}:{i % 60:02d}+00:00"
        lines.append(f"{ts} {severities[i % 5]} worker {i} processed batch\n")
        if i in (40, 90, 140):
            lines.append("    at queue.drain (worker thread)\n")
    lines.append("2026-07-16T08:05:00+00:00 ERROR unhandled exception in dispatcher\n")
    lines.extend(
        f"    at dispatch.frame_{n} (dispatcher.py:{100 + n})\n" for n in range(11)
    )
    (input_dir / "app.log").write_text("".join(lines), encoding="utf-8")

    svc = "".join(
        f"2026-07-16T09:00:{i:02d}+00:00 INFO svc heartbeat {i}\n" for i in range(10)
    )
    (input_dir / "svc.log.gz").write_bytes(gzip.compress(svc.encode("utf-8")))


def _new_and_ingest(input_dir: Path, case: str) -> str:
    result = runner.invoke(app, ["new", case, "--input", str(input_dir)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["ingest", case])
    assert result.exit_code == 0, result.output
    return result.output


def _event_ids(case: str) -> list[str]:
    """Read event_ids straight from the case store (bypasses the CLI)."""
    store = CaseStore(case_db_path(load_config({}).data_dir, case))
    try:
        return sorted(e.event_id for e in store.query_events())
    finally:
        store.close()


def test_acceptance_coverage_99(tmp_path: Path) -> None:
    """INGST-05 / M1: per-file coverage printed, >= 99% and (app.log) < 100%."""
    input_dir = tmp_path / "input"
    _build_fixture(input_dir)
    output = _new_and_ingest(input_dir, "acc")

    coverage = {
        m["file"]: float(m["pct"]) for m in _COVERAGE_LINE.finditer(output)
    }
    assert set(coverage) == {"app.log", "svc.log.gz"}, output
    assert all(pct >= 99.0 for pct in coverage.values()), coverage
    # Bounded: the preamble is real unparsed bytes, so the metric is not
    # vacuously 100% — proving coverage is actually computed.
    assert coverage["app.log"] < 100.0, coverage


def test_acceptance_idempotent_reingest(tmp_path: Path) -> None:
    """INGST-02 / M1: second ingest of the same snapshot adds zero events."""
    input_dir = tmp_path / "input"
    _build_fixture(input_dir)
    _new_and_ingest(input_dir, "acc")
    count_after_first = len(_event_ids("acc"))
    assert count_after_first > 200  # ~200 ISO lines + preamble + trace + gz

    second = runner.invoke(app, ["ingest", "acc"])
    assert second.exit_code == 0, second.output
    assert "Total: 0 new events" in second.output
    for m in _COVERAGE_LINE.finditer(second.output):
        assert m["new"] == "0", second.output

    assert len(_event_ids("acc")) == count_after_first


def test_acceptance_cross_case_determinism(tmp_path: Path) -> None:
    """event_id is source_file + byte_offset only: two cases, identical IDs."""
    input_dir = tmp_path / "input"
    _build_fixture(input_dir)
    _new_and_ingest(input_dir, "alpha")
    _new_and_ingest(input_dir, "beta")

    ids_alpha = _event_ids("alpha")
    ids_beta = _event_ids("beta")
    assert len(ids_alpha) > 0
    assert ids_alpha == ids_beta


def test_acceptance_show_events_renders_all(tmp_path: Path) -> None:
    """INGST-01 / M1: show events renders every fixture event with a hex ID."""
    input_dir = tmp_path / "input"
    _build_fixture(input_dir)
    _new_and_ingest(input_dir, "acc")
    stored = _event_ids("acc")

    shown = runner.invoke(app, ["show", "acc", "events"])
    assert shown.exit_code == 0, shown.output
    rendered = set(_HEX_ID.findall(shown.output))
    assert rendered == set(stored)
