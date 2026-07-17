"""Non-vacuous coverage regression for the ConfigurableAdapter generalisation.

The load-bearing guard: ``sift ingest`` must read the REAL per-file
``ParseStats.coverage`` for *any* ``ConfigurableAdapter``, not just genericlog.
Before the cli.py isinstance broadening, a non-genericlog adapter's
``last_stats`` is never read and coverage is fabricated as 100.0% — the exact
"nothing disappears silently" violation the project forbids. This test FAILS
against that cli.py and PASSES only after the fix.

The stub is self-contained here; the ``registry`` fixture saves/restores the
module-level REGISTRY so no other test sees the stub.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift import adapters
from sift.adapters import REGISTRY
from sift.adapters.base import ConfigurableAdapter, ParseStats
from sift.cli import app
from sift.models import Event, event_id

runner = CliRunner()


class _StubAdapter(ConfigurableAdapter):
    """A ConfigurableAdapter that emits a deliberate 10% unknown-fallback.

    total_bytes=100, unknown_fallback_bytes=10 -> coverage 0.9. It records the
    per-run config it actually received so the test can prove cli.py delivered
    ``input_root``/``tz_overrides`` to a non-genericlog adapter.
    """

    name = "stub"

    def __init__(self) -> None:
        super().__init__()
        self.seen_input_root: Path | None = None
        self.seen_tz_overrides: dict[str, str] = {}

    def sniff(self, path: Path) -> float:
        # Discriminative: beats genericlog's 0.1/0.0 so detect() picks the stub
        # without needing an --adapter override plumbed through the store.
        return 0.95

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        relpath = (
            path.relative_to(self.input_root) if self.input_root else Path(path.name)
        ).as_posix()
        # Capture what cli.py delivered before yielding any event.
        self.seen_input_root = self.input_root
        self.seen_tz_overrides = dict(self.tz_overrides)
        for i, offset in enumerate((0, 50)):
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
                attrs={},
                raw=f"stub event {i}",
            )
        self.last_stats = ParseStats(
            path=relpath,
            total_bytes=100,
            unknown_fallback_bytes=10,  # -> coverage 0.9
            event_count=2,
        )


@pytest.fixture
def registry() -> Iterator[dict[str, adapters.Adapter]]:
    """Expose REGISTRY for mutation; restore the original entries afterwards."""
    saved = dict(REGISTRY)
    try:
        yield REGISTRY
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)


def _write_config_timezones(tz_overrides: dict[str, str]) -> None:
    """Write a [timezones] config.toml into the isolated XDG_CONFIG_HOME."""
    import os

    config_home = Path(os.environ["XDG_CONFIG_HOME"]) / "sift"
    config_home.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(f'"{glob}" = "{tz}"' for glob, tz in tz_overrides.items())
    (config_home / "config.toml").write_text(
        f"[timezones]\n{lines}\n", encoding="utf-8"
    )


def test_stub_adapter_coverage_is_real_not_fabricated(
    registry: dict[str, adapters.Adapter], tmp_path: Path
) -> None:
    """A ConfigurableAdapter emitting 10% unknown-fallback bytes makes ingest
    report coverage 90.0%, never a fabricated 100.0%; and cli.py delivers
    input_root + tz_overrides to it."""
    stub = _StubAdapter()
    registry["stub"] = stub
    _write_config_timezones({"*": "Europe/London"})

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "payload.dat").write_text(
        "stub adapter payload without any timestamp\n", encoding="utf-8"
    )

    created = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert created.exit_code == 0, created.output
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output

    # Real coverage read from last_stats — NOT the fabricated 1.0 default.
    assert "coverage 90.0%" in result.output, result.output
    assert "coverage 100.0%" not in result.output, result.output

    # Config delivery reached the non-genericlog adapter.
    assert stub.seen_input_root == input_dir
    assert stub.seen_tz_overrides == {"*": "Europe/London"}


def test_genericlog_ingest_coverage_unchanged(tmp_path: Path) -> None:
    """Regression: a genericlog ingest still reports its real (100%) coverage —
    the isinstance broadening must not alter the reference adapter's path."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "app.log").write_text(
        "2026-07-16T10:00:00+00:00 INFO service started\n"
        "2026-07-16T10:00:01+00:00 ERROR connection pool exhausted\n",
        encoding="utf-8",
    )

    created = runner.invoke(app, ["new", "demo", "--input", str(input_dir)])
    assert created.exit_code == 0, created.output
    result = runner.invoke(app, ["ingest", "demo"])
    assert result.exit_code == 0, result.output
    assert "app.log" in result.output
    assert "coverage 100.0%" in result.output, result.output
    assert "2 events" in result.output, result.output
