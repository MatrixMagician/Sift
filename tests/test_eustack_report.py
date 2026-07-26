"""``render/eustack_report.py`` rendering tests (EUS-07/08/09).

Covers the D-09 changed-only progression section, the D-05 widened CSV (one
column per dump plus the delta pair), the D-01/D-02 ordering basis rendering
(Task 1), the D-07 matched/leaf-frame identity projection, the D-06
formula-injection guard, and the two honesty gates this plan closes: D-13
ownership-blind vocabulary and D-10 population-only phrasing, both asserted
over strings the renderer actually emits rather than over source text
(Task 2).

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
from sift.config import EustackThresholdsConfig, load_config
from sift.models import Event
from sift.pipeline.eustack import load_rules
from sift.pipeline.eustack_progression import (
    ORDER_BASIS_FILENAME,
    ORDER_BASIS_TIMESTAMP,
    ORDERING_UNVERIFIED_MESSAGE,
    EustackBundle,
    analyse_eustack_bundle,
)
from sift.render import eustack_report
from sift.render.eustack_report import (
    render_eustack_json,
    render_eustack_markdown,
    write_eustack_signatures_csv,
)
from sift.render.perfmon_report import _csv_safe as _perfmon_csv_safe

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eustack" / "progression"
_REQUIREMENTS_MD = Path(__file__).parent.parent / ".planning" / "REQUIREMENTS.md"
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


def _find(bundle: EustackBundle, label: str) -> object:
    """Find a progression row by its matched frame — mirrors
    ``test_eustack_progression.py``'s own ``_signature`` helper."""
    matched_frame = {
        "warehouse": "CDSSQueryEngine::WaitUntilFinished",
        "parked": "MSIQTask::GetNextPreferredJob",
        "stable": "_shi_allocBlock",
        "newcomer": "curl_multi_poll",
        "departing": "MSICommandQTask::GetNextCommand",
    }[label]
    for signature in bundle.progression.signatures:
        if signature.matched_frame == matched_frame:
            return signature
    raise AssertionError(f"no progression row found for signature {label!r}")


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


def _synthetic_dump(
    source_file: str, frames: tuple[str, ...], count: int, thread_prefix: str = "t"
) -> list[Event]:
    """``count`` synthetic threads sharing one authored frame chain, stamped
    onto ``source_file`` — the minimal shape ``group_dumps``/``analyse_eustack``
    need per dump, hand-built rather than parsed so a crafted symbol reaches
    the pipeline byte-for-byte."""
    events: list[Event] = []
    for i in range(count):
        lines = [f"TID {i}:\n"]
        for idx, frame in enumerate(frames):
            lines.append(f"#{idx}  0x{idx:016x} {frame}\n")
        events.append(
            Event(
                event_id="0" * 16,
                case_id="case",
                ts=None,
                ts_confidence="missing",
                source="eustack",
                source_file=source_file,
                line_start=1,
                line_end=1,
                severity="unknown",
                component=None,
                thread=f"{thread_prefix}{i}",
                session=None,
                message="",
                attrs={},
                raw="".join(lines),
            )
        )
    return events


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


# ------------------------------------------------------------------ Task 2 ---


def test_identity_projection_omits_full_frames_tuple(tmp_path: Path) -> None:
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    warehouse = _find(bundle, "warehouse")
    assert len(warehouse.frames) > 2  # type: ignore[attr-defined]
    hidden_frames = [
        f
        for f in warehouse.frames  # type: ignore[attr-defined]
        if f != warehouse.matched_frame and f != warehouse.leaf_frame  # type: ignore[attr-defined]
    ]
    assert hidden_frames, "fixture must carry a frame beyond matched/leaf"

    markdown_text = render_eustack_markdown(bundle)
    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    csv_text = csv_path.read_text(encoding="utf-8")

    for frame in hidden_frames:
        assert frame not in markdown_text
        assert frame not in csv_text


def test_identity_projection_has_no_hash_column(tmp_path: Path) -> None:
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    rows = list(csv.reader(csv_path.open(encoding="utf-8")))
    header = rows[0]
    assert not any(re.search(r"hash", cell, re.IGNORECASE) for cell in header)
    hex16 = re.compile(r"[0-9a-f]{16}", re.IGNORECASE)
    for row in rows:
        for cell in row:
            assert hex16.fullmatch(cell) is None


def test_csv_safe_guards_formula_trigger_symbol(tmp_path: Path) -> None:
    """D-06/T-17-01: a frame symbol crafted to begin with a spreadsheet
    formula trigger is neutralised by the imported ``_csv_safe`` guard
    (identity-checked so a future reimplementation would fail here), and a
    legitimately negative ``overall_delta`` stays a bare numeric cell rather
    than being quoted into text.

    ``pipeline.eustack.normalise`` always ``.strip()``s a frame body (its own
    tail-drop plus the shared ``adapters.eustack._condense_symbol``), so a
    literal leading space before the trigger can never survive into a stored
    ``SignatureGroup`` frame — that leading-whitespace-before-a-trigger case
    is instead proven directly against the imported guard, exactly the shape
    ``_csv_safe``'s own docstring (``perfmon_report.py:203``) documents.
    """
    assert eustack_report._csv_safe is _perfmon_csv_safe  # noqa: SLF001
    assert eustack_report._csv_safe(" =cmd").startswith("'")  # noqa: SLF001

    trigger_frame = "=cmd|('calc')!A1"
    events = _synthetic_dump("dumpA.txt", (trigger_frame,), count=5) + _synthetic_dump(
        "dumpB.txt", (trigger_frame,), count=2
    )
    bundle = analyse_eustack_bundle(
        events, _RULES, _RULES_HASH, EustackThresholdsConfig()
    )
    assert tuple(d.source_file for d in bundle.progression.dumps) == (
        "dumpA.txt",
        "dumpB.txt",
    )
    signature = bundle.progression.signatures[0]
    assert signature.overall_delta == -3
    assert signature.leaf_frame == trigger_frame

    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    rows = list(csv.reader(csv_path.open(encoding="utf-8")))
    header, row = rows[0], rows[1]
    assert row[header.index("leaf_frame")] == f"'{trigger_frame}"
    assert row[header.index("overall_delta")] == "-3"


_LOCK_FRAMES = (
    "__lll_lock_wait",
    "pthread_mutex_lock",
    "MSynch::CriticalSection::Enter",
    "Alpha::Caller",
)


def test_ownership_blind_vocabulary_absent_from_rendered_bundle(
    tmp_path: Path,
) -> None:
    """D-13/T-17-13: the three D-05 prohibited terms, read from
    REQUIREMENTS.md at runtime exactly as
    ``test_ownership_blind_vocabulary_absent_from_source_and_emitted_output``
    (tests/test_eustack_rules.py) does, are absent from the rendered
    Markdown, JSON and written CSV of a genuine multi-dump bundle carrying a
    real lock-convergence finding."""
    requirements_text = _REQUIREMENTS_MD.read_text(encoding="utf-8")
    match = re.search(r'the word "(\w+)"', requirements_text)
    assert match is not None, "REQUIREMENTS.md must name the forbidden term"
    forbidden_term = match.group(1)
    prohibited_terms = (forbidden_term, "owner", "holder")

    events = _synthetic_dump(
        "dumpA.txt", _LOCK_FRAMES, count=5, thread_prefix="a"
    ) + _synthetic_dump("dumpB.txt", _LOCK_FRAMES, count=5, thread_prefix="b")
    bundle = analyse_eustack_bundle(
        events, _RULES, _RULES_HASH, EustackThresholdsConfig()
    )
    assert bundle.saturation.lock_sites, "synthetic scenario must produce a lock site"
    assert any(
        f.dimension == "lock_convergence_count" for f in bundle.saturation.flags
    ), "synthetic scenario must produce a lock flag"

    markdown_text = render_eustack_markdown(bundle)
    json_text = render_eustack_json(bundle)
    csv_path = tmp_path / "sig.csv"
    write_eustack_signatures_csv(bundle, csv_path)
    csv_text = csv_path.read_text(encoding="utf-8")

    candidates = [markdown_text, json_text, csv_text]
    assert candidates, "candidate string set must be non-empty"
    for candidate in candidates:
        for term in prohibited_terms:
            found = re.search(rf"\b{re.escape(term)}\b", candidate, re.IGNORECASE)
            assert found is None, (
                f"prohibited term {term!r} found in rendered output"
            )


def test_progression_section_is_population_phrased() -> None:
    """D-10: the rendered progression section carries no word-boundary
    thread-identifier VALUE token and none of the per-thread continuity
    verbs, on a genuinely non-empty section (a non-vacuity guard, mirroring
    ``test_no_per_tid_claim_in_progression_strings`` in
    ``tests/test_eustack_progression.py`` but over RENDERED output)."""
    bundle = _bundle_for("dump_charlie.txt", "dump_bravo.txt", "dump_alpha.txt")
    progression_section = _section(render_eustack_markdown(bundle), "Progression")
    assert progression_section.strip(), "progression section must be non-empty"

    for verb in ("persisted", "remained", "stayed", "still blocked"):
        found = re.search(rf"\b{re.escape(verb)}\b", progression_section, re.IGNORECASE)
        assert found is None, (
            f"continuity verb {verb!r} found in rendered progression section"
        )
    identifier_value = re.search(
        r"\bTID\W{0,3}\d+\b", progression_section, re.IGNORECASE
    )
    assert identifier_value is None, (
        "thread-identifier value found in rendered progression section"
    )
