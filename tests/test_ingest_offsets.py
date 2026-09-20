"""Offset-tracking capability and the re-ingest determinism pin (issue #11).

``event_id = sha256(source_file, byte_offset)[:16]``, so the bounded-batch
offset bookkeeping in ``pipeline/ingest.py`` is determinism-load-bearing. The
pin here ingests one fixture per registered adapter twice and demands zero new
events the second time, for every adapter rather than genericlog alone.

The capability tests are the SPEC §5.2 guard: a sixth adapter that streams in
ascending byte order opts into offset tracking by declaring
``streams_offsets``, with no edit to ``pipeline/ingest.py``.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from rich.progress import Progress, TaskID
from typer.testing import CliRunner

from sift import adapters
from sift.adapters import REGISTRY
from sift.adapters.base import ConfigurableAdapter
from sift.cli import app
from sift.models import Event, event_id

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"

# One real fixture per registered adapter, forced with an --adapter glob so
# detection cannot quietly route a file to genericlog and leave an adapter
# unpinned.
PINNED_FIXTURES = {
    "genericlog": FIXTURES / "dsserrors" / "node1" / "DSSErrors.log",
    "journald": FIXTURES / "journald" / "basic.json",
    "dsserrors": FIXTURES / "dsserrors" / "node1" / "DSSErrors.log",
    "eustack": FIXTURES / "eustack" / "threaddump.txt",
    "dssperfmon": FIXTURES / "dssperfmon" / "hartford_deny_slice.csv",
}


@pytest.mark.parametrize("adapter_name", sorted(PINNED_FIXTURES))
def test_reingest_adds_zero_events_for_every_adapter(
    tmp_path: Path, adapter_name: str
) -> None:
    """Re-ingesting a case inserts nothing new, for every registered adapter."""
    source = PINNED_FIXTURES[adapter_name]
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    target = input_dir / source.name
    target.write_bytes(source.read_bytes())

    created = runner.invoke(
        app,
        [
            "new",
            "demo",
            "--input",
            str(input_dir),
            "--adapter",
            f"{source.name}={adapter_name}",
        ],
    )
    assert created.exit_code == 0, created.output

    first = runner.invoke(app, ["ingest", "demo"])
    assert first.exit_code == 0, first.output
    assert "Total: 0 new events" not in first.output, (
        f"{adapter_name} parsed nothing from {source.name}; the pin is vacuous"
    )

    second = runner.invoke(app, ["ingest", "demo"])
    assert second.exit_code == 0, second.output
    assert "Total: 0 new events" in second.output, second.output


@pytest.fixture
def registry() -> Iterator[dict[str, adapters.Adapter]]:
    """Expose REGISTRY for mutation; restore the original entries afterwards."""
    saved = dict(REGISTRY)
    try:
        yield REGISTRY
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)


class _StreamingStub(ConfigurableAdapter):
    """A throwaway sixth adapter that declares the offset-tracking capability.

    Its two events describe bytes 0-19 of a 100-byte file, so a mid-file
    advance to 20 is distinguishable from the whole-file advance to 100 that
    every adapter gets.
    """

    name = "streamingstub"
    streams_offsets = True

    def sniff(self, path: Path) -> float:
        # Discriminative: beats genericlog's 0.1/0.0 so detect() picks the
        # stub without an --adapter override.
        return 0.95

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = self.case_relpath(path)
        for i, offset in enumerate((0, 10)):
            yield Event(
                event_id=event_id(relpath, offset),
                case_id=case_id,
                ts=None,
                ts_confidence="missing",
                source=self.name,
                source_file=relpath,
                line_start=i + 1,
                line_end=i + 1,
                severity="info",
                component=None,
                thread=None,
                session=None,
                message=f"stub event {i}",
                attrs={"byte_offset": str(offset), "byte_len": "10"},
                raw=f"stub event {i}",
            )


def _ingest_recording_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[int]:
    """Ingest a 100-byte file and return every ``completed`` value reported."""
    completed: list[int] = []
    original = Progress.update

    def _record(self: Progress, task_id: TaskID, **kwargs: Any) -> None:
        value = kwargs.get("completed")
        if isinstance(value, int):
            completed.append(value)
        original(self, task_id, **kwargs)

    monkeypatch.setattr(Progress, "update", _record)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "payload.dat").write_bytes(b"x" * 100)

    created = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert created.exit_code == 0, created.output
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    return completed


def test_streaming_adapter_opts_in_without_editing_ingest(
    registry: dict[str, adapters.Adapter],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC §5.2: a new adapter earns offset tracking by declaring the
    capability, with no edit to pipeline/ingest.py."""
    registry["streamingstub"] = _StreamingStub()

    completed = _ingest_recording_progress(tmp_path, monkeypatch)

    assert completed == [20, 100], completed


def test_offset_tracking_is_opt_in(
    registry: dict[str, adapters.Adapter],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same stub without the flag reports only the whole-file advance."""

    class _Silent(_StreamingStub):
        name = "silentstub"
        streams_offsets = False

    registry["silentstub"] = _Silent()

    completed = _ingest_recording_progress(tmp_path, monkeypatch)

    assert completed == [100], completed
