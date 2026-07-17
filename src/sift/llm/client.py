"""The single HTTP boundary: an injectable OpenAI-compatible inference client.

`InferenceClient` is the only place in Sift that opens HTTP (SPEC.md §5.6). It
speaks the OpenAI-compatible surface of a *local* llama.cpp `llama-server` or
Lemonade Server — `/v1/embeddings` and `/v1/chat/completions` — over an injected
`httpx.Client` (EVAL-05: tests bind a `MockTransport`, no socket opens).

Three boundary controls are load-bearing:

* **SSRF guard (LLM-02):** `_assert_local` refuses any non-loopback / non-RFC1918
  `base_url` at construction unless `allow_public` (the `--i-know-what-im-doing`
  break-glass). It never performs a DNS lookup — only literal IPs and the
  `localhost` name are accepted, so there is no TOCTOU egress.
* **Manual backoff (A1):** httpx transport `retries=` retries connection setup
  only, never read timeouts or 5xx, so `_request` loops manually over
  `ConnectError` / `TimeoutException` / `status >= 500` with exponential backoff.
* **Untrusted responses (T-03-05/06):** every server body is parsed defensively;
  embedding vectors are validated as non-empty consistent-length float lists and
  chat content is length-capped.

No third-party vendor inference SDK is imported here — only httpx.
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

import httpx

# Cap server-supplied chat text before it flows to callers/render (DoS defence).
_MAX_CONTENT_CHARS = 100_000


@dataclass(frozen=True)
class Endpoint:
    """A per-role inference endpoint.

    Attributes:
        base_url: OpenAI-compatible base, e.g. ``http://localhost:13305/v1``.
        model: Model identity, config-only with no baked default (D-03); ``None``
            lets the server pick its loaded model.
    """

    base_url: str
    model: str | None


def _assert_local(base_url: str, allow_public: bool) -> None:
    """Refuse a non-local inference endpoint (LLM-02 SSRF guard).

    Accepts the ``localhost`` name (and ``*.localhost``) plus any literal
    loopback / RFC1918 / link-local IP. Never performs DNS resolution — that is
    itself egress and TOCTOU-racey. A public literal is refused unless
    ``allow_public`` (the ``--i-know-what-im-doing`` override).

    Args:
        base_url: The endpoint to validate.
        allow_public: When ``True``, skip the refusal (explicit break-glass).

    Raises:
        ValueError: If the host is a non-local literal and ``allow_public`` is
            ``False``.
    """
    host = urlsplit(base_url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = (
            ipaddress.ip_address(host)
        )
    except ValueError:
        ip = None
    ok = ip is not None and (ip.is_loopback or ip.is_private)
    if not ok and not allow_public:
        raise ValueError(
            f"refusing non-local inference endpoint {base_url!r}; "
            "pass --i-know-what-im-doing to override"
        )


def _server_root(base_url: str) -> str:
    """Return ``scheme://netloc`` for llama.cpp's native (non-``/v1``) endpoints.

    ``/props`` and ``/tokenize`` live at the server root, not under ``/v1``.
    """
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


def _json_object(response: httpx.Response) -> dict[str, object]:
    """Parse a response body as a JSON object, defensively (untrusted input)."""
    try:
        raw: object = response.json()
    except ValueError as exc:  # includes json.JSONDecodeError
        raise ValueError("inference server returned invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("inference server returned a non-object JSON body")
    return cast(dict[str, object], raw)


def _coerce_vector(embedding: object) -> list[float]:
    """Validate one embedding is a non-empty list of finite numbers (T-03-06)."""
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("embedding must be a non-empty list of floats")
    vector: list[float] = []
    for value in cast(list[object], embedding):
        # bool is an int subclass — reject it explicitly, it is never a vector.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding contains a non-numeric value")
        vector.append(float(value))
    return vector


def _order_by_index(rows: object, count: int) -> list[object]:
    """Reorder an embeddings ``data`` array by each row's ``index`` field."""
    if not isinstance(rows, list):
        raise ValueError("embeddings response 'data' is not a list")
    rows_list = cast(list[object], rows)
    if len(rows_list) != count:
        raise ValueError("embeddings response has an unexpected row count")
    slots: list[object | None] = [None] * count
    for row in rows_list:
        if not isinstance(row, dict):
            raise ValueError("embeddings response row is not an object")
        row_obj = cast(dict[str, object], row)
        index = row_obj.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not (
            0 <= index < count
        ):
            raise ValueError("embeddings response has an out-of-range index")
        if slots[index] is not None:
            raise ValueError("embeddings response has a duplicate index")
        slots[index] = row_obj.get("embedding")
    if any(slot is None for slot in slots):
        raise ValueError("embeddings response is missing an index")
    return cast(list[object], slots)


class InferenceClient:
    """The only HTTP client in Sift; hits both inference roles.

    Args:
        generation: Endpoint for ``/chat/completions``.
        embeddings: Endpoint for ``/embeddings``.
        http: Injected transport (EVAL-05); production wires timeouts here.
        allow_public: Break-glass to skip the SSRF guard (``--i-know-what-im-doing``).
        retries: Extra attempts after the first on connect/timeout/5xx.
        backoff_base: Seconds for exponential backoff (`base * 2**attempt`).
        batch_size: Max inputs per ``/embeddings`` request.
    """

    def __init__(
        self,
        generation: Endpoint,
        embeddings: Endpoint,
        http: httpx.Client,
        *,
        allow_public: bool = False,
        retries: int = 2,
        backoff_base: float = 0.5,
        batch_size: int = 64,
    ) -> None:
        _assert_local(generation.base_url, allow_public)
        _assert_local(embeddings.base_url, allow_public)
        self._generation = generation
        self._embeddings = embeddings
        self._http = http
        self._retries = retries
        self._backoff_base = backoff_base
        self._batch_size = max(1, batch_size)
        self._has_tokenize: bool | None = None  # None = not yet probed
        self._has_props: bool | None = None

    def _request(
        self, method: str, url: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        """Issue a request with manual backoff over connect/timeout/5xx (A1)."""
        for attempt in range(self._retries + 1):
            try:
                response = self._http.request(method, url, json=json)
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt == self._retries:
                    raise
            else:
                if response.status_code < 500 or attempt == self._retries:
                    return response
            time.sleep(self._backoff_base * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        """Embed inputs, preserving order and validating dimensions (LLM-01).

        Sends the whole list in ``batch_size`` chunks, reorders each batch by the
        server's ``data[].index``, and asserts every vector shares one non-zero
        dimension. ``embed([])`` short-circuits to ``[]`` with no HTTP call.

        Raises:
            ValueError: On a malformed or dimension-inconsistent response.
            httpx.HTTPStatusError: On a non-retriable error status.
        """
        if not inputs:
            return []
        url = f"{self._embeddings.base_url.rstrip('/')}/embeddings"
        vectors: list[list[float]] = []
        dim: int | None = None
        for start in range(0, len(inputs), self._batch_size):
            batch = list(inputs[start : start + self._batch_size])
            payload: dict[str, object] = {"input": batch}
            if self._embeddings.model is not None:
                payload["model"] = self._embeddings.model
            response = self._request("POST", url, json=payload)
            response.raise_for_status()
            data = _json_object(response)
            for embedding in _order_by_index(data.get("data"), len(batch)):
                vector = _coerce_vector(embedding)
                if dim is None:
                    dim = len(vector)
                elif len(vector) != dim:
                    raise ValueError(
                        f"inconsistent embedding dimension: expected {dim}, "
                        f"got {len(vector)}"
                    )
                vectors.append(vector)
        return vectors

    def chat(self, messages: Sequence[dict[str, str]]) -> str:
        """Return ``choices[0].message.content`` from a chat completion (LLM-01).

        Parses defensively and caps the returned text length (DoS defence).

        Raises:
            ValueError: On a malformed response.
            httpx.HTTPStatusError: On a non-retriable error status.
        """
        url = f"{self._generation.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, object] = {"messages": list(messages)}
        if self._generation.model is not None:
            payload["model"] = self._generation.model
        response = self._request("POST", url, json=payload)
        response.raise_for_status()
        data = _json_object(response)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat response has no choices")
        first = cast(list[object], choices)[0]
        if not isinstance(first, dict):
            raise ValueError("chat response choice is not an object")
        message = cast(dict[str, object], first).get("message")
        if not isinstance(message, dict):
            raise ValueError("chat response choice has no message")
        content = cast(dict[str, object], message).get("content")
        if not isinstance(content, str):
            raise ValueError("chat response message content is not a string")
        return content[:_MAX_CONTENT_CHARS]

    def models(self, endpoint: Endpoint) -> list[str]:
        """List the model ids advertised at ``endpoint``'s ``/v1/models`` (LLM-03).

        ``sift doctor`` uses this to prove an endpoint is reachable and to report
        the loaded model identities. Capability is NEVER inferred from this list —
        an embedding round-trip is the only real probe (Pitfall 2). The returned
        ids are untrusted server strings; the caller sanitises before printing.

        Raises:
            httpx.HTTPStatusError: On a non-2xx status (endpoint unreachable/broken).
            httpx.ConnectError / httpx.TimeoutException: On transport failure.
            ValueError: On a malformed response body.
        """
        url = f"{endpoint.base_url.rstrip('/')}/models"
        response = self._request("GET", url)
        response.raise_for_status()
        data = _json_object(response)
        rows = data.get("data")
        ids: list[str] = []
        if isinstance(rows, list):
            for row in cast(list[object], rows):
                if isinstance(row, dict):
                    model_id = cast(dict[str, object], row).get("id")
                    if isinstance(model_id, str):
                        ids.append(model_id)
        return ids

    @property
    def has_tokenize(self) -> bool:
        """Whether the generation server exposes ``/tokenize`` (probed once)."""
        if self._has_tokenize is None:
            self._has_tokenize = self.tokenize("") is not None
        return self._has_tokenize

    def tokenize(self, text: str) -> int | None:
        """Return the server's token count for ``text``, or ``None`` if absent.

        Feature-detection must never raise for an absent endpoint (LLM-04) — a
        404 or transport error degrades to ``None`` so Lemonade (which lacks
        ``/tokenize``) works unmodified.
        """
        url = f"{_server_root(self._generation.base_url)}/tokenize"
        try:
            response = self._http.request("POST", url, json={"content": text})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = _json_object(response)
        except ValueError:
            return None
        tokens = data.get("tokens")
        if not isinstance(tokens, list):
            return None
        return len(cast(list[object], tokens))

    @property
    def has_props(self) -> bool:
        """Whether the generation server exposes ``/props`` (probed once)."""
        if self._has_props is None:
            self._has_props = bool(self.props())
        return self._has_props

    def props(self) -> dict[str, object]:
        """Return the server's ``/props`` dict, or ``{}`` if absent (LLM-04).

        Callers read keys such as ``n_ctx`` / ``n_parallel`` defensively with
        ``.get`` — an absent endpoint or key is never an error.
        """
        url = f"{_server_root(self._generation.base_url)}/props"
        try:
            response = self._http.request("GET", url)
        except httpx.HTTPError:
            return {}
        if response.status_code != 200:
            return {}
        try:
            return _json_object(response)
        except ValueError:
            return {}
