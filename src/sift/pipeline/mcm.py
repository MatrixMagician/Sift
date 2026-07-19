"""Deterministic MCM (Memory Contract Manager) episode analyser (MCM-01, MCM-02).

Milestone v1.1's numeric core. Like ``salience.py`` this module is typer-free,
print-free, SQL-free and I/O-free: the caller passes in already-queried
``Event`` rows and receives typed models back. It NEVER talks to the network,
an LLM, a subprocess or the filesystem — the figures reported here are computed
from stored log text, never authored by a model. Every signal keeps the
``event_id`` of the row it was parsed from so Phase 11 can cite it
(cited ⊆ prompted ⊆ store).

The regex/marker constants and the ``prescan`` / ``parse_detail_block`` /
``parse_abbrev_block`` / ``_get`` helpers are ported from the vendored reference
``docs/reference/analyze_dss8.py`` (line ranges cited inline). The port reads the
event-id-carrying line stream rebuilt from ``event.raw`` (D-01 — re-parse raw,
never enrich the adapter) rather than a flat file, and extends the reference
with lifecycle-signal capture (D-02), open/truncated handling (D-07), the
in-span Info-Dump association rule (Q1), a widened abbrev regex that keeps
``0Bytes`` values, and the multi-node fragmentation guard (D-06).

Determinism (crit #5, D-05): the incoming order from ``store.query_events`` is
the D-06 canonical order and is never re-sorted; output uses insertion-ordered
dicts and tuples, never ``set`` iteration, so ``model_dump_json`` is
byte-identical on re-run.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

# --- Ported regex constants (docs/reference/analyze_dss8.py:38-66) -----------
# Anchored, linear-scan patterns with required terminators — no ReDoS
# (mirrors adapters/dsserrors.py:50). Verbatim from the reference EXCEPT
# ABBREV_LINE_RE, widened below.
TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)")
SID_RE = re.compile(r"\[SID:(0|[A-Fa-f0-9]{32})\]")
OID_RE = re.compile(r"\[OID:(0|[A-Fa-f0-9]{32})\]")
SIZE_RE = re.compile(r"\bSize=(\d+)")
SOURCE_RE = re.compile(r"\bSource=([\w:]+)")
AVAIL_MCM_RE = re.compile(r"\bAvailableMCM=(\d+)")
HWM_RE = re.compile(r"\bHWM\(\w+\)=(\d+)")

SUCCESS_MARKER = "Contract Request Succeeded"
DENIAL_MARKER = "IServer enters MCM denial state"
NORMAL_MARKER = "State=normal"
CURRENT_INFO_MARKER = "Current Memory Info:"
MCM_SETTINGS_MARKER = "MCM Settings:"

# "Label(UNIT): value" lines in the detailed breakdown block. The (.+?) before
# the unit is intentionally permissive — labels can contain parentheses
# themselves (e.g. "...Memory(Including MMF) For...").
DETAIL_LINE_RE = re.compile(r"^\t*(.+?)\((GB|MB|KB)\):\s*(-?\d+)\s*$")

# "Label = value (human UNIT)" lines in abbreviated blocks. WIDENED from the
# reference: the optional unit group now accepts ``Bytes`` and tolerates a
# missing space before the unit, so ``Memory Reserve = 0 (0Bytes)`` is NOT
# dropped ("nothing disappears silently").
ABBREV_LINE_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9 /\-]*?)\s*=\s*(unlimited|true|false|-?\d+)\s*"
    r"(?:\(([\d.]+)\s*(TB|GB|MB|KB|Bytes)\))?\s*$"
)

UNIT_TO_MB = {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0, "TB": 1024.0 * 1024.0}


def to_mb(value: int, unit: str) -> float:
    """Normalise a (value, unit) pair to megabytes."""
    return value * UNIT_TO_MB[unit]


# --- Lifecycle-marker anchors (D-02, RESEARCH § Lifecycle Markers) -----------
# Pinned substrings; the signal kind is classified by the tail text. Quoted
# exactly from the real Hartford denial-time offload sequence.
MEMORY_STATUS_LOW_MARKER = "Memory status changes to low"
MEMORY_STATUS_HANDLER_MARKER = "MsiSessionManager::MemoryStatusHandler()"
OFFLOAD_START_MARKER = "Initiating emergency memory offload for Working Set"
OFFLOAD_COMPLETE_MARKER = "Working set emergency offload completed"


# --- Fuzzy accessor (docs/reference/analyze_dss8.py:500-504) -----------------


def _get(data: dict[str, tuple[float, str]], substr: str) -> float | None:
    """First value whose label contains ``substr`` (case-insensitive), else None.

    Substring lookup tolerates label drift and absence (D-03): a missing label
    returns ``None`` rather than raising.
    """
    needle = substr.lower()
    for label, (value_mb, _unit) in data.items():
        if needle in label.lower():
            return value_mb
    return None


# --- Typed models (frozen, extra="forbid" — Hypothesis convention) -----------


class LifecycleSignal(BaseModel):
    """One denial-lifecycle marker, keyed to the event it was parsed from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str  # "memory-status-low" | "emergency-offload-start" | "-complete"
    event_id: str
    ts: str | None
    text: str


class MemoryBreakdown(BaseModel):
    """The denial-time memory picture: the verbatim Format-A map plus the
    in-span abbreviated Current Memory Info / MCM Settings blocks.

    ``raw_map`` keeps all labels verbatim (D-04). The typed accessors resolve
    via ``_get`` substring lookup so label drift and absence are tolerated
    (each returns ``float | None``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_map: dict[str, tuple[float, str]]
    current_memory_info: dict[str, str]
    mcm_settings: dict[str, str]

    @property
    def physical_total(self) -> float | None:
        return _get(self.raw_map, "Total System Physical Memory")

    @property
    def iserver_physical_mb(self) -> float | None:
        return _get(
            self.raw_map, "Total In Use Physical Memory For Intelligence Server"
        )

    @property
    def other_processes_mb(self) -> float | None:
        return _get(self.raw_map, "Total In Use Physical Memory For Other Processes")

    @property
    def iserver_virtual_mb(self) -> float | None:
        return _get(self.raw_map, "Total In Use Virtual Memory")

    @property
    def cube_caches_mb(self) -> float | None:
        return _get(self.raw_map, "Cube Caches In Memory")

    @property
    def cube_growth_index_mb(self) -> float | None:
        return _get(self.raw_map, "Cube Size Growth In Memory Including Indexes")

    @property
    def mmf_mb(self) -> float | None:
        return _get(self.raw_map, "MMF Virtual Memory Size")

    @property
    def working_set_mb(self) -> float | None:
        return _get(self.raw_map, "Working Set Cache RAM Usage")

    @property
    def smartheap_unused_pool_mb(self) -> float | None:
        return _get(self.raw_map, "Unused Memory Pool In SmartHeap")

    @property
    def other_memory_mb(self) -> float | None:
        return _get(self.raw_map, "Other Memory In Intelligence Server")


class McmEpisode(BaseModel):
    """One MCM denial episode, every boundary keyed to a real ``event_id``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    denial_event_id: str
    denial_ts: str | None
    recovery: str | None  # recovery event_id, or None if never recovered (D-07)
    open_truncated: bool
    fragmented: bool
    event_ids: tuple[str, ...]  # all rows in the episode span, ordered, deduped
    lifecycle: tuple[LifecycleSignal, ...]
    breakdown: MemoryBreakdown | None


# --- Ported block parsers (docs/reference/analyze_dss8.py:247-286) -----------


def parse_detail_block(
    lines: list[str], start_idx: int
) -> tuple[dict[str, tuple[float, str]], int]:
    """Parse the Format-A "Label(UNIT): value" detail block from ``start_idx``.

    Stops at the trailing Note/Working-set/SmartHeap prose, a timestamp line, a
    blank line, or the 60-line safety cap (a never-terminated block cannot
    spin). Returns ``(label -> (value_mb, unit), next_idx)``.
    """
    data: dict[str, tuple[float, str]] = {}
    idx = start_idx
    while idx < len(lines):
        line = lines[idx].rstrip("\n")
        stripped = line.strip()
        if (
            stripped.startswith("Note:")
            or stripped.startswith("Working set includes")
            or stripped.startswith("SmartHeap cache memory")
        ):
            break
        m = DETAIL_LINE_RE.match(line)
        if m:
            label, unit, value = m.group(1), m.group(2), m.group(3)
            data[label.strip()] = (to_mb(int(value), unit), unit)
            idx += 1
        elif TIMESTAMP_RE.match(line) or stripped == "":
            break
        else:
            idx += 1
            if idx - start_idx > 60:
                break
    return data, idx


def parse_abbrev_block(lines: list[str], start_idx: int) -> tuple[dict[str, str], int]:
    """Parse a "Label = value (human UNIT)" abbreviated block from ``start_idx``.

    Returns ``(label -> raw_value, next_idx)``. Stops at the next timestamp
    line; blank lines are skipped; the widened ``ABBREV_LINE_RE`` keeps
    ``0Bytes`` values.
    """
    data: dict[str, str] = {}
    idx = start_idx
    while idx < len(lines):
        line = lines[idx].rstrip("\n")
        if TIMESTAMP_RE.match(line):
            break
        stripped = line.strip()
        m = ABBREV_LINE_RE.match(stripped)
        if m:
            data[m.group(1).strip()] = m.group(2)
            idx += 1
        elif stripped == "":
            idx += 1
        else:
            break
    return data, idx
