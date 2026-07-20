"""Renderer + CSV goldens for the perfmon correlation bundle (PERF-06, Plan 13-05).

Pins the executable contract for ``sift.render.perfmon_report``:
``render_perfmon_markdown`` (D-19 computed figures with citations, D-20 the
honest empty case), ``render_perfmon_json`` (D-21 canonical, ASCII-safe) and
``write_perfmon_trend_csv`` (D-18 one row per counter per episode, plus the
formula-injection guard the header-derived counter names require).

``PerfmonAnalysis`` values are constructed directly — the models are frozen and
cheap to build, which keeps the renderer suite independent of ingest. No
network, no ``input()`` — the conftest guards are autouse.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sift.pipeline.perfmon import (
    CounterTrend,
    PerfmonAnalysis,
    PerfmonHazard,
    TrendGroup,
)
from sift.render.perfmon_report import (
    PERFMON_CSV_HEADER,
    render_perfmon_json,
    render_perfmon_markdown,
    write_perfmon_trend_csv,
)

# A Unicode format (category Cf) code point — written as an escape, never as a
# raw byte — that ``sanitise`` (via ``_field``) must strip from the report.
_BIDI_OVERRIDE = "\u202e"


def _trend(
    counter: str = "Memory\\Available MBytes",
    *,
    at_denial: float | None = 1.5,
    at_denial_event_id: str | None = "aaaa1111",
    slope_per_second: float | None = 0.25,
    peak: float | None = 9.75,
    peak_event_id: str | None = "bbbb2222",
    sample_count: int = 4,
    excluded_samples: int = 0,
) -> CounterTrend:
    return CounterTrend(
        counter=counter,
        at_denial=at_denial,
        at_denial_event_id=at_denial_event_id,
        slope_per_second=slope_per_second,
        peak=peak,
        peak_event_id=peak_event_id,
        sample_count=sample_count,
        excluded_samples=excluded_samples,
    )


def _group(
    *,
    scope: str = "episode",
    key: str = "denial00",
    label: str = "60 minutes before the denial",
    counters: tuple[CounterTrend, ...] = (),
    hazards: tuple[PerfmonHazard, ...] = (),
) -> TrendGroup:
    return TrendGroup(
        scope=scope,
        key=key,
        label=label,
        start_ts="2026-01-02T03:04:05Z",
        end_ts="2026-01-02T04:04:05Z",
        boundary_event_ids=("bnd11111", "bnd22222"),
        sample_count=120,
        counters=counters,
        hazards=hazards,
    )


def _hazard(value: float | None = 3.5) -> PerfmonHazard:
    return PerfmonHazard(
        dimension="non_overlap",
        severity="warn",
        message="The perfmon capture does not overlap the denial window.",
        event_ids=("haz11111",),
        value=value,
    )


# --------------------------------------------------------------------------- #
# Markdown (Task 1)
# --------------------------------------------------------------------------- #


def test_markdown_renders_group_sections() -> None:
    """Every counter's figures appear WITH the event_ids they were derived from."""
    counters = (
        _trend("Memory\\Available MBytes"),
        _trend(
            "Process(MSTRSvr)\\Working Set",
            at_denial_event_id="cccc3333",
            peak_event_id="dddd4444",
        ),
    )
    analysis = PerfmonAnalysis(
        groups=(_group(counters=counters, hazards=(_hazard(),)),)
    )
    out = render_perfmon_markdown(analysis)

    assert "60 minutes before the denial" in out
    assert "2026-01-02T03:04:05Z" in out
    assert "2026-01-02T04:04:05Z" in out
    for t in counters:
        assert t.at_denial_event_id is not None
        assert t.peak_event_id is not None
        assert t.at_denial_event_id in out
        assert t.peak_event_id in out
    # The dimension reaches the cell Markdown-escaped (``non\_overlap``) — proof
    # it went through ``_field`` rather than being interpolated raw.
    assert "does not overlap the denial window" in out
    assert "haz11111" in out


def test_markdown_none_figures_render_as_dash() -> None:
    """A single-sample lead-up has no slope; that renders as — not 0 and not None."""
    analysis = PerfmonAnalysis(
        groups=(
            _group(
                counters=(
                    _trend(slope_per_second=None, peak=None, peak_event_id=None),
                ),
                hazards=(_hazard(value=None),),
            ),
        )
    )
    out = render_perfmon_markdown(analysis)

    assert "—" in out
    assert "None" not in out
    assert "nan" not in out


def test_markdown_empty_analysis_states_full_range() -> None:
    """D-20: no episodes must never imply a correlation that was not performed."""
    out = render_perfmon_markdown(PerfmonAnalysis(groups=()))

    assert "full sample range" in out
    assert "no mcm denial episodes were detected" in out.lower()
    assert "| --- |" not in out


def test_markdown_empty_hazards_line() -> None:
    """An empty hazard set gets an explicit line, never a bare heading."""
    analysis = PerfmonAnalysis(groups=(_group(counters=(_trend(),), hazards=()),))
    out = render_perfmon_markdown(analysis)

    assert "_No correlation hazards raised._" in out


def test_markdown_cells_pass_through_field() -> None:
    """T-13-MDESC: a hostile counter name cannot reach the operator's terminal."""
    hostile = f"Memory{_BIDI_OVERRIDE}\\Hostile"
    analysis = PerfmonAnalysis(groups=(_group(counters=(_trend(hostile),)),))
    out = render_perfmon_markdown(analysis)

    assert _BIDI_OVERRIDE not in out
    assert "Hostile" in out


# --------------------------------------------------------------------------- #
# JSON (Task 2)
# --------------------------------------------------------------------------- #


def _json_analysis(counter: str = "Memory\\Available MBytes") -> PerfmonAnalysis:
    return PerfmonAnalysis(
        groups=(
            _group(
                counters=(_trend(counter),),
                hazards=(_hazard(), _hazard(value=None)),
            ),
        ),
    )


def test_json_is_key_sorted_and_newline_terminated() -> None:
    """D-21: sort_keys + a single trailing newline make the artefact re-runnable."""
    out = render_perfmon_json(_json_analysis())

    assert out.endswith("\n")
    assert not out.endswith("\n\n")
    body = out[:-1]
    reserialised = json.dumps(
        json.loads(body), sort_keys=True, ensure_ascii=True, indent=2
    )
    assert reserialised == body


def test_json_is_pure_ascii() -> None:
    """T-13-JSONESC: no raw C1/Cf byte survives into the JSON artefact."""
    out = render_perfmon_json(_json_analysis(f"Memory{_BIDI_OVERRIDE}\\Hostile"))

    out.encode("ascii")  # raises UnicodeEncodeError if a raw byte survived
    assert _BIDI_OVERRIDE not in out
    assert "\\u202e" in out


def test_json_round_trips_through_loads() -> None:
    """T-13-JSONNAN: no bare NaN/Infinity token can reach a downstream parser."""
    out = render_perfmon_json(_json_analysis())

    assert json.loads(out)
    assert "NaN" not in out
    assert "Infinity" not in out


def test_json_byte_identical_on_repeat() -> None:
    analysis = _json_analysis()

    assert render_perfmon_json(analysis) == render_perfmon_json(analysis)


# --------------------------------------------------------------------------- #
# CSV (Task 3)
# --------------------------------------------------------------------------- #


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def test_csv_row_per_counter_per_group(tmp_path: Path) -> None:
    """D-18: one row per counter per episode, and byte-identical on re-run."""
    analysis = PerfmonAnalysis(
        groups=(
            _group(key="denial00", counters=(_trend("A"), _trend("B"))),
            _group(scope="file", key="perf.csv", counters=(_trend("C"),)),
        )
    )
    first = tmp_path / "one.csv"
    second = tmp_path / "two.csv"
    write_perfmon_trend_csv(analysis, first)
    write_perfmon_trend_csv(analysis, second)

    rows = _read_csv(first)
    assert rows[0] == list(PERFMON_CSV_HEADER)
    assert len(rows) - 1 == sum(len(g.counters) for g in analysis.groups) == 3
    assert first.read_bytes() == second.read_bytes()


def test_csv_header_only_when_no_groups(tmp_path: Path) -> None:
    """The header is written before any iteration, so an empty case still parses."""
    path = tmp_path / "empty.csv"
    write_perfmon_trend_csv(PerfmonAnalysis(groups=()), path)

    assert _read_csv(path) == [list(PERFMON_CSV_HEADER)]


def test_csv_formula_guard(tmp_path: Path) -> None:
    """T-13-CSVINJ + WR-05: a trigger is neutralised even behind leading whitespace.

    A spreadsheet strips leading whitespace before deciding a cell is a formula,
    so the guard must test the first SIGNIFICANT character, not literally the
    first character. ``" =cmd"`` and ``"\\t=cmd"`` are therefore just as
    dangerous as a bare leading ``=``.
    """
    triggers = ("=", "+", "-", "@")
    names = [f"{t}cmd|'/c calc'!A0" for t in triggers]
    names += [f" {t}cmd" for t in triggers]  # leading space
    names += [f"\t{t}cmd" for t in triggers]  # leading tab
    for name in names:
        path = tmp_path / "guard.csv"
        write_perfmon_trend_csv(
            PerfmonAnalysis(groups=(_group(counters=(_trend(name),)),)),
            path,
        )
        counter_cell = _read_csv(path)[1][PERFMON_CSV_HEADER.index("counter")]
        assert counter_cell == f"'{name}", f"{name!r} not neutralised"


def test_csv_leading_whitespace_then_ordinary_is_not_quoted(tmp_path: Path) -> None:
    """WR-05: whitespace before an ORDINARY character is not a formula, left as-is."""
    name = "\tData(MB)"
    path = tmp_path / "ws.csv"
    write_perfmon_trend_csv(
        PerfmonAnalysis(groups=(_group(counters=(_trend(name),)),)), path
    )
    assert _read_csv(path)[1][PERFMON_CSV_HEADER.index("counter")] == name


def test_csv_strips_terminal_driving_bytes(tmp_path: Path) -> None:
    """CR-02: no raw C1/bidi byte from a counter name reaches the trend CSV.

    The trend CSV was the only shipped artefact that did not sanitise its
    attacker-influenceable counter names, so a single-byte CSI (0x9B) or a bidi
    override could drive the terminal of an operator who ``cat``s the bundle —
    exactly the threat T-13-MDESC/T-13-JSONESC closed for Markdown and JSON.
    """
    csi = "\x9b"
    name = f"Memory{_BIDI_OVERRIDE}{csi}\\Hostile"
    path = tmp_path / "sanitise.csv"
    write_perfmon_trend_csv(
        PerfmonAnalysis(groups=(_group(counters=(_trend(name),)),)), path
    )
    text = path.read_text(encoding="utf-8")
    assert _BIDI_OVERRIDE not in text
    assert csi not in text
    assert "Hostile" in text


def test_csv_formula_guard_leaves_ordinary_names_unchanged(tmp_path: Path) -> None:
    """The guard is not over-broad: an ordinary name round-trips byte-for-byte."""
    name = "Process(MSTRSvr)\\Working Set"
    path = tmp_path / "ordinary.csv"
    write_perfmon_trend_csv(
        PerfmonAnalysis(groups=(_group(counters=(_trend(name),)),)), path
    )

    assert _read_csv(path)[1][PERFMON_CSV_HEADER.index("counter")] == name


def test_csv_none_figures_are_empty_cells(tmp_path: Path) -> None:
    """An uncomputable figure is an empty cell, never the string ``None``."""
    path = tmp_path / "none.csv"
    write_perfmon_trend_csv(
        PerfmonAnalysis(
            groups=(
                _group(
                    counters=(
                        _trend(slope_per_second=None, peak=None, peak_event_id=None),
                    )
                ),
            )
        ),
        path,
    )

    row = _read_csv(path)[1]
    assert row[PERFMON_CSV_HEADER.index("slope_per_second")] == ""
    assert row[PERFMON_CSV_HEADER.index("peak")] == ""
    assert b"None" not in path.read_bytes()


def test_csv_event_ids_semicolon_joined(tmp_path: Path) -> None:
    """A multi-id cell uses ';' so csv.writer adds no comma-quoting."""
    path = tmp_path / "ids.csv"
    write_perfmon_trend_csv(
        PerfmonAnalysis(groups=(_group(counters=(_trend(),)),)), path
    )

    cell = _read_csv(path)[1][PERFMON_CSV_HEADER.index("boundary_event_ids")]
    assert cell == "bnd11111;bnd22222"
    assert '"' not in path.read_text(encoding="utf-8")
