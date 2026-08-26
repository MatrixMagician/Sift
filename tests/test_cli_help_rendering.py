"""``sift --help`` must show the text the docstrings actually say.

Typer renders help through Rich, which treats ``[...]`` as a style tag and
silently deletes anything it does not recognise. Every square bracket an
operator needs to read is therefore at risk: ``sift[pdf]`` rendered as ``sift``,
and ``taskmap``'s whole purpose line, "convert a taskmap into ``[[pu]]`` rows",
rendered as "into ``[]`` rows" in the top-level command list.

Nothing catches this in review, because the source is correct — the damage
happens at render. So these tests render the help the way a user sees it and
assert on the output, not on the docstring.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from sift.cli import app

runner = CliRunner()

_COMMANDS = (
    "new",
    "list",
    "delete",
    "ingest",
    "show",
    "analyze",
    "report",
    "validate",
    "tui",
    "mcm",
    "perfmon",
    "eustack",
    "taskmap",
    "eval",
    "doctor",
)

# Bracketed strings each command's help must show verbatim. Every one of these
# is a real name an operator has to type or look for: a pip extra, a TOML table.
_MUST_SURVIVE: dict[str, tuple[str, ...]] = {
    "report": ("sift[pdf]",),
    "taskmap": ("[[pu]]", "[eustack] rules_path", "[meta]"),
}


def _help(*argv: str) -> str:
    result = runner.invoke(app, [*argv, "--help"])
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize(("command", "expected"), sorted(_MUST_SURVIVE.items()))
def test_bracketed_names_survive_rich_rendering(
    command: str, expected: tuple[str, ...]
) -> None:
    """A TOML table name or pip extra must reach the screen intact.

    Rich swallows an unescaped tag whole, so the failure is silent deletion
    rather than mangling: the sentence still reads as a sentence, just with the
    one word the operator needed missing.
    """
    output = " ".join(_help(command).split())
    for name in expected:
        assert name in output, f"{command} --help lost {name!r} to Rich markup"


def test_no_command_help_shows_an_empty_bracket_pair() -> None:
    """``[]`` in rendered help is the signature of a swallowed tag.

    A catch-all over every command, so a newly added one is covered without
    anyone remembering to extend the table above.
    """
    offenders = [
        command for command in _COMMANDS if "[]" in " ".join(_help(command).split())
    ]
    assert not offenders, f"Rich swallowed a markup tag in: {offenders}"


def test_top_level_command_list_is_intact() -> None:
    """The command list re-renders each summary line and can swallow tags again.

    ``taskmap``'s summary was mangled here while its own ``--help`` page was
    fine, so asserting only on the per-command pages would have missed it.
    """
    assert "[]" not in " ".join(_help().split())


def test_every_command_help_renders() -> None:
    """A smoke check that the command table above has not gone stale."""
    for command in _COMMANDS:
        assert _help(command)


def test_docstrings_with_brackets_are_raw_strings() -> None:
    """The escape Rich needs (``\\[``) is not a valid Python escape.

    A non-raw docstring containing it raises SyntaxWarning today and is a
    SyntaxError on a future Python, so the escape and the ``r`` prefix have to
    travel together. Pin the pairing rather than trusting it: the failure mode
    is a module that no longer imports.
    """
    import ast
    import inspect

    import sift.cli

    source = inspect.getsource(sift.cli)
    lines = source.splitlines()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc is None or "\\[" not in doc:
            continue
        # The docstring node's own first line carries any string prefix.
        literal = node.body[0]
        opener = lines[literal.lineno - 1].lstrip()
        assert opener.startswith("r"), (
            f"{node.name}'s docstring contains a Rich escape but is not a raw "
            f"string; it would raise SyntaxWarning: {opener[:60]!r}"
        )
