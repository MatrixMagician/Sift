"""Deterministic MCM fact renderer (MCM-06, Plan 11-01).

``render_mcm_facts(analysis) -> (block_text, citable_ids)`` is the model-free,
byte-identical-on-re-run source of truth for every MCM figure surfaced to the
triage prompt. It fills the versioned ``prompts/mcm_facts.md`` fragment (labels
and prose only — D-20) with figures read **verbatim** from ``analyse_mcm``
output: the denial-episode summary, the graded diagnostic flags (each surfacing
``DiagnosticFlag.value_pct`` — already computed and machine-independent, D-11, so
never re-derived here), and the top-5 attribution rows per dimension (OID /
Source / SID, D-19). Numbers originate in Python; wording lives in the template.

Every emitted line begins with an ``[evt:<id>]`` citation token, and the returned
id set is **exactly** those printed ids (the exemplar contract — never expose an
id the model was not shown). An empty analysis renders to ``("", set())`` so the
Wave-2 splice strips residue-free. Every log-derived value (attribution ``key``,
flag ``message``, window ``label``, denial timestamp) is routed through
``render._util.sanitise`` before interpolation (V5 prompt-injection defence,
T-11-01) — mirroring ``hypothesise._apply_kb_block``.

This is a leaf module: it reads the analyser's model tree and the prompt fragment
only. It must NOT import from ``sift.pipeline.hypothesise`` or ``sift.cli``
(hypothesise imports this, not the reverse).
"""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING

from sift.render._util import mb_bytes, sanitise

if TYPE_CHECKING:
    from sift.pipeline.mcm import EpisodeAnalysis, McmAnalysis

_PROMPT_PACKAGE = "sift.prompts"
_MCM_FILE = "mcm_facts.md"
_MCM_LINES_SLOT = "<<MCM_LINES>>"

# Display order for graded flags (mirrors cli.py:1059 / render/mcm_report.py) —
# critical first. An unknown severity sorts last rather than raising.
_SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}

# Top-N attribution rows surfaced per dimension (D-19: token-bounded so the fact
# block cannot crowd cluster exemplars out of the prompt budget).
_TOP_N = 5

# Max denial episodes rendered into the fact block. D-19 bounds rows PER episode
# (top-5 × 3 dimensions) but the episode COUNT was unbounded — a denial storm of
# dozens of episodes could inflate the un-budgeted prompt prefix past the model
# context (WR-01). Most-severe-first so a truncated block keeps the worst
# episodes; only the rendered episodes' ids enter the citable set.
# ponytail: fixed episode ceiling; swap for budget-aware trimming if real logs
# ever carry more than this many denial episodes.
_MAX_EPISODES = 8


def _episode_severity_rank(ea: EpisodeAnalysis) -> int:
    """The episode's worst diagnostic-flag rank (lower = more severe).

    Reuses ``_SEVERITY_ORDER`` (critical < warn < info); an episode with no
    graded flags sorts last. Used to keep the most severe episodes when the
    ``_MAX_EPISODES`` cap drops surplus ones.
    """
    return min(
        (_SEVERITY_ORDER.get(f.severity, len(_SEVERITY_ORDER)) for f in ea.flags),
        default=len(_SEVERITY_ORDER),
    )


def _load_mcm_fragment() -> str:
    """Load the versioned MCM fragment from package data (CLI-02).

    Mirrors ``hypothesise._load_triage_template`` — the same
    ``importlib.resources`` idiom, so wording changes touch no path maths.
    """
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_MCM_FILE)
        .read_text(encoding="utf-8")
    )


def render_mcm_facts(analysis: McmAnalysis) -> tuple[str, set[str]]:
    """Render the MCM fact block and the set of ids it makes citable.

    Returns ``("", set())`` when there are no episodes (residue-free strip). Each
    id in the returned set corresponds to an ``[evt:<id>]`` token actually printed
    in the block — nothing more.
    """
    if not analysis.episodes:
        return "", set()

    ids: set[str] = set()
    lines: list[str] = []

    # Cap the episode count (WR-01): keep the most severe episodes, dropping any
    # surplus. sorted() is stable, so equal-severity episodes retain their D-06
    # chronological order — deterministic. Only rendered episodes contribute ids,
    # so a dropped episode's ids stay out of the citable set (cited ⊆ prompted).
    selected = sorted(analysis.episodes, key=_episode_severity_rank)[:_MAX_EPISODES]

    for ea in selected:
        ep = ea.episode
        # Episode summary — cite the denial event; frame the AvailableMCM descent.
        denial_ts = sanitise(ep.denial_ts) if ep.denial_ts else "an unrecorded time"
        ids.add(ep.denial_event_id)
        lines.append(
            f"[evt:{ep.denial_event_id}] MCM denial at {denial_ts}; "
            f"{sanitise(ea.window.label)}."
        )

        # Graded diagnostic flags — surface value_pct verbatim (never re-derived).
        for flag in sorted(
            ea.flags,
            key=lambda f: _SEVERITY_ORDER.get(f.severity, len(_SEVERITY_ORDER)),
        ):
            eid = flag.event_ids[0]
            ids.add(eid)
            lines.append(
                f"[evt:{eid}] {sanitise(flag.severity)} flag "
                f"{sanitise(flag.dimension)} at {flag.value_pct:.1f}%: "
                f"{sanitise(flag.message)}"
            )

        # Top-5 attributions per dimension — rows are already granted-desc/key-asc
        # sorted, so a plain slice is the top-5 (D-19).
        for rows in (
            ea.attribution.by_oid,
            ea.attribution.by_source,
            ea.attribution.by_sid,
        ):
            for row in rows[:_TOP_N]:
                eid = row.event_ids[0]
                ids.add(eid)
                granted_mb = mb_bytes(row.granted_bytes)
                lines.append(
                    f"[evt:{eid}] {sanitise(row.dimension)}={sanitise(row.key)} "
                    f"granted {granted_mb:,.1f} MB"
                )

    return _load_mcm_fragment().replace(_MCM_LINES_SLOT, "\n".join(lines)), ids
