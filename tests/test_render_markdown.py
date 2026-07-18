"""Markdown renderer tests (REPT-01): D-05 sections, anchor links, appendix.

Every case.db is built network-free via ``_report_fixtures.build_analysed_case``.
"""

from __future__ import annotations

import pytest

from sift.render.markdown import render_markdown
from _report_fixtures import (
    MISSING_ID,
    REAL_ID,
    REAL_RAW,
    TIMELINE_SUMMARY,
    build_analysed_case,
    open_case,
)

_SECTIONS = [
    "Executive summary",
    "Ranked hypotheses",
    "Evidence appendix",
    "Cluster inventory",
    "Timeline",
    "Unexplained signals",
    "Run metadata",
]


def _render(monkeypatch: pytest.MonkeyPatch, *, degraded: bool = False) -> str:
    case = build_analysed_case(monkeypatch, degraded=degraded)
    store = open_case(case)
    try:
        return render_markdown(store)
    finally:
        store.close()


def test_report_contains_every_d05_section(monkeypatch: pytest.MonkeyPatch) -> None:
    md = _render(monkeypatch)
    for heading in _SECTIONS:
        assert heading in md, heading


def test_in_appendix_cited_id_becomes_anchor_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _render(monkeypatch)
    # The narrative token for a stored, cited id is rewritten to an anchor link…
    assert f"[evt:{REAL_ID}](#evt-{REAL_ID})" in md
    # …and the appendix entry carries the explicit target anchor.
    assert f'<a id="evt-{REAL_ID}"></a>' in md


def test_cited_id_not_in_store_stays_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _render(monkeypatch)
    # A cited-but-absent id is never turned into a dangling link (Pitfall 2).
    assert f"[evt:{MISSING_ID}]" in md
    assert f"[evt:{MISSING_ID}](#evt-{MISSING_ID})" not in md
    assert f'<a id="evt-{MISSING_ID}"></a>' not in md


def test_appendix_shows_provenance_and_fenced_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _render(monkeypatch)
    # file:line provenance for the cited stored event.
    assert "case.log:1-1" in md
    # raw text present and fenced.
    assert REAL_RAW in md
    assert "```" in md


def test_appendix_truncates_oversized_raw_with_elision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sift.models import Event, event_id
    from sift.render.markdown import _RAW_BYTE_CAP
    from sift.store import StoredHypothesis

    case = build_analysed_case(monkeypatch)
    big_id = event_id("big.log", 0)
    big_raw = "X" * (_RAW_BYTE_CAP + 500)
    store = open_case(case)
    try:
        with store.transaction():
            store.insert_events(
                [
                    Event(
                        event_id=big_id,
                        case_id="demo",
                        ts=None,
                        ts_confidence="missing",
                        source="genericlog",
                        source_file="big.log",
                        line_start=1,
                        line_end=1,
                        severity="error",
                        component=None,
                        thread=None,
                        session=None,
                        message="big",
                        attrs={},
                        raw=big_raw,
                    )
                ]
            )
            store.replace_hypotheses(
                [
                    StoredHypothesis(
                        hyp_index=0,
                        title="Oversized raw",
                        narrative=f"See [evt:{big_id}].",
                        confidence="low",
                        confidence_reasoning="n/a",
                        supporting_event_ids=[big_id],
                        contradicting_evidence=None,
                        suggested_next_steps=[],
                        citations_valid=True,
                    )
                ]
            )
        md = render_markdown(store)
    finally:
        store.close()
    assert "truncated" in md
    assert str(_RAW_BYTE_CAP) in md
    # The full oversized body is never emitted verbatim.
    assert big_raw not in md


def test_degraded_run_shows_banner_and_flagged_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _render(monkeypatch, degraded=True)
    assert "DEGRADED" in md
    assert "FLAGGED" in md
    # The OK hypothesis is still marked OK.
    assert "OK" in md
