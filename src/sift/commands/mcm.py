"""``sift mcm`` — write the MCM forensics bundle for a case (MCM-05, D-10).

Deterministic: ``analyse_mcm`` computes every figure from log text, with no
LLM and no network. Thresholds and the lead-up window are config-only — there
is no per-run knob (D-12/D-13).
"""

from collections.abc import Callable

from sift.commands._bundle import BundleFormat, print_top_flag, write_bundle
from sift.commands._exit import ExitCode
from sift.config import SiftConfig
from sift.store import CaseStore, case_db_path


def run_mcm(
    store: CaseStore,
    config: SiftConfig,
    *,
    case: str,
    fmt: BundleFormat = BundleFormat.md,
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Write ``<case>/mcm/`` and echo a short summary.

    ALWAYS writes both the report (md or json) and the attribution CSV.
    Returns the ADR 0007 exit code — 0 written (including an empty case),
    1 write failure.
    """
    from sift.pipeline.mcm import analyse_mcm
    from sift.render.mcm_report import (
        render_mcm_json,
        render_mcm_markdown,
        write_attribution_csv,
    )

    # T-10-14: the bundle dir is derived from the SAME resolved case path
    # open_case validated (case_db_path asserts containment) — only
    # <case>/mcm/ beneath it is ever created, never a user-supplied path.
    mcm_dir = case_db_path(config.data_dir, case).parent / "mcm"
    # Scoped to the analyser's own source: hydrating (and zstd-
    # decompressing) unrelated genericlog/journald rows would cost memory
    # for events analyse_mcm filters straight back out.
    analysis = analyse_mcm(
        store.query_events(sources=["dsserrors"]), config.mcm.thresholds
    )
    if fmt is BundleFormat.json:
        report_name = "mcm_report.json"
        report_text = render_mcm_json(analysis)
    else:
        report_name = "mcm_report.md"
        report_text = render_mcm_markdown(analysis)
    code = write_bundle(
        mcm_dir,
        report_name,
        report_text,
        "mcm_attribution.csv",
        lambda path: write_attribution_csv(analysis, path),
        "MCM",
        echo,
    )
    if code:
        return code

    n = len(analysis.episodes)
    plural = "episode" if n == 1 else "episodes"
    echo(
        f"Analysed {n} MCM denial {plural}; wrote {report_name} + "
        f"mcm_attribution.csv to {mcm_dir}"
    )
    for i, ea in enumerate(analysis.episodes, start=1):
        print_top_flag(
            ea.flags, f"  Episode {i}: ", "no diagnostic flags raised", echo
        )
    return ExitCode.SUCCESS
