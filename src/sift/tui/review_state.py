"""Review-state helpers: latest verdict badges and progress counts (R014).

Pure store-backed functions shared by every verdict surface: badge columns
need the latest verdict per target, and the landing screen needs
ruled-vs-total counts per level. Everything here reads ONLY the bounded
aggregate tables — ``list_verdicts``, ``query_hypotheses``,
``query_clusters``, ``query_template_groups`` — never the events table, so
cost is bounded by review size, not case size (R008).

No SQL lives here (store.py owns ALL SQL) and no error handling either:
``sqlite3`` errors from a locked, corrupt or vanished case.db deliberately
bubble to the caller, exactly as ``data_access`` does — the app shell's
error screens (R012) sanitise and present them.
"""

from dataclasses import dataclass

from sift.store import VERDICT_TARGET_TYPES, CaseStore


def latest_verdicts(
    store: CaseStore, target_type: str | None = None
) -> dict[tuple[str, str], str]:
    """Latest verdict state per ``(target_type, target_id)``.

    ``list_verdicts`` returns rows newest-first (created_at DESC, rowid
    DESC), so the FIRST row seen for a target is its latest ruling; every
    later row for that target is history and is skipped. Passing
    ``target_type`` narrows the read to one level via the store's
    allowlisted filter — badge columns only ever need their own level.
    Verdicts are append-only, so history is expected, not an anomaly.
    """
    filters: dict[str, str | int] | None = None
    if target_type is not None:
        if target_type not in VERDICT_TARGET_TYPES:
            valid = ", ".join(sorted(VERDICT_TARGET_TYPES))
            raise ValueError(
                f"unknown verdict target type {target_type!r}; valid: {valid}"
            )
        filters = {"target-type": target_type}
    latest: dict[tuple[str, str], str] = {}
    for row in store.list_verdicts(filters):
        key = (row.target_type, row.target_id)
        if key not in latest:
            latest[key] = row.verdict
    return latest


@dataclass(frozen=True)
class LevelProgress:
    """Ruled-vs-total for one verdict level (R014)."""

    ruled: int
    total: int


@dataclass(frozen=True)
class ReviewProgress:
    """Ruled-vs-total counts for all three verdict levels (R014)."""

    hypotheses: LevelProgress
    clusters: LevelProgress
    templates: LevelProgress


def review_progress(store: CaseStore) -> ReviewProgress:
    """Ruled-vs-total counts per level for the landing screen (R014).

    A target counts as ruled only if it exists in the CURRENT case: a
    verdict whose target vanished under external re-analysis is history,
    not progress, so ``ruled <= total`` always holds and the counts never
    overstate review coverage. Totals come from the bounded aggregate
    queries; each target counts once no matter how many verdict rows it
    has accumulated.
    """
    latest = latest_verdicts(store)

    def _level(target_type: str, current_ids: set[str]) -> LevelProgress:
        ruled = sum(1 for tid in current_ids if (target_type, tid) in latest)
        return LevelProgress(ruled=ruled, total=len(current_ids))

    return ReviewProgress(
        hypotheses=_level(
            "hypothesis",
            {str(h.hyp_index) for h in store.query_hypotheses()},
        ),
        clusters=_level(
            "cluster",
            {str(c.cluster_id) for c in store.query_clusters()},
        ),
        templates=_level(
            "template",
            {g.template_id for g in store.query_template_groups()},
        ),
    )


def format_progress(progress: ReviewProgress) -> str:
    """One-line landing-screen summary of what is not yet ruled on (R014)."""
    return (
        f"Reviewed {progress.hypotheses.ruled}/{progress.hypotheses.total} "
        f"hypotheses · {progress.clusters.ruled}/{progress.clusters.total} "
        f"clusters · {progress.templates.ruled}/{progress.templates.total} "
        "templates"
    )
