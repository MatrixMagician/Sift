"""Unit tests for ``pipeline.eustack_facts`` (EUS-10, D-05, D-16, D-17).

Mirrors ``tests/test_perfmon_facts.py``/``tests/test_mcm_facts.py``: the
versioned ``eustack_facts.md`` fragment carries zero authored digits (D-16 —
every figure originates in Python), and the id set ``render_eustack_facts``
returns is provably EXACTLY the set of ids printed as ``[evt:<id>]`` tokens in
its text — neither a superset nor a subset (D-05).

Plan 18-02 adds coverage for the three remaining Phase 16 groupings (pool
occupancy, lock-site convergence, external-wait concentration), the D-17
union-then-sample exemplar contract for multi-signature aggregates, the D-03
sampling-sentence honesty gate, and the D-06/D-07/D-08 capped, drop-disclosing
per-signature listing.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

from sift.adapters.eustack import EustackAdapter
from sift.config import EustackThresholdsConfig, McmThresholdsConfig, load_config
from sift.models import Event
from sift.pipeline import hypothesise
from sift.pipeline.eustack import (
    EustackAnalysis,
    PoolOccupancy,
    SaturationAnalysis,
    SignatureGroup,
    load_rules,
)
from sift.pipeline.eustack_facts import (
    _MAX_SIGNATURES,  # pyright: ignore[reportPrivateUsage]
    _load_eustack_fragment,  # pyright: ignore[reportPrivateUsage]
    render_eustack_facts,
)
from sift.pipeline.eustack_progression import (
    ORDER_BASIS_FILENAME,
    ORDER_BASIS_TIMESTAMP,
    DumpSlice,
    EustackBundle,
    ProgressionAnalysis,
    analyse_eustack_bundle,
)
from sift.pipeline.eustack_vocabulary import (
    PROHIBITED_OWNERSHIP_TERMS,
)
from sift.pipeline.mcm import analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.perfmon import analyse_perfmon
from sift.pipeline.perfmon_facts import render_perfmon_facts
from sift.render._util import sanitise
from sift.store import CaseStore

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eustack"
_PROGRESSION_FIXTURES_DIR = _FIXTURES_DIR / "progression"
_EVT_TOKEN_RE = re.compile(r"\[evt:([0-9a-f]{16})\]")
_SAMPLING_RE = re.compile(r"\((\d+) of (\d+) thread events cited as exemplars\)")

# Mirrored from tests/test_eustack_report.py's own continuity-verb gate
# (D-10) — the per-thread continuity vocabulary a progression narrative must
# never use, since eu-stack carries no per-thread identity link across dumps.
_CONTINUITY_VERBS = ("persisted", "remained", "stayed", "still blocked")

_ALL_ROLES = (
    "idle-parked",
    "blocked-on-external",
    "blocked-on-lock",
    "running",
    "unclassified",
)


def test_fragment_holds_no_authored_number() -> None:
    """D-16: the versioned fragment carries no ASCII digit — proving every
    figure is computed in Python, so a wording change touches no number. Read
    through the same package-data path the renderer uses, so this guards
    exactly what ships."""
    fragment = _load_eustack_fragment()
    offending = [ch for ch in fragment if "0" <= ch <= "9"]
    assert offending == [], f"eustack_facts.md holds an authored figure: {offending}"


def test_id_set_equals_printed_evt_tokens() -> None:
    """D-05: the returned id set equals exactly the ids printed inside
    ``[evt:...]`` tokens in the rendered text — never a superset or a subset.
    Asserted non-empty first so the equality cannot pass vacuously."""
    adapter = EustackAdapter()
    adapter.input_root = _FIXTURES_DIR
    events = list(adapter.parse(_FIXTURES_DIR / "threaddump.txt", "case1"))
    rules, rules_hash = load_rules()
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, EustackThresholdsConfig()
    )

    block, ids = render_eustack_facts(bundle, events)

    printed = set(_EVT_TOKEN_RE.findall(block))
    assert printed, "the block must print >=1 [evt:] token (non-vacuity guard)"
    assert printed == ids


# --- Plan 18-02 fixtures/helpers ---------------------------------------------


def _derivative_bundle() -> tuple[list[Event], EustackBundle]:
    """The committed 93-signature derivative fixture (D-17/D-06 test bed)."""
    adapter = EustackAdapter()
    adapter.input_root = _FIXTURES_DIR
    events = list(
        adapter.parse(_FIXTURES_DIR / "reference_capture_derivative.txt", "case1")
    )
    rules, rules_hash = load_rules()
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, EustackThresholdsConfig()
    )
    return events, bundle


def _synthetic_thread_event(
    source_file: str, frames: tuple[str, ...], event_id_val: str, thread: str
) -> Event:
    """One synthetic thread block on ``source_file``, hand-built rather than
    parsed so a crafted event_id/frame chain reaches the pipeline byte-for-byte
    (mirrors ``tests/test_eustack_report.py::_synthetic_dump``)."""
    lines = [f"TID {thread}:\n"]
    for idx, frame in enumerate(frames):
        lines.append(f"#{idx}  0x{idx:016x} {frame}\n")
    return Event(
        event_id=event_id_val,
        case_id="case",
        ts=None,
        ts_confidence="missing",
        source="eustack",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="unknown",
        component=None,
        thread=thread,
        session=None,
        message="",
        attrs={},
        raw="".join(lines),
    )


def _line_containing(block: str, needle: str) -> str:
    for line in block.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"no line containing {needle!r} found in block")


def _synthetic_bundle(
    signatures: tuple[SignatureGroup, ...],
    pools: tuple[PoolOccupancy, ...],
) -> EustackBundle:
    """A minimal, directly-constructed bundle for testing the renderer's own
    contract in isolation from ``analyse_saturation``'s grading (e.g. forcing
    ``flags=()`` regardless of what real grading would compute)."""
    threads_by_role: dict[str, int] = dict.fromkeys(_ALL_ROLES, 0)
    signatures_by_role: dict[str, int] = dict.fromkeys(_ALL_ROLES, 0)
    for group in signatures:
        threads_by_role[group.role] += group.thread_count
        signatures_by_role[group.role] += 1
    analysis = EustackAnalysis(
        total_threads=sum(g.thread_count for g in signatures),
        total_signatures=len(signatures),
        threads_by_role=threads_by_role,  # pyright: ignore[reportArgumentType]
        signatures_by_role=signatures_by_role,  # pyright: ignore[reportArgumentType]
        signatures=signatures,
        unclassified=tuple(g for g in signatures if g.role == "unclassified"),
        rules_hash="0" * 16,
        rules_version=1,
        rules_validated_against="test",
    )
    saturation = SaturationAnalysis(
        pools=pools, lock_sites=(), dependencies=(), flags=()
    )
    progression = ProgressionAnalysis(
        dumps=(
            DumpSlice(
                source_file="dumpA.txt",
                ts=None,
                ts_confidence="missing",
                thread_count=sum(g.thread_count for g in signatures),
            ),
        ),
        order_basis="filename",
        ordering_flags=(),
        signatures=(),
    )
    return EustackBundle(
        analysis=analysis, saturation=saturation, progression=progression
    )


# --- Task 1: four Phase-16 groupings, D-17 union-then-sample -----------------


def test_exemplar_ids_exist_in_store(tmp_path: Path) -> None:
    """For a bundle built from a real ingested store, every id the block
    prints is a real ``event_id`` present in ``store.query_events()``."""
    store = CaseStore(tmp_path / "case.db")
    try:
        adapter = EustackAdapter()
        adapter.input_root = _FIXTURES_DIR
        events = list(
            adapter.parse(
                _FIXTURES_DIR / "reference_capture_derivative.txt", "case1"
            )
        )
        with store.transaction():
            store.insert_events(events)
        stored_events = store.query_events()
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            stored_events, rules, rules_hash, EustackThresholdsConfig()
        )
        _block, ids = render_eustack_facts(bundle, stored_events)
        assert ids, "the block must print >=1 citable id (non-vacuity guard)"
        by_id = {event.event_id for event in stored_events}
        for eid in ids:
            assert eid in by_id
    finally:
        store.close()


def test_sampling_sentence_states_true_population() -> None:
    """D-03: for a multi-signature pool, the parenthetical states an exemplar
    count equal to the number of ``[evt:]`` tokens on that line, and a
    population equal to the POOL's own ``total_threads`` — never a single
    contributing signature's ``thread_count``."""
    events, bundle = _derivative_bundle()
    block, _ids = render_eustack_facts(bundle, events)

    multi_sig_pool = next(p for p in bundle.saturation.pools if p.signature_count > 1)
    label = (
        multi_sig_pool.subsystem if multi_sig_pool.subsystem is not None
        else "unclassified"
    )
    line = _line_containing(block, f"eu-stack {label} pool occupancy")

    tokens = _EVT_TOKEN_RE.findall(line)
    match = _SAMPLING_RE.search(line)
    assert match is not None, "sampling sentence not found on the pool line"
    exemplar_count, population = int(match.group(1)), int(match.group(2))

    assert exemplar_count == len(tokens)
    assert population == multi_sig_pool.total_threads

    contributing_counts = {
        g.thread_count
        for g in bundle.analysis.signatures
        if g.subsystem == multi_sig_pool.subsystem
    }
    assert population not in contributing_counts, (
        "the sampling sentence's population must be the AGGREGATE's own "
        "count, not a single contributing signature's thread_count"
    )


def test_every_cited_line_carries_sampling_sentence() -> None:
    """CR-01 whole-block invariant: every line carrying at least one
    ``[evt:...]`` citation token must also carry the D-03 sampling
    disclosure sentence — not just the pool line
    ``test_sampling_sentence_states_true_population`` already covers.
    ``_flag_lines`` was the sole exception (a ``SaturationFlag`` line printed
    citations beside a figure with no disclosure at all); the derivative
    fixture's real saturation flags exercise exactly that renderer."""
    events, bundle = _derivative_bundle()
    assert bundle.saturation.flags, (
        "fixture must produce >=1 SaturationFlag for this test to exercise "
        "_flag_lines (non-vacuity guard)"
    )
    block, _ids = render_eustack_facts(bundle, events)

    cited_lines_without_sentence = [
        line
        for line in block.splitlines()
        if _EVT_TOKEN_RE.search(line) and _SAMPLING_RE.search(line) is None
    ]
    assert cited_lines_without_sentence == [], (
        "every line carrying an [evt:] citation must also carry the "
        "'(N of M thread events cited as exemplars)' disclosure sentence; "
        f"offending lines: {cited_lines_without_sentence}"
    )


def test_multi_signature_aggregate_unions_before_sampling() -> None:
    """D-17: a pool backed by two signatures with disjoint, interleaved id
    ranges must union both event pools BEFORE sampling the lowest three —
    never each signature's own lowest three, concatenated."""
    sig_a_ids = [f"aaaaaaaaaaaaaaa{i}" for i in (1, 3, 5)]
    sig_b_ids = [f"aaaaaaaaaaaaaaa{i}" for i in (2, 4, 6)]

    frames_a = ("FrameA1", "FrameA2")
    frames_b = ("FrameB1", "FrameB2")

    events = [
        _synthetic_thread_event("dumpA.txt", frames_a, eid, f"a{i}")
        for i, eid in enumerate(sig_a_ids)
    ] + [
        _synthetic_thread_event("dumpA.txt", frames_b, eid, f"b{i}")
        for i, eid in enumerate(sig_b_ids)
    ]

    signatures = (
        SignatureGroup(
            frames=frames_a,
            thread_count=3,
            role="idle-parked",
            subsystem="poolX",
            pattern="ruleA",
            frame_index=0,
            reason=None,
        ),
        SignatureGroup(
            frames=frames_b,
            thread_count=3,
            role="idle-parked",
            subsystem="poolX",
            pattern="ruleA",
            frame_index=0,
            reason=None,
        ),
    )
    pools = (
        PoolOccupancy(
            subsystem="poolX",
            total_threads=6,
            idle_threads=6,
            busy_threads=0,
            occupancy=0.0,
            signature_count=2,
        ),
    )
    bundle = _synthetic_bundle(signatures, pools)

    block, _ids = render_eustack_facts(bundle, events)
    line = _line_containing(block, "eu-stack poolX pool occupancy")
    printed = _EVT_TOKEN_RE.findall(line)

    union_lowest_three = sorted(sig_a_ids + sig_b_ids)[:3]
    per_signature_concat = sorted(sig_a_ids)[:3]  # signature A alone, the
    # failure mode of resolving only ONE contributing signature's pool
    # instead of the true union.

    assert len(printed) == 3
    assert printed == union_lowest_three
    assert printed != per_signature_concat, (
        "result must differ from the rejected per-signature strategy, or "
        "this test cannot distinguish union-then-sample from it"
    )


def test_zero_flag_capture_still_renders_block() -> None:
    """A bundle with ``saturation.flags == ()`` but ``analysis.total_threads
    > 0`` still renders a non-empty block containing >=1 pool line —
    emptiness is gated on ``total_threads`` alone, never on ``flags``."""
    frames = ("MSIQTask::GetNextPreferredJob",)
    events = [_synthetic_thread_event("dumpA.txt", frames, "b" * 16, "t0")]
    signatures = (
        SignatureGroup(
            frames=frames,
            thread_count=1,
            role="idle-parked",
            subsystem="job-queue",
            pattern="MSIQTask::GetNextPreferredJob",
            frame_index=0,
            reason=None,
        ),
    )
    pools = (
        PoolOccupancy(
            subsystem="job-queue",
            total_threads=1,
            idle_threads=1,
            busy_threads=0,
            occupancy=0.0,
            signature_count=1,
        ),
    )
    bundle = _synthetic_bundle(signatures, pools)
    assert bundle.saturation.flags == ()
    assert bundle.analysis.total_threads > 0

    block, ids = render_eustack_facts(bundle, events)
    assert block
    assert ids
    assert "pool occupancy" in block


def test_block_byte_identical_on_rerun() -> None:
    """Rendering the same bundle twice returns identical text and an
    identical sorted id list — no set-iteration nondeterminism anywhere."""
    events, bundle = _derivative_bundle()
    block_1, ids_1 = render_eustack_facts(bundle, events)
    block_2, ids_2 = render_eustack_facts(bundle, events)
    assert block_1 == block_2
    assert sorted(ids_1) == sorted(ids_2)


def test_lock_site_lines_carry_no_ownership_language() -> None:
    """D-05: the lock-site convergence lines report only that threads were
    observed converging at a site — never lock possession or a wait-for
    graph. Mirrors ``test_eustack_report.py``'s ownership-blind vocabulary
    gate, reading the prohibited terms from the product constant that declares
    them (D-05) rather than from a planning document."""
    prohibited_terms = PROHIBITED_OWNERSHIP_TERMS

    lock_frames = (
        "__lll_lock_wait",
        "pthread_mutex_lock",
        "MSynch::CriticalSection::Enter",
        "Alpha::Caller",
    )
    events = [
        _synthetic_thread_event("dumpA.txt", lock_frames, f"{i:016x}", f"t{i}")
        for i in range(5)
    ]
    rules, rules_hash = load_rules()
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, EustackThresholdsConfig()
    )
    assert bundle.saturation.lock_sites, "synthetic scenario must produce a lock site"

    block, _ids = render_eustack_facts(bundle, events)
    assert "lock-site convergence" in block, "non-vacuity guard"
    for term in prohibited_terms:
        found = re.search(rf"\b{re.escape(term)}\b", block, re.IGNORECASE)
        assert found is None, f"prohibited term {term!r} found in rendered block"


# --- Task 2: capped, drop-disclosing per-signature listing (D-06/D-07/D-08) -


def test_signature_cap_states_dropped_count() -> None:
    """The 93-signature derivative fixture renders exactly eight
    per-signature rows — the eight highest by thread count, per
    ``analyse_eustack``'s own pre-sorted order — plus an explicit
    dropped-count statement naming the remaining 85."""
    events, bundle = _derivative_bundle()
    block, _ids = render_eustack_facts(bundle, events)

    assert block.count("eu-stack signature:") == 8
    expected_counts = [g.thread_count for g in bundle.analysis.signatures[:8]]
    rendered_counts = [
        int(m.group(1).replace(",", ""))
        for m in re.finditer(r"eu-stack signature: ([\d,]+) threads", block)
    ]
    assert rendered_counts == expected_counts, (
        "rendered rows must be exactly the top-8 slice in the analyser's own "
        "order — never re-sorted, never force-including a lower-ranked one"
    )
    assert "85 further signatures not shown" in block
    assert "93" in _line_containing(block, "further signatures not shown")


def test_signature_cap_no_dropped_sentence_when_at_or_under_cap() -> None:
    """A case with <=8 signatures emits no dropped-count sentence at all — a
    small case's block must never carry a misleading zero."""
    adapter = EustackAdapter()
    adapter.input_root = _FIXTURES_DIR
    events = list(adapter.parse(_FIXTURES_DIR / "threaddump.txt", "case1"))
    rules, rules_hash = load_rules()
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, EustackThresholdsConfig()
    )
    assert bundle.analysis.total_signatures <= 8

    block, _ids = render_eustack_facts(bundle, events)
    assert "further signatures not shown" not in block


# --- Plan 18-03: multi-dump progression, D-09/D-10/D-11 ---------------------


def _parse_progression_fixture(name: str) -> list[Event]:
    adapter = EustackAdapter()
    adapter.input_root = _PROGRESSION_FIXTURES_DIR
    return list(adapter.parse(_PROGRESSION_FIXTURES_DIR / name, "progression-test"))


def _progression_bundle(*names: str) -> tuple[list[Event], EustackBundle]:
    """Concatenate several progression fixtures' events into one bundle,
    exactly as ``sift eustack``/``sift analyze`` would (mirrors
    ``tests/test_eustack_report.py``'s own ``_bundle_for``)."""
    events: list[Event] = []
    for name in names:
        events.extend(_parse_progression_fixture(name))
    rules, rules_hash = load_rules()
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, EustackThresholdsConfig()
    )
    return events, bundle


def _two_untimestamped_dumps(tmp_path: Path) -> tuple[list[Event], EustackBundle]:
    """The real-shaped, header-timestamp-less derivative fixture ingested
    TWICE under distinct filenames, so the case is genuinely multi-dump while
    neither dump carries a header timestamp — the D-11 primary path: the real
    reference capture takes exactly this route."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    first = input_root / "reference_capture_derivative.txt"
    second = input_root / "reference_capture_derivative_copy.txt"
    original = _FIXTURES_DIR / "reference_capture_derivative.txt"
    first.write_bytes(original.read_bytes())
    second.write_bytes(original.read_bytes())

    adapter = EustackAdapter()
    adapter.input_root = input_root
    events = list(adapter.parse(first, "case1")) + list(
        adapter.parse(second, "case1")
    )
    rules, rules_hash = load_rules()
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, EustackThresholdsConfig()
    )
    return events, bundle


def test_deltas_suppressed_on_unverified_order(tmp_path: Path) -> None:
    """D-10/D-11 PRIMARY path: a multi-dump case whose ordering basis falls
    back to sorted file names (neither dump carries a header timestamp, the
    real reference capture's own shape) renders last-dump state plus an
    explicit suppression statement and NO delta figure anywhere."""
    events, bundle = _two_untimestamped_dumps(tmp_path)
    assert bundle.progression.order_basis == ORDER_BASIS_FILENAME
    assert len(bundle.progression.dumps) == 2

    block, _ids = render_eustack_facts(bundle, events)
    assert block, "the two-dump case must still yield a non-empty block"
    assert "progression across dumps was not reported" in block, (
        "the suppression statement must be present"
    )
    assert "eu-stack signature population change:" not in block, (
        "no delta-vocabulary figure may appear when the order is unverified"
    )
    assert not re.search(r"overall change [+-][\d,]+ threads", block), (
        "no signed-integer delta token may appear when the order is unverified"
    )
    assert bundle.progression.scope_note in block


def test_deltas_rendered_on_verified_order() -> None:
    """D-09: a multi-dump case with a VERIFIED (timestamp-ordered) dump order
    renders capped, cited per-signature population deltas, never more than
    ``_MAX_SIGNATURES`` rows, alongside the verbatim scope note."""
    events, bundle = _progression_bundle(
        "dump_alpha.txt", "dump_bravo.txt", "dump_charlie.txt"
    )
    assert bundle.progression.order_basis == ORDER_BASIS_TIMESTAMP

    block, _ids = render_eustack_facts(bundle, events)
    assert bundle.progression.scope_note in block
    assert "eu-stack signature population change:" in block, (
        "at least one delta row must render"
    )
    assert block.count("eu-stack signature population change:") <= _MAX_SIGNATURES


def test_no_continuity_or_ownership_claim_in_emitted_strings(tmp_path: Path) -> None:
    """D-10/T-18-10: neither the verified nor the suppressed progression
    rendering ever uses a per-thread continuity verb or a lock-possession
    claim — mirrors ``tests/test_eustack_report.py``'s own vocabulary gate,
    asserted over rendered output, never source text."""
    verified_events, verified_bundle = _progression_bundle(
        "dump_alpha.txt", "dump_bravo.txt", "dump_charlie.txt"
    )
    suppressed_events, suppressed_bundle = _two_untimestamped_dumps(tmp_path)

    verified_block, _ = render_eustack_facts(verified_bundle, verified_events)
    suppressed_block, _ = render_eustack_facts(suppressed_bundle, suppressed_events)
    assert verified_block and suppressed_block, "non-vacuity guard"

    prohibited = (*_CONTINUITY_VERBS, "deadlock", "owner", "holder")
    for block in (verified_block, suppressed_block):
        for term in prohibited:
            found = re.search(rf"\b{re.escape(term)}\b", block, re.IGNORECASE)
            assert found is None, f"prohibited term {term!r} found in rendered block"


# --- Plan 18-03 Task 2: V5 sanitisation gate + D-14 measured headroom -------


def test_control_chars_sanitised() -> None:
    """T-18-03/V5: a control-char-laden rules-derived subsystem string and a
    frame symbol are sanitised before interpolation, while the template's own
    untrusted-data framing sentence survives untouched (mirrors
    ``tests/test_perfmon_facts.py``'s injection/sanitisation test shape)."""
    hostile_subsystem = "job\x1b[31m\x07-queue"
    hostile_frame = "Frame\x9bWith\x00Control"
    frames = (hostile_frame,)
    events = [_synthetic_thread_event("dumpA.txt", frames, "c" * 16, "t0")]
    signatures = (
        SignatureGroup(
            frames=frames,
            thread_count=1,
            role="idle-parked",
            subsystem=hostile_subsystem,
            pattern=hostile_frame,
            frame_index=0,
            reason=None,
        ),
    )
    pools = (
        PoolOccupancy(
            subsystem=hostile_subsystem,
            total_threads=1,
            idle_threads=1,
            busy_threads=0,
            occupancy=0.0,
            signature_count=1,
        ),
    )
    bundle = _synthetic_bundle(signatures, pools)

    block, _ids = render_eustack_facts(bundle, events)

    assert sanitise(hostile_subsystem) in block
    assert sanitise(hostile_frame) in block
    assert "\x1b" not in block
    assert "\x9b" not in block
    assert "\x00" not in block
    assert "these facts ARE evidence" in block


def test_combined_fact_block_headroom_measured(tmp_path: Path) -> None:
    """D-14: measure the combined MCM + perfmon + eu-stack fact-block size
    (plus the triage template) against the excerpt budget ``PromptBudget.fit``
    reserves (``ctx_fallback=8192`` minus ``reserve_out=1024`` = 7168 tokens),
    using the identical ``len(text) // 4`` heuristic ``PromptBudget.estimate``
    falls back to. This is a regression bound on block growth, not a
    functional assertion — the message always prints the measured figure so
    it is recoverable from CI output."""
    from sift.pipeline.ingest import run_ingest

    repo_root = Path(__file__).resolve().parents[1]
    perfmon_case_input = repo_root / "eval" / "cases" / "perfmon-denial" / "input"

    combined_input = tmp_path / "input"
    combined_input.mkdir()
    for src in perfmon_case_input.iterdir():
        (combined_input / src.name).write_bytes(src.read_bytes())
    (combined_input / "reference_capture_derivative.txt").write_bytes(
        (_FIXTURES_DIR / "reference_capture_derivative.txt").read_bytes()
    )

    config = load_config({})
    noise = io.StringIO()
    db = tmp_path / "case.db"
    with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
        store = CaseStore(db)
        store.set_meta("input_dir", str(combined_input.resolve()))
        store.set_meta("adapter_overrides", "[]")
        run_ingest(db.parent.name, config, store)
    try:
        events = store.query_events()
        mcm_analysis = analyse_mcm(events, McmThresholdsConfig())
        mcm_text, _ = render_mcm_facts(mcm_analysis)
        perfmon_text, _ = render_perfmon_facts(analyse_perfmon(mcm_analysis, events))
        rules, rules_hash = load_rules()
        bundle = analyse_eustack_bundle(
            events, rules, rules_hash, EustackThresholdsConfig()
        )
        eustack_text, _ = render_eustack_facts(bundle, events)
    finally:
        store.close()

    assert mcm_text, "the combined case must yield a non-empty MCM block"
    assert perfmon_text, "the combined case must yield a non-empty perfmon block"
    assert eustack_text, "the combined case must yield a non-empty eu-stack block"

    template = hypothesise._load_triage_template()  # pyright: ignore[reportPrivateUsage]
    combined = template + mcm_text + perfmon_text + eustack_text
    estimated_tokens = max(1, len(combined) // 4)

    # Ceiling frozen at plan 18-03 authoring time (2026-07-26): measured
    # 4,528 tokens (18,115 chars) over this exact combined case (MCM 1,953 +
    # perfmon 2,161 + eu-stack 10,152 chars of fact-block text, plus the
    # 3,849-char triage template). Headroom to the ceiling below is
    # deliberate — this is a regression bound on unbounded growth, not a
    # tight pin on the current figure.
    _CEILING_TOKENS = 6000
    _EXCERPT_BUDGET_TOKENS = 8192 - 1024

    assert estimated_tokens < _CEILING_TOKENS, (
        f"combined fact-block+template size grew to an estimated "
        f"{estimated_tokens:,} tokens (ceiling {_CEILING_TOKENS:,}); against "
        f"the {_EXCERPT_BUDGET_TOKENS:,}-token excerpt budget PromptBudget.fit "
        f"reserves for cluster excerpts, this combined figure is "
        f"{'OVER' if estimated_tokens > _EXCERPT_BUDGET_TOKENS else 'under'} "
        "that budget on its own, before any excerpt is added"
    )
