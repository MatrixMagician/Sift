"""MCM forensics-bundle renderer + CSV export (MCM-05, Plan 10-04).

Three pure functions over the Plan-03 ``McmAnalysis``:

- ``render_mcm_markdown`` — a deterministic, timeline-first (D-11) human report:
  per episode the lifecycle timeline, then the graded diagnostic flags, then the
  denial-time memory breakdown, then the three attribution tables (by OID, by
  request source, by SID). Every log-sourced field (SID/OID keys, ``Source=``
  values, lifecycle text, flag messages) is routed through the shared
  ``markdown._field`` escaping so hostile DSSErrors bytes cannot inject Markdown
  or HTML structure into the report or the PDF-capable HTML path (T-10-12). Flags
  and the window are framed as percentages, never an absolute-GB headline
  (T-10-16); absolute figures live only in the breakdown/attribution tables and
  the CSV (RESEARCH Deliverable 3).
- ``render_mcm_json`` — the canonical ``model_dump`` serialisation, key-sorted,
  ``ensure_ascii`` (so no raw C1/Cf terminal-injection byte survives) and
  newline-terminated — byte-identical on re-run (the ``json_out`` precedent).
- ``write_attribution_csv`` — a single dimension-tagged CSV (D-15) via stdlib
  ``csv.writer`` (never a manual join, so embedded delimiters/quotes are quoted
  correctly — T-10-13); every row carries its owning ``event_id``s (D-16).

Pure ``McmAnalysis -> str`` / ``-> file``: no store re-read, no recompute, no
network, no LLM. The only I/O is the CSV file write. Reuses the markdown
escaping rather than reimplementing it — the anti-injection escaping is
load-bearing, not polish.
"""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

# Reuse the load-bearing markdown escaping (sanitise + Markdown/HTML escape) —
# NOT a second implementation (RESEARCH Security V5). ``_field`` wraps
# ``render._util.sanitise``; importing it here is the sanctioned cross-module
# reuse the plan prescribes ("import them, do not reimplement escaping").
from sift.render.markdown import _field  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path

    from sift.pipeline.mcm import (
        AttributionRow,
        DiagnosticFlag,
        EpisodeAnalysis,
        LifecycleSignal,
        McmAnalysis,
        MemoryBreakdown,
    )

CSV_HEADER: tuple[str, ...] = (
    "episode_id",
    "dimension",
    "key",
    "granted_bytes",
    "granted_mb",
    "request_count",
    "event_ids",
)

# The denial-time breakdown rows surfaced in the report, in a fixed British-
# English order. Each entry is (label, accessor-name); an absent (None) figure
# is simply skipped (D-03 — never a fabricated zero).
_BREAKDOWN_ROWS: tuple[tuple[str, str], ...] = (
    ("Total system physical memory", "physical_total"),
    ("IServer in-use physical memory", "iserver_physical_mb"),
    ("Other processes' physical memory", "other_processes_mb"),
    ("IServer in-use virtual memory", "iserver_virtual_mb"),
    ("Cube caches in memory", "cube_caches_mb"),
    ("Cube growth incl. indexes", "cube_growth_index_mb"),
    ("MMF virtual memory size", "mmf_mb"),
    ("Working set cache RAM usage", "working_set_mb"),
    ("SmartHeap unused pool", "smartheap_unused_pool_mb"),
    ("Other IServer memory", "other_memory_mb"),
)


def _mb_bytes(granted_bytes: int) -> float:
    """Convert bytes to megabytes, rounded deterministically to 3 dp."""
    return round(granted_bytes / 1024**2, 3)


def _lifecycle_table(signals: tuple[LifecycleSignal, ...]) -> list[str]:
    lines = ["### Lifecycle timeline", ""]
    if not signals:
        lines.append("_No lifecycle signals recorded._")
        lines.append("")
        return lines
    lines.append("| Time | Signal | Detail |")
    lines.append("| --- | --- | --- |")
    for s in signals:
        ts = _field(s.ts) if s.ts else "—"
        lines.append(f"| {ts} | {_field(s.kind)} | {_field(s.text)} |")
    lines.append("")
    return lines


def _flags_table(flags: tuple[DiagnosticFlag, ...]) -> list[str]:
    lines = ["### Diagnostic flags", ""]
    if not flags:
        lines.append("_No diagnostic flags raised._")
        lines.append("")
        return lines
    lines.append("| Dimension | Severity | Value | Detail |")
    lines.append("| --- | --- | --- | --- |")
    for f in flags:
        # value_pct is ALWAYS a percentage (the machine-independence lock) — never
        # an absolute GB headline (T-10-16). message carries the % inline already.
        lines.append(
            f"| {_field(f.dimension)} | {_field(f.severity)} "
            f"| {f.value_pct:.1f}% | {_field(f.message)} |"
        )
    lines.append("")
    return lines


def _breakdown_table(breakdown: MemoryBreakdown) -> list[str]:
    lines = ["### Denial-time memory breakdown", ""]
    rows: list[tuple[str, float]] = []
    for label, attr in _BREAKDOWN_ROWS:
        value = getattr(breakdown, attr)
        if value is not None:
            rows.append((label, value))
    if not rows:
        lines.append("_No denial-time memory breakdown captured._")
        lines.append("")
        return lines
    lines.append("| Metric | Value (MB) |")
    lines.append("| --- | --- |")
    for label, value in rows:
        lines.append(f"| {_field(label)} | {value:,.1f} |")
    lines.append("")
    return lines


def _attribution_table(
    heading: str, rows: tuple[AttributionRow, ...], *, fan_out: bool = False
) -> list[str]:
    lines = [heading, ""]
    if not rows:
        lines.append("_No attributed lead-up grants._")
        lines.append("")
        return lines
    if fan_out:
        lines.append("| Key | Granted (MB) | Requests | Sessions | Event IDs |")
        lines.append("| --- | --- | --- | --- | --- |")
    else:
        lines.append("| Key | Granted (MB) | Requests | Event IDs |")
        lines.append("| --- | --- | --- | --- |")
    for r in rows:
        # event_ids are regex-gated hex, but pass through _field defensively so a
        # tampered id can never break the cell (mirrors markdown.py appendix).
        eids = _field(", ".join(r.event_ids))
        cells = [
            _field(r.key),
            f"{_mb_bytes(r.granted_bytes):,.1f}",
            str(r.request_count),
        ]
        if fan_out:
            cells.append(str(len(r.sids)))
        cells.append(eids)
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _episode_section(index: int, ea: EpisodeAnalysis) -> list[str]:
    ep = ea.episode
    denial = _field(ep.denial_ts) if ep.denial_ts else _field(ep.denial_event_id)
    lines = [f"## Episode {index}: denial at {denial}", ""]
    if ep.open_truncated:
        lines.append("> **Open/truncated** — the episode never recovered "
                     "(no `State=normal`) within the captured log.")
        lines.append("")
    if ep.fragmented:
        lines.append("> **Fragmented** — the denial-time detail block spans a "
                     "log-file boundary.")
        lines.append("")
    # Window framed as a percentage of HWM; any GB is a parenthetical human aid
    # inside the label, never the threshold itself (T-10-16).
    lines.append(
        f"- Lead-up window: {_field(ea.window.label)} "
        f"({ea.window.request_count} requests)"
    )
    lines.append("")
    lines.extend(_lifecycle_table(ep.lifecycle))
    lines.extend(_flags_table(ea.flags))
    lines.extend(_breakdown_table(ep.breakdown))
    lines.extend(
        _attribution_table(
            "### Attribution by object (OID)", ea.attribution.by_oid, fan_out=True
        )
    )
    lines.extend(
        _attribution_table(
            "### Attribution by request source", ea.attribution.by_source
        )
    )
    lines.extend(
        _attribution_table("### Attribution by session (SID)", ea.attribution.by_sid)
    )
    return lines


def render_mcm_markdown(analysis: McmAnalysis) -> str:
    """Render the deterministic, timeline-first MCM report (D-11, MCM-05)."""
    out: list[str] = ["# MCM Denial Analysis", ""]
    count = len(analysis.episodes)
    if count == 0:
        out.append("_No MCM denial episodes detected._")
        out.append("")
        return "\n".join(out)
    plural = "episode" if count == 1 else "episodes"
    out.append(f"_{count} denial {plural} detected._")
    out.append("")
    for i, ea in enumerate(analysis.episodes, start=1):
        out.extend(_episode_section(i, ea))
    return "\n".join(out)


def render_mcm_json(analysis: McmAnalysis) -> str:
    """Serialise the analysis to canonical, key-sorted, ASCII-safe JSON.

    ``ensure_ascii=True`` backslash-u-escapes every non-ASCII code point so the
    JSON report carries no raw C1/Cf terminal-injection byte (the ``json_out``
    precedent); ``sort_keys`` + trailing newline make it byte-identical on re-run.
    """
    doc = analysis.model_dump(mode="json")
    return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"


def write_attribution_csv(analysis: McmAnalysis, path: Path) -> None:
    """Write the single dimension-tagged attribution CSV (D-15/D-16).

    stdlib ``csv.writer(newline="")`` quotes embedded delimiters/quotes/newlines
    (T-10-13); the keys are structurally hex (SID/OID) or ``Source=`` ``[\\w:]+``
    values which cannot begin with a spreadsheet formula trigger, so the quoting
    is the complete mitigation — never a manual join. Rows are emitted per episode
    in dimension order oid → source → sid, each already sorted; ``event_ids`` is
    ';'-joined (a semicolon avoids CSV comma-quoting) and never empty (D-16).
    """
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for ea in analysis.episodes:
            episode_id = ea.episode.denial_event_id
            for rows in (
                ea.attribution.by_oid,
                ea.attribution.by_source,
                ea.attribution.by_sid,
            ):
                for r in rows:
                    writer.writerow(
                        (
                            episode_id,
                            r.dimension,
                            r.key,
                            r.granted_bytes,
                            _mb_bytes(r.granted_bytes),
                            r.request_count,
                            ";".join(r.event_ids),
                        )
                    )
