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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from sift.config import McmThresholdsConfig
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

# The single auto-selected lead-up window threshold (MCM-04, D-13). This is the
# reference's Enter-default ``WINDOW_THRESHOLDS_PCT[0]`` (docs/reference/
# analyze_dss8.py:76 — [25, 15, 10, 5, 2]); the interactive menu of narrower
# thresholds is dropped — the window is fully automatic, no CLI override (D-13).
WINDOW_WIDEST_PCT = 25


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
    # Window inputs (MCM-04): the lead-up AvailableMCM descent captured over the
    # succeeded grants BEFORE the denial banner. Each entry keeps its owning
    # event_id (D-16) — never a line number. hwm_bytes is the last lead-up
    # sample's HWM, or None when the lead-up carries no AvailableMCM data.
    hwm_bytes: int | None
    avail_timeline: tuple[tuple[str, int, int], ...]


class EpisodeWindow(BaseModel):
    """The auto-selected lead-up analysis window for one episode (MCM-04, D-13).

    ``start_event_id`` keys the window start to a real store ``event_id`` (D-16),
    or is ``None`` for the full-lead-up fallback. Fully automatic and
    non-interactive — no CLI override, no ``input()`` (D-13).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold_pct: int
    start_event_id: str | None
    hwm_bytes: int | None
    request_count: int
    label: str


class DiagnosticFlag(BaseModel):
    """One graded MCM diagnostic signal (D-12 / MCM-03).

    ``value_pct`` is ALWAYS a ratio ``part / whole * 100`` — never an absolute GB
    (the milestone-locked machine-independence invariant: scaling every absolute
    figure by any constant leaves every flag tier and displayed % identical).
    ``event_ids`` cites the denial event whose Info-Dump block the figure was
    parsed from (D-16 provenance).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str  # "working_set_pct_virtual" | ... (the config key it grades)
    severity: str  # "info" | "warn" | "critical"
    value_pct: float  # the triggering ratio, *100, rounded deterministically (1 dp)
    message: str  # British-English one-liner with the % inline
    event_ids: tuple[str, ...]


class AttributionRow(BaseModel):
    """One aggregated lead-up attribution figure (MCM-04 / D-14 / D-16).

    A single row of one dimension: the memory granted to one ``key`` (an OID, a
    ``Source=`` request type, or a SID/session) over the lead-up window.
    ``event_ids`` carries the deduped, insertion-ordered ``event_id``s of the
    grant lines it aggregates — the D-16 ``cited ⊆ store`` provenance that makes
    every figure verifiable. ``sids`` is populated ONLY for ``dimension="oid"``:
    the distinct sessions that consumed that object, the fan-out note resolving
    the one-OID/many-SID case (D-14).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str  # "oid" | "source" | "sid"
    key: str
    granted_bytes: int
    request_count: int
    event_ids: tuple[str, ...]
    sids: tuple[str, ...] = ()  # distinct sessions, only for dimension="oid"


class Attribution(BaseModel):
    """The lead-up window attributed across three independent dimensions (D-14).

    ``by_oid`` / ``by_source`` / ``by_sid`` each aggregate the SAME succeeded
    grants keyed differently — flattened to three top-level tables (the reference
    nested source under oid). Rows are sorted ``granted_bytes`` desc then ``key``
    asc for determinism. A succeeded line missing SID/OID/Size is recorded in
    ``unmatched_event_ids`` rather than dropped (nothing disappears silently).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    by_oid: tuple[AttributionRow, ...]
    by_source: tuple[AttributionRow, ...]
    by_sid: tuple[AttributionRow, ...]
    unmatched_event_ids: tuple[str, ...]


class EpisodeAnalysis(BaseModel):
    """One episode's full analysis: episode + window + flags + attribution.

    The unit the report/CLI (Plan 04) render per denial episode — bundling the
    detected episode (MCM-01/02), its auto-selected lead-up window (MCM-04/D-13),
    its graded diagnostic flags (MCM-03/D-12) and its three-dimension attribution
    (MCM-04/D-14).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode: McmEpisode
    window: EpisodeWindow
    flags: tuple[DiagnosticFlag, ...]
    attribution: Attribution


class McmAnalysis(BaseModel):
    """The full MCM analysis over a case: one EpisodeAnalysis per episode.

    The single object ``analyse_mcm`` returns and the renderer/CLI consume. An
    empty case (no MCM denial episodes) yields ``episodes=()`` — never a crash.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    episodes: tuple[EpisodeAnalysis, ...]


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


def _avail_timeline(
    stream: list[_StreamLine], ep: _RawEpisode
) -> tuple[tuple[str, int, int], ...]:
    """Capture the lead-up AvailableMCM descent as (event_id, avail, hwm) samples.

    Walks ``range(span_start, denial_idx)`` — the lead-up, EXCLUSIVE of the
    denial banner (Pitfall 1: post-denial fan-out is recovery-phase, never
    attributed). For each ``SUCCESS_MARKER`` line where BOTH ``AvailableMCM=``
    and ``HWM(...)=`` match, records the owning ``event_id`` (D-16 — never a line
    index) with the two integer byte values. Ported from analyze_dss8.py:148-154
    over stream indices rather than file linenos; absence yields no sample (D-03).
    """
    samples: list[tuple[str, int, int]] = []
    for i in range(ep.span_start, ep.denial_idx):
        line, eid, _ts = stream[i]
        if SUCCESS_MARKER not in line:
            continue
        avail_m = AVAIL_MCM_RE.search(line)
        hwm_m = HWM_RE.search(line)
        if avail_m and hwm_m:
            samples.append((eid, int(avail_m.group(1)), int(hwm_m.group(1))))
    return tuple(samples)


def select_window(ep: McmEpisode) -> EpisodeWindow:
    """Auto-select the lead-up analysis window from AvailableMCM descent (MCM-04).

    Fully automatic and non-interactive (D-13): a faithful port of the reference
    ``prompt_window`` (analyze_dss8.py:678-773) restricted to the Enter-default
    widest threshold (``WINDOW_WIDEST_PCT`` = 25% of HWM), with the ``input()``
    prompt and the narrower-threshold menu dropped.

    "Last crossing downward": the window starts at the first lead-up sample that
    fell below 25% of HWM AFTER the final time it was still above — anchoring the
    window to the final pressure descent, not the first time the threshold was
    ever crossed. An always-below episode (AvailableMCM never reached 25% of HWM)
    anchors to the first timeline entry (D-16 — a real event_id, not line 1). An
    empty lead-up / absent HWM returns the full-lead-up fallback
    (``threshold_pct=0``, ``start_event_id=None``) rather than raising (D-03).
    """
    timeline = ep.avail_timeline
    hwm_bytes = ep.hwm_bytes
    if not timeline or not hwm_bytes:
        return EpisodeWindow(
            threshold_pct=0,
            start_event_id=None,
            hwm_bytes=hwm_bytes,
            request_count=len(timeline),
            label="full available lead-up",
        )

    threshold_bytes = hwm_bytes * WINDOW_WIDEST_PCT / 100
    last_above: int | None = None
    for idx, (_eid, avail, _hw) in enumerate(timeline):
        if avail >= threshold_bytes:
            last_above = idx

    if last_above is not None:
        # Final descent: first sample after last_above that is below threshold.
        start_idx = next(
            (
                idx
                for idx in range(last_above + 1, len(timeline))
                if timeline[idx][1] < threshold_bytes
            ),
            None,
        )
        if start_idx is None:
            # last_above was the final sample above, then the lead-up ends. The
            # reference points one line PAST it (a lineno beyond the timeline);
            # we clamp to last_above so start_event_id stays a real event_id
            # (D-16) rather than None.
            # ponytail: clamp-to-last edge; only fires if AvailableMCM never
            # descended below 25% before denial (untested rarity).
            start_idx = last_above
    else:
        # Always below the threshold — anchor to the very first timeline entry.
        start_idx = 0

    hwm_gb = hwm_bytes / 1024**3
    return EpisodeWindow(
        threshold_pct=WINDOW_WIDEST_PCT,
        start_event_id=timeline[start_idx][0],
        hwm_bytes=hwm_bytes,
        request_count=len(timeline) - start_idx,
        label=f"AvailableMCM < {WINDOW_WIDEST_PCT}% of HWM ({hwm_gb:.1f} GB)",
    )


# --- Diagnostic flags (docs/reference/analyze_dss8.py:79-85,507-624; D-12) ---


def _grade(value_pct: float, warn: float, crit: float, *, invert: bool = False) -> str:
    """Grade a ratio into info/warn/critical against two cut-points.

    Upward (default): a HIGHER value is worse — ``critical`` at ``>= crit``,
    ``warn`` at ``>= warn``. Inverted (``invert=True``, the system-free-headroom
    special case): a LOWER value is worse, so the comparisons flip — ``critical``
    at ``<= crit``, ``warn`` at ``<= warn``. A uniform upward comparison would
    mis-grade high headroom as critical (Pitfall 2).
    """
    if invert:
        if value_pct <= crit:
            return "critical"
        return "warn" if value_pct <= warn else "info"
    if value_pct >= crit:
        return "critical"
    return "warn" if value_pct >= warn else "info"


def compute_flags(ep: McmEpisode, t: McmThresholdsConfig) -> tuple[DiagnosticFlag, ...]:
    """Grade the denial-time memory picture into five diagnostic flags (MCM-03).

    Pure and deterministic: each flag is a ratio ``part / whole * 100`` compared
    to config-injected cut-points (D-12) — never an absolute GB (the milestone
    machine-independence lock). Every ``None``/zero-denominator input is guarded
    BEFORE dividing, so a missing signal simply emits no flag rather than a
    fabricated percentage (D-03). All flags cite the denial event whose Info-Dump
    block they were parsed from (D-16). British-English messages carry the %
    inline (D-11).
    """
    b = ep.breakdown
    cite = (ep.denial_event_id,)
    flags: list[DiagnosticFlag] = []

    # 1. Working set as % of IServer virtual — the denial driver (65.4% at Hartford).
    ws, virt = b.working_set_mb, b.iserver_virtual_mb
    if ws is not None and virt:
        pct = round(ws / virt * 100, 1)
        flags.append(
            DiagnosticFlag(
                dimension="working_set_pct_virtual",
                severity=_grade(
                    pct,
                    t.working_set_pct_virtual.warn,
                    t.working_set_pct_virtual.critical,
                ),
                value_pct=pct,
                message=f"Working set is {pct:.1f}% of IServer virtual memory",
                event_ids=cite,
            )
        )

    # 2. Other (non-IServer) processes as % of total physical — cohabitation.
    other, phys = b.other_processes_mb, b.physical_total
    if other is not None and phys:
        pct = round(other / phys * 100, 1)
        flags.append(
            DiagnosticFlag(
                dimension="other_processes_pct_physical",
                severity=_grade(
                    pct,
                    t.other_processes_pct_physical.warn,
                    t.other_processes_pct_physical.critical,
                ),
                value_pct=pct,
                message=f"Other processes hold {pct:.1f}% of physical memory",
                event_ids=cite,
            )
        )

    # 3. Cube-cache share of virtual, gated by MMF coverage of the cube: only
    #    material when cubes dominate memory yet MMF offloads little of them.
    cube = b.cube_caches_mb
    if cube is not None and virt:
        cube_pct = round(cube / virt * 100, 1)
        mmf = b.mmf_mb
        mmf_cov = mmf / cube * 100 if (mmf is not None and cube) else None
        low_cover = mmf_cov is None or mmf_cov < t.mmf_pct_of_cube_low
        if cube_pct >= t.cube_pct_virtual.critical and low_cover:
            severity = "critical"
        elif cube_pct >= t.cube_pct_virtual.warn and low_cover:
            severity = "warn"
        else:
            severity = "info"
        cover_note = (
            f" (MMF covers {mmf_cov:.1f}% of cube)" if mmf_cov is not None else ""
        )
        msg = f"Cube caches are {cube_pct:.1f}% of IServer virtual memory{cover_note}"
        flags.append(
            DiagnosticFlag(
                dimension="cube_mmf_coverage",
                severity=severity,
                value_pct=cube_pct,
                message=msg,
                event_ids=cite,
            )
        )

    # 4. SmartHeap unused pool as % of virtual — but a releasable pool is
    #    reclaimed automatically, so its size is not actionable (info).
    pool = b.smartheap_unused_pool_mb
    if pool is not None and virt:
        pct = round(pool / virt * 100, 1)
        releasable = b.mcm_settings.get("SmartHeap Cache Releasable") == "true"
        if releasable:
            severity = "info"
            suffix = " (releasable)"
        else:
            severity = _grade(
                pct,
                t.smartheap_pool_pct_virtual.warn,
                t.smartheap_pool_pct_virtual.critical,
            )
            suffix = " (not releasable)"
        msg = f"SmartHeap unused pool is {pct:.1f}% of IServer virtual memory{suffix}"
        flags.append(
            DiagnosticFlag(
                dimension="smartheap_releasable",
                severity=severity,
                value_pct=pct,
                message=msg,
                event_ids=cite,
            )
        )

    # 5. System-free headroom — the inverted metric: lower free-% is worse.
    avail_s = b.current_memory_info.get("System Available")
    total_s = b.current_memory_info.get("System Total")
    if avail_s is not None and total_s is not None:
        total = int(total_s)
        if total:
            pct = round(int(avail_s) / total * 100, 1)
            flags.append(
                DiagnosticFlag(
                    dimension="system_free_headroom_pct",
                    severity=_grade(
                        pct,
                        t.system_free_headroom_pct.warn,
                        t.system_free_headroom_pct.critical,
                        invert=True,
                    ),
                    value_pct=pct,
                    message=f"System free headroom is {pct:.1f}% of total memory",
                    event_ids=cite,
                )
            )

    return tuple(flags)


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
            dict.fromkeys(stream[i][1] for i in range(ep.span_start, ep.span_end + 1))
        )
        lifecycle = _scan_lifecycle(stream, ep.span_start, ep.span_end)
        breakdown, fragmented = _build_breakdown(stream_lines, ep, dss, pos)
        avail_timeline = _avail_timeline(stream, ep)
        hwm_bytes = avail_timeline[-1][2] if avail_timeline else None
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
                hwm_bytes=hwm_bytes,
                avail_timeline=avail_timeline,
            )
        )
    return episodes


# --- Lead-up attribution (docs/reference/analyze_dss8.py:293-394; D-14/D-16) --


@dataclass
class _Attr:
    """Mutable per-key accumulator for one attribution dimension.

    ``event_ids`` / ``sids`` are appended in walk order and deduped via
    ``dict.fromkeys`` at row build — never ``set`` iteration (determinism).
    """

    granted_bytes: int = 0
    request_count: int = 0
    event_ids: list[str] = field(default_factory=list[str])
    sids: list[str] = field(default_factory=list[str])


def attribute_window(
    ep: McmEpisode, window: EpisodeWindow, events: list[Event]
) -> Attribution:
    """Attribute the lead-up window across three independent dimensions (MCM-04).

    A faithful port of the reference ``parse_log`` (analyze_dss8.py:293-394)
    forward accumulation, flattened from the reference's ``oid_sources[oid][src]``
    nesting to THREE top-level tables — by OID, by ``Source=`` request type and by
    SID/session — so the one-OID/many-SID fan-out is resolved by session (D-14).

    Walks ``[window.start_event_id … denial)`` EXCLUSIVE of the denial banner
    (Pitfall 1: post-denial/recovery grants are never attributed; Pitfall 5: the
    denial line's own failed-request ``Source=`` is gated out by ``SUCCESS_MARKER``
    and by stopping before the denial line). For the full-lead-up fallback
    (``window.start_event_id is None``) the walk starts at the episode's span head.
    On each ``SUCCESS_MARKER`` line SID AND OID AND Size are required, else the
    line's ``event_id`` is recorded in ``unmatched_event_ids`` — nothing disappears
    silently (D-03). ``Source`` defaults to ``"Unknown"`` when absent.

    Every ``AttributionRow.event_ids`` carries the owning grant-line ``event_id``s
    (D-16 — the ``cited ⊆ ep.event_ids ⊆ store`` bridge Phase 11 reuses); rows are
    sorted ``granted_bytes`` desc then ``key`` asc; ids are deduped insertion-
    ordered. Pure and I/O-free: rebuilds the same D-06-ordered stream as
    ``detect_episodes`` and never re-sorts.
    """
    stream = _line_stream([e for e in events if e.source == "dsserrors"])
    # Denial banner index for THIS episode — the walk stops just before it.
    denial_idx = next(
        (
            i
            for i, (line, eid, _ts) in enumerate(stream)
            if eid == ep.denial_event_id and DENIAL_MARKER in line
        ),
        len(stream),
    )
    # Window start: the narrowed descent start (a real event_id), or the lead-up
    # span head for the full-lead-up fallback (window.start_event_id is None).
    head = window.start_event_id or (ep.event_ids[0] if ep.event_ids else None)
    start_idx = next(
        (i for i, (_line, eid, _ts) in enumerate(stream) if eid == head), 0
    )

    by_oid: dict[str, _Attr] = {}
    by_source: dict[str, _Attr] = {}
    by_sid: dict[str, _Attr] = {}
    unmatched: list[str] = []

    for i in range(start_idx, denial_idx):
        line, eid, _ts = stream[i]
        if SUCCESS_MARKER not in line:
            continue
        sid_m = SID_RE.search(line)
        oid_m = OID_RE.search(line)
        size_m = SIZE_RE.search(line)
        if not (sid_m and oid_m and size_m):
            unmatched.append(eid)
            continue
        sid, oid, size = sid_m.group(1), oid_m.group(1), int(size_m.group(1))
        source_m = SOURCE_RE.search(line)
        source = source_m.group(1) if source_m else "Unknown"
        for bucket, key in ((by_oid, oid), (by_source, source), (by_sid, sid)):
            acc = bucket.setdefault(key, _Attr())
            acc.granted_bytes += size
            acc.request_count += 1
            acc.event_ids.append(eid)
        by_oid[oid].sids.append(sid)  # fan-out note lives on the OID row only

    def rows(dimension: str, buckets: dict[str, _Attr]) -> tuple[AttributionRow, ...]:
        out = [
            AttributionRow(
                dimension=dimension,
                key=key,
                granted_bytes=acc.granted_bytes,
                request_count=acc.request_count,
                event_ids=tuple(dict.fromkeys(acc.event_ids)),
                sids=tuple(dict.fromkeys(acc.sids)) if dimension == "oid" else (),
            )
            for key, acc in buckets.items()
        ]
        out.sort(key=lambda r: (-r.granted_bytes, r.key))
        return tuple(out)

    return Attribution(
        by_oid=rows("oid", by_oid),
        by_source=rows("source", by_source),
        by_sid=rows("sid", by_sid),
        unmatched_event_ids=tuple(dict.fromkeys(unmatched)),
    )


def analyse_mcm(events: list[Event], thresholds: McmThresholdsConfig) -> McmAnalysis:
    """Compose the full MCM analysis — the single entry the CLI (Plan 04) calls.

    ``detect_episodes`` then, per episode, ``select_window`` (Plan 01) +
    ``compute_flags`` (Plan 02) + ``attribute_window`` bundled into one
    ``EpisodeAnalysis``. No episodes → ``McmAnalysis(episodes=())`` (never a
    crash). Pure and deterministic: ``model_dump_json`` is byte-identical on
    re-run (no ``set`` iteration anywhere on the path).
    """
    analyses: list[EpisodeAnalysis] = []
    for ep in detect_episodes(events):
        window = select_window(ep)
        analyses.append(
            EpisodeAnalysis(
                episode=ep,
                window=window,
                flags=compute_flags(ep, thresholds),
                attribution=attribute_window(ep, window, events),
            )
        )
    return McmAnalysis(episodes=tuple(analyses))
