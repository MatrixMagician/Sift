"""The default output sinks a case command writes through.

``echo`` defaults to ``print`` (stdout, scriptable); ``echo_err`` defaults to
the stderr sink below. Both are parameters rather than direct calls so the TUI
can collect lines instead of writing to a terminal it does not own.
"""

import sys


def echo_stderr(message: str) -> None:
    """Plain-print stderr sink: the default warning channel."""
    print(message, file=sys.stderr)
