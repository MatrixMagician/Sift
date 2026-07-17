"""WR-07: a disk-full / I/O error mid-ingest aborts with zero committed events.

Forces a real ``SQLITE_FULL`` via ``PRAGMA max_page_count`` (no actual disk
fill) and drives ``_ingest`` past that page budget, asserting a ``DiskFullError``
abort AND an empty event table — the whole transaction rolled back, never a
disk-full swallowed as one failed-parse file (RESEARCH Pitfall 1).
"""

from pathlib import Path

import pytest

from sift.cli import (
    DiskFullError,
    _ingest,  # pyright: ignore[reportPrivateUsage] — drives the ingest body directly
)
from sift.config import load_config
from sift.store import CaseStore, case_db_path


def _big_log(n_lines: int) -> str:
    return "".join(
        f"2026-07-16T10:00:{i % 60:02d}+00:00 ERROR event number {i} overflow\n"
        for i in range(n_lines)
    )


def test_disk_full_mid_ingest_aborts_with_zero_events(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "big.log").write_text(_big_log(4000), encoding="utf-8")

    config = load_config()
    store = CaseStore(case_db_path(config.data_dir, "demo"))
    store.set_meta("input_dir", str(input_dir))
    store.set_meta("adapter_overrides", "[]")
    # Cap the database a couple of pages above its current size, then ingest
    # far past that budget so a genuine SQLITE_FULL fires during insert.
    page_count: int = store._conn.execute(  # pyright: ignore[reportPrivateUsage] — force SQLITE_FULL
        "PRAGMA page_count"
    ).fetchone()[0]
    store._conn.execute(  # pyright: ignore[reportPrivateUsage] — force SQLITE_FULL
        f"PRAGMA max_page_count = {page_count + 2}"
    )

    try:
        with pytest.raises(DiskFullError, match="disk full"):
            _ingest("demo", config, store)
        # The auto-rollback destroyed every savepoint AND the outer
        # transaction: zero events survive.
        assert store.query_events() == []
    finally:
        # Lift the cap so close()'s WAL checkpoint is unconstrained.
        store._conn.execute(  # pyright: ignore[reportPrivateUsage] — lift the test cap
            "PRAGMA max_page_count = 0"
        )
        store.close()
