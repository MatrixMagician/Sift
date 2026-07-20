"""dsserrors adapter: MicroStrategy DSSErrors.log + rotated .bak siblings.

[ASSUMED shapes] The 05-02 human-verify checkpoint was resolved
"proceed-on-assumed-shapes": the exact record-line layout and the SID token
shape are RESEARCH-derived assumptions, not pinned to a user-confirmed
sanitised sample. Extraction is anchored on version-stable *structural* tokens
(``[Name.cpp:NNNN]`` source-location tags, ``0x`` error codes, GUID-shaped
OIDs, ``SID=`` session ids, and the MCM ``***** Start/End of Info Dump *****``
sentinels) rather than on column order, so a later layout refinement against a
real sample is a localised regex change — not a rewrite.

Reuses ``base.ConfigurableAdapter`` (``input_root``/``tz_overrides``/
``last_stats``), the shared ``base.to_utc``/``base.tz_override_for`` UTC path
(the criterion-4 hook), ``base.open_bytes``, ``base.read_head`` and
``base.ParseStats``. Byte offsets are computed on the raw decompressed byte
stream (``offset += len(byte_line)``) so ``event_id`` stays deterministic.

``parse()`` is per file (frozen ``Adapter`` signature): it never stitches
records across rotated siblings. An MCM block split across a rotation boundary
therefore fragments into one event per file (ADR 0006) — "nothing disappears".
Timeline ordering is by each event's own UTC ts downstream, never by the
``.bakNN`` filename suffix.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sift.adapters.base import (
    ConfigurableAdapter,
    ParseStats,
    open_bytes,
    read_head,
    to_utc,
    tz_override_for,
)
from sift.adapters.genericlog import byte_lines
from sift.models import Event, event_id

# Record-accumulation safety caps: on breach the open event closes and a
# severity="unknown" continuation event opens — bounded memory for a
# never-terminated MCM dump (Pitfall 5 / T-05-20). The byte-line splitter
# (with its own MAX_EVENT_BYTES force-split) is shared from genericlog (IN-01)
# to avoid a drifting verbatim copy.
MAX_EVENT_LINES = 256
MAX_EVENT_BYTES = 65536

# Anchored, linear-scan token regexes — no ReDoS (mirrors dedup discipline).
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
_SRCLOC_RE = re.compile(r"\[([A-Za-z]\w*)\.cpp:(\d+)\]")
_ERRCODE_RE = re.compile(r"\b0[xX][0-9A-Fa-f]+\b")
_OID_RE = re.compile(
    r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
    r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b|\b[0-9A-Fa-f]{32}\b"
)
# SID shape is MicroStrategy-version-specific -> [ASSUMED] a labelled 12+ hex
# run (SID=... / SID:...). Anchored on the label so it never collides with the
# GUID OID or a bracketed thread id.
_SID_RE = re.compile(r"\bSID[=:]\s*([0-9A-Fa-f]{12,})\b")
# A purely-numeric bracketed field -> thread (severity/module brackets are
# alphabetic; the source-location bracket carries a dot and colon).
_THREAD_RE = re.compile(r"\[(\d+)\]")
_SEV_TAG_RE = re.compile(r"\[([A-Za-z]+)\]")

_MCM_START = "***** Start of Info Dump *****"
_MCM_END = "***** End of Info Dump *****"
_MCM_SOURCE_RE = re.compile(r"Source=(\S+)")
_MCM_SIZE_RE = re.compile(r"\bSize=(\d+)")

# Exhaustive severity map (Pitfall 4): only the six store-CHECK values, default
# unknown; a severity is never fabricated.
_DSS_SEVERITY = {
    "FATAL": "fatal",
    "SEVERE": "fatal",
    "CRITICAL": "fatal",
    "ERROR": "error",
    "WARNING": "warn",
    "WARN": "warn",
    "INFO": "info",
    "NOTICE": "info",
    "TRACE": "debug",
    "DEBUG": "debug",
}

# Sniff signature: a source-location token or a well-known MicroStrategy string.
#
# The MCM markers are qualified, never the bare substring "MCM" (ADR 0013). A
# DSSPerformanceMonitor PDH-CSV header names the counter `Total MCM Denial` —
# the very counter PERF-05 tracks — so a bare "MCM" made this adapter claim
# every real perfmon CSV at 0.8. `AvailableMCM=` and `MCM Settings:` are both
# DSSErrors-only spellings and appear in no PDH counter path.
_SNIFF_SRCLOC_RE = re.compile(r"\[[A-Za-z]\w*\.cpp:\d+\]")
_SNIFF_STRINGS = (
    "Contract Request Failed",
    "Info Dump",
    "AvailableMCM",
    "MCM Settings",
    "I-Server",
)


def _severity_from(text: str) -> str:
    """First recognised bracketed severity tag; else unknown (never fabricate)."""
    for m in _SEV_TAG_RE.finditer(text):
        sev = _DSS_SEVERITY.get(m.group(1).upper())
        if sev is not None:
            return sev
    return "unknown"


def _match_ts(text: str, override_tz: str | None) -> tuple[int, datetime, str] | None:
    """Return (prefix_end, aware-UTC datetime, ts_confidence) or None.

    An offset-bearing stamp -> ``exact``; a naive stamp -> ``inferred`` after
    the node's ``tz_overrides`` glob is applied through the shared ``to_utc``.
    """
    m = _TS_RE.match(text)
    if m is None:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace(",", "."))
    except ValueError:
        return None
    dt_utc, confidence = to_utc(dt, override_tz)
    return m.end(), dt_utc, confidence


def _mcm_message(raw: str) -> str:
    """Condensed MCM head: title + Source/Size (the verbatim block is ``raw``)."""
    parts = ["MCM Info Dump"]
    src = _MCM_SOURCE_RE.search(raw)
    if src is not None:
        parts.append(f"Source={src.group(1)}")
    size = _MCM_SIZE_RE.search(raw)
    if size is not None:
        parts.append(f"Size={size.group(1)}")
    return " ".join(parts)


@dataclass
class _Record:
    """Accumulator for one in-progress event."""

    offset: int
    line_start: int
    ts: datetime | None
    ts_confidence: str
    severity: str
    is_mcm: bool = False
    is_fallback: bool = False
    component: str | None = None
    thread: str | None = None
    session: str | None = None
    error_code: str | None = None
    oid: str | None = None
    source_loc: str | None = None
    line_end: int = 0
    byte_len: int = 0
    message_lines: list[str] = field(default_factory=list[str])
    raw_parts: list[str] = field(default_factory=list[str])


class DsserrorsAdapter(ConfigurableAdapter):
    """MicroStrategy DSSErrors.log adapter (INGST-08).

    Inherits ``input_root``/``tz_overrides``/``last_stats`` from
    ``ConfigurableAdapter`` — per-run config travels on the instance because
    the frozen ``Adapter`` Protocol carries no config attributes.
    """

    name = "dsserrors"

    def sniff(self, path: Path) -> float:
        head = read_head(path).decode("utf-8", errors="replace")
        if _SNIFF_SRCLOC_RE.search(head) or any(s in head for s in _SNIFF_STRINGS):
            return 0.8
        return 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:  # noqa: C901
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        # Only a real subdirectory (nodeN/DSSErrors.log) names a node; a file
        # placed directly under the case root has parts[0] == the filename, so
        # omit the attr rather than mislabel it (WR-01).
        parts = Path(relpath).parts
        node = parts[0] if len(parts) > 1 else None
        override_tz = tz_override_for(relpath, self.tz_overrides)
        stats = ParseStats(path=relpath)
        current: _Record | None = None
        offset = 0
        line_no = 0

        def finish(rec: _Record) -> Event:
            stats.event_count += 1
            if rec.is_fallback:
                stats.unknown_fallback_bytes += rec.byte_len
            raw = "".join(rec.raw_parts)
            message = _mcm_message(raw) if rec.is_mcm else "\n".join(rec.message_lines)
            attrs: dict[str, str] = {
                "byte_offset": str(rec.offset),
                "byte_len": str(rec.byte_len),
            }
            if node is not None:
                attrs["node"] = node
            if rec.error_code is not None:
                attrs["error_code"] = rec.error_code
            if rec.oid is not None:
                attrs["oid"] = rec.oid
            if rec.source_loc is not None:
                attrs["source_loc"] = rec.source_loc
            return Event(
                event_id=event_id(relpath, rec.offset),
                case_id=case_id,
                ts=rec.ts,
                ts_confidence=rec.ts_confidence,
                source=self.name,
                source_file=relpath,
                line_start=rec.line_start,
                line_end=rec.line_end,
                severity=rec.severity,
                component=rec.component,
                thread=rec.thread,
                session=rec.session,
                message=message,
                attrs=attrs,
                raw=raw,
            )

        def add_line(rec: _Record, text: str, decoded: str, blen: int) -> None:
            rec.message_lines.append(text)
            rec.raw_parts.append(decoded)
            rec.line_end = line_no
            rec.byte_len += blen

        def start_timestamped(
            line_offset: int, text: str, dt_utc: datetime, confidence: str
        ) -> _Record:
            rec = _Record(
                offset=line_offset,
                line_start=line_no,
                ts=dt_utc,
                ts_confidence=confidence,
                severity=_severity_from(text),
            )
            src = _SRCLOC_RE.search(text)
            if src is not None:
                rec.component = src.group(1)
                rec.source_loc = f"{src.group(1)}.cpp:{src.group(2)}"
            errcode = _ERRCODE_RE.search(text)
            if errcode is not None:
                rec.error_code = errcode.group(0)
            oid = _OID_RE.search(text)
            if oid is not None:
                rec.oid = oid.group(0)
            sid = _SID_RE.search(text)
            if sid is not None:
                rec.session = sid.group(1)
            thread = _THREAD_RE.search(text)
            if thread is not None:
                rec.thread = thread.group(1)
            return rec

        with open_bytes(path) as stream:
            # DSSErrors is UTF-8: a plain b"\n" byte split suffices; byte_lines
            # still force-splits a monster line at MAX_EVENT_BYTES (T-05-20).
            for bline in byte_lines(stream, b"\n", b"", unit=1):
                line_offset = offset
                offset += len(bline)  # every byte counted, newline too
                line_no += 1
                decoded = bline.decode("utf-8", errors="replace")
                text = decoded.rstrip("\r\n")
                stripped = text.strip()
                ts_match = _match_ts(text, override_tz)
                # A new record-start (MCM Start sentinel or timestamp line)
                # closes the open event — this also force-closes an
                # unterminated MCM block (Pitfall 5).
                if stripped == _MCM_START:
                    if current is not None:
                        yield finish(current)
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=None,
                        ts_confidence="missing",
                        severity="unknown",
                        is_mcm=True,
                        component="MCM",
                    )
                    add_line(current, text, decoded, len(bline))
                elif ts_match is not None:
                    if current is not None:
                        yield finish(current)
                    prefix_end, dt_utc, confidence = ts_match
                    current = start_timestamped(line_offset, text, dt_utc, confidence)
                    body = text[prefix_end:].lstrip()
                    add_line(current, body, decoded, len(bline))
                elif current is not None and current.is_mcm and stripped == _MCM_END:
                    # End sentinel closes the MCM block (inclusive).
                    add_line(current, text, decoded, len(bline))
                    yield finish(current)
                    current = None
                elif current is not None:
                    # Continuation — unless a safety cap would be breached, in
                    # which case the event closes and a severity="unknown"
                    # continuation event opens (bounded memory, T-05-20).
                    lines_in_event = current.line_end - current.line_start + 1
                    if (
                        lines_in_event >= MAX_EVENT_LINES
                        or current.byte_len + len(bline) > MAX_EVENT_BYTES
                    ):
                        yield finish(current)
                        current = _Record(
                            offset=line_offset,
                            line_start=line_no,
                            ts=None,
                            ts_confidence="missing",
                            severity="unknown",
                            is_fallback=True,
                        )
                    add_line(current, text, decoded, len(bline))
                else:
                    # Leading/interstitial unparseable region -> its own
                    # severity=unknown, ts=None event (counts as fallback).
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=None,
                        ts_confidence="missing",
                        severity="unknown",
                        is_fallback=True,
                    )
                    add_line(current, text, decoded, len(bline))
        if current is not None:
            yield finish(current)
        stats.total_bytes = offset
        self.last_stats = stats
