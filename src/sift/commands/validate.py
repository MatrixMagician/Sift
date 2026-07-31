"""``sift validate`` — append one immutable analyst verdict to a case (D003).

The shared body behind BOTH capture surfaces: the headless CLI command and the
review TUI's verdict modal call ``record_validation`` through here, so the two
are byte-equivalent (D004). Verdicts are history, never state — re-running
``sift analyze`` replaces hypotheses but keeps every recorded verdict, and no
update or delete path exists.
"""

import sqlite3
from collections.abc import Callable

from sift.commands._exit import ExitCode
from sift.render._util import sanitise
from sift.store import CaseStore
from sift.verdicts import TargetSpec, UnknownTargetError, record_validation


def run_validate(
    store: CaseStore,
    *,
    case: str,
    spec: TargetSpec,
    verdict: str,
    note: str = "",
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Record one verdict against an already-parsed target.

    The target SPEC is parsed by the caller (a malformed spec is a usage error
    that must fail before the store opens); whether the target EXISTS in this
    case is checked here, at record time, and is a failure rather than a usage
    error. Returns the ADR 0005/0007 exit code — 0 appended, 1 unknown target
    or locked database.
    """
    try:
        recorded = record_validation(store, spec, verdict, note=note)
    except UnknownTargetError as exc:
        echo(f"Error: {sanitise(str(exc))}")
        return ExitCode.ERROR
    except sqlite3.OperationalError as exc:
        # The service lets a locked/busy database bubble unswallowed
        # precisely so this command can map it: a semantic failure (exit
        # 1) with a sanitised message, never a traceback (WR-02).
        echo(
            f"Error: cannot record verdict for case {case!r}: "
            f"{sanitise(str(exc))}"
        )
        return ExitCode.ERROR
    # WR-01: a template target_id is caller-supplied text and the note
    # echoes nothing — sanitise the COMPLETE line, not per field. One
    # stdout line, scriptable: automation reads the verdict_id from here.
    echo(sanitise(
        f"Recorded verdict {recorded.verdict_id}: "
        f"{recorded.target_type}:{recorded.target_id} {recorded.verdict}"
    ))
    return ExitCode.SUCCESS
