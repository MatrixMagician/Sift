"""Direct tests for the case-command seam's genuinely new units (ADR 0019).

Pass 1 of ADR 0019 is a behaviour-preserving move, and the existing
``CliRunner`` suite is what proves the moved bodies still behave. These tests
cover the parts that are NOT moved code — the exit-code vocabulary and the
case-opening path — which the CLI suite only exercises incidentally.

No ``CliRunner``, no ``httpx``, no temp inference server: the point of the seam
is that this is possible.
"""

import sqlite3
from pathlib import Path

import pytest

from sift.commands import ExitCode, is_failure
from sift.store import CaseNotFound, CaseStore, CaseUnreadable, case_db_path, open_case

# --- the exit-code vocabulary (ADR 0005 / 0007 / 0010) --------------------


def test_exit_code_values_match_the_adr_contract() -> None:
    """The four numbers are the contract; automation branches on them."""
    assert (ExitCode.SUCCESS, ExitCode.ERROR, ExitCode.USAGE, ExitCode.DEGRADED) == (
        0,
        1,
        2,
        3,
    )


def test_success_is_falsy_so_if_code_still_works() -> None:
    """``cli.py`` branches on ``if code:`` at every call site — an IntEnum keeps
    that idiom honest, and a non-int enum would silently break it."""
    assert not ExitCode.SUCCESS
    assert ExitCode.ERROR and ExitCode.USAGE and ExitCode.DEGRADED


@pytest.mark.parametrize(
    ("code", "failed"),
    [
        (ExitCode.SUCCESS, False),
        (ExitCode.ERROR, True),
        (ExitCode.USAGE, True),
        # The load-bearing case: DEGRADED persisted its output, so the TUI must
        # show it rather than route it to the ErrorScreen (CLI-04 / ADR 0005).
        (ExitCode.DEGRADED, False),
    ],
)
def test_is_failure_treats_degraded_as_usable(code: ExitCode, failed: bool) -> None:
    assert is_failure(code) is failed


# --- case opening (the CLI's exit-1 contract, the TUI's ErrorScreen) -------


def test_open_case_returns_a_usable_store(tmp_path: Path) -> None:
    db_path = case_db_path(tmp_path, "good")
    db_path.parent.mkdir(parents=True)
    CaseStore(db_path).close()

    store = open_case(tmp_path, "good")
    try:
        assert store.get_meta("nothing-here") is None
    finally:
        store.close()


@pytest.mark.parametrize("name", ["..", "has/slash", "", "sp ace"])
def test_open_case_rejects_an_invalid_name(tmp_path: Path, name: str) -> None:
    """T-02-01: path traversal is refused before anything touches the disk."""
    with pytest.raises(CaseNotFound):
        open_case(tmp_path, name)


def test_open_case_missing_names_the_remedy(tmp_path: Path) -> None:
    """The message is the operator's next action, not just a diagnosis."""
    with pytest.raises(CaseNotFound) as excinfo:
        open_case(tmp_path, "absent")
    assert str(excinfo.value) == (
        "case 'absent' does not exist; create it with 'sift new'"
    )


def test_open_case_reports_a_corrupt_db_without_a_traceback(tmp_path: Path) -> None:
    """WR-02: corrupt evidence media fails loudly with a message, not a stack.

    The message is also pre-sanitised (T-04-01) because sqlite error text can
    echo attacker-controlled db bytes — but that guard is defence in depth and
    is NOT asserted here: a merely corrupt file yields "file is not a
    database", which carries nothing to strip. Asserting on it would be a test
    that cannot fail. ``sanitise`` has its own tests.
    """
    db_path = case_db_path(tmp_path, "corrupt")
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"this is definitely not a SQLite database" * 64)

    with pytest.raises(CaseUnreadable) as excinfo:
        open_case(tmp_path, "corrupt")
    assert str(excinfo.value).startswith("cannot open case 'corrupt': ")


def test_open_case_failures_are_distinguishable(tmp_path: Path) -> None:
    """The CLI maps both to exit 1, but the TUI and any future caller must be
    able to tell 'no such case' from 'this case is broken'."""
    assert not issubclass(CaseNotFound, CaseUnreadable)
    assert not issubclass(CaseUnreadable, CaseNotFound)
    assert issubclass(CaseUnreadable, Exception)


def test_open_case_does_not_create_a_case(tmp_path: Path) -> None:
    """A failed open must not leave a half-made case behind — ``sift new`` owns
    creation, and a typo at ``show`` should not fabricate one."""
    with pytest.raises(CaseNotFound):
        open_case(tmp_path, "typo")
    assert not (tmp_path / "cases" / "typo").exists()


def test_open_case_propagates_a_locked_database(tmp_path: Path) -> None:
    """A busy database is NOT a CaseUnreadable: the verdict path maps
    ``sqlite3.OperationalError`` itself (``commands/validate.py``), so swallowing
    it here would hide a lock behind 'corrupt evidence'."""
    db_path = case_db_path(tmp_path, "locked")
    db_path.parent.mkdir(parents=True)
    CaseStore(db_path).close()

    blocker = sqlite3.connect(db_path)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        store = open_case(tmp_path, "locked")
        try:
            with pytest.raises(sqlite3.OperationalError):
                store.set_meta("blocked", "1")
        finally:
            store.close()
    finally:
        blocker.close()
