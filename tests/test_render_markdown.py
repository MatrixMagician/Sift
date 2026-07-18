"""Markdown renderer tests (REPT-01): D-05 sections, anchor links, appendix.

Every case.db is built network-free via ``_report_fixtures.build_analysed_case``.
"""

from __future__ import annotations

import pytest
from _report_fixtures import (
    MISSING_ID,
    REAL_ID,
    REAL_RAW,
    build_analysed_case,
    open_case,
)

from sift.render.markdown import render_markdown

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
    # WR-04: the token stays plain text but its brackets are now backslash-escaped
    # (inert Markdown), so it renders as literal text rather than a link.
    assert f"\\[evt:{MISSING_ID}\\]" in md
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
    from sift.render.markdown import RAW_BYTE_CAP
    from sift.store import StoredHypothesis

    case = build_analysed_case(monkeypatch)
    big_id = event_id("big.log", 0)
    big_raw = "X" * (RAW_BYTE_CAP + 500)
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
    assert str(RAW_BYTE_CAP) in md
    # The full oversized body is never emitted verbatim.
    assert big_raw not in md


def test_model_text_is_escaped_against_markdown_and_html_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WR-04: attacker-influenced title/narrative must not inject Markdown
    # structure or raw HTML (the PDF path turns raw HTML real). Escaping must
    # neutralise it while the legitimate [evt:] citation link still renders.
    from sift.store import StoredHypothesis

    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        with store.transaction():
            store.replace_hypotheses(
                [
                    StoredHypothesis(
                        hyp_index=0,
                        title="Pwned <img src=x> # Heading [evil](http://evil)",
                        narrative=(
                            "Injected <script>alert(1)</script> and a fake "
                            f"[link](http://evil), yet [evt:{REAL_ID}] still links."
                        ),
                        confidence="high",
                        confidence_reasoning="ok",
                        supporting_event_ids=[REAL_ID],
                        contradicting_evidence=None,
                        suggested_next_steps=[],
                        citations_valid=True,
                    )
                ]
            )
        md = render_markdown(store)
    finally:
        store.close()
    # Raw HTML is neutralised to entities (no live <img>/<script> reaches the PDF).
    assert "<img" not in md
    assert "<script>" not in md
    assert "&lt;img" in md
    # Injected Markdown heading / link syntax is backslash-escaped, not structural.
    assert "\\# Heading" in md
    assert "\\[evil\\]" in md
    # The genuine citation token is still rewritten to an anchor link.
    assert f"[evt:{REAL_ID}](#evt-{REAL_ID})" in md


def test_appendix_nonconforming_event_id_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WR-05: a tampered case.db could carry a cited event_id that is not the
    # sha256[:16] hex shape. It must not flow verbatim into a raw HTML id
    # attribute (attribute break-out / anchor spoofing) — render it inert.
    from sift.models import Event
    from sift.store import StoredHypothesis

    bad_id = '"><b>evil'  # not [0-9a-f]{16}
    case = build_analysed_case(monkeypatch)
    store = open_case(case)
    try:
        with store.transaction():
            store.insert_events(
                [
                    Event(
                        event_id=bad_id,
                        case_id="demo",
                        ts=None,
                        ts_confidence="missing",
                        source="genericlog",
                        source_file="x.log",
                        line_start=1,
                        line_end=1,
                        severity="error",
                        component=None,
                        thread=None,
                        session=None,
                        message="m",
                        attrs={},
                        raw="r",
                    )
                ]
            )
            store.replace_hypotheses(
                [
                    StoredHypothesis(
                        hyp_index=0,
                        title="tampered id",
                        narrative="see it",
                        confidence="low",
                        confidence_reasoning="n/a",
                        supporting_event_ids=[bad_id],
                        contradicting_evidence=None,
                        suggested_next_steps=[],
                        citations_valid=True,
                    )
                ]
            )
        md = render_markdown(store)
    finally:
        store.close()
    # No raw HTML anchor is emitted for the non-conforming id.
    assert f'id="evt-{bad_id}"' not in md
    assert '<a id="evt-"><b>' not in md
    assert "<b>evil" not in md  # the raw break-out never reaches the output


def test_degraded_run_shows_banner_and_flagged_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _render(monkeypatch, degraded=True)
    assert "DEGRADED" in md
    assert "FLAGGED" in md
    # The OK hypothesis is still marked OK.
    assert "OK" in md


def _render_with_raw(
    monkeypatch: pytest.MonkeyPatch, *, case: str, raw: str
) -> str:
    """Build a case whose sole cited event carries exactly ``raw`` and render it."""
    from sift.models import Event, event_id
    from sift.store import StoredHypothesis

    build_analysed_case(monkeypatch, case=case)
    eid = event_id("b.log", 0)
    store = open_case(case)
    try:
        with store.transaction():
            store.insert_events(
                [
                    Event(
                        event_id=eid,
                        case_id="demo",
                        ts=None,
                        ts_confidence="missing",
                        source="genericlog",
                        source_file="b.log",
                        line_start=1,
                        line_end=1,
                        severity="error",
                        component=None,
                        thread=None,
                        session=None,
                        message="m",
                        attrs={},
                        raw=raw,
                    )
                ]
            )
            store.replace_hypotheses(
                [
                    StoredHypothesis(
                        hyp_index=0,
                        title="raw boundary",
                        narrative=f"See [evt:{eid}].",
                        confidence="low",
                        confidence_reasoning="n/a",
                        supporting_event_ids=[eid],
                        contradicting_evidence=None,
                        suggested_next_steps=[],
                        citations_valid=True,
                    )
                ]
            )
        return render_markdown(store)
    finally:
        store.close()


def test_appendix_raw_truncation_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    from sift.render.markdown import RAW_BYTE_CAP

    at_cap = "Y" * RAW_BYTE_CAP  # ASCII → 1 byte per char
    over_cap = "Z" * (RAW_BYTE_CAP + 1)
    md_at = _render_with_raw(monkeypatch, case="atcap", raw=at_cap)
    md_over = _render_with_raw(monkeypatch, case="overcap", raw=over_cap)
    # Exactly at the cap: verbatim, no elision marker.
    assert at_cap in md_at
    assert "truncated" not in md_at
    # One byte over: elided, full body never emitted.
    assert "truncated" in md_over
    assert over_cap not in md_over
