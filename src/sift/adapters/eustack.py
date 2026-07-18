"""eustack adapter: MicroStrategy EU-stack / native thread-dump files.

[ASSUMED shape] The 05-02 human-verify checkpoint was resolved
"proceed-on-assumed-shapes": the confirmed format is native elfutils
``eu-stack`` output — ``TID <n>:`` thread headers followed by
``#<N>  0x<ADDR>  <symbol>[ - <lib> <source>:<line>]`` frames — which carries
**no lock / blocked-on info**. The "lock info in attrs" portion of INGST-09 is
therefore satisfied by asserting *absence* (nothing fabricated). If a real
sanitised dump later turns out to be a JVM-style thread dump (with
``waiting to lock`` / ``locked`` lines), lock extraction is a localised
addition — the grouping rule (a thread-header line starts a new event, frames
accrue until the next header or a safety cap) is format-independent.

Reuses ``base.ConfigurableAdapter`` (``input_root``/``tz_overrides``/
``last_stats``), the shared ``base.to_utc``/``base.tz_override_for`` UTC path,
``base.open_bytes``, ``base.read_head`` and ``base.ParseStats``. Byte offsets
are computed on the raw decompressed byte stream (``offset += len(byte_line)``)
so ``event_id`` stays deterministic.

A thread dump carries at most one dump-time timestamp (not per-thread); when
present it stamps *every* thread from the dump, when absent every thread is
``ts=None``/``ts_confidence="missing"`` — per-thread times are never invented.
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

# Record-accumulation safety caps: on breach the open thread closes and a
# severity="unknown" continuation event opens — bounded memory for a
# monster/never-terminated thread block (Pitfall 5 / T-05-30). The byte-line
# splitter (with its own MAX_EVENT_BYTES force-split) is shared from genericlog
# (IN-01) to avoid a drifting verbatim copy.
MAX_EVENT_LINES = 256
MAX_EVENT_BYTES = 65536

# Condensed message: the first few frame symbols (SPEC "condensed top frames").
CONDENSED_FRAMES = 5

# Anchored, linear-scan regexes — no ReDoS.
# Native eu-stack thread header: "TID <n>:".
_TID_RE = re.compile(r"^TID (\d+):")
# Frame: "#<N>  0x<ADDR>  <symbol>[ - <lib> <source>:<line>]".
_FRAME_RE = re.compile(r"^#(\d+)\s+0x([0-9A-Fa-f]+)\s+(.+)$")
# Optional single dump-time header timestamp (ISO 8601, offset -> exact).
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

# Sniff signature: both a TID header AND an eu-stack frame must appear in the
# head, so a bare "TID" mention in prose can never be mistaken for a dump.
_SNIFF_TID_RE = re.compile(r"^TID \d+:", re.MULTILINE)
_SNIFF_FRAME_RE = re.compile(r"^#\d+\s+0x", re.MULTILINE)


def _condense_symbol(frame_body: str) -> str:
    """The bare symbol name for the condensed message — drop any
    ``- <lib> <source>:<line>`` suffix so the message stays signal, not noise.
    """
    return frame_body.split(" - ", 1)[0].strip()


def _match_ts(text: str, override_tz: str | None) -> tuple[datetime, str] | None:
    """Parse a leading ISO 8601 dump-time stamp -> (aware-UTC dt, confidence).

    Offset-bearing -> ``exact``; naive -> ``inferred`` after the file's
    ``tz_overrides`` glob is applied through the shared ``to_utc``.
    """
    m = _TS_RE.match(text)
    if m is None:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace(",", "."))
    except ValueError:
        return None
    dt_utc, confidence = to_utc(dt, override_tz)
    return dt_utc, confidence


@dataclass
class _Record:
    """Accumulator for one in-progress event."""

    offset: int
    line_start: int
    ts: datetime | None
    ts_confidence: str
    severity: str
    is_thread: bool = False
    is_fallback: bool = False
    thread: str | None = None
    line_end: int = 0
    byte_len: int = 0
    message_lines: list[str] = field(default_factory=list[str])
    raw_parts: list[str] = field(default_factory=list[str])
    frames: list[str] = field(default_factory=list[str])


class EustackAdapter(ConfigurableAdapter):
    """MicroStrategy EU-stack / native thread-dump adapter (INGST-09).

    Inherits ``input_root``/``tz_overrides``/``last_stats`` from
    ``ConfigurableAdapter`` — per-run config travels on the instance because
    the frozen ``Adapter`` Protocol carries no config attributes.
    """

    name = "eustack"

    def sniff(self, path: Path) -> float:
        head = read_head(path).decode("utf-8", errors="replace")
        if _SNIFF_TID_RE.search(head) and _SNIFF_FRAME_RE.search(head):
            return 0.8
        return 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        override_tz = tz_override_for(relpath, self.tz_overrides)
        stats = ParseStats(path=relpath)
        current: _Record | None = None
        dump_ts: datetime | None = None
        dump_ts_confidence = "missing"
        offset = 0
        line_no = 0

        def finish(rec: _Record) -> Event:
            stats.event_count += 1
            if rec.is_fallback:
                stats.unknown_fallback_bytes += rec.byte_len
            raw = "".join(rec.raw_parts)
            message = (
                "\n".join(rec.frames) if rec.is_thread else "\n".join(rec.message_lines)
            )
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
                component=None,
                thread=rec.thread,
                session=None,
                message=message,
                attrs={
                    "byte_offset": str(rec.offset),
                    "byte_len": str(rec.byte_len),
                },
                raw=raw,
            )

        def add_line(rec: _Record, text: str, decoded: str, blen: int) -> None:
            rec.message_lines.append(text)
            rec.raw_parts.append(decoded)
            rec.line_end = line_no
            rec.byte_len += blen

        with open_bytes(path) as stream:
            # eu-stack output is UTF-8: a plain b"\n" byte split suffices;
            # byte_lines still force-splits a monster line at MAX_EVENT_BYTES
            # (T-05-30).
            for bline in byte_lines(stream, b"\n", b"", unit=1):
                line_offset = offset
                offset += len(bline)  # every byte counted, newline too
                line_no += 1
                decoded = bline.decode("utf-8", errors="replace")
                text = decoded.rstrip("\r\n")
                tid_match = _TID_RE.match(text)
                if tid_match is not None:
                    # Thread-header line = record-start: closes the open event
                    # (Pitfall 5 also force-closes an unterminated block).
                    if current is not None:
                        yield finish(current)
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=dump_ts,
                        ts_confidence=dump_ts_confidence,
                        severity="unknown",  # thread dumps carry no severity
                        is_thread=True,
                        thread=tid_match.group(1),
                    )
                    add_line(current, text, decoded, len(bline))
                elif current is not None:
                    # Continuation of the thread (a frame) OR of the preamble —
                    # unless a safety cap would be breached, in which case the
                    # event closes and a severity="unknown" continuation opens
                    # (bounded memory, T-05-30).
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
                    if current.is_thread and len(current.frames) < CONDENSED_FRAMES:
                        frame_match = _FRAME_RE.match(text)
                        if frame_match is not None:
                            symbol: str = _condense_symbol(frame_match.group(3))
                            current.frames.append(symbol)
                    elif dump_ts is None and not current.is_thread:
                        # Scan the preamble (before the first thread) for the
                        # single dump-time timestamp that stamps every thread.
                        ts_result = _match_ts(text, override_tz)
                        if ts_result is not None:
                            dump_ts, dump_ts_confidence = ts_result
                else:
                    # Leading preamble/header region before the first thread ->
                    # its own severity=unknown, ts=None fallback event; scan it
                    # for the dump-time timestamp.
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=None,
                        ts_confidence="missing",
                        severity="unknown",
                        is_fallback=True,
                    )
                    add_line(current, text, decoded, len(bline))
                    ts_result = _match_ts(text, override_tz)
                    if ts_result is not None:
                        dump_ts, dump_ts_confidence = ts_result
        if current is not None:
            yield finish(current)
        stats.total_bytes = offset
        self.last_stats = stats
