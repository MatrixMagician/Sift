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
    analyse_eustack,
    analyse_saturation,
    classify_signature,
    load_rules,
    normalise,
    signature_of,
)

FIXTURES = Path(__file__).parent / "fixtures" / "eustack"
_REQUIREMENTS_MD = (
    Path(__file__).parent.parent / ".planning" / "REQUIREMENTS.md"
)

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


def test_no_ownership_attributed_lock_language_in_shipped_surface() -> None:
    """The lock-ownership term REQUIREMENTS.md's Out of Scope table names as
    a permanent non-goal appears nowhere in the shipped rules file or
    classifier module. Read from REQUIREMENTS.md at runtime rather than
    hardcoded, so the test cannot itself become the only place it's typed."""
    requirements_text = _REQUIREMENTS_MD.read_text(encoding="utf-8")
    match = re.search(r'the word "(\w+)"', requirements_text)
    assert match is not None, "REQUIREMENTS.md must name the forbidden term"
    forbidden_term = match.group(1)

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
