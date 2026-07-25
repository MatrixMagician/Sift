"""Multi-dump ordering and progression tests (EUS-07/08).

Covers ``resolve_dump_order``'s three states (single dump, D-01 timestamp,
D-02 filename fallback with its loud flag) and ``compute_progression``'s
per-signature deltas over the synthetic fixture set in
``tests/fixtures/eustack/progression/`` (see that directory's own
``derive_progression_fixtures.py`` for the exact populations and the
properties they're chosen to exercise).
"""

from __future__ import annotations

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
    EustackBundle,
    analyse_eustack_bundle,
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
