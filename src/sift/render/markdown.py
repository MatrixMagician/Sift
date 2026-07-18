"""Markdown triage report renderer (REPT-01, D-03/D-04/D-05).

``render_markdown`` is a pure function of an open ``CaseStore``: it reads the
persisted hypotheses, clusters and ``triage_*`` run-meta and returns one
self-contained Markdown string. It never constructs an inference client, never
re-runs clustering/labelling and never recomputes the citation verdict — the
FLAGGED marker and degraded banner are surfaced straight from the persisted
state (ADR 0004, the anti-hallucination gate stays load-bearing).

Every rendered field is passed through ``_field`` (WR-01/WR-04/T-06-01): titles,
narratives, labels, reasoning, next-steps, cluster names and cited ids are all
attacker-controlled in a shared ``case.db`` (or via a prompt-injected local-LLM
response). ``_field`` strips control characters (``sanitise``, T-06-01) AND
backslash-escapes Markdown structural metacharacters plus HTML-escapes ``& < >``
(WR-04), so hostile text cannot inject Markdown structure (headings, links, fake
OK markers) into the report or raw HTML (e.g. ``<img>``) into the PDF path.
Appendix raw additionally goes inside a fenced code block whose fence is longer
than any backtick run in the body, so hostile log bytes cannot break out.
"""

from __future__ import annotations

import html
import json
import re
from typing import TYPE_CHECKING, cast

from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.models import Event
    from sift.store import CaseStore, Cluster, StoredHypothesis

# event_id is sha256(...)[:16] -> always [0-9a-f]{16}, a valid anchor slug.
_EVT_RE = re.compile(r"\[evt:([0-9a-f]{16})\]")
# A well-formed event id: the same hex shape _link_citations gates on. Used to
# keep a tampered/non-conforming appendix id out of a raw HTML attribute (WR-05).
_ID_RE = re.compile(r"[0-9a-f]{16}")

# Markdown structural metacharacters that could inject headings, emphasis,
# lists, code spans, links or table columns if left raw in a DB/model field.
# Backslash comes first so we never double-escape our own escapes. `< > &` are
# handled by html.escape (they become entities, safe in Markdown AND the PDF's
# HTML), so they are deliberately NOT in this backslash set.
_MD_STRUCT = ("\\", "`", "*", "_", "#", "[", "]", "|")

# D-04: cap appendix raw text so multi-line stack traces / MCM blocks cannot
# balloon the report. Measured in UTF-8 bytes.
RAW_BYTE_CAP = 2048


def _escape(text: str) -> str:
    """Escape Markdown structural + HTML metacharacters in DB/model text (WR-04).

    Backslash-escapes Markdown structure (``\\ ` * _ # [ ] |``) then HTML-escapes
    ``& < >`` to entities. The result is inert both as inline Markdown and, once
    ``markdown.markdown`` converts it, as HTML in the PDF path — so a title or
    narrative cannot inject a heading, link, fake OK marker, or a raw ``<img>``.
    """
    for ch in _MD_STRUCT:
        text = text.replace(ch, "\\" + ch)
    return html.escape(text, quote=False)


def _field(text: str) -> str:
    """Sanitise (strip control chars) then escape a DB/model inline field."""
    return _escape(sanitise(text))


def _link_citations(narrative: str, appendix_ids: set[str]) -> str:
    """Escape DB/model prose and rewrite in-appendix ``[evt:<id>]`` tokens to
    anchor links in one pass (WR-04).

    Segments between citation tokens are ``_escape``-d so hostile prose cannot
    inject Markdown/HTML structure; the id itself is regex-gated hex, safe to
    interpolate. A cited id absent from the appendix stays escaped plain text —
    never a dangling link (Pitfall 2). Callers pass ``sanitise``-d input.
    """
    parts: list[str] = []
    last = 0
    for match in _EVT_RE.finditer(narrative):
        parts.append(_escape(narrative[last : match.start()]))
        eid = match.group(1)
        parts.append(
            f"[evt:{eid}](#evt-{eid})"
            if eid in appendix_ids
            else _escape(match.group(0))
        )
        last = match.end()
    parts.append(_escape(narrative[last:]))
    return "".join(parts)


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
        # Static Markdown structure (###, the marker) stays raw; only the
        # DB/model-sourced values are escaped (WR-04) so a title/confidence
        # cannot inject a heading, link or fake OK marker.
        lines.append(
            f"### {h.hyp_index}. {_field(h.title)}  "
            f"({_field(h.confidence)}, {marker})"
        )
        lines.append("")
        lines.append(_link_citations(sanitise(h.narrative), appendix_ids))
        lines.append("")
        lines.append(f"*Confidence reasoning:* {_field(h.confidence_reasoning)}")
        if h.contradicting_evidence:
            lines.append(
                f"*Contradicting evidence:* {_field(h.contradicting_evidence)}"
            )
        if h.suggested_next_steps:
            lines.append("")
            lines.append("*Suggested next steps:*")
            for step in h.suggested_next_steps:
                lines.append(f"- {_field(step)}")
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
        lines.append(_field(provenance))
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
            # Escape the model/DB name so a `|` cannot break the table columns
            # and structural chars cannot inject Markdown (WR-04). The static
            # pipe delimiters stay raw.
            lines.append(
                f"| {c.cluster_id} | {c.count} | {_field(c.severity_max)} "
                f"| {_field(name)} |"
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

    # Timeline (D-05). Escape the model summary (WR-04); keep the italic
    # "_None._" placeholder literal when there is no summary.
    out.append("## Timeline")
    out.append("")
    timeline = store.get_meta("triage_timeline_summary")
    out.append(_field(timeline) if timeline else "_None._")
    out.append("")

    # Unexplained signals (D-05).
    out.append("## Unexplained signals")
    out.append("")
    loaded: object = json.loads(store.get_meta("triage_unexplained_signals") or "[]")
    signals = cast("list[object]", loaded) if isinstance(loaded, list) else []
    if signals:
        for sig in signals:
            out.append(f"- {_field(str(sig))}")
    else:
        out.append("_None._")
    out.append("")

    # Run metadata (D-05). Server/config-sourced, but cheap to escape (WR-04).
    out.append("## Run metadata")
    out.append("")
    out.append(f"- Model: {_field(store.get_meta('triage_model') or '-')}")
    out.append(
        f"- Prompt hash: {_field(store.get_meta('triage_prompt_hash') or '-')}"
    )
    out.append(
        f"- Embedding model: {_field(store.get_meta('embedding_model') or '-')}"
    )
    out.append(f"- Degraded: {'yes' if degraded else 'no'}")
    out.append(
        f"- Generated at: {_field(store.get_meta('triage_created_at') or '-')}"
    )
    out.append("")

    return "\n".join(out)
