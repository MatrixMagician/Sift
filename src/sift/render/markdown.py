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

import json
import re
from typing import TYPE_CHECKING, cast

from sift.render._util import md_escape as _escape
from sift.render._util import md_field as _field
from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.models import Event
    from sift.store import CaseStore, Cluster, StoredHypothesis, Verdict

# event_id is sha256(...)[:16] -> always [0-9a-f]{16}, a valid anchor slug.
_EVT_RE = re.compile(r"\[evt:([0-9a-f]{16})\]")
# A well-formed event id: the same hex shape _link_citations gates on. Used to
# keep a tampered/non-conforming appendix id out of a raw HTML attribute (WR-05).
_ID_RE = re.compile(r"[0-9a-f]{16}")

# D-04: cap appendix raw text so multi-line stack traces / MCM blocks cannot
# balloon the report. Measured in UTF-8 bytes.
RAW_BYTE_CAP = 2048


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
        # WR-05: eid flows verbatim into a raw HTML id attribute. Normally it is
        # sha256(...)[:16] (safe hex), but a tampered/shared case.db could carry a
        # non-conforming event_id. Only emit the HTML anchor when eid is the same
        # [0-9a-f]{16} shape _link_citations gates on; otherwise render an inert,
        # escaped code span (no anchor) so it can never break out of the attribute.
        if _ID_RE.fullmatch(eid):
            lines.append(f'#### <a id="evt-{eid}"></a>`evt:{eid}`')
        else:
            lines.append(f"#### `evt:{_field(eid)}`")
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


# R007: the report is the durable, CLI-visible record of human validation, so
# verdicts render grouped by target level in a fixed order. A target_type
# outside this vocabulary (tampered case.db with the CHECK stripped) falls into
# the trailing "Other" group — nothing disappears silently.
_VERDICT_LEVELS = (
    ("hypothesis", "Hypothesis verdicts"),
    ("cluster", "Cluster verdicts"),
    ("template", "Template verdicts"),
)

# Which context-snapshot keys can label each level, in preference order. The
# snapshot vocabulary is owned by verdicts.py and the column is opaque JSON
# from an untrusted case.db (WR-01), so these are hints, never a contract.
_VERDICT_LABEL_KEYS: dict[str, tuple[str, ...]] = {
    "hypothesis": ("title",),
    "cluster": ("label", "signature"),
    "template": ("template",),
}


def _verdict_line(v: Verdict) -> list[str]:
    """One list entry for a verdict row: state, target, label, stamp, note.

    The label comes from the opaque context snapshot defensively: only a
    non-blank ``str`` under a known key is used; anything else (missing key,
    tampered non-string JSON, whitespace) degrades to the bare ``<type>:<id>``
    spec. Every DB-sourced value goes through ``_field`` (WR-04) — the note is
    operator free text and the snapshot is model/DB text, both hostile in a
    shared case.db.
    """
    spec = f"{v.target_type}:{v.target_id}"
    label = ""
    for key in _VERDICT_LABEL_KEYS.get(v.target_type, ()):
        value = v.context.get(key)
        if isinstance(value, str) and value.strip():
            label = value
            break
    target = f"{spec} — {label}" if label else spec
    lines = [
        f"- **{_field(v.verdict)}** — {_field(target)} ({_field(v.created_at)})"
    ]
    if v.note:
        lines.append(f"  - Note: {_field(v.note)}")
    return lines


def _verdicts_section(verdicts: list[Verdict]) -> list[str]:
    """The R007 "Recorded verdicts" section: full history, newest-first.

    ``list_verdicts`` already orders newest-first (created_at DESC, rowid
    DESC); grouping by level preserves that order within each group. The
    history is append-only, so every row renders — no dedup, no collapsing.
    """
    lines = ["## Recorded verdicts", ""]
    if not verdicts:
        lines.append("_None._")
        lines.append("")
        return lines
    known = {level for level, _ in _VERDICT_LEVELS}
    groups = [
        *_VERDICT_LEVELS,
        ("__other__", "Other verdicts"),
    ]
    for level, heading in groups:
        if level == "__other__":
            rows = [v for v in verdicts if v.target_type not in known]
        else:
            rows = [v for v in verdicts if v.target_type == level]
        if not rows:
            continue
        lines.append(f"### {heading}")
        lines.append("")
        for v in rows:
            lines.extend(_verdict_line(v))
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
    out.extend(_verdicts_section(store.list_verdicts()))

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
