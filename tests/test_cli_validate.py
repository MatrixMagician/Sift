"""``sift validate`` CLI-surface tests (S01, ADR 0005/0007 exit codes).

ADR 0019: what is left here is the part the CLI can get *independently* wrong.
The exit-2 branches are genuinely the translation layer's — the "exactly one
verdict flag" check lives at ``cli.py:618`` and has no seam-side existence, and
a malformed target spec must fail *before* the store opens (the parse-before-
open ordering the ADR pins), which is an ordering only the command body can
break. The absent-case exit 1 is ``open_case``'s, raised outside the seam. Each
verdict flag's mapping to its stored state is flag wiring by definition.

``run_validate``'s own branches — unknown target, locked database, the
append-only history — moved to ``tests/test_commands_validate.py``; the seeded
case both files share lives in ``_validate_fixtures``.

Every branch still runs against a real seeded ``case.db`` through Typer's
CliRunner — no store mocks anywhere (the slice proof level).
"""

from __future__ import annotations

import pytest
from _validate_fixtures import CASE, HYP_TITLE, build_case, verdicts
from typer.testing import CliRunner

from sift.cli import app
from sift.commands import ExitCode
from sift.store import CaseStore
from sift.verdicts import TargetSpec

runner = CliRunner()


# --- success paths (exit 0) --------------------------------------------------


def test_validate_confirm_records_and_prints_id_and_target() -> None:
    # The assembled CLI path, end to end: flags and --note reach the body, the
    # verdict lands in the store, and the body's one stdout line survives
    # Click's output path intact.
    build_case()
    result = runner.invoke(
        app,
        [
            "validate",
            CASE,
            "hypothesis:0",
            "--confirm",
            "--note",
            "Root cause confirmed on the customer call",
        ],
    )
    assert result.exit_code == 0, result.output
    (row,) = verdicts()
    assert row.verdict == "confirmed"
    assert row.note == "Root cause confirmed on the customer call"
    assert row.context["title"] == HYP_TITLE
    # Scriptable stdout: the verdict_id and the canonical target both appear.
    assert row.verdict_id in result.output
    assert "hypothesis:0" in result.output


@pytest.mark.parametrize(
    ("flag", "state"),
    [
        ("--confirm", "confirmed"),
        ("--reject", "rejected"),
        ("--uncertain", "uncertain"),
    ],
)
def test_validate_each_flag_maps_to_its_state(flag: str, state: str) -> None:
    build_case()
    result = runner.invoke(app, ["validate", CASE, "hypothesis:0", flag])
    assert result.exit_code == 0, result.output
    (row,) = verdicts()
    assert row.verdict == state
    assert row.note == ""


# --- usage errors (exit 2) ---------------------------------------------------


def test_validate_no_verdict_flag_is_usage_error() -> None:
    build_case()
    result = runner.invoke(app, ["validate", CASE, "hypothesis:0"])
    assert result.exit_code == 2, result.output
    assert "exactly one of --confirm, --reject or --uncertain" in result.output
    assert verdicts() == []


def test_validate_multiple_verdict_flags_is_usage_error() -> None:
    build_case()
    result = runner.invoke(
        app, ["validate", CASE, "hypothesis:0", "--confirm", "--reject"]
    )
    assert result.exit_code == 2, result.output
    assert "exactly one of --confirm, --reject or --uncertain" in result.output
    assert verdicts() == []


@pytest.mark.parametrize("spec", ["0", "hyp:0", "hypothesis:", "cluster:x2"])
def test_validate_malformed_target_is_usage_error(spec: str) -> None:
    build_case()
    result = runner.invoke(app, ["validate", CASE, spec, "--confirm"])
    assert result.exit_code == 2, result.output
    assert "Error:" in result.output
    assert verdicts() == []


def test_validate_malformed_target_names_valid_types() -> None:
    build_case()
    result = runner.invoke(app, ["validate", CASE, "hyp:0", "--confirm"])
    assert result.exit_code == 2, result.output
    assert "cluster, hypothesis, template" in result.output


# --- semantic failure the CLI owns (exit 1) ----------------------------------


def test_validate_absent_case_exits_one() -> None:
    # open_case's failure, mapped by cli.py — it happens before the seam.
    result = runner.invoke(app, ["validate", "ghost", "hypothesis:0", "--confirm"])
    assert result.exit_code == 1, result.output
    assert "does not exist" in result.output


def test_validate_body_failure_code_reaches_the_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero code returned by ``run_validate`` becomes the process status.

    The body's failures — unknown target, locked database — are tested at the
    seam, where they are one call each. Their translation into ``typer.Exit``
    is a separate joint that no seam test can exercise, so it is pinned here
    with a faked body: without this, every remaining CliRunner test in this
    file would stay green with that translation deleted.
    """
    build_case()

    def fake(
        store: CaseStore, *, case: str, spec: TargetSpec, verdict: str, **kwargs: object
    ) -> ExitCode:
        return ExitCode.ERROR

    monkeypatch.setattr("sift.cli.run_validate", fake)
    result = runner.invoke(app, ["validate", CASE, "hypothesis:0", "--confirm"])
    assert result.exit_code == 1, result.output
