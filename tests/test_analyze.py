"""`sift analyze` + `sift show clusters` full-flow tests (CLUS-03, EVAL-05).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` injected
through the ``cli._make_http_client`` seam, so the autouse ``_no_network`` conftest
fixture stays active and untouched (EVAL-05). Vectors are planted deterministically
(the ``test_cluster`` plant): two ``alpha`` synonyms on one axis, two ``beta``
synonyms on a second, a lone ``gamma`` noise point orthogonal to both — HDBSCAN
merges the synonyms and leaves the noise a singleton, giving three clusters.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.store import CaseStore, case_db_path

Handler = Callable[[httpx.Request], httpx.Response]
runner = CliRunner()
_BASE = datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC)

# Planted 8-dim vectors (mirrors tests/test_cluster.py): alpha synonyms near
# axis 0, beta synonyms near axis 1, gamma noise orthogonal on axis 7.
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
_CORPUS = [_ALPHA_A, _ALPHA_B, _BETA_A, _BETA_B, _GAMMA]


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


def _seed_case(case: str, messages: list[str]) -> None:
    """Create a case.db seeded with one event per message + template groups."""
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        with store.transaction():
            store.insert_events([_ev(i, m) for i, m in enumerate(messages)])
        dedup.rebuild_template_groups(store)
    finally:
        store.close()


def _handler(
    *,
    calls: list[str] | None = None,
    chat_content: str | None = None,
    embed_raises: bool = False,
) -> Handler:
    """Serve /v1/embeddings (planted vectors) and /v1/chat/completions (labels).

    ``embed_raises`` makes the embeddings endpoint refuse the connection, so the
    analyze embed leg raises mid-run (the interrupted-embed atomicity probe).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            if calls is not None:
                calls.append("embeddings")
            if embed_raises:
                raise httpx.ConnectError("connection refused", request=request)
            inputs = json.loads(request.content)["input"]
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


def _patch_http(
    monkeypatch: pytest.MonkeyPatch, handler: Handler
) -> None:
    """Bind analyze's httpx.Client to a MockTransport via the Task-1 seam."""

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.cli._make_http_client", _factory)


# --- analyze: cluster + label happy path ---------------------------------


def test_analyze_clusters_and_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_case("demo", _CORPUS)
    calls: list[str] = []
    labels = json.dumps({0: "Memory pressure", 1: "SMTP backlog", 2: "Disk anomaly"})
    _patch_http(monkeypatch, _handler(calls=calls, chat_content=labels))
    result = runner.invoke(app, ["analyze", "demo"])
    assert result.exit_code == 0, result.output
    # alpha + beta merge, gamma is a noise singleton -> three clusters.
    assert "Clusters: 3 (3 labelled)" in result.output
    assert "embeddings" in calls  # the embed leg ran
    assert "chat" in calls  # eager labelling ran (D-01)


def test_analyze_no_label_skips_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_case("demo", _CORPUS)
    calls: list[str] = []
    _patch_http(monkeypatch, _handler(calls=calls))
    result = runner.invoke(app, ["analyze", "demo", "--no-label"])
    assert result.exit_code == 0, result.output
    assert "Clusters: 3 (0 labelled)" in result.output
    assert "embeddings" in calls
    assert "chat" not in calls  # --no-label never calls the LLM (D-01)


def test_analyze_empty_case_reports_nothing_to_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A case with no ingested events (no template groups): no embed, clean exit.
    store = CaseStore(case_db_path(load_config().data_dir, "empty"))
    store.close()
    calls: list[str] = []
    _patch_http(monkeypatch, _handler(calls=calls))
    result = runner.invoke(app, ["analyze", "empty"])
    assert result.exit_code == 0, result.output
    assert "Nothing to cluster" in result.output
    assert calls == []  # the client was never contacted


def test_analyze_missing_case_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, _handler())
    result = runner.invoke(app, ["analyze", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_analyze_public_endpoint_refused_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    monkeypatch.setenv("SIFT_EMBEDDINGS_BASE_URL", "http://8.8.8.8/v1")
    # Construction refuses first (LLM-02, T-03-21) — transport never reached.
    _patch_http(monkeypatch, _handler())
    result = runner.invoke(app, ["analyze", "demo"])
    assert result.exit_code == 1
    assert "refusing non-local inference endpoint" in result.output


# --- show clusters: labels, signature fallback, sanitise, atomicity ------


def _clusters_meta(case: str) -> tuple[int, int]:
    """Return (cluster count, labelled count) from the persisted case.db."""
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        rows = store.query_clusters()
        return len(rows), sum(1 for c in rows if c.label)
    finally:
        store.close()


def test_show_clusters_renders_labels_after_analyze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    labels = json.dumps({0: "Memory pressure", 1: "SMTP backlog", 2: "Disk anomaly"})
    _patch_http(monkeypatch, _handler(chat_content=labels))
    assert runner.invoke(app, ["analyze", "demo"]).exit_code == 0
    # D-01: show clusters now surfaces the eager labels, not the signatures.
    result = runner.invoke(app, ["show", "demo", "clusters"])
    assert result.exit_code == 0, result.output
    assert "Memory pressure" in result.output
    assert "SMTP backlog" in result.output
    assert "Disk anomaly" in result.output


def test_show_clusters_falls_back_to_signature_when_no_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    _patch_http(monkeypatch, _handler())
    assert runner.invoke(app, ["analyze", "demo", "--no-label"]).exit_code == 0
    _, labelled = _clusters_meta("demo")
    assert labelled == 0  # no labels persisted
    result = runner.invoke(app, ["show", "demo", "clusters"])
    assert result.exit_code == 0, result.output
    # The signature is the first 16 hex chars of the cluster's template hash —
    # non-empty, deterministic, and shown when no label exists (D-01).
    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        signatures = [c.signature for c in store.query_clusters()]
    finally:
        store.close()
    assert signatures  # sanity: clusters exist
    for sig in signatures:
        assert sig in result.output


def test_show_clusters_strips_control_bytes_from_hostile_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    # A model that returns a label carrying a C1 CSI byte (U+009B) and a bidi
    # override (U+202E) — T-03-20: the whole rendered line is _sanitise'd, so
    # neither control byte reaches the terminal, only the printable text does.
    hostile = "clean\x9b31mRED\u202e"
    labels = json.dumps({0: hostile, 1: "ok", 2: "ok"})
    _patch_http(monkeypatch, _handler(chat_content=labels))
    assert runner.invoke(app, ["analyze", "demo"]).exit_code == 0
    result = runner.invoke(app, ["show", "demo", "clusters"])
    assert result.exit_code == 0, result.output
    assert "\x9b" not in result.output  # C1 CSI stripped
    assert "\u202e" not in result.output  # bidi override stripped
    assert "clean31mRED" in result.output  # the printable text survives


def test_interrupted_embed_leaves_no_clusters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    # No retries/backoff so the ConnectError surfaces immediately (no sleeps).
    monkeypatch.setenv("SIFT_GENERATION_RETRIES", "0")
    monkeypatch.setenv("SIFT_GENERATION_BACKOFF_BASE", "0")
    _patch_http(monkeypatch, _handler(embed_raises=True))
    result = runner.invoke(app, ["analyze", "demo"])
    assert result.exit_code == 1
    # T-03-22: the embed leg raised mid-run → zero clusters persisted (atomic).
    count, _ = _clusters_meta("demo")
    assert count == 0
    # show clusters therefore reverts to the pre-cluster template-groups view.
    show = runner.invoke(app, ["show", "demo", "clusters"])
    assert show.exit_code == 0, show.output
    assert "exemplars:" in show.output
