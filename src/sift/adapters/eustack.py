"""eustack adapter: MicroStrategy thread-dump files (eu-stack and pstack).

Handles native elfutils ``eu-stack`` output (``TID <n>:`` headers with
``#<N>  0x<ADDR>  <symbol>`` frames), Solaris ``pstack`` output (``lwp#``
headers with ``<addr> <symbol> + <offset>`` frames) and Linux ``pstack`` /
gdb ``thread apply all bt`` output (``Thread <n> (... LWP <n>)`` headers with
``#<N>  0x<ADDR> in <symbol>`` frames). None of the three carries lock or
blocked-on metadata the way a JVM thread dump does, so lock state is inferred
from frames by ``pipeline.eustack``'s rules and nothing is fabricated here.

Every format-specific detail — how a thread header is spelled, where the
thread id lives, what a frame line looks like, what location noise to strip —
lives in ``adapters.threaddump`` as a ``DumpGrammar``, never inline here. The
adapter's own rule is format-independent and unchanged: a thread-header line
starts a new event, frames accrue until the next header or a safety cap.
Adding a format is a new grammar, not an adapter edit.

Reuses ``base.ConfigurableAdapter`` (``input_root``/``tz_overrides``/
``last_stats``), the shared ``base.match_iso_ts``/``base.tz_override_for`` UTC
path, ``base.open_bytes``, ``base.read_head`` and ``base.ParseStats``. Byte offsets
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
    match_iso_ts,
    open_bytes,
    read_head,
    tz_override_for,
)
from sift.adapters.genericlog import MAX_EVENT_BYTES, MAX_EVENT_LINES, byte_lines
from sift.adapters.threaddump import (
    GRAMMARS,
    DumpGrammar,
    eu_symbol,  # the eu-stack grammar's symbol rule, aliased as _condense_symbol below
    grammar_for_header,
)
from sift.adapters.threaddump import (
    iter_frames as iter_frames,  # re-exported: pipeline.eustack imports it from here
)
from sift.models import Event, event_id

# Record-accumulation safety caps: on breach the open thread closes and a
# severity="unknown" continuation event opens — bounded memory for a
# monster/never-terminated thread block (Pitfall 5 / T-05-30). The caps and the
# byte-line splitter (with its own MAX_EVENT_BYTES force-split) are shared from
# genericlog (IN-01) to avoid drifting verbatim copies.

# Condensed message: the first few frame symbols (SPEC "condensed top frames").
CONDENSED_FRAMES = 5

# The optional single dump-time header timestamp (ISO 8601, offset -> exact)
# is matched by the shared base.match_iso_ts.

# Sniff signature: a thread header AND a frame line of the SAME grammar must
# both appear in the head, so a bare "TID" mention in prose, or a stray
# "Thread 1 (...)" line in a log, can never be mistaken for a dump.
#
# `header_fallback` is included, not just `header`: gdb omits the LWP for a
# single-threaded target ("Thread 1 (process 4242):"), which the parse loop
# reads happily via `match_header`. Sniffing on the primary pattern alone made
# detection stricter than parsing, so such a dump parsed correctly if the
# adapter was forced by an override and was silently handed to genericlog
# otherwise. Detection and parsing must recognise the same set of files.
_SNIFF_HEADERS: tuple[tuple[DumpGrammar, re.Pattern[str]], ...] = tuple(
    (grammar, re.compile(pattern.pattern, re.MULTILINE))
    for grammar in GRAMMARS
    for pattern in (grammar.header, grammar.header_fallback)
    if pattern is not None
)
_SNIFF_FRAMES: tuple[tuple[DumpGrammar, re.Pattern[str]], ...] = tuple(
    (grammar, re.compile(grammar.frame.pattern, re.MULTILINE)) for grammar in GRAMMARS
)


# The eu-stack grammar's own symbol rule, re-exported under the name
# ``pipeline.eustack.normalise`` imports. An ALIAS, not a second
# implementation: the adapter, the grammar table and the normaliser therefore
# cannot drift apart on what an eu-stack symbol is (D-08). normalise() stays
# idempotent over an already-extracted symbol because dropping a
# ``- <lib> <source>:<line>`` tail that is not there is a no-op.
_condense_symbol = eu_symbol


def _match_ts(text: str, override_tz: str | None) -> tuple[datetime, str] | None:
    """Parse a leading ISO 8601 dump-time stamp -> (aware-UTC dt, confidence).

    Thin wrapper over the shared ``base.match_iso_ts``, dropping the prefix
    end — the whole line stays in the preamble event, so eustack never slices
    the text at the match boundary.
    """
    parsed = match_iso_ts(text, override_tz)
    if parsed is None:
        return None
    _, dt_utc, confidence = parsed
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
    # The grammar whose header opened this record. Carried per record rather
    # than per file so a concatenation of captures in different formats parses,
    # and so a thread's frames are always read with the grammar that opened it.
    grammar: DumpGrammar | None = None
    line_end: int = 0
    byte_len: int = 0
    # Bytes of an otherwise-fallback preamble that carried genuinely-parsed
    # signal (the dump-time timestamp line) — credited as parsed, not fallback
    # (IN-03), so coverage isn't understated on a region the adapter extracts
    # a real, thread-stamping value from.
    parsed_bytes: int = 0
    message_lines: list[str] = field(default_factory=list[str])
    raw_parts: list[str] = field(default_factory=list[str])
    frames: list[str] = field(default_factory=list[str])


class EustackAdapter(ConfigurableAdapter):
    """MicroStrategy thread-dump adapter: eu-stack and pstack (INGST-09).

    Inherits ``input_root``/``tz_overrides``/``last_stats`` from
    ``ConfigurableAdapter`` — per-run config travels on the instance because
    the frozen ``Adapter`` Protocol carries no config attributes.
    """

    name = "eustack"

    def sniff(self, path: Path) -> float:
        """0.8 when the head holds a thread header AND a frame line of the
        SAME grammar, 0.0 otherwise.

        Requiring both of one grammar is what keeps a log line mentioning
        ``Thread 1 (worker)`` or a prose ``TID`` from scoring: neither is
        accompanied by that grammar's frame lines. Confidence does not vary by
        grammar — a Solaris pstack is exactly as certainly a thread dump as an
        eu-stack capture, and a graded score would only make adapter selection
        depend on which format a customer's tooling emits.
        """
        head = read_head(path).decode("utf-8", errors="replace").removeprefix("\ufeff")
        matched_headers = {
            grammar.name for grammar, pattern in _SNIFF_HEADERS if pattern.search(head)
        }
        if not matched_headers:
            return 0.0
        for grammar, pattern in _SNIFF_FRAMES:
            if grammar.name in matched_headers and pattern.search(head):
                return 0.8
        return 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = self.case_relpath(path)
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
                stats.unknown_fallback_bytes += rec.byte_len - rec.parsed_bytes
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
                    # Which grammar read this thread, so an engineer inspecting
                    # a surprising signature can see whether the file was read
                    # as they expected. Absent on preamble/fallback records,
                    # which no grammar opened.
                    **(
                        {"dump_format": rec.grammar.name}
                        if rec.grammar is not None
                        else {}
                    ),
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
            for bline in byte_lines(stream):
                line_offset = offset
                offset += len(bline)  # every byte counted, newline too
                line_no += 1
                decoded = bline.decode("utf-8", errors="replace")
                if line_no == 1:
                    # A UTF-8 BOM sits on the first line and would otherwise
                    # defeat every anchored header pattern, so a dump saved on
                    # Windows would yield zero threads and fall to genericlog
                    # with full reported coverage. Stripped AFTER the byte
                    # accounting above, so byte_offset/byte_len and therefore
                    # event_id stay computed over the raw stream (genericlog's
                    # own Pitfall 7 rule, applied here).
                    decoded = decoded.removeprefix("\ufeff")
                text = decoded.rstrip("\r\n")
                header_grammar = grammar_for_header(text)
                if header_grammar is not None:
                    # Thread-header line = record-start: closes the open event
                    # (Pitfall 5 also force-closes an unterminated block). The
                    # grammar that recognised the header is carried on the
                    # record, so this thread's frames are read with the same
                    # grammar that opened it — never re-detected per line, and
                    # never leaked into the next thread's block.
                    thread_id = header_grammar.match_header(text)
                    if current is not None:
                        yield finish(current)
                    current = _Record(
                        offset=line_offset,
                        line_start=line_no,
                        ts=dump_ts,
                        ts_confidence=dump_ts_confidence,
                        severity="unknown",  # thread dumps carry no severity
                        is_thread=True,
                        thread=thread_id,
                        grammar=header_grammar,
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
                    if (
                        current.is_thread
                        and current.grammar is not None
                        and len(current.frames) < CONDENSED_FRAMES
                    ):
                        frame_match = current.grammar.frame.match(text)
                        if frame_match is not None:
                            symbol: str = current.grammar.symbol(
                                frame_match.group(current.grammar.body_group)
                            )
                            current.frames.append(symbol)
                    elif dump_ts is None and not current.is_thread:
                        # Scan the preamble (before the first thread) for the
                        # single dump-time timestamp that stamps every thread.
                        ts_result = _match_ts(text, override_tz)
                        if ts_result is not None:
                            dump_ts, dump_ts_confidence = ts_result
                            current.parsed_bytes += len(bline)  # credited (IN-03)
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
                        current.parsed_bytes += len(bline)  # credited (IN-03)
        if current is not None:
            yield finish(current)
        stats.total_bytes = offset
        self.last_stats = stats
