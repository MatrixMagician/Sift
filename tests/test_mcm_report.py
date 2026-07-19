"""Renderer + CSV goldens for the MCM forensics bundle (MCM-05, Plan 10-04).

RED half: these assertions pin the executable contract for the yet-to-exist
``sift.render.mcm_report`` module — ``render_mcm_markdown`` (D-11 timeline-first
layout), ``render_mcm_json`` (deterministic, ASCII-safe) and
``write_attribution_csv`` (D-15 single dimension-tagged CSV, D-16 every row
carries its owning ``event_id``s). Until that module lands the suite fails at
import — the intended Wave-4 RED state.

Renderer goldens are built over a REAL ``McmAnalysis`` (``analyse_mcm`` over an
ingested Hartford fixture) so they track the actual model shapes, plus one
synthetic hostile-field analysis to prove the shared markdown escaping is
load-bearing (T-10-12: hostile log bytes cannot inject Markdown/HTML structure).
No network, no ``input()`` — the conftest guards are autouse.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.config import McmThresholdsConfig
from sift.pipeline.mcm import (
    Attribution,
    AttributionRow,
    DiagnosticFlag,
    EpisodeAnalysis,
    EpisodeWindow,
    LifecycleSignal,
    McmAnalysis,
    McmEpisode,
    MemoryBreakdown,
    analyse_mcm,
)
from sift.render.mcm_report import (  # RED: module built GREEN in Task 2
    render_mcm_json,
    render_mcm_markdown,
    write_attribution_csv,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"

_MD_HEADINGS = (
    "### Lifecycle timeline",
    "### Diagnostic flags",
    "### Denial-time memory breakdown",
    "### Attribution by object (OID)",
    "### Attribution by request source",
    "### Attribution by session (SID)",
)


def _analysis(rel: str = "hartford_deny_predenial_multisid.log") -> McmAnalysis:
    """Build a real ``McmAnalysis`` by ingesting a Hartford fixture (no network)."""
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, "case1"))
    return analyse_mcm(events, McmThresholdsConfig())


def _hostile_analysis() -> McmAnalysis:
    """A synthetic one-episode analysis whose log-sourced fields carry Markdown/
    HTML metacharacters and a C1/bidi control byte (T-10-12 guard input)."""
    hostile_key = "AABB|## [x](y) <img src=x onerror=alert(1)>"
    bidi = "‮"  # right-to-left override — a Cf terminal-reorder byte
    episode = McmEpisode(
        denial_event_id="00ff00ff00ff00ff",
        denial_ts="2026-07-19T10:00:00+00:00",
        recovery=None,
        open_truncated=True,
        fragmented=False,
        event_ids=("00ff00ff00ff00ff",),
        lifecycle=(
            LifecycleSignal(
                kind="memory-status-low",
                event_id="00ff00ff00ff00ff",
                ts="2026-07-19T10:00:00+00:00",
                text=f"Memory status changes to low {bidi}<script>alert(1)</script>",
            ),
        ),
        breakdown=MemoryBreakdown(
            raw_map={}, current_memory_info={}, mcm_settings={}
        ),
        hwm_bytes=None,
        avail_timeline=(),
    )
    window = EpisodeWindow(
        threshold_pct=0,
        start_event_id=None,
        hwm_bytes=None,
        request_count=0,
        label="full available lead-up",
    )
    flag = DiagnosticFlag(
        dimension="working_set_pct_virtual",
        severity="critical",
        value_pct=65.4,
        message="Working set is 65.4% of IServer virtual memory",
        event_ids=("00ff00ff00ff00ff",),
    )
    row = AttributionRow(
        dimension="oid",
        key=hostile_key,
        granted_bytes=1024,
        request_count=1,
        event_ids=("00ff00ff00ff00ff",),
        sids=("DEADBEEF",),
    )
    attribution = Attribution(
        by_oid=(row,),
        by_source=(
            AttributionRow(
                dimension="source",
                key="GovernedObject",
                granted_bytes=1024,
                request_count=1,
                event_ids=("00ff00ff00ff00ff",),
            ),
        ),
        by_sid=(
            AttributionRow(
                dimension="sid",
                key="DEADBEEF",
                granted_bytes=1024,
                request_count=1,
                event_ids=("00ff00ff00ff00ff",),
            ),
        ),
        unmatched_event_ids=(),
    )
    return McmAnalysis(
        episodes=(
            EpisodeAnalysis(
                episode=episode,
                window=window,
                flags=(flag,),
                attribution=attribution,
            ),
        )
    )


def test_markdown_layout_order() -> None:
    """D-11: per episode the report is timeline → flags → breakdown → the three
    attribution tables, in that order."""
    md = render_mcm_markdown(_analysis())
    positions = [md.index(h) for h in _MD_HEADINGS]
    assert positions == sorted(positions), md
    # Every heading is present exactly once for the single-episode fixture.
    for h in _MD_HEADINGS:
        assert md.count(h) == 1, h


def test_markdown_sanitises_hostile_fields() -> None:
    """T-10-12: hostile log bytes in a key / lifecycle text render escaped — no
    raw ``<img``/``<script``, no bidi control byte, and the ``|`` is escaped so a
    cell cannot break the attribution table."""
    md = render_mcm_markdown(_hostile_analysis())
    assert "<img" not in md
    assert "<script" not in md
    assert "‮" not in md
    # The hostile key's pipe is backslash-escaped (never a raw column break).
    assert "AABB\\|" in md


def test_markdown_no_absolute_gb_headline() -> None:
    """T-10-16: flag lines are framed as percentages, never an absolute-GB
    headline figure."""
    md = render_mcm_markdown(_analysis("hartford_deny_slice.log"))
    flag_lines = [
        line
        for line in md.splitlines()
        if "% of" in line and ("Working set" in line or "processes" in line)
    ]
    assert flag_lines, md
    for line in flag_lines:
        assert "%" in line
        assert " GB" not in line


def test_json_deterministic() -> None:
    """render_mcm_json is byte-identical on re-run, newline-terminated, and free
    of raw non-ASCII control bytes (ensure_ascii)."""
    analysis = _analysis()
    a = render_mcm_json(analysis)
    b = render_mcm_json(analysis)
    assert a == b
    assert a.endswith("\n")
    assert a.isascii()


def test_json_empty_case() -> None:
    """An empty analysis serialises to a valid, deterministic JSON document."""
    out = render_mcm_json(McmAnalysis(episodes=()))
    assert out.endswith("\n")
    assert '"episodes": []' in out


def test_csv_schema_and_rows(tmp_path: Path) -> None:
    """D-15/D-16: the single CSV carries the fixed header, rows in dimension order
    oid → source → sid, and every row's ``event_ids`` cell is a non-empty
    ';'-joined id list."""
    analysis = _analysis()
    path = tmp_path / "a.csv"
    write_attribution_csv(analysis, path)
    text = path.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    assert header == (
        "episode_id,dimension,key,granted_bytes,granted_mb,request_count,event_ids"
    )
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "expected attribution rows for the multi-SID fixture"
    dims = [r["dimension"] for r in rows]
    # Dimension blocks appear in oid → source → sid order (already sorted within).
    assert dims == sorted(dims, key=["oid", "source", "sid"].index)
    assert {"oid", "source", "sid"} >= set(dims)
    for r in rows:
        assert r["event_ids"], r
        for eid in r["event_ids"].split(";"):
            assert eid, r
        assert int(r["granted_bytes"]) >= 0
        assert r["episode_id"]


def test_csv_empty_case(tmp_path: Path) -> None:
    """An empty analysis writes a header-only CSV, never crashes (D-15)."""
    path = tmp_path / "empty.csv"
    write_attribution_csv(McmAnalysis(episodes=()), path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("episode_id,dimension,key")
    assert len(lines) == 1


def test_csv_deterministic(tmp_path: Path) -> None:
    """Two writes of the same analysis produce byte-identical CSV."""
    analysis = _analysis()
    p1 = tmp_path / "1.csv"
    p2 = tmp_path / "2.csv"
    write_attribution_csv(analysis, p1)
    write_attribution_csv(analysis, p2)
    assert p1.read_bytes() == p2.read_bytes()
