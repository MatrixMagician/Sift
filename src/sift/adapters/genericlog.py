"""genericlog adapter: timestamped line-based logs (SPEC.md §5.2 adapter #1).

v0 scope (plan 01-02): ISO 8601 timestamps, UTF-8 errors-replace decoding,
continuation grouping per D-06. Plan 01-03 adds the full timestamp ladder,
encodings and per-event caps.

Byte offsets are computed on the raw decompressed byte stream, never on
decoded text or via ``.tell()`` on a text wrapper — event_id determinism
depends on it.

Per-run configuration travels on the adapter instance (``input_root``,
``tz_overrides``; results in ``last_stats``) because the Adapter protocol
signature is frozen. Set by the ingest orchestrator before ``parse``.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from zoneinfo import ZoneInfo

from sift.adapters.base import ParseStats, open_bytes, read_head
from sift.models import Event, event_id

# Anchored ISO 8601 candidate: four-digit year, dashes, T-or-space separator,
# HH:MM:SS, optional fractional seconds and offset/Z. The bounded slice is fed
# to datetime.fromisoformat — never an unanchored substring (Pitfall 5).
_ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

_SEVERITY_RE = re.compile(
    r"\b(FATAL|CRITICAL|CRIT|ERROR|ERR|WARNING|WARN|INFO|NOTICE|DEBUG|TRACE|FINE)\b",
    re.IGNORECASE,
)
_SEVERITY_MAP = {
    "FATAL": "fatal",
    "CRITICAL": "fatal",
    "CRIT": "fatal",
    "ERROR": "error",
    "ERR": "error",
    "WARNING": "warn",
    "WARN": "warn",
    "INFO": "info",
    "NOTICE": "info",
    "DEBUG": "debug",
    "TRACE": "debug",
    "FINE": "debug",
}


def to_utc(dt: datetime, override_tz: str | None) -> tuple[datetime, str]:
    """Normalise to aware UTC, returning (datetime, ts_confidence) per D-05."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC), "exact"
    tz = ZoneInfo(override_tz) if override_tz else UTC
    return dt.replace(tzinfo=tz).astimezone(UTC), "inferred"


def _severity(text: str) -> str:
    """Case-insensitive token scan; never fabricate a severity (RESEARCH A2)."""
    m = _SEVERITY_RE.search(text)
    return _SEVERITY_MAP[m.group(1).upper()] if m else "unknown"


def _match_ts(text: str, override_tz: str | None) -> tuple[int, datetime, str] | None:
    """Return (prefix_end, aware-UTC datetime, confidence) or None."""
    m = _ISO_RE.match(text)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace(",", "."))
    except ValueError:
        return None
    dt_utc, confidence = to_utc(dt, override_tz)
    return m.end(), dt_utc, confidence


@dataclass
class _Record:
    """Accumulator for one in-progress event."""

    offset: int
    line_start: int
    ts: datetime | None
    ts_confidence: str
    severity: str
    line_end: int = 0
    byte_len: int = 0
    message_lines: list[str] = field(default_factory=list[str])
    raw_parts: list[str] = field(default_factory=list[str])


class GenericLogAdapter:
    """Fallback adapter for timestamped line-based logs."""

    name = "genericlog"

    def __init__(self) -> None:
        self.input_root: Path | None = None
        self.tz_overrides: dict[str, str] = {}  # glob -> IANA name (D-05)
        self.last_stats: ParseStats | None = None

    def sniff(self, path: Path) -> float:
        # Low-but-nonzero so genericlog never outcompetes a domain adapter,
        # while the fallback rule still applies (Pattern 2).
        head = read_head(path).decode("utf-8", errors="replace")
        return 0.1 if any(_ISO_RE.match(line) for line in head.splitlines()) else 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        override_tz = next(
            (tz for glob, tz in self.tz_overrides.items() if fnmatch(relpath, glob)),
            None,
        )
        stats = ParseStats(path=relpath)
        inferred = 0
        current: _Record | None = None
        offset = 0
        line_no = 0

        def finish(rec: _Record) -> Event:
            stats.event_count += 1
            if rec.ts is None:
                stats.unknown_fallback_bytes += rec.byte_len
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
                thread=None,
                session=None,
                message="\n".join(rec.message_lines),
                attrs={},
                raw="".join(rec.raw_parts),
            )

        with open_bytes(path) as stream:
            for bline in stream:
                line_offset = offset
                offset += len(bline)  # every byte counted, newline included
                line_no += 1
                decoded = bline.decode("utf-8", errors="replace")
                text = decoded.rstrip("\r\n")
                parsed = _match_ts(text, override_tz)
                if parsed is not None:
                    prefix_end, dt_utc, confidence = parsed
                    if confidence == "inferred":
                        inferred += 1
                    if current is not None:
                        yield finish(current)
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=dt_utc,
                        ts_confidence=confidence,
                        severity=_severity(text[prefix_end:]),
                    )
                    current.message_lines.append(text[prefix_end:].lstrip())
                elif current is not None:
                    # Continuation (D-06): timestamp-less line appends.
                    current.message_lines.append(text)
                else:
                    # Leading unparseable region becomes its own event (D-06).
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=None,
                        ts_confidence="missing",
                        severity="unknown",
                    )
                    current.message_lines.append(text)
                current.line_end = line_no
                current.byte_len += len(bline)
                current.raw_parts.append(decoded)
        if current is not None:
            yield finish(current)
        stats.total_bytes = offset
        if inferred:
            stats.notes.append(
                f"{inferred} naive timestamp(s) assumed "
                f"{override_tz or 'UTC'} (ts_confidence=inferred)"
            )
        self.last_stats = stats
