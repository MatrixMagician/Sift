"""``sift perfmon`` — write the perfmon correlation bundle (PERF-06, D-17).

Correlates stored DSSPerformanceMonitor samples with the MCM denial episodes
``analyse_mcm`` detects. Deterministic: every figure is computed from counter
readings, with no LLM and no network. With no DSSErrors log, and therefore no
episodes, there is no window — the same figures are computed over each file's
full sample range and the report says so plainly (D-20).
"""

from collections.abc import Callable

from sift.commands._bundle import BundleFormat, print_top_flag, write_bundle
from sift.commands._exit import ExitCode
from sift.config import SiftConfig
from sift.store import CaseStore, case_db_path


def run_perfmon(
    store: CaseStore,
    config: SiftConfig,
    *,
    case: str,
    fmt: BundleFormat = BundleFormat.md,
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Write ``<case>/perfmon/`` and echo a short summary.

    ALWAYS writes both the report (md or json) and the trend CSV. Returns the
    ADR 0007 exit code — 0 written (including an empty case), 1 write failure.
    """
    from sift.pipeline.mcm import analyse_mcm
    from sift.pipeline.perfmon import analyse_perfmon
    from sift.render.perfmon_report import (
        render_perfmon_json,
        render_perfmon_markdown,
        write_perfmon_trend_csv,
    )

    # T-13-PATH: the bundle dir is derived from the SAME resolved case path
    # open_case validated (case_db_path asserts containment) — only
    # <case>/perfmon/ beneath it is ever created, never a user-supplied path.
    perfmon_dir = case_db_path(config.data_dir, case).parent / "perfmon"
    # ONCE (T-13-DOUBLEREAD): the same list feeds both analyses rather
    # than doubling the hydrate/decompress cost — and the read is scoped
    # to the two sources the correlator consumes, so unrelated
    # genericlog/journald rows are never materialised.
    # config.mcm.thresholds is threaded in only because obtaining the
    # episodes needs it — the perfmon hazards themselves take no config
    # knob.
    events = store.query_events(sources=["dsserrors", "dssperfmon"])
    analysis = analyse_perfmon(analyse_mcm(events, config.mcm.thresholds), events)
    if fmt is BundleFormat.json:
        report_name = "perfmon_report.json"
        report_text = render_perfmon_json(analysis)
    else:
        report_name = "perfmon_report.md"
        report_text = render_perfmon_markdown(analysis)
    code = write_bundle(
        perfmon_dir,
        report_name,
        report_text,
        "perfmon_trend.csv",
        lambda path: write_perfmon_trend_csv(analysis, path),
        "perfmon",
        echo,
    )
    if code:
        return code

    n = len(analysis.groups)
    plural = "span" if n == 1 else "spans"
    echo(
        f"Correlated {n} {plural}; wrote {report_name} + "
        f"perfmon_trend.csv to {perfmon_dir}"
    )
    for i, group in enumerate(analysis.groups, start=1):
        print_top_flag(
            group.hazards, f"  Span {i}: ", "no correlation hazards raised", echo
        )
    return ExitCode.SUCCESS
