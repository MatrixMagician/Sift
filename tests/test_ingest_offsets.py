"""Offset-tracking capability and the re-ingest determinism pin (issue #11).

``event_id = sha256(source_file, byte_offset)[:16]``, so the bounded-batch
offset bookkeeping in ``pipeline/ingest.py`` is determinism-load-bearing. The
pin here ingests one fixture per registered adapter twice and demands zero new
events the second time, for every adapter rather than genericlog alone.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift.cli import app

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
