"""``sift eustack`` — write the eu-stack thread-dump analysis bundle (EUS-09).

Deterministic: every figure is computed from thread-dump text, with no LLM and
no network. Works identically with NO DSSErrors log anywhere in the case —
eu-stack dumps are this command's sole input. Classification and saturation are
computed on the LAST dump only; a single-dump case is the N=1 case of that same
shape (D-11). The rules file and saturation thresholds are config-only (D-12).
"""

from collections.abc import Callable

from sift.commands._bundle import BundleFormat, print_top_flag, write_bundle
from sift.commands._exit import ExitCode
from sift.config import SiftConfig
from sift.pipeline.eustack import load_rules
from sift.pipeline.eustack_progression import analyse_eustack_bundle
from sift.render._util import sanitise
from sift.store import CaseStore, case_db_path


def run_eustack(
    store: CaseStore,
    config: SiftConfig,
    *,
    case: str,
    fmt: BundleFormat = BundleFormat.md,
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Write ``<case>/eustack/`` and echo a short summary.

    ALWAYS writes both the report (md or json) and the signatures CSV. Returns
    the ADR 0007 exit code — 0 written (including an empty case), 1 write
    failure.
    """
    # Deferred because it is the only import here NOT already loaded at CLI
    # startup: ``cli`` -> ``hypothesise`` -> ``analysers`` pulls the whole
    # pipeline half in regardless, so deferring THAT saves nothing, while
    # ``render.eustack_report`` is absent from ``sys.modules`` after
    # ``import sift.cli`` and costs ~2 ms. Measured, not assumed.
    #
    # This block previously also held ``load_rules``, justified as preserving
    # the ``monkeypatch.setattr("sift.pipeline.eustack.load_rules", ...)`` seam.
    # That was false here: no test patches ``load_rules`` while driving
    # ``run_eustack``, and hoisting it leaves the suite green. The seam is real
    # only in ``eval/runner.py``, which says so there.
    from sift.render.eustack_report import (
        changed_signature_count,
        render_eustack_json,
        render_eustack_markdown,
        write_eustack_signatures_csv,
    )

    # T-17-03: the bundle dir is derived from the SAME resolved case path
    # open_case validated (case_db_path asserts containment) — only
    # <case>/eustack/ beneath it is ever created, never a user-supplied
    # path.
    eustack_dir = case_db_path(config.data_dir, case).parent / "eustack"
    rules, rules_hash = load_rules(config.eustack.rules_path)
    bundle = analyse_eustack_bundle(
        store.query_events(sources=["eustack"]),
        rules,
        rules_hash,
        config.eustack.thresholds,
    )
    if fmt is BundleFormat.json:
        report_name = "eustack_report.json"
        report_text = render_eustack_json(bundle)
    else:
        report_name = "eustack_report.md"
        report_text = render_eustack_markdown(bundle)
    code = write_bundle(
        eustack_dir,
        report_name,
        report_text,
        "eustack_signatures.csv",
        lambda path: write_eustack_signatures_csv(bundle, path),
        "eustack",
        echo,
    )
    if code:
        return code

    n_dumps = len(bundle.progression.dumps)
    dump_plural = "dump" if n_dumps == 1 else "dumps"
    n_signatures = bundle.analysis.total_signatures
    sig_plural = "signature" if n_signatures == 1 else "signatures"
    summary = (
        f"Analysed {n_dumps} eu-stack {dump_plural}, {n_signatures} "
        f"{sig_plural}; wrote {report_name} + eustack_signatures.csv to "
        f"{eustack_dir}"
    )
    if n_dumps > 1:
        n_changed = changed_signature_count(bundle.progression)
        changed_plural = "signature" if n_changed == 1 else "signatures"
        summary += f"; {n_changed} changed {changed_plural}"
    echo(sanitise(summary))
    print_top_flag(
        bundle.saturation.flags, "  ", "no saturation flags raised", echo
    )
    return ExitCode.SUCCESS
