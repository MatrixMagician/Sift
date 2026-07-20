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
_NO_TZ_NOTE = (
    "PDH header declares no timezone or bias; tz_name/tz_offset_min omitted "
    "from Event.attrs rather than invented. Timestamps are unaffected — the "
    "declaration is inert metadata either way (ADR 0012)."
)
_DRIFT_NOTE = (
    "line {line}: {seen} columns, expected {expected}; row degraded to "
    "severity='unknown' without realignment (D-16)."
)
_COLLISION_NOTE = (
    "counter short name(s) {names} are claimed by more than one column; those "
    "columns are keyed by their qualified paths ({keys}) so none is dropped "
    "(WR-03). Non-colliding names are unchanged."
)
_CSV_ERROR_NOTE = (
    "line {line}: stdlib csv could not tokenise the row ({detail}); degraded to "
    "severity='unknown' with its bytes preserved verbatim (PERF-02)."
)

# WR-02 / T-13-DOS: one malformed header width can drive one note per data row —
# 13,596 of them on the reference artefact, roughly 1 MB in a single
# parse_coverage meta row and 13,596 lines to the operator's terminal. Each note
# category is bounded to _NOTE_CAP entries plus one honest summary. Capping is
# only safe because the per-event _DRIFT_ATTR marker below is the evidence: the
# note is a file-level disclosure, and the hazard in plan 13-04 reads the marker.
_NOTE_CAP = 10
_NOTE_SUMMARY = "{count} further {category} note(s) suppressed after the first {cap}."
_DRIFT_CATEGORY = "column-drift"
_CSV_ERROR_CATEGORY = "csv-tokenise"

# Per-event drift evidence (WR-05). The file-level _DRIFT_NOTE is a disclosure
# and is capped; this marker is the evidence, and it is what the counter-set
# drift hazard in plan 13-04 cites, because an Event carries an event_id and a
# note does not. Drift is detected once, here at ingest, and never re-detected
# at correlation time — a second detector could disagree with this one (D-15).
_DRIFT_ATTR = "counter_set_drift"
_DRIFT_MARKER = "{seen} columns, expected {expected}"

# Attrs keys this adapter owns. Counter names come from the customer's CSV
# header, so they are attacker-influenceable (see module docstring); a counter
# named "byte_offset" must not be able to overwrite the provenance event_id is
# derived from. Colliding counters are namespaced under _COUNTER_PREFIX rather
# than dropped — nothing disappears silently in either direction.
_RESERVED_ATTRS = frozenset(
    {
        "byte_offset",
        "byte_len",
        "host",
        "pdh_version",
        "tz_name",
        "tz_offset_min",
        "unparsed_columns",
        _DRIFT_ATTR,
    }
)
_COUNTER_PREFIX = "counter."

# Stable join for attrs["unparsed_columns"] — counter names may contain spaces
# and parentheses but never a semicolon.
UNPARSED_SEP = ";"


def _short_counter_name(path: str) -> str:
    """Final backslash segment of a PDH counter path, unit included (D-02).

    ``\\\\host\\Object(Instance)\\Counter(unit)`` -> ``Counter(unit)``.
    """
    return path.rsplit("\\", 1)[-1]


def _qualify_counter_names(counter_paths: list[str]) -> tuple[list[str], list[str]]:
    r"""Resolve counter paths to attrs keys, keeping every colliding column.

    ``dict(zip(names, cells))`` silently discards all but the last column
    sharing a short name — two instances of one object (``Process(MSTRSvr)``
    and ``Process(other)`` both reporting ``Size(MB)``) would leave the
    correlator's figures quietly incomplete with no disclosure anywhere
    (WR-03). Colliding columns are therefore qualified: the key becomes the
    last TWO backslash segments of the path, e.g.
    ``Process(MSTRSvr)\Size(MB)``, falling back to the full counter path only
    if two segments still collide.

    Qualification is applied ONLY to colliding names, precisely so that
    non-colliding keys stay byte-identical and Phase 12's shipped golden
    assertions remain valid. This ordering is load-bearing: plan 13-04's
    counter lookup (``Total MCM Denial``) is written against this key format,
    so the spelling is decided here, before that lookup exists.
    """
    shorts = [_short_counter_name(path) for path in counter_paths]
    colliding = {name for name in shorts if shorts.count(name) > 1}
    if not colliding:
        return shorts, []
    two_segment = ["\\".join(path.rsplit("\\", 2)[-2:]) for path in counter_paths]
    keys = [
        two_segment[i] if short in colliding else short
        for i, short in enumerate(shorts)
    ]
    # Two segments may themselves collide (identical object+counter under
    # different hosts); promote EVERY member of a still-ambiguous group to its
    # full path, not just the ones a mutating ``count()`` happens to catch — the
    # old positional pass rewrote siblings while testing against the list it was
    # editing, so ``[p, p, p]`` collapsed to two keys (CR-01, IN-04).
    ambiguous = {k for k in keys if keys.count(k) > 1}
    keys = [counter_paths[i] if k in ambiguous else k for i, k in enumerate(keys)]
    # Exact-duplicate header columns share even their full path and no spelling
    # can tell them apart; index them so the column survives with a disclosed
    # ``#n`` suffix rather than vanishing under ``dict(zip(...))`` (CR-01).
    seen: dict[str, int] = {}
    for i, k in enumerate(keys):
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1:
            keys[i] = f"{k}#{seen[k]}"
    return keys, [
        _COLLISION_NOTE.format(
            names=", ".join(sorted(colliding)),
            keys=", ".join(
                keys[i] for i, short in enumerate(shorts) if short in colliding
            ),
        )
    ]


def _fallback_event(
    *,
    relpath: str,
    case_id: str,
    line_offset: int,
    line_no: int,
    host: str,
    ts: datetime | None,
    ts_confidence: str,
    attrs: dict[str, str],
    text: str,
) -> Event:
    """Build the ``severity="unknown"`` Event every malformed row degrades to.

    Single funnel for the never-drop guarantee: no caller returns, raises or
    continues past emission, so a malformed row still costs exactly one Event
    with its bytes preserved verbatim and its offset untouched (PERF-02).
    """
    return Event(
        event_id=event_id(relpath, line_offset),
        case_id=case_id,
        ts=ts,
        ts_confidence=ts_confidence,
        source="dssperfmon",
        source_file=relpath,
        line_start=line_no,
        line_end=line_no,
        severity="unknown",
        component=host,
        thread=None,
        session=None,
        message=text,
        attrs=attrs,
        raw=text,
    )


def _bad_cells(names: list[str], values: list[str]) -> list[str]:
    """Short counter names whose cell is blank or not a number (D-14).

    ``float()`` is a validity *probe* only — its result is discarded and the
    cell stays an unconverted string in ``attrs``, so a crafted numeric
    literal cannot alter stored state (D-03, T-12-07).
    """
    bad: list[str] = []
    for name, value in zip(names, values, strict=False):
        try:
            float(value)
        except ValueError:
            bad.append(name)
    return bad


def _parse_header(columns: list[str]) -> tuple[str, str, str, list[str], list[str]]:
    """Return (host, tz_name, tz_offset_min, short_counter_names, notes).

    The zone name and bias are pulled out of ``columns[0]``'s parenthesised
    groups by string partitioning — deliberately not a regex. When either is
    absent the empty string is returned and the caller omits the attr rather
    than inventing a value; ``notes`` carries the disclosure either way. The
    caller owns ``ParseStats``, so the notes travel back rather than the stats
    travelling in.
    """
    counters = columns[1:]
    names, collision_notes = _qualify_counter_names(counters)
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
    tz_name, tz_offset_min = tz_name.strip(), tz_offset_min.strip()
    note = (
        _TZ_NOTE.format(name=tz_name, bias=tz_offset_min)
        if tz_name and tz_offset_min
        else _NO_TZ_NOTE
    )
    return host, tz_name, tz_offset_min, names, [note, *collision_notes]


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
        # Per-category occurrence counts, local to this parse: the cap needs no
        # room in ParseStats' public shape, so the adapter protocol is untouched.
        seen_notes: dict[str, int] = {}

        def note(category: str, text: str) -> None:
            """Append ``text`` unless this category has already spent its cap."""
            seen_notes[category] = seen_notes.get(category, 0) + 1
            if seen_notes[category] <= _NOTE_CAP:
                stats.notes.append(text)

        header: tuple[str, str, str, list[str], list[str]] | None = None
        header_width = 0

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
                #
                # csv.Error is NOT a ValueError, so it would sail past the
                # strptime guard below and out of parse() entirely — taking
                # every remaining row with it and reporting coverage 0.0. A
                # CR-only export reaches here as one force-split monster line
                # and trips exactly that. A row csv cannot tokenise is the case
                # the never-drop guarantee exists for, so it degrades like any
                # other malformed row (PERF-02, T-12-08).
                try:
                    row = next(csv.reader([text]))
                except csv.Error as exc:
                    note(
                        _CSV_ERROR_CATEGORY,
                        _CSV_ERROR_NOTE.format(line=line_no, detail=exc),
                    )
                    stats.event_count += 1
                    stats.unknown_fallback_bytes += len(bline)
                    csv_error_attrs: dict[str, str] = {
                        "byte_offset": str(line_offset),
                        "byte_len": str(len(bline)),
                        "pdh_version": "4.0",
                        "unparsed_columns": "*",
                    }
                    if header is not None:
                        csv_error_attrs["host"] = header[0]
                    yield _fallback_event(
                        relpath=relpath,
                        case_id=case_id,
                        line_offset=line_offset,
                        line_no=line_no,
                        host=header[0] if header is not None else "",
                        # No tokens means no field 0: there is no stamp to
                        # recover, unlike the drift and bad-cell branches.
                        ts=None,
                        ts_confidence="missing",
                        attrs=csv_error_attrs,
                        text=text,
                    )
                    continue
                if header is None:
                    header = _parse_header(row)
                    header_width = len(row)
                    stats.notes.extend(header[4])
                    continue
                host, tz_name, tz_offset_min, counter_names, _ = header
                # Step 0: attempt the stamp BEFORE any fallback branch. A
                # malformed row can still carry a good timestamp, and that is
                # what lets Phase 13 place the surviving evidence on a
                # timeline; D-16 asks for severity="unknown", not for the loss
                # of a ts that parsed cleanly.
                #
                # Naive wall clock -> the shared UTC seam, unshifted (ADR 0012).
                # DTZ007 is suppressed deliberately: a PDH sample stamp carries
                # no zone, and attaching one here would bypass to_utc and the
                # --tz override, which is exactly what ADR 0012 forbids.
                ts: datetime | None
                try:
                    naive = datetime.strptime(row[0], TS_FORMAT)  # noqa: DTZ007
                except ValueError:
                    # D-15, mirroring dsserrors._match_ts's ValueError guard.
                    ts, ts_confidence = None, "missing"
                else:
                    ts, ts_confidence = to_utc(naive, override_tz)
                values = dict(zip(counter_names, row[1:], strict=False))
                attrs: dict[str, str] = {
                    "byte_offset": str(line_offset),
                    "byte_len": str(len(bline)),
                    "host": host,
                    "pdh_version": "4.0",
                }
                # D-16: column drift is disclosed, never realigned, padded or
                # truncated. Recorded per event BEFORE the counter loop, so the
                # reserved-key logic below protects the marker with no second,
                # parallel guard (WR-05, T-13-ATTRKEY).
                drifted = len(row) != header_width
                if drifted:
                    attrs[_DRIFT_ATTR] = _DRIFT_MARKER.format(
                        seen=len(row), expected=header_width
                    )
                # Omitted rather than invented when the header declares neither.
                if tz_name:
                    attrs["tz_name"] = tz_name
                if tz_offset_min:
                    attrs["tz_offset_min"] = tz_offset_min
                # Reserved keys win: a counter named "byte_offset" must not be
                # able to rewrite the provenance event_id derives from. The
                # colliding counter keeps its value under a prefix rather than
                # being dropped, so neither the provenance nor the counter
                # disappears silently.
                for counter_name, counter_value in values.items():
                    key = (
                        f"{_COUNTER_PREFIX}{counter_name}"
                        if counter_name in _RESERVED_ATTRS
                        else counter_name
                    )
                    attrs[key] = counter_value

                if drifted:
                    note(
                        _DRIFT_CATEGORY,
                        _DRIFT_NOTE.format(
                            line=line_no, seen=len(row), expected=header_width
                        ),
                    )
                # D-14: blank or non-numeric cells name themselves and degrade
                # the row; only checked when the columns line up at all.
                bad = [] if drifted else _bad_cells(counter_names, row[1:])
                if bad:
                    attrs["unparsed_columns"] = UNPARSED_SEP.join(bad)

                stats.event_count += 1
                if drifted or bad or ts is None:
                    # The row's bytes count against coverage — silent loss is
                    # observable rather than deniable (PERF-02, T-12-08).
                    stats.unknown_fallback_bytes += len(bline)
                    yield _fallback_event(
                        relpath=relpath,
                        case_id=case_id,
                        line_offset=line_offset,
                        line_no=line_no,
                        host=host,
                        ts=ts,
                        ts_confidence=ts_confidence,
                        attrs=attrs,
                        text=text,
                    )
                    continue
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
        # One honest summary per category that actually overflowed; a category
        # that stayed under the cap says nothing at all.
        for category, count in sorted(seen_notes.items()):
            if count > _NOTE_CAP:
                stats.notes.append(
                    _NOTE_SUMMARY.format(
                        count=count - _NOTE_CAP, category=category, cap=_NOTE_CAP
                    )
                )
        stats.total_bytes = offset
        self.last_stats = stats
