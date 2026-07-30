"""``sift validate`` CLI tests (S01, ADR 0005/0007 exit codes).

Every exit-code branch runs against a real seeded ``case.db`` through
Typer's CliRunner — no store mocks anywhere (the slice proof level). The
locked-database branch holds a genuine EXCLUSIVE lock from a second
connection rather than faking the error.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from functools import partial

import pytest
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.store import (
    CaseStore,
    Cluster,
    StoredHypothesis,
    TemplateGroup,
    Verdict,
    case_db_path,
)

runner = CliRunner()

# Two messages sharing one masked template, one with a different shape —
# the same fixture geometry as tests/test_verdicts.py.
MSG_A1 = "Connection to 10.0.0.5 refused after 30 s"
MSG_A2 = "Connection to 10.9.9.9 refused after 45 s"
MSG_B = "Pool exhausted: 0 of 64 slots free"

TMPL_A = dedup.mask(MSG_A1)
TMPL_B = dedup.mask(MSG_B)
TID_A = dedup.template_id(TMPL_A)
TID_B = dedup.template_id(TMPL_B)


def _ev(source_file: str, offset: int, message: str) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id="valcase",
        ts=datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC),
        ts_confidence="exact",
        source="genericlog",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="error",
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw=message,
    )


E1 = _ev("a.log", 0, MSG_A1)
E2 = _ev("a.log", 100, MSG_A2)
E3 = _ev("b.log", 0, MSG_B)


def _build_case(case: str = "valcase") -> None:
    """A real case.db with events, template groups, one cluster, one
    hypothesis — everything the three target types resolve against."""
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        store.insert_events([E1, E2, E3])
        store.replace_template_groups(
            [
                TemplateGroup(
                    template_id=TID_A,
                    template=TMPL_A,
                    count=2,
                    first_ts="2026-07-16T10:00:00+00:00",
                    last_ts="2026-07-16T10:05:00+00:00",
                    severity_max="error",
                    exemplar_event_ids=[E1.event_id],
                ),
                TemplateGroup(
                    template_id=TID_B,
                    template=TMPL_B,
                    count=1,
                    first_ts=None,
                    last_ts=None,
                    severity_max="warn",
                    exemplar_event_ids=[E3.event_id],
                ),
            ]
        )
        store.replace_clusters(
            [
                Cluster(
                    cluster_id=3,
                    label=None,
                    signature="connection-refused",
                    severity_max="error",
                    count=2,
                    template_ids=[TID_A, TID_B],
                )
            ]
        )
        store.replace_hypotheses(
            [
                StoredHypothesis(
                    hyp_index=0,
                    title="Network partition",
                    narrative="The firewall dropped the pool connections.",
                    confidence="high",
                    confidence_reasoning="All evidence agrees.",
                    supporting_event_ids=[E1.event_id, E2.event_id],
                    contradicting_evidence=None,
                    suggested_next_steps=["Check firewall rules"],
                    citations_valid=True,
                )
            ]
        )
        store.set_meta("triage_model", "qwen3:32b")
        store.set_meta("triage_prompt_hash", "abc123")
        store.set_meta("triage_created_at", "2026-07-30T10:00:00+00:00")
    finally:
        store.close()


def _verdicts(case: str = "valcase") -> list[Verdict]:
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        return store.list_verdicts()
    finally:
        store.close()


# --- success paths (exit 0) --------------------------------------------------


def test_validate_confirm_records_and_prints_id_and_target() -> None:
    _build_case()
    result = runner.invoke(
        app,
        [
            "validate",
            "valcase",
            "hypothesis:0",
            "--confirm",
            "--note",
            "Root cause confirmed on the customer call",
        ],
    )
    assert result.exit_code == 0, result.output
    (row,) = _verdicts()
    assert row.verdict == "confirmed"
    assert row.note == "Root cause confirmed on the customer call"
    assert row.context["title"] == "Network partition"
    # Scriptable stdout: the verdict_id and the canonical target both appear.
    assert row.verdict_id in result.output
    assert "hypothesis:0" in result.output


@pytest.mark.parametrize(
    ("flag", "state"),
    [
        ("--confirm", "confirmed"),
        ("--reject", "rejected"),
        ("--uncertain", "uncertain"),
    ],
)
def test_validate_each_flag_maps_to_its_state(flag: str, state: str) -> None:
    _build_case()
    result = runner.invoke(app, ["validate", "valcase", "hypothesis:0", flag])
    assert result.exit_code == 0, result.output
    (row,) = _verdicts()
    assert row.verdict == state
    assert row.note == ""


def test_validate_cluster_and_template_targets() -> None:
    _build_case()
    r_cluster = runner.invoke(app, ["validate", "valcase", "cluster:3", "--reject"])
    assert r_cluster.exit_code == 0, r_cluster.output
    r_template = runner.invoke(
        app, ["validate", "valcase", f"template:{TID_A}", "--uncertain"]
    )
    assert r_template.exit_code == 0, r_template.output
    assert f"template:{TID_A}" in r_template.output
    rows = _verdicts()
    assert {(v.target_type, v.target_id) for v in rows} == {
        ("cluster", "3"),
        ("template", TID_A),
    }


def test_validate_history_survives_reanalysis() -> None:
    # The append-only contract end-to-end: a verdict recorded through the CLI
    # outlives replace_hypotheses (a re-run of analyze) and later verdicts
    # accumulate as history rather than replacing it.
    _build_case()
    first = runner.invoke(app, ["validate", "valcase", "hypothesis:0", "--confirm"])
    assert first.exit_code == 0, first.output
    store = CaseStore(case_db_path(load_config().data_dir, "valcase"))
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
    second = runner.invoke(app, ["validate", "valcase", "hypothesis:0", "--reject"])
    assert second.exit_code == 0, second.output
    # list_verdicts orders newest first (created_at DESC, rowid DESC).
    rows = _verdicts()
    assert [v.verdict for v in rows] == ["rejected", "confirmed"]
    # Each verdict's snapshot still shows the hypothesis it actually judged.
    assert rows[0].context["title"] == "Pool exhaustion"
    assert rows[1].context["title"] == "Network partition"


# --- usage errors (exit 2) ---------------------------------------------------


def test_validate_no_verdict_flag_is_usage_error() -> None:
    _build_case()
    result = runner.invoke(app, ["validate", "valcase", "hypothesis:0"])
    assert result.exit_code == 2, result.output
    assert "exactly one of --confirm, --reject or --uncertain" in result.output
    assert _verdicts() == []


def test_validate_multiple_verdict_flags_is_usage_error() -> None:
    _build_case()
    result = runner.invoke(
        app, ["validate", "valcase", "hypothesis:0", "--confirm", "--reject"]
    )
    assert result.exit_code == 2, result.output
    assert "exactly one of --confirm, --reject or --uncertain" in result.output
    assert _verdicts() == []


@pytest.mark.parametrize("spec", ["0", "hyp:0", "hypothesis:", "cluster:x2"])
def test_validate_malformed_target_is_usage_error(spec: str) -> None:
    _build_case()
    result = runner.invoke(app, ["validate", "valcase", spec, "--confirm"])
    assert result.exit_code == 2, result.output
    assert "Error:" in result.output
    assert _verdicts() == []


def test_validate_malformed_target_names_valid_types() -> None:
    _build_case()
    result = runner.invoke(app, ["validate", "valcase", "hyp:0", "--confirm"])
    assert result.exit_code == 2, result.output
    assert "cluster, hypothesis, template" in result.output


# --- semantic failures (exit 1) ----------------------------------------------


@pytest.mark.parametrize(
    "spec", ["hypothesis:99", "cluster:99", "template:deadbeefdeadbeef"]
)
def test_validate_unknown_target_exits_one(spec: str) -> None:
    _build_case()
    result = runner.invoke(app, ["validate", "valcase", spec, "--confirm"])
    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert _verdicts() == []


def test_validate_absent_case_exits_one() -> None:
    result = runner.invoke(app, ["validate", "ghost", "hypothesis:0", "--confirm"])
    assert result.exit_code == 1, result.output
    assert "does not exist" in result.output


def test_validate_locked_db_exits_one_no_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A GENUINELY locked database (the slice proof level): a second connection
    # holds an EXCLUSIVE transaction while the CLI tries to record. The only
    # concession to test speed is a short busy timeout on sqlite3.connect —
    # the store itself is entirely real.
    _build_case()
    db_path = case_db_path(load_config().data_dir, "valcase")
    lock = sqlite3.connect(db_path)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(
            "sift.store.sqlite3.connect", partial(sqlite3.connect, timeout=0.2)
        )
        result = runner.invoke(
            app, ["validate", "valcase", "hypothesis:0", "--confirm"]
        )
        assert result.exit_code == 1, result.output
        # WR-02: a clean sanitised message, never a raw OperationalError.
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "locked" in result.output.lower()
    finally:
        lock.rollback()
        lock.close()
    assert _verdicts() == []
