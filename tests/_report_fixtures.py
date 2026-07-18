"""Shared analysed-case builder for Phase-6 report tests (REPT-01/02).

Builds a real analysed ``case.db`` with zero sockets: clustering and labelling
run through the same ``httpx.MockTransport`` seam as ``tests/test_analyze.py``
(so the autouse ``_no_network`` guard stays active), then the exact hypotheses
and ``triage_*`` run-meta the renderer reads are planted deterministically via
the public store API. Planting (rather than round-tripping the citation gate)
keeps the fixture's citations, FLAGGED verdicts and degraded flag fully
controllable — the renderer under test only ever reads the store.

This is a plain helper module, NOT a conftest fixture: ``tests/conftest.py`` is
owned by plan 01-01 and must stay untouched (later plans add fixtures in their
own files).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config
from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.store import CaseStore, StoredHypothesis, case_db_path

if TYPE_CHECKING:
    import pytest

Handler = Callable[[httpx.Request], httpx.Response]
runner = CliRunner()
_BASE = datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC)

# Planted 8-dim vectors (mirrors tests/test_analyze.py): alpha synonyms near
# axis 0, beta synonyms near axis 1, gamma noise orthogonal on axis 7 — HDBSCAN
# merges the synonyms and leaves gamma a singleton, giving three real clusters.
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

# A schema-valid HypothesisSet with no hypotheses, so the analyze leg exits 0;
# the real hypotheses are planted afterwards.
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)

# REAL_ID is a genuinely stored event (offset 0 == _ALPHA_A) → the appendix can
# show its raw + provenance. MISSING_ID is 16 hex chars that are never a stored
# event → a cited-but-absent id the renderer must leave as plain text (Pitfall 2).
REAL_ID = event_id("case.log", 0)
MISSING_ID = "0" * 16
REAL_RAW = _ALPHA_A  # what the appendix code block should contain for REAL_ID
TIMELINE_SUMMARY = "09:00 memory watermark warnings; 09:05 worker OOM-killed"
UNEXPLAINED = ["gamma unrelated disk anomaly on a separate volume"]
TRIAGE_MODEL = "test-triage-model"
PROMPT_HASH = "deadbeefdeadbeef"


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


def _seed_case(case: str) -> None:
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        with store.transaction():
            store.insert_events([_ev(i, m) for i, m in enumerate(_CORPUS)])
        dedup.rebuild_template_groups(store)
    finally:
        store.close()


def _handler() -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions (cluster labels AND triage)."""
    labels = json.dumps({0: "Memory pressure", 1: "SMTP backlog", 2: "Disk anomaly"})

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": _VECTORS.get(text, [0.0] * 8)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data, "model": "test-embed"})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            content = _VALID_HYPSET if "response_format" in payload else labels
            return httpx.Response(
                200, json={"choices": [{"message": {"content": content}}]}
            )
        return httpx.Response(404)

    return handler


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.cli._make_http_client", _factory)


def _default_hypotheses() -> list[StoredHypothesis]:
    return [
        StoredHypothesis(
            hyp_index=0,
            title="Memory pressure exhausted the worker",
            narrative=(
                "The worker crossed a memory watermark; the smoking gun is "
                f"[evt:{REAL_ID}]. A stray reference [evt:{MISSING_ID}] points "
                "at an event that is not in this case store."
            ),
            confidence="high",
            confidence_reasoning="Two correlated memory warnings precede the kill.",
            supporting_event_ids=[REAL_ID],
            contradicting_evidence=None,
            suggested_next_steps=["Raise the cgroup memory limit"],
            citations_valid=True,
        ),
        StoredHypothesis(
            hyp_index=1,
            title="SMTP backlog is a secondary symptom",
            narrative=f"Queue growth follows the memory event; see [evt:{REAL_ID}].",
            confidence="low",
            confidence_reasoning="Weak temporal correlation only.",
            supporting_event_ids=[REAL_ID],
            contradicting_evidence="Delivery resumed without intervention.",
            suggested_next_steps=["Confirm queue drained after restart"],
            citations_valid=True,
        ),
    ]


def _degraded_hypotheses() -> list[StoredHypothesis]:
    return [
        StoredHypothesis(
            hyp_index=0,
            title="Memory pressure exhausted the worker",
            narrative=f"The worker was OOM-killed; see [evt:{REAL_ID}].",
            confidence="high",
            confidence_reasoning="Two correlated memory warnings precede the kill.",
            supporting_event_ids=[REAL_ID],
            contradicting_evidence=None,
            suggested_next_steps=["Raise the cgroup memory limit"],
            citations_valid=True,
        ),
        StoredHypothesis(
            hyp_index=1,
            title="Fabricated disk failure",
            narrative=(
                "The model cited an event it was never shown: "
                f"[evt:{MISSING_ID}] cannot be resolved."
            ),
            confidence="medium",
            confidence_reasoning="Model asserted a cause with no shown evidence.",
            supporting_event_ids=[MISSING_ID],
            contradicting_evidence=None,
            suggested_next_steps=["Ignore this flagged hypothesis"],
            citations_valid=False,
        ),
    ]


def _plant(case: str, *, degraded: bool) -> None:
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        rows = _degraded_hypotheses() if degraded else _default_hypotheses()
        with store.transaction():
            store.replace_hypotheses(rows)
            store.set_meta("triage_degraded", "1" if degraded else "0")
            store.set_meta("triage_prompt_hash", PROMPT_HASH)
            store.set_meta("triage_created_at", "2026-07-17T09:10:00+00:00")
            store.set_meta("triage_model", TRIAGE_MODEL)
            store.set_meta("triage_timeline_summary", TIMELINE_SUMMARY)
            store.set_meta("triage_unexplained_signals", json.dumps(UNEXPLAINED))
    finally:
        store.close()


def build_analysed_case(
    monkeypatch: pytest.MonkeyPatch, *, case: str = "demo", degraded: bool = False
) -> str:
    """Return the name of a freshly analysed case with planted hypotheses.

    Runs the real ``sift analyze`` path (embed → cluster → label) against a
    ``MockTransport`` fake server so the case has real clusters + embedding
    meta, then plants deterministic hypotheses + ``triage_*`` meta. Pass
    ``degraded=True`` for a run with ``triage_degraded=1`` and a FLAGGED
    (``citations_valid=0``) row citing an id that is not in the store.
    """
    _seed_case(case)
    _patch_http(monkeypatch, _handler())
    result = runner.invoke(app, ["analyze", case])
    assert result.exit_code == 0, result.output
    _plant(case, degraded=degraded)
    return case


def open_case(case: str) -> CaseStore:
    """Open the built case for direct assertions or extra planting."""
    return CaseStore(case_db_path(load_config().data_dir, case))
