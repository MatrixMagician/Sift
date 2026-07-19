"""Per-case orchestration: drive one golden case through the pipeline (EVAL-02).

``run_case`` reuses the exact calls ``sift analyze`` makes — ``cli._ingest`` then
``dedup.rebuild_template_groups`` (inside ``_ingest``), ``cluster_and_label`` and
``hypothesise`` — against a temp ``case.db`` under a tempfile-managed directory
(never the user's real data dir, mirroring the conftest XDG isolation, T-07-06).
Every metric is then a pure read of the persisted rows against the frozen
``truth.yaml``. Determinism (D-06) runs the pipeline ``repeats`` times from the
same ingested state on fresh db copies and compares the normalised JSON.

The harness owns no inference logic — it sequences existing pipeline functions
and reads rows back. This module is the only one in the package that touches the
store or the client.
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

from sift.eval.metrics import (
    CaseResult,
    citation_validity_rate,
    determinism_stability,
    hypothesis_hit_at_k,
    retrieval_hit_rate,
)
from sift.eval.truth import load_truth
from sift.pipeline.cluster import cluster_and_label
from sift.pipeline.hypothesise import hypothesise
from sift.render.json_out import normalise_for_determinism, render_json
from sift.store import CaseStore

if TYPE_CHECKING:
    from sift.config import SiftConfig
    from sift.llm.client import InferenceClient


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
        # the analyze triage defaults reused verbatim (the sanctioned seam).
        from sift.cli import (  # noqa: PLC0415 — lazy import breaks a cli↔eval cycle
            _TRIAGE_CTX_FALLBACK,  # pyright: ignore[reportPrivateUsage]
            _TRIAGE_RESERVE_OUT,  # pyright: ignore[reportPrivateUsage]
        )

        hypothesise(
            store,
            client,
            top_clusters=top_clusters,
            incident_time=None,
            ctx_fallback=_TRIAGE_CTX_FALLBACK,
            reserve_out=_TRIAGE_RESERVE_OUT,
        )
    finally:
        # A clean close checkpoints the WAL on every path (Pitfall 4).
        store.close()


def run_case(
    case_dir: Path,
    client: InferenceClient,
    config: SiftConfig,
    *,
    repeats: int = 2,
    k: int = 3,
) -> CaseResult:
    """Score one golden case end-to-end and return its ``CaseResult``.

    ``repeats`` (D-06, N) independent pipeline runs on fresh copies of the
    post-ingest db drive the determinism metric; the first run's persisted rows
    drive the keyword metrics. A transport/parse failure surfaces as a
    ``run_failed`` result rather than crashing the whole suite."""
    # Reuse the analyze CLI seams verbatim (the sanctioned reuse points): the
    # top-clusters default and the ingest leg. Lazy import breaks a cli↔eval cycle.
    from sift.cli import (  # noqa: PLC0415
        _DEFAULT_TOP_CLUSTERS,  # pyright: ignore[reportPrivateUsage]
        _ingest,  # pyright: ignore[reportPrivateUsage]
    )

    name = case_dir.name
    truth = load_truth(case_dir / "truth.yaml")
    top_clusters = _DEFAULT_TOP_CLUSTERS

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
                    _ingest(name, config, seed)
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
    return CaseResult(
        name=name,
        retrieval_hit_rate=retrieval_hit_rate(metric_texts, truth.required_evidence),
        hypothesis_hit_at_k=hypothesis_hit_at_k(hyps, truth.acceptable_keywords, k),
        citation_validity_rate=citation_validity_rate(hyps),
        determinism_stability=determinism_stability(docs),
        expect_no_incident=truth.expect_no_incident,
        negative_case_pass=negative_pass,
    )
