"""Canonical event schema and identity.

The ``Event`` dataclass is the contract every adapter normalises into
(SPEC.md §5.1, copied field-by-field). This schema is FROZEN after Phase 1:
breaking changes require a new milestone decision recorded in
``docs/decisions/`` and a store migration — never an in-place edit.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class Event:
    """One canonical event. SPEC.md §5.1 verbatim — FROZEN after Phase 1."""

    event_id: str  # deterministic: sha256(source_file, byte_offset)[:16]
    case_id: str
    ts: datetime | None  # UTC; None if genuinely unparseable
    ts_confidence: str  # "exact" | "inferred" | "missing"
    source: str  # adapter name, e.g. "dsserrors"
    source_file: str  # relative path within the case input dir
    line_start: int  # 1-based, inclusive
    line_end: int
    severity: str  # "fatal"|"error"|"warn"|"info"|"debug"|"unknown"
    component: str | None  # adapter-specific, e.g. "MCM", unit name
    thread: str | None
    session: str | None  # e.g. MSTR SID, systemd invocation ID
    message: str  # normalised message text (multi-line permitted)
    attrs: dict[str, str]  # adapter-specific structured extras
    raw: str  # verbatim source text for citation display


def event_id(source_file: str, byte_offset: int) -> str:
    """Canonical event identity. FROZEN — changing this invalidates every stored case.

    ``source_file`` is the case-relative POSIX path (the compressed file's own
    path for ``.gz``/``.zst`` inputs, per D-07). ``byte_offset`` is the 0-based
    offset of the event's first byte in the DECOMPRESSED stream. The NUL
    separator prevents concatenation ambiguity (("a1", 1) vs ("a", 11)).
    Depends on nothing else: no case_id, no clock, no randomness.
    """
    return hashlib.sha256(f"{source_file}\x00{byte_offset}".encode()).hexdigest()[:16]


# --- Hypothesis output contract (SPEC.md §5.5) ------------------------------
#
# Field names below are AUTHORITATIVE from SPEC.md §5.5 — the same schema whose
# model_json_schema() feeds the server's constrained decoding (04-04). These
# are additive Pydantic models; they never touch the frozen Event dataclass.
# extra="forbid" is the V5 fail-loud anti-hallucination control: an unknown key
# from a tampered or hallucinating model raises rather than being silently
# accepted. Keep both models self-contained (no external $ref) so the JSON
# schema inlines Hypothesis under $defs only.


class Hypothesis(BaseModel):
    """One ranked, evidence-cited root-cause hypothesis (SPEC §5.5 verbatim)."""

    model_config = ConfigDict(extra="forbid")

    title: str
    narrative: str
    confidence: Literal["high", "medium", "low"]
    confidence_reasoning: str
    supporting_event_ids: list[str]
    contradicting_evidence: str | None
    suggested_next_steps: list[str]


class HypothesisSet(BaseModel):
    """The full triage output the model must return (SPEC §5.5 verbatim)."""

    model_config = ConfigDict(extra="forbid")

    hypotheses: list[Hypothesis]
    timeline_summary: str
    unexplained_signals: list[str]
