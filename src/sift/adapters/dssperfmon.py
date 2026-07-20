"""dssperfmon adapter: MicroStrategy DSSPerformanceMonitor PDH-CSV samples.

PERF-01 / PERF-02. One `Event` per sample row — never downsampled, never
capped: a perfmon series is only useful whole, and Phase 13's correlator reads
every point. The PDH header line is metadata, not an Event (D-01).

Parsing uses stdlib ``csv`` on a *single row at a time*; the read loop is
``genericlog.byte_lines`` over the raw decompressed byte stream, so
``offset += len(bline)`` accounts every byte before any decode and ``event_id``
stays deterministic across re-ingest (D-20). No regular expression is imported
anywhere in this module, which discharges the ReDoS surface by construction —
counter names are attacker-influenceable in principle (T-12-01).

**ADR 0012 is binding here.** The header declares a zone and numeric bias
(e.g. ``(Eastern Standard Time)(300)``). Those are recorded into ``attrs`` as
``tz_name``/``tz_offset_min`` and disclosed in ``ParseStats.notes``, and are
never applied as a shift. Timestamps flow only through the shared
``base.to_utc`` seam, byte-for-byte the call shape every other adapter uses, so
a perfmon CSV and its paired DSSErrors log land on one timeline.

Reuses ``base.ConfigurableAdapter`` (``input_root``/``tz_overrides``/
``last_stats``) so per-run config travels on the instance — the frozen
``Adapter`` Protocol carries no config attributes (ADR 0006).
"""

import csv
from collections.abc import Iterator
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

# Anchored literal sniff marker — a byte comparison, no scan and no regex
# (T-12-01). 0.95 sits above dsserrors' 0.8 because the marker is unambiguous:
# detect() scores every adapter against every file (Pitfall 3).
PDH_SNIFF_PREFIX = b'"(PDH-CSV 4.0)'
SNIFF_SCORE = 0.95

# PDH sample stamp, e.g. 04/07/2026 12:39:39.397 — naive, no zone token (D-12).
TS_FORMAT = "%m/%d/%Y %H:%M:%S.%f"

_TZ_NOTE = (
    "PDH header declares timezone {name!r} with bias {bias} minutes; recorded "
    "in Event.attrs as tz_name/tz_offset_min and NOT applied as a shift "
    "(ADR 0012)."
)


def _short_counter_name(path: str) -> str:
    """Final backslash segment of a PDH counter path, unit included (D-02).

    ``\\\\host\\Object(Instance)\\Counter(unit)`` -> ``Counter(unit)``.
    """
    return path.rsplit("\\", 1)[-1]


def _parse_header(columns: list[str]) -> tuple[str, str, str, list[str]]:
    """Return (host, tz_name, tz_offset_min, short_counter_names).

    The zone name and bias are pulled out of ``columns[0]``'s parenthesised
    groups by string partitioning — deliberately not a regex.
    """
    counters = columns[1:]
    names = [_short_counter_name(c) for c in counters]
    host = ""
    for column in counters:
        segments = [s for s in column.split("\\") if s]
        if segments:
            host = segments[0]
            break
    # '(PDH-CSV 4.0) (Eastern Standard Time)(300)'
    #                ^^^^^^^^^^^^^^^^^^^^^^  ^^^
    _, _, after_version = columns[0].partition(")")
    tz_name, _, after_zone = after_version.partition("(")[2].partition(")")
    tz_offset_min = after_zone.partition("(")[2].partition(")")[0]
    return host, tz_name.strip(), tz_offset_min.strip(), names


class DssperfmonAdapter(ConfigurableAdapter):
    """DSSPerformanceMonitor PDH-CSV adapter (PERF-01, PERF-02).

    Inherits ``input_root``/``tz_overrides``/``last_stats`` from
    ``ConfigurableAdapter`` — per-run config travels on the instance because
    the frozen ``Adapter`` Protocol carries no config attributes.
    """

    name = "dssperfmon"

    def sniff(self, path: Path) -> float:
        if read_head(path).startswith(PDH_SNIFF_PREFIX):
            return SNIFF_SCORE
        return 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        override_tz = tz_override_for(relpath, self.tz_overrides)
        stats = ParseStats(path=relpath)
        offset = 0
        line_no = 0
        header: tuple[str, str, str, list[str]] | None = None

        with open_bytes(path) as stream:
            for bline in byte_lines(stream, b"\n", b"", unit=1):
                line_offset = offset
                # Every byte accounted before any decode: no parse outcome may
                # perturb the offset, or event_id stops being reproducible.
                offset += len(bline)
                line_no += 1
                decoded = bline.decode("utf-8", errors="replace")
                text = decoded.rstrip("\r\n")
                if not text.strip():
                    continue
                # stdlib csv parses ONE row; it never owns file iteration.
                row = next(csv.reader([text]))
                if header is None:
                    header = _parse_header(row)
                    stats.notes.append(_TZ_NOTE.format(name=header[1], bias=header[2]))
                    continue
                host, tz_name, tz_offset_min, counter_names = header
                # Naive wall clock -> the shared UTC seam, unshifted (ADR 0012).
                # DTZ007 is suppressed deliberately: a PDH sample stamp carries
                # no zone, and attaching one here would bypass to_utc and the
                # --tz override, which is exactly what ADR 0012 forbids.
                naive = datetime.strptime(row[0], TS_FORMAT)  # noqa: DTZ007
                ts, ts_confidence = to_utc(naive, override_tz)
                values = dict(zip(counter_names, row[1:], strict=False))
                attrs: dict[str, str] = {
                    "byte_offset": str(line_offset),
                    "byte_len": str(len(bline)),
                    "host": host,
                    "pdh_version": "4.0",
                    "tz_name": tz_name,
                    "tz_offset_min": tz_offset_min,
                }
                attrs.update(values)
                stats.event_count += 1
                yield Event(
                    event_id=event_id(relpath, line_offset),
                    case_id=case_id,
                    ts=ts,
                    ts_confidence=ts_confidence,
                    source=self.name,
                    source_file=relpath,
                    line_start=line_no,
                    line_end=line_no,
                    # A counter value is never a severity: the adapter forms no
                    # judgement about magnitude (D-05). Phase 13 does that.
                    severity="info",
                    component=host,
                    thread=None,
                    session=None,
                    message=" ".join(f"{k}={v}" for k, v in values.items()),
                    attrs=attrs,
                    raw=text,
                )
        stats.total_bytes = offset
        self.last_stats = stats
