"""Walking-skeleton end-to-end test.

Deliberately RED at the end of plan 01-01: the CLI bodies are stubs that exit 1.
Plan 01-02 implements new/ingest/show and turns this green. Do not xfail/skip.
Plan 01-04 adds the CLI hardening tests (precedence, sanitisation, empty-input,
adapter overrides, tz wiring).
"""

import gzip
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift.adapters import REGISTRY
from sift.adapters.genericlog import GenericLogAdapter
from sift.cli import app
from sift.config import load_config
from sift.models import Event
from sift.store import CaseStore, case_db_path


def _read_coverage_meta(case: str) -> dict[str, dict[str, object]]:
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        return json.loads(store.get_meta("parse_coverage") or "{}")
    finally:
        store.close()

runner = CliRunner()

# Three ISO 8601 timestamped entries (mixed severities in the message text),
# with one indented continuation line under the second entry.
FIXTURE_LOG = (
    "2026-07-16T10:00:00+00:00 INFO service started\n"
    "2026-07-16T10:00:01+00:00 ERROR connection pool exhausted\n"
    "    at pool.acquire (worker thread 7)\n"
    "2026-07-16T10:00:02+00:00 WARN retrying with backoff\n"
)


def _make_case(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(FIXTURE_LOG, encoding="utf-8")
    return input_dir


def test_reingest_adds_zero_events(tmp_path: Path) -> None:
    input_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert result.exit_code == 0, result.output

    first = runner.invoke(app, ["ingest", "demo"])
    assert first.exit_code == 0, first.output
    assert "3 new" in first.output

    second = runner.invoke(app, ["ingest", "demo"])
    assert second.exit_code == 0, second.output
    assert "0 new" in second.output

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    event_ids = set(re.findall(r"\b[0-9a-f]{16}\b", shown.output))
    assert len(event_ids) == 3, "row count changed after re-ingest"


def test_walking_skeleton_happy_path(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(FIXTURE_LOG, encoding="utf-8")

    result = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert "app.log" in result.output
    assert re.search(r"\d+(?:\.\d+)?\s*%", result.output), (
        f"expected a coverage percentage in ingest output: {result.output!r}"
    )

    result = runner.invoke(app, ["show", "demo", "events"])
    assert result.exit_code == 0, result.output
    event_ids = set(re.findall(r"\b[0-9a-f]{16}\b", result.output))
    assert len(event_ids) == 3, (
        f"expected three 16-char hex event IDs, got {sorted(event_ids)}"
    )
    assert "connection pool exhausted" in result.output


# --- plan 01-04: CLI hardening -------------------------------------------


def test_data_dir_flag_beats_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-01 flags layer end-to-end: --data-dir wins over SIFT_DATA_DIR."""
    input_dir = _make_case(tmp_path)
    env_dir = tmp_path / "env-data"
    flag_dir = tmp_path / "flag-data"
    monkeypatch.setenv("SIFT_DATA_DIR", str(env_dir))

    result = runner.invoke(
        app,
        ["new", "demo", "--input", str(input_dir), "--data-dir", str(flag_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (flag_dir / "cases" / "demo" / "case.db").exists()
    assert not (env_dir / "cases" / "demo" / "case.db").exists()

    result = runner.invoke(app, ["ingest", "demo", "--data-dir", str(flag_dir)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app, ["show", "demo", "events", "--data-dir", str(flag_dir)]
    )
    assert result.exit_code == 0, result.output
    assert "connection pool exhausted" in result.output


def test_show_strips_terminal_escapes(tmp_path: Path) -> None:
    """T-04-01: an ESC byte in log content never reaches the terminal."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(
        "2026-07-16T10:00:00+00:00 ERROR \x1b[31mred alert\x1b[0m\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "\x1b" not in shown.output
    assert "red alert" in shown.output


def test_ingest_skips_symlinks_loudly_never_follows(tmp_path: Path) -> None:
    """WR-02: a symlink inside the bundle must never pull outside content
    into the case DB; the skip is loud and lands in the coverage meta."""
    input_dir = _make_case(tmp_path)
    secret = tmp_path / "outside-secret.log"
    secret.write_text(
        "2026-07-16T10:00:00+00:00 ERROR super secret outside content\n",
        encoding="utf-8",
    )
    (input_dir / "link.log").symlink_to(secret)
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0

    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert "SKIP link.log: symlink (not followed)" in result.output

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "super secret" not in shown.output

    cov = _read_coverage_meta("demo")
    assert cov["link.log"]["skipped"] == "symlink (not followed)"


def test_hostile_filename_escapes_never_reach_terminal(tmp_path: Path) -> None:
    """CR-02 / T-04-01: an ESC byte in a *filename* is stripped at render time
    in both ingest and show output (filenames are untrusted bundle bytes)."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "\x1b[31mEVIL\x1b[0m.log").write_text(FIXTURE_LOG, encoding="utf-8")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0

    ingested = runner.invoke(app, ["ingest", "demo"])
    assert ingested.exit_code == 0, ingested.output
    assert "\x1b" not in ingested.output
    assert "EVIL" in ingested.output

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "\x1b" not in shown.output
    assert "EVIL" in shown.output


def test_ingest_corrupt_compressed_file_fails_loudly_but_continues(
    tmp_path: Path,
) -> None:
    """CR-01: a corrupt archive errors per-file; other files still ingest.

    Detection decompresses file heads, so a truncated .gz raises during
    detect — that must not abort the whole run and roll back good files.
    """
    input_dir = _make_case(tmp_path)
    (input_dir / "truncated.log.gz").write_bytes(b"\x1f\x8b\x08\x00cut")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0

    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 1, result.output
    assert "ERROR truncated.log.gz" in result.output
    assert "3 new" in result.output  # the good file's events survive

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output


def test_failed_file_recorded_in_parse_coverage_meta(tmp_path: Path) -> None:
    """WR-04: a failed file must appear in the persisted parse_coverage
    record, not just in stdout — later phases read the meta, not the log."""
    input_dir = _make_case(tmp_path)
    (input_dir / "truncated.log.gz").write_bytes(b"\x1f\x8b\x08\x00cut")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 1

    cov = _read_coverage_meta("demo")
    assert "app.log" in cov  # the good file
    entry = cov["truncated.log.gz"]
    assert entry["event_count"] == 0
    assert entry["coverage"] == 0.0
    assert entry["error"]  # non-empty failure description


def test_show_strips_bidi_and_zero_width_characters(tmp_path: Path) -> None:
    """WR-06 / T-04-01: Unicode format characters (bidi overrides, zero-width)
    in log content must not reach the terminal — they can visually reorder or
    hide rendered triage output."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(
        "2026-07-16T10:00:00+00:00 ERROR \u202erevoked\u202c access"
        " zero\u200bwidth\ufeff end\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    for ch in ("\u202e", "\u202c", "\u200b", "\ufeff"):
        assert ch not in shown.output
    assert "revoked" in shown.output
    assert "zerowidth" in shown.output


def test_new_warns_but_creates_on_empty_input_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty-input"
    empty.mkdir()
    result = runner.invoke(app, ["new", "demo", "--input", str(empty)])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.output


def test_ingest_empty_input_dir_reports_zero_files_exit_0(tmp_path: Path) -> None:
    empty = tmp_path / "empty-input"
    empty.mkdir()
    assert runner.invoke(app, ["new", "demo", "--input", str(empty)]).exit_code == 0
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert "0 files" in result.output


def test_new_refuses_to_overwrite_existing_case(tmp_path: Path) -> None:
    """WR-03: re-running `new` must not silently repoint an existing case
    at a different snapshot (mixed-snapshot corruption).

    Also the plan 02-02 acceptance pin: creating a case whose name already
    exists exits 1 containing 'already exists' — Phase 1 behaviour preserved
    at scale, no silent overwrite."""
    input_dir = _make_case(tmp_path)
    other_dir = tmp_path / "other-input"
    other_dir.mkdir()
    (other_dir / "b.log").write_text(FIXTURE_LOG, encoding="utf-8")

    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    second = runner.invoke(app, ["new", "demo", "--input", str(other_dir)])
    assert second.exit_code == 1, second.output
    assert "already exists" in second.output


def test_new_missing_input_dir_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["new", "demo", "--input", str(tmp_path / "does-not-exist")]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_unknown_adapter_name_fails_listing_registered(tmp_path: Path) -> None:
    input_dir = _make_case(tmp_path)
    result = runner.invoke(
        app,
        ["new", "demo", "--input", str(input_dir), "--adapter", "*.log=nope"],
    )
    assert result.exit_code != 0
    assert "genericlog" in result.output


def test_adapter_flag_beats_overlapping_config_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-01 / D-08: --adapter wins over config.adapters even when the globs
    overlap without being byte-identical (flag globs must match first)."""

    class _RecordingAdapter:
        name = "recording"

        def __init__(self) -> None:
            self.parsed: list[str] = []

        def sniff(self, path: Path) -> float:
            return 0.0

        def parse(self, path: Path, case_id: str) -> Iterator[Event]:
            self.parsed.append(path.name)
            yield from ()

    fake = _RecordingAdapter()
    monkeypatch.setitem(REGISTRY, "recording", fake)

    cfg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        '[adapters]\n"*.log" = "genericlog"\n', encoding="utf-8"
    )
    input_dir = _make_case(tmp_path)
    created = runner.invoke(
        app,
        ["new", "demo", "--input", str(input_dir), "--adapter", "app.log=recording"],
    )
    assert created.exit_code == 0, created.output

    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert fake.parsed == ["app.log"], (
        "flag override lost to an overlapping config glob"
    )


def test_config_timezones_reach_adapter_and_events(tmp_path: Path) -> None:
    """D-05 wiring: config.timezones -> adapter.tz_overrides -> event UTC value."""
    cfg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        '[timezones]\n"node1/*" = "Europe/Berlin"\n', encoding="utf-8"
    )
    input_dir = tmp_path / "input"
    (input_dir / "node1").mkdir(parents=True)
    # Naive timestamp, January: Berlin is UTC+1, so 10:00 local == 09:00 UTC.
    (input_dir / "node1" / "app.log").write_text(
        "2026-01-15 10:00:00 INFO naive line under tz override\n", encoding="utf-8"
    )

    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output

    generic = REGISTRY["genericlog"]
    assert isinstance(generic, GenericLogAdapter)
    assert generic.tz_overrides == {"node1/*": "Europe/Berlin"}

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert "2026-01-15T09:00:00+00:00" in shown.output


# --- plan 02-02: portability + progress regression (STORE-01, CLI-03) ------


def test_case_dir_contains_only_case_db_after_clean_run(tmp_path: Path) -> None:
    """STORE-01 / Pitfall 4: after a clean CLI run no -wal/-shm sidecars
    survive, so the case directory is the deletable unit."""
    input_dir = _make_case(tmp_path)
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    case_dir = load_config().data_dir / "cases" / "demo"
    assert sorted(p.name for p in case_dir.iterdir()) == ["case.db"]


def test_deleting_case_directory_deletes_the_case(tmp_path: Path) -> None:
    """STORE-01: rmtree of data_dir/cases/<name>/ removes the case entirely;
    a subsequent show exits 1 with the does-not-exist error."""
    input_dir = _make_case(tmp_path)
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    case_dir = load_config().data_dir / "cases" / "demo"
    shutil.rmtree(case_dir)
    assert not case_dir.exists()

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 1, shown.output
    assert "does not exist" in shown.output


def test_ingest_stdout_contract_unchanged_off_terminal(tmp_path: Path) -> None:
    """CLI-03 regression guard: progress renders on stderr only, so on
    non-TTY runs (CliRunner, CI, pipes) stdout keeps the per-file coverage
    lines and the Total/Template-groups lines. Passes before AND after the
    batched-streaming change — do not xfail."""
    input_dir = _make_case(tmp_path)
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0

    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert re.search(
        r"^app\.log  coverage \d+\.\d%  3 events  3 new$", result.output, re.MULTILINE
    ), result.output
    assert re.search(r"^Total: 3 new events$", result.output, re.MULTILINE)
    assert re.search(r"^Template groups: \d+$", result.output, re.MULTILINE)


# --- plan 02-01: show clusters (STORE-04, CLUS-01) -------------------------

# Three lines differing only in a volatile number (one template group of
# count 3) plus one distinct line (count 1).
REPETITIVE_LOG = (
    "2026-07-16T10:00:00+00:00 ERROR connection pool exhausted after 3 retries\n"
    "2026-07-16T10:00:01+00:00 ERROR connection pool exhausted after 17 retries\n"
    "2026-07-16T10:00:02+00:00 ERROR connection pool exhausted after 99 retries\n"
    "2026-07-16T10:00:03+00:00 INFO service started\n"
)


def test_show_clusters_e2e(tmp_path: Path) -> None:
    """new -> ingest -> show clusters renders template groups end-to-end."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(REPETITIVE_LOG, encoding="utf-8")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0

    ingested = runner.invoke(app, ["ingest", "demo"])
    assert ingested.exit_code == 0, ingested.output
    assert re.search(r"^Template groups: \d+$", ingested.output, re.MULTILINE), (
        f"expected a 'Template groups: N' line in ingest output: {ingested.output!r}"
    )

    shown = runner.invoke(app, ["show", "demo", "clusters"])
    assert shown.exit_code == 0, shown.output
    # A 16-hex template_id line carrying the count-3 group.
    assert re.search(r"^[0-9a-f]{16}\s+3\s", shown.output, re.MULTILINE), shown.output
    # An indented exemplars line with 16-hex event ids.
    assert re.search(
        r"^\s+exemplars: [0-9a-f]{16}( [0-9a-f]{16})*$", shown.output, re.MULTILINE
    ), shown.output


def test_show_clusters_empty_case_exits_0(tmp_path: Path) -> None:
    """A case with zero events renders an empty listing — no crash."""
    empty = tmp_path / "empty-input"
    empty.mkdir()
    assert runner.invoke(app, ["new", "demo", "--input", str(empty)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(app, ["show", "demo", "clusters"])
    assert shown.exit_code == 0, shown.output
    assert not re.search(r"\b[0-9a-f]{16}\b", shown.output)


def test_show_clusters_ordering(tmp_path: Path) -> None:
    """Groups render by count DESC, tie-break on template text ASC."""
    lines: list[str] = []
    second = 0
    for msg, n in [
        ("gamma repeated event", 3),
        ("beta thing done", 2),
        ("alpha thing done", 2),
    ]:
        for _ in range(n):
            lines.append(f"2026-07-16T10:00:{second:02d}+00:00 INFO {msg}")
            second += 1
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(app, ["show", "demo", "clusters"])
    assert shown.exit_code == 0, shown.output
    out = shown.output
    assert (
        out.index("gamma repeated event")
        < out.index("alpha thing done")
        < out.index("beta thing done")
    ), out


def test_show_clusters_strips_terminal_escapes(tmp_path: Path) -> None:
    """T-02-02: hostile log bytes in templates never reach the terminal."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(
        "2026-07-16T10:00:00+00:00 ERROR \x1b[31mred alert\x1b[0m\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(app, ["show", "demo", "clusters"])
    assert shown.exit_code == 0, shown.output
    assert "\x1b" not in shown.output
    assert "red alert" in shown.output


# --- plan 02-03: show --filter (STORE-04) -----------------------------------

EVENT_FILTER_KEYS = ("severity", "source", "file", "since", "until", "limit")
CLUSTER_FILTER_KEYS = ("severity", "min-count", "contains", "limit")
SEVERITIES = ("fatal", "error", "warn", "info", "debug", "unknown")


def _ingested_case(tmp_path: Path, content: str = FIXTURE_LOG) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(content, encoding="utf-8")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0


def test_show_events_output_matches_query_events_rendering(tmp_path: Path) -> None:
    """Safety net for the 02-03 streaming rewrite: unfiltered `show events`
    lines must stay byte-identical to the rendering derived from
    query_events(). Passes before AND after the rewrite — do not xfail."""
    _ingested_case(tmp_path)

    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        expected = [
            (
                f"{e.event_id}  "
                f"{e.ts.isoformat() if e.ts is not None else '-'}  "
                f"{e.severity:<7}  {e.source_file}:{e.line_start}  "
                f"{e.message.replace(chr(10), ' ')[:120]}"
            )
            for e in store.query_events()
        ]
    finally:
        store.close()

    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 0, shown.output
    assert shown.output.splitlines() == expected


def test_show_events_filter_severity(tmp_path: Path) -> None:
    _ingested_case(tmp_path)
    shown = runner.invoke(
        app, ["show", "demo", "events", "--filter", "severity=error"]
    )
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output
    assert "service started" not in shown.output
    assert "retrying with backoff" not in shown.output


def test_show_events_filters_and_combine(tmp_path: Path) -> None:
    """Two --filter options AND-combine (severity AND file)."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(FIXTURE_LOG, encoding="utf-8")
    (input_dir / "other.log").write_text(
        "2026-07-16T10:00:05+00:00 ERROR database on fire\n", encoding="utf-8"
    )
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0

    shown = runner.invoke(
        app,
        [
            "show", "demo", "events",
            "--filter", "severity=error",
            "--filter", "file=app",
        ],
    )
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output
    assert "database on fire" not in shown.output
    assert "service started" not in shown.output


def test_show_events_filter_limit(tmp_path: Path) -> None:
    _ingested_case(tmp_path)
    shown = runner.invoke(app, ["show", "demo", "events", "--filter", "limit=1"])
    assert shown.exit_code == 0, shown.output
    assert len(re.findall(r"\b[0-9a-f]{16}\b", shown.output)) == 1


def test_show_events_filter_since_naive_treated_as_utc(tmp_path: Path) -> None:
    """A naive since/until value is treated as UTC and normalised before
    binding — 10:00:01 excludes only the 10:00:00 event."""
    _ingested_case(tmp_path)
    shown = runner.invoke(
        app, ["show", "demo", "events", "--filter", "since=2026-07-16T10:00:01"]
    )
    assert shown.exit_code == 0, shown.output
    assert "service started" not in shown.output
    assert "connection pool exhausted" in shown.output
    assert "retrying with backoff" in shown.output


def test_show_events_unknown_filter_key_exits_2_listing_keys(tmp_path: Path) -> None:
    _ingested_case(tmp_path)
    shown = runner.invoke(app, ["show", "demo", "events", "--filter", "bogus=1"])
    assert shown.exit_code == 2, shown.output
    for key in EVENT_FILTER_KEYS:
        assert key in shown.output, f"{key!r} missing from: {shown.output!r}"


def test_show_clusters_unknown_filter_key_exits_2_listing_keys(tmp_path: Path) -> None:
    _ingested_case(tmp_path)
    shown = runner.invoke(app, ["show", "demo", "clusters", "--filter", "bogus=1"])
    assert shown.exit_code == 2, shown.output
    for key in CLUSTER_FILTER_KEYS:
        assert key in shown.output, f"{key!r} missing from: {shown.output!r}"


def test_show_clusters_filter_min_count(tmp_path: Path) -> None:
    _ingested_case(tmp_path, REPETITIVE_LOG)
    shown = runner.invoke(
        app, ["show", "demo", "clusters", "--filter", "min-count=2"]
    )
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output
    assert "service started" not in shown.output


def test_show_clusters_filter_contains_literal(tmp_path: Path) -> None:
    """contains matches template substrings literally — a LIKE-style %
    wildcard pattern matches nothing (instr semantics, T-02-08)."""
    _ingested_case(tmp_path, REPETITIVE_LOG)
    shown = runner.invoke(
        app, ["show", "demo", "clusters", "--filter", "contains=pool"]
    )
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output
    assert "service started" not in shown.output

    wildcard = runner.invoke(
        app, ["show", "demo", "clusters", "--filter", "contains=connection%retries"]
    )
    assert wildcard.exit_code == 0, wildcard.output
    assert not re.findall(r"\b[0-9a-f]{16}\b", wildcard.output)


def test_show_clusters_filter_severity(tmp_path: Path) -> None:
    _ingested_case(tmp_path, REPETITIVE_LOG)
    shown = runner.invoke(
        app, ["show", "demo", "clusters", "--filter", "severity=error"]
    )
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output
    assert "service started" not in shown.output


@pytest.mark.parametrize(
    ("target", "spec", "fragment"),
    [
        ("events", "limit=abc", "abc"),
        ("events", "since=notatime", "notatime"),
        ("clusters", "min-count=abc", "abc"),
        ("clusters", "min-count=-1", "-1"),
    ],
)
def test_show_invalid_filter_values_exit_2(
    tmp_path: Path, target: str, spec: str, fragment: str
) -> None:
    """Invalid values fail loudly naming the offending value — never an
    empty result set that looks like 'no matches'."""
    _ingested_case(tmp_path)
    shown = runner.invoke(app, ["show", "demo", target, "--filter", spec])
    assert shown.exit_code == 2, shown.output
    assert fragment in shown.output


def test_show_invalid_severity_exits_2_listing_vocabulary(tmp_path: Path) -> None:
    _ingested_case(tmp_path)
    shown = runner.invoke(
        app, ["show", "demo", "events", "--filter", "severity=catastrophic"]
    )
    assert shown.exit_code == 2, shown.output
    assert "catastrophic" in shown.output
    for sev in SEVERITIES:
        assert sev in shown.output, f"{sev!r} missing from: {shown.output!r}"


def test_show_filter_injection_shaped_value_is_literal(tmp_path: Path) -> None:
    """T-02-08: a SQL-shaped filter VALUE binds as a literal — zero rows,
    exit 0, never a syntax error; the tables survive."""
    _ingested_case(tmp_path)
    inj = "file='; DROP TABLE events;--"
    shown = runner.invoke(app, ["show", "demo", "events", "--filter", inj])
    assert shown.exit_code == 0, shown.output
    assert not re.findall(r"\b[0-9a-f]{16}\b", shown.output)

    inj2 = "contains=' OR 1=1; DROP TABLE template_groups;--"
    clusters = runner.invoke(app, ["show", "demo", "clusters", "--filter", inj2])
    assert clusters.exit_code == 0, clusters.output
    assert not re.findall(r"\b[0-9a-f]{16}\b", clusters.output)

    # Both tables are intact afterwards: unfiltered listings still render.
    events_again = runner.invoke(app, ["show", "demo", "events"])
    assert events_again.exit_code == 0, events_again.output
    assert len(set(re.findall(r"\b[0-9a-f]{16}\b", events_again.output))) == 3
    clusters_again = runner.invoke(app, ["show", "demo", "clusters"])
    assert clusters_again.exit_code == 0, clusters_again.output
    assert re.findall(r"\b[0-9a-f]{16}\b", clusters_again.output)


# --- plan 02-04: gap closure (CR-01, WR-01..WR-05) --------------------------


def _query_scalar(case: str, sql: str, params: tuple[object, ...] = ()) -> int:
    """One integer straight from the case DB (accounting identity checks)."""
    conn = sqlite3.connect(case_db_path(load_config().data_dir, case))
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row[0])
    finally:
        conn.close()


def test_ingest_truncated_gz_mid_stream_contributes_zero_rows(
    tmp_path: Path,
) -> None:
    """CR-01: a file whose parse fails AFTER >=1 inserted batch contributes
    exactly zero event rows, and the three-way accounting identity holds:
    sum(template_groups.count) == count(events) == sum(coverage event_counts).
    """
    input_dir = _make_case(tmp_path)  # good app.log: 3 events
    base = datetime(2026, 7, 15, 0, 0, 0, tzinfo=UTC)
    lines = "".join(
        f"{(base + timedelta(seconds=i)).isoformat()} INFO worker tick "
        f"processed request in queue slot {i}\n"
        for i in range(20_000)
    )
    compressed = gzip.compress(lines.encode("utf-8"))
    truncated = compressed[: int(len(compressed) * 0.6)]
    (input_dir / "big.log.gz").write_bytes(truncated)

    # Pin the fixture as a MID-STREAM failure (not detect-time): the adapter
    # yields well past one 5000-event insert batch before gzip gives up.
    adapter = GenericLogAdapter()
    adapter.input_root = input_dir
    yielded = 0
    with pytest.raises(Exception, match="[Cc]ompressed|[Ee]nd-of-stream|EOF"):
        for _ in adapter.parse(input_dir / "big.log.gz", "demo"):
            yielded += 1
    assert yielded > 5000, (
        f"fixture must cross at least one insert batch, yielded {yielded}"
    )

    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 1, result.output
    assert "file(s) failed to parse" in result.output
    assert "ERROR big.log.gz" in result.output

    # Zero rows from the failed file; the good file's events all present.
    assert _query_scalar(
        "demo", "SELECT COUNT(*) FROM events WHERE source_file = ?", ("big.log.gz",)
    ) == 0
    n_events = _query_scalar("demo", "SELECT COUNT(*) FROM events")
    assert n_events == 3

    cov = _read_coverage_meta("demo")
    assert cov["big.log.gz"]["event_count"] == 0
    cov_total = sum(int(str(entry["event_count"])) for entry in cov.values())
    groups_total = _query_scalar(
        "demo", "SELECT COALESCE(SUM(count), 0) FROM template_groups"
    )
    assert groups_total == n_events == cov_total


def test_show_sanitises_every_db_sourced_field(tmp_path: Path) -> None:
    """WR-01 / T-04-01: hostile bytes planted directly in the case DB (the
    tampered-case.db trust boundary) never reach the terminal from ANY
    rendered field — not just message/source_file/template. Only non-CHECK
    columns are planted: severity CHECK rejects hostile values, and
    whole-line sanitisation makes per-column coverage equivalent."""
    _ingested_case(tmp_path, REPETITIVE_LOG)
    conn = sqlite3.connect(case_db_path(load_config().data_dir, "demo"))
    try:
        conn.execute(
            "UPDATE template_groups SET first_ts = ?, exemplar_event_ids = ?",
            (
                "\x1b[31m2026-07-16\x1b[0m",
                json.dumps(["\x1b]0;evil\x07id1", "\u202eid2"]),
            ),
        )
        conn.execute(
            "UPDATE events SET event_id = ?, ts = ?, message = ? "
            "WHERE rowid = (SELECT rowid FROM events LIMIT 1)",
            ("\x1b[2Jdeadbeef", "\x1b[31m2026-07-16T10:00:00", "\u202ehidden"),
        )
        conn.commit()
    finally:
        conn.close()

    for target in ("clusters", "events"):
        shown = runner.invoke(app, ["show", "demo", target])
        assert shown.exit_code == 0, shown.output
        assert "\x1b" not in shown.output, f"raw ESC leaked from show {target}"
        assert "\u202e" not in shown.output, f"bidi override leaked from {target}"


def test_show_clusters_non_list_exemplar_json_renders_sanitised(
    tmp_path: Path,
) -> None:
    """WR-01: a tampered non-array exemplar_event_ids JSON renders visibly
    (sanitised) instead of crashing ' '.join with a traceback."""
    _ingested_case(tmp_path, REPETITIVE_LOG)
    conn = sqlite3.connect(case_db_path(load_config().data_dir, "demo"))
    try:
        conn.execute(
            "UPDATE template_groups SET exemplar_event_ids = ? "
            "WHERE rowid = (SELECT rowid FROM template_groups LIMIT 1)",
            ('"hostile"',),
        )
        conn.commit()
    finally:
        conn.close()

    shown = runner.invoke(app, ["show", "demo", "clusters"])
    assert shown.exit_code == 0, shown.output
    assert "Traceback" not in shown.output
    assert "hostile" in shown.output  # tampering stays visible to the operator


def test_show_duplicate_filter_key_exits_2(tmp_path: Path) -> None:
    """WR-05: a repeated --filter key fails loudly naming the key — never
    silent last-wins (fail-loud prohibition)."""
    _ingested_case(tmp_path, REPETITIVE_LOG)
    events = runner.invoke(
        app,
        [
            "show", "demo", "events",
            "--filter", "severity=error",
            "--filter", "severity=warn",
        ],
    )
    assert events.exit_code == 2, events.output
    assert "duplicate filter key" in events.output
    assert "severity" in events.output

    clusters = runner.invoke(
        app,
        [
            "show", "demo", "clusters",
            "--filter", "min-count=1",
            "--filter", "min-count=2",
        ],
    )
    assert clusters.exit_code == 2, clusters.output
    assert "duplicate filter key" in clusters.output
    assert "min-count" in clusters.output


def test_show_corrupt_case_db_exits_1_without_traceback(tmp_path: Path) -> None:
    """WR-02: garbage bytes over case.db (corrupt evidence media) fail loudly
    with a helpful message, never a Python traceback."""
    _ingested_case(tmp_path)
    case_db_path(load_config().data_dir, "demo").write_bytes(
        b"not a sqlite database"
    )
    shown = runner.invoke(app, ["show", "demo", "events"])
    assert shown.exit_code == 1, shown.output
    assert "Error: cannot open case" in shown.output
    assert "Traceback" not in shown.output
    assert shown.exception is None or isinstance(shown.exception, SystemExit)


def test_show_clusters_warns_when_template_groups_stale(tmp_path: Path) -> None:
    """WR-03: a crash between the event commit and the rebuild is detectable —
    show clusters warns on stderr while still rendering groups on stdout."""
    _ingested_case(tmp_path, REPETITIVE_LOG)

    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        assert store.get_meta("template_groups_stale") == "0"
    finally:
        store.close()
    clean = runner.invoke(app, ["show", "demo", "clusters"])
    assert clean.exit_code == 0, clean.output
    assert "stale" not in clean.stderr

    # Simulate a crash between the event transaction and the rebuild.
    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        store.set_meta("template_groups_stale", "1")
    finally:
        store.close()
    shown = runner.invoke(app, ["show", "demo", "clusters"])
    assert shown.exit_code == 0, shown.output
    assert "stale" in shown.stderr
    assert "sift ingest" in shown.stderr
    assert re.findall(r"\b[0-9a-f]{16}\b", shown.stdout), "groups still render"
