"""Multi-dump ordering and progression tests (EUS-07/08).

Covers ``resolve_dump_order``'s three states (single dump, D-01 timestamp,
D-02 filename fallback with its loud flag) and ``compute_progression``'s
per-signature deltas over the synthetic fixture set in
``tests/fixtures/eustack/progression/`` (see that directory's own
``derive_progression_fixtures.py`` for the exact populations and the
properties they're chosen to exercise).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from sift.adapters.eustack import EustackAdapter
from sift.config import load_config
from sift.models import Event
from sift.pipeline.eustack import load_rules
from sift.pipeline.eustack_progression import (
    ORDER_BASIS_FILENAME,
    ORDER_BASIS_SINGLE,
    ORDER_BASIS_TIMESTAMP,
    ORDERING_UNVERIFIED_DIMENSION,
    ORDERING_UNVERIFIED_MESSAGE,
    PROGRESSION_SCOPE_NOTE,
    EustackBundle,
    analyse_eustack_bundle,
    resolve_dump_order,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eustack" / "progression"
_RULES, _RULES_HASH = load_rules()
_THRESHOLDS = load_config().eustack.thresholds


def _parse_progression_fixture(name: str) -> list[Event]:
    """Parse one named fixture from ``tests/fixtures/eustack/progression/``
    with the shipped ``EustackAdapter`` — never a hand-built ``Event`` list,
    so these tests exercise the same adapter path production traffic does.
    """
    adapter = EustackAdapter()
    adapter.input_root = _FIXTURE_DIR
    return list(adapter.parse(_FIXTURE_DIR / name, "progression-test"))


def _bundle_for(*names: str) -> EustackBundle:
    """Concatenate several fixtures' events and run the full bundle
    orchestration over them, exactly as ``sift eustack`` would for a
    multi-dump case.
    """
    events: list[Event] = []
    for name in names:
        events.extend(_parse_progression_fixture(name))
    return analyse_eustack_bundle(events, _RULES, _RULES_HASH, _THRESHOLDS)


def test_order_by_timestamp_ignores_filename_order() -> None:
    """D-01: with every dump timestamped, the alpha/bravo/charlie trio
    resolves to charlie, bravo, alpha (chronological) — the exact REVERSE of
    sorted filename order, so this cannot pass by ordering on filename by
    accident.
    """
    bundle = _bundle_for("dump_alpha.txt", "dump_bravo.txt", "dump_charlie.txt")
    order = tuple(d.source_file for d in bundle.progression.dumps)
    assert order == ("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    assert order != tuple(sorted(order))
    assert bundle.progression.order_basis == ORDER_BASIS_TIMESTAMP
    assert bundle.progression.ordering_flags == ()


def test_order_fallback_flagged_when_any_dump_untimestamped() -> None:
    """D-02: charlie (timestamped) plus delta (no header timestamp) falls
    back to sorted filename order and raises exactly one ordering flag."""
    bundle = _bundle_for("dump_charlie.txt", "dump_delta_nots.txt")
    order = tuple(d.source_file for d in bundle.progression.dumps)
    assert order == ("dump_charlie.txt", "dump_delta_nots.txt")
    assert bundle.progression.order_basis == ORDER_BASIS_FILENAME
    assert len(bundle.progression.ordering_flags) == 1
    assert bundle.progression.ordering_flags[0].dimension == (
        ORDERING_UNVERIFIED_DIMENSION
    )


def _threadless_event(source_file: str) -> Event:
    """A preamble-only event with no ``TID`` line — the shape a truncated or
    failed eu-stack capture, or any file an operator routes to the
    ``eustack`` adapter via ``--adapter glob=name`` without a ``TID <n>:``
    line, produces."""
    return Event(
        event_id="0" * 16,
        case_id="c",
        ts=None,
        ts_confidence="missing",
        source="eustack",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="unknown",
        component=None,
        thread=None,
        session=None,
        message="",
        attrs={},
        raw="",
    )


def _threaded_event(source_file: str) -> Event:
    return Event(
        event_id="1" * 16,
        case_id="c",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ts_confidence="exact",
        source="eustack",
        source_file=source_file,
        line_start=1,
        line_end=1,
        severity="unknown",
        component=None,
        thread="1",
        session=None,
        message="",
        attrs={},
        raw="",
    )


def test_order_resolves_without_crash_when_a_dump_has_no_thread_events() -> None:
    """CR-01 regression: a dump group with zero thread-bearing events (e.g. a
    truncated capture) must not crash ``resolve_dump_order`` with an
    unhandled ``StopIteration``. A ``None`` representative is treated the
    same as ``ts_confidence == "missing"``, forcing the D-02 filename
    fallback under its flag rather than raising."""
    dumps = {
        "dump_good.txt": [_threaded_event("dump_good.txt")],
        "dump_empty.txt": [_threadless_event("dump_empty.txt")],
    }
    order, basis, flags = resolve_dump_order(dumps)
    assert order == ("dump_empty.txt", "dump_good.txt")
    assert basis == ORDER_BASIS_FILENAME
    assert len(flags) == 1


def test_order_fallback_still_renders_progression() -> None:
    """The D-02 flag declares the limitation; it never suppresses the
    progression itself."""
    bundle = _bundle_for("dump_charlie.txt", "dump_delta_nots.txt")
    assert len(bundle.progression.signatures) > 0


def test_no_timestamp_is_invented() -> None:
    """The untimestamped dump's own ``DumpSlice`` keeps ``ts is None`` and
    ``ts_confidence == "missing"`` after ordering — nothing is assigned,
    inferred or filesystem-derived (ADR 0012 precedent)."""
    bundle = _bundle_for("dump_charlie.txt", "dump_delta_nots.txt")
    delta_slice = next(
        d for d in bundle.progression.dumps if d.source_file == "dump_delta_nots.txt"
    )
    assert delta_slice.ts is None
    assert delta_slice.ts_confidence == "missing"


def test_single_dump_needs_no_ordering() -> None:
    """One dump needs no ordering decision: ``ORDER_BASIS_SINGLE`` and zero
    flags."""
    bundle = _bundle_for("dump_alpha.txt")
    assert bundle.progression.order_basis == ORDER_BASIS_SINGLE
    assert bundle.progression.ordering_flags == ()


def _signature(bundle: EustackBundle, label: str) -> object:
    """Find the progression row for a fixture signature by its matched
    frame — normalised (``pipeline.eustack.normalise``: tail dropped,
    version suffix dropped) since that is the exact string ``compute_
    progression`` stores, distinct for each of the five fixture signatures
    (``derive_progression_fixtures.py``)."""
    matched_frame = {
        "warehouse": "CDSSQueryEngine::WaitUntilFinished",
        "parked": "MSIQTask::GetNextPreferredJob",
        "stable": "_shi_allocBlock",
        "newcomer": "curl_multi_poll",
        "departing": "MSICommandQTask::GetNextCommand",
    }[label]
    for signature in bundle.progression.signatures:
        if signature.matched_frame == matched_frame:
            return signature
    raise AssertionError(f"no progression row found for signature {label!r}")


def test_step_and_overall_deltas_disagree_on_grew_then_shrank() -> None:
    """D-08: warehouse over charlie/bravo/alpha runs 3 -> 7 -> 5 — step
    deltas +4/-2 disagree with the overall +2, and the module carries both
    rather than flattening the sequence to one figure."""
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    warehouse = _signature(bundle, "warehouse")
    assert warehouse.counts == (3, 7, 5)
    assert warehouse.step_deltas == (4, -2)
    assert warehouse.overall_delta == 2


def test_appeared_and_vanished_signatures() -> None:
    """D-09: newcomer (absent in charlie, present in bravo/alpha) is
    appeared-not-vanished; departing (present in charlie only) is the
    converse."""
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")

    newcomer = _signature(bundle, "newcomer")
    assert newcomer.counts == (0, 2, 2)
    assert newcomer.appeared is True
    assert newcomer.vanished is False

    departing = _signature(bundle, "departing")
    assert departing.counts == (2, 0, 0)
    assert departing.appeared is False
    assert departing.vanished is True


def test_unchanged_signature_has_zero_delta() -> None:
    """A signature present with the same count in every dump has a zero
    overall delta and all-zero step deltas, and still appears in
    ``ProgressionAnalysis.signatures`` (no cap, D-09)."""
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    stable = _signature(bundle, "stable")
    assert stable.counts == (4, 4, 4)
    assert stable.overall_delta == 0
    assert stable.step_deltas == (0, 0)
    assert stable in bundle.progression.signatures


def test_progression_carries_every_signature_no_cap() -> None:
    """No cap is applied to the signature set (D-09's changed-only filter is
    a rendering concern for 17-03): all five fixture signatures — including
    the unchanged ``stable`` — are present in ``ProgressionAnalysis.
    signatures`` so the CSV can export the unchanged ones too."""
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    labels = ("warehouse", "parked", "stable", "newcomer", "departing")
    assert len(bundle.progression.signatures) == len(labels)
    for label in labels:
        _signature(bundle, label)  # raises AssertionError if missing


def test_progression_ranking_is_a_total_order() -> None:
    """Two independent ``analyse_eustack_bundle`` calls over the same events,
    one with the input event list reversed, produce an identical
    ``signatures`` tuple — the sort key is a true total order, not merely
    stable over one particular input ordering."""
    events: list[Event] = []
    for name in ("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt"):
        events.extend(_parse_progression_fixture(name))

    forward = analyse_eustack_bundle(events, _RULES, _RULES_HASH, _THRESHOLDS)
    reversed_bundle = analyse_eustack_bundle(
        list(reversed(events)), _RULES, _RULES_HASH, _THRESHOLDS
    )
    assert forward.progression.signatures == reversed_bundle.progression.signatures


def test_saturation_computed_on_last_dump_only() -> None:
    """D-11: adding dumps never changes which dump the classification and
    saturation figures come from — ``total_threads`` equals the LAST dump's
    (alpha's) own 17 threads, not the 55-thread sum across all three dumps."""
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    assert bundle.analysis.total_threads == 17
    assert bundle.analysis.total_threads != 55


def test_no_per_tid_claim_in_progression_strings() -> None:
    """D-10: no module-level string or emitted ``OrderingFlag.message`` makes
    a per-thread continuity claim. Mirrors the word-boundary,
    non-vacuity-guarded technique
    ``test_ownership_blind_vocabulary_absent_from_source_and_emitted_output``
    (tests/test_eustack_rules.py) already uses.

    ``PROGRESSION_SCOPE_NOTE`` legitimately contains the bare word "TID"
    while explaining that TID reuse means continuity CANNOT be established
    — that is the D-10 rationale itself, not a claim. What must never appear
    is a continuity VERB (persisted/remained/stayed/"still blocked") or an
    actual thread-identifier VALUE token (e.g. "TID 100001") standing in for
    a specific thread.
    """
    candidates: list[str] = [
        ORDER_BASIS_SINGLE,
        ORDER_BASIS_TIMESTAMP,
        ORDER_BASIS_FILENAME,
        PROGRESSION_SCOPE_NOTE,
        ORDERING_UNVERIFIED_MESSAGE,
    ]
    bundle = _bundle_for("dump_charlie.txt", "dump_delta_nots.txt")
    candidates.extend(flag.message for flag in bundle.progression.ordering_flags)

    assert candidates, "candidate string set must be non-empty"

    continuity_verbs = ("persisted", "remained", "stayed", "still blocked")
    for candidate in candidates:
        for verb in continuity_verbs:
            found = re.search(rf"\b{re.escape(verb)}\b", candidate, re.IGNORECASE)
            assert found is None, (
                f"continuity verb {verb!r} found in emitted string {candidate!r}"
            )
        # A concrete thread-identifier VALUE (e.g. "TID 100001") would imply
        # a specific thread is being tracked across dumps; the bare word
        # "TID" alone (as in PROGRESSION_SCOPE_NOTE) is not such a claim.
        identifier_value = re.search(r"\bTID\W{0,3}\d+\b", candidate, re.IGNORECASE)
        assert identifier_value is None, (
            f"thread-identifier value found in emitted string {candidate!r}"
        )
