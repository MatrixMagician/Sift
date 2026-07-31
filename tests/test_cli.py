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
from sift.commands import ExitCode
from sift.config import SiftConfig, load_config
from sift.models import Event
from sift.pipeline.hypothesise import DEFAULT_TOP_CLUSTERS
from sift.store import CaseStore, StoredHypothesis, case_db_path


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
#
# ADR 0019 pass 2: what a given filter spec PARSES to — the key allowlists, the
# severity vocabulary, integer and timestamp coercion, duplicate keys — is
# asserted directly against ``parse_filters`` in tests/test_commands_parse.py.
# What stays here is the CLI boundary either side of it: that a parse failure
# becomes exit 2, and that a parsed filter actually reaches the query.


def _ingested_case(tmp_path: Path, content: str = FIXTURE_LOG) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(content, encoding="utf-8")
    assert runner.invoke(app, ["new", "demo", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "demo"]).exit_code == 0


def test_show_filter_flag_reaches_the_query(tmp_path: Path) -> None:
    """The wiring test: a ``--filter`` genuinely scopes the rows shown.

    ``parse_filters`` and ``run_show_events`` are each covered directly, so what
    is left to prove here is only that ``show`` passes the parsed value to the
    body — dropping it would leave both of those suites green and quietly
    render every event under any filter.
    """
    _ingested_case(tmp_path)
    shown = runner.invoke(
        app, ["show", "demo", "events", "--filter", "severity=error"]
    )
    assert shown.exit_code == 0, shown.output
    assert "connection pool exhausted" in shown.output
    assert "service started" not in shown.output
    assert "retrying with backoff" not in shown.output


def test_show_bad_filter_exits_2_carrying_the_parser_message(tmp_path: Path) -> None:
    """A ``parse_filters`` ValueError becomes exit 2 with the message on stdout.

    One test for the boundary, per target, rather than one per rejection: the
    rejections themselves are asserted in tests/test_commands_parse.py, and the
    only thing the CLI adds is the translation.
    """
    _ingested_case(tmp_path)
    for target in ("events", "clusters", "hypotheses"):
        shown = runner.invoke(app, ["show", "demo", target, "--filter", "bogus=1"])
        assert shown.exit_code == 2, shown.output
        assert "unknown filter key" in shown.output


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
    # The hypotheses target too: titles and cited ids are MODEL-generated, the
    # one rendered surface whose hostile bytes need no tampered case.db at all.
    store = CaseStore(case_db_path(load_config().data_dir, "demo"))
    try:
        store.replace_hypotheses(
            [
                StoredHypothesis(
                    hyp_index=0,
                    title="\x1b[31mfabricated\u202e",
                    narrative="n",
                    confidence="high",
                    confidence_reasoning="r",
                    supporting_event_ids=["\x1b[2Jdeadbeef"],
                    contradicting_evidence=None,
                    suggested_next_steps=[],
                    citations_valid=True,
                )
            ]
        )
    finally:
        store.close()

    for target in ("clusters", "events", "hypotheses"):
        shown = runner.invoke(app, ["show", "demo", target])
        assert shown.exit_code == 0, shown.output
        assert "\x1b" not in shown.output, f"raw ESC leaked from show {target}"
        assert "\u202e" not in shown.output, f"bidi override leaked from {target}"


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


# --- analyze: the CLI boundary (CLI-04, ADR 0005) --------------------------
#
# ADR 0019 pass 2: which exit code a given run EARNS — degraded output, an
# invalid citation, a refused endpoint, an empty case — is asserted against
# ``run_analyze`` directly in tests/test_analyze.py. Three things are left that
# only the CLI can be wrong about, and each is tested by faking ``run_analyze``
# rather than running the pipeline: that every flag lands on the parameter it
# names, that the returned code reaches the shell, and that the contract is
# documented in ``--help``.


def _empty_case(case: str = "demo") -> None:
    """Create an empty but openable ``case.db``.

    Every analyze test below fakes ``run_analyze``, so the case needs no events
    — it exists only to give ``_case_store`` something to open. Seeding one
    anyway would imply the pipeline runs here, and it does not.
    """
    db_path = case_db_path(load_config().data_dir, case)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    CaseStore(db_path).close()


def _record_analyze(
    monkeypatch: pytest.MonkeyPatch, code: ExitCode = ExitCode.SUCCESS
) -> dict[str, object]:
    """Replace ``run_analyze`` with a recorder and return the kwargs dict."""
    recorded: dict[str, object] = {}

    def fake(store: CaseStore, config: SiftConfig, **kwargs: object) -> ExitCode:
        recorded.update(kwargs)
        return code

    monkeypatch.setattr("sift.cli.run_analyze", fake)
    return recorded


def test_analyze_flags_land_on_the_parameters_they_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every ``analyze`` flag, in one pass.

    Nine of these twelve parameters had no CLI-level coverage at all before the
    seam existed, because reaching them meant driving the whole pipeline. A
    flag silently wired to the wrong parameter — ``--since`` onto ``until``, or
    ``--no-label`` inverted — is exactly the failure this catches, and it needs
    no inference server to catch it.
    """
    _empty_case()
    kb_dir = tmp_path / "runbooks"
    kb_dir.mkdir()
    recorded = _record_analyze(monkeypatch)

    result = runner.invoke(
        app,
        [
            "analyze", "demo",
            "--i-know-what-im-doing",
            "--no-label",
            "--re-embed",
            "--hint", "the customer restarted the box",
            "--kb", str(kb_dir),
            "--since", "2026-07-16T10:00:00",
            "--until", "2026-07-16T18:00:00+02:00",
            "--top-clusters", "7",
        ],
    )
    assert result.exit_code == 0, result.output
    assert recorded == {
        "allow_public": True,
        # --no-label is the negation of the `label` parameter, not a pass-through.
        "label": False,
        "re_embed": True,
        # --hint is free operator text and is NEVER parsed as a time.
        "hint": "the customer restarted the box",
        "kb": kb_dir,
        # Both moments arrive parsed and normalised to UTC. They are
        # deliberately DIFFERENT instants (and the naive one is the earlier):
        # two values that normalised alike would survive a since/until swap,
        # which is the very mistake this test names.
        "since": datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
        "until": datetime(2026, 7, 16, 16, 0, tzinfo=UTC),
        "top_clusters": 7,
    }


def test_analyze_defaults_are_the_permissive_flags_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``analyze`` labels, reuses embeddings and refuses a public
    endpoint — the safe defaults, none of them accidentally inverted."""
    _empty_case()
    recorded = _record_analyze(monkeypatch)

    assert runner.invoke(app, ["analyze", "demo"]).exit_code == 0
    assert recorded["allow_public"] is False
    assert recorded["label"] is True
    assert recorded["re_embed"] is False
    assert recorded["hint"] is None
    assert recorded["kb"] is None
    assert recorded["since"] is None
    assert recorded["until"] is None
    assert recorded["top_clusters"] == DEFAULT_TOP_CLUSTERS


@pytest.mark.parametrize(
    "code", [ExitCode.SUCCESS, ExitCode.ERROR, ExitCode.DEGRADED]
)
def test_analyze_exit_code_reaches_the_shell(
    monkeypatch: pytest.MonkeyPatch, code: ExitCode
) -> None:
    """ADR 0005: a process exit status must carry EVERY non-zero code, code 3
    included — ``cli.py`` branches on ``if code:`` for exactly this reason, and
    must not borrow ``is_failure``, which deliberately treats DEGRADED as
    usable for the callers that keep running.
    """
    _empty_case()
    _record_analyze(monkeypatch, code=code)
    assert runner.invoke(app, ["analyze", "demo"]).exit_code == code


def test_analyze_exit_1_on_missing_case() -> None:
    """The store never opens, so ``run_analyze`` is never reached — this is
    ``_case_store``'s mapping of ``open_case``'s failure onto exit 1."""
    result = runner.invoke(app, ["analyze", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_analyze_help_documents_exit_code_contract() -> None:
    """CLI-04 / ADR 0005: the exit-code table is discoverable in --help."""
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0, result.output
    low = result.output.lower()
    assert "exit" in low and "degraded" in low
    # The --until incident-time anchor is documented too (RESEARCH Q3).
    assert "incident-time" in low or "incident time" in low


def test_analyze_exit_2_on_bad_since_before_the_store_opens() -> None:
    """A bad --since is a usage error (2) — never confused with degraded (3).

    Deliberately run against a case that does not exist: parsing happens before
    the store is opened, so a malformed timestamp costs a usage error and
    nothing else. Were the ordering ever reversed this would exit 1 ("case does
    not exist") instead. What ``--since`` parses TO is tested directly in
    tests/test_commands_parse.py.
    """
    result = runner.invoke(app, ["analyze", "ghost", "--since", "not-a-time"])
    assert result.exit_code == 2, result.output
    assert "not an ISO 8601 timestamp" in result.output


# --- plan 05-06: Phase-5 domain-adapter end-to-end ingest slices ----------
# new -> ingest -> show for each real domain fixture, through the CLI boundary
# that wires input_root onto the ConfigurableAdapter. Proves: canonical events
# land and render; the deliberate unparseable region yields REAL coverage below
# 100% (never the fabricated 1.0 of the pre-05-01 bug); a second ingest is
# idempotent (INGST-02) for the newly-registered domain adapters.

_FIXTURES = Path(__file__).parent / "fixtures"

# (format dir, total events across the bundle, the file with a deliberate
# unparseable region, a stable substring `show events` renders, an optional
# single filename to copy instead of the whole format directory).
#
# eustack's fixture directory also carries the phase-15 signature-preserving
# derivative fixture and its (uncollected) derivation script -- neither is
# part of this curated e2e bundle, so this case scopes the copy to the one
# file it actually means to ingest (T-05-E2E-eustack-scope).
_PHASE5_E2E = [
    ("journald", 15, "basic.json", "emergency shutdown", None),
    ("dsserrors", 14, "node1/DSSErrors.log", "node2/DSSErrors.log", None),
    ("eustack", 6, "threaddump.txt", "clock_nanosleep", "threaddump.txt"),
]


def _copy_fixture(tmp_path: Path, fmt: str, *, only: str | None = None) -> Path:
    input_dir = tmp_path / "input"
    if only is None:
        shutil.copytree(_FIXTURES / fmt, input_dir)
    else:
        input_dir.mkdir()
        shutil.copy2(_FIXTURES / fmt / only, input_dir / only)
    return input_dir


@pytest.mark.parametrize(("fmt", "total", "unparseable", "shown", "only"), _PHASE5_E2E)
def test_phase5_e2e_ingest_show_real_coverage_idempotent(
    tmp_path: Path,
    fmt: str,
    total: int,
    unparseable: str,
    shown: str,
    only: str | None,
) -> None:
    input_dir = _copy_fixture(tmp_path, fmt, only=only)
    assert runner.invoke(app, ["new", fmt, "--input", str(input_dir)]).exit_code == 0

    first = runner.invoke(app, ["ingest", fmt])
    assert first.exit_code == 0, first.output

    # (b) REAL coverage below 100% on the unparseable-region file — the 05-01
    # non-vacuous-coverage fix, proven on a real domain fixture (not the stub).
    cov = _read_coverage_meta(fmt)
    file_cov = cov[unparseable]["coverage"]
    assert isinstance(file_cov, float)
    assert 0.0 < file_cov < 1.0, (
        f"{unparseable} should have real sub-100% coverage, got {file_cov}"
    )
    # ...and the ingest stdout reports that same sub-100% percentage (never a
    # fabricated 100.0%).
    match = re.search(
        rf"{re.escape(unparseable)}\s+coverage\s+([\d.]+)%", first.output
    )
    assert match is not None, f"no coverage line for {unparseable}: {first.output!r}"
    assert float(match.group(1)) < 100.0

    # (a) canonical events landed and render (event ids + a known message token;
    # the unparseable file's relpath appears as a source_file, and for dsserrors
    # node2's relpath proves multi-node tagging is visible).
    shown_out = runner.invoke(app, ["show", fmt, "events"])
    assert shown_out.exit_code == 0, shown_out.output
    event_ids = set(re.findall(r"\b[0-9a-f]{16}\b", shown_out.output))
    assert len(event_ids) == total, f"unexpected event count for {fmt}"
    assert shown in shown_out.output
    assert unparseable in shown_out.output

    # (c) re-ingesting the same snapshot adds zero events (INGST-02).
    second = runner.invoke(app, ["ingest", fmt])
    assert second.exit_code == 0, second.output
    assert "0 new" in second.output
    reshown = runner.invoke(app, ["show", fmt, "events"])
    assert set(re.findall(r"\b[0-9a-f]{16}\b", reshown.output)) == event_ids


def test_phase5_show_sanitises_domain_adapter_escape_bytes(tmp_path: Path) -> None:
    """T-05-41: a terminal-escape byte in a domain-adapter event field is
    stripped by the existing whole-line _sanitise on `show`, never reaching
    stdout raw (proven here for a journald MESSAGE field)."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    entry = {
        "__REALTIME_TIMESTAMP": "1784160000000000",
        "_BOOT_ID": "aabbccddeeff00112233445566778899",
        "PRIORITY": "3",
        # \x1b is escape NOTATION in this source; json.dumps writes the
        # escaped \\u001b to disk, json.loads decodes a real ESC into MESSAGE.
        "MESSAGE": "boot \x1b[31mRED ALERT\x1b[0m failure",
    }
    (input_dir / "dump.json").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert runner.invoke(app, ["new", "esc", "--input", str(input_dir)]).exit_code == 0
    assert runner.invoke(app, ["ingest", "esc"]).exit_code == 0

    shown = runner.invoke(app, ["show", "esc", "events"])
    assert shown.exit_code == 0, shown.output
    assert "\x1b" not in shown.output
    assert "RED ALERT" in shown.output


# --- plan 12-03: dssperfmon end-to-end ingest (PERF-01, criterion 1) ------
# The CSV routes by sniff alone — no --adapter override is passed anywhere
# below, so these also prove registration wired detection end to end.

# 21 lines in the fixture: 1 PDH header (metadata, never an Event per D-01)
# plus 20 sample rows, one Event each. Perfmon samples are never downsampled
# or capped — a series is only useful whole.
_PERFMON_CSV = "hartford_deny_slice.csv"
_PERFMON_ROWS = 20


def _read_event_ids(case: str) -> set[str]:
    store = CaseStore(case_db_path(load_config().data_dir, case))
    try:
        return {e.event_id for e in store.query_events()}
    finally:
        store.close()


def test_ingest_perfmon_full_coverage(tmp_path: Path) -> None:
    """One Event per sample row, at 100% parse coverage.

    The fixture has no malformed cells, so nothing degrades to the
    severity='unknown' fallback and coverage is a real — not fabricated —
    1.0 (the 05-01 non-vacuous-coverage contract).
    """
    input_dir = _copy_fixture(tmp_path, "dssperfmon")
    assert runner.invoke(app, ["new", "perf", "--input", str(input_dir)]).exit_code == 0

    result = runner.invoke(app, ["ingest", "perf"])
    assert result.exit_code == 0, result.output

    entry = _read_coverage_meta("perf")[_PERFMON_CSV]
    assert entry["event_count"] == _PERFMON_ROWS, (
        f"expected one Event per sample row, got {entry['event_count']}"
    )
    assert entry["coverage"] == 1.0, (
        f"fixture has no malformed cells; expected full coverage, got "
        f"{entry['coverage']}"
    )
    assert len(_read_event_ids("perf")) == _PERFMON_ROWS


def test_ingest_perfmon_idempotent(tmp_path: Path) -> None:
    """Re-ingest adds zero events AND regenerates no ids (INGST-02).

    Asserting the event_id SET rather than the count is deliberate: a
    count-only check still passes if ids were regenerated on the second run.
    Stable ids under re-ingest are the actual determinism contract, since
    event_id = sha256(source_file, byte_offset)[:16].
    """
    input_dir = _copy_fixture(tmp_path, "dssperfmon")
    assert runner.invoke(app, ["new", "perf", "--input", str(input_dir)]).exit_code == 0

    first = runner.invoke(app, ["ingest", "perf"])
    assert first.exit_code == 0, first.output
    first_ids = _read_event_ids("perf")
    assert len(first_ids) == _PERFMON_ROWS

    second = runner.invoke(app, ["ingest", "perf"])
    assert second.exit_code == 0, second.output
    assert "0 new" in second.output

    assert _read_event_ids("perf") == first_ids, "event ids changed on re-ingest"


# --- plan 12-04: PERF-03 exclusion, the phase's primary regression gate ---

_MCM_LOG = _FIXTURES / "mcm" / "hartford_deny_slice.log"
_PERFMON_FIXTURE_CSV = _FIXTURES / "dssperfmon" / _PERFMON_CSV

# tests/fixtures/eustack/threaddump.txt parses to exactly 6 events (measured,
# same figure the phase-5 e2e parametrisation pins), 4 of them thread records.
_EUSTACK_THREADDUMP_EVENTS = 6
_EUSTACK_FIXTURE_DUMP = _FIXTURES / "eustack" / "threaddump.txt"


def _ingest_case(
    tmp_path: Path, case: str, *, with_csv: bool, with_eustack: bool = False
) -> None:
    """Create and ingest a case from the shared log, optionally plus the CSV
    and/or the eu-stack thread dump.

    No `analyze` step, so no embedding or LLM call occurs — `show clusters`
    falls back to the template-group path, which is both the cheaper and the
    stronger assertion (exemplars derive from template groups).
    """
    input_dir = tmp_path / case
    input_dir.mkdir()
    shutil.copy(_MCM_LOG, input_dir / _MCM_LOG.name)
    if with_csv:
        shutil.copy(_PERFMON_FIXTURE_CSV, input_dir / _PERFMON_CSV)
    if with_eustack:
        shutil.copy(_EUSTACK_FIXTURE_DUMP, input_dir / _EUSTACK_FIXTURE_DUMP.name)
    assert runner.invoke(app, ["new", case, "--input", str(input_dir)]).exit_code == 0
    result = runner.invoke(app, ["ingest", case])
    assert result.exit_code == 0, result.output


def test_cluster_output_identical_with_and_without_perfmon(tmp_path: Path) -> None:
    """Criterion 4: adding a perfmon CSV perturbs no cluster output at all.

    Compares the DERIVED cluster output, never the two case.db files — case B
    legitimately holds the perfmon events; the phase promises identity of
    ranking, not of stored state.
    """
    _ingest_case(tmp_path, "logonly", with_csv=False)
    _ingest_case(tmp_path, "logplus", with_csv=True)

    a = runner.invoke(app, ["show", "logonly", "clusters"])
    b = runner.invoke(app, ["show", "logplus", "clusters"])
    assert a.exit_code == 0, a.output
    assert b.exit_code == 0, b.output
    assert a.output == b.output, "perfmon CSV perturbed cluster output"

    # Non-vacuity: without this the equality could pass for the wrong reason
    # — e.g. if the CSV silently failed to ingest at all.
    n_a = len(_read_event_ids("logonly"))
    n_b = len(_read_event_ids("logplus"))
    assert n_b > n_a, f"CSV was not ingested: {n_a} vs {n_b} events"
    assert n_b - n_a == _PERFMON_ROWS


def test_show_events_includes_perfmon(tmp_path: Path) -> None:
    """Criterion 5 at CLI level: exclusion never reached the citation path."""
    _ingest_case(tmp_path, "logplus", with_csv=True)
    shown = runner.invoke(app, ["show", "logplus", "events"])
    assert shown.exit_code == 0, shown.output
    assert _PERFMON_CSV in shown.output, "perfmon rows vanished from show events"


def test_every_perfmon_sample_citable_and_none_ranked(tmp_path: Path) -> None:
    """PERF-03 over the whole ingested population, not one seeded event.

    The anti-hallucination invariant is per-sample: EVERY perfmon event_id must
    resolve through the citation path (`get_events_by_ids`, what the evidence
    appendix uses) while NONE reach the ranking seam. Asserted on real
    CLI-ingested data, both directions, all 20 rows.
    """
    _ingest_case(tmp_path, "logplus", with_csv=True)
    store = CaseStore(case_db_path(load_config().data_dir, "logplus"))
    try:
        perf_ids = {
            e.event_id for e in store.query_events() if e.source == "dssperfmon"
        }
        assert len(perf_ids) == _PERFMON_ROWS, "fixture did not ingest as expected"

        cited = store.get_events_by_ids(sorted(perf_ids))
        assert set(cited) == perf_ids, "perfmon samples not individually citable"

        ranked = {row[0] for row in store.iter_event_summaries()}
        assert not (perf_ids & ranked), "perfmon leaked into the ranking seam"
        assert ranked, "non-vacuity: ranking seam yielded nothing at all"
    finally:
        store.close()


# --- plan 19-01: EUS-11 exclusion, mirroring the PERF-03 block above -------


def test_cluster_output_identical_with_and_without_eustack(tmp_path: Path) -> None:
    """D-19-03: adding an eu-stack dump perturbs no cluster output at all.

    Compares the DERIVED cluster output, never the two case.db files — case B
    legitimately holds the eu-stack events. Case A carries the shared MCM log
    (a non-eu-stack ranked source), so — unlike a bare eu-stack-only
    comparison — this guards against the vacuous case where both sides would
    otherwise trivially be empty and the equality would pass while proving
    nothing.
    """
    _ingest_case(tmp_path, "logonly", with_csv=False)
    _ingest_case(tmp_path, "logplus", with_csv=False, with_eustack=True)

    a = runner.invoke(app, ["show", "logonly", "clusters"])
    b = runner.invoke(app, ["show", "logplus", "clusters"])
    assert a.exit_code == 0, a.output
    assert b.exit_code == 0, b.output
    assert a.output == b.output, "eu-stack dump perturbed cluster output"

    # Non-vacuity guard 1: case A genuinely has rendered cluster rows — an
    # eu-stack-only comparison would leave both sides trivially empty.
    assert a.output.strip() != "", "non-vacuity: case A rendered no clusters"

    # Non-vacuity guard 2: the dump really was ingested, not silently dropped.
    n_a = len(_read_event_ids("logonly"))
    n_b = len(_read_event_ids("logplus"))
    assert n_b > n_a, f"eu-stack dump was not ingested: {n_a} vs {n_b} events"

    # Non-vacuity guard 3: the exact delta matches the measured fixture size.
    assert n_b - n_a == _EUSTACK_THREADDUMP_EVENTS


def test_every_eustack_event_citable_and_none_ranked(tmp_path: Path) -> None:
    """EUS-11 over the whole ingested population, not one seeded event.

    Mirrors test_every_perfmon_sample_citable_and_none_ranked: every eu-stack
    event_id must resolve through the citation path while none reach the
    ranking seam.
    """
    _ingest_case(tmp_path, "logplus", with_csv=False, with_eustack=True)
    store = CaseStore(case_db_path(load_config().data_dir, "logplus"))
    try:
        eustack_ids = {
            e.event_id for e in store.query_events() if e.source == "eustack"
        }
        assert len(eustack_ids) == _EUSTACK_THREADDUMP_EVENTS, (
            "fixture did not ingest as expected"
        )

        cited = store.get_events_by_ids(sorted(eustack_ids))
        assert set(cited) == eustack_ids, "eustack events not individually citable"

        ranked = {row[0] for row in store.iter_event_summaries()}
        assert not (eustack_ids & ranked), "eustack leaked into the ranking seam"
        assert ranked, "non-vacuity: ranking seam yielded nothing at all"
    finally:
        store.close()


def test_show_events_includes_eustack(tmp_path: Path) -> None:
    """D-19-04 at CLI level: exclusion never reached the citation path."""
    _ingest_case(tmp_path, "logplus", with_csv=False, with_eustack=True)
    shown = runner.invoke(app, ["show", "logplus", "events"])
    assert shown.exit_code == 0, shown.output
    assert _EUSTACK_FIXTURE_DUMP.name in shown.output, (
        "eustack rows vanished from show events"
    )


def _case_dir(case: str = "demo") -> Path:
    return case_db_path(load_config().data_dir, case).parent


def test_delete_force_removes_the_whole_case_directory(tmp_path: Path) -> None:
    """`sift delete --force` removes case.db AND the mcm/perfmon report
    artefacts — the whole directory, which is what deleting a case means."""
    _ingested_case(tmp_path)
    case_dir = _case_dir()
    (case_dir / "mcm").mkdir()
    (case_dir / "mcm" / "report.md").write_text("findings", encoding="utf-8")
    assert (case_dir / "case.db").exists()

    result = runner.invoke(app, ["delete", "demo", "--force"])

    assert result.exit_code == 0, result.output
    assert "Deleted case 'demo'" in result.output
    assert not case_dir.exists(), "report artefacts or db survived the delete"


def test_delete_declined_at_the_prompt_leaves_the_case_intact(tmp_path: Path) -> None:
    """Answering 'n' aborts: nothing is removed and the exit code is non-zero,
    so a scripted caller cannot mistake a decline for a deletion."""
    _ingested_case(tmp_path)
    case_dir = _case_dir()
    before = sorted(p.name for p in case_dir.iterdir())

    result = runner.invoke(app, ["delete", "demo"], input="n\n")

    assert result.exit_code != 0
    assert case_dir.exists()
    assert sorted(p.name for p in case_dir.iterdir()) == before


def test_delete_unknown_case_exits_1_without_traceback() -> None:
    result = runner.invoke(app, ["delete", "nosuchcase", "--force"])

    assert result.exit_code == 1, result.output
    assert "does not exist" in result.output
    assert "Traceback" not in result.output


def test_delete_rejects_a_traversal_case_name_and_removes_nothing(
    tmp_path: Path,
) -> None:
    """T-02-01: a case name that would escape <data_dir>/cases is refused by
    case_db_path's allowlist before rmtree is ever reached. The sibling
    directory next to the case root must survive untouched.

    The decoy carries a case.db so a naive ``data_dir / "cases" / case`` join
    would find it, pass the existence check, and recursively delete the lot —
    the assertion below is what fails if the containment check is ever dropped.
    """
    _ingested_case(tmp_path)
    cases_root = _case_dir().parent
    outside = cases_root.parent / "not-a-case"
    outside.mkdir()
    (outside / "case.db").write_bytes(b"decoy")
    (outside / "keep.txt").write_text("do not delete me", encoding="utf-8")

    result = runner.invoke(app, ["delete", "../not-a-case", "--force"])

    assert result.exit_code == 1, result.output
    assert "invalid case name" in result.output
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "do not delete me"
    assert _case_dir().exists(), "the real case was collateral damage"


def test_list_shows_each_case_sorted_with_counts(tmp_path: Path) -> None:
    """The listing names every case and carries the numbers you pick one by."""
    _ingested_case(tmp_path)
    second = tmp_path / "input2"
    second.mkdir()
    (second / "app.log").write_text(FIXTURE_LOG, encoding="utf-8")
    assert runner.invoke(app, ["new", "acme", "--input", str(second)]).exit_code == 0

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert lines[0].split() == ["CASE", "CREATED", "EVENTS", "HYPOTHESES", "DB", "(MB)"]
    # Sorted by name: acme (created, never ingested) before demo (3 events).
    assert lines[1].startswith("acme")
    assert lines[2].startswith("demo")
    assert lines[2].split()[2] == "3"


def test_list_with_no_cases_is_not_an_error() -> None:
    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "No cases in" in result.output


def test_list_still_shows_a_corrupt_case(tmp_path: Path) -> None:
    """A case whose db cannot be read is the one you most want to see listed —
    it degrades to em dashes rather than taking the whole listing down."""
    _ingested_case(tmp_path)
    case_db_path(load_config().data_dir, "demo").write_bytes(b"not a sqlite database")

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "demo" in result.output
    assert "—" in result.output


def test_list_does_not_migrate_the_cases_it_lists(tmp_path: Path) -> None:
    """`list` must never write to a case.

    CaseStore.__init__ runs _migrate(), so listing through the store would
    rewrite the schema of every case on disk purely to display it. An EMPTY
    case.db is the honest fixture for that: it is un-migrated (user_version 0)
    with no tables, so the migration chain would run to completion and be
    plainly visible afterwards. (Rewinding user_version on an already-migrated
    file does NOT work as a probe — migration 1 hits "table events already
    exists", so a store-based listing would error out and write nothing,
    passing this test for the wrong reason.)
    """
    stale = case_db_path(load_config().data_dir, "stale")
    stale.parent.mkdir(parents=True)
    stale.touch()  # 0 bytes: a valid, empty, never-migrated sqlite database

    assert runner.invoke(app, ["list"]).exit_code == 0

    conn = sqlite3.connect(stale)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    assert version == 0, "listing migrated the case it was only meant to display"
    assert stale.stat().st_size == 0, "listing wrote to case.db"
