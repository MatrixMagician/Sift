"""CaseStore embedding + cluster persistence tests (STORE-03, EVAL-05).

Covers migration 3 (chunks + clusters tables), the lazily-created sqlite-vec
vec0 vectors table with its dimension guard, the confined float32
(de)serialisation, and the caller-owns-transaction cluster/chunk methods. No
socket is ever opened — everything runs against an on-disk tmp_path case.db.
"""

import sqlite3
from pathlib import Path

import pytest

from sift.store import (
    CaseStore,
    Cluster,
    _blob_to_vec,  # pyright: ignore[reportPrivateUsage] — round-trip test
    _vec_to_blob,  # pyright: ignore[reportPrivateUsage] — round-trip test
)


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()


# --- Task 1: migration 3 -------------------------------------------------


def test_migration_3_creates_chunks_and_clusters(tmp_path: Path) -> None:
    db = tmp_path / "case.db"
    store = CaseStore(db)
    store.close()
    assert {"chunks", "clusters"} <= _tables(db)
    conn = sqlite3.connect(db)
    try:
        # CaseStore always migrates to the head schema (v4 since plan 04-01).
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 4
    finally:
        conn.close()


def test_migration_3_llama_free_open_creates_no_vectors_table(
    tmp_path: Path,
) -> None:
    # Opening a case must never require sqlite-vec: migration 3 alone must not
    # create the vectors table (D-03, lazy).
    db = tmp_path / "case.db"
    store = CaseStore(db)
    store.close()
    assert "vectors" not in _tables(db)


def test_migration_3_clusters_enforces_severity_check(tmp_path: Path) -> None:
    db = tmp_path / "case.db"
    store = CaseStore(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):  # noqa: PT012 — txn + insert
            with store.transaction():
                store._conn.execute(  # pyright: ignore[reportPrivateUsage]
                    "INSERT INTO clusters "
                    "(cluster_id, label, signature, severity_max, count, template_ids) "
                    "VALUES (1, NULL, 'sig', 'bogus', 1, '[]')"
                )
    finally:
        store.close()


# --- Task 2: lazy vec0 vectors table + dim guard + serialisation ---------


def test_vec_blob_round_trips_float32(tmp_path: Path) -> None:
    values = [0.5, -0.25, 1.0, -1.5]
    restored = _blob_to_vec(_vec_to_blob(values))
    assert restored == pytest.approx(values, abs=1e-6)


def test_ensure_vectors_table_creates_vec0_and_records_dim(
    tmp_path: Path,
) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        store.ensure_vectors_table(8)
        assert "vectors" in _tables(tmp_path / "case.db")
        assert store.get_meta("embedding_dim") == "8"
        assert store.get_meta("embedding_metric") == "cosine"
        version = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT vec_version()"
        ).fetchone()[0]
        assert isinstance(version, str) and version
    finally:
        store.close()


def test_ensure_vectors_table_is_idempotent(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        store.ensure_vectors_table(8)
        store.ensure_vectors_table(8)  # no error, no re-create
        assert store.get_meta("embedding_dim") == "8"
    finally:
        store.close()


def test_ensure_vectors_table_dim_mismatch_is_hard_error(
    tmp_path: Path,
) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        store.ensure_vectors_table(8)
        with pytest.raises(ValueError, match="8.*16|16.*8") as exc:
            store.ensure_vectors_table(16)
        # STORE-03: the hard error must not silently mutate the recorded dim.
        assert store.get_meta("embedding_dim") == "8"
        assert "8" in str(exc.value) and "16" in str(exc.value)
    finally:
        store.close()


def test_upsert_vectors_round_trips(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        store.ensure_vectors_table(3)
        with store.transaction():
            store.upsert_vectors([(1, [0.1, 0.2, 0.3]), (2, [0.4, 0.5, 0.6])])
        blob = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT embedding FROM vectors WHERE chunk_id = 1"
        ).fetchone()[0]
        assert _blob_to_vec(blob) == pytest.approx([0.1, 0.2, 0.3], abs=1e-6)
    finally:
        store.close()


def test_upsert_vectors_replaces_existing_chunk(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        store.ensure_vectors_table(3)
        with store.transaction():
            store.upsert_vectors([(1, [0.1, 0.2, 0.3])])
        with store.transaction():
            store.upsert_vectors([(1, [0.9, 0.8, 0.7])])
        blob = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT embedding FROM vectors WHERE chunk_id = 1"
        ).fetchone()[0]
        assert _blob_to_vec(blob) == pytest.approx([0.9, 0.8, 0.7], abs=1e-6)
    finally:
        store.close()


def test_record_embedding_identity_guards_dim(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        store.record_embedding_identity("nomic-embed", 8)
        assert store.get_meta("embedding_model") == "nomic-embed"
        assert store.get_meta("embedding_dim") == "8"
        # Recording a different dim later is a hard error, not a silent rewrite.
        with pytest.raises(ValueError, match="8.*16|16.*8"):
            store.record_embedding_identity("other", 16)
        assert store.get_meta("embedding_dim") == "8"
    finally:
        store.close()


# --- Task 3: replace_clusters + query + defensive reads -------------------


def _cluster(cluster_id: int, count: int, label: str | None = None) -> Cluster:
    return Cluster(
        cluster_id=cluster_id,
        label=label,
        signature=f"sig-{cluster_id}",
        severity_max="error",
        count=count,
        template_ids=[f"t{cluster_id}a", f"t{cluster_id}b"],
    )


def test_replace_clusters_round_trips_ordered_by_count_desc(
    tmp_path: Path,
) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with store.transaction():
            store.replace_clusters(
                [_cluster(1, 3), _cluster(2, 10), _cluster(3, 5)]
            )
        got = store.query_clusters()
        assert [c.cluster_id for c in got] == [2, 3, 1]
        assert got[0].template_ids == ["t2a", "t2b"]
    finally:
        store.close()


def test_replace_clusters_deletes_prior_rows(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with store.transaction():
            store.replace_clusters([_cluster(1, 3), _cluster(2, 10)])
        with store.transaction():
            store.replace_clusters([_cluster(9, 1)])
        assert [c.cluster_id for c in store.query_clusters()] == [9]
    finally:
        store.close()


def test_set_cluster_labels_updates_by_id(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with store.transaction():
            store.replace_clusters([_cluster(1, 3), _cluster(2, 10)])
        with store.transaction():
            store.set_cluster_labels({2: "database timeouts"})
        by_id = {c.cluster_id: c for c in store.query_clusters()}
        assert by_id[2].label == "database timeouts"
        assert by_id[1].label is None
    finally:
        store.close()


def test_query_clusters_filter_by_min_count(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with store.transaction():
            store.replace_clusters(
                [_cluster(1, 3), _cluster(2, 10), _cluster(3, 5)]
            )
        got = store.query_clusters({"min-count": 5})
        assert [c.cluster_id for c in got] == [2, 3]
    finally:
        store.close()


def test_query_clusters_unknown_filter_key_raises(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with pytest.raises(ValueError, match="unknown filter key"):
            store.query_clusters({"bogus": "x"})
    finally:
        store.close()


def test_query_clusters_coerces_tampered_template_ids(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with store.transaction():
            store.replace_clusters([_cluster(1, 3)])
        # Simulate a tampered case.db holding a non-array JSON value.
        with store.transaction():
            store._conn.execute(  # pyright: ignore[reportPrivateUsage]
                "UPDATE clusters SET template_ids = '\"oops\"' WHERE cluster_id = 1"
            )
        (got,) = store.query_clusters()
        assert got.template_ids == ["oops"]
    finally:
        store.close()


def test_replace_chunks_round_trips(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        with store.transaction():
            store.replace_chunks([(1, "t1", "boom", ["e1", "e2"])])
        rows = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT chunk_id, template_id, text, event_ids FROM chunks"
        ).fetchall()
        assert rows == [(1, "t1", "boom", '["e1", "e2"]')]
    finally:
        store.close()
