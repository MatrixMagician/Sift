"""Processing-unit mapping and multi-format thread-dump grammars (ADR 0022).

Covers the second, orthogonal classification axis added from the
reverse-engineered MicroStrategy Support Utility, and the ``DumpGrammar``
table that lets the same analysis run over eu-stack, Solaris ``pstack`` and
gdb/Linux ``pstack`` captures.

The load-bearing tests here are the ones pinning the three deliberate
divergences from the utility (deepest-frame-wins attribution, no sentinel
bucket, rules in the versioned TOML) and the two measured facts that forced
them, because those are the claims that would silently rot if someone
"simplified" the matching later.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.adapters.eustack import EustackAdapter
from sift.adapters.threaddump import (
    GDB_PSTACK_GRAMMAR,
    SOLARIS_PSTACK_GRAMMAR,
    grammar_for_block,
    iter_frames,
    strip_call_arguments,
)
from sift.config import EustackThresholdsConfig
from sift.models import Event
from sift.pipeline.eustack import (
    PU_FINDING_NOTE,
    ThreadRoleRules,
    analyse_eustack,
    analyse_pu_health,
    analyse_saturation,
    attribute_pu,
    load_rules,
    signature_of,
)
from sift.pipeline.eustack_facts import render_eustack_facts
from sift.pipeline.eustack_progression import EustackBundle, analyse_eustack_bundle
from sift.pipeline.eustack_vocabulary import PROHIBITED_OWNERSHIP_TERMS
from sift.render.eustack_report import (
    render_eustack_json,
    render_eustack_markdown,
    write_eustack_signatures_csv,
)

FIXTURES = Path(__file__).parent / "fixtures" / "eustack"
_RULES, _RULES_HASH = load_rules()


def _parse(name: str) -> list[Event]:
    adapter = EustackAdapter()
    adapter.input_root = FIXTURES
    return list(adapter.parse(FIXTURES / name, "pu-case"))


def _bundle(name: str) -> EustackBundle:
    return analyse_eustack_bundle(
        _parse(name), _RULES, _RULES_HASH, EustackThresholdsConfig()
    )


# --------------------------------------------------- attribution semantics ---


def test_deepest_frame_wins_over_lowest_pu_index() -> None:
    """THE divergence from the utility, pinned in both directions.

    ``TaskMap::Lookup`` returns the LOWEST PU index appearing anywhere in the
    block, so a thread carrying a SQL Engine helper (PU 1) near the leaf and
    ``MSIEvaluationTask::Run`` (PU 8) at the dispatch frame is reported as SQL
    Engine. It is an Evaluation thread that called a SQL helper. Sift takes
    the deepest match instead; this test fails if anyone reverts to index
    order, including by accident via a file reorder.
    """
    signature = (
        "DFCBitVector::operator[](int) const",
        "CDSSSQLEngineServer::ResolveAllLevelHelper(int)",
        "CDSSMetricSlice::Populate(ICDSSCubeSlice*)",
        "MSIEvaluationTask::Run()",
        "MSIThread::Run()",
    )
    attribution = attribute_pu(signature, _RULES)
    assert attribution is not None
    assert attribution.name == "Evaluation"
    assert attribution.frame_index == 3
    # ...and the shallower SQL Engine frame really was a candidate, so the
    # assertion above is about precedence rather than about it never matching.
    shallow = attribute_pu(signature[:3], _RULES)
    assert shallow is not None
    assert shallow.name == "SQL Engine"


def test_deepest_frame_rule_holds_on_the_reference_capture() -> None:
    """The measurement behind the rule, recomputed rather than quoted.

    Three signatures in the committed reference capture carry both a SQL
    Engine and an Evaluation frame. Every one of them must resolve to
    Evaluation, and the SQL frame must genuinely be the shallower one — which
    is what makes the utility's index-order answer wrong rather than merely
    different.
    """
    analysis = analyse_eustack(
        _parse("reference_capture_derivative.txt"), _RULES, _RULES_HASH
    )
    overlaps = 0
    for group in analysis.signatures:
        sql = next(
            (i for i, f in enumerate(group.frames) if "CDSSSQLEngineServer" in f), None
        )
        evaluation = next(
            (i for i, f in enumerate(group.frames) if "MSIEvaluationTask::Run" in f),
            None,
        )
        if sql is None or evaluation is None:
            continue
        overlaps += 1
        assert sql < evaluation, "the SQL frame is expected to be the shallower one"
        assert group.pu is not None
        assert group.pu.name == "Evaluation"
    assert overlaps == 3, (
        "the reference capture is expected to carry exactly three "
        "SQL-Engine/Evaluation overlap signatures"
    )


def test_no_match_is_none_not_a_sentinel_bucket() -> None:
    """The utility collapses "no match" and "PU index out of range" into the
    same sentinel 10, so both render identically. Sift returns None for the
    former and has no bound at all for the latter, which is why an
    unattributed thread is its own reported row rather than a shared bucket.
    """
    assert attribute_pu(("start_thread", "__clone3"), _RULES) is None
    rows = analyse_pu_health(
        analyse_eustack(_parse("pstack_solaris.txt"), _RULES, _RULES_HASH)
    )
    unattributed = [r for r in rows if r.pu_name is None]
    assert len(unattributed) == 1
    assert unattributed[0].pu_index is None


def test_unresolvable_frames_are_never_attribution_candidates() -> None:
    """The role axis skips ``??`` and bare addresses as match candidates; the
    PU axis reuses the same predicate rather than growing its own idea of a
    resolvable frame."""
    assert attribute_pu(("??", "0x7f0000000001"), _RULES) is None


def test_pu_index_is_provenance_and_never_precedence() -> None:
    """``index`` traces a finding back to the utility's own numbering. If it
    were precedence, a rules file listing a high-index queue first would
    reorder outcomes; it must not."""
    reordered = _RULES.model_copy(update={"pu": tuple(reversed(_RULES.pu))})
    signature = ("CDSSSQLEngineServer::Foo()", "MSIEvaluationTask::Run()")
    as_shipped = attribute_pu(signature, _RULES)
    as_reordered = attribute_pu(signature, reordered)
    assert as_shipped is not None
    assert as_reordered is not None
    assert as_shipped.name == "Evaluation"
    assert as_reordered.name == "Evaluation"


def test_substring_matching_matches_the_utility() -> None:
    """One property deliberately KEPT from the utility: a signature hits as a
    substring, so ``CDSSSQLEngineServer`` matches
    ``CDSSSQLEngineServerImpl::Foo`` too. Fully-qualified patterns are what
    keep that safe."""
    attribution = attribute_pu(("CDSSSQLEngineServerImpl::Foo()",), _RULES)
    assert attribution is not None
    assert attribution.name == "SQL Engine"


# ------------------------------------------------------- rules file loading ---


def test_packaged_rules_carry_the_utilitys_nine_named_queues() -> None:
    """The utility's compiled-in table holds ten entries, the tenth being its
    "Not Yet Implemented" sentinel. Sift carries the nine real queues and
    represents the sentinel's job with None instead."""
    assert len(_RULES.pu) == 9
    assert [p.index for p in _RULES.pu] == list(range(9))
    assert {p.name for p in _RULES.pu} == {
        "Command PU",
        "SQL Engine",
        "Query Engine",
        "Analytical Engine",
        "Resolution",
        "Delivery(NCSPU)",
        "Browsing",
        "Document Data Preparation",
        "Evaluation",
    }
    for rule in _RULES.pu:
        assert rule.description.strip()
        assert rule.subsystem.strip()


def test_rules_file_without_pu_table_still_loads(tmp_path: Path) -> None:
    """A rules file written before this axis existed must keep working, with
    every signature reading unattributed rather than raising."""
    rules_path = tmp_path / "roles.toml"
    rules_path.write_text(
        '[meta]\nversion = 1\nvalidated_against = "none"\n', encoding="utf-8"
    )
    rules, _ = load_rules(str(rules_path))
    assert rules.pu == ()
    assert attribute_pu(("MSIDSSCommand::Process()",), rules) is None


@pytest.mark.parametrize(
    ("bad", "expected"),
    [
        (
            """
[meta]
version = 1
validated_against = "x"
[[pu]]
index = 0
name = "A"
subsystem = "a"
match = "contains"
pattern = 'Foo'
description = "d"
[[pu]]
index = 0
name = "A"
subsystem = "a"
match = "contains"
pattern = 'Foo'
description = "d"
""",
            "duplicate pu rule",
        ),
        (
            """
[meta]
version = 1
validated_against = "x"
[[pu]]
index = 0
name = "A"
subsystem = "a"
pattern = 'Foo'
description = "d"
[[pu]]
index = 1
name = "A"
subsystem = "a"
pattern = 'Bar'
description = "d"
""",
            "conflicting indices",
        ),
        (
            """
[meta]
version = 1
validated_against = "x"
[[pu]]
index = 0
name = "A"
subsystem = "a"
pattern = 'Foo'
description = "d"
[[pu]]
index = 0
name = "B"
subsystem = "a"
pattern = 'Bar'
description = "d"
""",
            "conflicting names",
        ),
        (
            """
[meta]
version = 1
validated_against = "x"
[[pu]]
index = 0
name = "A"
subsystem = "a"
pattern = 'Foo@@GLIBC_2.2.5'
description = "d"
""",
            "is not normalised",
        ),
    ],
)
def test_ambiguous_or_non_canonical_pu_rules_are_rejected(
    bad: str, expected: str, tmp_path: Path
) -> None:
    """Every one of these would otherwise make attribution depend on row
    order or on a build-specific symbol suffix, which is exactly what
    depth-wins matching and canonical patterns exist to prevent. They fail at
    load time, quoting the problem."""
    rules_path = tmp_path / "roles.toml"
    rules_path.write_text(bad, encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match=expected):
        load_rules(str(rules_path))


def test_two_patterns_may_share_one_queue(tmp_path: Path) -> None:
    """One queue legitimately has several dispatch frames; those aggregate
    into ONE reported row rather than being rejected as a duplicate."""
    rules = ThreadRoleRules.model_validate(
        {
            "meta": {"version": 1, "validated_against": "x"},
            "pu": [
                {
                    "index": 0,
                    "name": "Q",
                    "subsystem": "q",
                    "match": "contains",
                    "pattern": "AlphaTask::Run",
                    "description": "d",
                },
                {
                    "index": 0,
                    "name": "Q",
                    "subsystem": "q",
                    "match": "contains",
                    "pattern": "BetaTask::Run",
                    "description": "d",
                },
            ],
        }
    )
    analysis = analyse_eustack(
        _synthetic_events(tmp_path, ("AlphaTask::Run",), ("BetaTask::Run",)),
        rules,
        "hash",
    )
    rows = analyse_pu_health(analysis)
    assert [r.pu_name for r in rows] == ["Q"]
    assert rows[0].total_threads == 2
    assert rows[0].signature_count == 2


def _synthetic_events(tmp_path: Path, *signatures: tuple[str, ...]) -> list[Event]:
    """One eu-stack thread event per given frame tuple, built through the real
    adapter so the events are exactly the shape the analyser sees."""
    text = "".join(
        f"TID {1000 + i}:\n"
        + "".join(f"#{n}  0x000000000000000{n} {f}\n" for n, f in enumerate(frames))
        for i, frames in enumerate(signatures)
    )
    path = tmp_path / "synthetic.txt"
    path.write_text(text, encoding="utf-8")
    adapter = EustackAdapter()
    adapter.input_root = tmp_path
    return list(adapter.parse(path, "synthetic"))


# -------------------------------------------------------- health aggregation ---


def test_pu_health_crosses_the_two_axes() -> None:
    """The whole point of the axis: per queue, how many threads are at a lock,
    on a dependency, idle and running. Neither axis answers this alone."""
    rows = {
        r.pu_name: r
        for r in analyse_pu_health(
            analyse_eustack(_parse("pstack_solaris.txt"), _RULES, _RULES_HASH)
        )
    }
    query = rows["Query Engine"]
    assert query.total_threads == 3
    assert query.blocked_on_lock_threads == 2
    assert query.blocked_on_external_threads == 1
    assert query.blocked_threads == 3
    assert query.idle_threads == 0
    assert rows["Command PU"].idle_threads == 2
    assert rows["Evaluation"].idle_threads == 2


def test_pu_health_row_totals_reconcile_with_the_analysis() -> None:
    """Every thread lands in exactly one row: no thread double-counted across
    queues, none dropped. The unattributed row is what makes this hold."""
    analysis = analyse_eustack(
        _parse("reference_capture_derivative.txt"), _RULES, _RULES_HASH
    )
    rows = analyse_pu_health(analysis)
    assert sum(r.total_threads for r in rows) == analysis.total_threads
    assert sum(r.signature_count for r in rows) == analysis.total_signatures
    for row in rows:
        assert sum(row.threads_by_role.values()) == row.total_threads


def test_pu_rows_rank_trouble_above_size() -> None:
    """A queue with 4 000 healthy idle workers must not outrank one with a
    handful of threads stuck at a lock — this table exists to surface the
    queue in trouble."""
    rows = analyse_pu_health(
        analyse_eustack(_parse("pstack_solaris.txt"), _RULES, _RULES_HASH)
    )
    assert rows[0].pu_name == "Query Engine"
    assert rows[0].total_threads < sum(r.total_threads for r in rows[1:])


def test_pu_health_is_deterministic_and_empty_safe() -> None:
    analysis = analyse_eustack([], _RULES, _RULES_HASH)
    assert analyse_pu_health(analysis) == ()
    populated = analyse_eustack(
        _parse("reference_capture_derivative.txt"), _RULES, _RULES_HASH
    )
    assert analyse_pu_health(populated) == analyse_pu_health(populated)


def test_pu_lock_sites_agree_with_the_global_lock_table() -> None:
    """Both tables walk to the enclosing application frame using the same
    shipped helper, so they can never name different sites for the same
    threads."""
    saturation = analyse_saturation(
        analyse_eustack(_parse("pstack_solaris.txt"), _RULES, _RULES_HASH),
        EustackThresholdsConfig(),
    )
    per_pu = {
        (site.site, site.thread_count)
        for row in saturation.pu_health
        for site in row.lock_sites
    }
    global_sites = {(s.site, s.thread_count) for s in saturation.lock_sites}
    assert per_pu == global_sites


# --------------------------------------------------------------------- flags ---


def test_lock_blocked_flag_grades_only_lock_waits() -> None:
    saturation = analyse_saturation(
        analyse_eustack(_parse("pstack_solaris.txt"), _RULES, _RULES_HASH),
        EustackThresholdsConfig(),
    )
    pu_flags = [f for f in saturation.flags if f.dimension == "pu_lock_blocked_count"]
    assert len(pu_flags) == 1
    assert pu_flags[0].value == 2.0
    assert pu_flags[0].unit == "threads"
    assert "Query Engine" in pu_flags[0].message


def test_no_flag_grades_a_dependency_wait_share() -> None:
    """The measurement that rejected a blocked-share threshold: the healthy
    reference capture's Query Engine is 100% blocked-on-external, being
    threads waiting on the warehouse, so a graded share would report a
    problem on a healthy server. The figure is reported, never graded.
    """
    analysis = analyse_eustack(
        _parse("reference_capture_derivative.txt"), _RULES, _RULES_HASH
    )
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())
    query = next(r for r in saturation.pu_health if r.pu_name == "Query Engine")
    assert query.blocked_pct == 100.0
    assert query.blocked_on_external_threads == query.total_threads
    assert not [f for f in saturation.flags if f.dimension == "pu_lock_blocked_count"]
    assert all(f.severity == "info" or "unclassified" in f.dimension
               for f in saturation.flags)


def test_unattributed_row_is_reported_but_never_graded() -> None:
    """"The unattributed queue is 40% blocked" names nothing actionable, so it
    raises no flag — while still appearing in the table, where it says how
    much of the dump serves no queue this rules file names."""
    analysis = analyse_eustack(
        _parse("reference_capture_derivative.txt"), _RULES, _RULES_HASH
    )
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())
    assert any(r.pu_name is None for r in saturation.pu_health)
    for flag in saturation.flags:
        assert "unattributed" not in flag.message


# ------------------------------------------------------------------ grammars ---


def test_solaris_and_gdb_reach_the_same_conclusion_as_eu_stack() -> None:
    """The utility's own finding, re-proven here: only where a block starts
    and how the thread id is read are format-dependent. Identical logical
    stacks in three spellings must produce one signature and one attribution.
    """
    eu = (
        "TID 1:\n"
        "#0  0x0000000000000001 __lll_lock_wait\n"
        "#1  0x0000000000000002 MSynch::CriticalSectionImpl::Lock\n"
        "#2  0x0000000000000003 MSIDSSCommand::Process\n"
    )
    solaris = (
        "-----------------  lwp# 1 / thread# 1  -----------------\n"
        " 0000000000000001 __lll_lock_wait (0x1, 2) + a\n"
        " 0000000000000002 MSynch::CriticalSectionImpl::Lock (void) + 91\n"
        " 0000000000000003 MSIDSSCommand::Process (void*) + 7\n"
    )
    gdb = (
        "Thread 3 (Thread 0x7f0d5c1f7700 (LWP 1)):\n"
        "#0  0x0000000000000001 in __lll_lock_wait () from /lib64/libpthread.so.0\n"
        "#1  0x0000000000000002 in MSynch::CriticalSectionImpl::Lock (this=0x55f1)"
        " at sync.cpp:91\n"
        "#2  0x0000000000000003 in MSIDSSCommand::Process (ctx=0x0) at cmd.cpp:7\n"
    )
    signatures = {signature_of(text) for text in (eu, solaris, gdb)}
    assert len(signatures) == 1, signatures
    attribution = attribute_pu(signatures.pop(), _RULES)
    assert attribution is not None
    assert attribution.name == "Command PU"


def test_grammar_detection_and_thread_ids() -> None:
    """Solaris reports the lwp number and gdb the LWP rather than its own
    sequential thread number, because the kernel thread id is the one that
    correlates with other diagnostics."""
    solaris_block = (
        "-----------------  lwp# 41 / thread# 41  -----------------\n"
        " 0000000000000001 lwp_park (0, 0, 0) + a\n"
    )
    gdb_block = (
        "Thread 7 (Thread 0x7f0d5c1f7700 (LWP 21875)):\n"
        "#0  0x0000000000000001 in poll () from /lib64/libc.so.6\n"
    )
    assert grammar_for_block(solaris_block) is SOLARIS_PSTACK_GRAMMAR
    assert grammar_for_block(gdb_block) is GDB_PSTACK_GRAMMAR
    assert SOLARIS_PSTACK_GRAMMAR.match_header(solaris_block.splitlines()[0]) == "41"
    assert GDB_PSTACK_GRAMMAR.match_header(gdb_block.splitlines()[0]) == "21875"
    # gdb omits the LWP for a single-threaded target; the sequential number is
    # then the honest best available rather than nothing.
    assert GDB_PSTACK_GRAMMAR.match_header("Thread 1 (process 4242):") == "1"


def test_solaris_grammar_records_the_dump_format_and_timestamp() -> None:
    bundle = _bundle("pstack_solaris.txt")
    events = _parse("pstack_solaris.txt")
    threads = [e for e in events if e.thread is not None]
    assert len(threads) == 8
    assert {e.attrs["dump_format"] for e in threads} == {"solaris-pstack"}
    # The single dump-time header stamps every thread; no per-thread time is
    # invented.
    assert bundle.progression.dumps[0].ts_confidence == "exact"
    assert {e.ts for e in threads} == {threads[0].ts}
    # A preamble record was never opened by a grammar, so it carries no format.
    assert all("dump_format" not in e.attrs for e in events if e.thread is None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # gdb argument VALUES and Solaris argument words differ per thread, so
        # keeping them would give every thread its own signature.
        ("MSynch::EventImpl::Wait (this=0x55f1c0, ms=30)", "MSynch::EventImpl::Wait"),
        ("lwp_park (0, 0, 0)", "lwp_park"),
        ("Foo::Bar (std::pair<int, int>(1, 2))", "Foo::Bar"),
        ("Foo::Bar (void) const", "Foo::Bar"),
        # operator() would otherwise collapse to a bare "operator".
        ("std::function<void ()>::operator()", "std::function<void ()>::operator()"),
        ("plain_symbol", "plain_symbol"),
    ],
)
def test_argument_stripping_keeps_symbols_distinct(raw: str, expected: str) -> None:
    assert strip_call_arguments(raw) == expected


def test_eu_stack_keeps_its_demangled_type_signature() -> None:
    """Measured: dropping eu-stack type signatures collapses the reference
    capture from 93 signatures to 88, merging genuinely different overloads.
    The pstack grammars strip arguments, eu-stack must not."""
    block = "TID 1:\n#0  0x0001 Wait(unsigned int) const - libcastor.so f.cpp:1\n"
    frames = dict(iter_frames(block))
    assert frames[0] == "Wait(unsigned int) const"


def test_frame_index_is_a_position_not_a_printed_number() -> None:
    """Solaris prints no frame numbers at all, so a position is the only thing
    the three formats can agree on — and every consumer of ``frame_index`` is
    a position already."""
    block = (
        "-----------------  lwp# 5 / thread# 5  -----------------\n"
        " 0000000000000001 alpha (0) + a\n"
        " 0000000000000002 beta (0) + b\n"
    )
    assert list(iter_frames(block)) == [(0, "alpha"), (1, "beta")]


def test_prose_mentioning_a_thread_is_not_sniffed_as_a_dump(tmp_path: Path) -> None:
    """Both a header AND a frame line of the SAME grammar are required, so a
    log line mentioning "Thread 1 (worker)" or a prose TID cannot be mistaken
    for a capture."""
    decoy = tmp_path / "app.log"
    decoy.write_text(
        "2026-07-30 INFO Thread 1 (worker) started\n"
        "2026-07-30 INFO TID 42: handling request\n",
        encoding="utf-8",
    )
    adapter = EustackAdapter()
    adapter.input_root = tmp_path
    assert adapter.sniff(decoy) == 0.0


# ------------------------------------------------------------------- output ---


def test_report_leads_with_the_processing_unit_table() -> None:
    """The table answering "which queue is in trouble" comes before the ones
    answering the follow-ups."""
    markdown = render_eustack_markdown(_bundle("pstack_solaris.txt"))
    assert "### Processing units" in markdown
    assert markdown.index("### Processing units") < markdown.index("### Pool occupancy")
    assert markdown.index("### Processing units") < markdown.index("### Lock sites")
    assert "Query Engine" in markdown
    assert "(no processing unit)" in markdown


def test_report_never_claims_lock_ownership_on_the_pu_axis() -> None:
    """ADR 0015's permanent non-goal applies verbatim to this axis: eu-stack
    and pstack alike carry no monitor-ownership edges, so a queue can be
    reported as having threads waiting, never as holding anything.

    Word-boundary matching, the same convention the shipped gates in
    ``test_eustack_facts`` and ``test_eustack_report`` use — a bare substring
    test trips on the innocent "placeholder" in the prompt fragment.
    """
    bundle = _bundle("pstack_solaris.txt")
    markdown = render_eustack_markdown(bundle)
    facts, _ = render_eustack_facts(bundle, _parse("pstack_solaris.txt"))
    # Non-vacuity: this capture really does carry a lock finding on the PU
    # axis, so the assertions below are about restraint, not about emptiness.
    assert any(row.lock_sites for row in bundle.saturation.pu_health)
    assert "eu-stack processing unit" in facts
    for term in PROHIBITED_OWNERSHIP_TERMS:
        pattern = rf"\b{re.escape(term)}\b"
        assert re.search(pattern, markdown, re.IGNORECASE) is None, term
        assert re.search(pattern, facts, re.IGNORECASE) is None, term
    assert PU_FINDING_NOTE in markdown


def test_csv_carries_the_processing_unit_columns(tmp_path: Path) -> None:
    path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(_bundle("pstack_solaris.txt"), path)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert "processing_unit" in rows[0]
    assert "processing_unit_frame" in rows[0]
    named = [r for r in rows if r["processing_unit"]]
    assert named, "at least one signature is expected to carry a processing unit"
    for row in named:
        # The frame column is the evidence for the attribution, so it must
        # never be blank when a queue is named.
        assert row["processing_unit_frame"]


def test_json_and_facts_expose_the_axis_deterministically() -> None:
    bundle = _bundle("pstack_solaris.txt")
    events = _parse("pstack_solaris.txt")
    assert render_eustack_json(bundle) == render_eustack_json(bundle)
    first, first_ids = render_eustack_facts(bundle, events)
    second, second_ids = render_eustack_facts(bundle, events)
    assert first == second
    assert first_ids == second_ids
    assert "processing unit Query Engine" in first
    # Every emitted line is cited, and the returned set is exactly the printed
    # ids — the exemplar contract, unchanged by this axis.
    for line in first.splitlines():
        if "eu-stack processing unit" in line:
            assert line.startswith("[evt:")
    stored = {e.event_id for e in events}
    assert first_ids <= stored


def test_facts_report_lock_and_dependency_waits_separately() -> None:
    """A merged "N blocked" figure would let a model pick either explanation;
    the two are reported as distinct figures on the same line."""
    bundle = _bundle("pstack_solaris.txt")
    facts, _ = render_eustack_facts(bundle, _parse("pstack_solaris.txt"))
    line = next(
        ln for ln in facts.splitlines() if "processing unit Query Engine" in ln
    )
    assert "2 waiting at a lock site" in line
    assert "1 waiting on an external dependency" in line


@pytest.mark.parametrize(
    ("name", "text"),
    [
        # gdb omits the LWP for a single-threaded target. The parse loop reads
        # this happily via `match_header`, so detection must too — otherwise a
        # dump parses correctly under a forced override and is silently handed
        # to genericlog without one.
        (
            "single-threaded gdb core",
            "Thread 1 (process 4242):\n"
            "#0  0x0000000000000001 in MSIEvaluationTask::Run () at t.cpp:1\n",
        ),
        # CRLF: a capture copied through a Windows support workflow.
        (
            "CRLF Solaris pstack",
            "-----  lwp# 7 / thread# 7  -----\r\n"
            " 0000000000000001 MSIDSSCommand::Process (void) + a\r\n",
        ),
    ],
)
def test_sniff_accepts_every_shape_the_parser_reads(
    name: str, text: str, tmp_path: Path
) -> None:
    """Detection and parsing must recognise the same set of files.

    A shape the parser handles but the sniff rejects is the worst failure mode
    available here: the file is silently handed to genericlog, so it still
    ingests, still reports coverage, and produces no threads at all — a
    missing analysis rather than an error.
    """
    path = tmp_path / "dump.txt"
    path.write_text(text, encoding="utf-8")
    adapter = EustackAdapter()
    adapter.input_root = tmp_path
    assert adapter.sniff(path) >= 0.5, name
    threads = [e for e in adapter.parse(path, "case") if e.thread is not None]
    assert len(threads) == 1, name
    assert signature_of(threads[0].raw), name


def test_degenerate_dumps_never_raise(tmp_path: Path) -> None:
    """An empty file, a header with no frames, and a stack of nothing but
    unresolvable frames must all analyse to an honest empty-or-unattributed
    result rather than an exception \u2014 the analysis runs on whatever a
    customer actually captured.
    """
    cases = {
        "empty.txt": "",
        "noframes.txt": "TID 1:\n",
        # `??` and a bare address are eu-stack's own spellings of "no symbol
        # resolved here": a real stack from a stripped binary.
        "unresolved.txt": "TID 1:\n#0  0x1 ??\n#1  0x2 0x00007f00\n",
    }
    for name, text in cases.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        adapter = EustackAdapter()
        adapter.input_root = tmp_path
        events = list(adapter.parse(path, "case"))
        analysis = analyse_eustack(events, _RULES, _RULES_HASH)
        saturation = analyse_saturation(analysis, EustackThresholdsConfig())
        # No queue is ever named on evidence this thin.
        assert all(row.pu_name is None for row in saturation.pu_health), name
        assert analyse_pu_health(analysis) == saturation.pu_health, name

    # The unresolvable stack is reported as a symbols problem, not as a rules
    # problem — the D-07 split, still intact on the PU path.
    path = tmp_path / "unresolved.txt"
    adapter = EustackAdapter()
    adapter.input_root = tmp_path
    analysis = analyse_eustack(
        list(adapter.parse(path, "case")), _RULES, _RULES_HASH
    )
    assert analysis.unclassified[0].reason == "no-resolvable-frame"
    assert analysis.unclassified[0].pu is None


# --- Provenance: the rules match the utility they were recovered from -------

# Verbatim from the utility's compiled-in tables, verified byte-for-byte
# against MicroStrategy_Support_Util.dll v1.25 (the two parallel ten-entry
# std::vector<std::string> at 0x1800de808 and 0x1800de850). Transcribed here
# rather than read from the DLL at test time: the binary is not redistributable
# and is not in this repo, so a test that needed it would be unrunnable in CI.
#
# The pairing is positional in the binary, and the tenth entry
# ("Not Yet Implemented") is the utility's sentinel, which Sift represents as
# pu=None instead — see ADR 0022 divergence 2.
_UTILITY_PU_TABLE: tuple[tuple[int, str, str], ...] = (
    (0, "MSIDSSCommand::Process", "Command PU"),
    (1, "CDSSSQLEngineServer", "SQL Engine"),
    (2, "CDSSQueryEngineServer", "Query Engine"),
    (3, "CDSSAnalyticalEngineServer", "Analytical Engine"),
    (4, "DSSResolutionServerTask::Run", "Resolution"),
    (5, "DSSPersistResultTask::Run", "Delivery(NCSPU)"),
    (6, "DSSObjectServerTask::Run", "Browsing"),
    (7, "DSSDocumentDataPreparationTask::Run", "Document Data Preparation"),
    (8, "MSIEvaluationTask::Run", "Evaluation"),
)


def test_pu_rules_reproduce_the_utilitys_table_verbatim() -> None:
    """Every shipped ``[[pu]]`` row matches the utility's own table exactly:
    same index, same identifying symbol, same queue NAME byte-for-byte.

    Byte-exactness on the name is not pedantry. ``Delivery(NCSPU)`` carries no
    space before the parenthesis in the binary, and this test was written after
    a transcription introduced one — an engineer reading a Sift report and a
    utility report side by side would have seen two spellings and had to work
    out whether they meant the same queue.

    The index pairing matters for the same reason: ``index`` exists only to
    trace a finding back to the utility's numbering (ADR 0022 divergence 2), so
    an index paired with the wrong queue would silently break the one job it
    has.
    """
    by_pattern = {rule.pattern: rule for rule in _RULES.pu}
    assert len(by_pattern) == len(_UTILITY_PU_TABLE), (
        "the shipped rules carry a different number of distinct patterns than "
        "the utility's table"
    )
    for index, pattern, name in _UTILITY_PU_TABLE:
        rule = by_pattern.get(pattern)
        assert rule is not None, f"no [[pu]] row matches {pattern!r}"
        assert rule.index == index, pattern
        assert rule.name == name, pattern
        # `contains` is what makes the utility's substring semantics hold —
        # `exact` would silently stop matching CDSSSQLEngineServerImpl::Foo.
        assert rule.match == "contains", pattern


def test_utility_sentinel_is_not_a_queue() -> None:
    """The utility's tenth entry, "Not Yet Implemented", is its no-match
    sentinel and must never appear as a queue Sift can attribute a thread to.
    Shipping it as a row would recreate exactly the bucket ADR 0022's
    divergence 2 exists to remove."""
    assert all(rule.name != "Not Yet Implemented" for rule in _RULES.pu)
    assert all(rule.pattern != "Not Yet Implemented" for rule in _RULES.pu)
    # And nothing occupies index 9, the sentinel's position.
    assert all(rule.index != 9 for rule in _RULES.pu)
