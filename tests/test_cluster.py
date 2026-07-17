"""Semantic clustering + labelling tests (CLUS-02, CLUS-03, CLI-02, EVAL-05).

Every embedding and chat call is faked with ``httpx.MockTransport`` — no socket
opens (EVAL-05). Vectors are planted deterministically: two ``alpha`` synonyms
sit on one axis, two ``beta`` synonyms on a second, and a lone ``gamma`` noise
point sits orthogonal to both, so HDBSCAN merges the synonyms and leaves the
noise a singleton. The store is a real on-disk tmp_path case.db seeded via the
Phase-2 dedup path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from sift.config import ClusteringConfig
from sift.llm.client import Endpoint, InferenceClient
from sift.models import Event, event_id
from sift.pipeline import cluster, dedup
from sift.store import CaseStore

Handler = Callable[[httpx.Request], httpx.Response]
_BASE = datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC)

# Planted 8-dim vectors: alpha synonyms near-identical on axis 0, beta synonyms
# on axis 1, gamma noise orthogonal on axis 7. Two clusters of two give HDBSCAN
# enough density to form clusters; gamma falls out as noise (-1 -> singleton).
_ALPHA_A = "alpha memory pressure warning"
_ALPHA_B = "alpha memory watermark exceeded"
_BETA_A = "beta smtp delivery retries"
_BETA_B = "beta smtp queue backing up"
_GAMMA = "gamma unrelated disk anomaly"

_VECTORS: dict[str, list[float]] = {
    _ALPHA_A: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _ALPHA_B: [0.99, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _BETA_A: [0.02, 0.99, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _BETA_B: [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _GAMMA: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
}

_SYNONYM_CORPUS = [_ALPHA_A, _ALPHA_B, _BETA_A, _BETA_B, _GAMMA]


def _ev(offset: int, message: str) -> Event:
    return Event(
        event_id=event_id("case.log", offset),
        case_id="demo",
        ts=_BASE,
        ts_confidence="exact",
        source="genericlog",
        source_file="case.log",
        line_start=offset + 1,
        line_end=offset + 1,
        severity="error",
        component=None,
        thread=None,
        session=None,
        message=message,
        attrs={},
        raw=message,
    )


def _seed(store: CaseStore, messages: list[str]) -> None:
    """Insert one event per message and rebuild template groups (one per msg)."""
    events = [_ev(i, m) for i, m in enumerate(messages)]
    with store.transaction():
        store.insert_events(events)
    dedup.rebuild_template_groups(store)


def _embed_handler(calls: list[str] | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            if calls is not None:
                calls.append("embeddings")
            data = [
                {"index": i, "embedding": _VECTORS.get(text, [0.0] * 8)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        return httpx.Response(404)

    return handler


def _client(handler: Handler) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _template_id(message: str) -> str:
    return dedup.template_id(dedup.mask(message))


def _cluster_of(store: CaseStore, message: str) -> int:
    tid = _template_id(message)
    for c in store.query_clusters():
        if tid in c.template_ids:
            return c.cluster_id
    raise AssertionError(f"no cluster contains template for {message!r}")


# --- CLUS-02: merge synonyms, noise -> singleton -------------------------


def test_cluster_merges_synonyms_and_singletons_noise(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        n = cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        # alpha+beta merge into two clusters, gamma is a noise singleton -> 3.
        assert n == 3
        assert _cluster_of(store, _ALPHA_A) == _cluster_of(store, _ALPHA_B)
        assert _cluster_of(store, _BETA_A) == _cluster_of(store, _BETA_B)
        gamma_id = _cluster_of(store, _GAMMA)
        by_id = {c.cluster_id: c for c in store.query_clusters()}
        assert by_id[gamma_id].count == 1  # gamma stands alone
        assert by_id[gamma_id].template_ids == [_template_id(_GAMMA)]
    finally:
        store.close()


def test_cluster_zero_groups_returns_zero_no_embed(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    calls: list[str] = []
    try:
        n = cluster.cluster_and_label(
            store, _client(_embed_handler(calls)), ClusteringConfig()
        )
        assert n == 0
        assert calls == []  # no embedding call when there are no groups
        assert store.query_clusters() == []
    finally:
        store.close()


def test_cluster_single_group_is_one_singleton(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, [_ALPHA_A])
        n = cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        assert n == 1
        (only,) = store.query_clusters()
        assert only.count == 1
        assert only.template_ids == [_template_id(_ALPHA_A)]
    finally:
        store.close()


def test_cluster_assignment_is_deterministic(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cfg = ClusteringConfig()
        cluster.cluster_and_label(store, _client(_embed_handler()), cfg)
        first = [(c.cluster_id, tuple(c.template_ids)) for c in store.query_clusters()]
        cluster.cluster_and_label(store, _client(_embed_handler()), cfg)
        second = [(c.cluster_id, tuple(c.template_ids)) for c in store.query_clusters()]
        assert first == second
    finally:
        store.close()


def test_cluster_agglomerative_fallback_routes_and_merges(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cfg = ClusteringConfig(algorithm="agglomerative", distance_threshold=0.3)
        n = cluster.cluster_and_label(store, _client(_embed_handler()), cfg)
        assert n == 3
        assert _cluster_of(store, _ALPHA_A) == _cluster_of(store, _ALPHA_B)
        assert _cluster_of(store, _GAMMA) != _cluster_of(store, _ALPHA_A)
    finally:
        store.close()


def test_cluster_persists_vectors_and_chunks(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(store, _client(_embed_handler()), ClusteringConfig())
        assert store.get_meta("embedding_dim") == "8"
        chunk_rows = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT count(*) FROM chunks"
        ).fetchone()[0]
        vec_rows = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT count(*) FROM vectors"
        ).fetchone()[0]
        assert chunk_rows == len(_SYNONYM_CORPUS)
        assert vec_rows == len(_SYNONYM_CORPUS)
    finally:
        store.close()
