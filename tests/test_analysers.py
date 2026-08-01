"""Registry invariants for the deterministic analysers (ADR 0021).

ADR 0021 declines to widen ``pipeline/analysers.py`` to also describe the
mcm/perfmon/eustack bundle commands, and rests that decision partly on the
duplicated ``sources`` list being enforced already. It is — but only
INCIDENTALLY: mis-scoping a bundle command produces a wrong bundle, and the
per-command bundle-content tests catch the wrongness. Rewrite one of those
fixtures and the guarantee leaves with it, silently, taking the ADR's argument
with it.

So the invariant is pinned here directly, in the terms the ADR states it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from sift.commands import eustack as eustack_cmd
from sift.commands import mcm as mcm_cmd
from sift.commands import perfmon as perfmon_cmd
from sift.pipeline.analysers import ANALYSERS

# Each registered analyser and the bundle command that must read the same
# events it does. An analyser is NOT required to have a bundle command (ADR
# 0021) — these three have one because they are operator-facing forensics
# products — so this map is deliberately explicit rather than derived.
_BUNDLE_COMMANDS = {
    "mcm": mcm_cmd,
    "perfmon": perfmon_cmd,
    "eustack": eustack_cmd,
}


def _query_events_sources(module: object) -> list[list[str]]:
    """Every ``store.query_events(sources=[...])`` literal in a module.

    Read out of the AST rather than matched against the source text: the claim
    is about the VALUE the command scopes to, and a reformat, a line break or a
    quote-style change must not fail this test for a reason that has nothing to
    do with the invariant.
    """
    tree = ast.parse(inspect.getsource(module))  # pyright: ignore[reportArgumentType]
    found: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "query_events":
            continue
        for kw in node.keywords:
            if kw.arg == "sources":
                found.append(ast.literal_eval(kw.value))
    return found


@pytest.mark.parametrize("name", sorted(_BUNDLE_COMMANDS))
def test_bundle_command_scopes_to_its_registered_sources(name: str) -> None:
    """A bundle command reads exactly the sources its registry entry declares.

    Both paths feed the SAME analyser function, so the two lists cannot
    legitimately differ: under-scoping silently drops events the analyser needs
    (perfmon without ``dsserrors`` loses the MCM denial episodes its trends are
    anchored on), over-scoping hydrates and zstd-decompresses rows the analyser
    filters straight back out.
    """
    entry = next(a for a in ANALYSERS if a.name == name)
    scopes = _query_events_sources(_BUNDLE_COMMANDS[name])
    assert len(scopes) == 1, (
        f"expected exactly one scoped read in commands/{name}.py, got {scopes}"
    )
    assert sorted(scopes[0]) == sorted(entry.sources)


def test_every_bundle_command_is_covered_by_this_file() -> None:
    """The map above must not silently fall behind ``commands/``.

    A fourth bundle command added without a registry entry — or without being
    listed here — would otherwise leave the ADR 0021 invariant unpinned for it,
    which is the exact rot this file exists to prevent.
    """
    commands_dir = Path(inspect.getfile(mcm_cmd)).parent
    with_bundles = {
        path.stem
        for path in commands_dir.glob("*.py")
        if not path.stem.startswith("_")
        and "write_bundle(" in path.read_text(encoding="utf-8")
    }
    assert with_bundles == set(_BUNDLE_COMMANDS)


def test_registered_sources_are_declared_once_per_analyser() -> None:
    """``ANALYSER_SOURCES`` stays the union the prompt path actually reads."""
    from sift.pipeline.analysers import ANALYSER_SOURCES

    assert ANALYSER_SOURCES == tuple(
        sorted({s for a in ANALYSERS for s in a.sources})
    )
