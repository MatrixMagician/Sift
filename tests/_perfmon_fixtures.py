"""Synthetic PDH-CSV builders for the three paths the real artefacts cannot reach.

The Hartford DSSPerformanceMonitor export is clean in exactly the ways that make
Phase 13's defensive branches untestable from it: its 23 counters yield 22 unique
short names (no collision), all 13,596 data rows are width 23 (no drift), and it
contains zero non-numeric cells (no ``nan``/``inf``). Each builder below
manufactures one of those conditions so the corresponding branch — WR-03
(collision), WR-05 (mid-file drift), D-11 (non-finite-but-float-parseable) — can
be exercised at all.

Every builder writes strictly beneath the pytest-supplied ``tmp_path``; none
accepts a caller-chosen destination, so a fixture can never overwrite repo files
(T-13-FIXPATH). Each builder is paired with a test asserting the fixture
genuinely carries the property it claims: a builder that quietly stops producing
its defect must fail loudly here rather than turn a downstream test green for the
wrong reason (T-13-VACUOUS).

This is a plain helper module, not a ``test_``-prefixed one, so its guard tests
run only when it is named explicitly (``uv run pytest tests/_perfmon_fixtures.py``).
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from sift.adapters.dssperfmon import _short_counter_name

PDH_HEADER_PREFIX = "(PDH-CSV 4.0) (Eastern Standard Time)(300)"


# ------------------------------------------------------------------ guards ---


def test_collision_fixture_really_collides(tmp_path: Path) -> None:
    """Two distinct header columns must map to ONE short counter name (WR-03)."""
    rows = _read(write_collision_csv(tmp_path))
    header = rows[0]
    shorts = [_short_counter_name(column) for column in header[1:]]
    duplicated = [name for name in shorts if shorts.count(name) > 1]
    assert duplicated, f"no colliding short name in {shorts}"
    colliding = {
        column for column in header[1:] if _short_counter_name(column) in duplicated
    }
    # The columns differ; their short names do not. That is the collision.
    assert len(colliding) >= 2
    assert len({_short_counter_name(column) for column in colliding}) == 1


def test_drift_fixture_really_drifts(tmp_path: Path) -> None:
    """Cell counts must be non-uniform, mid-file — not at either edge (WR-05)."""
    rows = _read(write_drift_csv(tmp_path))
    widths = [len(row) for row in rows]
    assert len(set(widths)) > 1, f"uniform widths {widths}"
    data_widths = widths[1:]
    drifted = [i for i, width in enumerate(data_widths) if width != widths[0]]
    assert drifted, "no data row differs from the header width"
    assert 0 not in drifted, "drift must not be the first data row"
    assert len(data_widths) - 1 not in drifted, "drift must not be the last data row"


def test_non_finite_fixture_passes_bare_float(tmp_path: Path) -> None:
    """``float()`` accepts every cell; ``isfinite`` rejects exactly two (D-11).

    This is the precise gap D-11 closes: the adapter's ``_bad_cells`` probe is a
    bare ``float()``, and ``float("nan")``/``float("inf")`` both succeed — so
    these rows sail through as healthy and poison any downstream arithmetic.
    """
    rows = _read(write_non_finite_csv(tmp_path))
    cells = [cell for row in rows[1:] for cell in row[1:]]
    for cell in cells:
        float(cell)  # must not raise: _bad_cells would otherwise flag the row
    non_finite = [cell for cell in cells if not math.isfinite(float(cell))]
    assert len(non_finite) == 2, non_finite
