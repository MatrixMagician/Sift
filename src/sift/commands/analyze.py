"""``sift analyze`` — cluster, retrieve and generate citation-gated hypotheses.

The one case command with a network path, and the one that can emit progress:
``announce`` is its third sink, so the ability to narrate is visible in the
type rather than assumed. The client is built through ``llm.bringup``, whose
SSRF guard runs on BOTH base_urls at construction (LLM-02).
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from sift.commands._echo import echo_stderr
from sift.commands._exit import ExitCode
from sift.config import SiftConfig
from sift.llm import bringup
from sift.llm.client import InferenceClient
from sift.pipeline import retrieve
from sift.pipeline.analysers import AnalyserSettings
from sift.pipeline.cluster import cluster_and_label
from sift.pipeline.hypothesise import (
    DEFAULT_TOP_CLUSTERS,
    TRIAGE_CTX_FALLBACK,
    hypothesise,
)
from sift.render._util import sanitise
from sift.store import CaseStore


def resolve_generation_ctx(
    configured: int | None, client: InferenceClient
) -> tuple[int, str | None]:
    """Resolve the generation prompt-budget context window (D-10).

    Returns ``(context_tokens, warning_or_None)`` and is the SINGLE place the
    generation context is resolved on the ``analyze`` path. Precedence follows
    the project's documented order (CLI flags > ``SIFT_*`` env > config.toml >
    defaults): an explicitly configured ``generation.context`` wins outright and
    is never overridden by a server-reported ``n_ctx``, because a pinned value
    is a deliberate operator decision rather than a hint.

    The warning is RETURNED rather than printed so the whole decision is
    unit-testable without a ``CliRunner`` and without depending on how the
    pinned Click version separates stdout from stderr.
    """
    if configured is not None and configured > 0:
        # A pinned window is a choice, not an estimate — never warned about.
        return configured, None
    n = client.props().get("n_ctx")
    if isinstance(n, int) and n > 0:
        return n, None
    return (
        TRIAGE_CTX_FALLBACK,
        "Warning: the generation prompt budget is estimated rather than "
        "discovered — the endpoint served no usable context size, so "
        f"{TRIAGE_CTX_FALLBACK} tokens is assumed. Set generation.context in "
        "config.toml to pin the real window.",
    )


def run_analyze(
    store: CaseStore,
    config: SiftConfig,
    *,
    allow_public: bool = False,
    label: bool = True,
    re_embed: bool = False,
    hint: str | None = None,
    kb: Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    top_clusters: int = DEFAULT_TOP_CLUSTERS,
    echo: Callable[[str], None] = print,
    echo_err: Callable[[str], None] = echo_stderr,
    announce: Callable[[str], None] | None = None,
) -> ExitCode:
    """Run the analyse pipeline against an open case store (R006).

    The shared in-process body of ``sift analyze``: the Typer command wraps
    it with flag parsing, config resolution and store lifecycle; the TUI
    calls it from a worker thread with its own ``CaseStore`` and callbacks.
    Every operator-visible line flows through an injected sink — ``echo``
    (stdout result lines), ``echo_err`` (stderr warnings) and ``announce``
    (pipeline stage messages; ``None`` binds the CLI default, the stderr
    console that owns the transient progress bar) — so callers fully own
    presentation. Returns the CLI-04 exit code (0 success, 3 degraded but
    persisted, 1 failure); the caller owns process exit and ``store.close()``.
    """
    # CLUS-01: zero template groups has two distinct causes, which must not
    # be conflated (D-19-02, EUS-11). Zero events at all means ingest has
    # not run (or produced nothing) — there is nothing to embed OR
    # narrate, so skip the client entirely and exit cleanly. Zero groups
    # WITH events present means every ingested source is held out of
    # ranking (EXCLUDED_FROM_RANKING, e.g. an eu-stack-only case) — there
    # is still nothing to embed, but the deterministic fact blocks
    # (MCM/perfmon/eu-stack) must still reach hypothesise() so they
    # narrate; falling through here is what makes exclusion a
    # replacement, not a dead end. groups > 0 always yields >= 1 cluster
    # (auto-singleton). The probe reads at most one row from the cheap
    # unfiltered streaming generator — never store.query_events(), which
    # decompresses every raw zstd blob.
    groups = store.query_template_groups()
    if not groups and next(iter(store.iter_event_rows()), None) is None:
        echo("Nothing to cluster; run 'sift ingest' first")
        return ExitCode.SUCCESS

    # Construct the client → runs the loopback/RFC1918 SSRF guard on BOTH
    # base_urls (LLM-02). A public endpoint without the override refuses.
    try:
        http, client, _gen_ep, _emb_ep = bringup.build_client(
            config, allow_public=allow_public, tuned_embeddings=True
        )
    except ValueError as exc:
        echo(f"Error: {sanitise(str(exc))}")
        return ExitCode.ERROR
    try:
        # CLI-03: transient stderr-only progress with a STATIC description —
        # untrusted server/DB text never enters a rich renderable (T-03-23).
        # stdout stays scriptable; a non-TTY run renders nothing (disable=).
        # The embed + cluster + label + persist is one opaque call, so the
        # count column ticks from 0/N to N/N once it completes.
        err_console = Console(stderr=True)
        if announce is None:
            # D-04: the pipeline's only operator-facing seam. The CLI default
            # binds the SAME Console that owns the transient Progress live
            # region, so rich moves the bar below the printed line instead of
            # letting a redraw erase it. soft_wrap keeps the message on one
            # line regardless of terminal width; markup/highlight off keep
            # the text literal (the T-03-23 discipline, applied uniformly).
            def _default_announce(message: str) -> None:
                err_console.print(
                    message, highlight=False, markup=False, soft_wrap=True
                )

            announce = _default_announce

        with Progress(
            TextColumn("Embedding"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=err_console,
            transient=True,
            disable=not err_console.is_terminal,
        ) as progress:
            ptask = progress.add_task("embed", total=len(groups))
            try:
                # T-03-22: cluster_and_label persists everything inside ONE
                # store.transaction(); an interrupted embed (client raises)
                # rolls back to zero clusters/vectors — the embed call is the
                # first step and precedes every write, so nothing survives.
                cluster_result = cluster_and_label(
                    store,
                    client,
                    config.clustering,
                    label=label,
                    re_embed=re_embed,
                    announce=announce,
                )
            except (httpx.HTTPError, ValueError) as exc:
                echo(f"Error: embedding/clustering failed: {sanitise(str(exc))}")
                return ExitCode.ERROR
            progress.update(ptask, completed=len(groups))

        # RAG-07: when --kb is given, index the runbook/RCA directory and
        # retrieve the nearest chunks against the top salient clusters, then
        # thread them into the triage prompt as NON-citable reference
        # material (D-01). KB embeds through the SAME injected client whose
        # SSRF guard already ran on both base_urls (LLM-02) — no new HTTP
        # path. An embed/index failure maps to exit 1 with a sanitised
        # message, mirroring the cluster-embed failure above (T-06-19).
        kb_context: list[str] | None = None
        if kb is not None:
            try:
                retrieve.index_kb(store, client, kb)
                query_texts = [
                    c.label or c.signature
                    for c in store.query_clusters()[:top_clusters]
                ]
                kb_context = retrieve.retrieve_kb(store, client, query_texts)
            except (httpx.HTTPError, ValueError) as exc:
                echo(f"Error: KB indexing/retrieval failed: {sanitise(str(exc))}")
                return ExitCode.ERROR

        # D-10: resolve the prompt-budget context window ONCE, here, after
        # the Progress live region has exited so no bar redraw can overwrite
        # the warning. A configured generation.context wins over anything
        # /props reports; an estimated budget is disclosed on stderr.
        # Passing the resolved int as ctx_configured short-circuits
        # _ctx_tokens' own probe, so analyze issues exactly one /props GET.
        ctx_tokens, ctx_warning = resolve_generation_ctx(
            config.generation.context, client
        )
        if ctx_warning is not None:
            echo_err(ctx_warning)

        # RAG-02: salience + citation-gated hypotheses over the fresh
        # clusters, still inside the http lifecycle so the same client is
        # reused. hypothesise NEVER raises on bad model output — it degrades
        # and persists; a transport/SSRF error returns a failed Outcome.
        # --until doubles as the salience incident-time anchor (RESEARCH Q3);
        # None lets salience derive it from the case-end timestamp.
        outcome = hypothesise(
            store,
            client,
            top_clusters=top_clusters,
            incident_time=until,
            since=since,
            until=until,
            hint=hint,
            kb_context=kb_context,
            analyser_settings=AnalyserSettings.from_config(config),
            # ctx_fallback/reserve_out stay on their hypothesise defaults (the
            # shared TRIAGE_* constants); ctx_configured is the load-bearing
            # resolved window from resolve_generation_ctx above.
            ctx_configured=ctx_tokens,
        )
    finally:
        http.close()

    # Counts are ints — no untrusted text. The labels themselves are only
    # rendered by `show clusters`, where the whole line is sanitise'd.
    labelled = sum(1 for c in store.query_clusters() if c.label)
    # D-06: always printed, including a first run where reused is 0 — a
    # stable shape is what tests assert, and zero reuse is itself a signal.
    echo(
        f"Embeddings: {cluster_result.embedded_count} new, "
        f"{cluster_result.reused_count} reused"
    )
    echo(f"Clusters: {cluster_result.cluster_count} ({labelled} labelled)")

    # CLI-04 exit-code contract: failed -> 1, degraded -> 3, success -> 0.
    # (Typer/Click usage errors stay 2; never reused here.)
    if outcome.failed:
        # Surface the real cause (a transport failure, OR a server-rejected
        # 200 body such as a context overflow — 'request (N tokens) exceeds
        # the available context size') instead of always blaming transport.
        # A context overflow is fixed by loading the model with a larger
        # context, lowering --top-clusters, or setting generation.context.
        reason = outcome.error or "the inference endpoint returned no output"
        echo(
            f"Error: hypothesis generation failed ({sanitise(reason)}); "
            "no hypotheses were persisted"
        )
        return ExitCode.ERROR
    count = len(outcome.hypotheses.hypotheses) if outcome.hypotheses else 0
    if outcome.degraded:
        # A degraded run RAN to completion but the model output could not be
        # fully validated or some citations were invalid — the flagged/raw
        # output is persisted, never presented as a clean success (T-04-02).
        echo_err(
            "Warning: triage degraded — the model output could not be fully "
            "validated or some citations were invalid; the raw/flagged "
            "output was persisted (see 'sift show hypotheses')"
        )
        echo(f"Hypotheses: {count} (degraded)")
        return ExitCode.DEGRADED
    echo(f"Hypotheses: {count}")
    echo("Run 'sift show hypotheses' to view them")
    return ExitCode.SUCCESS
