"""eu-stack thread-role classifier tests (EUS-01, EUS-02).

The tracer test proves the whole Phase 15 path on one thread: adapter frame
split -> normalisation -> signature -> packaged TOML load -> first-match-wins
classification. It uses an inline raw thread block, not the committed
``tests/fixtures/eustack/threaddump.txt`` — that fixture is a sanitised
synthetic capture with no MicroStrategy frames, so it cannot carry this proof.
"""

import importlib.resources
from pathlib import Path

import pytest
from pydantic import ValidationError

from sift.pipeline.eustack import (
    classify_signature,
    load_rules,
    normalise,
    signature_of,
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
