"""genericlog adapter: timestamped line-based logs (SPEC.md §5.2 adapter #1).

v1 scope (plan 01-03): full timestamp ladder (ISO 8601, syslog RFC3164 with
mtime year inference, epoch seconds/millis, Apache CLF), UTC normalisation
with ``ts_confidence`` and per-glob timezone overrides (D-05), continuation
grouping per D-06.

Byte offsets are computed on the raw decompressed byte stream, never on
decoded text or via ``.tell()`` on a text wrapper — event_id determinism
depends on it.

Per-run configuration travels on the adapter instance (``input_root``,
``tz_overrides``; results in ``last_stats``) because the Adapter protocol
signature is frozen. Set by the ingest orchestrator before ``parse``.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from zoneinfo import ZoneInfo

from sift.adapters.base import ParseStats, open_bytes, read_head
from sift.models import Event, event_id

# Epoch plausibility window: 2000-01-01 .. 2100-01-01 (Pitfall 5 — a bare
# 10/13-digit number is only a timestamp if it lands in a sane era).
EPOCH_MIN = 946684800
EPOCH_MAX = 4102444800

# Anchored ISO 8601 candidate: four-digit year, dashes, T-or-space separator,
# HH:MM:SS, optional fractional seconds and offset/Z. The bounded slice is fed
# to datetime.fromisoformat — never an unanchored substring (Pitfall 5:
# fromisoformat accepts bare "20260716" as a date).
_ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

# syslog RFC3164: "Jul  9 03:14:15" at line start, followed by whitespace.
# Parsed by hand (not strptime) because strptime defaults to year 1900 and
# rejects "Feb 29" outright — the real year comes from file mtime (A3/D-05).
_SYSLOG_RE = re.compile(
    r"^([A-Z][a-z]{2}) {1,2}(\d{1,2}) (\d{2}):(\d{2}):(\d{2})(?=\s)"
)
_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}  # fmt: skip

# Epoch seconds (10 digits, optional fraction) or millis (13 digits) at line
# start, delimiter-terminated so a 16-digit ID never half-matches.
_EPOCH_RE = re.compile(r"^(\d{13}|\d{10}(?:\.\d+)?)(?=\s|$)")

# Apache CLF "16/Jul/2026:14:02:03 +0200", optionally bracketed (A1).
_CLF_RE = re.compile(
    r"^\[?(\d{1,2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]?"
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


def _try_iso(text: str, _mtime: float) -> tuple[int, datetime] | None:
    m = _ISO_RE.match(text)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return m.end(), dt


def _try_syslog(text: str, mtime: float) -> tuple[int, datetime] | None:
    m = _SYSLOG_RE.match(text)
    if not m:
        return None
    month = _MONTHS.get(m.group(1))
    if month is None:
        return None
    mtime_dt = datetime.fromtimestamp(mtime, tz=UTC).replace(tzinfo=None)
    try:
        # Deliberately naive (DTZ001): D-05 routes naive results through
        # to_utc, which applies the tz override or UTC and sets "inferred".
        dt = datetime(  # noqa: DTZ001
            mtime_dt.year,
            month,
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
        )
        # Year-boundary rule (A3): a syslog ts landing more than a day after
        # the file's mtime belongs to the previous year (December logs read
        # in January).
        if dt > mtime_dt + timedelta(days=1):
            dt = dt.replace(year=mtime_dt.year - 1)
    except ValueError:
        return None  # e.g. Feb 29 in a non-leap target year
    return m.end(), dt


def _try_epoch(text: str, _mtime: float) -> tuple[int, datetime] | None:
    m = _EPOCH_RE.match(text)
    if not m:
        return None
    token = m.group(1)
    value = int(token) / 1000.0 if len(token) == 13 else float(token)
    if not (EPOCH_MIN <= value <= EPOCH_MAX):
        return None  # plausibility window (Pitfall 5)
    return m.end(), datetime.fromtimestamp(value, tz=UTC)


def _try_clf(text: str, _mtime: float) -> tuple[int, datetime] | None:
    m = _CLF_RE.match(text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    return m.end(), dt


# Ladder order per RESEARCH Pattern 5. Index 1 (syslog) is the only entry
# whose year is inferred rather than read — parse() discloses its use.
_LADDER: tuple[Callable[[str, float], tuple[int, datetime] | None], ...] = (
    _try_iso,
    _try_syslog,
    _try_epoch,
    _try_clf,
)
_SYSLOG_IDX = 1


def _match_ts(
    text: str, mtime: float, override_tz: str | None, locked: int | None
) -> tuple[int, datetime, str, int] | None:
    """Return (prefix_end, aware-UTC datetime, confidence, ladder index) or None.

    ``locked`` is the per-file format fast path: the last-matched ladder entry
    is tried first, falling back to the full ladder on a miss (deterministic).
    """
    order: Iterator[int] | range
    if locked is None:
        order = range(len(_LADDER))
    else:
        order = iter([locked, *(i for i in range(len(_LADDER)) if i != locked)])
    for i in order:
        result = _LADDER[i](text, mtime)
        if result is None:
            continue
        prefix_end, dt = result
        if dt.tzinfo is not None:
            return prefix_end, dt.astimezone(UTC), "exact", i
        dt_utc, confidence = to_utc(dt, override_tz)
        return prefix_end, dt_utc, confidence, i
    return None


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
        # while the fallback rule still applies (Pattern 2). Any ladder entry
        # counts as a match.
        head = read_head(path).decode("utf-8", errors="replace")
        mtime = path.stat().st_mtime
        return (
            0.1
            if any(_match_ts(line, mtime, None, None) for line in head.splitlines())
            else 0.0
        )

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        override_glob, override_tz = next(
            (
                (glob, tz)
                for glob, tz in self.tz_overrides.items()
                if fnmatch(relpath, glob)
            ),
            (None, None),
        )
        mtime = path.stat().st_mtime
        stats = ParseStats(path=relpath)
        inferred = 0
        syslog_used = False
        locked: int | None = None
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
                parsed = _match_ts(text, mtime, override_tz, locked)
                if parsed is not None:
                    prefix_end, dt_utc, confidence, locked = parsed
                    if confidence == "inferred":
                        inferred += 1
                    if locked == _SYSLOG_IDX:
                        syslog_used = True
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
        # D-05: disclose one note per assumption kind per file.
        if inferred:
            if override_tz is not None:
                stats.notes.append(
                    f"{inferred} naive timestamp(s) assumed {override_tz} "
                    f"(tz_overrides glob {override_glob!r}); ts_confidence=inferred"
                )
            else:
                stats.notes.append(
                    f"{inferred} naive timestamp(s) assumed UTC; "
                    "ts_confidence=inferred"
                )
        if syslog_used:
            stats.notes.append(
                "syslog timestamps: year inferred from file mtime; "
                "ts_confidence=inferred"
            )
        self.last_stats = stats
