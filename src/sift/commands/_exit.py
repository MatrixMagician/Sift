"""The exit-code vocabulary every case command returns (ADR 0019).

Four meanings, fixed by ADR 0005 (``analyze``), ADR 0007 (``report``) and
ADR 0010 (``eval``). Individual commands use a SUBSET — ADR 0007 records that
``report`` deliberately never returns ``DEGRADED``, because a degraded case
still produced a report and the banner communicates the degradation.

This module only names the codes; it does not decide which command may return
which. That stays with each command and its ADR.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """A case command's outcome, as the process exit status it maps to.

    ``IntEnum`` rather than a plain int so pyright rejects a command inventing
    a fifth code, and so ``if code:`` keeps working — ``SUCCESS`` is falsy.
    """

    SUCCESS = 0
    ERROR = 1
    USAGE = 2
    DEGRADED = 3
    """Degraded but PERSISTED: the run completed and its output was stored,
    flagged. Never a failure — ``analyze`` returns it, ``report`` does not."""


def is_failure(code: ExitCode) -> bool:
    """Whether a code means nothing usable was produced.

    For adapters that KEEP RUNNING after a command and must decide what to
    show — the TUI, which routes a failure to its ErrorScreen and anything
    else to the results. ``DEGRADED`` is NOT a failure here: its output was
    persisted and is worth showing.

    The CLI deliberately does not use this. A process exit status must carry
    every non-zero code through to the shell, ``DEGRADED`` included (ADR
    0005), so ``cli.py`` branches on ``if code:`` instead. The two rules
    differ because the questions differ: "is there something to show?" versus
    "what status did this run finish with?".
    """
    return code in (ExitCode.ERROR, ExitCode.USAGE)
