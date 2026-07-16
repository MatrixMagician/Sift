"""Deterministic template dedup: volatile-token masking and grouping.

CLUS-01 / ADR 0003 (hand-rolled masking over drain3): a single compiled
``re.VERBOSE`` alternation masks numbers, hex, UUIDs, SIDs, paths and
timestamps in event MESSAGES only — stored ``raw`` and ``message`` stay
byte-verbatim citation evidence; masking exists only in derived template
strings. This module is typer-free, print-free and SQL-free: persistence
goes exclusively through CaseStore methods.
"""

import hashlib
import re

from sift.store import CaseStore, TemplateGroup

MASK_VERSION = 1  # bump whenever mask rules change; groups recompute cheaply

# Most-specific-first order is load-bearing (Pitfall 1): ts before num (else
# dates shatter into <NUM>-<NUM>-<NUM>), uuid before hex (else the 8-hex
# prefix wins), hex before num (else 0x1A2B splits). Every alternative is a
# linear scan — no nested quantifiers, no overlapping optionals (T-02-03).
_MASK = re.compile(
    r"""
    (?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)
  | (?P<uuid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}
             -[0-9a-fA-F]{4}-[0-9a-fA-F]{12})
  | (?P<hex>0[xX][0-9a-fA-F]+|\b[0-9a-fA-F]{8,}\b)   # 32-hex SIDs land here
  | (?P<path>(?:/[\w.\-]+){2,}|(?:[A-Za-z]:)?(?:\\[\w.\-]+){2,})
  | (?P<num>\b\d+\b)
    """,
    re.VERBOSE,
)
_PLACEHOLDER = {
    "ts": "<TS>",
    "uuid": "<UUID>",
    "hex": "<HEX>",
    "path": "<PATH>",
    "num": "<NUM>",
}

# Explicit rank order — never lexicographic comparison ('unknown' > 'error'
# as a string, which would be wrong).
_SEVERITY_RANK = {
    "fatal": 5,
    "error": 4,
    "warn": 3,
    "info": 2,
    "debug": 1,
    "unknown": 0,
}

EXEMPLAR_K = 5  # exemplar event ids kept per group, in canonical store order


def _placeholder(m: re.Match[str]) -> str:
    # lastgroup is never None: every _MASK alternative is a named group.
    assert m.lastgroup is not None
    return _PLACEHOLDER[m.lastgroup]


def mask(message: str) -> str:
    """Deterministic volatile-token masking (CLUS-01). No ML, no state."""
    return _MASK.sub(_placeholder, message)


def template_id(template: str) -> str:
    """sha256(template)[:16], mirroring the frozen event_id idiom."""
    return hashlib.sha256(template.encode()).hexdigest()[:16]


class _Agg:
    """Mutable per-template accumulator for one rebuild pass."""

    __slots__ = ("count", "exemplars", "first_ts", "last_ts", "severity_max")

    def __init__(self) -> None:
        self.count = 0
        self.first_ts: str | None = None
        self.last_ts: str | None = None
        self.severity_max = "unknown"
        self.exemplars: list[str] = []


def rebuild_template_groups(store: CaseStore) -> int:
    """Recompute ALL template groups from the store; returns the group count.

    Recompute-from-store (Pitfall 6) keeps dedup idempotent: groups always
    reflect the store's actual contents, and every stored event — including
    severity='unknown' rows — is counted in exactly one group. Streams
    summaries in canonical order, so exemplar ids and first/last timestamps
    are byte-stable across runs (CLUS-01).
    """
    aggregates: dict[str, _Agg] = {}
    for eid, ts, severity, message in store.iter_event_summaries():
        template = mask(message)
        agg = aggregates.get(template)
        if agg is None:
            agg = aggregates[template] = _Agg()
        agg.count += 1
        if ts is not None:
            if agg.first_ts is None:
                agg.first_ts = ts
            agg.last_ts = ts
        if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK[agg.severity_max]:
            agg.severity_max = severity
        if len(agg.exemplars) < EXEMPLAR_K:
            agg.exemplars.append(eid)

    groups = [
        TemplateGroup(
            template_id=template_id(template),
            template=template,
            count=agg.count,
            first_ts=agg.first_ts,
            last_ts=agg.last_ts,
            severity_max=agg.severity_max,
            exemplar_event_ids=agg.exemplars,
        )
        for template, agg in aggregates.items()
    ]
    with store.transaction():
        store.replace_template_groups(groups)
        store.set_meta("mask_version", str(MASK_VERSION))
        # WR-03: clear the stale flag ingest set with its event transaction —
        # inside the rebuild transaction, so the flag and the groups agree.
        store.set_meta("template_groups_stale", "0")
    return len(groups)
