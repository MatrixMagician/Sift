"""Per-case orchestration: drive one golden case through the pipeline (EVAL-02).

``run_case`` calls the SHIPPED analyse body — ``ingest.run_ingest`` (which runs
``dedup.rebuild_template_groups`` inside it), then ``commands.run_analyze`` —
against a temp ``case.db`` under a tempfile-managed directory (never the user's
real data dir, mirroring the conftest XDG isolation, T-07-06). Every metric is
then a pure read of the persisted rows against the frozen ``truth.yaml``.
Determinism (D-06) runs the pipeline ``repeats`` times from the same ingested
state on fresh db copies and compares the normalised JSON.

Calling ``run_analyze`` rather than re-sequencing its parts is what makes the
harness measure the pipeline Sift actually ships (ADR 0019). The re-implementation
it replaced had drifted in three ways at once, each silently: it omitted
``analyser_settings`` (so MCM and eu-stack analysers ran on default thresholds
rather than the operator's), it never resolved ``generation.context`` (so a
pinned window was ignored), and its client was built without ``tuned_embeddings``
(so the embedding knobs differed too). None of the three was reachable by a test,
because a second orchestration is not wrong in any single line — it is wrong by
omission, and omissions have no line to assert on.

The harness owns no inference logic — it sequences the shipped command bodies
and reads rows back. This module is the only one in the package that touches the
store or the client.

An eu-stack case (``truth.expect_eustack is not None``, EUS-12) is LLM-free:
``run_case`` dispatches it to ``_run_eustack_case`` immediately after loading
``truth.yaml``, which ingests the case and scores ``analyse_eustack_bundle``'s
output directly — no ``cluster_and_label``, no ``hypothesise``, no client
contact at all (D-19-06/D-19-16). Every other case in the suite still requires
a live inference endpoint.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from sift.commands import ExitCode, is_failure, run_analyze
from sift.eval.judge import judge_case
from sift.eval.metrics import (
    CaseResult,
    citation_validity_rate,
    determinism_stability,
    hypothesis_hit_at_k,
    retrieval_hit_rate,
)
from sift.eval.truth import load_truth
from sift.pipeline.hypothesise import DEFAULT_TOP_CLUSTERS
from sift.pipeline.ingest import run_ingest
from sift.render.json_out import normalise_for_determinism, render_json
from sift.store import CaseStore

if TYPE_CHECKING:
    from sift.config import SiftConfig
    from sift.eval.truth import ExpectEustack
    from sift.llm.client import InferenceClient
    from sift.pipeline.eustack_progression import EustackBundle


def _cluster_exemplar_texts(store: CaseStore, top_clusters: int) -> list[str]:
    """The exemplar messages of the top-N salience-ranked clusters — the same
    slice fed to the hypothesiser (RESEARCH A1). Mirrors
    ``hypothesise._gather_exemplar_messages`` but scoped to the selected
    clusters' member template groups."""
    clusters = store.query_clusters()[:top_clusters]
    groups = {g.template_id: g for g in store.query_template_groups()}
    wanted: set[str] = set()
    for cluster in clusters:
        for template_id in cluster.template_ids:
            group = groups.get(template_id)
            if group is not None and group.exemplar_event_ids:
                wanted.add(group.exemplar_event_ids[0])
    if not wanted:
        return []
    texts: list[str] = []
    for eid, _ts, _severity, message in store.iter_event_summaries():
        if eid in wanted:
            texts.append(message)
            if len(texts) == len(wanted):
                break
    return texts


def _analyse(
    db_path: Path, config: SiftConfig, *, allow_public: bool, top_clusters: int
) -> tuple[ExitCode, list[str]]:
    """Run the shipped ``analyze`` body over one ingested case.db (in place).

    Returns the CLI-04 exit code plus every echoed line, for the caller to map
    onto a ``CaseResult`` — the same shape ``tui/app.py`` uses at this seam.

    ``run_analyze`` builds and closes its OWN client per run, through the
    ``llm.bringup.make_http_client`` seam offline tests bind to. That is the
    point rather than an inefficiency: a client eval constructed itself is a
    client eval could construct differently, which is exactly how the
    ``tuned_embeddings`` drift happened. ``since``/``until``/``hint``/``kb``
    stay unset — a golden case has no operator flags — and ``incident_time``
    therefore derives from the case-end timestamp, as before.
    """
    lines: list[str] = []
    store = CaseStore(db_path)
    try:
        code = run_analyze(
            store,
            config,
            allow_public=allow_public,
            top_clusters=top_clusters,
            echo=lines.append,
            echo_err=lines.append,
            # The metric table is the only thing eval emits; a progress
            # narration sink that discards is clearer than relying on the
            # CLI default's own non-TTY suppression.
            announce=lambda _message: None,
        )
    finally:
        # A clean close checkpoints the WAL on every path (Pitfall 4).
        store.close()
    return code, lines


def _eustack_verdict(bundle: EustackBundle, expect: ExpectEustack) -> bool:
    """Figure-reproduction comparison, per D-19-17 — never ``bool(flags)`` and
    never a new threshold over ``PoolOccupancy``/``DependencyWait`` (both
    explicitly rejected by D-19-17). A declared key with no matching row is a
    mismatch, not a skip.

    ``hang_detected`` is deliberately NOT compared here: D-19-17 established
    that Sift computes no deterministic hang verdict at all (``PoolOccupancy``/
    ``DependencyWait`` carry no threshold or severity), so there is no bundle
    figure to reproduce it against without inventing exactly the new judgement
    D-19-17 rejects. It stays a declarative field on the truth block for a
    human reading the fixture.
    """
    if bundle.analysis.total_threads != expect.total_threads:
        return False

    pools_by_subsystem = {p.subsystem: p for p in bundle.saturation.pools}
    for subsystem, busy_threads in expect.pools.items():
        pool = pools_by_subsystem.get(subsystem)
        if pool is None or pool.busy_threads != busy_threads:
            return False

    deps_by_subsystem = {d.subsystem: d for d in bundle.saturation.dependencies}
    for subsystem, thread_count in expect.dependencies.items():
        dependency = deps_by_subsystem.get(subsystem)
        if dependency is None or dependency.thread_count != thread_count:
            return False

    # Severity-bucketed flag comparison (D-19-18): warn/critical are exact
    # counts, info is the exact NAMED dimension set — an info dimension
    # escalating to warn changes both sides and is caught.
    warn_count = sum(1 for f in bundle.saturation.flags if f.severity == "warn")
    critical_count = sum(
        1 for f in bundle.saturation.flags if f.severity == "critical"
    )
    info_dimensions = {
        f.dimension for f in bundle.saturation.flags if f.severity == "info"
    }
    if warn_count != expect.warn or critical_count != expect.critical:
        return False
    return info_dimensions == set(expect.info_dimensions)


def _run_eustack_case(case_dir: Path, config: SiftConfig) -> CaseResult:
    """Score one eu-stack golden case reaching NO inference endpoint at all
    (D-19-06/D-19-16).

    A sibling to ``run_case``, never a threaded optional parameter through it
    — it reuses the exact ingest seeding sequence ``run_case`` uses, then
    calls ``load_rules``/``analyse_eustack_bundle`` directly on the ingested
    events. It never touches the clustering/labelling or hypothesis-
    generation stages, and never opens an HTTP connection of any kind. The
    four keyword-metric fields are the honest default ``0.0`` (never a
    fabricated ``1.0``) — they are excluded from every aggregate by
    ``CaseResult.is_eustack`` (``eval/metrics.py``).
    """
    name = case_dir.name
    truth = load_truth(case_dir / "truth.yaml")
    if truth.expect_eustack is None:
        raise AssertionError(
            "_run_eustack_case is only ever dispatched when expect_eustack is set"
        )
    expect = truth.expect_eustack

    noise = io.StringIO()
    try:
        with tempfile.TemporaryDirectory(prefix="sift-eval-eustack-") as tmp:
            seed_db = Path(tmp) / "seed.db"
            with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
                seed = CaseStore(seed_db)
                try:
                    seed.set_meta("input_dir", str((case_dir / "input").resolve()))
                    seed.set_meta("adapter_overrides", "[]")
                    run_ingest(name, config, seed)
                    events = seed.query_events(sources=["eustack"])
                finally:
                    # A clean close checkpoints the WAL (Pitfall 4).
                    seed.close()
    except ValueError as exc:
        from sift.render._util import sanitise  # noqa: PLC0415

        return CaseResult(
            name=name,
            is_eustack=True,
            run_failed=True,
            error=sanitise(str(exc)),
        )

    # Resolved late through the module attribute (not a top-level from-import)
    # so tests can monkeypatch the ``load_rules`` seam on sift.pipeline.eustack.
    from sift.pipeline import eustack, eustack_progression  # noqa: PLC0415

    rules, rules_hash = eustack.load_rules(config.eustack.rules_path)
    bundle = eustack_progression.analyse_eustack_bundle(
        events, rules, rules_hash, config.eustack.thresholds
    )

    return CaseResult(
        name=name,
        is_eustack=True,
        eustack_case_pass=_eustack_verdict(bundle, expect),
    )


def run_case(
    case_dir: Path,
    config: SiftConfig,
    *,
    allow_public: bool = False,
    judge_client: InferenceClient | None = None,
    repeats: int = 2,
    k: int = 3,
) -> CaseResult:
    """Score one golden case end-to-end and return its ``CaseResult``.

    ``repeats`` (D-06, N) independent pipeline runs on fresh copies of the
    post-ingest db drive the determinism metric; the first run's persisted rows
    drive the keyword metrics. A transport/parse failure surfaces as a
    ``run_failed`` result rather than crashing the whole suite.

    EVERY run's exit code is checked, not just the first. ``is_failure`` (ADR
    0019) on any of them abandons the case: a case whose second run could not
    reach the endpoint has not been measured, and scoring it off run 0 alone
    would report a determinism figure built from fewer samples than declared.
    ``DEGRADED`` deliberately falls through — it persisted its (flagged) output,
    and ``citation_validity_rate`` is precisely the metric that scores it.

    ``judge_client`` is read on one path only: when given, the first run's
    hypotheses are additionally graded against ``truth.root_cause`` by the
    advisory LLM-as-judge (EVAL-04). The score is attached to
    ``CaseResult.judge_score`` but NEVER enters any metric or gate (D-08), and
    ``judge_case`` degrades to ``None`` on any error, so it cannot turn a scored
    case into a ``run_failed`` one. The analyse path does not use it — that
    client is built inside ``run_analyze``."""
    name = case_dir.name
    truth = load_truth(case_dir / "truth.yaml")
    # D-19-06/D-19-16: dispatch BEFORE any client work, right after loading
    # truth.yaml — the earliest possible branch point, so a half-run pipeline
    # state can never occur (19-CONTEXT.md).
    if truth.expect_eustack is not None:
        return _run_eustack_case(case_dir, config)
    top_clusters = DEFAULT_TOP_CLUSTERS

    with tempfile.TemporaryDirectory(prefix="sift-eval-") as tmp:
        tmp_dir = Path(tmp)
        seed_db = tmp_dir / "seed.db"
        docs: list[dict[str, object]] = []
        metric_texts: list[str] = []
        metric_hyps = None
        # run_ingest prints coverage to stdout and the store prints migration
        # notes to stderr; the metric table is the only thing eval should
        # emit, so contain both streams around all pipeline work here.
        noise = io.StringIO()
        try:
            with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
                seed = CaseStore(seed_db)
                try:
                    seed.set_meta("input_dir", str((case_dir / "input").resolve()))
                    seed.set_meta("adapter_overrides", "[]")
                    run_ingest(name, config, seed)
                finally:
                    # A clean close checkpoints the WAL so the file copies are
                    # complete (Pitfall 4).
                    seed.close()

                for i in range(max(repeats, 1)):
                    run_db = tmp_dir / f"run{i}.db"
                    shutil.copyfile(seed_db, run_db)
                    code, lines = _analyse(
                        run_db,
                        config,
                        allow_public=allow_public,
                        top_clusters=top_clusters,
                    )
                    if is_failure(code):
                        # run_analyze already sanitised whatever it echoed
                        # (WR-02), so the last line is reportable as-is.
                        return CaseResult(
                            name=name,
                            expect_no_incident=truth.expect_no_incident,
                            run_failed=True,
                            error=lines[-1] if lines else "analyze failed",
                        )
                    store = CaseStore(run_db)
                    try:
                        docs.append(
                            normalise_for_determinism(json.loads(render_json(store)))
                        )
                        if i == 0:
                            metric_texts = _cluster_exemplar_texts(store, top_clusters)
                            metric_hyps = store.query_hypotheses()
                    finally:
                        store.close()
        except (httpx.HTTPError, ValueError) as exc:
            from sift.render._util import sanitise

            return CaseResult(
                name=name,
                expect_no_incident=truth.expect_no_incident,
                run_failed=True,
                error=sanitise(str(exc)),
            )

    hyps = metric_hyps if metric_hyps is not None else []
    negative_pass = None
    if truth.expect_no_incident:
        from sift.eval.metrics import negative_case_pass

        negative_pass = negative_case_pass(hyps)
    # Advisory only (D-08): judge_case degrades to None on any error, so this can
    # never turn a scored case into a failure and is never read by the gate.
    judged = judge_case(judge_client, truth, hyps) if judge_client is not None else None
    return CaseResult(
        name=name,
        retrieval_hit_rate=retrieval_hit_rate(metric_texts, truth.required_evidence),
        hypothesis_hit_at_k=hypothesis_hit_at_k(hyps, truth.acceptable_keywords, k),
        citation_validity_rate=citation_validity_rate(hyps),
        determinism_stability=determinism_stability(docs),
        expect_no_incident=truth.expect_no_incident,
        negative_case_pass=negative_pass,
        judge_score=judged.score if judged is not None else None,
    )
