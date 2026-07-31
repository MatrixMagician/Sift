"""Direct tests for the four ``run_show_*`` bodies (ADR 0019 pass 2).

These assertions used to run ``new`` -> ``ingest`` -> ``show`` through
``CliRunner`` and then grep ``result.output``. What they were actually about is
what each ``run_show_*`` renders from a given case store, so they call the seam
with a list's ``append`` as the sink and assert on the lines. The store is
seeded directly rather than ingested: the adapter's mapping from log text to
events has its own tests, and threading it through here only made the fixture
harder to read.

``tests/test_cli.py`` keeps what is genuinely CLI: the end-to-end
new/ingest/show slice, target dispatch, the exit-2 filter boundary, the exit-1
corrupt-case path and the terminal-escape checks that prove hostile bytes never
reach a real terminal.
"""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sift.commands import (
    ExitCode,
    run_show_clusters,
    run_show_events,
    run_show_hypotheses,
    run_show_templates,
)
from sift.models import Event, event_id
from sift.store import (
    CaseStore,
    Cluster,
    StoredHypothesis,
    TemplateGroup,
    case_db_path,
)

_BASE = datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC)


def _ev(
    source_file: str, offset: int, severity: str, message: str, second: int
) -> Event:
    return Event(
        event_id=event_id(source_file, offset),
        case_id="demo",
        ts=_BASE.replace(second=second),
        ts_confidence="exact",
        source="genericlog",
        source_file=source_file,
        line_start=offset + 1,
        line_end=offset + 1,
        severity=severity,
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw=message,
    )


# Three app.log events at 10:00:00/01/02 plus one in a second file — enough to
# tell severity, file, limit and since filters apart from one another.
STARTED = _ev("app.log", 0, "info", "service started", 0)
EXHAUSTED = _ev("app.log", 100, "error", "connection pool exhausted", 1)
BACKOFF = _ev("app.log", 200, "warn", "retrying with backoff", 2)
ON_FIRE = _ev("other.log", 0, "error", "database on fire", 5)
EVENTS = [STARTED, EXHAUSTED, BACKOFF, ON_FIRE]


def _group(
    template: str, count: int, severity: str, exemplar: Event
) -> TemplateGroup:
    return TemplateGroup(
        # A template_id is 16 hex chars in production; the shape matters to the
        # rendered line, the exact digest does not.
        template_id=event_id(template, 0),
        template=template,
        count=count,
        first_ts=_BASE.isoformat(),
        last_ts=_BASE.replace(second=9).isoformat(),
        severity_max=severity,
        exemplar_event_ids=[exemplar.event_id],
    )


POOL_GROUP = _group("connection pool exhausted after <NUM> retries", 3, "error",
                    EXHAUSTED)
STARTED_GROUP = _group("service started", 1, "info", STARTED)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CaseStore]:
    """An open case store holding the four events and two template groups."""
    db_path = case_db_path(tmp_path, "demo")
    db_path.parent.mkdir(parents=True)
    opened = CaseStore(db_path)
    try:
        opened.insert_events(EVENTS)
        opened.replace_template_groups([POOL_GROUP, STARTED_GROUP])
        yield opened
    finally:
        opened.close()


# --- templates: the pre-cluster view (STORE-04) -------------------------------


def test_templates_render_id_count_severity_timestamps_and_exemplars(
    store: CaseStore,
) -> None:
    """Two lines per group: the summary row, then an indented exemplars row."""
    out: list[str] = []
    assert run_show_templates(store, echo=out.append) is ExitCode.SUCCESS
    assert len(out) == 4
    assert out[0].split() == [
        POOL_GROUP.template_id,
        "3",
        "error",
        POOL_GROUP.first_ts,
        POOL_GROUP.last_ts,
        *POOL_GROUP.template.split(),
    ]
    assert out[1] == f"    exemplars: {EXHAUSTED.event_id}"


def test_templates_order_by_count_desc_then_template_asc(
    store: CaseStore,
) -> None:
    """The tie-break is what makes the listing stable across runs (DET-01)."""
    store.replace_template_groups(
        [
            _group("gamma repeated event", 3, "info", STARTED),
            _group("beta thing done", 2, "info", STARTED),
            _group("alpha thing done", 2, "info", STARTED),
        ]
    )
    out: list[str] = []
    assert run_show_templates(store, echo=out.append) is ExitCode.SUCCESS
    rendered = "\n".join(out)
    assert (
        rendered.index("gamma repeated event")
        < rendered.index("alpha thing done")
        < rendered.index("beta thing done")
    ), rendered


def test_templates_missing_timestamps_render_as_a_dash(store: CaseStore) -> None:
    """A group whose events carry no timestamp still renders a full-width row
    rather than a ragged one."""
    store.replace_template_groups(
        [
            TemplateGroup(
                template_id=event_id("undated", 0),
                template="undated thing",
                count=1,
                first_ts=None,
                last_ts=None,
                severity_max="unknown",
                exemplar_event_ids=[STARTED.event_id],
            )
        ]
    )
    out: list[str] = []
    assert run_show_templates(store, echo=out.append) is ExitCode.SUCCESS
    assert out[0].split()[3:5] == ["-", "-"]


def test_templates_empty_table_renders_nothing_and_succeeds(
    store: CaseStore,
) -> None:
    store.replace_template_groups([])
    out: list[str] = []
    assert run_show_templates(store, echo=out.append) is ExitCode.SUCCESS
    assert out == []


def test_templates_tampered_non_list_exemplars_render_instead_of_crashing(
    store: CaseStore, tmp_path: Path
) -> None:
    """WR-01: a tampered non-array ``exemplar_event_ids`` JSON stays visible to
    the operator rather than crashing ``' '.join`` with a traceback.

    The tamper is applied through a second connection, exactly as a hostile
    party with the case.db would — the store has no API for writing invalid
    JSON, and it should not grow one.
    """
    tamper = sqlite3.connect(case_db_path(tmp_path, "demo"))
    try:
        tamper.execute(
            "UPDATE template_groups SET exemplar_event_ids = '\"hostile\"'"
        )
        tamper.commit()
    finally:
        tamper.close()
    out: list[str] = []
    assert run_show_templates(store, echo=out.append) is ExitCode.SUCCESS
    assert any("hostile" in line for line in out)


@pytest.mark.parametrize(
    "filters",
    [{"min-count": 2}, {"contains": "pool"}, {"severity": "error"}],
)
def test_templates_filters_scope_the_listing(
    store: CaseStore, filters: dict[str, str | int]
) -> None:
    out: list[str] = []
    assert (
        run_show_templates(store, filters=filters, echo=out.append)
        is ExitCode.SUCCESS
    )
    rendered = "\n".join(out)
    assert "connection pool exhausted" in rendered
    assert "service started" not in rendered


def test_templates_contains_is_a_literal_substring_not_a_like_pattern(
    store: CaseStore,
) -> None:
    """T-02-08: ``contains`` is an ``instr()`` substring, so a ``%`` is matched
    literally and matches nothing. Asserting the listing is EMPTY is the point
    — a run that merely excludes the other group would also pass under LIKE
    semantics, which is the behaviour this rules out."""
    out: list[str] = []
    assert (
        run_show_templates(
            store, filters={"contains": "connection%retries"}, echo=out.append
        )
        is ExitCode.SUCCESS
    )
    assert out == []


# --- clusters: the post-analyze view, falling back to templates (D-01) --------


def _cluster(cluster_id: int, label: str | None, count: int, severity: str) -> Cluster:
    return Cluster(
        cluster_id=cluster_id,
        label=label,
        signature=f"signature{cluster_id:04d}",
        severity_max=severity,
        count=count,
        template_ids=[POOL_GROUP.template_id],
    )


def test_clusters_render_the_label_when_one_exists(store: CaseStore) -> None:
    store.replace_clusters([_cluster(0, "Memory pressure", 5, "error")])
    out: list[str] = []
    assert run_show_clusters(store, echo=out.append) is ExitCode.SUCCESS
    assert out == ["0        5  error    Memory pressure"]


def test_clusters_fall_back_to_the_signature_when_unlabelled(
    store: CaseStore,
) -> None:
    """``--no-label`` leaves the label NULL; the signature is the stable,
    deterministic name shown in its place (D-01)."""
    store.replace_clusters([_cluster(0, None, 5, "error")])
    out: list[str] = []
    assert run_show_clusters(store, echo=out.append) is ExitCode.SUCCESS
    assert "signature0000" in out[0]


def test_clusters_order_by_count_desc_then_id_asc(store: CaseStore) -> None:
    store.replace_clusters(
        [
            _cluster(0, "small", 1, "info"),
            _cluster(2, "big second", 9, "error"),
            _cluster(1, "big first", 9, "error"),
        ]
    )
    out: list[str] = []
    assert run_show_clusters(store, echo=out.append) is ExitCode.SUCCESS
    assert [line.split()[0] for line in out] == ["1", "2", "0"]


def test_clusters_fall_back_to_template_groups_before_analyze(
    store: CaseStore,
) -> None:
    """An empty clusters table IS the pre-cluster state, so the template groups
    are rendered instead — the exemplars line is what distinguishes them."""
    out: list[str] = []
    assert run_show_clusters(store, echo=out.append) is ExitCode.SUCCESS
    assert any(line.startswith("    exemplars: ") for line in out)


def test_clusters_fallback_is_decided_on_the_unfiltered_table(
    store: CaseStore,
) -> None:
    """The load-bearing half of the fallback: once clusters exist, a filter that
    excludes every one of them renders an EMPTY clusters view. Deciding on the
    filtered table instead would silently revert to template groups and present
    pre-analyze data as though it were the analysis.

    The filter is chosen so the two views cannot look alike: ``severity=info``
    matches no cluster (the only one is ``error``) but does match a template
    group, so a fallback decided on the filtered table would render the
    ``service started`` group here instead of nothing.
    """
    store.replace_clusters([_cluster(0, "Memory pressure", 5, "error")])
    out: list[str] = []
    assert (
        run_show_clusters(store, filters={"severity": "info"}, echo=out.append)
        is ExitCode.SUCCESS
    )
    assert out == []


def test_clusters_on_a_wholly_empty_case_render_nothing(tmp_path: Path) -> None:
    """No clusters AND no template groups: the fallback fires and finds nothing
    to render. Zero events is a state to display, not an error."""
    db_path = case_db_path(tmp_path, "empty")
    db_path.parent.mkdir(parents=True)
    empty = CaseStore(db_path)
    try:
        out: list[str] = []
        assert run_show_clusters(empty, echo=out.append) is ExitCode.SUCCESS
        assert out == []
    finally:
        empty.close()


def test_clusters_filters_scope_the_listing(store: CaseStore) -> None:
    """``contains`` searches the SIGNATURE on the clusters table — the label is
    optional and may still be NULL."""
    store.replace_clusters(
        [_cluster(0, "Memory pressure", 5, "error"), _cluster(1, "Quiet", 1, "info")]
    )
    out: list[str] = []
    assert (
        run_show_clusters(store, filters={"severity": "error"}, echo=out.append)
        is ExitCode.SUCCESS
    )
    assert out == ["0        5  error    Memory pressure"]

    by_signature: list[str] = []
    assert (
        run_show_clusters(
            store, filters={"contains": "signature0001"}, echo=by_signature.append
        )
        is ExitCode.SUCCESS
    )
    assert [line.split()[0] for line in by_signature] == ["1"]


def test_clusters_warn_on_stderr_when_template_groups_are_stale(
    store: CaseStore,
) -> None:
    """WR-03: a crash between the event commit and the group rebuild is
    detectable — warn on stderr, still render on stdout."""
    out: list[str] = []
    err: list[str] = []
    assert store.get_meta("template_groups_stale") in (None, "0")
    assert (
        run_show_clusters(store, echo=out.append, echo_err=err.append)
        is ExitCode.SUCCESS
    )
    assert err == []

    store.set_meta("template_groups_stale", "1")
    out.clear()
    assert (
        run_show_clusters(store, echo=out.append, echo_err=err.append)
        is ExitCode.SUCCESS
    )
    assert len(err) == 1
    assert "stale" in err[0]
    assert "sift ingest" in err[0]
    assert out, "the groups still render alongside the warning"


# --- events -------------------------------------------------------------------


def test_events_render_every_column_in_store_order(store: CaseStore) -> None:
    """Order is ts (NULLs last), source_file, line_start — and the rendered ts
    is the stored string verbatim, which is what keeps the line byte-identical
    to the Phase 1 rendering."""
    out: list[str] = []
    assert run_show_events(store, echo=out.append) is ExitCode.SUCCESS
    assert out == [
        f"{e.event_id}  {e.ts.isoformat() if e.ts else '-'}  {e.severity:<7}  "
        f"{e.source_file}:{e.line_start}  {e.message}"
        for e in (STARTED, EXHAUSTED, BACKOFF, ON_FIRE)
    ]


def test_events_filter_severity(store: CaseStore) -> None:
    out: list[str] = []
    assert (
        run_show_events(store, filters={"severity": "error"}, echo=out.append)
        is ExitCode.SUCCESS
    )
    rendered = "\n".join(out)
    assert "connection pool exhausted" in rendered
    assert "database on fire" in rendered
    assert "service started" not in rendered


def test_events_filters_and_combine(store: CaseStore) -> None:
    """Two filters AND-combine (severity AND file) rather than widening."""
    out: list[str] = []
    assert (
        run_show_events(
            store, filters={"severity": "error", "file": "app"}, echo=out.append
        )
        is ExitCode.SUCCESS
    )
    assert [line.split()[0] for line in out] == [EXHAUSTED.event_id]


def test_events_filter_limit(store: CaseStore) -> None:
    out: list[str] = []
    assert (
        run_show_events(store, filters={"limit": 1}, echo=out.append)
        is ExitCode.SUCCESS
    )
    assert len(out) == 1


def test_events_filter_since_is_inclusive_of_its_own_second(
    store: CaseStore,
) -> None:
    """``since`` compares against the stored UTC isoformat string, so the value
    ``parse_filters`` produced must be normalised the same way — 10:00:01
    excludes only the 10:00:00 event."""
    out: list[str] = []
    assert (
        run_show_events(
            store,
            filters={"since": _BASE.replace(second=1).isoformat()},
            echo=out.append,
        )
        is ExitCode.SUCCESS
    )
    rendered = "\n".join(out)
    assert "service started" not in rendered
    assert "connection pool exhausted" in rendered
    assert "retrying with backoff" in rendered


def test_events_flatten_newlines_and_truncate_the_message(
    store: CaseStore, tmp_path: Path
) -> None:
    """A multi-line record (a stack trace) is ONE event, and its message is
    flattened to one line and cut at 120 characters for the listing.

    Both halves matter: an unflattened newline would forge an extra row in
    line-oriented output, and an untruncated one would push the columns off the
    screen. The raw text is untouched in the store — this is a render-time cut.
    """
    long_message = "boom\nat frame.one\n" + "x" * 200
    store.insert_events([_ev("trace.log", 900, "error", long_message, 7)])
    out: list[str] = []
    assert (
        run_show_events(store, filters={"file": "trace"}, echo=out.append)
        is ExitCode.SUCCESS
    )
    (line,) = out
    rendered = line.split("trace.log:901  ", 1)[1]
    assert rendered == ("boom at frame.one " + "x" * 200)[:120]
    assert "\n" not in line


def test_templates_flatten_newlines_and_truncate_the_template(
    store: CaseStore,
) -> None:
    """The same render-time cut on the template column, at 100 characters."""
    long_template = "pool\nexhausted " + "y" * 200
    store.replace_template_groups([_group(long_template, 1, "error", STARTED)])
    out: list[str] = []
    assert run_show_templates(store, echo=out.append) is ExitCode.SUCCESS
    assert out[0].endswith(("pool exhausted " + "y" * 200)[:100])
    assert "\n" not in out[0]


def test_events_empty_case_renders_nothing_and_succeeds(tmp_path: Path) -> None:
    db_path = case_db_path(tmp_path, "empty")
    db_path.parent.mkdir(parents=True)
    empty = CaseStore(db_path)
    try:
        out: list[str] = []
        assert run_show_events(empty, echo=out.append) is ExitCode.SUCCESS
        assert out == []
    finally:
        empty.close()


# --- hypotheses (RAG-02, WR-03) -----------------------------------------------


def _hyp(index: int, title: str, cited: list[str], *, valid: bool) -> StoredHypothesis:
    return StoredHypothesis(
        hyp_index=index,
        title=title,
        narrative="n",
        confidence="high",
        confidence_reasoning="r",
        supporting_event_ids=cited,
        contradicting_evidence=None,
        suggested_next_steps=[],
        citations_valid=valid,
    )


def test_hypotheses_render_marker_confidence_and_cited_ids(
    store: CaseStore,
) -> None:
    store.replace_hypotheses([_hyp(0, "Memory exhaustion likely", [STARTED.event_id],
                                   valid=True)])
    out: list[str] = []
    assert run_show_hypotheses(store, echo=out.append) is ExitCode.SUCCESS
    assert out == [
        "0  high    OK       Memory exhaustion likely",
        f"    cites: {STARTED.event_id}",
    ]


def test_hypotheses_flag_a_row_whose_citations_were_not_all_shown(
    store: CaseStore,
) -> None:
    """FLAGGED is how an invalid citation stays visible — nothing disappears
    silently, so the row is marked rather than dropped."""
    store.replace_hypotheses([_hyp(0, "Fabricated cause", ["deadbeefdeadbeef"],
                                   valid=False)])
    out: list[str] = []
    assert run_show_hypotheses(store, echo=out.append) is ExitCode.SUCCESS
    assert "FLAGGED" in out[0]
    assert "deadbeefdeadbeef" in out[1]


def test_hypotheses_strip_control_bytes_from_a_hostile_title(
    store: CaseStore,
) -> None:
    """WR-01 / T-04-03: a title is model-generated and attacker-controlled in a
    shared case.db, so the COMPLETE rendered line is sanitised — a C1 CSI byte
    and a bidi override are stripped, the printable text survives, and the
    title is cut at 100 characters like every other rendered field."""
    hostile = "clean\x9b31mRED‮" + "z" * 200
    store.replace_hypotheses([_hyp(0, hostile, [STARTED.event_id], valid=True)])
    out: list[str] = []
    assert run_show_hypotheses(store, echo=out.append) is ExitCode.SUCCESS
    assert "\x9b" not in out[0]
    assert "‮" not in out[0]
    assert out[0].endswith("clean31mRED" + "z" * (100 - len("clean\x9b31mRED‮")))


def test_hypotheses_warn_on_stderr_after_a_degraded_analyze(
    store: CaseStore,
) -> None:
    """The warning goes to stderr so stdout stays scriptable."""
    store.replace_hypotheses([_hyp(0, "Something", [STARTED.event_id], valid=True)])
    store.set_meta("triage_degraded", "1")
    out: list[str] = []
    err: list[str] = []
    assert (
        run_show_hypotheses(store, echo=out.append, echo_err=err.append)
        is ExitCode.SUCCESS
    )
    assert len(err) == 1
    assert "degraded" in err[0]
    assert out, "the hypotheses still render alongside the warning"


def test_hypotheses_empty_before_analyze_names_the_next_command(
    store: CaseStore,
) -> None:
    out: list[str] = []
    err: list[str] = []
    assert (
        run_show_hypotheses(store, echo=out.append, echo_err=err.append)
        is ExitCode.SUCCESS
    )
    assert out == ["No hypotheses yet; run 'sift analyze' first"]
    assert err == []


def test_hypotheses_empty_after_a_hard_degraded_run_does_not_claim_analyze_never_ran(
    store: CaseStore,
) -> None:
    """WR-03: zero schema-valid rows WITH ``triage_created_at`` set means analyze
    ran and degraded hard, persisting only raw output. Telling the operator to
    run analyze would be factually wrong, and would hide the raw output the
    report can still show."""
    store.set_meta("triage_created_at", "2026-07-16T10:00:00+00:00")
    out: list[str] = []
    err: list[str] = []
    assert (
        run_show_hypotheses(store, echo=out.append, echo_err=err.append)
        is ExitCode.SUCCESS
    )
    assert out == []
    assert len(err) == 1
    assert "sift report" in err[0]
