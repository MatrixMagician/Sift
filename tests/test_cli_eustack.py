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
from sift.models import Event
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
    events: list[Event] = []
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


# --- Mixed-format ingest and the processing-unit axis (ADR 0022) -------------


def _build_mixed_format_case(tmp_path: Path, case: str = "eustackmixed") -> Path:
    """A case holding a Solaris pstack capture and a gdb/Linux pstack capture,
    both selected by real adapter DETECTION rather than by a forced override.

    Going through ``adapters.detect`` is the point: it proves the sniff really
    recognises both spellings, which a direct ``EustackAdapter()`` call would
    assume rather than test.
    """
    from sift.adapters import detect

    gdb_text = (
        "Thread 7 (Thread 0x7f0d5c1f7700 (LWP 21875)):\n"
        "#0  0x00007f0d5e9a1234 in __lll_lock_wait () from /lib64/libpthread.so.0\n"
        "#1  0x0000000004b1a5c1 in MSynch::CriticalSectionImpl::Lock (this=0x55f1)"
        " at sync.cpp:91\n"
        "#2  0x0000000004a02133 in CDSSQueryEngine::AcquireConnection (c=0x0)"
        " at qe.cpp:12\n"
        "#3  0x0000000004a01977 in CDSSQueryEngineServer::ProcessRequest (r=0x0)"
        " at qe.cpp:44\n"
    )
    input_dir = tmp_path / "mixed"
    input_dir.mkdir()
    (input_dir / "gdb_dump.txt").write_text(gdb_text, encoding="utf-8")
    (input_dir / "pstack_solaris.txt").write_text(
        (FIXTURES / "pstack_solaris.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )

    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    events: list[Event] = []
    for name in ("gdb_dump.txt", "pstack_solaris.txt"):
        path = input_dir / name
        adapter = detect(path, name, {})
        assert adapter.name == "eustack", (
            f"{name} must be detected as a thread dump, not {adapter.name}"
        )
        adapter.input_root = input_dir  # pyright: ignore[reportAttributeAccessIssue]
        events.extend(adapter.parse(path, case))
    store = CaseStore(db_path)
    try:
        store.insert_events(events)
    finally:
        store.close()
    return db_path.parent


def test_eustack_reports_processing_units_across_dump_formats(
    tmp_path: Path,
) -> None:
    """End-to-end through the CLI: two dumps in two different pstack
    spellings, one report, one processing-unit table.

    Both grammars must feed one comparable signature space, which the
    progression table proves: it carries the union across dumps, with the gdb
    capture's Query Engine signature and the Solaris capture's own signatures
    all attributed to named queues.

    The processing-unit table itself stays scoped to the LAST dump (D-11 — the
    state being diagnosed, never a union), so this test asserts that scope
    rather than a summed figure. Getting this wrong in the other direction is
    exactly the sort of quiet cross-dump merge D-11 exists to prevent.
    """
    case_dir = _build_mixed_format_case(tmp_path)
    result = runner.invoke(app, ["eustack", "eustackmixed"])
    assert result.exit_code == 0, result.output

    report = (case_dir / "eustack" / "eustack_report.md").read_text(encoding="utf-8")
    assert "### Processing units" in report
    assert "Query Engine" in report
    # The report leads with the queue view, before the pool/lock follow-ups.
    assert report.index("### Processing units") < report.index("### Pool occupancy")
    # The lock site is reported by its enclosing application frame, never the
    # glibc leaf every contended futex passes through.
    assert "MSynch::CriticalSectionImpl::Lock" in report
    assert "__lll_lock_wait" not in report.split("### Pool occupancy")[0]

    result_json = runner.invoke(app, ["eustack", "eustackmixed", "--format", "json"])
    assert result_json.exit_code == 0, result_json.output
    doc = json.loads(
        (case_dir / "eustack" / "eustack_report.json").read_text(encoding="utf-8")
    )
    dumps = [d["source_file"] for d in doc["progression"]["dumps"]]
    assert dumps[-1] == "pstack_solaris.txt"

    pu_health = doc["saturation"]["pu_health"]
    rows = {r["pu_name"]: r for r in pu_health}
    query = rows["Query Engine"]
    # The last dump's own figures: 2 threads at a lock, 1 on the warehouse.
    assert query["blocked_on_lock_threads"] == 2
    assert query["blocked_on_external_threads"] == 1
    assert query["total_threads"] == 3
    # Every thread of that dump lands in exactly one row, unattributed included.
    last_dump_threads = doc["progression"]["dumps"][-1]["thread_count"]
    assert sum(r["total_threads"] for r in pu_health) == last_dump_threads

    # The gdb capture's threads are absent from the table above (D-11) but
    # present in the progression union, attributed by the gdb grammar — which
    # is what proves both grammars fed one comparable signature space.
    gdb_only = [
        s
        for s in doc["progression"]["signatures"]
        if s["counts"][0] > 0 and s["counts"][-1] == 0
    ]
    assert gdb_only, "the gdb dump is expected to carry signatures of its own"
    assert all(s["pu_name"] for s in gdb_only)


def test_eustack_csv_carries_processing_unit_columns_via_cli(
    tmp_path: Path,
) -> None:
    """The CSV an engineer pivots on gains the queue and the frame that named
    it, beside the role columns."""
    import csv

    case_dir = _build_mixed_format_case(tmp_path, "eustackmixedcsv")
    result = runner.invoke(app, ["eustack", "eustackmixedcsv"])
    assert result.exit_code == 0, result.output
    csv_path = case_dir / "eustack" / "eustack_signatures.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows
    assert "processing_unit" in rows[0]
    named = [r for r in rows if r["processing_unit"]]
    assert named
    for row in named:
        assert row["processing_unit_frame"]
