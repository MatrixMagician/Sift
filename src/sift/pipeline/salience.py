"""Deterministic salience ranking of clusters (RAG-01, SPEC §5.4).

This module mirrors ``cluster.py``'s contract: it is typer-free, print-free and
SQL-free — the caller passes in the already-queried clusters and template
groups, and this function returns a ranked list. No I/O, no LLM.

A cluster's salience combines five features, each hand-tuned per SPEC Open
Question 4: severity, event count, burstiness, novelty and temporal proximity
to the incident time. The ordering is stable and reproducible — equal scores
break ties by ``cluster_id`` ascending — because a reproducible ranking is the
groundwork for a reproducible prompt (and prompt hash); determinism is
load-bearing.

Pitfall 1 (migration 3): the persisted ``Cluster`` row has NO timestamps —
temporal features are aggregated from member ``TemplateGroup`` rows via
``cluster.template_ids``. A cluster whose members all lack timestamps scores on
severity and count only; its burstiness, novelty and proximity are a neutral 0
and the maths never divides by zero (T-04-07).
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import exp, log1p
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sift.store import Cluster, TemplateGroup

# Explicit severity rank, copied verbatim from cluster.py:56-66 — never
# lexicographic ('unknown' > 'error' as a string would be wrong). The vocabulary
# is frozen by the clusters/severity CHECK constraint, so a local copy cannot
# drift; an out-of-vocab severity defaults to rank 0 (T-04-09).
_SEVERITY_RANK = {
    "fatal": 5,
    "error": 4,
    "warn": 3,
    "info": 2,
    "debug": 1,
    "unknown": 0,
}

# Feature weights (sum 1.0) — a hand-tuned starting point per SPEC OQ4.
_W_SEVERITY = 0.35
_W_COUNT = 0.20
_W_BURST = 0.15
_W_NOVELTY = 0.10
_W_PROXIMITY = 0.20

# Clamp burst spans so a zero/negative span (single-timestamp or adversarial
# groups) can never divide by zero or blow up (T-04-07).
_SPAN_FLOOR = 1.0  # seconds

# Decay constant for novelty/proximity when the case span is degenerate.
_TAU_FALLBACK = 3600.0  # seconds


def _as_utc(dt: datetime) -> datetime:
    """Normalise a datetime to aware UTC (naive is treated as UTC).

    Mixing naive and aware datetimes raises on subtraction, so every timestamp
    that reaches the salience maths passes through here first — the caller's
    convention (naive == UTC) is honoured centrally.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp to aware UTC, or None on absent/bad input."""
    if ts is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(ts))
    except ValueError:
        return None


def _cluster_span(
    cluster: Cluster, index: dict[str, TemplateGroup]
) -> tuple[datetime | None, datetime | None]:
    """Aggregate (first_ts, last_ts) across a cluster's member groups.

    Pitfall 1: the cluster row carries no timestamps, so we join to its member
    ``TemplateGroup`` rows via ``template_ids``. Returns ``(None, None)`` when no
    member has a parseable timestamp — the neutral-feature path.
    """
    firsts: list[datetime] = []
    lasts: list[datetime] = []
    for template_id in cluster.template_ids:
        group = index.get(template_id)
        if group is None:
            continue
        first = _parse(group.first_ts)
        last = _parse(group.last_ts)
        if first is not None:
            firsts.append(first)
        if last is not None:
            lasts.append(last)
    cluster_first = min(firsts) if firsts else None
    cluster_last = max(lasts) if lasts else None
    return cluster_first, cluster_last


def _intersects_window(
    first: datetime | None,
    last: datetime | None,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    """Return whether a cluster's span intersects the [since, until] window.

    A cluster with no timestamps cannot be confirmed in-window, so it is kept
    only when no window bound is set (both None) and dropped otherwise.
    """
    if since is None and until is None:
        return True
    if first is None or last is None:
        return False
    if since is not None and last < _as_utc(since):
        return False
    return not (until is not None and first > _as_utc(until))


def rank_clusters(
    clusters: list[Cluster],
    groups: list[TemplateGroup],
    *,
    incident_time: datetime | None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[tuple[Cluster, float]]:
    """Rank clusters by salience, most incident-relevant first.

    Returns ``[(Cluster, score)]`` sorted by score descending then
    ``cluster_id`` ascending — a stable, reproducible order (identical inputs
    yield an identical list). Higher severity, higher count, a tighter burst and
    a first/last appearance closer to ``incident_time`` all raise the score.

    Temporal features are aggregated from member ``TemplateGroup`` rows (the
    cluster row has no timestamps, Pitfall 1). A cluster whose members all lack
    timestamps scores on severity and count only — burstiness, novelty and
    proximity are a neutral 0 and never divide by zero (T-04-07).

    ``since``/``until`` scope the candidate set at cluster granularity: a cluster
    whose member span does not intersect the window is dropped before scoring,
    never re-clustered. ``incident_time=None`` derives the incident time from the
    latest member ``last_ts`` (case end); if no member has any timestamp, all
    temporal features are neutral. Naive datetimes are treated as UTC.
    """
    index = {group.template_id: group for group in groups}

    # Aggregate spans and apply the window filter BEFORE scoring.
    candidates: list[tuple[Cluster, datetime | None, datetime | None]] = []
    for cluster in clusters:
        first, last = _cluster_span(cluster, index)
        if _intersects_window(first, last, since, until):
            candidates.append((cluster, first, last))
    if not candidates:
        return []

    # Derive incident time from the latest member last_ts when not supplied.
    all_lasts = [last for _c, _f, last in candidates if last is not None]
    if incident_time is not None:
        incident = _as_utc(incident_time)
    elif all_lasts:
        incident = max(all_lasts)
    else:
        incident = None

    # tau = case span / 4, or the fallback when the span is degenerate.
    all_firsts = [first for _c, first, _l in candidates if first is not None]
    if all_firsts and all_lasts:
        case_span = (max(all_lasts) - min(all_firsts)).total_seconds()
        tau = case_span / 4 if case_span > 0 else _TAU_FALLBACK
    else:
        tau = _TAU_FALLBACK

    max_count = max(cluster.count for cluster, _f, _l in candidates)
    count_denom = log1p(max_count) or 1.0

    # First pass: raw features. Burstiness is min-max normalised in a second
    # pass over the timestamped clusters only.
    raw_bursts: list[float] = []
    for cluster, first, last in candidates:
        if first is not None and last is not None:
            span = max((last - first).total_seconds(), _SPAN_FLOOR)
            raw_bursts.append(cluster.count / span)
    burst_min = min(raw_bursts) if raw_bursts else 0.0
    burst_max = max(raw_bursts) if raw_bursts else 0.0
    burst_range = burst_max - burst_min

    ranked: list[tuple[Cluster, float]] = []
    for cluster, first, last in candidates:
        severity = _SEVERITY_RANK.get(cluster.severity_max, 0) / 5
        count = log1p(cluster.count) / count_denom
        if first is not None and last is not None and incident is not None:
            span = max((last - first).total_seconds(), _SPAN_FLOOR)
            raw_burst = cluster.count / span
            burst = (raw_burst - burst_min) / burst_range if burst_range else 0.0
            novelty = exp(-abs((first - incident).total_seconds()) / tau)
            proximity = exp(-abs((last - incident).total_seconds()) / tau)
        else:
            burst = novelty = proximity = 0.0
        score = (
            _W_SEVERITY * severity
            + _W_COUNT * count
            + _W_BURST * burst
            + _W_NOVELTY * novelty
            + _W_PROXIMITY * proximity
        )
        ranked.append((cluster, score))

    ranked.sort(key=lambda item: (-item[1], item[0].cluster_id))
    return ranked
