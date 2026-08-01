"""Shared seeded case for the ``sift validate`` suites (S01, D003).

ADR 0019 split the validate tests across two files — ``test_cli_validate.py``
for what only the CLI can get wrong, ``test_commands_validate.py`` for
``run_validate``'s own branches — and both need the same real ``case.db``: one
cluster, two template groups, one hypothesis, so every target type resolves.
The builder lives here rather than in either file so the split did not fork it.

A plain helper module, not a conftest fixture (the ``_report_fixtures``
precedent): ``tests/conftest.py`` is owned by plan 01-01 and stays untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

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

CASE = "valcase"

# Two messages sharing one masked template, one with a different shape —
# the same fixture geometry as tests/test_verdicts.py.
MSG_A1 = "Connection to 10.0.0.5 refused after 30 s"
MSG_A2 = "Connection to 10.9.9.9 refused after 45 s"
MSG_B = "Pool exhausted: 0 of 64 slots free"

TMPL_A = dedup.mask(MSG_A1)
TMPL_B = dedup.mask(MSG_B)
TID_A = dedup.template_id(TMPL_A)
TID_B = dedup.template_id(TMPL_B)

CLUSTER_ID = 3

# The title of the hypothesis planted at index 0 — asserted on both sides of
# the split, so it is named here rather than spelled out twice.
HYP_TITLE = "Network partition"


def _ev(source_file: str, offset: int, message: str) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id=CASE,
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


def build_case() -> None:
    """A real case.db with events, template groups, one cluster, one
    hypothesis — everything the three target types resolve against."""
    store = CaseStore(case_db_path(load_config().data_dir, CASE))
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
                    cluster_id=CLUSTER_ID,
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
                    title=HYP_TITLE,
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


def verdicts() -> list[Verdict]:
    """Every verdict recorded against the built case, newest first."""
    store = CaseStore(case_db_path(load_config().data_dir, CASE))
    try:
        return store.list_verdicts()
    finally:
        store.close()
