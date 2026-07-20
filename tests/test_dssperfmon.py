"""dssperfmon adapter tests: PDH-CSV sniff, one-event-per-sample-row parsing,
deterministic byte-offset event ids, and the ADR-0012 recorded-not-applied
timezone rule (selectable via ``pytest -k sniff/row/id/timezone/coverage``).

Fixtures live under tests/fixtures/dssperfmon/. ``hartford_deny_slice.csv`` is
a byte-verbatim cut of a real DSSPerformanceMonitor artefact (header + first 10
and last 10 samples); the real file contains no blank or non-numeric cells, so
malformed cases are authored inline via ``write`` rather than checked in (D-17).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from _perfmon_fixtures import write_collision_csv

from sift.adapters.base import ParseStats
from sift.adapters.dsserrors import DsserrorsAdapter
from sift.adapters.dssperfmon import (
    _DRIFT_ATTR,  # pyright: ignore[reportPrivateUsage] — the per-event drift evidence key under test
    _NOTE_CAP,  # pyright: ignore[reportPrivateUsage] — the bound the cap tests are written against
    _RESERVED_ATTRS,  # pyright: ignore[reportPrivateUsage] — the key set the collision/shadowing guards assert against
    DssperfmonAdapter,
    _qualify_counter_names,  # pyright: ignore[reportPrivateUsage] — the collision-resolution under test (CR-01)
)
from sift.models import Event, event_id

FIXTURES = Path(__file__).parent / "fixtures" / "dssperfmon"

SLICE = "hartford_deny_slice.csv"
HOST = "env-325602laio1use1"


def run_parse(
    root: Path,
    relname: str,
    tz_overrides: dict[str, str] | None = None,
) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = DssperfmonAdapter()
    adapter.input_root = root
    if tz_overrides:
        adapter.tz_overrides = tz_overrides
    events = list(adapter.parse(root / relname, "case1"))
    assert adapter.last_stats is not None
    return events, adapter.last_stats


def assert_span_partition(
    events: list[Event], total_bytes: int, start: int = 0
) -> None:
    """Event byte spans must partition the file: contiguous from ``start``,
    non-overlapping, reaching the total decompressed byte count.

    ``start`` is non-zero for PDH-CSV because the header line is metadata, not
    an Event (D-01), so its bytes precede the first span. Every byte after it
    is still accounted for — nothing disappears silently.
    """
    pos = start
    for e in events:
        assert int(e.attrs["byte_offset"]) == pos, (
            f"gap/overlap at {e.event_id}: span starts at "
            f"{e.attrs['byte_offset']}, expected {pos}"
        )
        pos += int(e.attrs["byte_len"])
    assert pos == total_bytes


def write(root: Path, relname: str, data: bytes) -> Path:
    path = root / relname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# Synthetic two-counter PDH file: the real artefact has no malformed cells
# (D-17), so every fallback case below is authored inline where the defect
# under test is visible in the test body rather than hidden in a fixture.
SYN_HEADER = (
    b'"(PDH-CSV 4.0) (Eastern Standard Time)(300)",'
    b'"\\\\host1\\MSTR Server\\Working set cache RAM usage(MB)",'
    b'"\\\\host1\\MSTR Server\\Total MCM Denial"\n'
)
SYN_NO_ZONE = b'"(PDH-CSV 4.0)",' + SYN_HEADER.split(b",", 1)[1]
GOOD_ROW = b'"04/07/2026 12:39:39.397","266042","1"\n'
CACHE = "Working set cache RAM usage(MB)"


def syn(root: Path, *rows: bytes, header: bytes = SYN_HEADER) -> tuple[Path, int]:
    """Write a synthetic PDH file; return (path, header byte length)."""
    return write(root, "syn.csv", header + b"".join(rows)), len(header)


def run_syn(
    root: Path, *rows: bytes, header: bytes = SYN_HEADER
) -> tuple[list[Event], ParseStats, int]:
    _, header_bytes = syn(root, *rows, header=header)
    events, stats = run_parse(root, "syn.csv")
    assert_span_partition(events, stats.total_bytes, start=header_bytes)
    return events, stats, header_bytes


# --------------------------------------------------- unknown-row fallbacks ---


def test_blank_cell_unknown_fallback(tmp_path: Path) -> None:
    """A blank counter cell degrades the row, it does not drop it (D-14)."""
    row = b'"04/07/2026 12:39:39.397","","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    assert events[0].attrs["unparsed_columns"] == CACHE
    assert events[0].raw == row.decode().rstrip("\n")
    # A bad cell never costs the row its timestamp.
    assert events[0].ts is not None


def test_non_numeric_cell_unknown_fallback(tmp_path: Path) -> None:
    """A non-numeric counter cell takes the same path as a blank one (D-14)."""
    row = b'"04/07/2026 12:39:39.397","N/A","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    assert events[0].attrs["unparsed_columns"] == CACHE
    # The float() attempt is a validity probe only: attrs keep the raw string.
    assert events[0].attrs[CACHE] == "N/A"


def test_bad_timestamp_survives(tmp_path: Path) -> None:
    """An unparseable stamp yields ts None / 'missing', never an exception (D-15)."""
    row = b'"not a timestamp","266042","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    assert events[0].ts is None
    assert events[0].ts_confidence == "missing"
    assert events[0].raw == row.decode().rstrip("\n")
    # Columns that did parse still populate attrs.
    assert events[0].attrs[CACHE] == "266042"


def test_column_drift_unknown(tmp_path: Path) -> None:
    """Column drift is disclosed, not realigned — and keeps a good ts (D-16)."""
    row = b'"04/07/2026 12:39:39.397","266042"\n'
    events, stats, _ = run_syn(tmp_path, row)
    assert len(events) == 1
    assert events[0].severity == "unknown"
    # D-16 asks for the unknown severity, not for the loss of a recoverable ts:
    # Phase 13 still needs somewhere to place this evidence on the timeline.
    assert events[0].ts == datetime(2026, 4, 7, 12, 39, 39, 397000, tzinfo=UTC)
    assert any("expected 3" in note and "2" in note for note in stats.notes)


def test_embedded_newline_two_unknown_events(tmp_path: Path) -> None:
    """A quoted embedded newline splits into two unknown rows, offsets intact.

    Reassembly is deliberately NOT implemented: it would require buffering
    across byte_lines and so compromise the byte-offset contract that
    event_id depends on, for a case the PDH writer cannot actually emit.
    """
    row = b'"04/07/2026 12:39:39.397","2660\n42","1"\n'
    events, _, _ = run_syn(tmp_path, row)
    assert len(events) == 2
    assert [e.severity for e in events] == ["unknown", "unknown"]


def test_header_without_bias_still_parses(tmp_path: Path) -> None:
    """A header declaring no zone/bias omits the attrs rather than inventing them."""
    events, stats, _ = run_syn(tmp_path, GOOD_ROW, header=SYN_NO_ZONE)
    assert len(events) == 1
    assert events[0].severity == "info"
    assert events[0].ts_confidence == "inferred"
    assert "tz_name" not in events[0].attrs
    assert "tz_offset_min" not in events[0].attrs
    assert any("no timezone" in note for note in stats.notes)


def test_parse_coverage(tmp_path: Path) -> None:
    """Unknown-row bytes reach ParseStats, so coverage reflects the loss (PERF-02)."""
    bad = b'"04/07/2026 12:39:40.397","","1"\n'
    events, stats, _ = run_syn(tmp_path, GOOD_ROW, GOOD_ROW, bad)
    assert len(events) == 3
    assert stats.unknown_fallback_bytes == len(bad)
    assert stats.coverage < 1.0


# ------------------------------------------------ paired-artefact alignment ---

MCM_FIXTURES = Path(__file__).parent / "fixtures" / "mcm"
MCM_LOG = "hartford_deny_slice.log"
DENIAL_MARKER = "Contract Request Failed"


def test_csv_aligns_with_paired_log() -> None:
    """ADR 0012: a perfmon CSV and its paired DSSErrors log share one timeline.

    See docs/decisions/0012-perfmon-naive-timestamps.md. The two fixtures are a
    matched pair from the same incident: the CSV's final sample is taken seconds
    before the log's MCM denial. Applying the header's declared 300-minute bias
    would land the CSV roughly five hours *after* the denial.

    A failure here means a timestamp shift has been reintroduced on one side of
    the pair. That defect is invisible to every single-adapter test — they would
    all still pass — and would make Phase 13's episode correlation silently
    return nothing. This is the only test in the phase that reads both artefacts
    together, so it is the only one that can catch it.

    Both adapters run with no tz override, so this exercises the default ingest
    path rather than a configured one.
    """
    csv_events, _ = run_parse(FIXTURES, SLICE)

    log_adapter = DsserrorsAdapter()
    log_adapter.input_root = MCM_FIXTURES
    log_events = list(log_adapter.parse(MCM_FIXTURES / MCM_LOG, "case1"))

    csv_last = max(e.ts for e in csv_events if e.ts is not None)
    # Matched on the denial marker text, not an index, so a re-sliced fixture
    # fails loudly rather than drifting onto the wrong record.
    denials = [
        e.ts for e in log_events if e.ts is not None and DENIAL_MARKER in e.raw
    ]
    assert denials, f"no {DENIAL_MARKER!r} record in {MCM_LOG}"

    lead_in = min(denials) - csv_last
    assert timedelta(0) < lead_in < timedelta(seconds=10), (
        f"CSV/log alignment broke: final sample {csv_last} vs denial "
        f"{min(denials)} (lead-in {lead_in}). A bias shift has been "
        f"reintroduced — see docs/decisions/0012-perfmon-naive-timestamps.md."
    )


# ------------------------------------------------------------------- sniff ---


def test_sniff_pdh_header() -> None:
    adapter = DssperfmonAdapter()
    assert adapter.sniff(FIXTURES / SLICE) == 0.95


def test_sniff_plain_text_zero(tmp_path: Path) -> None:
    path = write(tmp_path, "plain.txt", b"just some prose\nno counters here\n")
    adapter = DssperfmonAdapter()
    assert adapter.sniff(path) == 0.0


# --------------------------------------------------------------------- row ---


def test_one_event_per_sample_row() -> None:
    events, stats = run_parse(FIXTURES, SLICE)
    # The PDH header line is not an Event; every sample row is (D-01).
    assert len(events) == 20
    assert stats.event_count == 20
    for i, e in enumerate(events):
        # Never downsampled, never severity-inferred from counter magnitude.
        assert e.severity == "info"
        assert e.component == HOST
        assert e.thread is None
        assert e.session is None
        assert e.line_start == e.line_end
        assert e.line_start == i + 2  # header is line 1
        assert e.source == "dssperfmon"
        assert e.source_file == SLICE
        assert all(isinstance(v, str) for v in e.attrs.values())


def test_counter_attrs_and_message() -> None:
    events, _ = run_parse(FIXTURES, SLICE)
    first = events[0]
    assert first.attrs["host"] == HOST
    assert first.attrs["pdh_version"] == "4.0"
    # Short counter names are the final backslash segment, unit included (D-02).
    assert "Working set cache RAM usage(MB)" in first.attrs
    assert "Total MCM Denial" in first.attrs
    # Values stay unconverted strings — numeric interpretation is Phase 13's job.
    last = events[-1]
    assert last.attrs["Working set cache RAM usage(MB)"] == "266042"
    assert "Working set cache RAM usage(MB)=266042" in last.message
    assert last.raw.startswith('"04/07/2026 12:39:39.397"')


def test_span_partition_and_coverage() -> None:
    events, stats = run_parse(FIXTURES, SLICE)
    assert stats.total_bytes == (FIXTURES / SLICE).stat().st_size
    header_bytes = len((FIXTURES / SLICE).read_bytes().split(b"\n", 1)[0]) + 1
    assert_span_partition(events, stats.total_bytes, start=header_bytes)
    assert stats.coverage == 1.0


# ---------------------------------------------------------------------- id ---


def test_event_ids_stable_across_reparse() -> None:
    first, _ = run_parse(FIXTURES, SLICE)
    second, _ = run_parse(FIXTURES, SLICE)
    assert [e.event_id for e in first] == [e.event_id for e in second]
    # Ids are the canonical models.event_id over the byte offset, not reinvented.
    assert first[0].event_id == event_id(SLICE, int(first[0].attrs["byte_offset"]))


# ---------------------------------------------------------------- timezone ---


def test_timestamp_utc_and_confidence() -> None:
    """ADR 0012: the naive wall clock is stamped UTC verbatim — no bias shift."""
    events, _ = run_parse(FIXTURES, SLICE)
    last = events[-1]
    assert last.ts == datetime(2026, 4, 7, 12, 39, 39, 397000, tzinfo=UTC)
    assert last.ts_confidence == "inferred"


def test_tz_override_applies() -> None:
    """A --tz glob override reaches base.tz_override_for -> base.to_utc."""
    plain, _ = run_parse(FIXTURES, SLICE)
    shifted, _ = run_parse(FIXTURES, SLICE, {"*": "America/New_York"})
    assert plain[-1].ts != shifted[-1].ts
    # April 2026 is EDT (UTC-4), so the wall clock moves forward four hours.
    assert shifted[-1].ts == datetime(2026, 4, 7, 16, 39, 39, 397000, tzinfo=UTC)


def test_header_zone_recorded_not_applied() -> None:
    events, stats = run_parse(FIXTURES, SLICE)
    for e in events:
        assert e.attrs["tz_name"] == "Eastern Standard Time"
        assert e.attrs["tz_offset_min"] == "300"
    # The declared bias is disclosed once per file, never used in arithmetic.
    assert any("ADR 0012" in note for note in stats.notes)


# ------------------------------------------- csv-tokenise + key-collision ---


def test_cr_only_line_endings_degrade_not_crash(tmp_path: Path) -> None:
    """A row csv cannot tokenise degrades; it never kills the whole parse.

    ``byte_lines`` splits on b"\\n" only, so a CR-only PDH export arrives as
    one very long "line". stdlib csv then raises ``csv.Error`` — which is NOT
    a ValueError, so it slips past the strptime guard and, before this test,
    propagated out of parse() entirely: the file recorded coverage 0.0 and
    event_count 0. Every row vanished, silently, which is precisely what
    PERF-02's never-drop guarantee forbids.
    """
    body = b'"04/07/2026 12:39:39.397","266042","1"\r' * 3
    path = write(tmp_path, "cr.csv", SYN_HEADER.replace(b"\n", b"\r") + body)
    adapter = DssperfmonAdapter()
    adapter.input_root = tmp_path
    events = list(adapter.parse(path, "case1"))
    stats = adapter.last_stats
    assert stats is not None
    # The bytes are accounted for rather than abandoned.
    assert events, "parse yielded nothing — the never-drop guarantee failed"
    assert all(e.severity == "unknown" for e in events)
    assert stats.event_count == len(events)
    assert stats.unknown_fallback_bytes > 0


def test_collision_qualified_keys_retain_both_counters(tmp_path: Path) -> None:
    r"""Two columns sharing one short name are BOTH kept, under distinct keys.

    Before this, ``dict(zip(counter_names, ...))`` silently dropped one of the
    two — the correlator's figures would have been quietly incomplete with no
    disclosure anywhere (WR-03, T-13-DROP).
    """
    path = write_collision_csv(tmp_path)
    events, stats = run_parse(tmp_path, path.name)
    assert len(events) == 3
    attrs = events[0].attrs
    left = "Process(MSTRSvr)\\Size(MB)"
    right = "Process(other)\\Size(MB)"
    assert left in attrs, sorted(attrs)
    assert right in attrs, sorted(attrs)
    # Distinct values prove neither column overwrote the other.
    assert attrs[left] != attrs[right]
    # Non-colliding names are untouched.
    assert attrs["RAM used(MB)"] in {"463900", "463901", "463902"}
    counter_keys = set(attrs) - set(_RESERVED_ATTRS)
    assert len(counter_keys) == 3
    assert any("Size(MB)" in note for note in stats.notes)


def test_three_identical_paths_stay_unique() -> None:
    r"""Three columns with an IDENTICAL full counter path keep three distinct keys.

    The last-resort full-path fallback used to be resolved positionally against a
    list it was mutating, so ``[p, p, p]`` collapsed to two keys and
    ``dict(zip(...))`` then dropped a whole column — the very ``dict(zip)`` drop
    ``_qualify_counter_names`` exists to prevent (CR-01, T-13-DROP).
    """
    p = "\\\\hostA\\Process(MSTRSvr)\\Size(MB)"
    keys, notes = _qualify_counter_names([p, p, p])
    assert len(set(keys)) == len(keys) == 3, keys
    assert notes  # the collision must be disclosed, not silent
    """Phase 12's shipped key spelling is unchanged by the collision fix.

    Asserted against an explicit literal, not a recomputed value: a recomputed
    expectation would move with the implementation and prove nothing.
    """
    events, _ = run_parse(FIXTURES, SLICE)
    counter_keys = sorted(set(events[0].attrs) - set(_RESERVED_ATTRS))
    assert counter_keys == [
        "% CPU time",
        "Element Server Cache(MB)",
        "Memory Used by Change Journal Search (KB)",
        "Memory Used by Cube Element Blocks (KB)",
        "Memory Used by Cube Index Keys (KB)",
        "Memory Used by Cube Rowmaps (KB)",
        "Memory Used by Report Caches (MB)",
        "Number Of Report Cache Swaps",
        "Number of Document Cache Swaps",
        "Number of Intelligent Cube Cache Swaps",
        "Object Server Cache(MB)",
        "Open Project Sessions",
        "Open Sessions",
        "RAM used(MB)",
        "RSS(MB)",
        "Size(MB)",
        "Total CPU",
        "Total MCM Denial",
        "Total Memory Mapped Files Size (MB)",
        "Total size (in MB) of cubes loaded in memory",
        "Total size (in MB) of document caches loaded in memory",
        "Working set cache RAM usage(MB)",
    ]


def test_counter_named_like_reserved_attr_cannot_clobber_provenance(
    tmp_path: Path,
) -> None:
    """A counter named ``byte_offset`` must not overwrite the real offset.

    Counter names come from the customer's CSV header and are therefore
    attacker-influenceable. ``event_id`` is derived from the byte offset, so a
    counter that overwrote ``attrs["byte_offset"]`` would corrupt the
    provenance the evidence appendix renders — while still looking clean.
    The colliding counter is preserved under a prefix, not dropped: nothing
    disappears silently in either direction.
    """
    header = (
        b'"(PDH-CSV 4.0) (Eastern Standard Time)(300)",'
        b'"\\\\host1\\MSTR Server\\byte_offset",'
        b'"\\\\host1\\MSTR Server\\Total MCM Denial"\n'
    )
    events, _, header_bytes = run_syn(tmp_path, GOOD_ROW, header=header)
    assert len(events) == 1
    event = events[0]
    # Provenance survives: the offset is the row's true byte position.
    assert event.attrs["byte_offset"] == str(header_bytes)
    assert event.event_id == event_id("syn.csv", header_bytes)
    # The counter's own value is still retrievable, just namespaced.
    assert event.attrs["counter.byte_offset"] == "266042"


# ------------------------------------------------- per-event drift evidence ---

SHORT_ROW = b'"04/07/2026 12:39:39.397","266042"\n'


def test_drift_marker_in_attrs(tmp_path: Path) -> None:
    """A drifted row carries citable per-event evidence; a good row does not.

    The file-level ``stats.notes`` entry is a disclosure, not evidence: it
    carries no ``event_id`` a hazard could cite, and it is capped. The marker
    is what plan 13-04's counter-set-drift hazard reads (WR-05, D-15).
    """
    events, _, _ = run_syn(tmp_path, GOOD_ROW, SHORT_ROW)
    good, drifted = events
    assert _DRIFT_ATTR not in good.attrs
    assert drifted.severity == "unknown"
    marker = drifted.attrs[_DRIFT_ATTR]
    assert "2" in marker and "3" in marker, marker


def test_drift_marker_survives_note_cap(tmp_path: Path) -> None:
    """Every drifted row keeps its marker however many rows drift.

    The marker lives per event, so bounding ``stats.notes`` cannot destroy the
    evidence — the precise interaction that makes WR-02's cap safe.
    """
    events, _, _ = run_syn(tmp_path, *([SHORT_ROW] * 40))
    assert len(events) == 40
    assert all(_DRIFT_ATTR in e.attrs for e in events)


def test_counter_named_like_drift_marker_cannot_shadow_it(tmp_path: Path) -> None:
    """A counter named after the marker is namespaced, not allowed to shadow it.

    Counter names come from the customer's CSV, so without ``_DRIFT_ATTR`` in
    ``_RESERVED_ATTRS`` a crafted header could rewrite the drift evidence the
    hazard cites while the row still looked clean (T-13-ATTRKEY).
    """
    assert _DRIFT_ATTR in _RESERVED_ATTRS
    header = (
        b'"(PDH-CSV 4.0) (Eastern Standard Time)(300)",'
        b'"\\\\host1\\MSTR Server\\' + _DRIFT_ATTR.encode() + b'",'
        b'"\\\\host1\\MSTR Server\\Total MCM Denial"\n'
    )
    events, _, _ = run_syn(tmp_path, SHORT_ROW, header=header)
    assert len(events) == 1
    attrs = events[0].attrs
    assert attrs[f"counter.{_DRIFT_ATTR}"] == "266042"
    assert "expected" in attrs[_DRIFT_ATTR] or "3" in attrs[_DRIFT_ATTR]


# ------------------------------------------------------- bounded parse notes ---

# A bare CR inside an unquoted field: stdlib csv refuses to tokenise it.
CSV_ERROR_ROW = b"04/07/2026 12:39:39.397,266\r042,1\n"

SUMMARY_MARK = "suppressed"


def notes_matching(stats: ParseStats, needle: str) -> list[str]:
    return [note for note in stats.notes if needle in note]


def test_notes_capped(tmp_path: Path) -> None:
    """A pathological file yields a bounded note list, not one note per row.

    On the real Hartford artefact a single header-width mismatch would mean
    13,596 notes — roughly 1 MB in one ``parse_coverage`` meta row and 13,596
    lines to the operator's terminal (WR-02, T-13-DOS).
    """
    extra = 5
    events, stats, _ = run_syn(tmp_path, *([SHORT_ROW] * (_NOTE_CAP + extra)))
    assert len(notes_matching(stats, "expected 3")) == _NOTE_CAP
    summaries = notes_matching(stats, SUMMARY_MARK)
    assert len(summaries) == 1
    assert str(extra) in summaries[0], summaries[0]
    # The cap bounds the disclosure without destroying the evidence: every
    # drifted event still carries its own citable marker.
    assert all(_DRIFT_ATTR in e.attrs for e in events)


def test_note_cap_is_per_category(tmp_path: Path) -> None:
    """One noisy category cannot consume another's disclosure budget."""
    rows = [SHORT_ROW] * (_NOTE_CAP + 2) + [CSV_ERROR_ROW] * (_NOTE_CAP + 3)
    _, stats = run_parse(tmp_path, syn(tmp_path, *rows)[0].name)
    assert len(notes_matching(stats, "expected 3")) == _NOTE_CAP
    assert len(notes_matching(stats, "could not tokenise")) == _NOTE_CAP
    assert len(notes_matching(stats, SUMMARY_MARK)) == 2


def test_no_summary_note_below_cap(tmp_path: Path) -> None:
    """The summary appears only when suppression actually happened."""
    _, stats, _ = run_syn(tmp_path, *([SHORT_ROW] * (_NOTE_CAP - 1)))
    assert len(notes_matching(stats, "expected 3")) == _NOTE_CAP - 1
    assert notes_matching(stats, SUMMARY_MARK) == []
