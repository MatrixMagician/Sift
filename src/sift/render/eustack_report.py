"""Eu-stack bundle renderer + signatures CSV export (EUS-07/08/09).

Three pure functions over ``pipeline.eustack_progression.EustackBundle``,
mirroring ``render/perfmon_report.py``'s three-function shape verbatim:

- ``render_eustack_markdown`` — the human report: the ordered dump list and
  the stated ordering basis (D-01/D-02), the role-composition figures from
  ``EustackAnalysis``, the per-pool occupancy / lock-site / dependency-wait
  tables and graded flags from ``SaturationAnalysis`` (computed on the LAST
  dump only, D-11), and the ranked signature table. Every dynamic cell is
  routed through the shared ``markdown._field`` escaping.
- ``render_eustack_json`` — the canonical ``model_dump`` serialisation,
  key-sorted, ``ensure_ascii`` and newline-terminated — byte-identical on
  re-run (D-13). No wall-clock field anywhere in the bundle.
- ``write_eustack_signatures_csv`` — exactly one CSV, one row per signature
  (D-04), via stdlib ``csv.writer``. Every string cell passes through
  ``_csv_safe`` (imported from ``render.perfmon_report``, never
  reimplemented — D-06).

Pure ``EustackBundle -> str`` / ``-> file``: no store re-read, no recompute,
no network, no LLM.
"""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

from sift.render.markdown import _field  # pyright: ignore[reportPrivateUsage]
from sift.render.perfmon_report import _csv_safe  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path

    from sift.pipeline.eustack import Role, SaturationAnalysis
    from sift.pipeline.eustack_progression import (
        EustackBundle,
        ProgressionAnalysis,
        SignatureProgression,
    )

# The house spelling for an absent figure — never None, never a fabricated 0
# (matches perfmon_report._ABSENT / D-03).
_ABSENT = "—"

EUSTACK_CSV_BASE_HEADER: tuple[str, ...] = (
    "role",
    "subsystem",
    "matched_pattern",
    "frame_index",
    "reason",
    "matched_frame",
    "leaf_frame",
    "thread_count",
)

# D-12/EUS-09: a case with no eu-stack dumps at all must state that plainly
# rather than render an empty set of tables that reads as "nothing happened"
# (mirrors perfmon_report._NO_EPISODES' house style).
_NO_DUMPS = "_No eu-stack dumps were present in this case._"


def _dumps_section(progression: ProgressionAnalysis) -> list[str]:
    lines = ["## Dumps", ""]
    lines.append(f"- Order basis: {_field(progression.order_basis)}")
    names = ", ".join(d.source_file for d in progression.dumps)
    lines.append(f"- Dumps (ordered): {_field(names)}")
    lines.append(f"- Scope: {_field(progression.scope_note)}")
    lines.append("")
    if progression.ordering_flags:
        lines.append("| Dimension | Severity | Message |")
        lines.append("| --- | --- | --- |")
        for flag in progression.ordering_flags:
            lines.append(
                f"| {_field(flag.dimension)} | {_field(flag.severity)} "
                f"| {_field(flag.message)} |"
            )
        lines.append("")
    return lines


def _role_composition_section(
    total_threads: int,
    total_signatures: int,
    threads_by_role: dict[Role, int],
    signatures_by_role: dict[Role, int],
) -> list[str]:
    lines = ["## Role composition", ""]
    lines.append(f"- Total threads: {total_threads}")
    lines.append(f"- Total signatures: {total_signatures}")
    lines.append("")
    lines.append("| Role | Threads | Signatures |")
    lines.append("| --- | --- | --- |")
    for role, count in threads_by_role.items():
        lines.append(
            f"| {_field(role)} | {count} | {signatures_by_role.get(role, 0)} |"
        )
    lines.append("")
    return lines


def _pool_table(pools: tuple[object, ...]) -> list[str]:
    lines = ["### Pool occupancy", ""]
    if not pools:
        lines.append("_No pools present._")
        lines.append("")
        return lines
    lines.append("| Subsystem | Total | Idle | Busy | Occupancy | Signatures |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for p in pools:
        subsystem = p.subsystem if p.subsystem is not None else _ABSENT  # type: ignore[attr-defined]
        lines.append(
            f"| {_field(subsystem)} | {p.total_threads} | {p.idle_threads} "  # type: ignore[attr-defined]
            f"| {p.busy_threads} | {p.occupancy} | {p.signature_count} |"  # type: ignore[attr-defined]
        )
    lines.append("")
    return lines


def _lock_table(lock_sites: tuple[object, ...], lock_finding_note: str) -> list[str]:
    lines = ["### Lock sites", ""]
    lines.append(_field(lock_finding_note))
    lines.append("")
    if not lock_sites:
        lines.append("_No lock sites observed._")
        lines.append("")
        return lines
    lines.append("| Site | Threads | Signatures |")
    lines.append("| --- | --- | --- |")
    for s in lock_sites:
        lines.append(
            f"| {_field(s.site)} | {s.thread_count} | {s.signature_count} |"  # type: ignore[attr-defined]
        )
    lines.append("")
    return lines


def _dependency_table(dependencies: tuple[object, ...]) -> list[str]:
    lines = ["### Dependency waits", ""]
    if not dependencies:
        lines.append("_No dependency waits observed._")
        lines.append("")
        return lines
    lines.append("| Subsystem | Threads | Signatures |")
    lines.append("| --- | --- | --- |")
    for d in dependencies:
        lines.append(
            f"| {_field(d.subsystem)} | {d.thread_count} | {d.signature_count} |"  # type: ignore[attr-defined]
        )
    lines.append("")
    return lines


def _flag_table(flags: tuple[object, ...]) -> list[str]:
    lines = ["### Saturation flags", ""]
    if not flags:
        lines.append("_No saturation flags raised._")
        lines.append("")
        return lines
    lines.append("| Dimension | Severity | Value | Warn | Critical | Message |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for f in flags:
        lines.append(
            f"| {_field(f.dimension)} | {_field(f.severity)} | {f.value} "  # type: ignore[attr-defined]
            f"| {f.warn} | {f.critical} | {_field(f.message)} |"  # type: ignore[attr-defined]
        )
    lines.append("")
    return lines


def _saturation_section(saturation: SaturationAnalysis) -> list[str]:
    lines = ["## Saturation", ""]
    lines.extend(_pool_table(saturation.pools))
    lines.extend(_lock_table(saturation.lock_sites, saturation.lock_finding_note))
    lines.extend(_dependency_table(saturation.dependencies))
    lines.extend(_flag_table(saturation.flags))
    return lines


def _signature_table(signatures: tuple[SignatureProgression, ...]) -> list[str]:
    lines = ["## Signatures", ""]
    if not signatures:
        lines.append("_No signatures present._")
        lines.append("")
        return lines
    lines.append(
        "| Role | Subsystem | Pattern | Frame index | Reason | Matched frame "
        "| Leaf frame | Thread count |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in signatures:
        subsystem = s.subsystem if s.subsystem is not None else _ABSENT
        pattern = s.pattern if s.pattern is not None else _ABSENT
        frame_index = s.frame_index if s.frame_index is not None else _ABSENT
        reason = s.reason if s.reason is not None else _ABSENT
        matched_frame = s.matched_frame if s.matched_frame is not None else _ABSENT
        leaf_frame = s.leaf_frame if s.leaf_frame is not None else _ABSENT
        thread_count = s.counts[-1] if s.counts else _ABSENT
        lines.append(
            f"| {_field(s.role)} | {_field(subsystem)} | {_field(pattern)} "
            f"| {frame_index} | {_field(reason)} | {_field(matched_frame)} "
            f"| {_field(leaf_frame)} | {thread_count} |"
        )
    lines.append("")
    return lines


def render_eustack_markdown(bundle: EustackBundle) -> str:
    """Render the deterministic eu-stack report (EUS-07/08/09).

    A case with no eu-stack dumps at all states that plainly rather than
    rendering an empty set of tables (D-12) — the CSV still carries its
    header row in that case (``write_eustack_signatures_csv``).
    """
    out: list[str] = ["# Eu-Stack Analysis", ""]
    progression = bundle.progression
    if not progression.dumps:
        out.append(_NO_DUMPS)
        out.append("")
        return "\n".join(out)
    out.extend(_dumps_section(progression))
    out.extend(
        _role_composition_section(
            bundle.analysis.total_threads,
            bundle.analysis.total_signatures,
            bundle.analysis.threads_by_role,
            bundle.analysis.signatures_by_role,
        )
    )
    out.extend(_saturation_section(bundle.saturation))
    out.extend(_signature_table(progression.signatures))
    return "\n".join(out)


def render_eustack_json(bundle: EustackBundle) -> str:
    """Serialise the bundle to canonical, key-sorted, ASCII-safe JSON (D-13).

    ``ensure_ascii=True`` backslash-escapes every non-ASCII code point so the
    JSON report carries no raw C1/Cf terminal-injection byte (mirrors
    ``render_perfmon_json``'s T-13-JSONESC control). No wall-clock field of
    any kind anywhere in the bundle is what makes byte-identity achievable.
    """
    doc = bundle.model_dump(mode="json")
    return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"


def write_eustack_signatures_csv(bundle: EustackBundle, path: Path) -> None:
    """Write the summary signatures CSV: one row per signature (D-04/D-05).

    The header is written before any iteration, so a zero-signature bundle
    still yields a file that parses as valid CSV. ``thread_count`` holds the
    LAST dump's count (D-11). Every string cell carrying C++ symbol text
    passes through ``_csv_safe``; numeric cells (the per-dump counts,
    ``overall_delta``) are written as real ``int`` so a negative delta keeps
    its sign — never guarded, matching ``write_perfmon_trend_csv``'s own
    string-cells-only guarding discipline.
    """
    dump_names = tuple(d.source_file for d in bundle.progression.dumps)
    header = (
        *EUSTACK_CSV_BASE_HEADER,
        *(_csv_safe(name) for name in dump_names),
        "step_deltas",
        "overall_delta",
    )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for s in bundle.progression.signatures:
            thread_count = s.counts[-1] if s.counts else 0
            row: list[object] = [
                _csv_safe(s.role),
                _csv_safe(s.subsystem) if s.subsystem is not None else "",
                _csv_safe(s.pattern) if s.pattern is not None else "",
                s.frame_index if s.frame_index is not None else "",
                _csv_safe(s.reason) if s.reason is not None else "",
                _csv_safe(s.matched_frame) if s.matched_frame is not None else "",
                _csv_safe(s.leaf_frame) if s.leaf_frame is not None else "",
                thread_count,
                *s.counts,
                ";".join(str(d) for d in s.step_deltas),
                s.overall_delta,
            ]
            writer.writerow(row)
