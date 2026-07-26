"""Unit tests for ``pipeline.eustack_facts`` (EUS-10, D-05, D-16).

Mirrors ``tests/test_perfmon_facts.py``/``tests/test_mcm_facts.py``: the
versioned ``eustack_facts.md`` fragment carries zero authored digits (D-16 —
every figure originates in Python), and the id set ``render_eustack_facts``
returns is provably EXACTLY the set of ids printed as ``[evt:<id>]`` tokens in
its text — neither a superset nor a subset (D-05).
"""

from __future__ import annotations

import re
from pathlib import Path

from sift.adapters.eustack import EustackAdapter
from sift.config import EustackThresholdsConfig
from sift.pipeline.eustack import load_rules
from sift.pipeline.eustack_facts import _load_eustack_fragment, render_eustack_facts
from sift.pipeline.eustack_progression import analyse_eustack_bundle

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eustack"
_EVT_TOKEN_RE = re.compile(r"\[evt:([0-9a-f]{16})\]")


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
