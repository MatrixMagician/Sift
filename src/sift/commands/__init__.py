"""Case commands — the typer-free bodies behind ``sift``'s case operations.

Each command's implementation lives here as
``run_x(store, config, *, ..., echo, echo_err) -> ExitCode`` (ADR 0019). This
package imports neither ``sift.cli`` nor ``sift.tui``: both import it one-way,
which is what keeps the two adapters independent of each other.

Two parameters are carried only where they are used, rather than uniformly:

* ``config`` — omitted by ``show``, ``validate`` and ``report``, which read
  nothing from it. This follows the shape ``run_report`` has always had.
* ``echo_err`` — carried only by the bodies that actually write to stderr
  (``run_analyze``, ``run_show_hypotheses``, ``run_show_clusters``). The rest
  have no stderr output, so accepting a sink they never call would advertise
  behaviour they do not have.

``announce`` is narrower still: ``run_analyze`` alone can emit progress, so
only its signature offers the channel. Failures echo through the injected sink
and return a code; nothing raises across the seam.
"""

from sift.commands._bundle import BundleFormat
from sift.commands._echo import echo_stderr
from sift.commands._exit import ExitCode, is_failure
from sift.commands.analyze import resolve_generation_ctx, run_analyze
from sift.commands.eustack import run_eustack
from sift.commands.mcm import run_mcm
from sift.commands.parse import parse_filters, parse_moment
from sift.commands.perfmon import run_perfmon
from sift.commands.report import ReportFormat, run_report
from sift.commands.show import (
    run_show_clusters,
    run_show_events,
    run_show_hypotheses,
    run_show_templates,
)
from sift.commands.validate import run_validate

__all__ = [
    "BundleFormat",
    "ExitCode",
    "ReportFormat",
    "echo_stderr",
    "is_failure",
    "parse_filters",
    "parse_moment",
    "resolve_generation_ctx",
    "run_analyze",
    "run_eustack",
    "run_mcm",
    "run_perfmon",
    "run_report",
    "run_show_clusters",
    "run_show_events",
    "run_show_hypotheses",
    "run_show_templates",
    "run_validate",
]
