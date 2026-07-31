"""``sift report`` — render a self-contained triage report from a case (REPT-01).

A pure function of ``case.db``: no inference client is constructed and no
network call is made (zero-egress invariant).
"""

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from sift.commands._exit import ExitCode
from sift.render._util import PdfExtraMissing, sanitise
from sift.store import CaseStore


class ReportFormat(StrEnum):
    """Output formats for ``sift report`` (an unknown value is a Typer usage
    error, exit 2 — never a semantic outcome; ADR 0007)."""

    md = "md"
    json = "json"
    pdf = "pdf"


def run_report(
    store: CaseStore,
    *,
    fmt: ReportFormat = ReportFormat.md,
    out: Path | None = None,
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Render a triage report from an open case store (R006).

    The shared in-process body of ``sift report``: the Typer command wraps
    it with config resolution and store lifecycle; the TUI calls it with its
    own ``CaseStore`` and an ``out`` path in the case directory. Every
    operator-visible line — error messages and the stdout report text alike —
    flows through the injected ``echo`` sink (default ``print``), so callers
    fully own presentation. Returns the ADR 0007 exit code (0 rendered,
    including degraded; 1 no hypotheses / render-or-IO failure / missing
    sift[pdf]); the caller owns process exit and ``store.close()``.
    """
    # WR-03/IN-04: gate on whether analyze RAN (triage_created_at present),
    # not on whether it produced schema-valid rows. A hard-degraded run
    # persists zero hypotheses but sets triage_created_at and triage_raw —
    # that is a reportable degraded run (banner + raw), never "run analyze
    # first". Reserve the no-triage message for the genuine never-analysed
    # case. Gating on run-meta also drops the redundant second
    # query_hypotheses (the renderer runs it once) — IN-04.
    if store.get_meta("triage_created_at") is None:
        echo("No hypotheses to report; run 'sift analyze' first")
        return ExitCode.ERROR
    if fmt is ReportFormat.pdf:
        if out is None:
            echo("Error: --format pdf requires --out <path>")
            return ExitCode.ERROR
        try:
            # Renderer delivered in 06-05 — lazy so md/json need no WeasyPrint.
            from sift.render.pdf import render_pdf

            render_pdf(store, out)
        except (ImportError, PdfExtraMissing) as exc:
            echo(
                "Error: PDF rendering unavailable; install the sift[pdf] "
                f"extra and pango ({sanitise(str(exc))})"
            )
            return ExitCode.ERROR
        except OSError as exc:
            # WR-02: a write-target failure is NOT a missing-extra problem —
            # render_pdf renders to bytes first, so an OSError here can only
            # be the file write. Report it as such, not as "install pango".
            echo(f"Error: cannot write report to {out}: {sanitise(str(exc))}")
            return ExitCode.ERROR
        except ValueError as exc:
            # WR-04: the zero-egress url_fetcher raises ValueError on any
            # blocked fetch (e.g. an injected <img> in model text). Egress is
            # still blocked; surface a clean render failure, never a traceback.
            echo(f"Error: PDF rendering failed: {sanitise(str(exc))}")
            return ExitCode.ERROR
        return ExitCode.SUCCESS
    if fmt is ReportFormat.md:
        from sift.render.markdown import render_markdown

        text = render_markdown(store)
    else:  # ReportFormat.json
        from sift.render.json_out import render_json

        text = render_json(store)
    if out is not None:
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            # ADR 0007: a --out write failure (unwritable path, missing
            # parent, full disk) is exit 1 with a helpful message, never a
            # raw traceback — mirroring the pdf branch.
            echo(f"Error: cannot write report to {out}: {sanitise(str(exc))}")
            return ExitCode.ERROR
    else:
        echo(text)
    return ExitCode.SUCCESS
