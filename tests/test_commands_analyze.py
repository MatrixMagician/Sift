"""``run_analyze`` branch tests — the full triage slice (CLUS-03, RAG-02, D-10).

ADR 0019 pass 2: these call ``run_analyze`` directly with list sinks rather
than driving ``sift analyze`` through ``CliRunner`` and grepping stdout. The
exit code is the return value, the operator lines are a list, and a case is an
open ``CaseStore`` — so an exit-3 branch is one call, not a subprocess-shaped
round trip through a case directory.

What ``tests/test_cli.py`` keeps is the part that is genuinely the CLI's: that
each flag lands on the right ``run_analyze`` parameter, that the returned code
reaches the shell (``DEGRADED`` included, ADR 0005), and the ``--help`` text.

Zero sockets: every inference call is served by an ``httpx.MockTransport``
injected through the ``llm.bringup.make_http_client`` seam, so the autouse
``_no_network`` conftest fixture stays active and untouched (EVAL-05). Vectors
are planted deterministically (the ``test_cluster`` plant): two ``alpha``
synonyms on one axis, two ``beta`` synonyms on a second, a lone ``gamma`` noise
point orthogonal to both — HDBSCAN merges the synonyms and leaves the noise a
singleton, giving three clusters.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from sift.adapters.eustack import EustackAdapter
from sift.commands import (
    ExitCode,
    resolve_generation_ctx,
    run_analyze,
    run_show_clusters,
)
from sift.config import load_config
from sift.llm.client import Endpoint, InferenceClient
from sift.models import Event, event_id
from sift.pipeline import dedup
from sift.pipeline.hypothesise import DEFAULT_TOP_CLUSTERS
from sift.store import CaseStore, case_db_path, open_case

_EUSTACK_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eustack"

Handler = Callable[[httpx.Request], httpx.Response]
_BASE = datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC)
_PROPS_SUFFIX = "/props"  # generation server capability document

# Planted 8-dim vectors (mirrors tests/test_cluster.py): alpha synonyms near
# axis 0, beta synonyms near axis 1, gamma noise orthogonal on axis 7.
_ALPHA_A = "alpha memory pressure warning"
_ALPHA_B = "alpha memory watermark exceeded"
_BETA_A = "beta smtp delivery retries"
_BETA_B = "beta smtp queue backing up"
_GAMMA = "gamma unrelated disk anomaly"

# Any message with no planted vector embeds to this one, so a fixture that only
# needs "some events" clusters predictably instead of landing on a zero vector.
_DEFAULT_VECTOR = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

_VECTORS: dict[str, list[float]] = {
    _ALPHA_A: [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _ALPHA_B: [0.99, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _BETA_A: [0.02, 0.99, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _BETA_B: [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    _GAMMA: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
}
_CORPUS = [_ALPHA_A, _ALPHA_B, _BETA_A, _BETA_B, _GAMMA]

# A minimal schema-valid HypothesisSet with no hypotheses: empty citations are
# trivially cited ⊆ prompted, so the citation gate passes and the run exits 0.
_VALID_HYPSET = json.dumps(
    {"hypotheses": [], "timeline_summary": "none", "unexplained_signals": []}
)


def _hypset(
    *, title: str, cited: list[str], confidence: str = "high"
) -> str:
    """One-hypothesis generation reply — the shape the citation gate judges."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": title,
                    "narrative": "the box ran out of memory",
                    "confidence": confidence,
                    "confidence_reasoning": "clear signal",
                    "supporting_event_ids": cited,
                    "contradicting_evidence": None,
                    "suggested_next_steps": ["add RAM"],
                }
            ],
            "timeline_summary": "one event",
            "unexplained_signals": [],
        }
    )


def _ev(offset: int, message: str, case: str = "demo") -> Event:
    return Event(
        event_id=event_id("case.log", offset),
        case_id=case,
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


def _seed_case(case: str, messages: list[str]) -> list[str]:
    """Create a case.db seeded with one event per message + template groups.

    Returns the event ids in message order, so a test can plant a citation that
    the model was genuinely shown (or deliberately one it was not).
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = CaseStore(db_path)
    try:
        with store.transaction():
            store.insert_events([_ev(i, m, case) for i, m in enumerate(messages)])
        dedup.rebuild_template_groups(store)
    finally:
        store.close()
    return [event_id("case.log", i) for i in range(len(messages))]


def _handler(
    *,
    calls: list[str] | None = None,
    chat_content: str | None = None,
    hyp_content: str | None = None,
    embed_raises: bool = False,
    generate_raises: bool = False,
    embed_model: str | None = None,
) -> Handler:
    """Serve /v1/embeddings + /v1/chat/completions (cluster labels AND triage).

    Two distinct chat calls flow through analyze: the cluster-label call (plain
    body, tagged ``chat``) and the citation-gated generation call (body carries
    ``response_format``, tagged ``generate``) — the handler branches on that
    key. ``hyp_content`` overrides the generation reply (default: a valid empty
    HypothesisSet, so the run exits 0). ``embed_raises`` makes the embeddings
    endpoint refuse the connection (the interrupted-embed atomicity probe).
    ``embed_model`` sets the model the embeddings server reports back.
    ``generate_raises`` refuses the connection for the GENERATION call alone,
    so clustering completes and only hypothesis generation fails. Every
    unrecognised path 404s, the capability document included — which is what
    makes the estimated-context-budget branch reachable by default.
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
                {"index": i, "embedding": _VECTORS.get(text, _DEFAULT_VECTOR)}
                for i, text in enumerate(inputs)
            ]
            body: dict[str, object] = {"data": data}
            if embed_model is not None:
                body["model"] = embed_model
            return httpx.Response(200, json=body)
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            if "response_format" in payload:
                # The hypothesise generation call — serve a HypothesisSet.
                if calls is not None:
                    calls.append("generate")
                if generate_raises:
                    raise httpx.ConnectError("connection refused", request=request)
                content = hyp_content if hyp_content is not None else _VALID_HYPSET
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": content}}]}
                )
            if calls is not None:
                calls.append("chat")
            body = {"choices": [{"message": {"content": chat_content or "{}"}}]}
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    return handler


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Bind the analyze client's httpx.Client to a MockTransport."""

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.llm.bringup.make_http_client", _factory)


class Run:
    """The result of one ``run_analyze`` call: code plus each sink's lines."""

    def __init__(
        self, code: ExitCode, out: list[str], err: list[str], said: list[str]
    ) -> None:
        self.code = code
        self.out = out
        self.err = err
        self.said = said

    @property
    def embedding_line(self) -> str:
        """The single ``Embeddings:`` summary line (D-06), isolated.

        Asserting over the whole output would let an unrelated ``0 new``
        elsewhere satisfy a reuse assertion.
        """
        lines = [ln for ln in self.out if ln.startswith("Embeddings: ")]
        assert len(lines) == 1, f"expected exactly one Embeddings line: {lines!r}"
        return lines[0]


def _analyze(
    case: str = "demo",
    *,
    allow_public: bool = False,
    label: bool = True,
    re_embed: bool = False,
    hint: str | None = None,
    kb: Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    top_clusters: int = DEFAULT_TOP_CLUSTERS,
) -> Run:
    """Open ``case``, run the analyse body against it, close, return the sinks.

    The knobs are spelled out rather than forwarded as ``**kwargs``: pyright
    then checks every call site against ``run_analyze``'s real signature, which
    a ``**kwargs: object`` forward would silently give up.
    """
    config = load_config()
    store = open_case(config.data_dir, case)
    out: list[str] = []
    err: list[str] = []
    said: list[str] = []
    try:
        code = run_analyze(
            store,
            config,
            allow_public=allow_public,
            label=label,
            re_embed=re_embed,
            hint=hint,
            kb=kb,
            since=since,
            until=until,
            top_clusters=top_clusters,
            echo=out.append,
            echo_err=err.append,
            announce=said.append,
        )
    finally:
        store.close()
    return Run(code, out, err, said)


@contextmanager
def _reopen(case: str = "demo") -> Generator[CaseStore]:
    """Reopen a case to assert on what the run persisted."""
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        yield store
    finally:
        store.close()


# --- cluster + label happy path ------------------------------------------


def test_analyze_clusters_and_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_case("demo", _CORPUS)
    calls: list[str] = []
    labels = json.dumps({0: "Memory pressure", 1: "SMTP backlog", 2: "Disk anomaly"})
    _patch_http(monkeypatch, _handler(calls=calls, chat_content=labels))
    run = _analyze()
    assert run.code is ExitCode.SUCCESS, run.out
    # alpha + beta merge, gamma is a noise singleton -> three clusters.
    assert "Clusters: 3 (3 labelled)" in run.out
    assert "embeddings" in calls  # the embed leg ran
    assert "chat" in calls  # eager labelling ran (D-01)


def test_analyze_no_label_skips_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_case("demo", _CORPUS)
    calls: list[str] = []
    _patch_http(monkeypatch, _handler(calls=calls))
    run = _analyze(label=False)
    assert run.code is ExitCode.SUCCESS, run.out
    assert "Clusters: 3 (0 labelled)" in run.out
    assert "embeddings" in calls
    assert "chat" not in calls  # label=False never calls the LLM (D-01)


def test_analyze_empty_case_reports_nothing_to_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A case with no ingested events (no template groups): no embed, clean exit.
    db_path = case_db_path(load_config().data_dir, "empty")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    CaseStore(db_path).close()
    calls: list[str] = []
    _patch_http(monkeypatch, _handler(calls=calls))
    run = _analyze("empty")
    assert run.code is ExitCode.SUCCESS, run.out
    assert run.out == ["Nothing to cluster; run 'sift ingest' first"]
    assert calls == []  # the client was never contacted


def test_analyze_eustack_only_case_still_narrates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-19-02/EUS-11: a case whose only ingested source is eu-stack has zero
    template groups (EXCLUDED_FROM_RANKING now holds "eustack"), but that must
    NOT be conflated with a genuinely empty case — analyze falls through to
    hypothesise() so the Phase-18 eu-stack fact block still narrates, instead
    of printing the factually wrong "run sift ingest first"."""
    adapter = EustackAdapter()
    adapter.input_root = _EUSTACK_FIXTURE_DIR
    events = list(
        adapter.parse(_EUSTACK_FIXTURE_DIR / "threaddump.txt", "eustack-only")
    )
    db_path = case_db_path(load_config().data_dir, "eustack-only")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = CaseStore(db_path)
    try:
        with store.transaction():
            store.insert_events(events)
        dedup.rebuild_template_groups(store)
    finally:
        store.close()

    calls: list[str] = []
    _patch_http(monkeypatch, _handler(calls=calls))
    run = _analyze("eustack-only")
    assert run.code is ExitCode.SUCCESS, run.out
    assert not any("Nothing to cluster" in line for line in run.out)
    assert "Clusters: 0 (0 labelled)" in run.out
    # The citation-gated generation call (tagged "generate" by _handler, as
    # opposed to the cluster-label "chat" call which never fires here since
    # cluster_and_label short-circuits on zero groups) proves the generation
    # leg genuinely ran.
    assert "generate" in calls
    # Zero exemplars to embed: cluster_and_label short-circuits before any
    # embed round-trip.
    assert "embeddings" not in calls


def test_analyze_public_endpoint_refused_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    monkeypatch.setenv("SIFT_EMBEDDINGS_BASE_URL", "http://8.8.8.8/v1")
    # Construction refuses first (LLM-02, T-03-21) — transport never reached.
    _patch_http(monkeypatch, _handler())
    run = _analyze()
    assert run.code is ExitCode.ERROR
    assert any("refusing non-local inference endpoint" in ln for ln in run.out)


def test_analyze_persists_embedding_model_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WR-03 / STORE-03: the production analyze path must persist the embedding
    # model the server reported to meta (provenance/determinism), not just the
    # dimension. Previously record_embedding_identity was only called by tests.
    _seed_case("demo", _CORPUS)
    _patch_http(monkeypatch, _handler(embed_model="nomic-embed-text-v1.5"))
    assert _analyze().code is ExitCode.SUCCESS
    with _reopen() as store:
        assert store.get_meta("embedding_model") == "nomic-embed-text-v1.5"
        assert store.get_meta("embedding_dim") == "8"


# --- embedding reuse (DET-01, D-06) ---------------------------------------


def test_analyze_prints_embedding_split_on_the_first_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DET-01/D-06: the split is always printed, first run included — a stable
    shape is what callers parse, and zero reuse is itself a signal."""
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    _patch_http(monkeypatch, _handler())
    run = _analyze()
    assert run.code is ExitCode.SUCCESS, run.out
    assert run.embedding_line == "Embeddings: 2 new, 0 reused"


def test_analyze_second_run_reports_full_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DET-01: a second analyze with no re-ingest makes no embedding calls.

    The reuse is announced, not silent: this server reports no embedding model,
    so a model change could not be detected, and that disclosure is the only
    thing standing between the operator and a stale vector.
    """
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    _patch_http(monkeypatch, _handler())
    assert _analyze().code is ExitCode.SUCCESS
    second = _analyze()
    assert second.embedding_line == "Embeddings: 0 new, 2 reused"
    assert any("verifiable model identity" in line for line in second.said)


def test_analyze_re_embed_discards_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-07: re_embed forces every exemplar to be embedded afresh."""
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    _patch_http(monkeypatch, _handler())
    assert _analyze().code is ExitCode.SUCCESS
    assert _analyze(re_embed=True).embedding_line == "Embeddings: 2 new, 0 reused"


# --- the CLI-04 exit-code branches ----------------------------------------


def test_analyze_exit_0_with_valid_cited_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG-02: a model whose citation is in the prompt exits 0, unflagged."""
    ids = _seed_case("demo", [_ALPHA_A])
    _patch_http(
        monkeypatch,
        _handler(hyp_content=_hypset(title="Memory exhaustion", cited=[ids[0]])),
    )
    run = _analyze()
    assert run.code is ExitCode.SUCCESS, run.out
    assert "Hypotheses: 1" in run.out
    assert "Run 'sift show hypotheses' to view them" in run.out
    with _reopen() as store:
        hyps = store.query_hypotheses()
        assert len(hyps) == 1
        assert hyps[0].citations_valid is True
        assert store.get_meta("triage_degraded") == "0"


def test_analyze_exit_3_on_malformed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed generation output (twice) degrades — exit 3, not 0 and not 1.

    The warning goes to stderr while the count stays on stdout, so a degraded
    run is still scriptable.
    """
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    _patch_http(monkeypatch, _handler(hyp_content="not json at all"))
    run = _analyze()
    assert run.code is ExitCode.DEGRADED, run.out
    assert "Hypotheses: 0 (degraded)" in run.out
    assert any("degraded" in line for line in run.err)
    with _reopen() as store:
        assert store.get_meta("triage_degraded") == "1"
        assert store.get_meta("triage_raw") is not None  # raw persisted


def test_analyze_exit_3_on_invalid_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hypothesis citing an unseen id is FLAGGED and degrades — exit 3.

    This is the anti-hallucination gate: the row is persisted and marked, never
    silently dropped and never presented as a clean success.
    """
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    _patch_http(
        monkeypatch,
        _handler(
            hyp_content=_hypset(
                title="Fabricated", cited=["deadbeefdeadbeef"], confidence="low"
            )
        ),
    )
    run = _analyze()
    assert run.code is ExitCode.DEGRADED, run.out
    with _reopen() as store:
        hyps = store.query_hypotheses()
        assert hyps and hyps[0].citations_valid is False


def test_analyze_exit_1_when_generation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI-04: a generation transport failure is exit 1, NOT the exit 3 a
    malformed reply earns — the run produced nothing to persist, so it must not
    be reported as degraded-but-persisted. The clustering that already
    succeeded is still summarised and still committed; only the triage leg
    failed, and the message says which.
    """
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    # No retries/backoff so the ConnectError surfaces immediately (no sleeps).
    monkeypatch.setenv("SIFT_GENERATION_RETRIES", "0")
    monkeypatch.setenv("SIFT_GENERATION_BACKOFF_BASE", "0")
    _patch_http(monkeypatch, _handler(generate_raises=True))
    run = _analyze()
    assert run.code is ExitCode.ERROR, run.out
    assert any(
        "hypothesis generation failed" in line and "no hypotheses were persisted"
        in line
        for line in run.out
    ), run.out
    # The cluster summary still printed — the failure is scoped to triage.
    assert any(line.startswith("Clusters: ") for line in run.out), run.out
    with _reopen() as store:
        assert store.query_clusters()  # the clustering leg's writes survived
        assert store.query_hypotheses() == []
        assert store.get_meta("triage_degraded") != "1"


def test_interrupted_embed_leaves_no_clusters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    # No retries/backoff so the ConnectError surfaces immediately (no sleeps).
    monkeypatch.setenv("SIFT_GENERATION_RETRIES", "0")
    monkeypatch.setenv("SIFT_GENERATION_BACKOFF_BASE", "0")
    _patch_http(monkeypatch, _handler(embed_raises=True))
    run = _analyze()
    assert run.code is ExitCode.ERROR
    # T-03-22: the embed leg raised mid-run → zero clusters persisted (atomic).
    with _reopen() as store:
        assert store.query_clusters() == []
        # show clusters therefore reverts to the pre-cluster template-groups view.
        shown: list[str] = []
        run_show_clusters(store, echo=shown.append)
    assert any(line.startswith("    exemplars: ") for line in shown)


# --- what `show clusters` renders from an analysed case (D-01) ------------


def test_show_clusters_renders_the_labels_analyze_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    labels = json.dumps({0: "Memory pressure", 1: "SMTP backlog", 2: "Disk anomaly"})
    _patch_http(monkeypatch, _handler(chat_content=labels))
    assert _analyze().code is ExitCode.SUCCESS
    with _reopen() as store:
        shown: list[str] = []
        run_show_clusters(store, echo=shown.append)
    rendered = "\n".join(shown)
    assert "Memory pressure" in rendered
    assert "SMTP backlog" in rendered
    assert "Disk anomaly" in rendered


def test_show_clusters_falls_back_to_signature_when_analyze_did_not_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    _patch_http(monkeypatch, _handler())
    assert _analyze(label=False).code is ExitCode.SUCCESS
    with _reopen() as store:
        clusters = store.query_clusters()
        assert clusters and not any(c.label for c in clusters)
        shown: list[str] = []
        run_show_clusters(store, echo=shown.append)
    rendered = "\n".join(shown)
    # The signature is the first 16 hex chars of the cluster's template hash —
    # non-empty, deterministic, and shown when no label exists (D-01).
    for cluster in clusters:
        assert cluster.signature in rendered


def test_show_clusters_strips_control_bytes_from_a_hostile_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_case("demo", _CORPUS)
    # A model that returns a label carrying a C1 CSI byte (U+009B) and a bidi
    # override (U+202E) — T-03-20: the whole rendered line is sanitise'd, so
    # neither control byte survives, only the printable text does.
    hostile = "clean\x9b31mRED‮"
    labels = json.dumps({0: hostile, 1: "ok", 2: "ok"})
    _patch_http(monkeypatch, _handler(chat_content=labels))
    assert _analyze().code is ExitCode.SUCCESS
    with _reopen() as store:
        shown: list[str] = []
        run_show_clusters(store, echo=shown.append)
    rendered = "\n".join(shown)
    assert "\x9b" not in rendered  # C1 CSI stripped
    assert "‮" not in rendered  # bidi override stripped
    assert "clean31mRED" in rendered  # the printable text survives


# --- D-10: the single generation-context resolution point -----------------


def _ctx_probe_client(handler: Handler) -> InferenceClient:
    """A bare client for exercising ``resolve_generation_ctx``."""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Endpoint(base_url="http://127.0.0.1:8080/v1", model=None)
    return InferenceClient(ep, ep, http, backoff_base=0.0)


def _ctx_props_handler(n_ctx: object) -> Handler:
    """Serve the generation server capability document carrying ``n_ctx``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(_PROPS_SUFFIX):
            body = {} if n_ctx is None else {"n_ctx": n_ctx}
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    return handler


def _ctx_absent_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404)


def test_resolve_generation_ctx_prefers_configured() -> None:
    """A pinned generation.context is never overridden by the server."""
    client = _ctx_probe_client(_ctx_props_handler(32768))
    assert resolve_generation_ctx(4096, client) == (4096, None)


def test_resolve_generation_ctx_discovers_n_ctx() -> None:
    """Unconfigured: a positive discovered window is used, with no warning."""
    client = _ctx_probe_client(_ctx_props_handler(32768))
    assert resolve_generation_ctx(None, client) == (32768, None)


def test_resolve_generation_ctx_warns_when_props_absent() -> None:
    """The Lemonade case (LLM-04): estimated budget, disclosed."""
    client = _ctx_probe_client(_ctx_absent_handler)
    ctx, warning = resolve_generation_ctx(None, client)
    assert ctx == 8192
    assert warning is not None
    assert "estimated rather than discovered" in warning


def test_resolve_generation_ctx_warns_when_n_ctx_unusable() -> None:
    """A present document carrying no usable n_ctx is still an estimate."""
    for unusable in (None, 0, -1, "big"):
        client = _ctx_probe_client(_ctx_props_handler(unusable))
        ctx, warning = resolve_generation_ctx(None, client)
        assert ctx == 8192, unusable
        assert warning is not None, unusable
        assert "estimated rather than discovered" in warning


def test_analyze_discloses_an_estimated_budget_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning is emitted through echo_err and breaks nothing else.

    ``_handler`` 404s the capability document, so this is the default path
    against a server that serves no ``/props`` — the warning's wording is
    pinned by the unit tests above.
    """
    _seed_case("demo", [_ALPHA_A])
    _patch_http(monkeypatch, _handler())
    run = _analyze()
    assert run.code is ExitCode.SUCCESS, run.out
    assert any("estimated rather than discovered" in line for line in run.err)


def test_analyze_issues_exactly_one_props_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-10: one resolution point means one capability-document GET per run.

    Stronger than a grep for ``props()`` call sites: ``sift doctor``
    legitimately has its own, so only counting real requests on the analyze
    path proves the pipeline's own probe is genuinely short-circuited by
    ``ctx_configured``.
    """
    seen: list[str] = []
    inner = _handler()

    def counting(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith(_PROPS_SUFFIX):
            return httpx.Response(200, json={"n_ctx": 32768})
        return inner(request)

    _seed_case("demo", [_ALPHA_A])
    _patch_http(monkeypatch, counting)
    assert _analyze().code is ExitCode.SUCCESS
    props_hits = [p for p in seen if p.endswith(_PROPS_SUFFIX)]
    assert len(props_hits) == 1, props_hits


def test_analyze_default_announce_sink_writes_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``announce=None`` binds the CLI's own STDERR console (D-04).

    Every other test here injects a list to keep the progress narration
    inspectable, which would leave the default branch — the one the CLI
    actually ships — never executed. Two details are load-bearing:

    * it is the SECOND run that narrates. The pipeline only announces on the
      reuse and dimension-change paths, so a single fresh run would build the
      console and never write to it.
    * the narration must land on stderr, not stdout. Stdout is the scriptable
      channel; a default sink wired to it would corrupt every parsed run
      without failing anything else.
    """
    _seed_case("demo", [_ALPHA_A, _BETA_A])
    _patch_http(monkeypatch, _handler())
    assert _analyze().code is ExitCode.SUCCESS

    config = load_config()
    store = open_case(config.data_dir, "demo")
    out: list[str] = []
    try:
        code = run_analyze(store, config, echo=out.append, echo_err=lambda _: None)
    finally:
        store.close()
    assert code is ExitCode.SUCCESS, out
    captured = capsys.readouterr()
    assert "verifiable model identity" in captured.err
    assert "verifiable model identity" not in captured.out
