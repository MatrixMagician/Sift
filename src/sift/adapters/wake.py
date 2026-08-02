"""Adapter for Wake snapshots — eBPF incident flight-recorder captures.

Wake (https://github.com/MatrixMagician/Wake) records kernel-level events into a
bounded in-memory ring and persists a self-contained snapshot directory when a
trigger fires. Its snapshot schema is a versioned public contract, documented in
Wake's ``docs/snapshot-format.md``; **this adapter was written from that document
alone**, which is the point of the document existing.

What makes this adapter unlike the others here: its input is a *directory*, not a
line-oriented log. Sift's ``Adapter`` protocol is file-oriented, so the file this
adapter claims is ``events.jsonl.zst`` — the one file that carries events — and it
reads its sibling ``manifest.json`` for the context that turns a bare kernel event
into an attributable one (which trigger, which host, what was dropped).

Two contract properties do real work here and are worth stating up front:

* **Drops are honest.** Wake counts every event it lost at every boundary and
  reports them in the manifest. A snapshot with a non-zero ``userspace_ring``
  count is an *incomplete* record, and a triage engine that silently treated it
  as complete would draw confident conclusions from a gap. Those counts are
  surfaced as a synthetic ``warn`` event (see ``_drop_event``) so they land in
  the case timeline where an analyst — or the LLM — will actually see them.
* **Decode is total.** Wake never discards a record it cannot parse; it emits a
  ``generic`` event carrying the raw payload. This adapter mirrors that: an
  unparseable line becomes a ``severity="unknown"`` event rather than a hole,
  matching Sift's own "nothing disappears silently" rule.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sift.adapters.base import ParseStats, open_bytes
from sift.models import Event, event_id

# The schema versions this adapter understands. Wake's versioning policy says a
# backwards-compatible change (new optional field, new class, new trigger type)
# does not bump this, and that readers must tolerate unknown fields and unknown
# enum-like values. So the check is deliberately a floor-and-ceiling, not an
# equality test, and exceeding it degrades rather than raises.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

EVENTS_FILENAME = "events.jsonl.zst"
MANIFEST_FILENAME = "manifest.json"

# Severity is Sift's vocabulary, not Wake's: Wake records what happened, and
# deciding that an OOM kill is worse than an exec is triage's job. The mapping
# is intentionally conservative — only classes that are *inherently* bad news
# rank above "info", and an event's own fields can promote it further
# (see _severity).
_CLASS_BASE_SEVERITY = {
    "oom": "fatal",
    "signal": "warn",
    "exit": "info",
    "exec": "info",
    "open": "info",
    "connect": "info",
    "generic": "unknown",
}

# Signals that indicate a crash rather than an orderly request to stop. A
# SIGTERM is usually somebody asking politely; a SIGSEGV never is.
_CRASH_SIGNALS = frozenset(
    {"SIGSEGV", "SIGABRT", "SIGBUS", "SIGILL", "SIGFPE", "SIGSYS", "SIGKILL"}
)


class WakeAdapter:
    """Parses a Wake snapshot's ``events.jsonl.zst`` into canonical Events."""

    name = "wake"

    def __init__(self) -> None:
        self.stats: list[ParseStats] = []

    # -- sniffing ----------------------------------------------------------

    def sniff(self, path: Path) -> float:
        """Confidence that ``path`` is a Wake snapshot's event stream.

        The strong signal is structural rather than textual: the file is named
        ``events.jsonl.zst`` and sits beside a ``manifest.json`` that declares a
        ``schema_version`` and Wake's own field set. Content sniffing alone
        would be weak here — zstd-compressed JSONL is not a distinctive shape,
        and decompressing every candidate file to find out would be wasteful.
        """
        if path.name != EVENTS_FILENAME:
            return 0.0

        manifest = path.parent / MANIFEST_FILENAME
        if not manifest.is_file():
            # The right name in the wrong place. Possible but not a snapshot as
            # the contract defines one, so claim it only weakly.
            return 0.2

        try:
            data: Any = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0.2

        manifest_fields = _as_dict(data)
        if not manifest_fields:
            return 0.2

        # Fields the contract says are always present. Requiring several of them
        # avoids claiming some other tool's manifest.json that happens to sit
        # next to a similarly-named file.
        required = {"schema_version", "wake_version", "trigger", "drops"}
        if required.issubset(manifest_fields.keys()):
            return 1.0
        if "schema_version" in manifest_fields and "wake_version" in manifest_fields:
            return 0.8
        return 0.2

    # -- parsing -----------------------------------------------------------

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        """Yield one Event per snapshot line, plus synthetic context events.

        Snapshot events are yielded in file order, which Wake's contract
        guarantees is oldest-first by ``ts``.

        The two synthetic events (trigger, and drops if any) are yielded
        *first* but carry the trigger's firing time, which is at or after every
        other timestamp. So the yielded sequence is deliberately **not**
        monotonic in ``ts``. That is safe because Sift orders by ``ts`` when it
        builds a timeline rather than by arrival, and it is the right trade:
        a consumer streaming this adapter directly sees why the snapshot exists
        and what it is missing before it sees a single event, rather than after
        several hundred thousand of them.
        """
        source_file = self._case_relative(path)
        stats = ParseStats(path=source_file)
        self.stats.append(stats)

        manifest = self._load_manifest(path, stats)

        yield from self._context_events(manifest, source_file, case_id, stats)

        # Streamed rather than read whole: a snapshot from a busy host can hold
        # hundreds of thousands of events, and a triage tool should not need the
        # entire decompressed stream resident to read it.
        offset = 0
        line_no = 0
        with open_bytes(path) as stream:
            for raw_line in stream:
                line_start_offset = offset
                offset += len(raw_line)
                raw_line = raw_line.rstrip(b"\n")
                stats.total_bytes = offset
                if not raw_line.strip():
                    continue
                line_no += 1

                text = raw_line.decode("utf-8", errors="replace")
                try:
                    parsed: Any = json.loads(text)
                    record = _as_dict(parsed)
                    if not record:
                        raise ValueError("event line is not a JSON object")
                except ValueError as exc:
                    # Nothing disappears silently: an unparseable line becomes an
                    # unknown-severity event carrying its own bytes, exactly as
                    # Wake itself does for a record it cannot decode.
                    stats.unknown_fallback_bytes += len(raw_line)
                    stats.event_count += 1
                    yield Event(
                        event_id=event_id(source_file, line_start_offset),
                        case_id=case_id,
                        ts=None,
                        ts_confidence="missing",
                        source=self.name,
                        source_file=source_file,
                        line_start=line_no,
                        line_end=line_no,
                        severity="unknown",
                        component=None,
                        thread=None,
                        session=None,
                        message=f"unparseable Wake event line: {exc}",
                        attrs={"parse_error": str(exc)},
                        raw=text,
                    )
                    continue

                stats.event_count += 1
                yield self._to_event(
                    record, source_file, line_start_offset, line_no, case_id, text
                )

    # -- manifest ----------------------------------------------------------

    def _load_manifest(self, path: Path, stats: ParseStats) -> dict[str, Any]:
        """Read the sibling manifest, degrading to an empty one if unreadable.

        A missing or broken manifest costs attribution and drop reporting, but
        the events themselves are still worth having, so this never raises. The
        loss is disclosed in the parse notes rather than swallowed.
        """
        manifest_path = path.parent / MANIFEST_FILENAME
        try:
            data: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            stats.notes.append(
                f"manifest unreadable ({exc}); events parsed without context"
            )
            return {}

        manifest_data = _as_dict(data)
        if not manifest_data:
            stats.notes.append(
                "manifest is not a JSON object; events parsed without context"
            )
            return {}

        version: Any = manifest_data.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            # Forward compatibility over refusal: the contract says a
            # backwards-compatible change does not bump this, so a higher
            # version most likely still reads. Say so and carry on.
            stats.notes.append(
                f"snapshot schema_version {version!r} is outside the tested set "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}; parsed on a best-effort basis"
            )
        return manifest_data

    def _context_events(
        self,
        manifest: dict[str, Any],
        source_file: str,
        case_id: str,
        stats: ParseStats,
    ) -> Iterator[Event]:
        """Emit the trigger event and, if anything was lost, a drop warning."""
        if not manifest:
            return

        trigger = _as_dict(manifest.get("trigger"))
        fired_at = _parse_ts(trigger.get("fired_at")) or _parse_ts(
            manifest.get("generated_at")
        )

        host = _as_dict(manifest.get("host"))

        attrs = {
            "wake_version": str(manifest.get("wake_version", "")),
            "schema_version": str(manifest.get("schema_version", "")),
            "snapshot_id": str(manifest.get("id", "")),
            "trigger_type": str(trigger.get("type", "")),
            "config_hash": str(manifest.get("config_hash", "")),
            "event_count": str(manifest.get("event_count", "")),
        }
        for key in ("hostname", "kernel_release", "machine"):
            if key in host:
                attrs[key] = str(host[key])
        for key in ("rule", "pid", "unit"):
            if trigger.get(key) not in (None, ""):
                attrs[key] = str(trigger[key])

        reason = str(trigger.get("reason", "")).strip()
        ttype = str(trigger.get("type", "unknown"))
        message = f"Wake snapshot triggered ({ttype})"
        if reason:
            message += f": {reason}"

        stats.event_count += 1
        yield Event(
            event_id=event_id(source_file, -1),
            case_id=case_id,
            ts=fired_at,
            ts_confidence="exact" if fired_at else "missing",
            source=self.name,
            source_file=source_file,
            line_start=0,
            line_end=0,
            # The trigger is why this snapshot exists at all, so it is the one
            # event an analyst should never miss.
            severity="error",
            component=str(trigger.get("unit") or "") or None,
            thread=None,
            session=str(manifest.get("id", "")) or None,
            message=message,
            attrs={k: v for k, v in attrs.items() if v},
            raw=json.dumps(manifest.get("trigger", {}), sort_keys=True),
        )

        drop_event = self._drop_event(manifest, source_file, case_id, fired_at)
        if drop_event is not None:
            stats.event_count += 1
            yield drop_event

    def _drop_event(
        self,
        manifest: dict[str, Any],
        source_file: str,
        case_id: str,
        ts: datetime | None,
    ) -> Event | None:
        """Surface non-zero drop counters as a warning event, or return None.

        This is the adapter's most important behaviour and the reason it reads
        the manifest at all. Wake goes to real trouble to count what it lost;
        a consumer that ignored those counters would turn an honest partial
        record into a silently incomplete one, which is precisely the failure
        both projects are built to avoid.

        ``watch_fanout`` losses are excluded: per the contract they concern a
        live ``wake watch`` client and have no bearing on snapshot completeness.
        """
        drops = _as_dict(manifest.get("drops"))
        if not drops:
            return None

        lost: dict[str, int] = {}
        for boundary, classes in drops.items():
            if boundary == "watch_fanout":
                continue
            for cls, count in _as_dict(classes).items():
                if isinstance(count, int) and count > 0:
                    lost[f"{boundary}.{cls}"] = count

        if not lost:
            return None

        total = sum(lost.values())
        detail = ", ".join(f"{k}={v}" for k, v in sorted(lost.items()))
        return Event(
            event_id=event_id(source_file, -2),
            case_id=case_id,
            ts=ts,
            ts_confidence="exact" if ts else "missing",
            source=self.name,
            source_file=source_file,
            line_start=0,
            line_end=0,
            severity="warn",
            component="wake-drops",
            thread=None,
            session=str(manifest.get("id", "")) or None,
            message=(
                f"This snapshot is incomplete: Wake lost {total} event(s) before "
                f"capture ({detail}). Conclusions drawn from this timeline should "
                f"account for the gap."
            ),
            attrs={k: str(v) for k, v in lost.items()},
            raw=json.dumps(drops, sort_keys=True),
        )

    # -- event conversion --------------------------------------------------

    def _to_event(
        self,
        record: dict[str, Any],
        source_file: str,
        byte_offset: int,
        line_no: int,
        case_id: str,
        raw_text: str,
    ) -> Event:
        """Normalise one Wake event into Sift's canonical Event."""
        cls = str(record.get("class", "generic"))
        ts = _parse_ts(record.get("ts"))

        # Everything Wake knows that Sift's fixed columns cannot hold goes into
        # attrs verbatim, including fields this adapter has never heard of: the
        # contract requires readers to tolerate new fields, and dropping them
        # would lose evidence a future Wake version considered worth recording.
        attrs: dict[str, str] = {}
        for key, value in record.items():
            if key in ("ts", "class", "raw"):
                continue
            if value is None or value == "" or value == []:
                continue
            if isinstance(value, list):
                attrs[key] = " ".join(str(v) for v in cast("list[Any]", value))
            else:
                attrs[key] = str(value)

        return Event(
            event_id=event_id(source_file, byte_offset),
            case_id=case_id,
            ts=ts,
            ts_confidence="exact" if ts else "missing",
            source=self.name,
            source_file=source_file,
            line_start=line_no,
            line_end=line_no,
            severity=_severity(cls, record),
            # The systemd unit is the most useful component key an operator
            # already thinks in; comm is the fallback when there is no unit.
            component=(
                str(record.get("unit") or "")
                or str(record.get("comm") or "")
                or None
            ),
            thread=str(record.get("tid")) if record.get("tid") else None,
            session=str(record.get("cgroup") or "") or None,
            message=_message(cls, record),
            attrs=attrs,
            raw=raw_text,
        )

    @staticmethod
    def _case_relative(path: Path) -> str:
        """Case-relative path, keeping the snapshot directory for context.

        A case can hold several snapshots, and every one of them contains a file
        called ``events.jsonl.zst``; including the parent directory keeps
        ``source_file`` — and therefore ``event_id`` — unique between them.
        """
        return f"{path.parent.name}/{path.name}"


def _as_dict(value: Any) -> dict[str, Any]:
    """Narrow an untrusted JSON value to a dict, or to an empty one.

    The snapshot contract says readers must tolerate the unexpected, so a field
    that should be an object but is not degrades to "absent" rather than
    raising. Collecting that narrowing here keeps it in one place.
    """
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _severity(cls: str, record: dict[str, Any]) -> str:
    """Map a Wake event onto Sift's severity vocabulary.

    Class alone is too coarse: an ``exit`` is routine, but an exit with a
    non-zero code is the thing somebody is investigating. So the base severity
    from the class is promoted by the event's own outcome fields.
    """
    base = _CLASS_BASE_SEVERITY.get(cls, "unknown")

    if cls == "exit":
        if record.get("exit_signal"):
            return "error"
        code = record.get("exit_code")
        if isinstance(code, int) and code != 0:
            return "error"
        return "info"

    if cls == "signal":
        name = str(record.get("signal_name", ""))
        return "error" if name in _CRASH_SIGNALS else "warn"

    if cls in ("open", "connect"):
        # A failed syscall is evidence; a successful one is background. This is
        # what makes "show me everything that failed in the last 90 seconds" a
        # single severity filter rather than a bespoke query.
        ret = record.get("ret")
        if isinstance(ret, int) and ret < 0:
            return "warn"
        return "info"

    return base


def _message(cls: str, record: dict[str, Any]) -> str:
    """Render a human-readable one-line summary.

    Deliberately close to how an engineer would describe the event out loud,
    because this string is what gets embedded, clustered, and shown as evidence
    in a report. The structured fields all survive in ``attrs``, so nothing is
    lost by making this readable rather than exhaustive.
    """
    comm = str(record.get("comm", "")) or "?"
    pid = record.get("pid", "?")

    if cls == "exec":
        argv: Any = record.get("argv")
        if isinstance(argv, list) and argv:
            cmd = " ".join(str(a) for a in cast("list[Any]", argv))
        else:
            cmd = str(record.get("filename", ""))
        suffix = " (argv truncated)" if record.get("argv_truncated") else ""
        return f"exec: {comm}[{pid}] ran {cmd}{suffix}"

    if cls == "exit":
        if record.get("exit_signal"):
            name = record.get("signal_name") or f"signal {record['exit_signal']}"
            return f"exit: {comm}[{pid}] was killed by {name}"
        return f"exit: {comm}[{pid}] exited with code {record.get('exit_code', 0)}"

    if cls == "signal":
        name = record.get("signal_name") or f"signal {record.get('signal', '?')}"
        sender = record.get("sender_pid")
        origin = f" from pid {sender}" if sender else ""
        return f"signal: {name} delivered to {comm}[{pid}]{origin}"

    if cls == "oom":
        rss = record.get("anon_rss_kb")
        detail = f" (anon RSS {rss} kB)" if rss else ""
        return f"oom: {comm}[{pid}] was killed by the OOM killer{detail}"

    if cls == "open":
        path = record.get("path", "?")
        errno = record.get("errno")
        if errno:
            return f"open: {comm}[{pid}] failed to open {path}: {errno}"
        return f"open: {comm}[{pid}] opened {path}"

    if cls == "connect":
        dest = f"{record.get('daddr', '?')}:{record.get('dport', '?')}"
        errno = record.get("errno")
        if errno:
            return f"connect: {comm}[{pid}] failed to connect to {dest}: {errno}"
        transition = ""
        if record.get("old_state") and record.get("new_state"):
            transition = f" [{record['old_state']} -> {record['new_state']}]"
        return f"connect: {comm}[{pid}] connected to {dest}{transition}"

    if cls == "generic":
        why = record.get("decode_error") or "unrecognised record layout"
        kind = record.get("raw_kind")
        kind_text = f" (raw kind {kind})" if kind else ""
        # Wake kept this rather than dropping it; saying so plainly stops a
        # reader assuming it is noise.
        return f"generic: undecoded kernel record retained{kind_text}: {why}"

    return f"{cls}: {comm}[{pid}]"


def _parse_ts(value: Any) -> datetime | None:
    """Parse one of Wake's RFC 3339 UTC timestamps, or return None.

    Wake writes nanosecond precision; Python's ``fromisoformat`` handles at most
    microseconds before 3.11 and is fussy about the count of fractional digits,
    so the fraction is trimmed to six digits rather than risking a parse failure
    that would cost the event its place in the timeline.
    """
    if not isinstance(value, str) or not value:
        return None

    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        rest = tail[len(digits) :]
        text = f"{head}.{digits[:6]:<06}{rest}" if digits else head + rest

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
