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
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 3
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
