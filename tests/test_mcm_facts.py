"""Unit tests for the deterministic MCM fact renderer (MCM-06, Plan 11-01).

``render_mcm_facts(analyse_mcm(...))`` is the model-free, byte-identical-on-re-run
source of truth for every MCM figure the Wave-2 splice surfaces. These tests pin:

- the figures come verbatim from ``analyse_mcm`` (``DiagnosticFlag.value_pct``) —
  the renderer never re-derives a percentage (D-11 / criterion 2);
- the returned id set is exactly the set of ``[evt:<id>]`` tokens printed in the
  block — no id the model was not shown leaks in (criterion 1 provenance);
- top-5 per attribution dimension (D-19), in the analyser's granted-desc order;
- an empty analysis renders to ``("", set())`` so the downstream strip is
  residue-free (criterion 5);
- every log-derived value is routed through ``render._util.sanitise`` (T-11-01).

The fixture-ingest helper mirrors ``tests/test_mcm.py``; synthetic-analysis
builders let the top-5 / empty / sanitise cases stay tiny and deterministic. No
network, no ``input()`` — the autouse conftest guards apply.
"""

from __future__ import annotations

import re
from pathlib import Path

from sift.adapters.dsserrors import DsserrorsAdapter
from sift.config import McmThresholdsConfig
from sift.pipeline.mcm import (
    Attribution,
    AttributionRow,
    DiagnosticFlag,
    EpisodeAnalysis,
    EpisodeWindow,
    McmAnalysis,
    McmEpisode,
    MemoryBreakdown,
    analyse_mcm,
)
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.render._util import sanitise
from sift.store import CaseStore

FIXTURES = Path(__file__).parent / "fixtures" / "mcm"

_EVT_TOKEN_RE = re.compile(r"\[evt:([0-9a-f]+)\]")


def _analysis_from_fixture(
    tmp_path: Path, rel: str = "hartford_deny_slice.log"
) -> McmAnalysis:
    """Ingest the Hartford slice through the real adapter + store, then analyse.

    Mirrors ``tests/test_mcm.py::_episodes_from_fixture`` — parse via a fresh
    ``DsserrorsAdapter``, insert into a temp ``case.db``, and run the single
    ``analyse_mcm`` entry over the canonically-ordered stored events.
    """
    adapter = DsserrorsAdapter()
    adapter.input_root = FIXTURES
    events = list(adapter.parse(FIXTURES / rel, "case1"))
    store = CaseStore(tmp_path / "case.db")
    store.insert_events(events)
    return analyse_mcm(store.query_events(), McmThresholdsConfig())


def _row(dimension: str, key: str, granted: int, eid: str) -> AttributionRow:
    return AttributionRow(
        dimension=dimension,
        key=key,
        granted_bytes=granted,
        request_count=1,
        event_ids=(eid,),
    )


def _flag(dimension: str, severity: str, pct: float, msg: str, eid: str) -> DiagnosticFlag:
    return DiagnosticFlag(
        dimension=dimension,
        severity=severity,
        value_pct=pct,
        message=msg,
        event_ids=(eid,),
    )


def _analysis(
    *,
    flags: tuple[DiagnosticFlag, ...] = (),
    by_source: tuple[AttributionRow, ...] = (),
    denial_id: str = "d0d0d0d0d0d0d0d0",
    denial_ts: str | None = "2026-04-07T12:39:47",
    label: str = "AvailableMCM below a quarter of the high-water mark",
) -> McmAnalysis:
    """A minimal single-episode ``McmAnalysis`` for the synthetic cases."""
    episode = McmEpisode(
        denial_event_id=denial_id,
        denial_ts=denial_ts,
        recovery=None,
        open_truncated=True,
        fragmented=False,
        event_ids=(denial_id,),
        lifecycle=(),
        breakdown=MemoryBreakdown(raw_map={}, current_memory_info={}, mcm_settings={}),
        hwm_bytes=None,
        avail_timeline=(),
    )
    window = EpisodeWindow(
        threshold_pct=25,
        start_event_id=None,
        hwm_bytes=None,
        request_count=0,
        label=label,
    )
    attribution = Attribution(
        by_oid=(), by_source=by_source, by_sid=(), unmatched_event_ids=()
    )
    return McmAnalysis(
        episodes=(
            EpisodeAnalysis(
                episode=episode, window=window, flags=flags, attribution=attribution
            ),
        )
    )


def test_render_surfaces_analyser_figures_and_denial_line(tmp_path: Path) -> None:
    """A non-empty analysis yields a block whose working-set percentage equals the
    flag's ``value_pct`` verbatim and whose summary cites the denial event."""
    analysis = _analysis_from_fixture(tmp_path)
    block, ids = render_mcm_facts(analysis)

    assert block != ""
    ea = analysis.episodes[0]
    working_set = next(f for f in ea.flags if "working_set" in f.dimension)
    # The figure is the analyser's value_pct, formatted to 1 dp — not re-derived.
    assert f"{working_set.value_pct:.1f}%" in block
    # The episode summary line cites the denial event.
    assert f"[evt:{ea.episode.denial_event_id}]" in block
    assert ea.episode.denial_event_id in ids


def test_id_set_equals_printed_evt_tokens(tmp_path: Path) -> None:
    """The returned id set is exactly the ids printed as ``[evt:<id>]`` tokens —
    the denial id ∪ every printed flag/attribution-row id, and nothing more."""
    analysis = _analysis_from_fixture(tmp_path)
    block, ids = render_mcm_facts(analysis)

    printed = set(_EVT_TOKEN_RE.findall(block))
    assert ids == printed
    assert analysis.episodes[0].episode.denial_event_id in ids


def test_top_5_per_dimension_in_analyser_order() -> None:
    """No more than 5 rows per dimension appear even when the analyser has more,
    and they follow the analyser's granted-desc slice order (plain ``[:5]``)."""
    rows = tuple(
        _row("source", f"Source-{chr(ord('A') + i)}", 1000 * (7 - i), f"{i:016x}")
        for i in range(7)
    )
    block, _ = render_mcm_facts(_analysis(by_source=rows))

    source_lines = [line for line in block.splitlines() if "source=" in line]
    assert len(source_lines) == 5
    printed_keys = [line.split("source=", 1)[1].split(" granted", 1)[0] for line in source_lines]
    assert printed_keys == [f"Source-{chr(ord('A') + i)}" for i in range(5)]
    # The dropped rows never appear.
    assert "Source-F" not in block
    assert "Source-G" not in block


def test_empty_analysis_renders_to_empty_pair() -> None:
    """episodes=() renders to exactly ("", set()) so the splice strips clean."""
    assert render_mcm_facts(McmAnalysis(episodes=())) == ("", set())


def test_log_derived_values_are_sanitised() -> None:
    """A control-char-laden attribution key / flag message is sanitised in the
    output (the value is passed through ``sanitise`` before interpolation)."""
    hostile_key = "obj\x1b[31m\x07evil"
    hostile_msg = "working set\x1b[0m breached"
    analysis = _analysis(
        flags=(_flag("working_set_pct_virtual", "critical", 65.4, hostile_msg, "0" * 16),),
        by_source=(_row("source", hostile_key, 2048, "1" * 16),),
    )
    block, _ = render_mcm_facts(analysis)

    assert "\x1b" not in block
    assert "\x07" not in block
    assert sanitise(hostile_key) in block
    assert sanitise(hostile_msg) in block
