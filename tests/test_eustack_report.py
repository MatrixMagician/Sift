"""``render/eustack_report.py`` rendering tests (EUS-07/08/09).

Covers the D-09 changed-only progression section, the D-05 widened CSV (one
column per dump plus the delta pair), and the D-01/D-02 ordering basis
rendering this plan's Task 1 adds.

Reuses ``tests/test_eustack_progression.py``'s own fixture-bundle helper
(``_bundle_for``) over the same synthetic ``tests/fixtures/eustack/
progression/`` trio, since that fixture set already carries the D-08
grew-then-shrank and D-09 appeared/vanished properties this plan renders.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from sift.adapters.eustack import EustackAdapter
from sift.config import load_config
from sift.models import Event
from sift.pipeline.eustack import load_rules
from sift.pipeline.eustack_progression import (
    ORDER_BASIS_FILENAME,
    ORDER_BASIS_TIMESTAMP,
    ORDERING_UNVERIFIED_MESSAGE,
    EustackBundle,
    analyse_eustack_bundle,
)
from sift.render.eustack_report import (
    render_eustack_markdown,
    write_eustack_signatures_csv,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eustack" / "progression"
_RULES, _RULES_HASH = load_rules()
_THRESHOLDS = load_config().eustack.thresholds


def _parse_progression_fixture(name: str) -> list[Event]:
    adapter = EustackAdapter()
    adapter.input_root = _FIXTURE_DIR
    return list(adapter.parse(_FIXTURE_DIR / name, "progression-report-test"))


def _bundle_for(*names: str) -> EustackBundle:
    """Concatenate several fixtures' events and run the full bundle
    orchestration over them, exactly as ``sift eustack`` would."""
    events: list[Event] = []
    for name in names:
        events.extend(_parse_progression_fixture(name))
    return analyse_eustack_bundle(events, _RULES, _RULES_HASH, _THRESHOLDS)


def _section(markdown_text: str, heading: str) -> str:
    """The text of one ``## <heading>`` section, up to (excluding) the next
    ``## `` heading or the end of the document."""
    lines = markdown_text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line == f"## {heading}"), None
    )
    assert start is not None, f"section {heading!r} not found in rendered markdown"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


# ------------------------------------------------------------------ Task 1 ---


def test_csv_header_carries_one_column_per_dump(tmp_path: Path) -> None:
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    header = next(csv.reader(csv_path.open(encoding="utf-8")))
    assert len(header) == 8 + 3 + 2
    assert tuple(header[8:11]) == (
        "dump_charlie.txt",
        "dump_bravo.txt",
        "dump_alpha.txt",
    )


def test_csv_keeps_unchanged_signatures(tmp_path: Path) -> None:
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    rows = list(csv.reader(csv_path.open(encoding="utf-8")))
    header, data_rows = rows[0], rows[1:]
    leaf_index = header.index("leaf_frame")
    assert any(row[leaf_index] == "_shi_allocBlock" for row in data_rows)


def test_progression_section_lists_only_changed_signatures() -> None:
    # _field Markdown-escapes underscores (mirrors test_cli_perfmon.py's own
    # HAZARD_NON_OVERLAP.replace("_", r"\_") convention for the same reason).
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    progression_section = _section(render_eustack_markdown(bundle), "Progression")
    assert "_shi_allocBlock".replace("_", r"\_") not in progression_section
    for matched in (
        "CDSSQueryEngine::WaitUntilFinished",
        "MSIQTask::GetNextPreferredJob",
        "curl_multi_poll".replace("_", r"\_"),
        "MSICommandQTask::GetNextCommand",
    ):
        assert matched in progression_section


def test_progression_section_shows_step_and_overall_deltas() -> None:
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    progression_section = _section(render_eustack_markdown(bundle), "Progression")
    warehouse_line = next(
        line
        for line in progression_section.splitlines()
        if "CDSSQueryEngine::WaitUntilFinished" in line
    )
    assert "4;-2" in warehouse_line
    assert re.search(r"\|\s*2\s*\|\s*changed\s*\|", warehouse_line)


def test_progression_section_calls_out_appeared_and_vanished() -> None:
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    progression_section = _section(render_eustack_markdown(bundle), "Progression")
    newcomer_line = next(
        line
        for line in progression_section.splitlines()
        if "curl_multi_poll".replace("_", r"\_") in line
    )
    assert "appeared" in newcomer_line
    departing_line = next(
        line
        for line in progression_section.splitlines()
        if "MSICommandQTask::GetNextCommand" in line
    )
    assert "vanished" in departing_line


def test_order_basis_and_flag_are_rendered() -> None:
    trio_text = render_eustack_markdown(
        _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    )
    assert ORDER_BASIS_TIMESTAMP in trio_text

    fallback_text = render_eustack_markdown(
        _bundle_for("dump_charlie.txt", "dump_delta_nots.txt")
    )
    assert ORDER_BASIS_FILENAME in fallback_text
    assert ORDERING_UNVERIFIED_MESSAGE in fallback_text


def test_dumps_table_and_progression_table_preserve_resolved_order(
    tmp_path: Path,
) -> None:
    """The CSV's per-dump column order and the rendered dumps-table row order
    both equal ``bundle.progression.dumps`` order exactly — proving the
    renderer preserved the resolved D-02 fallback order rather than
    re-deriving one."""
    bundle = _bundle_for("dump_charlie.txt", "dump_delta_nots.txt")
    resolved_order = tuple(d.source_file for d in bundle.progression.dumps)
    assert resolved_order == ("dump_charlie.txt", "dump_delta_nots.txt")

    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    header = next(csv.reader(csv_path.open(encoding="utf-8")))
    assert tuple(header[8:10]) == resolved_order

    # _field Markdown-escapes underscores (mirrors test_cli_perfmon.py's own
    # HAZARD_NON_OVERLAP.replace("_", r"\_") convention) -- undo that before
    # comparing against the unescaped resolved order.
    dumps_section = _section(render_eustack_markdown(bundle), "Dumps")
    rendered_order = tuple(
        line.split("|")[2].strip().replace(r"\_", "_")
        for line in dumps_section.splitlines()
        if line.startswith("| ") and "Index" not in line and "---" not in line
    )
    assert rendered_order == resolved_order
