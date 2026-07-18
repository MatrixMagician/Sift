"""KB retrieval pipeline stage (RAG-07, D-01).

Indexes a directory of Markdown runbooks/RCAs into a physically separate,
structurally non-citable KB namespace (``kb_chunks`` / ``kb_vectors``) and
retrieves the nearest chunks by embedding similarity. Mirrors
``cluster.cluster_and_label``'s contract: typer-free, print-free, embeddings via
the injected ``InferenceClient.embed`` (the sole HTTP boundary), and the CALLER
owns the transaction. The embed precedes every write, so an interrupted embed
rolls the whole index back to zero KB rows.

D-01 is structural, not prompt-worded: KB chunks have no ``event_id`` column and
``retrieve_kb`` returns KB texts only — a KB chunk can never become citable
evidence.
"""

from __future__ import annotations

from pathlib import Path

from sift.llm.client import InferenceClient
from sift.store import CaseStore

# MVP defaults (planner assumptions A2/A6): paragraph/heading-bounded chunks,
# no overlap, fixed char cap → deterministic re-indexing. In-code for now, no
# config surface (kept a clean later swap behind this module).
KB_CHUNK_CHARS = 800
KB_TOP_K = 5


def _chunk_text(text: str, cap: int = KB_CHUNK_CHARS) -> list[str]:
    """Split text into deterministic, non-overlapping, paragraph-bounded chunks.

    Paragraphs (blank-line separated) are greedily packed up to ``cap`` chars; a
    single paragraph longer than ``cap`` is hard-split on the cap boundary. The
    output is a pure function of the input, so re-indexing the same file yields
    identical chunks.
    """
    paragraphs = [p.strip() for p in text.split("\n\n")]
    paragraphs = [p for p in paragraphs if p]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > cap:
            head, para = para[:cap], para[cap:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > cap and current:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def index_kb(store: CaseStore, client: InferenceClient, kb_dir: Path | str) -> int:
    """Index every ``*.md`` under ``kb_dir`` into the KB namespace (RAG-07).

    Walks ``kb_dir`` for Markdown (confined to the given dir via ``rglob``),
    reads UTF-8 (undecodable bytes are replaced, never crashing), chunks each
    file deterministically, embeds via the injected client, and persists chunks
    + vectors inside ONE ``store.transaction()`` — the embed precedes every
    write, so an interrupted embed leaves zero KB rows. Returns the number of
    chunks indexed. No files → 0 with no embed call and no writes.
    """
    root = Path(kb_dir)
    rows: list[tuple[int, str, int, str]] = []
    texts: list[str] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root).as_posix()
        for ordinal, chunk in enumerate(_chunk_text(content)):
            rows.append((len(texts), rel, ordinal, chunk))
            texts.append(chunk)

    if not texts:
        return 0

    vectors = client.embed(texts)
    dim = len(vectors[0])
    vector_rows = list(enumerate(vectors))

    with store.transaction():
        store.ensure_kb_vectors_table(dim)
        store.replace_kb_chunks(rows)
        store.upsert_kb_vectors(vector_rows)
    return len(texts)


def retrieve_kb(
    store: CaseStore,
    client: InferenceClient,
    query_texts: list[str],
    k: int = KB_TOP_K,
) -> list[str]:
    """Return the k nearest KB chunk texts for ``query_texts`` (RAG-07).

    Embeds the query text(s) through the injected client (averaging when several
    are given) and runs the confined vec0 KNN. Returns KB texts only — never
    event ids (D-01). An empty query or an empty KB index returns ``[]``.
    """
    queries = [q for q in query_texts if q.strip()]
    if not queries:
        return []
    vectors = client.embed(queries)
    if not vectors:
        return []
    dim = len(vectors[0])
    qvec = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return store.knn_kb_chunks(qvec, k)
