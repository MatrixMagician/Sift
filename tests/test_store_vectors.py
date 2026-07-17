"""CaseStore embedding + cluster persistence tests (STORE-03, EVAL-05).

Covers migration 3 (chunks + clusters tables), the lazily-created sqlite-vec
vec0 vectors table with its dimension guard, the confined float32
(de)serialisation, and the caller-owns-transaction cluster/chunk methods. No
socket is ever opened — everything runs against an on-disk tmp_path case.db.
"""

import sqlite3
from pathlib import Path

import pytest

from sift.store import CaseStore


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
