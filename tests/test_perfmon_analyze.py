"""Perfmon correlation over the ``perfmon-denial`` golden case (PERF-07/PERF-08).

This module is the anti-vacuous foundation of Phase 14. The shipped Hartford
artefacts do not overlap in time (the CSV's last sample is ~12:39:39 while the
denial is ~12:39:47 — a ~7.7 s gap with zero in-span samples), so a golden case
built on them verbatim would yield ZERO citable perfmon ``event_id``s and pass
silently. ``test_fixture_overlaps`` is the guard that fails loudly if that ever
becomes true again: it asserts ``analyse_perfmon`` over the committed
``eval/cases/perfmon-denial/input/`` pair produces an episode-scope trend whose
counters carry at least one non-None ``at_denial_event_id`` — the mechanical
proof that a real perfmon sample falls inside the denial window and is citable.

Zero sockets: this module runs only the deterministic analysers over a locally
ingested case, so the autouse ``_no_network`` conftest guard is never tripped
(EVAL-05). Later waves (14-04 integration, 14-05 ``truth.yaml``) append to this
same module and reuse ``_ingest_perfmon_case``.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path

from sift.config import McmThresholdsConfig, SiftConfig, load_config
from sift.models import Event
from sift.pipeline.mcm import McmAnalysis, analyse_mcm
from sift.pipeline.perfmon import analyse_perfmon
from sift.store import CaseStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PERFMON_CASE = _REPO_ROOT / "eval" / "cases" / "perfmon-denial"


def _ingest_perfmon_case(
    config: SiftConfig, case_dir: Path
) -> tuple[list[Event], McmAnalysis]:
    """Ingest a case's ``input/`` via the real sniff+ingest path (mirrors
    ``test_eval_cases._ingest_case``).

    Returns ``(events, mcm_analysis)``: the hydrated store events and the
    deterministic ``analyse_mcm`` result, so a later-wave test can drive
    ``analyse_perfmon(mcm, events)`` without re-ingesting. Both are pure values —
    the temp ``case.db`` is closed and discarded before returning, and event
    ``id``s are a stable function of ``(relpath, byte_offset)`` regardless of
    where the case was ingested.
    """
    from sift.cli import _ingest  # pyright: ignore[reportPrivateUsage]

    noise = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="sift-perfmon-test-") as tmp:
        db = Path(tmp) / "seed.db"
        with contextlib.redirect_stdout(noise), contextlib.redirect_stderr(noise):
            store = CaseStore(db)
            try:
                store.set_meta("input_dir", str((case_dir / "input").resolve()))
                store.set_meta("adapter_overrides", "[]")
                _ingest(case_dir.name, config, store)
                events = store.query_events()
                mcm = analyse_mcm(events, McmThresholdsConfig())
            finally:
                store.close()
    return events, mcm


def test_fixture_overlaps() -> None:
    """The golden pair is non-vacuous: >=1 counter carries a citable at-denial id.

    This is the single load-bearing guard of Wave 0. Proven demonstrably RED on
    the shipped non-overlapping pair (and on the log-only ``mcm-denial`` case):
    both yield an episode group with a ``non_overlap`` hazard, zero in-span
    samples, and therefore zero non-None ``at_denial_event_id``. It is GREEN here
    only because the authored CSV samples genuinely fall inside the resolved
    ``[window_start, denial_ts]`` window.
    """
    config = load_config({})
    events, mcm = _ingest_perfmon_case(config, _PERFMON_CASE)

    assert mcm.episodes, (
        "the denial log must auto-sniff as dsserrors and yield >=1 episode"
    )
    perfmon = analyse_perfmon(mcm, events)

    episode_groups = [g for g in perfmon.groups if g.scope == "episode"]
    assert episode_groups, "no episode-scope trend group was produced"

    citable = [
        counter.at_denial_event_id
        for group in episode_groups
        for counter in group.counters
        if counter.at_denial_event_id is not None
    ]
    assert citable, (
        "the perfmon-denial fixture no longer overlaps its denial window: no "
        "in-span sample yields a citable at_denial_event_id, so the golden case "
        "would be silently vacuous (RESEARCH Pitfall 1)"
    )

    # Source assertion (cited ⊆ store): the id names a real perfmon sample, not a
    # bare non-empty tuple. A non-None id that did not resolve here would mean the
    # trend cited an event the store never held.
    by_id = {event.event_id: event for event in events}
    assert by_id[citable[0]].source == "dssperfmon"
