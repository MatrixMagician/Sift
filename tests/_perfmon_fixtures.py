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

from sift.adapters.dssperfmon import (
    _short_counter_name,  # pyright: ignore[reportPrivateUsage] — the exact mapping the collision guard must prove
)

PDH_HEADER_PREFIX = "(PDH-CSV 4.0) (Eastern Standard Time)(300)"

_HOST = "env-325602laio1use1"
# Naive PDH wall-clock stamps, 30 s apart, dated to match the reference case.
_STAMPS = [
    "04/07/2026 12:39:09.397",
    "04/07/2026 12:39:39.397",
    "04/07/2026 12:40:09.397",
    "04/07/2026 12:40:39.397",
]


def _counter(obj: str, counter: str) -> str:
    r"""``\\host\Object(Instance)\Counter`` — the fully-qualified PDH form."""
    return f"\\\\{_HOST}\\{obj}\\{counter}"


def _write(tmp_path: Path, name: str, header: list[str], rows: list[list[str]]) -> Path:
    """Write one QUOTE_ALL, LF-terminated PDH-CSV strictly beneath ``tmp_path``.

    ``tmp_path`` is pytest-supplied and the filename is fixed by the caller-side
    builder, so no fixture can be aimed at a repo or user file (T-13-FIXPATH).
    The shipped Hartford artefact is LF-terminated, so these imitate that.
    """
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _read(path: Path) -> list[list[str]]:
    """Tokenise a written fixture back into rows (header first)."""
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.reader(handle) if row]


# ---------------------------------------------------------------- builders ---


def write_collision_csv(tmp_path: Path) -> Path:
    r"""Two INSTANCES of one object carrying the same counter (WR-03).

    ``Process(MSTRSvr)\Size(MB)`` and ``Process(other)\Size(MB)`` are distinct
    columns whose ``_short_counter_name`` is identically ``Size(MB)``. Two
    different counters of one object (Hartford has ``Size(MB)`` and ``RSS(MB)``)
    do NOT collide, which is why the instance axis is the one varied here.
    """
    header = [
        PDH_HEADER_PREFIX,
        _counter("Process(MSTRSvr)", "Size(MB)"),
        _counter("Process(other)", "Size(MB)"),
        _counter("System", "RAM used(MB)"),
    ]
    rows = [
        [stamp, str(401600 + i), str(1200 + i), str(463900 + i)]
        for i, stamp in enumerate(_STAMPS[:3])
    ]
    return _write(tmp_path, "collision.csv", header, rows)


def write_drift_csv(tmp_path: Path) -> Path:
    """A mid-file row narrower than the header, well-formed rows either side (WR-05).

    Hartford is uniformly width 23 across all 13,596 rows, so drift detection has
    no other way to be exercised. The defect is placed strictly between good rows
    because an edge-only drift would not distinguish mid-file detection from a
    truncated-file heuristic.
    """
    header = [
        PDH_HEADER_PREFIX,
        _counter("System", "Total CPU"),
        _counter("System", "RAM used(MB)"),
        _counter("Process(MSTRSvr)", "Size(MB)"),
    ]
    rows: list[list[str]] = [
        [_STAMPS[0], "19", "463915", "401603"],
        [_STAMPS[1], "20", "463920", "401610"],
        [_STAMPS[2], "21", "463925"],  # drifted: one cell short, mid-file
        [_STAMPS[3], "22", "463930", "401620"],
    ]
    return _write(tmp_path, "drift.csv", header, rows)


def write_non_finite_csv(tmp_path: Path) -> Path:
    """A ``nan`` and an ``inf`` cell on otherwise healthy, correctly-sized rows (D-11).

    Hartford has zero non-numeric cells, and these two are not non-numeric
    anyway: the adapter's ``_bad_cells`` probe is a bare ``float()``, which
    accepts both. They therefore pass as healthy readings today — that is the
    exact gap D-11 closes.
    """
    header = [
        PDH_HEADER_PREFIX,
        _counter("System", "RAM used(MB)"),
        _counter("MicroStrategy Server Users(CastorServer)", "Open Sessions"),
    ]
    rows = [
        [_STAMPS[0], "463915", "1488"],
        [_STAMPS[1], "nan", "1490"],
        [_STAMPS[2], "463925", "inf"],
        [_STAMPS[3], "463930", "1495"],
    ]
    return _write(tmp_path, "non_finite.csv", header, rows)


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
