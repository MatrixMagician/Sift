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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from sift.models import Event

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
    # Always present; an absent/garbled block is the EMPTY breakdown (all maps
    # empty, every accessor -> None) rather than a fabricated one (D-03).
    breakdown: MemoryBreakdown


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


# --- Episode detection (ported prescan + D-02/D-06/D-07 extensions) ----------

# One line of the reconstructed stream: (line_text, owning_event_id, iso_ts).
_StreamLine = tuple[str, str, str | None]


@dataclass
class _RawEpisode:
    """Prescan output: episode boundaries as stream indices carrying event_ids."""

    denial_idx: int
    denial_event_id: str
    denial_ts: str | None
    recovery_event_id: str | None
    open_truncated: bool
    span_start: int
    span_end: int


def _line_stream(dss: list[Event]) -> list[_StreamLine]:
    """Rebuild the event-id-carrying line stream from ``event.raw`` (D-01).

    Splits each row's verbatim text on newlines in the already-queried order —
    the store's ``ORDER BY ts IS NULL, ts, source_file, line_start`` is the D-06
    canonical order, so this NEVER re-sorts (store.py:567).
    """
    stream: list[_StreamLine] = []
    for e in dss:
        ts = e.ts.isoformat() if e.ts is not None else None
        for line in e.raw.split("\n"):
            stream.append((line, e.event_id, ts))
    return stream


def _prescan(stream: list[_StreamLine]) -> list[_RawEpisode]:
    """Port of analyze_dss8.py:112-238 over stream indices (not file linenos).

    Same-burst denial banners within one episode collapse; a denial banner that
    follows intervening successes closes the prior episode (implicit recovery);
    an open episode at EOF is flagged ``open_truncated`` (D-07). An
    ``AvailableMCM`` climb or resumed successes never close an episode (Q2).
    """
    episodes: list[_RawEpisode] = []
    in_denial = False
    start_idx: int | None = None
    start_eid: str | None = None
    start_ts: str | None = None
    prev_recovery_idx = -1
    succeeded_idxs: list[int] = []

    for i, (line, eid, ts) in enumerate(stream):
        if SUCCESS_MARKER in line:
            succeeded_idxs.append(i)

        if DENIAL_MARKER in line:
            if not in_denial:
                start_idx, start_eid, start_ts = i, eid, ts
                in_denial = True
            elif (
                start_idx is not None
                and start_eid is not None
                and any(idx > start_idx for idx in succeeded_idxs)
            ):
                # New activity since the open denial -> partial recovery: close
                # the current episode (no State=normal, but clearly ended).
                episodes.append(
                    _RawEpisode(
                        denial_idx=start_idx,
                        denial_event_id=start_eid,
                        denial_ts=start_ts,
                        recovery_event_id=None,
                        open_truncated=False,
                        span_start=prev_recovery_idx + 1,
                        span_end=i - 1,
                    )
                )
                # Close at the line just BEFORE the new denial (mirrors the
                # normal-recovery branch, which advances the boundary to its
                # closing line) so the next episode's span_start = i does not
                # reach back over the just-closed episode. Spans stay DISJOINT:
                # no lifecycle signal / citation event_id lands in two episodes
                # (WR-01). The new episode's pre-denial Info Dump, which precedes
                # index i, is recovered by _build_breakdown's widened backward
                # scan, NOT by widening this span.
                prev_recovery_idx = i - 1
                start_idx, start_eid, start_ts = i, eid, ts
            # else: same-burst repeated banner -> ignore.

        if NORMAL_MARKER in line and in_denial:
            assert start_idx is not None and start_eid is not None
            episodes.append(
                _RawEpisode(
                    denial_idx=start_idx,
                    denial_event_id=start_eid,
                    denial_ts=start_ts,
                    recovery_event_id=eid,
                    open_truncated=False,
                    span_start=prev_recovery_idx + 1,
                    span_end=i,
                )
            )
            prev_recovery_idx = i
            in_denial = False
            start_idx = start_eid = start_ts = None

    if in_denial:
        assert start_idx is not None and start_eid is not None
        episodes.append(
            _RawEpisode(
                denial_idx=start_idx,
                denial_event_id=start_eid,
                denial_ts=start_ts,
                recovery_event_id=None,
                open_truncated=True,
                span_start=prev_recovery_idx + 1,
                span_end=len(stream) - 1,
            )
        )
    return episodes


def _scan_lifecycle(
    stream: list[_StreamLine], span_start: int, span_end: int
) -> tuple[LifecycleSignal, ...]:
    """Emit the pinned denial-lifecycle signals within the episode span (D-02).

    Kind is classified by tail text; an absent marker simply yields no signal
    (D-03 — never fabricated). Each signal keeps its owning ``event_id``.
    """
    signals: list[LifecycleSignal] = []
    for i in range(span_start, span_end + 1):
        line, eid, ts = stream[i]
        if OFFLOAD_COMPLETE_MARKER in line:
            kind = "emergency-offload-complete"
        elif OFFLOAD_START_MARKER in line:
            kind = "emergency-offload-start"
        elif MEMORY_STATUS_LOW_MARKER in line:
            kind = "memory-status-low"
        else:
            continue
        signals.append(
            LifecycleSignal(kind=kind, event_id=eid, ts=ts, text=line.strip())
        )
    return tuple(signals)


def _build_breakdown(
    stream_lines: list[str], ep: _RawEpisode, dss: list[Event], pos: dict[str, int]
) -> tuple[MemoryBreakdown, bool]:
    """Parse the Format-A detail block from the denial line and associate the
    nearest in-span Info Dump (Q1), returning ``(breakdown, fragmented)``.

    The detail block is read forward from the denial banner; MCM Settings /
    Current Memory Info are found by scanning BACKWARD within the span for the
    nearest markers. An empty detail block whose neighbouring event is a
    different ``source_file`` sets ``fragmented`` (D-06). An absent/garbled block
    yields the EMPTY breakdown (all maps empty, accessors -> None) rather than
    raising or fabricating (D-03).
    """
    detail, _ = parse_detail_block(stream_lines, ep.denial_idx + 1)

    current_info: dict[str, str] = {}
    mcm_settings: dict[str, str] = {}
    # Scan backward from the denial banner for the nearest pre-denial Info Dump.
    # The lookup window may reach back BEFORE span_start (a partial-recovery
    # episode's span_start is its own denial index, so its dump — which precedes
    # the banner — sits just outside the span), but it STOPS at the previous
    # episode's boundary: a prior DENIAL_MARKER / NORMAL_MARKER line. This never
    # reads the previous episode's denial-time block and never widens the
    # lifecycle/citation span. Absence is tolerated (D-03): no dump -> empty maps.
    for i in range(ep.denial_idx - 1, -1, -1):
        line = stream_lines[i]
        if DENIAL_MARKER in line or NORMAL_MARKER in line:
            break
        if not mcm_settings and MCM_SETTINGS_MARKER in line:
            mcm_settings, _ = parse_abbrev_block(stream_lines, i + 1)
        elif not current_info and CURRENT_INFO_MARKER in line:
            current_info, _ = parse_abbrev_block(stream_lines, i + 1)
        if mcm_settings and current_info:
            break

    fragmented = False
    if not detail:
        p = pos[ep.denial_event_id]
        if p + 1 < len(dss) and dss[p + 1].source_file != dss[p].source_file:
            fragmented = True

    breakdown = MemoryBreakdown(
        raw_map=detail, current_memory_info=current_info, mcm_settings=mcm_settings
    )
    return breakdown, fragmented


def detect_episodes(events: list[Event]) -> list[McmEpisode]:
    """Detect MCM denial episodes over stored ``dsserrors`` events (MCM-01).

    Pure and non-interactive: filters to ``source == "dsserrors"``, rebuilds the
    event-id line stream in the incoming (D-06) order without re-sorting, runs
    the ported prescan, and for each episode captures the lifecycle signals
    (D-02), the denial-time Format-A breakdown + nearest in-span Info Dump (Q1),
    open/truncated (D-07) and fragmentation (D-06) state. Deterministic: no
    ``set`` iteration, so ``model_dump_json`` is byte-identical on re-run (D-05).
    """
    dss = [e for e in events if e.source == "dsserrors"]
    if not dss:
        return []

    stream = _line_stream(dss)
    stream_lines = [line for line, _eid, _ts in stream]
    pos = {e.event_id: i for i, e in enumerate(dss)}

    episodes: list[McmEpisode] = []
    for ep in _prescan(stream):
        span_eids = tuple(
            dict.fromkeys(
                stream[i][1] for i in range(ep.span_start, ep.span_end + 1)
            )
        )
        lifecycle = _scan_lifecycle(stream, ep.span_start, ep.span_end)
        breakdown, fragmented = _build_breakdown(stream_lines, ep, dss, pos)
        episodes.append(
            McmEpisode(
                denial_event_id=ep.denial_event_id,
                denial_ts=ep.denial_ts,
                recovery=ep.recovery_event_id,
                open_truncated=ep.open_truncated,
                fragmented=fragmented,
                event_ids=span_eids,
                lifecycle=lifecycle,
                breakdown=breakdown,
            )
        )
    return episodes
