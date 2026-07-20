"""InferenceClient tests: SSRF guard, per-role endpoints, embed/chat, backoff.

Every inference call is faked with ``httpx.MockTransport`` — no socket opens
(EVAL-05). The autouse ``_no_network`` fixture stays intact; MockTransport
never reaches ``socket.connect`` so no relaxation is needed.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from sift.llm.client import (
    Endpoint,
    InferenceClient,
    _assert_local,  # pyright: ignore[reportPrivateUsage] — SSRF guard under test
)

Handler = Callable[[httpx.Request], httpx.Response]


def _local() -> Endpoint:
    return Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)


def _client(handler: Handler, **kw: object) -> InferenceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = _local()
    return InferenceClient(ep, ep, http, backoff_base=0.0, **kw)  # type: ignore[arg-type]


# --- SSRF guard (LLM-02) ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/v1",
        "http://localhost:13305/v1",
        "http://svc.localhost/v1",
        "http://10.0.0.5/v1",
        "http://172.16.0.1/v1",
        "http://192.168.1.1/v1",
        "http://169.254.1.1/v1",
        "http://[::1]:8080/v1",
    ],
)
def test_assert_local_accepts_loopback_and_rfc1918(url: str) -> None:
    _assert_local(url, allow_public=False)  # must not raise


@pytest.mark.parametrize("url", ["http://8.8.8.8/v1", "http://172.32.0.1/v1"])
def test_assert_local_refuses_public(url: str) -> None:
    with pytest.raises(ValueError, match="i-know-what-im-doing"):
        _assert_local(url, allow_public=False)
    _assert_local(url, allow_public=True)  # explicit override accepted


def test_construction_guards_both_base_urls() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    public = Endpoint(base_url="http://8.8.8.8/v1", model=None)
    with pytest.raises(ValueError, match="i-know-what-im-doing"):
        InferenceClient(_local(), public, http)


# --- embed (LLM-01) -----------------------------------------------------------


def test_embed_empty_makes_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    assert _client(handler).embed([]) == []
    assert calls == []


def test_embed_preserves_index_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        data = [
            {"index": i, "embedding": [float(i), float(i) + 0.5]}
            for i in range(len(inputs))
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})

    assert _client(handler).embed(["a", "b"]) == [[0.0, 0.5], [1.0, 1.5]]


def test_embed_batches_whole_list() -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        seen.append(len(inputs))
        data = [{"index": i, "embedding": [1.0]} for i in range(len(inputs))]
        return httpx.Response(200, json={"data": data})

    vecs = _client(handler, batch_size=2).embed(["a", "b", "c"])
    assert len(vecs) == 3
    assert seen == [2, 1]  # two batches: sizes 2 then 1


def test_embed_truncates_inputs_to_max_input_chars() -> None:
    # An exemplar longer than the embedding model's context window makes the
    # backend reject the whole request (llama.cpp exceed_context_size_error).
    # embed() must cap each input to max_input_chars before sending, so a large
    # multi-line record (MCM dump, stack trace) never aborts the run.
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        seen.extend(len(t) for t in inputs)
        data = [{"index": i, "embedding": [1.0]} for i in range(len(inputs))]
        return httpx.Response(200, json={"data": data})

    _client(handler, max_input_chars=10).embed(["x" * 50, "short"])
    assert seen == [10, 5]  # long input truncated to 10 chars; short untouched


def test_embed_server_error_object_raises_actionable_message() -> None:
    # A 200 body carrying {"error": ...} (no "data" list) is how llama.cpp /
    # Lemonade reject an over-context request. embed() must surface an
    # actionable message (name the cause + the knob), not the cryptic
    # "data is not a list".
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": {
                    "message": "request (10237 tokens) exceeds the available "
                    "context size (8192 tokens)"
                }
            },
        )

    with pytest.raises(ValueError, match="max_input_chars|context"):
        _client(handler).embed(["anything"])


# --- manual backoff (A1) ------------------------------------------------------


def test_5xx_retries_then_succeeds() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] <= 2:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    assert _client(handler, retries=2).embed(["x"]) == [[1.0]]
    assert state["n"] == 3  # exactly two retries then success


def test_4xx_does_not_retry() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(400, json={})

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler, retries=2).embed(["x"])
    assert state["n"] == 1


# --- untrusted response defence (T-03-06) -------------------------------------


def test_inconsistent_dimension_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 2.0]},
                    {"index": 1, "embedding": [1.0]},
                ]
            },
        )

    with pytest.raises(ValueError, match="dimension"):
        _client(handler).embed(["a", "b"])


def test_non_numeric_embedding_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": ["x"]}]})

    with pytest.raises(ValueError):
        _client(handler).embed(["a"])


def test_invalid_json_raises_value_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(ValueError):
        _client(handler).embed(["a"])


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_embedding_raises(token: str) -> None:
    # WR-01: json.loads parses the bare tokens NaN/Infinity/-Infinity into
    # float nan/inf by default, so a hostile server can smuggle non-finite
    # components past the "finite" contract. embed() must reject them.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=f'{{"data": [{{"index": 0, "embedding": [1.0, {token}]}}]}}'
        )

    with pytest.raises(ValueError, match="non-finite"):
        _client(handler).embed(["a"])


def test_embedding_model_prefers_server_reported() -> None:
    # WR-03 / STORE-03: the embeddings server's reported model is the provenance
    # identity, authoritative even when no model is configured (D-03).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "nomic-embed-text",
                "data": [{"index": 0, "embedding": [1.0]}],
            },
        )

    client = _client(handler)
    assert client.embedding_model is None  # nothing known before the first embed
    client.embed(["a"])
    assert client.embedding_model == "nomic-embed-text"


def test_embedding_model_falls_back_to_configured() -> None:
    # No server-reported model → the configured endpoint model is the identity.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model="configured-embed")
    client = InferenceClient(ep, ep, http, backoff_base=0.0)
    client.embed(["a"])
    assert client.embedding_model == "configured-embed"


# --- chat (LLM-01) ------------------------------------------------------------


def test_chat_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"content": "hello"}}]}
        return httpx.Response(200, json=body)

    assert _client(handler).chat([{"role": "user", "content": "hi"}]) == "hello"


def test_chat_missing_content_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ValueError):
        _client(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_omits_response_format_when_not_passed() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _client(handler).chat([{"role": "user", "content": "hi"}])
    assert "response_format" not in seen[0]


def test_chat_sends_llama_cpp_response_format_shape() -> None:
    seen: list[dict[str, object]] = []
    rf: dict[str, object] = {
        "type": "json_schema",
        "schema": {"type": "object", "properties": {}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _client(handler).chat([{"role": "user", "content": "hi"}], response_format=rf)
    body = seen[0]
    # llama.cpp nesting: schema is top-level under response_format, verbatim.
    assert body["response_format"] == rf
    # Never send a second constraint field alongside the schema.
    assert "grammar" not in body


# --- feature detection: /tokenize, /props (LLM-04, Lemonade-safe) -------------


def test_has_tokenize_false_when_route_404s() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    c = _client(handler)
    assert c.has_tokenize is False
    assert c.tokenize("abc") is None  # graceful, no raise (Lemonade path)


def test_tokenize_returns_count_when_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tokens": [1, 2, 3]})

    c = _client(handler)
    assert c.has_tokenize is True
    assert c.tokenize("abc") == 3


def test_tokenize_swallows_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("server down")

    c = _client(handler)
    assert c.tokenize("x") is None
    assert c.has_tokenize is False


def test_props_absent_returns_empty_and_no_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    c = _client(handler)
    assert c.props() == {}
    assert c.has_props is False


def test_props_exposes_keys_absent_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"n_ctx": 4096})

    c = _client(handler)
    props = c.props()
    assert props.get("n_ctx") == 4096
    assert props.get("n_parallel") is None  # absent-key-safe
    assert c.has_props is True


def test_chat_surfaces_server_error_body() -> None:
    """A 200 body carrying an ``error`` and no ``choices`` surfaces the real cause.

    llama.cpp/Lemonade answer an over-context chat with HTTP 200 + a nested
    ``{"error": ...}`` object (no ``choices``). The raised ValueError must carry
    the server's specific message, not the cryptic 'no choices' — otherwise the
    CLI mislabels a context overflow as a 'transport error'.
    """
    overflow = {
        "error": {
            "details": {
                "response": {
                    "error": {
                        "message": (
                            "request (4867 tokens) exceeds the available "
                            "context size (4096 tokens), try increasing it"
                        ),
                        "type": "exceed_context_size_error",
                    }
                }
            },
            "message": "llama-server request failed",
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=overflow)

    with pytest.raises(ValueError, match="exceeds the available context size"):
        _client(handler).chat([{"role": "user", "content": "hi"}])
