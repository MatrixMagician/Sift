"""eu-stack thread-role classifier tests (EUS-01, EUS-02).

The tracer test proves the whole Phase 15 path on one thread: adapter frame
split -> normalisation -> signature -> packaged TOML load -> first-match-wins
classification. It uses an inline raw thread block, not the committed
``tests/fixtures/eustack/threaddump.txt`` — that fixture is a sanitised
synthetic capture with no MicroStrategy frames, so it cannot carry this proof.
"""

import importlib.resources
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.adapters.eustack import EustackAdapter
from sift.config import EustackThresholdsConfig
from sift.models import Event
from sift.pipeline import eustack as _eustack_module
from sift.pipeline.eustack import (
    LOCK_FINDING_NOTE,
    UNKNOWN_LOCK_SITE,
    EustackAnalysis,
    SaturationAnalysis,
    SignatureGroup,
    analyse_eustack,
    analyse_saturation,
    classify_signature,
    enclosing_application_frame,
    load_rules,
    normalise,
    signature_of,
)
from sift.pipeline.eustack_vocabulary import (
    PROHIBITED_OWNERSHIP_TERMS,
)

# Shared, not copied (D-08): _grade is imported here ONLY to independently
# recompute expected severity in test_every_flag_family_prints_value_beside_
# threshold — never to change how analyse_saturation() itself grades.
from sift.pipeline.mcm import _grade  # pyright: ignore[reportPrivateUsage]

FIXTURES = Path(__file__).parent / "fixtures" / "eustack"

# TID 4242: pthread_cond_timedwait@@GLIBC_2.3.2 (idle wait) ->
# Semaphore::SmartLock::WaitForResource -> MSIQTask::WaitForWork ->
# MSIQTask::GetNextPreferredJob (the classifying frame, #3) -> MSIThread::Run()
# (the enclosing thread-pool entry point). Classification reads Event.raw via
# signature_of(), never Event.message — the real captures the classifying
# frame sits 8-19 deep, past the CONDENSED_FRAMES = 5 message cap boundary;
# this shorter block proves the same raw-not-message path on frame 3.
_TRACER_THREAD_BLOCK = (
    "TID 4242:\n"
    "#0  0x00007f0000000001 pthread_cond_timedwait@@GLIBC_2.3.2\n"
    "#1  0x00007f0000000002 Semaphore::SmartLock::WaitForResource\n"
    "#2  0x00007f0000000003 MSIQTask::WaitForWork\n"
    "#3  0x00007f0000000004 MSIQTask::GetNextPreferredJob\n"
    "#4  0x00007f0000000005 MSIThread::Run()\n"
)


def test_tracer_thread_block_classifies_via_packaged_rules() -> None:
    signature = signature_of(_TRACER_THREAD_BLOCK)
    rules, content_hash = load_rules()
    result = classify_signature(signature, rules)
    assert result.role == "idle-parked"
    assert result.subsystem == "job-queue"
    assert result.pattern == "MSIQTask::GetNextPreferredJob"
    assert result.frame_index == 3
    assert len(content_hash) == 16


# ------------------------------------------------------------- normalise ---


# The reference capture carries these three symbols with a SINGLE `@` before
# the GLIBC version, not only the double-`@@` form CONTEXT.md D-05 is worded
# around (orchestrator-verified correction) — do not "fix" normalise() back
# to an `@@`-only split, or these three go build-brittle again.
def test_single_at_glibc_suffix_is_stripped() -> None:
    for symbol, expected in (
        ("clock_nanosleep@GLIBC_2.2.5", "clock_nanosleep"),
        ("cnd_timedwait@GLIBC_2.28", "cnd_timedwait"),
        ("pthread_rwlock_rdlock@GLIBC_2.2.5", "pthread_rwlock_rdlock"),
    ):
        assert normalise(symbol) == expected


def test_double_at_glibc_suffix_is_stripped() -> None:
    for symbol, expected in (
        ("pthread_cond_timedwait@@GLIBC_2.3.2", "pthread_cond_timedwait"),
        ("pthread_cond_wait@@GLIBC_2.3.2", "pthread_cond_wait"),
        ("__libc_start_main@@GLIBC_2.34", "__libc_start_main"),
    ):
        assert normalise(symbol) == expected


def test_lib_source_tail_is_stripped() -> None:
    assert (
        normalise("castor_worker_wait - libcastor.so worker.cpp:412")
        == "castor_worker_wait"
    )


def test_template_arguments_are_kept() -> None:
    symbol = "MTimer::Timer<Foo, Bar>::Run()"
    assert normalise(symbol) == symbol


def test_normalise_is_idempotent() -> None:
    for symbol in (
        "clock_nanosleep@GLIBC_2.2.5",
        "pthread_cond_timedwait@@GLIBC_2.3.2",
        "castor_worker_wait - libcastor.so worker.cpp:412",
        "MTimer::Timer<Foo, Bar>::Run()",
    ):
        once = normalise(symbol)
        assert normalise(once) == once


# --------------------------------------------------------------- loader ---

_META = '[meta]\nversion = 1\nvalidated_against = "test"\n'


def _write_rules(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rules.toml"
    path.write_text(_META + body, encoding="utf-8")
    return path


def test_unnormalised_pattern_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "blocked-on-external"\nsubsystem = "x"\n'
        "pattern = 'pthread_cond_timedwait@@GLIBC_2.3.2'\n",
    )
    with pytest.raises(ValidationError, match="pthread_cond_timedwait"):
        load_rules(str(path))


def test_single_at_pattern_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "blocked-on-external"\nsubsystem = "x"\n'
        "pattern = 'clock_nanosleep@GLIBC_2.2.5'\n",
    )
    with pytest.raises(ValidationError, match="clock_nanosleep"):
        load_rules(str(path))


def test_lib_tail_pattern_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "blocked-on-lock"\nsubsystem = "x"\n'
        "pattern = 'castor_worker_wait - libcastor.so worker.cpp:412'\n",
    )
    with pytest.raises(ValidationError, match="castor_worker_wait"):
        load_rules(str(path))


def test_empty_pattern_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "running"\nsubsystem = "x"\npattern = "   "\n',
    )
    with pytest.raises(ValidationError, match="empty"):
        load_rules(str(path))


def test_unclassified_is_illegal_as_a_rule_role(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "unclassified"\nsubsystem = "x"\npattern = "foo"\n',
    )
    with pytest.raises(ValidationError, match="unclassified"):
        load_rules(str(path))


def test_unknown_key_in_rule_table_is_a_loud_error_naming_the_key(
    tmp_path: Path,
) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrol = "running"\nsubsystem = "x"\npattern = "foo"\n',
    )
    with pytest.raises(ValidationError, match="rol"):
        load_rules(str(path))


def test_unknown_match_kind_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "running"\nsubsystem = "x"\nmatch = "regex"\n'
        'pattern = "foo"\n',
    )
    with pytest.raises(ValidationError, match="regex"):
        load_rules(str(path))


def test_duplicate_match_pattern_pair_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "running"\nsubsystem = "x"\nmatch = "contains"\n'
        'pattern = "foo"\n'
        '[[rule]]\nrole = "idle-parked"\nsubsystem = "y"\nmatch = "contains"\n'
        'pattern = "foo"\n',
    )
    with pytest.raises(ValidationError, match="duplicate rule"):
        load_rules(str(path))


def test_missing_subsystem_rejected_at_load(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "running"\npattern = "foo"\n',
    )
    with pytest.raises(ValidationError, match="subsystem"):
        load_rules(str(path))


def test_missing_validated_against_rejected_at_load(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text("[meta]\nversion = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="validated_against"):
        load_rules(str(path))


def test_malformed_rules_toml_is_a_loud_error_naming_the_source(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rules.toml"
    path.write_text("[meta\nversion = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match=str(path)):
        load_rules(str(path))


def test_missing_rules_path_does_not_fall_back_to_packaged_default(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist.toml"
    with pytest.raises(ValueError, match=str(missing)) as excinfo:
        load_rules(str(missing))
    # The failure must be the missing-file error, not a validated packaged
    # rules file mistakenly returned in its place.
    assert "not found" in str(excinfo.value)


def test_meta_only_rules_file_is_valid_with_no_rules(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(_META, encoding="utf-8")
    rules, _content_hash = load_rules(str(path))
    assert rules.rule == ()


def test_packaged_rules_file_is_importable_resource() -> None:
    assert (
        importlib.resources.files("sift.rules")
        .joinpath("eustack_roles.toml")
        .is_file()
    )


def test_rules_path_override_changes_classification(tmp_path: Path) -> None:
    """Success criterion 2: pointing rules_path at an edited copy changes a
    thread's role, with no Python edited and nothing reinstalled."""
    signature = signature_of(_TRACER_THREAD_BLOCK)
    packaged_rules, _ = load_rules()
    packaged_result = classify_signature(signature, packaged_rules)

    override_path = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "running"\nsubsystem = "compute"\nmatch = "contains"\n'
        'pattern = "MSIQTask::GetNextPreferredJob"\n',
    )
    override_rules, _ = load_rules(str(override_path))
    override_result = classify_signature(signature, override_rules)

    assert packaged_result.role != override_result.role
    assert override_result.role == "running"


def test_rule_order_is_the_precedence_knob(tmp_path: Path) -> None:
    signature = signature_of(_TRACER_THREAD_BLOCK)

    first_wins = _write_rules(
        tmp_path,
        '[[rule]]\nrole = "running"\nsubsystem = "a"\nmatch = "contains"\n'
        'pattern = "MSIQTask::GetNextPreferredJob"\n'
        '[[rule]]\nrole = "idle-parked"\nsubsystem = "b"\nmatch = "contains"\n'
        'pattern = "MSIQTask::WaitForWork"\n',
    )
    rules, _ = load_rules(str(first_wins))
    assert classify_signature(signature, rules).role == "running"

    second_wins = tmp_path / "reversed.toml"
    second_wins.write_text(
        _META
        + '[[rule]]\nrole = "idle-parked"\nsubsystem = "b"\nmatch = "contains"\n'
        'pattern = "MSIQTask::WaitForWork"\n'
        '[[rule]]\nrole = "running"\nsubsystem = "a"\nmatch = "contains"\n'
        'pattern = "MSIQTask::GetNextPreferredJob"\n',
        encoding="utf-8",
    )
    rules, _ = load_rules(str(second_wins))
    assert classify_signature(signature, rules).role == "idle-parked"


# ----------------------------------------------------------- analyse_eustack ---

_ALL_ROLE_KEYS = {
    "idle-parked",
    "blocked-on-external",
    "blocked-on-lock",
    "running",
    "unclassified",
}


def _thread_raw(*frames: str) -> str:
    """One synthetic ``TID N:`` block with the given (already-normalised)
    frame symbols, in the ``#N 0xADDR symbol`` shape ``iter_frames`` expects."""
    lines = ["TID 1:\n"]
    for index, frame in enumerate(frames):
        lines.append(f"#{index}  0x{index:016x} {frame}\n")
    return "".join(lines)


def _event(raw: str, thread: str | None) -> Event:
    """A minimal, otherwise-inert Event carrying only what analyse_eustack
    reads: `.raw` (signature source) and `.thread` (the is-a-thread marker)."""
    return Event(
        event_id="0" * 16,
        case_id="case",
        ts=None,
        ts_confidence="missing",
        source="eustack",
        source_file="dump.txt",
        line_start=1,
        line_end=1,
        severity="unknown",
        component=None,
        thread=thread,
        session=None,
        message="",
        attrs={},
        raw=raw,
    )


def _parse_derivative_fixture() -> list[Event]:
    adapter = EustackAdapter()
    return list(
        adapter.parse(FIXTURES / "reference_capture_derivative.txt", "case-1")
    )


def test_classification_partitions_all_threads() -> None:
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert set(analysis.threads_by_role) == _ALL_ROLE_KEYS
    assert set(analysis.signatures_by_role) == _ALL_ROLE_KEYS
    assert sum(analysis.threads_by_role.values()) == analysis.total_threads
    assert analysis.total_threads == sum(1 for e in events if e.thread is not None)


def test_unmatched_signature_reports_count_and_example() -> None:
    raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    events = [_event(raw, thread=str(i)) for i in range(3)]
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert len(analysis.unclassified) == 1
    group = analysis.unclassified[0]
    assert group.thread_count == 3
    assert group.frames == ("TotallyUnrecognisedApplicationFrame::Nobody",)
    assert group.role == "unclassified"
    assert group.pattern is None
    assert group.reason == "matched-no-rule"
    # Not folded into any known role.
    assert analysis.threads_by_role["idle-parked"] == 0
    assert analysis.threads_by_role["running"] == 0
    assert analysis.threads_by_role["blocked-on-external"] == 0
    assert analysis.threads_by_role["blocked-on-lock"] == 0
    assert analysis.threads_by_role["unclassified"] == 3


def test_all_unresolved_frames_is_distinct_category() -> None:
    unresolved_raw = _thread_raw("??", "??")
    matched_no_rule_raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    events = [
        _event(unresolved_raw, thread="1"),
        _event(matched_no_rule_raw, thread="2"),
    ]
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    reasons = {g.frames: g.reason for g in analysis.unclassified}
    assert reasons[("??", "??")] == "no-resolvable-frame"
    assert (
        reasons[("TotallyUnrecognisedApplicationFrame::Nobody",)] == "matched-no-rule"
    )
    unresolved_group = next(
        g for g in analysis.unclassified if g.reason == "no-resolvable-frame"
    )
    assert unresolved_group.frames == ("??", "??")


def test_unclassified_list_is_ranked_by_thread_count() -> None:
    small = _thread_raw("Alpha::Unrecognised")
    medium = _thread_raw("Bravo::Unrecognised")
    large = _thread_raw("Charlie::Unrecognised")
    events = (
        [_event(small, thread=f"s{i}") for i in range(1)]
        + [_event(medium, thread=f"m{i}") for i in range(3)]
        + [_event(large, thread=f"l{i}") for i in range(5)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert [g.thread_count for g in analysis.unclassified] == [5, 3, 1]
    assert len(analysis.unclassified) == 3  # full list, no cap


def test_equal_thread_counts_break_ties_on_frames_tuple() -> None:
    alpha = _thread_raw("Alpha::Unrecognised")
    bravo = _thread_raw("Bravo::Unrecognised")
    events = [
        _event(bravo, thread="b1"),
        _event(bravo, thread="b2"),
        _event(alpha, thread="a1"),
        _event(alpha, thread="a2"),
    ]
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert [g.frames for g in analysis.unclassified] == [
        ("Alpha::Unrecognised",),
        ("Bravo::Unrecognised",),
    ]


def test_classification_is_per_signature_not_per_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()

    real_classify = _eustack_module.classify_signature
    call_count = 0

    def counting_classify(
        signature: tuple[str, ...], rules: _eustack_module.ThreadRoleRules
    ) -> _eustack_module.Classification:
        nonlocal call_count
        call_count += 1
        return real_classify(signature, rules)

    monkeypatch.setattr(_eustack_module, "classify_signature", counting_classify)
    analysis = _eustack_module.analyse_eustack(events, rules, rules_hash)

    assert call_count == analysis.total_signatures
    assert call_count < analysis.total_threads  # strict: cap-5 signatures differ


def test_analysis_is_byte_identical_on_rerun() -> None:
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    first = analyse_eustack(events, rules, rules_hash).model_dump_json()
    second = analyse_eustack(events, rules, rules_hash).model_dump_json()
    assert first == second


def test_empty_event_list_yields_zero_analysis() -> None:
    rules, rules_hash = load_rules()
    analysis = analyse_eustack([], rules, rules_hash)

    assert analysis.total_threads == 0
    assert analysis.total_signatures == 0
    assert set(analysis.threads_by_role) == _ALL_ROLE_KEYS
    assert set(analysis.signatures_by_role) == _ALL_ROLE_KEYS
    assert all(v == 0 for v in analysis.threads_by_role.values())
    assert all(v == 0 for v in analysis.signatures_by_role.values())
    assert analysis.signatures == ()
    assert analysis.unclassified == ()


def test_preamble_events_are_excluded_from_counts() -> None:
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    assert analysis.total_threads < len(events)


# ---------------------------------------------------- 24-rule taxonomy ---


def test_reference_derivative_headline_signature() -> None:
    """EUS-01 criterion 4, CI half: the MSIQTask::GetNextPreferredJob
    population — the exact composition-blind false positive v1.3 exists to
    eliminate — reads idle-parked/job-queue at frame index 3, never a
    blocked role."""
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    group = next(
        g
        for g in analysis.signatures
        if any("MSIQTask::GetNextPreferredJob" in frame for frame in g.frames)
    )
    assert group.role == "idle-parked"
    assert group.subsystem == "job-queue"
    assert group.pattern == "MSIQTask::GetNextPreferredJob"
    assert group.frame_index == 3
    assert group.role != "blocked-on-external"
    assert group.role != "blocked-on-lock"


def test_running_rule_precedes_evaluation_ancestor_rule(tmp_path: Path) -> None:
    """D-01 ordering regression: a stack containing BOTH a running-rule frame
    and, deeper, the shared-ancestor MSIEvaluationTask::Run frame classifies
    running under the packaged order, and idle-parked under the reversed
    order — proving the packaged order is the cause, not a coincidence."""
    busy_raw = _thread_raw("_shi_allocBlock", "MSIEvaluationTask::Run")
    signature = signature_of(busy_raw)

    packaged_rules, _ = load_rules()
    packaged_result = classify_signature(signature, packaged_rules)
    assert packaged_result.role == "running"
    assert packaged_result.pattern == "_shi_allocBlock"

    reversed_path = tmp_path / "reversed.toml"
    reversed_path.write_text(
        _META
        + '[[rule]]\nrole = "idle-parked"\nsubsystem = "evaluation"\n'
        'match = "contains"\npattern = "MSIEvaluationTask::Run"\n'
        '[[rule]]\nrole = "running"\nsubsystem = "compute"\n'
        'match = "contains"\npattern = "_shi_allocBlock"\n',
        encoding="utf-8",
    )
    reversed_rules, _ = load_rules(str(reversed_path))
    reversed_result = classify_signature(signature, reversed_rules)
    assert reversed_result.role == "idle-parked"


def test_all_four_rule_roles_are_reachable() -> None:
    """blocked-on-lock matches zero threads in the healthy reference
    capture — without this test the whole role would ship unexercised."""
    rules, _ = load_rules()
    cases = {
        "running": _thread_raw("_shi_allocBlock"),
        "blocked-on-lock": _thread_raw("__lll_lock_wait"),
        "blocked-on-external": _thread_raw("curl_multi_poll"),
        "idle-parked": _thread_raw("MSIQTask::GetNextPreferredJob"),
    }
    for expected_role, raw in cases.items():
        result = classify_signature(signature_of(raw), rules)
        assert result.role == expected_role


def test_derivative_coverage_is_disclosed_not_inflated() -> None:
    """EUS-02 criterion 3: unclassified is non-empty, and a future catch-all
    rule that drives it to zero fails this test. Asserts a lower bound, not
    an exact count, so a later legitimate rule addition stays free to reduce
    the residual without rewriting this test."""
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert len(analysis.unclassified) > 0
    classified_frames = {
        g.frames for g in analysis.signatures if g.role != "unclassified"
    }
    unclassified_frames = {g.frames for g in analysis.unclassified}
    assert classified_frames.isdisjoint(unclassified_frames)


def test_ownership_blind_vocabulary_absent_from_source_and_emitted_output() -> None:
    """D-05: the three-term lock-ownership prohibition is asserted BOTH over
    shipped source text (the original Phase 15 half, byte-for-byte
    unchanged) AND over strings Phase 16 actually EMITS at runtime (S-7) —
    a behaviour assertion strictly stronger than a source grep. Renamed from
    test_no_ownership_attributed_lock_language_in_shipped_surface so the
    -k ownership_blind selector (16-VALIDATION.md) matches it.
    """
    # The prohibition is a PRODUCT invariant, so it is read from the product
    # (D-05). This previously parsed the term out of .planning/REQUIREMENTS.md
    # at runtime, which coupled the suite to a planning document and broke when
    # that document was archived at v1.3 milestone close.
    forbidden_term = PROHIBITED_OWNERSHIP_TERMS[0]
    assert forbidden_term, "the product must name the forbidden term"

    rules_toml = (
        Path(__file__).parent.parent
        / "src"
        / "sift"
        / "rules"
        / "eustack_roles.toml"
    ).read_text(encoding="utf-8")
    classifier_source = (
        Path(__file__).parent.parent / "src" / "sift" / "pipeline" / "eustack.py"
    ).read_text(encoding="utf-8")

    assert forbidden_term.lower() not in rules_toml.lower()
    assert forbidden_term.lower() not in classifier_source.lower()

    # --- S-7: extend the prohibition to all three D-05 terms, over EMITTED
    # OUTPUT rather than source text. src/sift/rules/eustack_roles.toml
    # carries "holder" in a prose comment describing the non-goal
    # (documentation, not output), which is why the whole-source grep above
    # stays scoped to the single REQUIREMENTS.md-named term while the
    # three-term prohibition below is enforced over strings the code
    # actually emits.
    prohibited_terms = PROHIBITED_OWNERSHIP_TERMS

    rules, rules_hash = load_rules()

    # Real derivative fixture: the healthy capture, zero lock matches by
    # design — still contributes its non-lock SaturationFlag messages.
    derivative_events = _parse_derivative_fixture()
    derivative_analysis = analyse_eustack(derivative_events, rules, rules_hash)
    derivative_saturation = analyse_saturation(
        derivative_analysis, EustackThresholdsConfig()
    )

    # Synthetic lock-convergence scenario (D-11) so lock-specific emitted
    # strings are genuinely present in the candidate set, not trivially
    # absent because no LockSite/lock flag was ever produced.
    lock_raw = _thread_raw(
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MSynch::CriticalSection::Enter",
        "Alpha::Caller",
    )
    lock_events = [_event(lock_raw, thread=f"t{i}") for i in range(5)]
    lock_analysis = analyse_eustack(lock_events, rules, rules_hash)
    lock_saturation = analyse_saturation(lock_analysis, EustackThresholdsConfig())
    assert lock_saturation.lock_sites, (
        "synthetic scenario must actually produce a lock site"
    )
    has_lock_flag = any(
        f.dimension == "lock_convergence_count" for f in lock_saturation.flags
    )
    assert has_lock_flag, "synthetic scenario must actually produce a lock flag"

    candidates: list[str] = [LOCK_FINDING_NOTE, UNKNOWN_LOCK_SITE]
    for saturation in (derivative_saturation, lock_saturation):
        candidates.extend(site.site for site in saturation.lock_sites)
        candidates.extend(flag.message for flag in saturation.flags)

    # Non-vacuity guard (mirrors the eval gate's empty-positive-set check):
    # a refactor that stops emitting these strings must not turn this test
    # vacuously green.
    assert candidates, "candidate string set must be non-empty"

    for candidate in candidates:
        for term in prohibited_terms:
            # Word-boundary matched: a bare substring test would false-
            # positive on an innocuous word ending in the same letters
            # (e.g. "placeholder" containing "holder").
            found = re.search(rf"\b{re.escape(term)}\b", candidate, re.IGNORECASE)
            assert found is None, (
                f"prohibited term {term!r} found in emitted string {candidate!r}"
            )


# ------------------------------------------------------- analyse_saturation ---
# Phase 16 tracer (16-01): EUS-03 per-pool occupancy end to end.


def test_pool_occupancy_splits_busy_and_parked() -> None:
    idle_raw = _thread_raw("MSIQTask::GetNextPreferredJob")
    running_raw = _thread_raw("CDSSSubsetEngine::GenCube")
    events = [_event(idle_raw, thread=f"i{i}") for i in range(3)] + [
        _event(running_raw, thread=f"r{i}") for i in range(2)
    ]
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    job_queue = next(p for p in saturation.pools if p.subsystem == "job-queue")
    assert job_queue.total_threads == 3
    assert job_queue.idle_threads == 3
    assert job_queue.busy_threads == 0
    assert job_queue.occupancy == 0.0
    assert job_queue.signature_count == 1

    cube_generation = next(
        p for p in saturation.pools if p.subsystem == "cube-generation"
    )
    assert cube_generation.total_threads == 2
    assert cube_generation.idle_threads == 0
    assert cube_generation.busy_threads == 2
    assert cube_generation.occupancy == 1.0
    assert cube_generation.signature_count == 1


def test_reference_derivative_occupancy_reads_pools_as_idle() -> None:
    """Success criterion 1: the healthy capture's parked job-queue workers
    read as idle (occupancy 0.0), not as a saturated pool."""
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    job_queue = next(p for p in saturation.pools if p.subsystem == "job-queue")
    assert job_queue.occupancy == 0.0
    assert job_queue.idle_threads == job_queue.total_threads


def test_flag_value_and_threshold_travel_together() -> None:
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    thresholds = EustackThresholdsConfig()
    saturation = analyse_saturation(analysis, thresholds)

    flag = next(
        f for f in saturation.flags if f.dimension == "unclassified_thread_pct"
    )
    assert flag.warn == thresholds.unclassified_thread_pct.warn
    assert flag.critical == thresholds.unclassified_thread_pct.critical
    expected = round(
        analysis.threads_by_role["unclassified"] / analysis.total_threads * 100, 1
    )
    assert flag.value == expected
    assert flag.unit == "percent"


def test_unclassified_not_pooled_and_not_in_any_denominator() -> None:
    """D-02: the unclassified population is isolated in its own None-keyed
    row and appears in no other pool's denominator. The dict key stays typed
    str | None and is never stringified — the mechanism preventing a literal
    "None" subsystem string from colliding with it."""
    unclassified_raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    idle_raw = _thread_raw("MSIQTask::GetNextPreferredJob")
    running_raw = _thread_raw("CDSSSubsetEngine::GenCube")
    events = (
        [_event(unclassified_raw, thread=f"u{i}") for i in range(4)]
        + [_event(idle_raw, thread=f"i{i}") for i in range(3)]
        + [_event(running_raw, thread=f"r{i}") for i in range(2)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    none_rows = [p for p in saturation.pools if p.subsystem is None]
    assert len(none_rows) == 1
    assert none_rows[0].total_threads == analysis.threads_by_role["unclassified"]
    assert none_rows[0].total_threads == 4

    other_total = sum(
        p.total_threads for p in saturation.pools if p.subsystem is not None
    )
    assert other_total == (
        analysis.total_threads - analysis.threads_by_role["unclassified"]
    )


def test_pool_occupancy_extremes_and_empty_analysis() -> None:
    # (a) zero idle-parked threads -> occupancy 1.0.
    running_raw = _thread_raw("CDSSSubsetEngine::GenCube")
    running_events = [_event(running_raw, thread=f"r{i}") for i in range(2)]
    rules, rules_hash = load_rules()
    running_analysis = analyse_eustack(running_events, rules, rules_hash)
    running_saturation = analyse_saturation(running_analysis, EustackThresholdsConfig())
    cube_generation = next(
        p for p in running_saturation.pools if p.subsystem == "cube-generation"
    )
    assert cube_generation.occupancy == 1.0

    # (b) only idle-parked threads -> occupancy 0.0.
    idle_raw = _thread_raw("MSIQTask::GetNextPreferredJob")
    idle_events = [_event(idle_raw, thread=f"i{i}") for i in range(3)]
    idle_analysis = analyse_eustack(idle_events, rules, rules_hash)
    idle_saturation = analyse_saturation(idle_analysis, EustackThresholdsConfig())
    job_queue = next(p for p in idle_saturation.pools if p.subsystem == "job-queue")
    assert job_queue.occupancy == 0.0

    # (c) empty event list and all-non-thread events -> empty tuples, no
    # exception, no division guard needed.
    empty_analysis = analyse_eustack([], rules, rules_hash)
    empty_saturation = analyse_saturation(empty_analysis, EustackThresholdsConfig())
    assert empty_saturation.pools == ()
    assert empty_saturation.flags == ()

    non_thread_events = [_event(idle_raw, thread=None) for _ in range(3)]
    non_thread_analysis = analyse_eustack(non_thread_events, rules, rules_hash)
    non_thread_saturation = analyse_saturation(
        non_thread_analysis, EustackThresholdsConfig()
    )
    assert non_thread_saturation.pools == ()
    assert non_thread_saturation.flags == ()


def test_deterministic_pool_ordering() -> None:
    # Two pools with EQUAL total_threads: alpha (job-queue) vs bravo
    # (cube-generation) tie on count, breaking ascending on subsystem name.
    idle_raw = _thread_raw("MSIQTask::GetNextPreferredJob")  # subsystem job-queue
    running_raw = _thread_raw("CDSSSubsetEngine::GenCube")  # subsystem cube-generation
    unclassified_raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    events = (
        [_event(idle_raw, thread=f"i{i}") for i in range(2)]
        + [_event(running_raw, thread=f"r{i}") for i in range(2)]
        + [_event(unclassified_raw, thread=f"u{i}") for i in range(2)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    subsystems = [p.subsystem for p in saturation.pools]
    # cube-generation < job-queue ascending; all three pools tie at 2 threads;
    # the None row sorts after every equal-count named pool.
    assert subsystems == ["cube-generation", "job-queue", None]

    first = analyse_saturation(analysis, EustackThresholdsConfig()).model_dump_json()
    second = analyse_saturation(analysis, EustackThresholdsConfig()).model_dump_json()
    assert first == second


# ------------------------------------------------- enclosing_application_frame ---
# Phase 16 plan 02 (EUS-04): the D-04 lock-site enclosing-frame walk.


def test_lock_site_walk_finds_enclosing_application_frame() -> None:
    """The walk goes toward INCREASING index and stops at the FIRST
    qualifying frame, not the outermost."""
    frames = (
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MSynch::CriticalSection::Enter",
        "MSIQTask::Execute",
    )
    assert (
        enclosing_application_frame(frames, 0) == "MSynch::CriticalSection::Enter"
    )


def test_lock_site_skips_runtime_namespace() -> None:
    """Real fixture shapes (tests/fixtures/eustack/reference_capture_derivative.txt):
    TID 100014 (lines 113-120) carries a std::condition_variable::wait(...)
    runtime frame directly above the futex wait, and TID 100011 (lines 86-93)
    carries several boost::asio::detail::... runtime frames — in both cases
    the walk must skip past the runtime frame(s) to the genuine MicroStrategy
    application frame beneath, not stop at the first '::'-qualified frame."""
    std_frames = (
        "__lll_lock_wait",
        "pthread_cond_wait",
        "std::condition_variable::wait(std::unique_lock<std::mutex>&)",
        "ParallelBursting::ThreadPool::WorkLoop(unsigned long)",
    )
    assert (
        enclosing_application_frame(std_frames, 0)
        == "ParallelBursting::ThreadPool::WorkLoop(unsigned long)"
    )

    boost_frames = (
        "__lll_lock_wait",
        "pthread_cond_wait",
        "boost::asio::detail::scheduler::do_run_one("
        "boost::asio::detail::conditionally_enabled_mutex::scoped_lock&, "
        "boost::asio::detail::scheduler_thread_info&, "
        "boost::system::error_code const&)",
        "boost::asio::detail::scheduler::run(boost::system::error_code&)",
        "ParallelBursting::ThreadPool::WorkLoop(unsigned long)",
    )
    assert (
        enclosing_application_frame(boost_frames, 0)
        == "ParallelBursting::ThreadPool::WorkLoop(unsigned long)"
    )


def test_lock_site_template_arg_not_misjudged() -> None:
    """D-04 edge case 3: the denylist test is applied to the symbol's LEADING
    namespace, not 'contains std:: anywhere' — a genuine MBase:: frame with a
    std:: template argument is kept; a genuine std:: frame with an MBase::
    template argument is skipped. Both directions of the same prefix rule."""
    mbase_leading = (
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MBase::ThreadedRepeater<std::chrono::duration<long> >::Run()",
    )
    assert (
        enclosing_application_frame(mbase_leading, 0)
        == "MBase::ThreadedRepeater<std::chrono::duration<long> >::Run()"
    )

    std_leading = (
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "std::thread::_State_impl<std::tuple<MBase::ThreadedRepeater> >::_M_run()",
    )
    assert enclosing_application_frame(std_leading, 0) is None


def test_lock_site_unknown_but_counted() -> None:
    """D-04 edge cases 1, 2 and 4: no qualifying frame above the leaf, in
    three different shapes, all resolve to None (unknown-but-counted at the
    caller, never dropped, never attributed to the leaf)."""
    # No frame above the leaf carries '::' at all — unqualified C symbols.
    all_c_symbols = ("__lll_lock_wait", "pthread_mutex_lock", "malloc")
    assert enclosing_application_frame(all_c_symbols, 0) is None

    # The leaf is the LAST frame in the tuple — empty slice, no IndexError.
    leaf_is_last = ("__lll_lock_wait",)
    assert enclosing_application_frame(leaf_is_last, 0) is None

    # Only unresolvable frames above the leaf — walked past, not a stop.
    only_unresolvable = ("__lll_lock_wait", "??", "0x00007f0000000001")
    assert enclosing_application_frame(only_unresolvable, 0) is None


def test_lock_site_walk_starts_at_reported_frame_index() -> None:
    """D-04 edge case 5: multiple __lll_lock_wait frames in one stack — the
    walk starts from the classification's reported frame_index, never a
    fresh re-scan of the tuple for the first leaf."""
    frames = (
        "__lll_lock_wait",
        "MSynch::First::Enter",
        "__lll_lock_wait",
        "MSynch::Second::Enter",
    )
    assert enclosing_application_frame(frames, 0) == "MSynch::First::Enter"
    assert enclosing_application_frame(frames, 2) == "MSynch::Second::Enter"


# ------------------------------------------------------- lock convergence ---
# Phase 16 plan 02 (EUS-04): LockSite grouping, the count flag, D-11.


def test_synthetic_lock_convergence() -> None:
    """HAND-AUTHORED, SYNTHETIC scenario (D-11) — NOT a redacted real
    capture. The healthy reference capture matches Rule 6 (__lll_lock_wait,
    the only blocked-on-lock rule in eustack_roles.toml) zero times by
    design, so no real capture can exercise the blocked-on-lock path. Built
    inline via _thread_raw()/_event() per 16-VALIDATION.md's Wave 0 note,
    rather than as a fixture file that would have to look synthetic and
    parse like a real capture at the same time.

    Threads converge on ONE site (MSynch::CriticalSection::Enter, frame #2)
    via THREE different outer frames (#3), so several distinct signatures
    collapse to the same site — that convergence, not the raw thread count,
    is what EUS-04 reports.
    """
    rules, rules_hash = load_rules()
    outers = ("Alpha::Caller", "Bravo::Caller", "Charlie::Caller")

    def _run(thread_count: int) -> SaturationAnalysis:
        events: list[Event] = []
        for i in range(thread_count):
            raw = _thread_raw(
                "__lll_lock_wait",
                "pthread_mutex_lock",
                "MSynch::CriticalSection::Enter",
                outers[i % len(outers)],
            )
            events.append(_event(raw, thread=f"t{i}"))
        analysis = analyse_eustack(events, rules, rules_hash)
        return analyse_saturation(analysis, EustackThresholdsConfig())

    # Below warn (default warn=5.0, critical=20.0): 3 threads -> info.
    below_warn = _run(3)
    assert len(below_warn.lock_sites) == 1
    site = below_warn.lock_sites[0]
    assert site.site == "MSynch::CriticalSection::Enter"
    assert site.thread_count == 3
    assert site.signature_count > 1
    flag = next(f for f in below_warn.flags if f.dimension == "lock_convergence_count")
    assert flag.severity == "info"

    # At warn: 5 threads -> warn.
    at_warn = _run(5)
    flag = next(f for f in at_warn.flags if f.dimension == "lock_convergence_count")
    assert flag.severity == "warn"

    # At/above critical: 20 threads -> critical.
    at_critical = _run(20)
    flag = next(f for f in at_critical.flags if f.dimension == "lock_convergence_count")
    assert flag.severity == "critical"

    # Unknown-but-counted: __lll_lock_wait with no qualifying frame above it
    # — never dropped, never attributed to the leaf.
    unknown_raw = _thread_raw("__lll_lock_wait", "pthread_mutex_lock", "malloc")
    unknown_events = [_event(unknown_raw, thread=f"u{i}") for i in range(4)]
    unknown_analysis = analyse_eustack(unknown_events, rules, rules_hash)
    unknown_saturation = analyse_saturation(unknown_analysis, EustackThresholdsConfig())
    assert len(unknown_saturation.lock_sites) == 1
    unknown_site = unknown_saturation.lock_sites[0]
    assert unknown_site.site == UNKNOWN_LOCK_SITE
    assert unknown_site.thread_count == 4


def test_reference_derivative_yields_no_lock_sites() -> None:
    """D-09: the healthy reference capture raises zero lock sites and zero
    lock_convergence_count flags — Rule 6 (__lll_lock_wait) matches it zero
    times by design."""
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    assert saturation.lock_sites == ()
    assert not any(f.dimension == "lock_convergence_count" for f in saturation.flags)


# ---------------------------------------------------- dependency split ---
# Phase 16 plan 03 (EUS-05): DependencyWait, the external-wait split by
# verbatim subsystem.


def test_dependency_split_by_subsystem() -> None:
    """Rules 16/warehouse, 17/http, 18/ipc, and 19/warehouse (a second rule
    sharing the warehouse subsystem) must aggregate MDb::Wrapper::
    InterpretStatus into the SAME warehouse row as CDSSQueryEngine::
    WaitUntilFinished, proving the grouping key is subsystem, not pattern."""
    warehouse_raw = _thread_raw("CDSSQueryEngine::WaitUntilFinished")
    warehouse_raw_2 = _thread_raw("MDb::Wrapper::InterpretStatus")
    http_raw = _thread_raw("curl_multi_poll")
    ipc_raw = _thread_raw("SharedMemoryImpl::WaitOnSemaphore")
    events = (
        [_event(warehouse_raw, thread=f"w{i}") for i in range(5)]
        + [_event(warehouse_raw_2, thread=f"w2-{i}") for i in range(2)]
        + [_event(http_raw, thread=f"h{i}") for i in range(3)]
        + [_event(ipc_raw, thread=f"p{i}") for i in range(1)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    assert len(saturation.dependencies) == 3
    by_subsystem = {d.subsystem: d for d in saturation.dependencies}

    # Two rules (CDSSQueryEngine::WaitUntilFinished, MDb::Wrapper::
    # InterpretStatus) both map to warehouse and must aggregate into one row
    # — 5 + 2 threads, TWO distinct signatures.
    warehouse = by_subsystem["warehouse"]
    assert warehouse.thread_count == 7
    assert warehouse.signature_count == 2

    http = by_subsystem["http"]
    assert http.thread_count == 3

    ipc = by_subsystem["ipc"]
    assert ipc.thread_count == 1

    # Axes are genuinely separate, never merged into one blocked total: no
    # row's thread count equals the sum of the others.
    for row in saturation.dependencies:
        others_sum = sum(
            other.thread_count
            for other in saturation.dependencies
            if other is not row
        )
        assert row.thread_count != others_sum

    # A blocked-on-external row's subsystem is never None.
    assert all(d.subsystem is not None for d in saturation.dependencies)


def test_reference_derivative_dependency_split_not_merged() -> None:
    """Derivative-fixture figures (measured, not the real-capture figures):
    the committed CI fixture caps thread counts at 1 per signature (5 for the
    three highest-population signatures), so its absolute dependency counts
    (warehouse 8, http 5, ipc 2) differ from the real out-of-repo reference
    capture (79 warehouse, 78 HTTP) by design. CI asserts the SPLIT's shape —
    warehouse and http are distinct, non-merged rows in the declared sort
    order — while the absolute real-capture figures are a manual verification
    (16-VALIDATION.md § Manual-Only Verifications)."""
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    assert [(d.subsystem, d.thread_count) for d in saturation.dependencies] == [
        ("warehouse", 8),
        ("http", 5),
        ("ipc", 2),
    ]
    warehouse = saturation.dependencies[0]
    http = saturation.dependencies[1]
    assert warehouse.thread_count != http.thread_count
    assert warehouse.thread_count != (warehouse.thread_count + http.thread_count)


# ---------------------------------------------- no_resolvable_frame_pct ---
# Phase 16 plan 03 (D-07 amended, S-5): the second ratio flag, same
# thread-weighted denominator as unclassified_thread_pct.


def test_no_resolvable_frame_flag_uses_total_thread_denominator() -> None:
    """Both residual reasons are present and unequal, plus a large body of
    genuinely classified threads, so the two candidate denominators
    (total_threads vs unclassified-only) differ by a large factor — proving
    the denominator choice is tested, not incidental."""
    no_resolvable_raw = _thread_raw("??", "??")
    matched_no_rule_raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    classified_raw = _thread_raw("MSIQTask::GetNextPreferredJob")
    events = (
        [_event(no_resolvable_raw, thread=f"n{i}") for i in range(2)]
        + [_event(matched_no_rule_raw, thread=f"m{i}") for i in range(6)]
        + [_event(classified_raw, thread=f"c{i}") for i in range(92)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    thresholds = EustackThresholdsConfig()
    saturation = analyse_saturation(analysis, thresholds)

    flag = next(f for f in saturation.flags if f.dimension == "no_resolvable_frame_pct")
    total_threads_denominator_value = round(2 / analysis.total_threads * 100, 1)
    unclassified_only_denominator_value = round(
        2 / analysis.threads_by_role["unclassified"] * 100, 1
    )
    assert total_threads_denominator_value != unclassified_only_denominator_value
    assert flag.value == total_threads_denominator_value
    assert flag.value != unclassified_only_denominator_value
    assert flag.unit == "percent"
    assert flag.warn == thresholds.no_resolvable_frame_pct.warn
    assert flag.critical == thresholds.no_resolvable_frame_pct.critical

    # Both ratio flags share the same denominator: recompute each
    # independently and compare against total_threads.
    unclassified_flag = next(
        f for f in saturation.flags if f.dimension == "unclassified_thread_pct"
    )
    expected_unclassified = round(
        analysis.threads_by_role["unclassified"] / analysis.total_threads * 100, 1
    )
    assert unclassified_flag.value == expected_unclassified


def test_signature_passthrough_reads_eustack_analysis_directly() -> None:
    """EUS-06: SaturationAnalysis has no field holding a signature list — a
    future field addition duplicating EustackAnalysis.signatures fails this
    test rather than passing silently. EustackAnalysis stays frozen,
    extra="forbid", field set unchanged from Phase 15 (D-10)."""
    assert set(SaturationAnalysis.model_fields) == {
        "pools",
        "lock_sites",
        "lock_finding_note",
        "dependencies",
        "flags",
    }

    assert EustackAnalysis.model_config.get("frozen") is True
    assert EustackAnalysis.model_config.get("extra") == "forbid"
    assert set(EustackAnalysis.model_fields) == {
        "total_threads",
        "total_signatures",
        "threads_by_role",
        "signatures_by_role",
        "signatures",
        "unclassified",
        "rules_hash",
        "rules_version",
        "rules_validated_against",
    }

    # The ranked collapse remains available and correct on the derivative
    # fixture, read directly rather than re-derived: 93 signatures, sorted
    # thread-count descending with ties ascending on the frames tuple, each
    # group carrying a role.
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert len(analysis.signatures) == 93
    for group in analysis.signatures:
        assert group.role is not None
    for earlier, later in zip(
        analysis.signatures, analysis.signatures[1:], strict=False
    ):
        assert (-earlier.thread_count, earlier.frames) <= (
            -later.thread_count,
            later.frames,
        )


# --------------------------------------------------- deterministic ordering ---
# Phase 16 plan 03: whole-model determinism across every grouping (pools,
# lock sites, dependencies, flags).


def test_deterministic_ordering_across_every_grouping() -> None:
    """One input exercising all four orderings at once, each with a
    deliberate tie, asserted against its named sort key directly rather than
    a hardcoded expected list — so the test documents the contract, not a
    snapshot. A Counter.most_common() regression (unspecified tie behaviour)
    would fail this test; the byte-identical-rerun check alone would NOT
    (tests/test_perfmon.py's own reasoning: hash order is fixed within one
    process, so a set iteration would not be detected by a repeat run)."""
    # Pool tie: job-queue and cube-generation both land on 4 threads —
    # cube-generation must sort first (ascending subsystem name on a tie).
    job_queue_raw = _thread_raw("MSIQTask::GetNextPreferredJob")
    cube_generation_raw = _thread_raw("CDSSSubsetEngine::GenCube")
    unclassified_raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")

    # Lock-site tie: two distinct sites, both converging 3 threads each —
    # "MSynch::AlphaSite::Enter" must sort first (ascending on site string).
    lock_a_raw = _thread_raw(
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MSynch::AlphaSite::Enter",
        "SomeCaller::A",
    )
    lock_b_raw = _thread_raw(
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MSynch::BravoSite::Enter",
        "SomeCaller::B",
    )

    # Dependency tie: warehouse and http both land on 2 threads — "http"
    # must sort first (ascending subsystem name on a tie).
    warehouse_raw = _thread_raw("CDSSQueryEngine::WaitUntilFinished")
    http_raw = _thread_raw("curl_multi_poll")

    events = (
        [_event(job_queue_raw, thread=f"jq{i}") for i in range(4)]
        + [_event(cube_generation_raw, thread=f"cg{i}") for i in range(4)]
        + [_event(unclassified_raw, thread=f"u{i}") for i in range(2)]
        + [_event(lock_a_raw, thread=f"la{i}") for i in range(3)]
        + [_event(lock_b_raw, thread=f"lb{i}") for i in range(3)]
        + [_event(warehouse_raw, thread=f"w{i}") for i in range(2)]
        + [_event(http_raw, thread=f"h{i}") for i in range(2)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    thresholds = EustackThresholdsConfig()
    saturation = analyse_saturation(analysis, thresholds)

    # --- pools: (-total_threads, subsystem is None, subsystem or "") ---
    for earlier, later in zip(
        saturation.pools, saturation.pools[1:], strict=False
    ):
        earlier_key = (
            -earlier.total_threads,
            earlier.subsystem is None,
            earlier.subsystem or "",
        )
        later_key = (
            -later.total_threads,
            later.subsystem is None,
            later.subsystem or "",
        )
        assert earlier_key <= later_key
    pool_subsystems = [p.subsystem for p in saturation.pools]
    cube_index = pool_subsystems.index("cube-generation")
    job_queue_index = pool_subsystems.index("job-queue")
    assert cube_index == job_queue_index - 1, (
        "tied pools (4 threads each) must break ascending on subsystem name: "
        "cube-generation before job-queue"
    )

    # --- lock_sites: (-thread_count, site) ---
    for earlier, later in zip(
        saturation.lock_sites, saturation.lock_sites[1:], strict=False
    ):
        assert (-earlier.thread_count, earlier.site) <= (
            -later.thread_count,
            later.site,
        )
    lock_sites_by_name = [s.site for s in saturation.lock_sites]
    alpha_index = lock_sites_by_name.index("MSynch::AlphaSite::Enter")
    bravo_index = lock_sites_by_name.index("MSynch::BravoSite::Enter")
    assert alpha_index == bravo_index - 1, (
        "tied lock sites (3 threads each) must break ascending on site: "
        "AlphaSite before BravoSite"
    )

    # --- dependencies: (-thread_count, subsystem) ---
    for earlier, later in zip(
        saturation.dependencies, saturation.dependencies[1:], strict=False
    ):
        assert (-earlier.thread_count, earlier.subsystem) <= (
            -later.thread_count,
            later.subsystem,
        )
    dependency_subsystems = [d.subsystem for d in saturation.dependencies]
    http_index = dependency_subsystems.index("http")
    warehouse_index = dependency_subsystems.index("warehouse")
    assert http_index == warehouse_index - 1, (
        "tied dependencies (2 threads each) must break ascending on "
        "subsystem name: http before warehouse"
    )

    # --- flags: fixed authored order, NOT sorted by severity ---
    # unclassified share, then no-resolvable-frame share, then
    # lock-convergence entries in lock_sites order (severity sorting is a
    # render-time concern belonging to Phase 17, per mcm_facts.py's
    # _SEVERITY_ORDER precedent).
    flag_dimensions = [f.dimension for f in saturation.flags]
    assert flag_dimensions[0] == "unclassified_thread_pct"
    assert flag_dimensions[1] == "no_resolvable_frame_pct"
    lock_flag_sites = [
        f.message for f in saturation.flags if f.dimension == "lock_convergence_count"
    ]
    assert len(lock_flag_sites) == 2
    # AlphaSite's flag must precede BravoSite's, matching lock_sites order.
    assert "AlphaSite" in lock_flag_sites[0]
    assert "BravoSite" in lock_flag_sites[1]

    # --- byte-identical rerun ---
    # Necessary but NOT sufficient on its own: hash order is fixed within
    # one process, so a set iteration would not be detected by a repeat run
    # (the same reasoning tests/test_perfmon.py records for its own
    # determinism check). The direct per-key order assertions above are
    # what actually catch a Counter.most_common()/set-iteration regression.
    first = analyse_saturation(analysis, thresholds).model_dump_json()
    second = analyse_saturation(analysis, thresholds).model_dump_json()
    assert first == second


# ---------------------------------------------------- D-09 zero-flags gate ---
# Phase 16 plan 04: the D-09 verification gate on the SHIPPED defaults, split
# across two tests per S-8, plus the Success Criterion 5 value-beside-
# threshold proof across all three flag families.


def test_reference_derivative_zero_flags() -> None:
    """S-8: the committed derivative fixture is signature-preserving, NOT
    thread-weight-preserving. Its cap policy (1 thread per signature, 5 for
    the three highest-population signatures) deflates the classified thread
    population by roughly 3,000 threads while leaving the unclassified
    population (40 of 93 signatures) nearly intact — inflating the
    unclassified THREAD share from the real capture's 52/3,902 = 1.33% to
    this fixture's 40/105 = 38.10%, a 28-fold inflation caused by the cap
    policy, not by any real rules-drift signal.

    `unclassified_thread_pct` is therefore deliberately EXCLUDED from this
    half of the D-09 gate — `test_measured_reference_composition_raises_
    zero_flags` covers it instead, against the real capture's MEASURED
    composition. Raising `EustackThresholdsConfig.unclassified_thread_pct.
    warn` above 38.1% to make this fixture read `info` was considered and
    REJECTED (16-04-PLAN.md S-8): that would ship a threshold calibrated
    against a fixture's cap policy rather than against a server, making the
    flag nearly useless against a real 40%+ rules-drift population. Do not
    "fix" this test by loosening the shipped default.

    This test covers the two flag families the derivative CAN faithfully
    exercise: `no_resolvable_frame_pct` (genuinely 0.0% here — every
    derivative thread resolved to a real symbol) and `lock_convergence_count`
    (genuinely zero sites — Rule 6, the sole `blocked-on-lock` rule, matches
    this healthy capture zero times by design)."""
    events = _parse_derivative_fixture()
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    # EustackThresholdsConfig() with NO arguments: this gate runs the
    # SHIPPED defaults, never a test-local override.
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    no_resolvable_flag = next(
        f for f in saturation.flags if f.dimension == "no_resolvable_frame_pct"
    )
    assert no_resolvable_flag.severity == "info"

    assert not any(f.dimension == "lock_convergence_count" for f in saturation.flags)

    unclassified_flag = next(
        f for f in saturation.flags if f.dimension == "unclassified_thread_pct"
    )
    assert unclassified_flag.value == 38.1


def test_measured_reference_composition_raises_zero_flags() -> None:
    """The real D-09 gate: the healthy reference capture's MEASURED
    composition — 3,902 threads, 52 unclassified (1.33%, reason=
    'matched-no-rule'), zero no-resolvable-frame threads, zero
    blocked-on-lock signatures, ~3,400 of the 3,850 classified threads
    parked in the headline job-queue pool — raises ZERO flags above `info`
    against the SHIPPED `EustackThresholdsConfig()` defaults. Figures are
    ADR 0015's Day-one coverage figures and 16-CONTEXT.md's Specific Ideas
    section, both measured UPSTREAM of `analyse_saturation()`, never
    reverse-engineered from it.

    `EustackAnalysis` is constructed DIRECTLY rather than synthesising 3,902
    raw thread blocks: `EustackAnalysis` is `analyse_saturation()`'s public,
    frozen input contract (D-10), so building it at the real capture's
    measured shape exercises the unit under test at the correct level
    without a multi-thousand-line synthetic fixture that would itself need
    its own provenance labelling."""
    job_queue = SignatureGroup(
        frames=("MSIQTask::GetNextPreferredJob",),
        thread_count=3400,
        role="idle-parked",
        subsystem="job-queue",
        pattern="MSIQTask::GetNextPreferredJob",
        frame_index=3,
        reason=None,
    )
    warehouse = SignatureGroup(
        frames=("CDSSQueryEngine::WaitUntilFinished",),
        thread_count=79,
        role="blocked-on-external",
        subsystem="warehouse",
        pattern="CDSSQueryEngine::WaitUntilFinished",
        frame_index=0,
        reason=None,
    )
    http = SignatureGroup(
        frames=("curl_multi_poll",),
        thread_count=78,
        role="blocked-on-external",
        subsystem="http",
        pattern="curl_multi_poll",
        frame_index=0,
        reason=None,
    )
    compute = SignatureGroup(
        frames=("_shi_allocBlock",),
        thread_count=293,
        role="running",
        subsystem="compute",
        pattern="_shi_allocBlock",
        frame_index=0,
        reason=None,
    )
    unclassified = SignatureGroup(
        frames=("SomeUnrecognisedFrame::Body",),
        thread_count=52,
        role="unclassified",
        subsystem=None,
        pattern=None,
        frame_index=None,
        reason="matched-no-rule",
    )
    analysis = EustackAnalysis(
        total_threads=3902,
        total_signatures=5,
        threads_by_role={
            "idle-parked": 3400,
            "blocked-on-external": 157,
            "blocked-on-lock": 0,
            "running": 293,
            "unclassified": 52,
        },
        signatures_by_role={
            "idle-parked": 1,
            "blocked-on-external": 2,
            "blocked-on-lock": 0,
            "running": 1,
            "unclassified": 1,
        },
        signatures=(job_queue, warehouse, http, compute, unclassified),
        unclassified=(unclassified,),
        rules_hash="0" * 16,
        rules_version=1,
        rules_validated_against="measured-reference-capture",
    )

    # EustackThresholdsConfig() with NO arguments: the SHIPPED defaults are
    # the gate under test; a test-local override would disconnect this test
    # from what actually ships.
    saturation = analyse_saturation(analysis, EustackThresholdsConfig())

    assert saturation.flags, "flag list must be non-empty to be a real gate"
    for flag in saturation.flags:
        assert flag.severity == "info", (
            f"{flag.dimension} graded {flag.severity!r} against the shipped "
            "defaults on the real capture's measured composition (D-09)"
        )

    unclassified_flag = next(
        f for f in saturation.flags if f.dimension == "unclassified_thread_pct"
    )
    assert unclassified_flag.value == 1.3

    no_resolvable_flag = next(
        f for f in saturation.flags if f.dimension == "no_resolvable_frame_pct"
    )
    assert no_resolvable_flag.value == 0.0

    assert not any(f.dimension == "lock_convergence_count" for f in saturation.flags)


def test_every_flag_family_prints_value_beside_threshold() -> None:
    """Success Criterion 5, all three flag families in one pass: every graded
    flag's `value` travels beside its own `warn`/`critical` cut-points
    (never re-read from config) with the matching `unit`, and `severity` is
    exactly what an INDEPENDENT recompute of `_grade(value, warn, critical)`
    in this test says it should be — a flag whose own severity disagrees
    with its own printed figures fails this test."""
    idle_raw = _thread_raw("MSIQTask::GetNextPreferredJob")
    no_resolvable_raw = _thread_raw("??", "??")
    matched_no_rule_raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    lock_raw = _thread_raw(
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MSynch::CriticalSection::Enter",
        "Alpha::Caller",
    )
    events = (
        [_event(idle_raw, thread=f"i{i}") for i in range(100)]
        + [_event(no_resolvable_raw, thread=f"n{i}") for i in range(2)]
        + [_event(matched_no_rule_raw, thread=f"m{i}") for i in range(3)]
        + [_event(lock_raw, thread=f"l{i}") for i in range(5)]
    )
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)
    thresholds = EustackThresholdsConfig()
    saturation = analyse_saturation(analysis, thresholds)

    assert saturation.flags, "flag list must be non-empty before iterating"
    dimensions = {f.dimension for f in saturation.flags}
    assert dimensions == {
        "unclassified_thread_pct",
        "no_resolvable_frame_pct",
        "lock_convergence_count",
    }

    for flag in saturation.flags:
        assert isinstance(flag.value, float)
        expected_pair = getattr(thresholds, flag.dimension)
        assert flag.warn == expected_pair.warn
        assert flag.critical == expected_pair.critical
        expected_unit = (
            "threads" if flag.dimension == "lock_convergence_count" else "percent"
        )
        assert flag.unit == expected_unit
        expected_severity = _grade(flag.value, flag.warn, flag.critical)
        assert flag.severity == expected_severity
