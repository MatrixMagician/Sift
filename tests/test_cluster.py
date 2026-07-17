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
import pytest

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


def _embed_handler(
    calls: list[str] | None = None, *, chat_content: str | None = None
) -> Handler:
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
        if path.endswith("/chat/completions"):
            if calls is not None:
                calls.append("chat")
            body = {"choices": [{"message": {"content": chat_content or "{}"}}]}
            return httpx.Response(200, json=body)
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


def test_failure_mid_transaction_does_not_lock_dimension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WR-02: the embedding-dimension lock (ensure_vectors_table's meta write +
    # vec0 DDL) must be atomic with the vector writes. If persistence fails
    # after the table is ensured, meta.embedding_dim must roll back — otherwise
    # a zero-vector case is permanently wedged and a later model/dim switch
    # hard-errors on the mismatch guard.
    store = CaseStore(tmp_path / "case.db")

    def _boom(*_: object, **__: object) -> None:
        raise RuntimeError("simulated mid-transaction failure")

    try:
        _seed(store, _SYNONYM_CORPUS)
        # replace_clusters runs inside the transaction, after ensure_vectors_table.
        monkeypatch.setattr(store, "replace_clusters", _boom)
        with pytest.raises(RuntimeError, match="simulated"):
            cluster.cluster_and_label(
                store, _client(_embed_handler()), ClusteringConfig()
            )
        # The failed run must leave no locked dimension behind.
        assert store.get_meta("embedding_dim") is None
        # Proof the case is not wedged: a fresh run at a *different* dim must not
        # trip the STORE-03 mismatch guard.
        monkeypatch.undo()
        store.ensure_vectors_table(16)
        assert store.get_meta("embedding_dim") == "16"
    finally:
        store.close()


# --- CLUS-03 / CLI-02: labelling from a versioned prompt -----------------


def test_label_sets_labels_on_right_clusters(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    content = json.dumps(
        {"0": "Memory watermark cascade", "1": "SMTP rejection storm", "2": "Disk"}
    )
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler(chat_content=content)), ClusteringConfig()
        )
        # cluster_ids are assigned 0,1,2 in canonical order, so response key i
        # maps to cluster_id i — every cluster carries its label.
        mapping = json.loads(content)
        for c in store.query_clusters():
            assert c.label == mapping[str(c.cluster_id)]
    finally:
        store.close()


def test_label_unparseable_keeps_signature(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store,
            _client(_embed_handler(chat_content="not json at all")),
            ClusteringConfig(),
        )
        for c in store.query_clusters():
            assert c.label is None  # degrade to signature, no crash
            assert c.signature  # signature is always present
    finally:
        store.close()


def test_label_disabled_skips_labelling(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    calls: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store,
            _client(_embed_handler(calls, chat_content="{}")),
            ClusteringConfig(),
            label=False,
        )
        assert "chat" not in calls  # no label call on the --no-label path
        assert all(c.label is None for c in store.query_clusters())
        assert store.get_meta("cluster_label_prompt_hash") is None
    finally:
        store.close()


def test_label_clusters_none_client_is_noop() -> None:
    assert cluster._label_clusters(None, [0], ["excerpt"], "T:\n") == {}  # pyright: ignore[reportPrivateUsage]


def test_label_british_spelling_round_trips(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    label = "Colour normalisation café backlog"  # British + non-ASCII
    content = json.dumps({"0": label})
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler(chat_content=content)), ClusteringConfig()
        )
        by_id = {c.cluster_id: c for c in store.query_clusters()}
        assert by_id[0].label == label
    finally:
        store.close()


def test_label_length_capped_by_code_points(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    content = json.dumps({"0": "x" * 500})
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler(chat_content=content)), ClusteringConfig()
        )
        by_id = {c.cluster_id: c for c in store.query_clusters()}
        assert by_id[0].label is not None
        assert len(by_id[0].label) <= 80  # capped by code points
    finally:
        store.close()


def test_label_prompt_hash_written_to_meta(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler(chat_content="{}")), ClusteringConfig()
        )
        expected = cluster._template_hash(cluster._load_template())  # pyright: ignore[reportPrivateUsage]
        assert store.get_meta("cluster_label_prompt_hash") == expected
    finally:
        store.close()


def test_editing_template_changes_prompt_no_python_change() -> None:
    prompt_a = cluster.build_label_prompt(["boom"], "TEMPLATE ALPHA\nClusters:\n")
    prompt_b = cluster.build_label_prompt(["boom"], "TEMPLATE BETA\nClusters:\n")
    assert prompt_a != prompt_b  # the template drives the assembled prompt
    assert "TEMPLATE ALPHA" in prompt_a
    assert "0. boom" in prompt_a
    # The loader reads the on-disk .md, so editing it changes the prompt with
    # zero Python change (CLI-02).
    loaded = cluster._load_template()  # pyright: ignore[reportPrivateUsage]
    assert "British English" in loaded
    assert loaded in cluster.build_label_prompt(["boom"], loaded)


def test_label_parse_lenient_ignores_bad_entries() -> None:
    parsed = cluster._parse_labels(  # pyright: ignore[reportPrivateUsage]
        '{"0": "good", "1": 42, "x": "skip", "2": "also good"}'
    )
    assert parsed == {0: "good", 2: "also good"}
