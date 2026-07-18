"""KB index + retrieval data-path tests (RAG-07, D-01).

Covers the physically separate KB namespace (migration 5: ``kb_chunks`` /
``kb_vectors``), the confined KB store methods, and the ``pipeline.retrieve``
index+KNN seam. The load-bearing invariant under test is D-01: KB chunks live
in a namespace with NO ``event_id`` column, so they can never enter the citable
set — a structural guarantee, not a prompt wording.

Zero sockets: every embedding is served by an ``httpx.MockTransport`` injected
into a real ``InferenceClient``, so the autouse ``_no_network`` conftest fixture
stays active and untouched (EVAL-05). The fake embedder keys off a substring so
the test never couples to the exact chunk boundaries: any chunk containing the
planted phrase lands on axis 0, unrelated text on axis 7, and the query embeds
to axis 0 — so KNN(k=1) must return the planted chunk.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from sift.llm.client import Endpoint, InferenceClient
from sift.pipeline import retrieve
from sift.store import CaseStore

Handler = Callable[[httpx.Request], httpx.Response]

_PLANTED = "planted"
_UNRELATED = "unrelated"
# 8-dim planted vectors: planted text near axis 0, unrelated near axis 7.
_AXIS0 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_AXIS7 = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _embed_for(text: str) -> list[float]:
    lowered = text.lower()
    if _PLANTED in lowered:
        return _AXIS0
    if _UNRELATED in lowered:
        return _AXIS7
    return [0.0] * 8


def _handler(*, embed_raises: bool = False) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            if embed_raises:
                raise httpx.ConnectError("connection refused", request=request)
            import json

            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": _embed_for(text)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        return httpx.Response(404)

    return handler


def _client(handler: Handler) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "runbook.md").write_text(
        "# Memory pressure runbook\n\n"
        "When the planted watermark alarm fires, restart the cache tier.\n",
        encoding="utf-8",
    )
    (kb / "network.md").write_text(
        "# Network runbook\n\n"
        "An unrelated smtp queue backlog needs a delivery retry sweep.\n",
        encoding="utf-8",
    )
    return kb


def _kb_chunk_count(store: CaseStore) -> int:
    row = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
        "SELECT count(*) FROM kb_chunks"
    ).fetchone()
    return int(row[0])


# --- RAG-07: index then retrieve the planted chunk ------------------------


def test_index_kb_then_retrieve_returns_planted_chunk(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    client = _client(_handler())
    try:
        retrieve.index_kb(store, client, _kb_dir(tmp_path))
        assert _kb_chunk_count(store) >= 2
        hits = retrieve.retrieve_kb(store, client, ["planted watermark alarm"], k=1)
        assert len(hits) == 1
        assert _PLANTED in hits[0].lower()
    finally:
        store.close()


# --- D-01: KB namespace is structurally non-citable -----------------------


def test_kb_chunks_table_has_no_event_id_column(tmp_path: Path) -> None:
    db = tmp_path / "case.db"
    store = CaseStore(db)
    store.close()
    conn = sqlite3.connect(db)
    try:
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(kb_chunks)")
        }
        assert cols, "kb_chunks table must exist (migration 5)"
        assert "event_id" not in cols, "D-01: KB chunks must never carry an event_id"
    finally:
        conn.close()


# --- Atomicity: an interrupted embed leaves zero KB rows ------------------


def test_index_kb_interrupted_embed_rolls_back(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    client = _client(_handler(embed_raises=True))
    try:
        with pytest.raises(httpx.ConnectError):
            retrieve.index_kb(store, client, _kb_dir(tmp_path))
        assert _kb_chunk_count(store) == 0
    finally:
        store.close()


# --- IN-03: symlinked KB files are skipped (trust-boundary parity) --------


def test_index_kb_skips_symlinks(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "real.md").write_text("planted real runbook", encoding="utf-8")
    # A file OUTSIDE the kb dir, reached only via a symlink inside it.
    secret = tmp_path / "secret.md"
    secret.write_text("planted secret leak", encoding="utf-8")
    (kb / "link.md").symlink_to(secret)

    store = CaseStore(tmp_path / "case.db")
    client = _client(_handler())
    try:
        retrieve.index_kb(store, client, kb)
        rows = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT DISTINCT source_file FROM kb_chunks"
        ).fetchall()
        sources = {r[0] for r in rows}
        assert "real.md" in sources
        assert "link.md" not in sources  # the symlinked target was never indexed
    finally:
        store.close()


# --- Determinism: re-indexing yields identical chunk text/ordinals --------


def test_index_kb_is_deterministic(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    client = _client(_handler())
    kb = _kb_dir(tmp_path)
    try:
        retrieve.index_kb(store, client, kb)
        first = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT source_file, ordinal, text FROM kb_chunks "
            "ORDER BY source_file, ordinal"
        ).fetchall()
        retrieve.index_kb(store, client, kb)
        second = store._conn.execute(  # pyright: ignore[reportPrivateUsage]
            "SELECT source_file, ordinal, text FROM kb_chunks "
            "ORDER BY source_file, ordinal"
        ).fetchall()
        assert first == second
    finally:
        store.close()
