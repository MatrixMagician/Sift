"""Perfmon correlation renderer + trend CSV export (PERF-06, Plan 13-05).

Three pure functions over the Plan 13-02 ``PerfmonAnalysis``:

- ``render_perfmon_markdown`` — the human report: per correlated span the window
  label and its resolved timestamp range, then a per-counter table of the
  computed figures (at-denial value, slope per second, peak) each shown with the
  ``event_id`` it was derived from, then the graded correlation hazards (D-19).
  The report carries computed figures only and never a raw sample series — the
  samples live in the case store and stay citable via ``sift show events``. With
  no MCM denial episodes the report says so plainly rather than implying a
  correlation that was not performed (D-20). Every dynamic cell is routed
  through the shared ``markdown._field`` escaping, so a counter name carrying a
  C1 CSI byte or a bidi override cannot drive the operator's terminal
  (T-13-MDESC).
- ``render_perfmon_json`` — the canonical ``model_dump`` serialisation,
  key-sorted, ``ensure_ascii`` (so no raw C1/Cf terminal-injection byte survives
  — T-13-JSONESC) and newline-terminated, hence byte-identical on re-run (D-21).
- ``write_perfmon_trend_csv`` — the summary trend CSV, one row per counter per
  span (D-18), via stdlib ``csv.writer``. Every string cell passes through
  ``_csv_safe``, which first ``sanitise``s away terminal-driving C1/bidi bytes
  (T-13-MDESC/JSONESC — CR-02) and then neutralises spreadsheet formula triggers
  (T-13-CSVINJ).

Pure ``PerfmonAnalysis -> str`` / ``-> file``: no store re-read, no recompute,
no network, no LLM. The only I/O is the CSV file write. Reuses the markdown
escaping rather than reimplementing it — the anti-injection escaping is
load-bearing, not polish.
"""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

# Reuse the load-bearing markdown escaping (sanitise + Markdown/HTML escape) —
# NOT a second implementation. ``_field`` wraps ``render._util.sanitise``;
# importing it here is the sanctioned cross-module reuse (as ``mcm_report``
# does), never a reimplementation.
from sift.render._util import sanitise
from sift.render.markdown import _field  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path

    from sift.pipeline.perfmon import (
        CounterTrend,
        PerfmonAnalysis,
        PerfmonHazard,
        TrendGroup,
    )

# The house spelling for an absent figure — never ``None``, and never a
# fabricated ``0`` which a reader would mistake for a measurement (D-03).
_ABSENT = "—"

PERFMON_CSV_HEADER: tuple[str, ...] = (
    "group_scope",
    "group_key",
    "group_label",
    "counter",
    "at_denial",
    "at_denial_event_id",
    "slope_per_second",
    "peak",
    "peak_event_id",
    "sample_count",
    "excluded_samples",
    "boundary_event_ids",
)

# The characters a spreadsheet treats as the start of a formula when it opens a
# CSV. Only the four printable triggers: leading whitespace is handled by
# testing the first SIGNIFICANT character in ``_csv_safe`` (WR-05) rather than
# by smuggling whitespace into the trigger set, where a naive first-character
# check would still miss ``" =cmd"`` (a space, then a real trigger).
_FORMULA_TRIGGERS = ("=", "+", "-", "@")

# D-20: an analysis with no groups must state both facts — that no denial
# episode was found, and what was (or was not) computed instead — so the report
# never implies a correlation it did not perform.
_NO_EPISODES = (
    "_No MCM denial episodes were detected. Where perfmon samples were present "
    "the trend was computed over each file's full sample range rather than a "
    "denial window; this analysis resolved no spans at all, so no correlation "
    "was performed._"
)


def _figure(value: float | None) -> str:
    """Render a pre-rounded figure, or the absent marker.

    Deliberately ``str(value)`` and not a format spec: the correlator rounds at
    source (3 dp for values, ``SLOPE_DP`` for slopes), and re-rounding here
    would break that round-at-source discipline and could show two different
    numbers for the same stored figure in the report and the CSV.
    """
    return _ABSENT if value is None else str(value)


def _citations(trend: CounterTrend) -> str:
    """The event_ids a counter's figures were derived from.

    A figure is never presented without its citation — a number the reader
    cannot trace back to a stored sample breaks the computed-and-citable
    contract the whole report rests on.
    """
    ids = [i for i in (trend.at_denial_event_id, trend.peak_event_id) if i]
    return _field(", ".join(ids)) if ids else _ABSENT


def _counter_table(counters: tuple[CounterTrend, ...]) -> list[str]:
    lines = ["### Counter trends", ""]
    if not counters:
        lines.append("_No counters carried samples in this span._")
        lines.append("")
        return lines
    lines.append(
        "| Counter | At denial | Slope /s | Peak | Citations | Samples | Excluded |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for t in counters:
        lines.append(
            f"| {_field(t.counter)} | {_figure(t.at_denial)} "
            f"| {_figure(t.slope_per_second)} | {_figure(t.peak)} "
            f"| {_citations(t)} | {t.sample_count} | {t.excluded_samples} |"
        )
    lines.append("")
    return lines


def _hazard_table(
    hazards: tuple[PerfmonHazard, ...], heading: str = "### Correlation hazards"
) -> list[str]:
    lines = [heading, ""]
    if not hazards:
        lines.append("_No correlation hazards raised._")
        lines.append("")
        return lines
    lines.append("| Dimension | Severity | Value | Detail | Event IDs |")
    lines.append("| --- | --- | --- | --- | --- |")
    for h in hazards:
        # ``value`` is float | None (unlike mcm's always-present ``value_pct``),
        # because a structural hazard such as a non-overlapping capture has no
        # triggering figure at all.
        lines.append(
            f"| {_field(h.dimension)} | {_field(h.severity)} "
            f"| {_figure(h.value)} | {_field(h.message)} "
            f"| {_field(', '.join(h.event_ids))} |"
        )
    lines.append("")
    return lines


def _group_section(group: TrendGroup) -> list[str]:
    scope = "Episode" if group.scope == "episode" else "File"
    lines = [f"## {scope}: {_field(group.key)}", ""]
    start = _field(group.start_ts) if group.start_ts else _ABSENT
    end = _field(group.end_ts) if group.end_ts else _ABSENT
    lines.append(f"- Window: {_field(group.label)}")
    lines.append(f"- Resolved span: {start} → {end}")
    lines.append(f"- Span boundaries: {_field(', '.join(group.boundary_event_ids))}")
    lines.append(f"- Samples in span: {group.sample_count}")
    lines.append("")
    lines.extend(_counter_table(group.counters))
    lines.extend(_hazard_table(group.hazards))
    return lines


def render_perfmon_markdown(analysis: PerfmonAnalysis) -> str:
    """Render the deterministic perfmon correlation report (D-19/D-20, PERF-06)."""
    out: list[str] = ["# Perfmon Correlation", ""]
    if not analysis.groups:
        out.append(_NO_EPISODES)
        out.append("")
        return "\n".join(out)
    count = len(analysis.groups)
    plural = "span" if count == 1 else "spans"
    out.append(f"_{count} correlated {plural}._")
    out.append("")
    for group in analysis.groups:
        out.extend(_group_section(group))
    return "\n".join(out)


def render_perfmon_json(analysis: PerfmonAnalysis) -> str:
    """Serialise the analysis to canonical, key-sorted, ASCII-safe JSON (D-21).

    ``ensure_ascii=True`` backslash-u-escapes every non-ASCII code point so the
    JSON report carries no raw C1/Cf terminal-injection byte (T-13-JSONESC) —
    a security control, not a cosmetic choice; ``sort_keys`` plus the trailing
    newline are what make the artefact byte-identical on re-run.

    No bare ``NaN``/``Infinity`` token can appear (T-13-JSONNAN): the
    correlator's ``_numeric`` guarantees every stored figure is finite or
    ``None``, so ``json.dumps``' non-standard float path is never reached.
    """
    doc = analysis.model_dump(mode="json")
    return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"


def _csv_safe(value: str) -> str:
    """Neutralise a spreadsheet formula trigger at the start of a CSV cell.

    Three facts make this guard necessary and non-redundant (T-13-CSVINJ):

    1. Perfmon counter names originate in the customer's DSSPerformanceMonitor
       CSV header and are therefore attacker-influenceable. This is exactly the
       premise that does NOT hold for ``mcm_report.write_attribution_csv``,
       whose keys are structurally hex SIDs/OIDs or ``[\\w:]+`` source values
       that cannot begin with a trigger — so that writer's quoting-suffices
       reasoning is deliberately NOT carried over here. The divergence is
       intentional, not an inconsistency.
    2. ``csv.writer`` quoting prevents delimiter and newline injection, but a
       quoted cell beginning ``=`` is still evaluated as a formula when the file
       is opened in a spreadsheet. Quoting is the wrong layer for this threat.
    3. ``render._util.sanitise`` handles a DIFFERENT threat and is composed here
       ALONGSIDE the formula guard, not instead of it (CR-02): it strips the
       control characters and Unicode-Cf code points (a single-byte CSI 0x9B, a
       bidi override) that would otherwise drive the terminal of an operator who
       ``cat``s the bundle — the same threat T-13-MDESC/T-13-JSONESC close for
       the Markdown and JSON artefacts. Every printable formula trigger passes
       through it untouched, so it cannot replace the quote-prefix.

    Only string cells are guarded. A numeric cell is written by ``csv.writer``
    from a real ``float``/``int``, so a legitimately negative figure such as a
    falling slope keeps its leading minus sign rather than being corrupted into
    text by a guard it never needed.

    Ordering is load-bearing: sanitise FIRST (strip the control bytes), then
    quote — quoting first would leave a stripped-to-empty trigger sitting behind
    the quote. The first SIGNIFICANT character is tested, not literally the first
    one: a spreadsheet strips leading whitespace before deciding a cell is a
    formula, so ``" =cmd"`` is as dangerous as a bare ``=`` (WR-05).
    """
    cleaned = sanitise(value)
    significant = cleaned.lstrip(" \t\r\n")
    return f"'{cleaned}" if significant.startswith(_FORMULA_TRIGGERS) else cleaned


def write_perfmon_trend_csv(analysis: PerfmonAnalysis, path: Path) -> None:
    """Write the summary trend CSV: one row per counter per span (D-18).

    A summary artefact of a few hundred rows, never a re-export of the stored
    samples — the samples stay in the case store and remain citable there. The
    header is written before any iteration, so an analysis with no groups still
    yields a file that parses as valid CSV. ``boundary_event_ids`` is
    ``';'``-joined (a semicolon avoids CSV comma-quoting) so each row stays
    traceable to the span it was computed over. A ``None`` figure is written as
    an empty cell, never the string ``None``.
    """
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(PERFMON_CSV_HEADER)
        for g in analysis.groups:
            boundaries = _csv_safe(";".join(g.boundary_event_ids))
            for t in g.counters:
                writer.writerow(
                    (
                        _csv_safe(g.scope),
                        _csv_safe(g.key),
                        _csv_safe(g.label),
                        _csv_safe(t.counter),
                        t.at_denial,
                        _csv_safe(t.at_denial_event_id or ""),
                        t.slope_per_second,
                        t.peak,
                        _csv_safe(t.peak_event_id or ""),
                        t.sample_count,
                        t.excluded_samples,
                        boundaries,
                    )
                )
