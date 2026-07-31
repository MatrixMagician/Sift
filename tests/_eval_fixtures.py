"""Shared offline fixtures for the eval-harness tests (EVAL-05).

Zero sockets: every inference call is served by an ``httpx.MockTransport`` bound
through the ``llm.bringup.make_http_client`` seam, mirroring ``tests/test_analyze.py``
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
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

Handler = Callable[[httpx.Request], httpx.Response]

_REPO_ROOT = Path(__file__).resolve().parents[1]


_EUSTACK_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "eustack" / "threaddump.txt"

# The measured truth for _EUSTACK_FIXTURE (verified in test_eval_thresholds.py's
# test_eustack_case_scored_with_zero_client_contact): 4 threads, all unclassified
# by the day-one taxonomy, critical unclassified_thread_pct + info
# no_resolvable_frame_pct. Reused verbatim rather than re-measured, per D-08.
_EUSTACK_SMOKE_TRUTH = (
    "root_cause: near-idle capture, all threads unclassified by design\n"
    "expect_eustack:\n"
    "  provenance: authored\n"
    "  hang_detected: false\n"
    "  total_threads: 4\n"
    "  warn: 0\n"
    "  critical: 1\n"
    "  info_dimensions:\n"
    "    - no_resolvable_frame_pct\n"
)


def single_case_suite(
    tmp_path: Path, case: str = "memory-watermark-cascade"
) -> Path:
    """Copy one committed golden case into an isolated temp suite directory,
    plus a self-contained, zero-network eu-stack case.

    The offline machinery/gate tests assert exit-code behaviour with the good
    handler, which only hits the memory-watermark-cascade keywords. They must
    stay decoupled from the real suite's breadth (Plan 04 grows it to six cases
    the single handler cannot hit), so they run against a one-case copy rather
    than ``eval/cases`` itself.

    The eu-stack case is built from the shipped
    ``tests/fixtures/eustack/threaddump.txt`` fixture (never from the committed
    ``eval/cases/eustack-healthy`` golden case, which these tests must stay
    decoupled from too) so every offline-suite test satisfies the D-19-13
    zero-eu-stack-cases vacuity guard (Plan 19-03) without depending on the real
    suite's breadth. It reaches no inference endpoint (D-19-06), so it cannot
    interfere with the keyword-metric handler under test.
    """
    src = _REPO_ROOT / "eval" / "cases" / case
    suite = tmp_path / "suite"
    shutil.copytree(src, suite / case)
    eustack_dir = suite / "eustack-smoke"
    (eustack_dir / "input").mkdir(parents=True)
    shutil.copy(_EUSTACK_FIXTURE, eustack_dir / "input" / "threaddump.txt")
    (eustack_dir / "truth.yaml").write_text(_EUSTACK_SMOKE_TRUTH, encoding="utf-8")
    return suite

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

    monkeypatch.setattr("sift.llm.bringup.make_http_client", _factory)
