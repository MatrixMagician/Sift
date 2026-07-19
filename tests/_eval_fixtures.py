"""Shared offline fixtures for the eval-harness tests (EVAL-05).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` bound
through the ``cli._make_http_client`` seam, mirroring ``tests/test_analyze.py``
so the autouse ``_no_network`` conftest guard stays active. The good handler
serves ``/v1/embeddings`` (a deterministic per-text vector) plus the two chat
calls analyze/eval make: the plain cluster-label call and the
``response_format``-tagged generation call, which returns a ``HypothesisSet``
whose title/narrative hit the memory-watermark-cascade acceptable_keywords so
``hypothesis_hit_at_k`` passes offline.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import httpx
import pytest

Handler = Callable[[httpx.Request], httpx.Response]

# A HypothesisSet that hits the memory-watermark-cascade acceptable_keywords
# (memory, watermark, OOM, cascade). Empty supporting_event_ids are trivially
# cited ⊆ prompted, so the citation gate passes and citations_valid is True.
_GOOD_HYPSET: dict[str, object] = {
    "hypotheses": [
        {
            "title": "Memory high-watermark breach cascaded into OOM kills",
            "narrative": (
                "An early memory high-watermark warning preceded progressive "
                "cache eviction that cascaded into OOM kills of the worker pool."
            ),
            "confidence": "high",
            "confidence_reasoning": (
                "The watermark breach precedes, and best explains, the OOM cascade."
            ),
            "supporting_event_ids": [],
            "contradicting_evidence": None,
            "suggested_next_steps": [
                "Raise the heap ceiling",
                "Tune the cache eviction policy",
            ],
        }
    ],
    "timeline_summary": "Watermark breach, then cache eviction, then OOM cascade.",
    "unexplained_signals": [],
}
GOOD_HYPSET = json.dumps(_GOOD_HYPSET)


def _vector(text: str, dim: int = 8) -> list[float]:
    """A deterministic pseudo-embedding for ``text`` (same text → same vector).

    Determinism matters twice over: it keeps the two determinism-drift runs
    byte-identical, and it lets the offline suite open zero sockets while still
    exercising the real clustering + hypothesise pipeline.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[i] / 255.0 for i in range(dim)]


def eval_handler(*, hyp_content: str | None = None) -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions offline (the good handler).

    ``hyp_content`` overrides the generation reply (default: a keyword-hitting
    HypothesisSet). The cluster-label call (no ``response_format``) returns an
    empty object, so clusters keep their signatures — labels are irrelevant to
    the four metrics and keeping them empty stays deterministic.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": _vector(text)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            if "response_format" in payload:
                content = hyp_content if hyp_content is not None else GOOD_HYPSET
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": content}}]}
                )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "{}"}}]}
            )
        return httpx.Response(404)

    return handler


def patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Bind the eval/analyze httpx.Client to a MockTransport (the EVAL-05 seam)."""

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.cli._make_http_client", _factory)
