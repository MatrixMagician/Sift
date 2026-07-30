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
from collections.abc import Callable, Sequence
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


def _ev(offset: int, message: str, source: str = "genericlog") -> Event:
    return Event(
        event_id=event_id("case.log", offset),
        case_id="demo",
        ts=_BASE,
        ts_confidence="exact",
        source=source,
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
        ).cluster_count
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


def test_exemplars_exclude_perfmon(tmp_path: Path) -> None:
    """PERF-03 belt-and-braces: no perfmon message reaches a cluster exemplar.

    Strictly weaker than test_template_groups_exclude_perfmon in
    tests/test_store.py — exemplars derive from template groups, so identical
    template groups make this identical by construction. Kept because it
    exercises the assertion through the real clustering path.
    """
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        # Perfmon samples inserted AFTER the log corpus, at non-colliding
        # offsets (event_id = sha256(source_file, byte_offset)).
        samples = [
            _ev(1000 + i, f"Total MCM Denial = {i}", "dssperfmon") for i in range(5)
        ]
        with store.transaction():
            store.insert_events(samples)
        dedup.rebuild_template_groups(store)

        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        exemplars = {
            row[0]
            for row in store._conn.execute(  # pyright: ignore[reportPrivateUsage]
                "SELECT text FROM chunks"
            )
        }
        assert exemplars, "no exemplars persisted — assertion would be vacuous"
        assert not [t for t in exemplars if "MCM Denial" in t]
    finally:
        store.close()


def test_cluster_zero_groups_returns_zero_no_embed(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    calls: list[str] = []
    try:
        n = cluster.cluster_and_label(
            store, _client(_embed_handler(calls)), ClusteringConfig()
        ).cluster_count
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
        ).cluster_count
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
        n = cluster.cluster_and_label(
            store, _client(_embed_handler()), cfg
        ).cluster_count
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


# --- DET-01: embedding vector reuse --------------------------------------


def test_cluster_and_label_returns_result_dataclass(tmp_path: Path) -> None:
    """D-05: the split travels on the return value, not just in meta."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        result = cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        assert isinstance(result, cluster.ClusterResult)
        assert result.cluster_count == 3
        assert result.embedded_count + result.reused_count == len(_SYNONYM_CORPUS)
    finally:
        store.close()


def test_reuse_empty_on_first_run_embeds_everything(tmp_path: Path) -> None:
    """A fresh case has no vectors table: reuse degrades to a full embed."""
    store = CaseStore(tmp_path / "case.db")
    calls: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        assert store.load_vectors_by_text() == {}
        result = cluster.cluster_and_label(
            store, _client(_embed_handler(calls)), ClusteringConfig()
        )
        assert result.embedded_count == len(_SYNONYM_CORPUS)
        assert result.reused_count == 0
        assert calls.count("embeddings") == 1
        assert store.get_meta("embedding_new_count") == str(len(_SYNONYM_CORPUS))
        assert store.get_meta("embedding_reused_count") == "0"
    finally:
        store.close()


def test_reuse_zero_embeds_on_unchanged_case(tmp_path: Path) -> None:
    """DET-01 headline: a second run makes ZERO embedding HTTP calls."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        first = cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        before = [
            (c.cluster_id, tuple(c.template_ids)) for c in store.query_clusters()
        ]

        calls: list[str] = []
        second = cluster.cluster_and_label(
            store, _client(_embed_handler(calls)), ClusteringConfig()
        )
        assert "embeddings" not in calls
        assert second.reused_count == len(_SYNONYM_CORPUS)
        assert second.embedded_count == 0
        assert second.cluster_count == first.cluster_count
        # The splice preserved order: identical cluster membership.
        after = [(c.cluster_id, tuple(c.template_ids)) for c in store.query_clusters()]
        assert after == before
        assert store.get_meta("embedding_new_count") == "0"
        assert store.get_meta("embedding_reused_count") == str(len(_SYNONYM_CORPUS))
    finally:
        store.close()


def test_reuse_partial_cache_embeds_only_misses(tmp_path: Path) -> None:
    """An interrupted prior run leaves a partial cache: only misses embed."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        full = cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        expected = [
            (c.cluster_id, tuple(c.template_ids)) for c in store.query_clusters()
        ]
        # Evict exactly one cached vector, simulating a partial cache.
        victim = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT chunk_id FROM chunks ORDER BY chunk_id LIMIT 1"
        ).fetchone()[0]
        with store.transaction():
            store._conn.execute(  # pyright: ignore[reportPrivateUsage]
                "DELETE FROM vectors WHERE chunk_id = ?", (victim,)
            )

        calls: list[str] = []
        mixed = cluster.cluster_and_label(
            store, _client(_embed_handler(calls)), ClusteringConfig()
        )
        assert mixed.embedded_count == 1
        assert mixed.reused_count == len(_SYNONYM_CORPUS) - 1
        assert calls.count("embeddings") == 1
        assert mixed.cluster_count == full.cluster_count
        # Mixed hit/miss membership matches the all-miss run (order preserved).
        assert [
            (c.cluster_id, tuple(c.template_ids)) for c in store.query_clusters()
        ] == expected
    finally:
        store.close()


def _client_with_model(handler: Handler, model: str) -> InferenceClient:
    """A client whose CONFIGURED embeddings model is known (D-03's client side).

    A variant rather than a parameter on ``_client``: ``_client``'s
    ``model=None`` is itself the unknown-client-side case D-04 covers, and
    every shipped test depends on it.
    """
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=model)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _tables(store: CaseStore) -> set[str]:
    """The case's table set, for proving --re-embed performs no DDL (D-07)."""
    return {
        row[0]
        for row in store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def test_reuse_invalidated_on_model_change(tmp_path: Path) -> None:
    """D-03: a PROVEN model change discards the whole cache."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client_with_model(_embed_handler(), "model-a"), ClusteringConfig()
        )
        assert store.get_meta("embedding_model") == "model-a"

        calls: list[str] = []
        result = cluster.cluster_and_label(
            store,
            _client_with_model(_embed_handler(calls), "model-b"),
            ClusteringConfig(),
        )
        assert result.embedded_count == len(_SYNONYM_CORPUS)
        assert result.reused_count == 0
        assert calls.count("embeddings") == 1
        assert store.get_meta("embedding_model") == "model-b"
    finally:
        store.close()


def test_reuse_proceeds_silently_when_model_unchanged(tmp_path: Path) -> None:
    """D-03: both sides known and equal reuses with no disclosure."""
    store = CaseStore(tmp_path / "case.db")
    announced: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client_with_model(_embed_handler(), "model-a"), ClusteringConfig()
        )
        result = cluster.cluster_and_label(
            store,
            _client_with_model(_embed_handler(), "model-a"),
            ClusteringConfig(),
            announce=announced.append,
        )
        assert result.reused_count == len(_SYNONYM_CORPUS)
        assert announced == []
    finally:
        store.close()


@pytest.mark.parametrize("stored_model", [None, "model-a"])
def test_reuse_proceeds_with_warning_on_unknown_identity(
    tmp_path: Path, stored_model: str | None
) -> None:
    """D-04: unverifiable identity reuses AND discloses, never silently.

    Parametrised over both unknown sides: no ``meta.embedding_model`` (the
    endpoint named no model on the first run) and a known stored model against
    a client that names none.
    """
    store = CaseStore(tmp_path / "case.db")
    announced: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        first_client = (
            _client(_embed_handler())
            if stored_model is None
            else _client_with_model(_embed_handler(), stored_model)
        )
        cluster.cluster_and_label(store, first_client, ClusteringConfig())
        assert store.get_meta("embedding_model") == stored_model

        # _client's Endpoint carries model=None — the unknown client side.
        result = cluster.cluster_and_label(
            store,
            _client(_embed_handler()),
            ClusteringConfig(),
            announce=announced.append,
        )
        assert result.reused_count == len(_SYNONYM_CORPUS)
        assert result.embedded_count == 0
        assert len(announced) == 1
        assert "without a verifiable model identity" in announced[0]
    finally:
        store.close()


def test_reuse_no_warning_on_first_run_with_unknown_identity(
    tmp_path: Path,
) -> None:
    """A first run has nothing reused, so there is nothing to disclose."""
    store = CaseStore(tmp_path / "case.db")
    announced: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store,
            _client(_embed_handler()),
            ClusteringConfig(),
            announce=announced.append,
        )
        assert announced == []
    finally:
        store.close()


def test_reuse_discarded_when_stored_vector_width_differs(tmp_path: Path) -> None:
    """T-20-08: a changed width discards the cache and surfaces STORE-03.

    The operator must keep receiving the ``embedding dimension mismatch``
    error naming both dimensions, never an opaque numpy ragged-array failure —
    that error is what points them at ``--re-embed``.
    """
    store = CaseStore(tmp_path / "case.db")

    def _narrow_handler(request: httpx.Request) -> httpx.Response:
        """Same shape as _embed_handler, but 4-wide instead of 8-wide."""
        if request.url.path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": [1.0, 0.0, 0.0, 0.0]}
                for i, _ in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    try:
        # Seed the cache at 8 dimensions, then add one new message so the
        # second run has a miss to embed (that fresh 4-wide vector is what
        # exposes the width change).
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        assert store.get_meta("embedding_dim") == "8"
        _seed(store, [*_SYNONYM_CORPUS, "delta fresh unseen message"])

        with pytest.raises(ValueError, match="embedding dimension mismatch"):
            cluster.cluster_and_label(
                store, _client(_narrow_handler), ClusteringConfig()
            )
        # The failed run left the shipped 8-dim lock intact.
        assert store.get_meta("embedding_dim") == "8"
    finally:
        store.close()


def test_re_embed_bypasses_cache_without_ddl(tmp_path: Path) -> None:
    """D-07: --re-embed re-embeds everything and touches no table definition."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        before = _tables(store)
        assert "vectors" in before, "cache not populated — assertion would be vacuous"

        calls: list[str] = []
        result = cluster.cluster_and_label(
            store,
            _client(_embed_handler(calls)),
            ClusteringConfig(),
            re_embed=True,
        )
        assert calls.count("embeddings") == 1
        assert result.embedded_count == len(_SYNONYM_CORPUS)
        assert result.reused_count == 0
        assert _tables(store) == before
    finally:
        store.close()


def test_re_embed_on_empty_cache_embeds_everything(tmp_path: Path) -> None:
    """--re-embed on a case with nothing stored is a graceful full embed."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        result = cluster.cluster_and_label(
            store,
            _client(_embed_handler()),
            ClusteringConfig(),
            re_embed=True,
        )
        assert result.embedded_count == len(_SYNONYM_CORPUS)
        assert result.reused_count == 0
        assert result.cluster_count == 3
    finally:
        store.close()


def test_re_embed_suppresses_the_unverified_identity_warning(
    tmp_path: Path,
) -> None:
    """Nothing is reused under --re-embed, so there is nothing to disclose."""
    store = CaseStore(tmp_path / "case.db")
    announced: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        cluster.cluster_and_label(
            store,
            _client(_embed_handler()),
            ClusteringConfig(),
            re_embed=True,
            announce=announced.append,
        )
        assert announced == []
    finally:
        store.close()


def _width_handler(width: int, calls: list[str] | None = None) -> Handler:
    """An embed handler returning vectors of an arbitrary width.

    A local variant rather than a parameter on the shared ``_embed_handler``,
    whose planted 8-dim ``_VECTORS`` every other test in this file depends on.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            if calls is not None:
                calls.append("embeddings")
            data = [
                {"index": i, "embedding": [1.0, *([0.0] * (width - 1))]}
                for i, _ in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        if calls is not None:
            calls.append("chat")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    return handler


def test_dimension_change_without_re_embed_still_hard_raises(
    tmp_path: Path,
) -> None:
    """D-03: without --re-embed the shipped STORE-03 hard error is unchanged."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        before = _tables(store)

        # A fresh, unseen message guarantees a miss, so a 4-wide vector really
        # reaches the splice and the dimension change is genuinely exercised.
        _seed(store, [*_SYNONYM_CORPUS, "delta fresh unseen message"])
        with pytest.raises(ValueError, match="embedding dimension mismatch"):
            cluster.cluster_and_label(
                store, _client(_width_handler(4)), ClusteringConfig()
            )
        assert _tables(store) == before, "a failed run must drop nothing"
        assert store.get_meta("embedding_dim") == "8"
    finally:
        store.close()


def test_re_embed_rebuilds_at_new_dimension_and_announces(tmp_path: Path) -> None:
    """D-08/D-09: --re-embed drops both tables, announces the blast radius."""
    store = CaseStore(tmp_path / "case.db")
    announced: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        assert store.get_meta("embedding_dim") == "8"

        result = cluster.cluster_and_label(
            store,
            _client(_width_handler(4)),
            ClusteringConfig(),
            re_embed=True,
            announce=announced.append,
        )
        assert len(announced) == 1
        message = announced[0]
        assert "dimension changed" in message
        assert "8 -> 4" in message
        # The real counted totals, not a nominal figure.
        assert f"{len(_SYNONYM_CORPUS)} stored vectors" in message
        assert "0 KB vectors" in message

        assert store.get_meta("embedding_dim") == "4"
        assert result.embedded_count == len(_SYNONYM_CORPUS)
        assert result.reused_count == 0
        # The rebuilt table really is 4-wide: a 4-wide reuse read round-trips.
        widths = {len(v) for v in store.load_vectors_by_text().values()}
        assert widths == {4}
    finally:
        store.close()


def test_re_embed_at_unchanged_dimension_announces_nothing(tmp_path: Path) -> None:
    """The 20-02 behaviour is untouched: no drop, no announcement."""
    store = CaseStore(tmp_path / "case.db")
    announced: list[str] = []
    try:
        _seed(store, _SYNONYM_CORPUS)
        cluster.cluster_and_label(
            store, _client(_embed_handler()), ClusteringConfig()
        )
        before = _tables(store)
        cluster.cluster_and_label(
            store,
            _client(_embed_handler()),
            ClusteringConfig(),
            re_embed=True,
            announce=announced.append,
        )
        assert announced == []
        assert _tables(store) == before
        assert store.get_meta("embedding_dim") == "8"
    finally:
        store.close()


def test_cluster_records_batch_knobs_even_without_model_identity(
    tmp_path: Path,
) -> None:
    """0014: knobs are recorded even on the D-03 model-is-None path."""
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed(store, _SYNONYM_CORPUS)
        http = httpx.Client(transport=httpx.MockTransport(_embed_handler()))
        ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
        client = InferenceClient(
            ep,
            ep,
            http,
            backoff_base=0.0,
            batch_size=2,
            max_input_chars=100,
            context=123,
        )
        cluster.cluster_and_label(store, client, ClusteringConfig())
        assert store.get_meta("embedding_model") is None
        assert store.get_meta("embedding_context") == "123"
        assert store.get_meta("embedding_batch_size") == "2"
        assert store.get_meta("embedding_max_input_chars") == "100"
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


class _CtxCappedClient:
    """A fake client whose chat rejects a prompt carrying more than ``capacity``
    numbered excerpts — mimicking llama-server's ``exceed_context_size`` 400 that
    made a single large batched label call return zero labels for the whole case.
    """

    has_tokenize = False

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.calls = 0

    def tokenize(self, text: str) -> int | None:  # PromptBudget seam (unused)
        return None

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        response_format: dict[str, object] | None = None,
    ) -> str:
        self.calls += 1
        prompt = messages[0]["content"]
        n = sum(
            1 for line in prompt.splitlines() if line.split(". ", 1)[0].isdigit()
        )
        if n > self.capacity:
            raise ValueError("chat response has no choices")  # 400 overflow
        return json.dumps({str(i): f"label-{i}" for i in range(n)})


def test_label_clusters_chunks_large_case_within_context() -> None:
    # More clusters than one context-bounded call can hold: a single batched
    # call overflows (0 labelled); chunking must still name every cluster.
    n = cluster._LABEL_CHUNK + 6  # pyright: ignore[reportPrivateUsage]
    ids = list(range(n))
    excerpts = [f"excerpt for cluster {i}" for i in range(n)]
    client = _CtxCappedClient(capacity=cluster._LABEL_CHUNK)  # pyright: ignore[reportPrivateUsage]
    labels = cluster._label_clusters(client, ids, excerpts, "T:\n")  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    assert len(labels) == n  # every cluster labelled despite the per-call cap
    assert client.calls == 2  # split into chunks, not one oversized call
