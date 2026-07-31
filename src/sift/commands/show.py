"""``sift show`` — render a case's hypotheses, clusters, templates or events.

One function per target rather than one dispatching on a string (ADR 0019):
the TUI already has a screen per target, so each screen calls exactly one
function, and each function takes only the parameters its target uses —
``filters`` applies to events and clusters, never to hypotheses.

``run_show_templates`` has no CLI target of its own: it is the fallback the
clusters target renders before ``sift analyze`` has built any clusters, and a
directly-callable surface for the TUI's templates screen.
"""

from collections.abc import Callable

from sift.commands._echo import echo_stderr
from sift.commands._exit import ExitCode
from sift.render._util import sanitise
from sift.store import CaseStore

Filters = dict[str, str | int] | None


def run_show_hypotheses(
    store: CaseStore,
    *,
    echo: Callable[[str], None] = print,
    echo_err: Callable[[str], None] = echo_stderr,
) -> ExitCode:
    """Render the persisted, ranked hypotheses (RAG-02).

    ``query_hypotheses`` orders by ``hyp_index`` ASC. Nothing yet means analyze
    has not run — say so and succeed.
    """
    hyps = store.query_hypotheses()
    if not hyps:
        # WR-03: distinguish "analyze never ran" from a hard-degraded run
        # that persisted zero schema-valid rows but stored raw output —
        # the latter must not claim analyze never ran (nothing disappears
        # silently). triage_created_at is the "did analyze run" signal.
        if store.get_meta("triage_created_at") is not None:
            echo_err(
                "No schema-valid hypotheses; the last analyze degraded "
                "and persisted raw model output — run 'sift report' to "
                "view the DEGRADED banner and raw output"
            )
            return ExitCode.SUCCESS
        echo("No hypotheses yet; run 'sift analyze' first")
        return ExitCode.SUCCESS
    # A degraded run flagged rows or persisted raw output — warn on
    # stderr (mirrors the stale-groups warning) so stdout stays scriptable.
    if store.get_meta("triage_degraded") == "1":
        echo_err(
            "Warning: last analyze degraded — some hypotheses are FLAGGED "
            "(invalid citations) or raw output was persisted; treat "
            "flagged rows with care"
        )
    # WR-01: titles and cited ids are model-generated / DB-sourced and
    # attacker-controlled in a shared case.db — sanitise the COMPLETE
    # rendered line, never per field (T-04-03). FLAGGED marks a row whose
    # citations were not all shown to the model (never silently dropped).
    for h in hyps:
        marker = "OK" if h.citations_valid else "FLAGGED"
        title = h.title.replace("\n", " ")[:100]
        echo(sanitise(
            f"{h.hyp_index}  {h.confidence:<6}  {marker:<7}  {title}"
        ))
        echo(sanitise(
            f"    cites: {' '.join(map(str, h.supporting_event_ids))}"
        ))
    return ExitCode.SUCCESS


def run_show_clusters(
    store: CaseStore,
    *,
    filters: Filters = None,
    echo: Callable[[str], None] = print,
    echo_err: Callable[[str], None] = echo_stderr,
) -> ExitCode:
    """Render the semantic clusters, falling back to template groups (D-01).

    Once ``sift analyze`` has run, the clusters table is populated and IS the
    clusters view. Until then, the template groups are the pre-cluster view.
    The fallback is decided on the UNFILTERED table, so an applied filter that
    excludes every row still renders the clusters view (zero matches), never
    silently reverting to template groups.
    """
    # WR-03: events committed but groups never rebuilt (crash between
    # the event transaction and the rebuild) — warn, still render.
    if store.get_meta("template_groups_stale") == "1":
        echo_err(
            "Warning: template groups are stale (last ingest did not "
            "complete); re-run 'sift ingest'"
        )
    if store.query_clusters():
        # STORE-04: clusters, count DESC then cluster_id ASC. Labels are
        # model-generated and signatures carry hostile log bytes — WR-01:
        # sanitise the COMPLETE rendered line, not per field (T-03-20).
        for c in store.query_clusters(filters or None):
            name = (c.label or c.signature).replace("\n", " ")[:100]
            echo(sanitise(
                f"{c.cluster_id}  {c.count:>7}  {c.severity_max:<7}  {name}"
            ))
        return ExitCode.SUCCESS
    return run_show_templates(store, filters=filters, echo=echo)


def run_show_templates(
    store: CaseStore,
    *,
    filters: Filters = None,
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Render the template groups — the pre-cluster view (STORE-04).

    Count DESC then template ASC. Templates and exemplar text carry hostile
    log bytes — sanitise at render only (T-02-02); an empty table renders
    nothing and still succeeds. WR-01: EVERY DB-sourced field (ids, counts,
    timestamps, severities, exemplars) is attacker-controlled in a shared
    case.db, so the COMPLETE rendered line is sanitised, not each field.
    """
    for g in store.query_template_groups(filters or None):
        template = g.template.replace("\n", " ")[:100]
        echo(sanitise(
            f"{g.template_id}  {g.count:>7}  {g.severity_max:<7}  "
            f"{g.first_ts or '-'}  {g.last_ts or '-'}  {template}"
        ))
        echo(sanitise(
            f"    exemplars: {' '.join(map(str, g.exemplar_event_ids))}"
        ))
    return ExitCode.SUCCESS


def run_show_events(
    store: CaseStore,
    *,
    filters: Filters = None,
    echo: Callable[[str], None] = print,
) -> ExitCode:
    """Stream the case's events, newest filter semantics applied (T-02-10).

    Column-scoped rows — no raw column, no zstd decompression, no full Event
    hydration. Lines stay byte-identical to the Phase 1 rendering (stored ts
    strings ARE isoformat output). WR-01: whole-line sanitisation covers
    event_id/ts/severity too.
    """
    for event_id, ts, severity, source_file, line_start, message in (
        store.iter_event_rows(filters or None)
    ):
        rendered = message.replace("\n", " ")[:120]
        echo(sanitise(
            f"{event_id}  {ts if ts is not None else '-'}  {severity:<7}  "
            f"{source_file}:{line_start}  {rendered}"
        ))
    return ExitCode.SUCCESS
