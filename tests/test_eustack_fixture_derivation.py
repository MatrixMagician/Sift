"""The fixture-derivation tool must keep importing and running.

``tests/fixtures/eustack/derive_reference_capture_derivative.py`` is the
provenance record for the committed 93-signature reference derivative: it is
how that fixture was produced, and re-deriving it is the only way to answer
"was this fixture shaped to agree with the analyser?". Pytest does not collect
it (its filename does not match ``test_*.py``) and it cannot run in CI (its
real input is an out-of-repo capture), so nothing exercised it — and it had in
fact been broken since 252484f, which moved the header regex it imports from
``adapters.eustack`` into ``adapters.threaddump``. The tool raised
``ImportError`` on any invocation.

These tests close that gap without needing the private capture: the committed
derivative is itself a valid eu-stack dump, so the tool can be run over its own
output. That exercises every stage (block splitting, signature grouping, header
renumbering, preamble assembly) against real captured frames.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_TOOL_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "eustack"
    / "derive_reference_capture_derivative.py"
)
_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "eustack"
    / "reference_capture_derivative.txt"
)


def _load_tool() -> ModuleType:
    """Import the tool by path — its directory is not a package."""
    spec = importlib.util.spec_from_file_location(
        "derive_reference_capture_derivative", _TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_tool_imports() -> None:
    """The regression that actually shipped: the tool would not even import."""
    _load_tool()


def test_header_rule_is_the_shipped_one(tool: ModuleType) -> None:
    """The tool must borrow the adapter's header rule, never restate it.

    Sharing is the point of the import — a second copy of the regex could drift
    from the parser and derive a fixture the parser reads differently.
    """
    from sift.adapters.threaddump import EUSTACK_GRAMMAR

    assert tool._TID_RE is EUSTACK_GRAMMAR.header


def test_round_trip_over_the_committed_derivative(tool: ModuleType) -> None:
    """Running the tool over its own output reproduces every signature.

    The committed fixture keeps 105 threads across 93 signatures, with five
    threads for each of the three highest-population signatures. Re-deriving
    from it must find those same 93 signatures and, applying the same two-tier
    cap to the already-capped populations, emit 5*3 + 1*90 = 105 threads again:
    the derivation is idempotent on its own output, which is what makes it a
    usable provenance check.
    """
    text = _FIXTURE_PATH.read_text(encoding="utf-8")
    blocks = list(tool.iter_thread_blocks(text))
    assert len(blocks) == 105

    groups = tool.group_by_signature(blocks)
    assert len(groups) == 93

    high = tool.high_population_signatures(groups)
    body, thread_count = tool.build_derivative_body(groups, high)
    assert thread_count == 105
    assert body.startswith("TID 100001:")
    # Headers are renumbered sequentially from the synthetic base, so the
    # derivative can never carry a real thread id from the source capture.
    assert "TID 100105:" in body
    assert len(list(tool.iter_thread_blocks(body))) == thread_count


def test_scaled_mode_thins_by_population(tool: ModuleType) -> None:
    """``--scale N`` keeps ``round(count / N)`` per signature, zero included.

    On the committed fixture, scale 5 rounds the three five-thread signatures
    to one apiece and every single-thread signature to zero, which is the
    thread-proportion faithfulness the mode exists for.
    """
    text = _FIXTURE_PATH.read_text(encoding="utf-8")
    groups = tool.group_by_signature(tool.iter_thread_blocks(text))
    _body, thread_count = tool.build_derivative_body_scaled(groups, 5)
    assert thread_count == 3


def test_preamble_states_the_policy_that_produced_it(tool: ModuleType) -> None:
    """A reader must be able to tell the two derivation modes apart."""
    capped = tool.build_preamble(3902, 93, 105, 93)
    assert "cap policy" in capped
    assert "scale policy" not in capped

    scaled = tool.build_preamble(3902, 93, 150, 40, scale=26)
    assert "scale policy: kept round(count / 26)" in scaled
    assert "cap policy" not in scaled
