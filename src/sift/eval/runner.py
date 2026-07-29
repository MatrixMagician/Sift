"""Per-case orchestration: drive one golden case through the pipeline (EVAL-02).

``run_case`` reuses the exact calls ``sift analyze`` makes — ``ingest.run_ingest``
then ``dedup.rebuild_template_groups`` (inside it), ``cluster_and_label`` and
``hypothesise`` — against a temp ``case.db`` under a tempfile-managed directory
(never the user's real data dir, mirroring the conftest XDG isolation, T-07-06).
Every metric is then a pure read of the persisted rows against the frozen
``truth.yaml``. Determinism (D-06) runs the pipeline ``repeats`` times from the
same ingested state on fresh db copies and compares the normalised JSON.

The harness owns no inference logic — it sequences existing pipeline functions
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

from sift.eval.judge import judge_case
from sift.eval.metrics import (
    CaseResult,
    citation_validity_rate,
    determinism_stability,
    hypothesis_hit_at_k,
    retrieval_hit_rate,
)
from sift.eval.truth import load_truth
from sift.pipeline.cluster import cluster_and_label
from sift.pipeline.hypothesise import (
    DEFAULT_TOP_CLUSTERS,
    TRIAGE_CTX_FALLBACK,
    TRIAGE_RESERVE_OUT,
    hypothesise,
)
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


def _run_pipeline(
    db_path: Path, client: InferenceClient, config: SiftConfig, top_clusters: int
) -> None:
    """Cluster + label + hypothesise one ingested case.db (in place)."""
    store = CaseStore(db_path)
    try:
        cluster_and_label(store, client, config.clustering, label=True)
        # A negative/quiet case still runs the full triage; incident_time=None
        # lets salience derive the anchor from the case-end timestamp. These are
        # the analyze triage defaults reused verbatim (shared constants in
        # pipeline.hypothesise — eval never imports the CLI).
        hypothesise(
            store,
            client,
            top_clusters=top_clusters,
            incident_time=None,
            ctx_fallback=TRIAGE_CTX_FALLBACK,
            reserve_out=TRIAGE_RESERVE_OUT,
        )
    finally:
        # A clean close checkpoints the WAL on every path (Pitfall 4).
        store.close()


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
    except (httpx.HTTPError, ValueError) as exc:
        from sift.render._util import sanitise  # noqa: PLC0415

        return CaseResult(
            name=name,
            retrieval_hit_rate=0.0,
            hypothesis_hit_at_k=0.0,
            citation_validity_rate=0.0,
            determinism_stability=0.0,
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
        retrieval_hit_rate=0.0,
        hypothesis_hit_at_k=0.0,
        citation_validity_rate=0.0,
        determinism_stability=0.0,
        is_eustack=True,
        eustack_case_pass=_eustack_verdict(bundle, expect),
    )


def run_case(
    case_dir: Path,
    client: InferenceClient,
    config: SiftConfig,
    *,
    repeats: int = 2,
    k: int = 3,
    judge: bool = False,
) -> CaseResult:
    """Score one golden case end-to-end and return its ``CaseResult``.

    ``repeats`` (D-06, N) independent pipeline runs on fresh copies of the
    post-ingest db drive the determinism metric; the first run's persisted rows
    drive the keyword metrics. A transport/parse failure surfaces as a
    ``run_failed`` result rather than crashing the whole suite.

    When ``judge`` is set, the first run's hypotheses are additionally graded
    against ``truth.root_cause`` by the advisory LLM-as-judge (EVAL-04); the
    score is attached to ``CaseResult.judge_score`` but NEVER enters any metric
    or gate (D-08). ``judge_case`` degrades to ``None`` on any error, so it
    cannot turn a scored case into a ``run_failed`` one."""
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
        # _ingest prints coverage to stdout and the store prints migration
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
                    _run_pipeline(run_db, client, config, top_clusters)
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
                retrieval_hit_rate=0.0,
                hypothesis_hit_at_k=0.0,
                citation_validity_rate=0.0,
                determinism_stability=0.0,
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
    judged = judge_case(client, truth, hyps) if judge else None
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
