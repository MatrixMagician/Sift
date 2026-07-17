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
