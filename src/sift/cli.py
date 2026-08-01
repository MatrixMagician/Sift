"""Sift command-line interface.

Flat subcommands per SPEC.md §5.8. new/ingest/show are implemented in
Phase 1; analyze/report/eval/doctor arrive in later phases. Config resolution
follows D-08 precedence (flags > SIFT_* env > config.toml > defaults) — every
implemented command exposes ``--data-dir`` as the flags layer.
"""

import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated

import httpx
import typer

from sift import adapters
from sift.commands import (
    BundleFormat,
    ReportFormat,
    parse_filters,
    run_analyze,
    run_eustack,
    run_mcm,
    run_perfmon,
    run_report,
    run_show_clusters,
    run_show_events,
    run_show_hypotheses,
    run_validate,
)
from sift.commands import parse_moment as _parse_moment_or_raise
from sift.config import SiftConfig, load_config
from sift.llm.bringup import build_client as _build_client
from sift.llm.props import determinism_warnings
from sift.pipeline.hypothesise import (
    DEFAULT_TOP_CLUSTERS as _DEFAULT_TOP_CLUSTERS,
)
from sift.pipeline.ingest import IngestError, IngestUsageError, run_ingest
from sift.render._util import sanitise as _sanitise
from sift.store import (
    CaseNotFound,
    CaseStore,
    CaseUnreadable,
    case_db_path,
    open_case,
    vec_version,
)
from sift.verdicts import TargetSpecError, parse_target

app = typer.Typer(no_args_is_help=True)


def _version_string() -> str:
    """Return the installed package version, or the source default off-tree."""
    try:
        return version("sift")
    except PackageNotFoundError:
        # Running from an uninstalled checkout (e.g. ``python -m sift.cli``):
        # no dist metadata exists, so fall back to the declared version.
        return "0.1.0"


def _version_callback(value: bool) -> None:
    """Eager ``--version`` handler: print the version and exit before dispatch.

    An eager Option callback fires during parsing, so it works even though the
    top-level group requires a subcommand (``no_args_is_help=True``).
    """
    if value:
        typer.echo(_version_string())
        raise typer.Exit()


@app.callback()


def _main(  # pyright: ignore[reportUnusedFunction] — registered via @app.callback
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the Sift version and exit.",
            is_eager=True,
            callback=_version_callback,
        ),
    ] = False,
) -> None:
    """Sift — a fully local, privacy-preserving incident triage engine."""


DataDirOption = Annotated[
    Path | None,
    typer.Option("--data-dir", help="Override the case data directory"),
]


def _case_store(case: str, config: SiftConfig) -> CaseStore:
    """Open an existing case or exit 1 with a helpful message.

    The CLI's mapping of ``store.open_case``'s typed failures (ADR 0019) onto
    the exit-1 contract. The TUI maps the same two exceptions onto its
    ErrorScreen, so a missing or corrupt case reads identically on both.
    """
    try:
        return open_case(config.data_dir, case)
    except (CaseNotFound, CaseUnreadable) as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from None


@app.command()


def new(
    case_name: str,
    input: Annotated[str, typer.Option("--input", help="Directory of artefacts")],
    # Typer reads the default once at import time, so the shared list is safe here.
    adapter: Annotated[
        list[str], typer.Option("--adapter", help="glob=name adapter override")
    ] = [],  # noqa: B006
    data_dir: DataDirOption = None,
) -> None:
    """Create a new case from a directory of artefacts."""
    config = load_config({"data_dir": data_dir})
    try:
        db_path = case_db_path(config.data_dir, case_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from None
    if db_path.exists():
        # A case is one snapshot: silently repointing input_dir would mix
        # events from two snapshots and poison the coverage meta.
        print(f"Error: case {case_name!r} already exists at {db_path.parent}")
        raise typer.Exit(1)
    try:
        # Validate glob=name specs now so a typo fails at `new`, not mid-ingest.
        adapters.parse_adapter_overrides(adapter)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(2) from None
    input_dir = Path(input).expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Error: input directory does not exist: {input_dir}")
        raise typer.Exit(1)
    if not any(input_dir.iterdir()):
        print(f"Warning: input directory is empty: {input_dir}")
    store = CaseStore(db_path)
    store.set_meta("input_dir", str(input_dir))
    store.set_meta("created_at", datetime.now(tz=UTC).isoformat())
    # Raw --adapter specs persist so `sift ingest` reuses them (flags win over
    # config.adapters per glob at ingest time).
    store.set_meta("adapter_overrides", json.dumps(adapter))
    store.close()
    print(f"Created case {case_name!r} for {input_dir}")


def _case_row(db_path: Path) -> tuple[str, str, str]:
    """Read (created, events, hypotheses) from a case WITHOUT migrating it.

    This is the one place in the CLI that opens sqlite outside ``CaseStore``,
    and deliberately so: ``CaseStore.__init__`` runs ``_migrate()``, so listing
    N cases through it would rewrite the schema of every case on disk — and
    announce a migration per case — purely as a side effect of displaying them.
    A listing must not mutate evidence, hence the read-only URI connection.

    Every field degrades to an em dash on any sqlite error rather than failing
    the whole listing: a corrupt or old-schema case is precisely the one an
    operator most wants to see (and most likely wants to delete). ``hypotheses``
    only exists from a later migration, so it is missing on Phase-1-era cases.
    """
    dash = "—"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return (dash, dash, dash)
    try:

        def scalar(sql: str) -> str:
            try:
                row = conn.execute(sql).fetchone()
            except sqlite3.Error:
                return dash
            return dash if row is None or row[0] is None else str(row[0])

        # Trimmed to minutes: the listing is for picking a case, not forensics.
        created = scalar("SELECT value FROM meta WHERE key = 'created_at'")[:16]
        return (
            created or dash,
            scalar("SELECT count(*) FROM events"),
            scalar("SELECT count(*) FROM hypotheses"),
        )
    finally:
        conn.close()


@app.command("list")


def list_(data_dir: DataDirOption = None) -> None:
    """List the cases in the data directory.

    Read-only: never opens a case for writing, so listing cannot migrate,
    modify or lock a case.db.
    """
    config = load_config({"data_dir": data_dir})
    cases_root = config.data_dir / "cases"
    rows: list[tuple[str, str, str, str, str]] = []
    for db_path in sorted(cases_root.glob("*/case.db")):
        size_mb = f"{db_path.stat().st_size / 1024**2:,.1f}"
        # A case directory name is filesystem-sourced and therefore untrusted —
        # sanitise it like every other display field (T-04-01).
        rows.append((_sanitise(db_path.parent.name), *_case_row(db_path), size_mb))
    if not rows:
        print(f"No cases in {cases_root}")
        return
    headers = ("CASE", "CREATED", "EVENTS", "HYPOTHESES", "DB (MB)")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
    for row in rows:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))


@app.command()


def delete(
    case: str,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Skip the confirmation prompt")
    ] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Delete a case and everything in it — the inverse of 'sift new'.

    Removes the whole case directory: ``case.db`` plus the ``mcm/`` and
    ``perfmon/`` report artefacts. A case is self-contained by design (a clean
    store close checkpoints the WAL, so nothing lives outside the directory),
    which is what makes deleting the directory equivalent to deleting the case.
    Reports exported elsewhere with 'sift report --out' are not touched.

    This is an unlink, not a secure wipe: the raw evidence bytes may remain
    recoverable on the underlying media until overwritten.
    """
    config = load_config({"data_dir": data_dir})
    try:
        # case_db_path allowlist-validates the name and asserts the resolved
        # path stays under <data_dir>/cases (T-02-01, D-04) — the single
        # containment check, which also closes a symlinked case directory.
        db_path = case_db_path(config.data_dir, case)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from None
    if not db_path.exists():
        print(f"Error: case {case!r} does not exist")
        raise typer.Exit(1)
    case_dir = db_path.parent
    files = [p for p in case_dir.rglob("*") if p.is_file()]
    total_mb = sum(p.stat().st_size for p in files) / 1024**2
    if not force:
        print(f"Delete case {case!r}?")
        print(f"  {case_dir}")
        print(f"  {len(files)} file(s), {total_mb:,.1f} MB")
        # Aborting raises typer.Abort (exit 1), so a declined or non-interactive
        # prompt can never fall through to the rmtree. --force is the scripted path.
        typer.confirm("This cannot be undone. Continue?", abort=True)
    try:
        shutil.rmtree(case_dir)
    except OSError as exc:
        # Read-only media or a permission failure mid-walk leaves a partial
        # directory; say so plainly rather than raising a traceback (WR-02).
        print(f"Error: cannot delete case {case!r}: {_sanitise(str(exc))}")
        raise typer.Exit(1) from None
    print(f"Deleted case {case!r}")


@app.command()


def ingest(case: str, data_dir: DataDirOption = None) -> None:
    """Parse the case's input directory and store canonical events.

    A case is one snapshot of artefacts: re-ingesting the same snapshot adds
    zero events (idempotent); re-collect changed inputs into a new case.
    New files appearing in the directory simply add events, and renamed
    files produce duplicate events (a documented limitation — event identity
    is source_file + byte_offset within one snapshot).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        run_ingest(case, config, store)
    except IngestUsageError as exc:
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(2) from None
    except IngestError as exc:
        # WR-07 disk-full included: abort loudly, non-zero, with zero events
        # committed (the transaction is already rolled back). Message text is
        # already sanitised at construction; re-sanitise for defence in depth.
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(1) from None
    finally:
        # STORE-01 / Pitfall 4: a clean close checkpoints the WAL, so the
        # case directory holds only case.db afterwards — deleting the
        # directory is deleting the case.
        store.close()


# The targets `sift show` accepts. Each has its own body in commands/show.py
# (ADR 0019), so this command is a dispatch: the CLI owns which names are
# public, the TUI reaches the same functions directly per screen. `templates`
# is deliberately absent — it is the clusters target's pre-analyze fallback,
# not a name an operator passes.
_SHOW_TARGETS = ("events", "clusters", "hypotheses")


@app.command()


def show(
    case: str,
    what: str,
    # Typer reads the default once at import time; shared list is safe here.
    filters: Annotated[
        list[str], typer.Option("--filter", help="key=value filter (repeatable)")
    ] = [],  # noqa: B006
    data_dir: DataDirOption = None,
) -> None:
    """Show events, clusters or hypotheses for a case.

    Filters (repeatable, AND-combined): --filter key=value

    events keys: severity=<fatal|error|warn|info|debug|unknown>,
    source=<adapter>, file=<source-file substring>, since=<ISO 8601>,
    until=<ISO 8601>, limit=<N>.

    clusters keys: severity=<max severity>, min-count=<N>,
    contains=<template substring>, limit=<N>.

    Substring matches (file, contains) are literal — no wildcards. Naive
    since/until timestamps are treated as UTC; since/until exclude events
    without a timestamp (a documented filter semantic, not silent loss).
    """
    if what not in _SHOW_TARGETS:
        print(f"Error: unknown target {what!r}; expected events|clusters|hypotheses")
        raise typer.Exit(1)
    try:
        parsed = parse_filters(filters, what)
    except ValueError as exc:
        # T-02-09: echoed filter values are untrusted input — sanitise.
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(2) from None
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        if what == "hypotheses":
            code = run_show_hypotheses(store)
        elif what == "clusters":
            code = run_show_clusters(store, filters=parsed)
        else:
            code = run_show_events(store, filters=parsed)
    finally:
        # Close so WAL sidecars checkpoint on every show path (Pitfall 4).
        store.close()
    if code:
        raise typer.Exit(code)


def _parse_moment(value: str | None, label: str) -> datetime | None:
    """Map ``commands.parse_moment``'s ValueError onto the exit-2 contract.

    A bad ``--since``/``--until`` is a usage error, never a silent ``None``
    that would look like an absent window. The parser's message is already
    sanitised (T-04-01: the echoed flag value is untrusted input).
    """
    try:
        return _parse_moment_or_raise(value, label)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(2) from None


def _config_with_model(data_dir: Path | None, model: str | None) -> SiftConfig:
    """Resolve config with the shared ``--model`` override.

    D-03 precedence: ``--model`` feeds BOTH roles' config (flags win,
    deep-merged) — the one dance analyze/eval/doctor all share.
    """
    overrides: dict[str, object] = {"data_dir": data_dir}
    if model is not None:
        overrides["generation"] = {"model": model}
        overrides["embeddings"] = {"model": model}
    return load_config(overrides)


@app.command()


def analyze(
    case: str,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)",
        ),
    ] = False,
    no_label: Annotated[
        bool,
        typer.Option(
            "--no-label",
            help="Skip LLM cluster labels; clusters keep their signature (D-01)",
        ),
    ] = False,
    re_embed: Annotated[
        bool,
        typer.Option(
            "--re-embed",
            help="Discard stored embedding vectors and re-embed every "
            "exemplar; the explicit escape hatch for applying a changed "
            "embedding model or batch knob (DET-01, D-07)",
        ),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the generation+embeddings model id"),
    ] = None,
    hint: Annotated[
        str | None,
        typer.Option(
            "--hint",
            help="Operator context appended verbatim to the prompt (never a time)",
        ),
    ] = None,
    kb: Annotated[
        Path | None,
        typer.Option(
            "--kb",
            help="Index a directory of runbooks/RCAs and thread the nearest "
            "chunks into the triage prompt as non-citable reference material "
            "(RAG-07, D-01)",
        ),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Only rank clusters intersecting on/after this ISO 8601 time",
        ),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            "--until",
            help="Rank clusters on/before this ISO 8601 time; also the "
            "incident-time anchor (defaults to case end)",
        ),
    ] = None,
    top_clusters: Annotated[
        int,
        typer.Option(
            "--top-clusters",
            help="How many top-salience clusters to feed the hypothesiser",
        ),
    ] = _DEFAULT_TOP_CLUSTERS,
    data_dir: DataDirOption = None,
) -> None:
    """Embed, cluster and label the case, then generate cited hypotheses (M4).

    The full triage slice: synonymous template groups are embedded and clustered
    (HDBSCAN / agglomerative fallback) and eagerly labelled by the local LLM
    (D-01, skip with ``--no-label``), then ranked by salience and passed to the
    citation-gated hypothesiser (RAG-02) — every hypothesis must cite an event
    the model was actually shown, or the run degrades. ``--hint`` adds operator
    context verbatim (never parsed as a time); ``--since``/``--until`` scope the
    ranked clusters (``--until`` also anchors the incident time, defaulting to
    case end); ``--top-clusters`` caps how many clusters feed the prompt.
    ``--kb <dir>`` indexes a directory of runbooks/RCAs and threads the nearest
    chunks into the prompt as NON-citable reference material (RAG-07, D-01).
    Stored embedding vectors are reused across runs, so a re-analyse of an
    unchanged case makes no embedding calls (DET-01); ``--re-embed`` discards
    them and embeds every exemplar afresh.
    ``sift show clusters`` / ``sift show hypotheses`` render the result.

    Exit-code contract (CLI-04, scriptable — see ADR 0005):

    \b
      0  success   hypotheses generated; every citation is valid
      3  degraded  ran to completion but repair failed or a citation was
                    invalid — output persisted and FLAGGED, not a clean success
      1  failure   inference transport error, SSRF refusal, or corrupt/absent
                    case.db — nothing new persisted
      2  usage     Typer/Click usage error (e.g. a malformed --since/--until)

    ``--until`` also sets the salience incident-time anchor (defaults to the
    case-end timestamp when omitted).
    """
    # A bad --since/--until is a usage error (exit 2); parse before touching the
    # store so it fails fast. --hint is never parsed as a time.
    since_dt = _parse_moment(since, "since")
    until_dt = _parse_moment(until, "until")
    config = _config_with_model(data_dir, model)
    store = _case_store(case, config)
    try:
        code = run_analyze(
            store,
            config,
            allow_public=i_know_what_im_doing,
            label=not no_label,
            re_embed=re_embed,
            hint=hint,
            kb=kb,
            since=since_dt,
            until=until_dt,
            top_clusters=top_clusters,
        )
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring
        # ingest — the case directory holds only case.db afterwards.
        store.close()
    if code:
        raise typer.Exit(code)


@app.command()


def report(
    case: str,
    fmt: Annotated[
        ReportFormat,
        typer.Option("--format", help="Output format: md (default), json or pdf"),
    ] = ReportFormat.md,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write to this file instead of stdout"),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Render a self-contained triage report from a case (REPT-01).

    A pure function of ``case.db``: no inference client is constructed and no
    network call is made (zero-egress invariant). Exit-code contract (ADR 0007):
    0 = rendered (including a degraded case — the banner communicates
    degradation), 1 = no hypotheses / render-or-IO failure / missing sift[pdf],
    2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        code = run_report(store, fmt=fmt, out=out)
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4).
        store.close()
    if code:
        raise typer.Exit(code)


@app.command()


def validate(
    case: str,
    target: Annotated[
        str,
        typer.Argument(
            help="Verdict target: hypothesis:<index>, cluster:<id> or "
            "template:<id> (the type prefix is required)"
        ),
    ],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Record the target as confirmed"),
    ] = False,
    reject: Annotated[
        bool,
        typer.Option("--reject", help="Record the target as rejected"),
    ] = False,
    uncertain: Annotated[
        bool,
        typer.Option("--uncertain", help="Record the target as uncertain"),
    ] = False,
    note: Annotated[
        str,
        typer.Option("--note", help="Free-text analyst note stored with the verdict"),
    ] = "",
    data_dir: DataDirOption = None,
) -> None:
    """Record an analyst verdict on a hypothesis, cluster or template (D003).

    Appends ONE immutable verdict row to case.db via the shared verdict
    service — the same ``record_validation`` code path the review TUI uses, so
    headless and interactive capture are byte-equivalent (D004). The row
    snapshots the judged target's context (hypothesis text + masked evidence
    templates + sources, or the cluster/template shape) and provenance (run
    marker, model, prompt hash), so M002 can harvest every case.db directly
    (D005). Verdicts are history, never state: re-running ``sift analyze``
    replaces hypotheses but keeps every recorded verdict, and no update or
    delete path exists.

    Exit-code contract (ADR 0005/0007, scriptable — branch on the code alone):

    \b
      0  success   verdict appended; stdout prints its verdict_id and target
      1  failure   missing/corrupt case, unknown target, locked database
      2  usage     malformed target spec, or zero/multiple verdict flags
    """
    # Exactly one verdict flag: zero is as much a usage error as several —
    # silently defaulting a verdict state would fabricate analyst judgement.
    chosen = [
        state
        for state, given in (
            ("confirmed", confirm),
            ("rejected", reject),
            ("uncertain", uncertain),
        )
        if given
    ]
    if len(chosen) != 1:
        print("Error: exactly one of --confirm, --reject or --uncertain is required")
        raise typer.Exit(2)
    # A malformed spec is a usage error (exit 2, the _parse_filters precedent):
    # parse before touching the store so it fails fast; existence in the case
    # is checked at record time (exit 1). The echoed spec is untrusted input —
    # sanitise (T-04-01).
    try:
        spec = parse_target(target)
    except TargetSpecError as exc:
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(2) from None
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        code = run_validate(store, case=case, spec=spec, verdict=chosen[0], note=note)
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4).
        store.close()
    if code:
        raise typer.Exit(code)


@app.command()


def tui(case: str, data_dir: DataDirOption = None) -> None:
    """Open an analysed case in the interactive terminal browser (SPEC.md §5.7).

    Fully local: the TUI's only network path is the analyse action's
    inference client against the configured localhost endpoint — the same
    ``run_analyze`` body (and SSRF guard) the CLI runs, in a background
    worker (R006/R020). A missing or corrupt case exits 1 with a message,
    never a traceback (the shared ``_case_store`` contract); a case that
    has not been analysed yet opens the TUI on a clear "not analysed"
    screen where `a` analyses it in place (R012). Press '?' inside for the
    key bindings (R013), q to quit (exit 0).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        # Lazy import (the report-renderer precedent): textual is a heavy
        # import no other subcommand should pay for.
        from sift.tui.app import SiftApp

        SiftApp(store, case, config=config).run()
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4) — the app
        # never closes the store itself, so this runs exactly once.
        store.close()


@app.command()


def mcm(
    case: str,
    fmt: Annotated[
        BundleFormat,
        typer.Option("--format", help="Report format: md (default) or json"),
    ] = BundleFormat.md,
    data_dir: DataDirOption = None,
) -> None:
    """Write the MCM forensics bundle for a case (MCM-05, D-10).

    Runs the deterministic ``analyse_mcm`` over the stored events (no LLM, no
    network — the figures are computed from log text, never model-authored) and
    ALWAYS writes ``<case>/mcm/mcm_report.md`` (or ``mcm_report.json`` with
    ``--format json``) AND ``<case>/mcm/mcm_attribution.csv``, then prints a
    short stdout summary. Thresholds and the lead-up window are config-only —
    there is no per-run CLI knob (D-12/D-13). Exit-code contract (ADR 0007):
    0 = bundle written (including an empty case), 1 = missing case / write
    failure, 2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        code = run_mcm(store, config, case=case, fmt=fmt)
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring report.
        store.close()
    if code:
        raise typer.Exit(code)


@app.command()


def perfmon(
    case: str,
    fmt: Annotated[
        BundleFormat,
        typer.Option("--format", help="Report format: md (default) or json"),
    ] = BundleFormat.md,
    data_dir: DataDirOption = None,
) -> None:
    """Write the perfmon correlation bundle for a case (PERF-06, D-17).

    Correlates the stored DSSPerformanceMonitor samples with the MCM denial
    episodes ``analyse_mcm`` detects (no LLM, no network — the figures are
    computed from counter readings, never model-authored) and ALWAYS writes
    ``<case>/perfmon/perfmon_report.md`` (or ``perfmon_report.json`` with
    ``--format json``) AND ``<case>/perfmon/perfmon_trend.csv``, then prints a
    short stdout summary. With no DSSErrors log, and therefore no episodes,
    there is no window: the same figures are computed over each file's full
    sample range and the report says so plainly (D-20). Exit-code contract
    (ADR 0007): 0 = bundle written (including an empty case), 1 = missing case
    / write failure, 2 = Typer usage (bad ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        code = run_perfmon(store, config, case=case, fmt=fmt)
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring mcm.
        store.close()
    if code:
        raise typer.Exit(code)


@app.command()


def eustack(
    case: str,
    fmt: Annotated[
        BundleFormat,
        typer.Option("--format", help="Report format: md (default) or json"),
    ] = BundleFormat.md,
    data_dir: DataDirOption = None,
) -> None:
    """Write the eu-stack thread-dump analysis bundle for a case (EUS-09).

    Runs the deterministic ``analyse_eustack_bundle`` over the stored
    eu-stack events (no LLM, no network — the figures are computed from
    thread-dump text, never model-authored) and ALWAYS writes
    ``<case>/eustack/eustack_report.md`` (or ``eustack_report.json`` with
    ``--format json``) AND ``<case>/eustack/eustack_signatures.csv``, then
    prints a short stdout summary. Works identically with NO DSSErrors log
    anywhere in the case — eu-stack dumps are this command's sole input.
    Classification and saturation are computed on the LAST dump only; a
    single-dump case is the N=1 case of that same shape (D-11). The rules
    file and saturation thresholds are config-only — there is no per-run CLI
    knob (D-12). Exit-code contract (ADR 0007): 0 = bundle written (including
    an empty case), 1 = missing case / write failure, 2 = Typer usage (bad
    ``--format``).
    """
    config = load_config({"data_dir": data_dir})
    store = _case_store(case, config)
    try:
        code = run_eustack(store, config, case=case, fmt=fmt)
    finally:
        # Close so the WAL checkpoints on every path (Pitfall 4), mirroring
        # mcm/perfmon.
        store.close()
    if code:
        raise typer.Exit(code)


@app.command("eval")


def eval_(
    suite: Annotated[
        Path,
        typer.Option("--suite", help="Directory of golden cases (default eval/cases)"),
    ] = Path("eval/cases"),
    thresholds: Annotated[
        Path,
        typer.Option(
            "--thresholds",
            help="TOML of per-metric floors (default eval/thresholds.toml)",
        ),
    ] = Path("eval/thresholds.toml"),
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the machine-readable metric table as JSON"),
    ] = False,
    judge: Annotated[
        bool,
        typer.Option(
            "--judge",
            help="Add an advisory local-model judge score (never affects the gate)",
        ),
    ] = False,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)",
        ),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the generation+embeddings model id"),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Run the golden-case evaluation suite and print the metric table (EVAL-02).

    Each case under ``--suite`` runs through the real ingest → cluster →
    hypothesise pipeline against a temp case.db, then the four quality metrics
    (retrieval hit rate, hypothesis hit@k, citation validity, determinism drift)
    are scored against its frozen ``truth.yaml``. Offline runs inject a fake
    client via the ``llm.bringup.make_http_client`` seam (EVAL-05). ``--json`` emits the
    machine-readable table.

    The suite is gated against ``--thresholds`` (default ``eval/thresholds.toml``,
    ADR 0010): exit 0 when every keyword-metric aggregate clears its floor and no
    case failed; exit 1 when a metric regressed, a case could not run, or a
    negative case emitted a confident hypothesis (a non-suppressible CI signal).
    A missing/invalid ``--suite`` or unreadable ``--thresholds`` is a usage error
    (exit 2).

    The eu-stack golden cases (``eustack-*``) are scored deterministically
    against ``analyse_eustack_bundle`` and run without an inference endpoint at
    all (D-19-16); every other case in the suite still requires one.
    """
    from sift.eval.metrics import SuiteResult
    from sift.eval.report import render_json_table, render_text_table
    from sift.eval.runner import run_case
    from sift.eval.thresholds import gate, load_thresholds

    if not suite.is_dir():
        print(f"Error: suite directory does not exist: {suite}")
        raise typer.Exit(2)
    case_dirs = sorted(
        d for d in suite.iterdir() if d.is_dir() and (d / "truth.yaml").exists()
    )
    if not case_dirs:
        print(f"Error: no golden cases (with truth.yaml) under {suite}")
        raise typer.Exit(2)
    try:
        floors = load_thresholds(thresholds)
    except ValueError as exc:
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(2) from None

    config = _config_with_model(data_dir, model)

    try:
        http, client, _gen_ep, _emb_ep = _build_client(
            config, allow_public=i_know_what_im_doing
        )
    except ValueError as exc:
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(1) from None
    try:
        results = [
            run_case(case_dir, client, config, judge=judge) for case_dir in case_dirs
        ]
    finally:
        http.close()

    suite_result = SuiteResult(results)
    gate_result = gate(suite_result, floors)
    if as_json:
        print(render_json_table(suite_result, gate_result), end="")
    else:
        print(render_text_table(suite_result, gate_result, show_judge=judge), end="")
    # The command OWNS the non-zero exit so CI sees a regression (T-07-07);
    # it is never suppressed by an advisory judge score (D-08).
    if not gate_result.passed:
        raise typer.Exit(1)


# The exact, actionable failure message for the Lemonade OGA/ONNX-recipe case
# (D-02 / RESEARCH Pitfall 2): a model is listed but /v1/embeddings returns no
# usable vector. Never inferred from /v1/models — only a real round-trip reveals it.
_OGA_ONNX_MSG = (
    "embeddings unsupported on this model/recipe; load a llamacpp/flm-recipe "
    "embedding model (Lemonade) or start llama-server with --embeddings"
)


@app.command()


def doctor(
    case: Annotated[
        str | None,
        typer.Argument(help="Optional case: check the server dim against its index"),
    ] = None,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Allow a non-loopback/non-RFC1918 inference endpoint (LLM-02)",
        ),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the generation+embeddings model id"),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Verify the local inference endpoints and vector support (fail-fast).

    D-02: checks run in dependency order and STOP at the first critical failure
    with a non-zero exit, naming the failure mode. The embedding check is a REAL
    round-trip (an actual ``/v1/embeddings`` call) — the only thing that catches
    a Lemonade OGA/ONNX-recipe model that lists but cannot embed. Determinism
    risks reached before any stop print as warnings without failing.
    """
    config = _config_with_model(data_dir, model)

    # 1. Construct the client → runs the loopback/RFC1918 SSRF guard on BOTH
    # base_urls (LLM-02). A public endpoint without the override is refused.
    try:
        http, client, gen_ep, emb_ep = _build_client(
            config, allow_public=i_know_what_im_doing
        )
    except ValueError as exc:
        print(f"Error: {_sanitise(str(exc))}")
        raise typer.Exit(1) from None
    try:
        # 2./3. GET /v1/models on the generation then embeddings endpoint
        # [CRITICAL if unreachable].
        for role, ep in (("generation", gen_ep), ("embeddings", emb_ep)):
            try:
                models = client.models(ep)
            except (httpx.HTTPError, ValueError) as exc:
                print(
                    f"Error: {role} endpoint {ep.base_url!r} unreachable: "
                    f"{_sanitise(str(exc))}"
                )
                raise typer.Exit(1) from None
            print(
                f"{role} endpoint OK: "
                + _sanitise(", ".join(models) or "(no models listed)")
            )

        # 4. REAL /v1/embeddings round-trip [CRITICAL]. An OGA/ONNX-recipe server
        # lists a model but returns an empty embedding — embed() raises. Never
        # infer capability from the /v1/models listing above (Pitfall 2, T-03-13).
        try:
            vectors = client.embed(["sift doctor embedding probe"])
        except (httpx.HTTPError, ValueError):
            print(f"Error: {_OGA_ONNX_MSG}")
            raise typer.Exit(1) from None
        if not vectors or not vectors[0]:
            print(f"Error: {_OGA_ONNX_MSG}")
            raise typer.Exit(1) from None
        dim = len(vectors[0])
        print(f"embedding round-trip OK: dimension {dim}")

        # 5. If a case is given, compare the returned dim against its recorded
        # index dimension [CRITICAL on mismatch] (LLM-03 + STORE-03). The dim is
        # an int on both sides — compared exactly, no rounding.
        if case is not None:
            store = _case_store(case, config)
            try:
                existing = store.get_meta("embedding_dim")
            finally:
                store.close()
            if existing is not None and int(existing) != dim:
                print(
                    f"Error: embedding dimension mismatch: case index has "
                    f"{int(existing)}, server returned {dim}"
                )
                raise typer.Exit(1) from None
            if existing is not None:
                print(f"case index dimension OK: {int(existing)} matches server")

        # 6. Load sqlite-vec on a throwaway connection and read vec_version()
        # [CRITICAL if it cannot load] (Pitfall 5). Names the enable_load_extension
        # caveat so a Python build without it is diagnosed by name.
        try:
            version = vec_version()
        except Exception as exc:  # noqa: BLE001 — any load failure is the same caveat
            print(
                "Error: cannot load the sqlite-vec extension; this Python's "
                "sqlite3 does not permit extension loading "
                f"(enable_load_extension): {_sanitise(str(exc))}"
            )
            raise typer.Exit(1) from None
        print(f"sqlite-vec OK: vec_version {_sanitise(version)}")

        # 7. Determinism WARNINGS (non-fatal): a multi-slot server, a random
        # seed or a non-zero temperature each break reproducibility (T-03-15).
        # The decision itself is pure and lives in llm/props.py (ADR 0020);
        # stderr keeps stdout scriptable.
        for warning in determinism_warnings(client.props()):
            print(warning, file=sys.stderr)

        print("doctor: all checks passed")
    finally:
        http.close()
