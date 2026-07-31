"""The M001 acceptance demo as one headless Pilot session (S05/T03, R007).

The full demo runs in-process with zero sockets against the real
``eval/cases/eustack-hang-pool-warehouse`` thread dump: ingest (``i``) and
analyse (``a``) through the S04 workers, the R001/R002 roam, verdicts at all
three levels through the S03 modal, quit, reopen to prove persistence, a
headless ``sift validate`` on the same case, and finally the ``e`` export
whose Markdown report must carry every recorded verdict (R007).

Two deliberate departures from a naive reading of the demo script:

* **The input bundle is the eval thread dump PLUS a small generic sidecar
  log.** Eu-stack events are ``EXCLUDED_FROM_RANKING`` (store.py, D-07), so
  the thread dump alone yields zero template groups and zero clusters —
  cluster- and template-level verdicts would have no target. The sidecar
  supplies those targets, mirroring ``test_eustack_analyze``'s
  eu-stack-carrying-store pattern; the eu-stack dump remains the incident
  core and the hypothesis cites its real ingested event ids.
* **The fake server is dynamic.** The static ``_VALID_HYPSET`` in
  ``tests/_report_fixtures.py`` cites ids that do not exist in this case, so
  the triage reply is built at request time: every ``[evt:<id>]`` token in
  the assembled prompt is extracted and cited, which passes the citation
  gate against genuinely ingested eu-stack event ids. Embeddings are served
  as distinct sha256-derived vectors — the ``[0.0]*8`` default would
  degenerate clustering (research Pitfall 2).

All inference traffic rides the ``sift.llm.bringup.make_http_client`` seam via
``httpx.MockTransport``; the autouse ``_no_network`` guard stays active.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from textual.widgets import Static
from typer.testing import CliRunner

from sift.cli import app as cli_app
from sift.config import load_config
from sift.store import CaseStore, case_db_path
from sift.tui.app import SiftApp
from sift.tui.screens.clusters import ClusterDetailScreen, ClustersScreen
from sift.tui.screens.error import NotAnalysedScreen
from sift.tui.screens.evidence import EvidenceScreen, RawSourceScreen
from sift.tui.screens.hypotheses import HypothesesScreen
from sift.tui.screens.timeline import TimelineScreen
from sift.tui.screens.verdict_modal import VerdictModal

Handler = Callable[[httpx.Request], httpx.Response]
runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EUSTACK_DUMP = (
    _REPO_ROOT / "eval" / "cases" / "eustack-hang-pool-warehouse" / "input"
    / "threaddump.txt"
)

_EVT_TOKEN = re.compile(r"\[evt:([0-9a-f]{16})\]")

# The generic sidecar: two connection-refused variants sharing one masked
# template, two identical pool lines sharing another, one distinct warning —
# three template groups, so clusters and templates exist to verdict on.
_SIDECAR_LOG = (
    "2026-07-17 09:00:00 ERROR Connection to 10.0.0.5 refused after 30 s\n"
    "2026-07-17 09:00:30 ERROR Connection to 10.9.9.9 refused after 45 s\n"
    "2026-07-17 09:01:00 ERROR Warehouse pool exhausted: 0 of 64 slots free\n"
    "2026-07-17 09:01:30 ERROR Warehouse pool exhausted: 0 of 64 slots free\n"
    "2026-07-17 09:02:00 WARN Queue depth climbing on scheduler\n"
)

HYP_TITLE = "Warehouse pool exhausted by parked query threads"
DEMO_NOTE = "demoruled"  # typed into the modal note field key-by-key
HEADLESS_NOTE = "Headless validation from the follow-up call"


def _vector(text: str) -> list[float]:
    """A deterministic, per-text, non-degenerate 8-dim embedding."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:8]]


def _acceptance_handler(cited: list[list[str]]) -> Handler:
    """Serve embeddings, labels and a DYNAMIC triage reply.

    The hypothesis set is built at request time from the assembled prompt:
    every ``[evt:<id>]`` token the prompt shows becomes a citation, so the
    reply passes the citation gate against the genuinely ingested events —
    including the eu-stack fact-block ids. Each cited id list is appended to
    ``cited`` so the test can prove eu-stack ids were really cited.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            data = [
                {"index": i, "embedding": _vector(text)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data, "model": "acc-embed"})
        if path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            if "response_format" not in payload:
                # Cluster labels: none — clusters keep their signatures.
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "{}"}}]}
                )
            prompt = payload["messages"][0]["content"]
            ids = list(dict.fromkeys(_EVT_TOKEN.findall(prompt)))
            cited.append(ids)
            body = json.dumps(
                {
                    "hypotheses": [
                        {
                            "title": HYP_TITLE,
                            "narrative": (
                                "Every warehouse worker is parked in "
                                "WaitUntilFinished, starving the pool."
                            ),
                            "confidence": "high",
                            "confidence_reasoning": (
                                "The thread-population composition "
                                "corroborates saturation."
                            ),
                            "supporting_event_ids": ids,
                            "contradicting_evidence": None,
                            "suggested_next_steps": [
                                "Inspect warehouse connection limits"
                            ],
                        }
                    ],
                    "timeline_summary": (
                        "Pool saturation observed at thread-dump capture."
                    ),
                    "unexplained_signals": [],
                }
            )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": body}}]}
            )
        return httpx.Response(404)

    return handler


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Route all inference HTTP through the seam (zero sockets)."""

    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
        )

    monkeypatch.setattr("sift.llm.bringup.make_http_client", _factory)


def _seed_case(case: str, tmp_path: Path) -> None:
    """A migrated case.db pointing at the composed acceptance bundle — the
    state ``sift new`` leaves behind, without invoking the CLI."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    shutil.copy2(_EUSTACK_DUMP, bundle / "threaddump.txt")
    (bundle / "support.log").write_text(_SIDECAR_LOG, encoding="utf-8")
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        with store.transaction():
            store.set_meta("input_dir", str(bundle))
    finally:
        store.close()


async def _wait_workers(app: SiftApp) -> None:
    await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]


def _static(app: SiftApp, widget_id: str) -> str:
    return str(app.screen.query_one(f"#{widget_id}", Static).content)


async def test_acceptance_demo_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The full M001 demo: i → a → roam → three-level verdicts → quit →
    reopen (persisted badges) → headless validate → exported report carrying
    every recorded verdict."""
    case = "eustackdemo"
    _seed_case(case, tmp_path)
    cited: list[list[str]] = []
    _patch_http(monkeypatch, _acceptance_handler(cited))
    config = load_config()

    # --- Session one: ingest, analyse, roam, three verdicts, quit ---------
    store = CaseStore(case_db_path(config.data_dir, case))
    try:
        app = SiftApp(store, case, config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            landing = app.screen
            assert isinstance(landing, NotAnalysedScreen)

            # i: ingest the composed bundle through the run_ingest worker.
            await pilot.press("i")
            await _wait_workers(app)
            await pilot.pause()
            assert isinstance(app.screen, NotAnalysedScreen)
            assert ("Ingest complete", "idle") in landing.pipeline_log
            events = store.query_events()
            sources = {event.source for event in events}
            assert "eustack" in sources  # the real thread dump landed
            assert "genericlog" in sources  # the sidecar targets landed

            # a: analyse through the run_analyze worker + dynamic handler.
            await pilot.press("a")
            await _wait_workers(app)
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            assert ("Analyse complete", "idle") in landing.pipeline_log
            # A clean run, never degraded: every citation resolved.
            assert store.get_meta("triage_degraded") == "0"
            by_id = {event.event_id: event for event in store.query_events()}
            assert cited and cited[0], "the triage prompt showed no ids"
            assert all(eid in by_id for eid in cited[0])
            assert any(
                by_id[eid].source == "eustack" for eid in cited[0]
            ), "the hypothesis must cite real ingested eu-stack event ids"
            assert app.screen.table.row_count == 1

            # Roam: hypotheses → evidence → raw source, then t/c.
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert "Confidence: high" in _static(app, "evidence-confidence")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, RawSourceScreen)
            assert _static(app, "raw-text").strip()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TimelineScreen)
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            # Escape retraces the trail home to the landing screen.
            for expected in (RawSourceScreen, EvidenceScreen, HypothesesScreen):
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, expected)

            # Verdict 1 — hypothesis level, with a note, via the modal.
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("c")  # confirmed
            await pilot.press("tab")  # focus the note field
            await pilot.press(*DEMO_NOTE)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            row = [cell.plain for cell in app.screen.table.get_row_at(0)]
            assert row[4] == "confirmed"
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 1/1 hypotheses"
            )

            # Verdict 2 — cluster level. Legible failure if clustering
            # collapsed: the demo needs a cluster target (research Pitfall 2).
            assert store.query_clusters(), "no clusters — nothing to verdict"
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("r")  # rejected
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            assert [c.plain for c in app.screen.table.get_row_at(0)][5] == (
                "rejected"
            )

            # Verdict 3 — template level, via the cluster-detail member row.
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            await pilot.press("v")
            await pilot.pause()
            assert isinstance(app.screen, VerdictModal)
            await pilot.press("u")  # uncertain
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            assert [c.plain for c in app.screen.table.get_row_at(0)][6] == (
                "uncertain"
            )

            # Quit cleanly from the landing screen.
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            await pilot.press("q")
        assert not app.is_running
        assert app.return_code == 0
    finally:
        store.close()

    # The three TUI verdicts are committed rows, built by record_validation
    # (the context snapshots prove the service path, MEM008).
    store = CaseStore(case_db_path(config.data_dir, case))
    try:
        rows = store.list_verdicts()
        assert {(v.target_type, v.verdict) for v in rows} == {
            ("hypothesis", "confirmed"),
            ("cluster", "rejected"),
            ("template", "uncertain"),
        }
        hyp_row = next(v for v in rows if v.target_type == "hypothesis")
        assert hyp_row.note == DEMO_NOTE
        assert hyp_row.context["title"] == HYP_TITLE
        cluster_id = next(
            v.target_id for v in rows if v.target_type == "cluster"
        )
        template_id = next(
            v.target_id for v in rows if v.target_type == "template"
        )
    finally:
        store.close()

    # --- Session two: reopen → persisted badges → validate → export -------
    store = CaseStore(case_db_path(config.data_dir, case))
    try:
        app = SiftApp(store, case, config=config)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HypothesesScreen)
            row = [cell.plain for cell in app.screen.table.get_row_at(0)]
            assert row[4] == "confirmed"  # persisted, repainted from the DB
            assert _static(app, "hypotheses-progress").startswith(
                "Reviewed 1/1 hypotheses"
            )
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, ClustersScreen)
            assert [c.plain for c in app.screen.table.get_row_at(0)][5] == (
                "rejected"
            )
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ClusterDetailScreen)
            assert [c.plain for c in app.screen.table.get_row_at(0)][6] == (
                "uncertain"
            )

            # Headless validate against the SAME case, mid-session: the CLI
            # and the open TUI store are two WAL connections to one case.db.
            result = runner.invoke(
                cli_app,
                [
                    "validate",
                    case,
                    "hypothesis:0",
                    "--uncertain",
                    "--note",
                    HEADLESS_NOTE,
                ],
            )
            assert result.exit_code == 0, result.output

            # e: export the Markdown report through the run_report worker
            # ('e' lives on the CaseScreen base, so it works from here too).
            await pilot.press("e")
            await _wait_workers(app)
            await pilot.pause()
            out = case_db_path(config.data_dir, case).parent / "report.md"
            assert app.last_report_path == out
    finally:
        store.close()

    # --- The exported report is the durable R007 record -------------------
    text = out.read_text(encoding="utf-8")
    assert "## Recorded verdicts" in text
    section = text.split("## Recorded verdicts", 1)[1].split("\n## ", 1)[0]
    # All four verdicts render — three from the TUI plus the headless one.
    assert section.count("- **") == 4
    assert "### Hypothesis verdicts" in section
    assert "### Cluster verdicts" in section
    assert "### Template verdicts" in section
    assert "**confirmed**" in section
    assert "**rejected**" in section
    assert section.count("**uncertain**") == 2  # template + headless rows
    assert "hypothesis:0" in section
    assert f"cluster:{cluster_id}" in section
    assert f"template:{template_id}" in section
    assert HYP_TITLE in section  # label derived from the context snapshot
    assert DEMO_NOTE in section
    assert HEADLESS_NOTE in section
