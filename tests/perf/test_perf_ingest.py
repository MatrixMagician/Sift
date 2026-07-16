"""M2 scale gate: 100 MB synthetic ingest < 60 s + STORE-01 portability.

The perf-marked test runs explicitly via ``uv run pytest -m perf`` — the
default suite excludes it (addopts, Pitfall 5). Generation time is excluded
from the budget: the 60 s contract covers the ingest command only.
"""

import time
from pathlib import Path

import generate_synthetic  # tests/perf is on sys.path (pytest prepend mode)
import pytest
from typer.testing import CliRunner

from sift.cli import app
from sift.config import load_config

runner = CliRunner()


def test_generator_is_deterministic(tmp_path: Path) -> None:
    """Same seed + size -> byte-identical files (runs in the default suite)."""
    a = tmp_path / "a.log"
    b = tmp_path / "b.log"
    generate_synthetic.generate(a, target_mb=1, seed=42)
    generate_synthetic.generate(b, target_mb=1, seed=42)
    assert a.stat().st_size >= 2**20
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.perf
def test_100mb_ingest_under_60s(tmp_path: Path) -> None:
    """M2 gate: parse + store + template rebuild of ~100 MB in < 60 s (CPU)."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    generate_synthetic.generate(input_dir / "big.log", target_mb=100, seed=42)

    assert runner.invoke(app, ["new", "big", "--input", str(input_dir)]).exit_code == 0
    start = time.perf_counter()
    result = runner.invoke(app, ["ingest", "big"])
    elapsed = time.perf_counter() - start

    # Visible with `-s`: the measured seconds are the M2 acceptance evidence.
    print(f"\n100 MB ingest took {elapsed:.1f} s (budget 60 s)")
    assert result.exit_code == 0, result.output[-2000:]
    assert elapsed < 60.0, f"100 MB ingest took {elapsed:.1f} s (budget 60 s)"
    assert "Template groups:" in result.output
    # STORE-01: after a clean run the case directory is exactly [case.db] —
    # no -wal/-shm siblings; deleting the directory is deleting the case.
    case_dir = load_config().data_dir / "cases" / "big"
    assert sorted(p.name for p in case_dir.iterdir()) == ["case.db"]
