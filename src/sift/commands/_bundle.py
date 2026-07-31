"""Shared bundle-writing for the mcm/perfmon/eustack analysis commands.

The three commands each produce a report file plus a CSV in a fixed directory
beneath the case, then print a one-line summary and their top diagnostic flag.
That tail is identical across all three; only the analyser call and the noun
differ.
"""

from collections.abc import Callable, Iterable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from sift.commands._exit import ExitCode
from sift.render._util import sanitise


class BundleFormat(StrEnum):
    """Report format for the ``mcm``/``perfmon``/``eustack`` bundle commands
    (an unknown value is a Typer usage error, exit 2 — mirrors ``ReportFormat``;
    ADR 0007). The CSV is always written."""

    md = "md"
    json = "json"


def write_bundle(
    bundle_dir: Path,
    report_name: str,
    report_text: str,
    csv_name: str,
    write_csv: Callable[[Path], None],
    label: str,
    echo: Callable[[str], None],
) -> ExitCode:
    """Write a bundle's report then CSV, unlinking both on any OSError (WR-06).

    The report is written before the CSV, so a mid-CSV failure would otherwise
    leave a valid-looking report next to a truncated CSV — unlink both so a
    half-written bundle is never mistaken for a complete one. A write-target
    failure returns ``ERROR`` with a helpful, sanitised message (WR-02), never
    a raw traceback.
    """
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / report_name).write_text(report_text, encoding="utf-8")
        write_csv(bundle_dir / csv_name)
    except OSError as exc:
        for partial in (bundle_dir / report_name, bundle_dir / csv_name):
            partial.unlink(missing_ok=True)
        echo(
            f"Error: cannot write {label} bundle to {bundle_dir}: "
            f"{sanitise(str(exc))}"
        )
        return ExitCode.ERROR
    return ExitCode.SUCCESS


# Diagnostic-flag severity order shared by the mcm/perfmon/eustack summaries.
SEV_RANK = {"critical": 0, "warn": 1, "info": 2}


class SeverityFlag(Protocol):
    """The severity/message slice shared by MCM flags, perfmon hazards and
    eu-stack saturation flags."""

    @property
    def severity(self) -> str: ...

    @property
    def message(self) -> str: ...


def print_top_flag(
    flags: Iterable[SeverityFlag],
    prefix: str,
    empty: str,
    echo: Callable[[str], None],
) -> None:
    """Print the top diagnostic flag by severity, or the empty-case line.

    Flag/hazard message text is log-derived (customer bytes), so it goes
    through ``sanitise`` before echo (T-10-15/T-13-STDOUTESC/T-17-02).
    """
    ordered = sorted(flags, key=lambda f: SEV_RANK.get(f.severity, 3))
    if ordered:
        top = ordered[0]
        echo(f"{prefix}{top.severity} — {sanitise(top.message)}")
    else:
        echo(f"{prefix}{empty}")
