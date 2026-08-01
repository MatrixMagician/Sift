"""``sift validate`` — append one immutable analyst verdict to a case (D003).

The CLI's mapping of :func:`sift.verdicts.record_validation`, which is the
shared body and the single write path both capture surfaces land on (D004).
The TUI's verdict modal does **not** call this function: it calls
``record_validation`` directly, because it needs the ``RecordedVerdict`` this
mapping discards (the object travels out through ``dismiss`` as the modal's
commit gate) and it stays open with an inline message rather than returning a
code. It therefore maps failures its own way — a fixed "locked" wording, no
``case`` name in the text.

What the two surfaces share is the ROW, never the message. An earlier version of
this docstring claimed they were "byte-equivalent", which was never true of the
output and is not the guarantee D004 makes.

Verdicts are history, never state — re-running ``sift analyze`` replaces
hypotheses but keeps every recorded verdict, and no update or delete path exists.
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
    except sqlite3.Error as exc:
        # The service lets storage failures bubble unswallowed precisely so
        # this command can map them: a semantic failure (exit 1) with a
        # sanitised message, never a traceback (WR-02).
        #
        # sqlite3.Error, not OperationalError alone — "the write did not
        # land" is one outcome to the operator whether the cause was a busy
        # lock, a corrupt page (DatabaseError), a rejected CHECK constraint
        # (IntegrityError) or a store some other path already closed
        # (ProgrammingError). The narrower catch let the last three cross the
        # seam as tracebacks, which ADR 0019 forbids and the comment above
        # already claimed was impossible.
        #
        # ValueError and TargetSpecError deliberately still raise. An invalid
        # verdict state or a malformed spec is a bug in the CALLER, not an
        # outage the operator can act on, and mapping it to an exit code would
        # ship that bug silently (ADR 0019, "failures return, never raise").
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
