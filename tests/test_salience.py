"""Deterministic salience ranking tests (RAG-01, SPEC §5.4).

Pure-function tests: no store, no sockets. Clusters and template groups are
built by hand so each feature (severity, count, burstiness, novelty, proximity)
and edge case (missing timestamps, window filter, determinism) is exercised in
isolation. Timestamps aggregate from member ``TemplateGroup`` rows — the cluster
row carries none (migration 3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sift.pipeline.salience import (
    _SEVERITY_RANK,  # pyright: ignore[reportPrivateUsage] — drift-guard on the frozen rank dict
    rank_clusters,
)
from sift.store import Cluster, TemplateGroup

_BASE = datetime(2026, 7, 17, 9, 0, 0, tzinfo=UTC)


def _iso(minutes: int) -> str:
    """ISO timestamp `minutes` after the base instant."""
    return (_BASE + timedelta(minutes=minutes)).isoformat()


def _group(
    template_id: str,
    *,
    count: int = 1,
    first: str | None = None,
    last: str | None = None,
    severity: str = "error",
) -> TemplateGroup:
    return TemplateGroup(
        template_id=template_id,
        template=f"tpl-{template_id}",
        count=count,
        first_ts=first,
        last_ts=last,
        severity_max=severity,
        exemplar_event_ids=[f"ev-{template_id}"],
    )


def _cluster(
    cluster_id: int,
    template_ids: list[str],
    *,
    count: int,
    severity: str = "error",
) -> Cluster:
    return Cluster(
        cluster_id=cluster_id,
        label=None,
        signature=f"sig-{cluster_id}",
        severity_max=severity,
        count=count,
        template_ids=template_ids,
    )


def test_severity_rank_matches_cluster_module() -> None:
    # Frozen vocabulary — a local copy that drifts is a bug (T-04-09).
    assert _SEVERITY_RANK == {
        "fatal": 5,
        "error": 4,
        "warn": 3,
        "info": 2,
        "debug": 1,
        "unknown": 0,
    }


def test_higher_severity_and_count_outranks_lower() -> None:
    groups = [
        _group("a", count=100, first=_iso(0), last=_iso(10), severity="fatal"),
        _group("b", count=2, first=_iso(0), last=_iso(10), severity="info"),
    ]
    clusters = [
        _cluster(0, ["a"], count=100, severity="fatal"),
        _cluster(1, ["b"], count=2, severity="info"),
    ]
    ranked = rank_clusters(clusters, groups, incident_time=None)
    assert [c.cluster_id for c, _s in ranked] == [0, 1]
    assert ranked[0][1] > ranked[1][1]


def test_ties_break_by_cluster_id_and_are_deterministic() -> None:
    # Two identical clusters (same features) must return in cluster_id order,
    # and two calls must produce byte-identical output (determinism invariant).
    groups = [
        _group("a", count=5, first=_iso(0), last=_iso(5)),
        _group("b", count=5, first=_iso(0), last=_iso(5)),
    ]
    clusters = [
        _cluster(2, ["b"], count=5),
        _cluster(1, ["a"], count=5),
    ]
    first_call = rank_clusters(clusters, groups, incident_time=_BASE)
    second_call = rank_clusters(clusters, groups, incident_time=_BASE)
    assert first_call == second_call
    assert [c.cluster_id for c, _s in first_call] == [1, 2]


def test_missing_ts_scores_on_severity_and_count_without_raising() -> None:
    # All member groups lack timestamps: temporal features are neutral (0), the
    # cluster still ranks on severity+count, and nothing divides by zero.
    groups = [_group("a", count=10, severity="error")]
    clusters = [_cluster(0, ["a"], count=10, severity="error")]
    ranked = rank_clusters(clusters, groups, incident_time=None)
    assert len(ranked) == 1
    cluster, score = ranked[0]
    assert cluster.cluster_id == 0
    # severity(4/5)*0.35 + count(log1p10/log1p10=1)*0.20 = 0.28 + 0.20 = 0.48
    assert score == 0.48


def test_window_excludes_non_intersecting_cluster() -> None:
    groups = [
        _group("early", count=3, first=_iso(0), last=_iso(5)),
        _group("late", count=3, first=_iso(100), last=_iso(110)),
    ]
    clusters = [
        _cluster(0, ["early"], count=3),
        _cluster(1, ["late"], count=3),
    ]
    since = datetime.fromtimestamp(_BASE.timestamp() + 90 * 60, tz=UTC)
    ranked = rank_clusters(clusters, groups, incident_time=None, since=since)
    assert [c.cluster_id for c, _s in ranked] == [1]


def test_window_drops_cluster_without_timestamps() -> None:
    groups = [_group("a", count=3)]  # no timestamps
    clusters = [_cluster(0, ["a"], count=3)]
    until = datetime.fromtimestamp(_BASE.timestamp() + 60 * 60, tz=UTC)
    assert rank_clusters(clusters, groups, incident_time=None, until=until) == []


def test_naive_incident_time_is_treated_as_utc() -> None:
    # A naive incident_time must not raise on subtraction with aware member ts.
    groups = [_group("a", count=3, first=_iso(0), last=_iso(10))]
    clusters = [_cluster(0, ["a"], count=3)]
    naive = datetime(2026, 7, 17, 9, 10, 0)  # noqa: DTZ001 — _as_utc normalises
    ranked = rank_clusters(clusters, groups, incident_time=naive)
    assert len(ranked) == 1
