"""Taskmap import: from the utility's live mapping to ``[[pu]]`` rows.

The nine queues Sift ships are the utility's compiled-in defaults, which its
own specification records as dead code in v1.25. The live mapping is the
``taskmap`` file, and it grows — the utility's version-skew warning exists for
exactly that. These tests cover the path off that snapshot.

The round-trip test is the load-bearing one: a converted taskmap must produce a
rules file that actually loads and attributes correctly, or the command is a
text generator that happens to look plausible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from sift.cli import app
from sift.pipeline.eustack import attribute_pu, load_rules
from sift.pipeline.taskmap import (
    parse_taskmap,
    subsystem_slug,
    to_pu_rows,
)

runner = CliRunner()

# The exact shape the utility's own parser reads, CRLF included: its
# `substr(1, len-2)` on a header strips the leading ':' AND one trailing
# character, which is the CR. `Delivery(NCSPU)` is spelled as the binary spells
# it, and `Cube Publication` stands in for a queue a newer taskmap carries that
# the 2022 built-in table does not.
_TASKMAP_BODY = (
    "LUT:37\r\n"
    ":Command PU:\r\n"
    "MSIDSSCommand::Process,Executing a client command\r\n"
    ":SQL Engine:\r\n"
    "CDSSSQLEngineServer,SQL generation\r\n"
    "CDSSSQLEngineServerImpl,SQL generation helper\r\n"
    ":Query Engine:\r\n"
    "CDSSQueryEngineServer,Executing SQL against the warehouse\r\n"
    ":Delivery(NCSPU):\r\n"
    "DSSPersistResultTask::Run,Persisting a subscription result\r\n"
    ":Cube Publication:\r\n"
    "DSSCubePublishTask::Run,Publishing an intelligent cube\r\n"
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHIPPED_RULES = _REPO_ROOT / "src" / "sift" / "rules" / "eustack_roles.toml"
_PU_BLOCK_MARKER = (
    "# ---------------------------------------------------------------------"
    "------\n# Processing-unit (PU) mapping"
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    # newline="" so the CRLF in the body survives verbatim rather than being
    # translated by Python's text-mode newline handling — the whole point of
    # the CRLF case.
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    return path


# --------------------------------------------------------------- parsing ---


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_line_endings_do_not_change_the_result(newline: str, tmp_path: Path) -> None:
    """CRLF and LF must parse identically.

    The utility blindly drops a header's last character to shed the CR, which
    silently truncates the queue name on an LF file. This parser reads the ':'
    delimiter instead, so a taskmap copied through a Unix workflow yields the
    same names as one straight off the share.
    """
    body = _TASKMAP_BODY.replace("\r\n", newline)
    parsed = parse_taskmap(body)
    assert parsed.lut == 37
    assert parsed.pu_names == [
        "Command PU",
        "SQL Engine",
        "Query Engine",
        "Delivery(NCSPU)",
        "Cube Publication",
    ]
    assert len(parsed.entries) == 6
    assert not parsed.skipped


def test_queue_names_survive_byte_exact() -> None:
    """`Delivery(NCSPU)` has no space before the parenthesis. Importing must
    not add one — hand-transcription already did that once, which is the whole
    reason this command exists."""
    parsed = parse_taskmap(_TASKMAP_BODY)
    assert "Delivery(NCSPU)" in parsed.pu_names
    assert "Delivery (NCSPU)" not in parsed.pu_names


def test_index_is_header_ordinal_and_shared_by_a_queues_signatures() -> None:
    """A queue with several dispatch frames is several entries sharing one
    index and name — the shape the rules loader accepts and aggregates."""
    parsed = parse_taskmap(_TASKMAP_BODY)
    sql = [e for e in parsed.entries if e.pu_name == "SQL Engine"]
    assert len(sql) == 2
    assert {e.pu_index for e in sql} == {1}
    assert [e.pu_index for e in parsed.entries] == [0, 1, 1, 2, 3, 4]


def test_unparseable_lines_are_reported_never_dropped() -> None:
    """A taskmap that is 95% readable is worth 95% of the rows, so a bad line
    is recorded with its number rather than aborting the import — but it is
    never silently discarded either."""
    body = _TASKMAP_BODY + "garbage with no comma\r\n"
    parsed = parse_taskmap(body)
    assert len(parsed.entries) == 6
    assert [n for n, _ in parsed.skipped] == [13]


def test_entry_before_any_header_belongs_to_no_queue() -> None:
    """An entry with no preceding ``:PU:`` header has no queue, and inventing
    one for it would fabricate an attribution."""
    parsed = parse_taskmap("LUT:1\r\nOrphan::Frame,description\r\n:A:\r\nB,c\r\n")
    assert [e.pu_name for e in parsed.entries] == ["A"]
    assert len(parsed.skipped) == 1


def test_empty_and_junk_inputs_yield_nothing_rather_than_raising() -> None:
    for body in ("", "\r\n\r\n", "not a taskmap at all\r\n"):
        parsed = parse_taskmap(body)
        assert parsed.entries == []
        assert parsed.pu_names == []


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Command PU", "command-pu"),
        ("Delivery(NCSPU)", "delivery-ncspu"),
        ("Document Data Preparation", "document-data-preparation"),
        ("!!!", "unnamed"),
    ],
)
def test_subsystem_slug_is_derived_and_stable(name: str, slug: str) -> None:
    assert subsystem_slug(name) == slug
    assert subsystem_slug(name) == subsystem_slug(name)


# --------------------------------------------------------------- rendering ---


def test_a_header_without_a_closing_colon_keeps_its_last_character() -> None:
    """The utility strips a header's leading ':' AND one trailing character,
    which its own grammar documents as ``":" pu-display-name <1 char>``. That
    trailing character is the CR of a CRLF file, so on a CRLF taskmap whose
    headers happen to close with ':' the two rules agree by coincidence.

    They stop agreeing the moment a header carries no closing colon — a shape
    the grammar permits — where blind truncation silently renames the queue
    ("Cube Publication" -> "Cube Publicatio"). A renamed queue is worse than a
    missing one: it attributes threads under a name that matches nothing an
    engineer can look up.
    """
    for body in (
        ":Cube Publication\r\nDSSCubePublishTask::Run,Publishing a cube\r\n",
        ":Cube Publication\nDSSCubePublishTask::Run,Publishing a cube\n",
    ):
        parsed = parse_taskmap(body)
        assert parsed.pu_names == ["Cube Publication"], body
        assert parsed.entries[0].pu_name == "Cube Publication"


def test_rendered_rows_are_deterministic_and_use_contains() -> None:
    """`contains` on every row reproduces the utility's substring semantics —
    its Lookup does a plain find over the whole block, so an `exact` import
    would silently stop matching stacks the utility matches."""
    parsed = parse_taskmap(_TASKMAP_BODY)
    rows = to_pu_rows(parsed)
    assert rows == to_pu_rows(parse_taskmap(_TASKMAP_BODY))
    assert rows.count("[[pu]]") == 6
    assert rows.count('match = "contains"') == 6
    assert "name = 'Delivery(NCSPU)'" in rows
    # The revision is carried so an operator can tell which taskmap generation
    # a rules file was built from.
    assert "revision (LUT): 37" in rows


def test_rendered_fragment_carries_no_meta_table(tmp_path: Path) -> None:
    """The output is a fragment by design: pasting it over a rules file must
    fail loudly at load rather than yield a file with no role rules.

    ``[meta]`` is a required field, so the loader's own validation is what
    enforces this — no separate guard is needed anywhere.
    """
    rows = to_pu_rows(parse_taskmap(_TASKMAP_BODY))
    assert "[meta]" not in rows
    path = tmp_path / "fragment-only.toml"
    path.write_text(rows, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_rules(str(path))


# --------------------------------------------------------------- round trip ---


def test_converted_taskmap_loads_and_attributes_correctly(tmp_path: Path) -> None:
    """THE test for this feature: a converted taskmap must produce a rules file
    that loads and attributes correctly, end to end.

    Without this, `sift taskmap` is a text generator whose output happens to
    look plausible. It includes a queue (`Cube Publication`) that the shipped
    2022 table does not carry, which is the entire reason the import path
    exists — and checks that depth-wins attribution still holds over imported
    rows, so an import cannot quietly reintroduce the utility's own bug.
    """
    if not _SHIPPED_RULES.exists():  # pragma: no cover — repo layout guard
        pytest.skip("shipped rules file not found")
    shipped = _SHIPPED_RULES.read_text(encoding="utf-8")
    head = shipped.split(_PU_BLOCK_MARKER)[0]
    assert "[meta]" in head and "[[rule]]" in head

    taskmap_path = _write(tmp_path, "taskmap", _TASKMAP_BODY)
    generated = tmp_path / "generated.toml"
    result = runner.invoke(app, ["taskmap", str(taskmap_path), "--out", str(generated)])
    assert result.exit_code == 0, result.output

    combined = tmp_path / "roles.toml"
    combined.write_text(head + generated.read_text(encoding="utf-8"), encoding="utf-8")

    rules, rules_hash = load_rules(str(combined))
    assert len(rules.pu) == 6
    assert rules_hash

    for frame, expected in [
        ("MSIDSSCommand::Process()", "Command PU"),
        # Substring semantics: an Impl symbol still matches its queue.
        ("CDSSSQLEngineServerImpl::Foo()", "SQL Engine"),
        ("DSSPersistResultTask::Run()", "Delivery(NCSPU)"),
        # The queue the shipped table has never heard of.
        ("DSSCubePublishTask::Run()", "Cube Publication"),
    ]:
        attribution = attribute_pu((frame,), rules)
        assert attribution is not None, frame
        assert attribution.name == expected, frame

    # Depth still decides over imported rows: the dispatch frame deeper in the
    # stack wins, not the row that appears first in the file.
    deep = attribute_pu(
        ("CDSSSQLEngineServer::Helper()", "DSSCubePublishTask::Run()"), rules
    )
    assert deep is not None
    assert deep.name == "Cube Publication"


# --------------------------------------------------------------------- CLI ---


def test_cli_writes_rows_and_reports_the_revision(tmp_path: Path) -> None:
    path = _write(tmp_path, "taskmap", _TASKMAP_BODY)
    result = runner.invoke(app, ["taskmap", str(path)])
    assert result.exit_code == 0, result.output
    assert "[[pu]]" in result.stdout
    assert "Converted 5 processing units, 6 signatures" in result.output
    assert "taskmap revision 37" in result.output


def test_cli_reports_skipped_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, "taskmap", _TASKMAP_BODY + "junk line\r\n")
    result = runner.invoke(app, ["taskmap", str(path)])
    assert result.exit_code == 0, result.output
    assert "skipped as unrecognised" in result.output


def test_cli_rejects_a_file_that_is_not_a_taskmap(tmp_path: Path) -> None:
    """Writing an empty fragment would look like success."""
    path = _write(tmp_path, "notes.txt", "just some prose\nwith no entries\n")
    result = runner.invoke(app, ["taskmap", str(path)])
    assert result.exit_code == 1
    assert "is this a taskmap file?" in result.output


def test_cli_reports_an_unreadable_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["taskmap", str(tmp_path / "absent")])
    assert result.exit_code == 1
    assert "cannot read taskmap" in result.output


# ------------------------------------------------------------- encodings ---
#
# The taskmap is cached and edited on Windows, so a UTF-8 BOM and UTF-16 are
# realistic shapes rather than hypothetical ones. Both were found by probing
# real-world encodings, and both failed in ways that would have wasted an
# engineer's afternoon.


@pytest.mark.parametrize("first_line", ["LUT:37\r\n", ""])
def test_utf8_bom_does_not_break_the_import(
    first_line: str, tmp_path: Path
) -> None:
    """A BOM lands on the FIRST line, whichever kind that is.

    Ahead of ``LUT:`` it makes the revision line fail to match, losing the
    revision silently. Ahead of the first ``:PU:`` header it makes the
    ``startswith(':')`` test fail, which drops that queue — and on a
    header-first file (no ``LUT:`` line at all) drops the entire import, so the
    command reports "is this a taskmap file?" about a file that is one.
    """
    body = (
        first_line
        + ":Command PU:\r\n"
        + "MSIDSSCommand::Process,Executing a client command\r\n"
    )
    path = tmp_path / "taskmap"
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))

    parsed = parse_taskmap(path.read_text(encoding="utf-8"))
    assert parsed.pu_names == ["Command PU"]
    assert len(parsed.entries) == 1
    assert parsed.lut == (37 if first_line else None)

    result = runner.invoke(app, ["taskmap", str(path)])
    assert result.exit_code == 0, result.output
    assert "name = 'Command PU'" in result.stdout


def test_utf16_is_diagnosed_rather_than_read_as_mojibake(tmp_path: Path) -> None:
    """UTF-16 decoded as UTF-8 becomes NUL-riddled mojibake that parses to zero
    entries. Reporting that as "is this a taskmap file?" would send an engineer
    looking for the wrong problem, so the encoding is named and a fix given."""
    path = tmp_path / "taskmap"
    path.write_bytes(_TASKMAP_BODY.encode("utf-16"))
    result = runner.invoke(app, ["taskmap", str(path)])
    assert result.exit_code == 1
    assert "UTF-16" in result.output
    assert "iconv" in result.output
    assert "is this a taskmap file?" not in result.output
