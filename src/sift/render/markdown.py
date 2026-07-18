"""Markdown triage report renderer (REPT-01, D-03/D-04/D-05).

``render_markdown`` is a pure function of an open ``CaseStore``: it reads the
persisted hypotheses, clusters and ``triage_*`` run-meta and returns one
self-contained Markdown string. It never constructs an inference client, never
re-runs clustering/labelling and never recomputes the citation verdict — the
FLAGGED marker and degraded banner are surfaced straight from the persisted
state (ADR 0004, the anti-hallucination gate stays load-bearing).

Every rendered field is passed through ``sanitise`` (WR-01/T-06-01): titles,
narratives, labels, cited ids and appendix raw text are all attacker-controlled
in a shared ``case.db``. Appendix raw additionally goes inside a fenced code
block whose fence is longer than any backtick run in the body, so hostile log
bytes cannot break out of the fence and inject Markdown.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, cast

from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.models import Event
    from sift.store import CaseStore, Cluster, StoredHypothesis

# event_id is sha256(...)[:16] -> always [0-9a-f]{16}, a valid anchor slug.
_EVT_RE = re.compile(r"\[evt:([0-9a-f]{16})\]")

# D-04: cap appendix raw text so multi-line stack traces / MCM blocks cannot
# balloon the report. Measured in UTF-8 bytes.
RAW_BYTE_CAP = 2048


def _link_citations(narrative: str, appendix_ids: set[str]) -> str:
    """Rewrite ``[evt:<id>]`` to an anchor link, but only for in-appendix ids.

    A cited id that is not a stored/appendix event stays plain text — never a
    dangling link (Pitfall 2).
    """

    def repl(match: re.Match[str]) -> str:
        eid = match.group(1)
        return f"[evt:{eid}](#evt-{eid})" if eid in appendix_ids else match.group(0)

    return _EVT_RE.sub(repl, narrative)


def _fence(body: str) -> str:
    """Fence ``body`` in a backtick run longer than any it contains (min 3)."""
    longest = run = 0
    for ch in body:
        if ch == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}\n{body}\n{ticks}"


def _truncate_raw(raw: str) -> str:
    """Return raw sanitised + fenced, truncated to the byte cap with an elision
    marker naming original -> kept bytes when it exceeds the cap (D-04)."""
    encoded = raw.encode("utf-8")
    if len(encoded) <= RAW_BYTE_CAP:
        return _fence(sanitise(raw))
    kept = encoded[:RAW_BYTE_CAP].decode("utf-8", errors="ignore")
    marker = f"\n… [truncated {len(encoded)} → {RAW_BYTE_CAP} bytes]"
    return _fence(sanitise(kept) + marker)


def _hypotheses_section(
    hyps: list[StoredHypothesis], appendix_ids: set[str]
) -> list[str]:
    lines = ["## Ranked hypotheses", ""]
    for h in hyps:
        marker = "OK" if h.citations_valid else "FLAGGED"
        lines.append(
            sanitise(f"### {h.hyp_index}. {h.title}  ({h.confidence}, {marker})")
        )
        lines.append("")
        lines.append(_link_citations(sanitise(h.narrative), appendix_ids))
        lines.append("")
        lines.append(sanitise(f"*Confidence reasoning:* {h.confidence_reasoning}"))
        if h.contradicting_evidence:
            lines.append(
                sanitise(f"*Contradicting evidence:* {h.contradicting_evidence}")
            )
        if h.suggested_next_steps:
            lines.append("")
            lines.append("*Suggested next steps:*")
            for step in h.suggested_next_steps:
                lines.append(sanitise(f"- {step}"))
        cites = " ".join(f"[evt:{e}]" for e in h.supporting_event_ids)
        lines.append("")
        lines.append(_link_citations(sanitise(f"Cites: {cites}"), appendix_ids))
        lines.append("")
    return lines


def _appendix_section(events: dict[str, Event]) -> list[str]:
    lines = ["## Evidence appendix", ""]
    for eid in sorted(events):
        ev = events[eid]
        lines.append(f'#### <a id="evt-{eid}"></a>`evt:{eid}`')
        provenance = f"{ev.source_file}:{ev.line_start}-{ev.line_end} · {ev.severity}"
        lines.append(sanitise(provenance))
        lines.append("")
        lines.append(_truncate_raw(ev.raw))
        lines.append("")
    return lines


def _cluster_section(clusters: list[Cluster]) -> list[str]:
    lines = ["## Cluster inventory", ""]
    if clusters:
        lines.append("| Cluster | Count | Severity | Label |")
        lines.append("| --- | --- | --- | --- |")
        for c in clusters:
            name = (c.label or c.signature).replace("\n", " ")
            lines.append(
                sanitise(f"| {c.cluster_id} | {c.count} | {c.severity_max} | {name} |")
            )
    else:
        lines.append("_No clusters._")
    lines.append("")
    return lines


def render_markdown(store: CaseStore) -> str:
    """Render a self-contained Markdown triage report from ``store`` (REPT-01)."""
    hyps = store.query_hypotheses()
    clusters = store.query_clusters()
    cited = sorted({eid for h in hyps for eid in h.supporting_event_ids})
    events = store.get_events_by_ids(cited)
    appendix_ids = set(events)
    degraded = store.get_meta("triage_degraded") == "1"

    out: list[str] = ["# Sift Triage Report", ""]

    if degraded:
        out.append(
            "> **DEGRADED RUN** — some hypotheses are FLAGGED (invalid citations) "
            "or raw model output was persisted; treat flagged rows with care."
        )
        out.append("")

    # Executive summary (D-05).
    flagged = sum(1 for h in hyps if not h.citations_valid)
    out.append("## Executive summary")
    out.append("")
    out.append(
        sanitise(
            f"{len(hyps)} ranked hypotheses across {len(clusters)} clusters"
            f" ({flagged} FLAGGED)."
        )
    )
    out.append("")

    out.extend(_hypotheses_section(hyps, appendix_ids))

    # WR-03: a hard-degraded run persists zero schema-valid hypotheses but stores
    # the raw model output in triage_raw so the operator can inspect it. Surface
    # it here (fenced + byte-capped, like the appendix raw) so "nothing
    # disappears silently" — otherwise the raw is unreachable without opening the
    # sqlite file by hand.
    raw = store.get_meta("triage_raw")
    if raw:
        out.append("## Raw model output (unvalidated)")
        out.append("")
        out.append(
            "_The model output could not be schema-validated even after the "
            "repair round-trip; the unvalidated raw is shown below for "
            "inspection._"
        )
        out.append("")
        out.append(_truncate_raw(raw))
        out.append("")

    out.extend(_appendix_section(events))
    out.extend(_cluster_section(clusters))

    # Timeline (D-05).
    out.append("## Timeline")
    out.append("")
    out.append(sanitise(store.get_meta("triage_timeline_summary") or "_None._"))
    out.append("")

    # Unexplained signals (D-05).
    out.append("## Unexplained signals")
    out.append("")
    loaded: object = json.loads(store.get_meta("triage_unexplained_signals") or "[]")
    signals = cast("list[object]", loaded) if isinstance(loaded, list) else []
    if signals:
        for sig in signals:
            out.append(sanitise(f"- {sig}"))
    else:
        out.append("_None._")
    out.append("")

    # Run metadata (D-05).
    out.append("## Run metadata")
    out.append("")
    out.append(sanitise(f"- Model: {store.get_meta('triage_model') or '-'}"))
    out.append(
        sanitise(f"- Prompt hash: {store.get_meta('triage_prompt_hash') or '-'}")
    )
    out.append(
        sanitise(f"- Embedding model: {store.get_meta('embedding_model') or '-'}")
    )
    out.append(sanitise(f"- Degraded: {'yes' if degraded else 'no'}"))
    out.append(
        sanitise(f"- Generated at: {store.get_meta('triage_created_at') or '-'}")
    )
    out.append("")

    return "\n".join(out)
