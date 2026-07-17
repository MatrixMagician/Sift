"""`sift doctor` fail-fast checks against a fake OpenAI-compatible server (LLM-03).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` injected
through the ``cli._make_http_client`` seam, so the autouse ``_no_network`` conftest
fixture stays active and untouched (EVAL-05). The checks are asserted in dependency
order — an unreachable generation endpoint must stop *before* the embeddings probe.
A live-server variant is ``@pytest.mark.live`` and excluded from the default suite
(``addopts = -m 'not perf and not live'``).
"""

import json
import socket

import httpx
import pytest
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.store import CaseStore, case_db_path

# Captured at import time — BEFORE the function-scoped autouse _no_network fixture
# monkeypatches socket.socket.connect — so the opt-in live test can restore real
# loopback networking for itself only.
_REAL_CONNECT = socket.socket.connect

runner = CliRunner()


def _make_transport(
    *,
    embed_dim: int = 4,
    embed_empty: bool = False,
    n_parallel: int = 1,
    connect_error_ports: tuple[int, ...] = (),
    seen: list[str] | None = None,
) -> httpx.MockTransport:
    """Build a MockTransport shaping /v1/models, /v1/embeddings, /props, /tokenize.

    Toggles simulate: a healthy server; an OGA/ONNX server that lists a model but
    returns an empty embeddings ``data`` list (``embed_empty``); a custom embedding
    dimension; an unreachable endpoint (``connect_error_ports`` → ConnectError); a
    multi-slot server (``n_parallel``). ``seen`` records ``"{port}{path}"`` per call
    so a test can prove fail-fast order (embeddings path never reached).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        port = request.url.port
        if seen is not None:
            seen.append(f"{port}{path}")
        if port in connect_error_ports:
            raise httpx.ConnectError("connection refused", request=request)
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        if path.endswith("/embeddings"):
            if embed_empty:
                return httpx.Response(200, json={"data": []})
            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": [0.1] * embed_dim}
                for i in range(len(inputs))
            ]
            return httpx.Response(200, json={"data": data})
        if path.endswith("/props"):
            return httpx.Response(200, json={"n_parallel": n_parallel})
        # /tokenize (and anything else) absent → 404, degraded gracefully.
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _patch_http(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport
) -> None:
    """Bind the doctor's httpx.Client to ``transport`` via the Task-1 seam."""

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=transport, timeout=httpx.Timeout(timeout))

    monkeypatch.setattr("sift.cli._make_http_client", _factory)


def _seed_case(case: str, *, embedding_dim: int) -> None:
    """Create a case.db with a recorded embedding_dim (no ingest needed)."""
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        store.set_meta("embedding_dim", str(embedding_dim))
    finally:
        store.close()


def test_healthy_server_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, _make_transport(embed_dim=4))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "generation endpoint OK" in result.output
    assert "embedding round-trip OK: dimension 4" in result.output
    assert "sqlite-vec OK: vec_version" in result.output
    assert "doctor: all checks passed" in result.output


def test_oga_onnx_empty_embedding_fails_with_named_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Lists a model, but /v1/embeddings returns no vector — the real round-trip
    # is the only thing that catches this (Pitfall 2, T-03-13).
    _patch_http(monkeypatch, _make_transport(embed_empty=True))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert (
        "embeddings unsupported on this model/recipe; load a llamacpp/flm-recipe "
        "embedding model (Lemonade) or start llama-server with --embeddings"
    ) in result.output


def test_dimension_mismatch_names_both_dims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", embedding_dim=8)
    _patch_http(monkeypatch, _make_transport(embed_dim=4))
    result = runner.invoke(app, ["doctor", "demo"])
    assert result.exit_code != 0
    assert "dimension mismatch" in result.output
    assert "8" in result.output  # index dim
    assert "4" in result.output  # server dim


def test_unreachable_generation_stops_before_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Distinct ports so the handler can down the generation endpoint only; the
    # embeddings check (port 9002) must never run — fail-fast order (D-02).
    monkeypatch.setenv("SIFT_GENERATION_BASE_URL", "http://127.0.0.1:9001/v1")
    monkeypatch.setenv("SIFT_EMBEDDINGS_BASE_URL", "http://127.0.0.1:9002/v1")
    monkeypatch.setenv("SIFT_GENERATION_RETRIES", "0")  # no backoff sleeps
    seen: list[str] = []
    _patch_http(
        monkeypatch,
        _make_transport(connect_error_ports=(9001,), seen=seen),
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "generation endpoint" in result.output
    assert "unreachable" in result.output
    # The embeddings endpoint was never contacted (fail-fast).
    assert not any("9002" in entry for entry in seen)
    assert not any("/embeddings" in entry for entry in seen)


def test_public_endpoint_refused_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIFT_EMBEDDINGS_BASE_URL", "http://8.8.8.8/v1")
    # Transport is never reached — construction refuses first (LLM-02, T-03-12).
    _patch_http(monkeypatch, _make_transport())
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code != 0
    assert "refusing non-local inference endpoint" in result.output


def test_public_endpoint_allowed_with_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIFT_GENERATION_BASE_URL", "http://8.8.8.8/v1")
    monkeypatch.setenv("SIFT_EMBEDDINGS_BASE_URL", "http://8.8.8.8/v1")
    _patch_http(monkeypatch, _make_transport(embed_dim=4))
    result = runner.invoke(app, ["doctor", "--i-know-what-im-doing"])
    assert result.exit_code == 0, result.output
    assert "doctor: all checks passed" in result.output


def test_multi_slot_warns_but_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, _make_transport(n_parallel=4))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "n_parallel=4" in result.output  # determinism WARNING (non-fatal)
    assert "doctor: all checks passed" in result.output


@pytest.mark.live
def test_doctor_against_live_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in: run doctor against a real llama-server/Lemonade on :13305.

    Excluded from the default suite (``-m 'not live'``). Restores real loopback
    networking for this test only, then skips unless a server is actually up.
    """
    monkeypatch.setattr(socket.socket, "connect", _REAL_CONNECT)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", 13305))
    except OSError:
        pytest.skip("no live inference server on 127.0.0.1:13305")
    finally:
        probe.close()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
