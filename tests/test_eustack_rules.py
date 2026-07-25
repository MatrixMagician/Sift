"""eu-stack thread-role classifier tests (EUS-01, EUS-02).

The tracer test proves the whole Phase 15 path on one thread: adapter frame
split -> normalisation -> signature -> packaged TOML load -> first-match-wins
classification. It uses an inline raw thread block, not the committed
``tests/fixtures/eustack/threaddump.txt`` — that fixture is a sanitised
synthetic capture with no MicroStrategy frames, so it cannot carry this proof.
"""

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
