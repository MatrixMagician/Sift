"""journald adapter: ``journalctl -o json`` export files (SPEC.md §5.2).

One self-contained JSON object per line, UTF-8, newline-separated — no
multi-line grouping and no encoding ladder. Each line becomes exactly one
``Event``: ``__REALTIME_TIMESTAMP`` (µs since epoch) is an authoritative UTC
timestamp, ``PRIORITY`` maps to the six-value severity set, ``_SYSTEMD_UNIT``
to component, ``_PID``/``_COMM`` to attrs, ``_SYSTEMD_INVOCATION_ID`` to
session.

Byte offsets are computed on the raw decompressed byte stream (via
``_byte_lines``, reused from genericlog so a monster single line is force-split
at the same MAX_EVENT_BYTES DoS cap), never on decoded text — ``event_id``
determinism depends on it (a plain and gzip copy of the same export yield
identical ids).

The one genuinely journald-specific piece is ``_field_to_str``: in ``-o json``
a field value is a string, ``null`` (oversized/dropped fields), an array of
byte-integers (binary/non-UTF-8 content), or an array of the above (a field
repeated in the entry). A naive ``str(v)`` would store a Python list repr for
the binary case — the classic journald-JSON bug.

Per-run configuration (``input_root``, results in ``last_stats``) travels on
the ``ConfigurableAdapter`` instance; set by the ingest orchestrator before
``parse``.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sift.adapters.base import ConfigurableAdapter, ParseStats, open_bytes, read_head
from sift.adapters.genericlog import byte_lines
from sift.models import Event, event_id

# syslog severities 0..7 → the six-value store CHECK set; anything else →
# "unknown" (never fabricate a severity that would violate store.py:150).
_PRIORITY_SEVERITY: dict[int, str] = {
    0: "fatal", 1: "fatal", 2: "fatal",   # emerg, alert, crit
    3: "error",                           # err
    4: "warn",                            # warning
    5: "info", 6: "info",                 # notice, info
    7: "debug",                           # debug
}  # fmt: skip

# journald head keys that unambiguously identify a ``-o json`` export.
_SIGNATURE_KEYS = ("__REALTIME_TIMESTAMP", "__CURSOR", "_BOOT_ID")


def _severity(priority: object) -> str:
    """PRIORITY → six-value severity; missing/invalid/out-of-range → unknown."""
    if isinstance(priority, (str, int)):
        try:
            return _PRIORITY_SEVERITY.get(int(priority), "unknown")
        except ValueError:
            return "unknown"
    return "unknown"


def _field_to_str(v: object) -> str | None:
    """Normalise a journald JSON field value to text (Pitfall 1).

    string → verbatim; ``None`` → ``None``; list of byte-ints → decoded via
    ``bytes(...).decode(errors="replace")`` (embedded NUL / invalid UTF-8
    survives, never a list repr); value-array → newline-joined normalised
    parts; int → ``str``.
    """
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        items = cast(list[object], v)
        if items and all(isinstance(x, int) for x in items):
            try:
                return bytes(x for x in items if isinstance(x, int)).decode(
                    "utf-8", errors="replace"
                )
            except ValueError:
                pass  # byte out of 0-255: fall through to value-array join
        return "\n".join(s for x in items if (s := _field_to_str(x)) is not None)
    if isinstance(v, int):
        return str(v)
    return None


class JournaldAdapter(ConfigurableAdapter):
    """``journalctl -o json`` export adapter (INGST-07).

    Inherits ``input_root``/``last_stats`` from ``ConfigurableAdapter`` — config
    travels on the instance because the frozen ``Adapter`` Protocol carries no
    config attributes.
    """

    name = "journald"

    def sniff(self, path: Path) -> float:
        """~0.95 on a journald head (first non-blank line is a JSON object with
        a signature key), else 0.0 — highly discriminative, never collides."""
        head = read_head(path).decode("utf-8", errors="replace")
        for line in head.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj: object = json.loads(stripped)
            except json.JSONDecodeError:
                return 0.0
            if isinstance(obj, dict) and any(k in obj for k in _SIGNATURE_KEYS):
                return 0.95
            return 0.0
        return 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        stats = ParseStats(path=relpath)
        offset = 0
        line_no = 0

        def make_event(
            line_offset: int,
            byte_len: int,
            ts: datetime | None,
            ts_confidence: str,
            severity: str,
            component: str | None,
            session: str | None,
            message: str,
            extra: dict[str, str],
            raw: str,
        ) -> Event:
            attrs = {"byte_offset": str(line_offset), "byte_len": str(byte_len)}
            attrs.update(extra)
            return Event(
                event_id=event_id(relpath, line_offset),
                case_id=case_id,
                ts=ts,
                ts_confidence=ts_confidence,
                source=self.name,
                source_file=relpath,
                line_start=line_no,
                line_end=line_no,
                severity=severity,
                component=component,
                thread=None,
                session=session,
                message=message,
                attrs=attrs,
                raw=raw,
            )

        with open_bytes(path) as stream:
            # nl=b"\n", unit=1: journald is UTF-8 so a plain byte split suffices;
            # byte_lines still force-splits a monster line at MAX_EVENT_BYTES
            # (T-05-10 DoS cap, inherited from genericlog).
            for bline in byte_lines(stream, b"\n", b"", unit=1):
                line_offset = offset
                offset += len(bline)  # every byte counted, newline too
                line_no += 1
                stats.event_count += 1
                text = bline.decode("utf-8", errors="replace")
                raw = text.rstrip("\r\n")
                stripped = text.strip()

                if not stripped:
                    # Blank separator line: no data, so covered (not fallback).
                    yield make_event(
                        line_offset, len(bline), None, "missing", "unknown",
                        None, None, "", {}, raw,
                    )
                    continue

                try:
                    parsed: object = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = None
                if not isinstance(parsed, dict):
                    # Malformed / non-object line → unknown, byte-accounted
                    # (T-05-11: fail-soft, "nothing disappears").
                    stats.unknown_fallback_bytes += len(bline)
                    yield make_event(
                        line_offset, len(bline), None, "missing", "unknown",
                        None, None, stripped, {}, raw,
                    )
                    continue

                fields = cast(dict[str, object], parsed)
                ts, ts_confidence = _parse_ts(fields.get("__REALTIME_TIMESTAMP"))
                extra: dict[str, str] = {}
                pid = _field_to_str(fields.get("_PID"))
                if pid is not None:
                    extra["pid"] = pid
                comm = _field_to_str(fields.get("_COMM"))
                if comm is not None:
                    extra["comm"] = comm
                yield make_event(
                    line_offset,
                    len(bline),
                    ts,
                    ts_confidence,
                    _severity(fields.get("PRIORITY")),
                    _field_to_str(fields.get("_SYSTEMD_UNIT")),
                    _field_to_str(fields.get("_SYSTEMD_INVOCATION_ID")),
                    _field_to_str(fields.get("MESSAGE")) or "",
                    extra,
                    raw,
                )

        stats.total_bytes = offset
        self.last_stats = stats


def _parse_ts(value: object) -> tuple[datetime | None, str]:
    """``__REALTIME_TIMESTAMP`` (µs since epoch) → (aware UTC, "exact");
    absent/invalid → (None, "missing"). A valid entry lacking the field still
    parses — its bytes are covered, not unknown_fallback."""
    if isinstance(value, (str, int)):
        try:
            return datetime.fromtimestamp(int(value) / 1_000_000, tz=UTC), "exact"
        except (ValueError, OverflowError, OSError):
            return None, "missing"
    return None, "missing"
