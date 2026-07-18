"""`sift analyze --kb` KB-context threading tests (RAG-07, D-01, D-02, CLI-02).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` — the
autouse ``_no_network`` conftest fixture stays active (EVAL-05). The load-bearing
invariant under test is D-01: KB chunks enrich the triage PROMPT only, never the
``prompted_ids`` universe, so a model that "cites" a KB chunk (an id never shown
as an ``[evt:]`` exemplar) is mechanically FLAGGED by the existing citation gate.

Three assertions anchor the slice:
  * the assembled prompt CHANGES with ``kb_context`` (the KB block appears) and is
    BYTE-IDENTICAL without it (the golden no-KB hash below, captured pre-change);
  * ``prompted_ids`` is identical with and without KB — KB never enters it;
  * an end-to-end ``analyze --kb`` run whose model cites a KB-derived id degrades
    (exit 3, ``citations_valid=0`` persisted), never a clean success.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sift.cli import app
from sift.config import ClusteringConfig, load_config
from sift.llm.budget import PromptBudget
from sift.llm.client import Endpoint, InferenceClient
from sift.models import Event, event_id
from sift.pipeline import cluster, dedup, hypothesise
from sift.pipeline.salience import rank_clusters
from sift.store import CaseStore, case_db_path

Handler = Callable[[httpx.Request], httpx.Response]
runner = CliRunner()
_BASE = datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC)

# Three orthogonal planted 8-dim vectors -> three noise singletons (mirrors
# tests/test_hypothesise.py so the seeded case is byte-for-byte the same one the
# golden no-KB prompt hash below was captured against).
_ALPHA = "alpha memory watermark exceeded"
_BETA = "beta smtp queue backing up"
_GAMMA = "gamma unrelated disk anomaly"
_CORPUS = [_ALPHA, _BETA, _GAMMA]
_VECTORS: dict[str, list[float]] = {
    _ALPHA: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _BETA: [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _GAMMA: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
}

# The exemplar id actually shown to the model (a valid, citable event).
_ID_ALPHA = event_id("case.log", 0)
# A KB-derived (non-exemplar) 16-hex id: shaped like a citation token but never
# in prompted_ids, so citing it must be FLAGGED (D-01).
_KB_CITE_ID = "cafefeedcafefeed"

# The pre-change no-KB assembled-prompt hash for the seeded 3-cluster corpus,
# captured BEFORE this plan touched triage.md / _assemble. The no-KB path must
# reproduce it byte-for-byte (prompt_hash == sha256(prompt)[:16]) — the
# determinism + Phase-4 regression guard for D-02's "byte-identical without KB".
_NO_KB_PROMPT_HASH = "ef5b76801235d179"

# A distinctive planted runbook chunk; its text must surface in the KB block of
# the assembled prompt when --kb is active, and never otherwise.
_KB_RUNBOOK = (
    "RUNBOOK cache-tier: when the memory watermark is exceeded, restart the "
    "cache tier and raise the working-set ceiling before the server stalls."
)

# A minimal schema-valid empty HypothesisSet (empty citations pass the gate -> 0).
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)


def _hset_body(cited_ids: list[str]) -> str:
    """A schema-valid HypothesisSet JSON string citing ``cited_ids``."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Memory watermark cascade",
                    "narrative": "The watermark was exceeded before the stall.",
                    "confidence": "high",
                    "confidence_reasoning": "Corroborating events.",
                    "supporting_event_ids": cited_ids,
                    "contradicting_evidence": None,
                    "suggested_next_steps": ["Raise the memory ceiling"],
                }
            ],
            "timeline_summary": "Memory pressure built, then the server stalled.",
            "unexplained_signals": [],
        }
    )


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


def _handler(
    *,
    hyp_content: str | None = None,
    prompts: list[str] | None = None,
    calls: list[str] | None = None,
) -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions; capture generation prompts.

    The triage (generation) call carries ``response_format``; its first user
    message content is appended to ``prompts`` so a test can assert the KB block
    is (or is not) present. ``hyp_content`` overrides the generation reply.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            if calls is not None:
                calls.append("embeddings")
            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": _VECTORS.get(text, [0.0] * 8)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            if "response_format" in payload:
                if prompts is not None:
                    prompts.append(payload["messages"][0]["content"])
                if calls is not None:
                    calls.append("generate")
                content = hyp_content if hyp_content is not None else _VALID_HYPSET
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": content}}]}
                )
            if calls is not None:
                calls.append("chat")
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "{}"}}]}
            )
        return httpx.Response(404)

    return handler


def _client(handler: Handler) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _seed_clustered(store: CaseStore) -> None:
    """Seed three orthogonal events -> three singleton clusters (label-free)."""
    events = [_ev(i, m) for i, m in enumerate(_CORPUS)]
    with store.transaction():
        store.insert_events(events)
    dedup.rebuild_template_groups(store)
    cluster.cluster_and_label(
        store, _client(_handler()), ClusteringConfig(), label=False
    )


def _assemble(
    store: CaseStore, client: InferenceClient, kb_context: list[str] | None
) -> tuple[set[str], str]:
    """Prepare _assemble's inputs from a seeded store and return (ids, prompt).

    Mirrors hypothesise's own assembly prep exactly (rank -> exemplar messages ->
    template -> PromptBudget) so the returned prompt is the one hypothesise would
    build; the only variable is ``kb_context``.
    """
    clusters = store.query_clusters()
    groups = store.query_template_groups()
    ranked = rank_clusters(clusters, groups, incident_time=None)
    group_index = {g.template_id: g for g in groups}
    messages = hypothesise._gather_exemplar_messages(store, groups)  # pyright: ignore[reportPrivateUsage]
    template = hypothesise._load_triage_template()  # pyright: ignore[reportPrivateUsage]
    budget = PromptBudget(client, 8192, 1024)  # pyright: ignore[reportArgumentType]
    _msgs, prompted_ids, prompt = hypothesise._assemble(  # pyright: ignore[reportPrivateUsage]
        ranked, group_index, messages, template, None, budget, kb_context=kb_context
    )
    return prompted_ids, prompt


# --- _assemble: KB changes the prompt, no-KB byte-identical, ids unchanged ----


def test_assemble_kb_block_present_and_stripped(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_clustered(store)
        client = _client(_handler())
        _ids_kb, prompt_kb = _assemble(store, client, [_KB_RUNBOOK])
        _ids_no, prompt_no = _assemble(store, client, None)
        # D-02: the KB text appears with --kb, and is fully absent without it.
        assert _KB_RUNBOOK in prompt_kb
        assert _KB_RUNBOOK not in prompt_no
        assert prompt_kb != prompt_no
        # The KB block is delimited from the citable evidence: it appears before
        # the trailing `Evidence:` SECTION marker (rindex — the word also occurs
        # earlier in the instruction prose).
        assert prompt_kb.index(_KB_RUNBOOK) < prompt_kb.rindex("Evidence:")
        # No sentinel markers leak into either rendered prompt.
        assert "KB_CONTEXT" not in prompt_kb
        assert "KB_BLOCK" not in prompt_kb
        assert "KB_BLOCK" not in prompt_no
    finally:
        store.close()


def test_assemble_no_kb_is_byte_identical_baseline(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_clustered(store)
        _ids, prompt_no = _assemble(store, _client(_handler()), None)
        # Byte-identity: sha256(prompt)[:16] must equal the pre-change golden.
        assert hypothesise._prompt_hash(prompt_no) == _NO_KB_PROMPT_HASH  # pyright: ignore[reportPrivateUsage]
    finally:
        store.close()


def test_assemble_prompted_ids_unchanged_by_kb(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "case.db")
    try:
        _seed_clustered(store)
        client = _client(_handler())
        ids_kb, _p1 = _assemble(store, client, [_KB_RUNBOOK])
        ids_no, _p2 = _assemble(store, client, None)
        # D-01: KB never enters the citable universe.
        assert ids_kb == ids_no
        assert _ID_ALPHA in ids_no
        assert _KB_RUNBOOK not in ids_kb  # the chunk text is not an id
    finally:
        store.close()


# --- analyze --kb: KB citation is FLAGGED (D-01, end-to-end) -----------------


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.cli._make_http_client", _factory)


def _seed_case(case: str) -> None:
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        with store.transaction():
            store.insert_events([_ev(i, m) for i, m in enumerate(_CORPUS)])
        dedup.rebuild_template_groups(store)
    finally:
        store.close()


def _kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "runbook.md").write_text(_KB_RUNBOOK, encoding="utf-8")
    return kb


def test_analyze_kb_citation_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_case("demo")
    kb = _kb_dir(tmp_path)
    # The model "cites" a KB-derived id never shown as an exemplar -> FLAGGED.
    handler = _handler(hyp_content=_hset_body([_KB_CITE_ID]))
    _patch_http(monkeypatch, handler)
    result = runner.invoke(
        app, ["analyze", "demo", "--kb", str(kb), "--no-label"]
    )
    # A KB citation degrades the run (exit 3), never a clean success (D-01).
    assert result.exit_code == 3, result.output
    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        rows = store.query_hypotheses()
        assert rows
        offender = rows[0]
        assert offender.citations_valid is False
        assert _KB_CITE_ID in offender.supporting_event_ids
        assert store.get_meta("triage_degraded") == "1"
    finally:
        store.close()


def test_analyze_kb_context_present_yet_noncitable_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full RAG-07 slice: retrieved KB context reaches the triage prompt, yet
    a hypothesis citing a KB chunk is FLAGGED — ``cited ⊆ prompted ⊆ store`` holds
    transitively with KB active (D-01), the KB block never citable (D-02).
    """
    _seed_case("demo")
    kb = _kb_dir(tmp_path)
    prompts: list[str] = []
    handler = _handler(hyp_content=_hset_body([_KB_CITE_ID]), prompts=prompts)
    _patch_http(monkeypatch, handler)
    result = runner.invoke(
        app, ["analyze", "demo", "--kb", str(kb), "--no-label"]
    )
    assert result.exit_code == 3, result.output
    # KB context DID reach the real triage prompt (retrieved + threaded, D-02)…
    assert prompts
    assert any(_KB_RUNBOOK in prompt for prompt in prompts)
    # …yet the KB citation is FLAGGED, never presented as clean (D-01).
    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        rows = store.query_hypotheses()
        assert rows and rows[0].citations_valid is False
        assert _KB_CITE_ID in rows[0].supporting_event_ids
    finally:
        store.close()


def test_analyze_kb_empty_dir_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01: a --kb dir with no indexable *.md must not crash. index_kb
    short-circuits before creating the kb_vectors table, so retrieve_kb must
    treat the un-indexed KB as empty rather than raising a raw
    sqlite3.OperationalError (never-crash invariant)."""
    _seed_case("demo")
    empty_kb = tmp_path / "kb_empty"
    empty_kb.mkdir()
    (empty_kb / "notes.txt").write_text("not markdown", encoding="utf-8")
    _patch_http(monkeypatch, _handler(hyp_content=_VALID_HYPSET))
    result = runner.invoke(
        app, ["analyze", "demo", "--kb", str(empty_kb), "--no-label"]
    )
    # Clean completion (exit 0 for an empty valid hypset), never a traceback.
    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_analyze_kb_valid_citation_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With --kb active, citing a real exemplar id is still a clean success — KB
    enrichment does not disturb the golden path (D-02 additive)."""
    _seed_case("demo")
    kb = _kb_dir(tmp_path)
    prompts: list[str] = []
    handler = _handler(hyp_content=_hset_body([_ID_ALPHA]), prompts=prompts)
    _patch_http(monkeypatch, handler)
    result = runner.invoke(
        app, ["analyze", "demo", "--kb", str(kb), "--no-label"]
    )
    assert result.exit_code == 0, result.output
    assert any(_KB_RUNBOOK in prompt for prompt in prompts)  # KB still threaded
    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        rows = store.query_hypotheses()
        assert rows and all(r.citations_valid for r in rows)
    finally:
        store.close()
