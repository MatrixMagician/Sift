"""``run_validate`` branch tests — recording one immutable verdict (S01, D003).

ADR 0019: these call ``run_validate`` directly against an open ``CaseStore``.
None of the branches here is the CLI's — an unknown target and a locked
database are both decided inside the body, after ``parse_target`` has already
succeeded and the store is already open, and the append-only history contract
is the store's. What stays in ``tests/test_cli_validate.py`` is the part the
CLI can get independently wrong: the "exactly one verdict flag" check
(``cli.py``), the malformed-spec exit 2 that must fire *before* the store
opens, and the absent-case exit 1 from ``open_case``.

The verdict target is spelled as the operator spells it and parsed with
``parse_target`` — a domain identifier, not a flag, which is why it stays in
``verdicts.py`` rather than moving to ``commands/parse.py`` (CONTEXT.md, *Flag
parsing / domain-identifier parsing*). The command seam therefore takes an
already-parsed ``TargetSpec``, and the test builds one the same way both
adapters do.
"""

from __future__ import annotations

import sqlite3
from functools import partial

import pytest
from _validate_fixtures import (
    CASE,
    CLUSTER_ID,
    E3,
    HYP_TITLE,
    TID_A,
    build_case,
    verdicts,
)

from sift.commands import ExitCode, run_validate
from sift.config import load_config
from sift.store import CaseStore, StoredHypothesis, case_db_path, open_case
from sift.verdicts import parse_target


def _validate(
    target: str, verdict: str, *, note: str = ""
) -> tuple[ExitCode, list[str]]:
    """Open the case, record one verdict, close; return the code and stdout."""
    store = open_case(load_config().data_dir, CASE)
    out: list[str] = []
    try:
        code = run_validate(
            store,
            case=CASE,
            spec=parse_target(target),
            verdict=verdict,
            note=note,
            echo=out.append,
        )
    finally:
        store.close()
    return code, out


# --- success paths --------------------------------------------------------


def test_validate_cluster_and_template_targets() -> None:
    build_case()
    code, _out = _validate(f"cluster:{CLUSTER_ID}", "rejected")
    assert code is ExitCode.SUCCESS
    code, out = _validate(f"template:{TID_A}", "uncertain")
    assert code is ExitCode.SUCCESS
    # The canonical target is echoed back on the one scriptable stdout line.
    assert any(f"template:{TID_A}" in line for line in out), out
    rows = verdicts()
    assert {(v.target_type, v.target_id) for v in rows} == {
        ("cluster", str(CLUSTER_ID)),
        ("template", TID_A),
    }


def test_validate_history_survives_reanalysis() -> None:
    # The append-only contract: a recorded verdict outlives replace_hypotheses
    # (a re-run of analyze) and later verdicts accumulate as history rather
    # than replacing it.
    build_case()
    first, _out = _validate("hypothesis:0", "confirmed")
    assert first is ExitCode.SUCCESS
    store = CaseStore(case_db_path(load_config().data_dir, CASE))
    try:
        store.replace_hypotheses(
            [
                StoredHypothesis(
                    hyp_index=0,
                    title="Pool exhaustion",
                    narrative="Fresh analysis after new evidence.",
                    confidence="medium",
                    confidence_reasoning="Second run.",
                    supporting_event_ids=[E3.event_id],
                    contradicting_evidence=None,
                    suggested_next_steps=[],
                    citations_valid=True,
                )
            ]
        )
    finally:
        store.close()
    second, _out = _validate("hypothesis:0", "rejected")
    assert second is ExitCode.SUCCESS
    # list_verdicts orders newest first (created_at DESC, rowid DESC).
    rows = verdicts()
    assert [v.verdict for v in rows] == ["rejected", "confirmed"]
    # Each verdict's snapshot still shows the hypothesis it actually judged.
    assert rows[0].context["title"] == "Pool exhaustion"
    assert rows[1].context["title"] == HYP_TITLE


# --- semantic failures (exit 1) -------------------------------------------


@pytest.mark.parametrize(
    "spec", ["hypothesis:99", "cluster:99", "template:deadbeefdeadbeef"]
)
def test_validate_unknown_target_exits_one(spec: str) -> None:
    # Well-formed but absent in THIS case: a failure, not a usage error — the
    # spec parsed cleanly, so only the store could reject it.
    build_case()
    code, out = _validate(spec, "confirmed")
    assert code is ExitCode.ERROR
    assert any(line.startswith("Error:") for line in out), out
    assert verdicts() == []


def test_validate_locked_db_exits_one_no_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A GENUINELY locked database (the slice proof level): a second connection
    # holds an EXCLUSIVE transaction while the body tries to record. The only
    # concession to test speed is a short busy timeout on sqlite3.connect —
    # the store itself is entirely real.
    build_case()
    db_path = case_db_path(load_config().data_dir, CASE)
    lock = sqlite3.connect(db_path)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(
            "sift.store.sqlite3.connect", partial(sqlite3.connect, timeout=0.2)
        )
        # WR-02: the sqlite3.OperationalError is mapped to a clean sanitised
        # line and an exit code. Were it to escape instead, it would propagate
        # out of this call and fail the test as a traceback of its own.
        code, out = _validate("hypothesis:0", "confirmed")
        assert code is ExitCode.ERROR
        assert any("locked" in line.lower() for line in out), out
        assert any(f"case {CASE!r}" in line for line in out), out
    finally:
        lock.rollback()
        lock.close()
    assert verdicts() == []
