"""``sift perfmon`` CLI integration tests (PERF-06).

Scaffold only. The ``perfmon`` command does not exist until plan 13-06, which
fills this file with the bundle, format, determinism and empty-case tests; no
test here may invoke it before then.

What this file ships now is the precondition for success criterion 5: a case
built from a perfmon CSV and NOTHING ELSE — no DSSErrors log, so no MCM
episodes — proving the "counters but no denials" shape the whole-file-trend path
must cope with actually exists and is buildable network-free.
"""

from __future__ import annotations

from pathlib import Path

from test_perfmon import FIXTURES, SLICE
from typer.testing import CliRunner

from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.config import load_config
from sift.store import CaseStore, case_db_path

runner = CliRunner()


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
