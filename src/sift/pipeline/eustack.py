"""Deterministic eu-stack thread-role classifier (EUS-01, EUS-02).

Like ``mcm.py`` and ``perfmon.py`` this module is typer-free, print-free,
SQL-free and I/O-free beyond reading a rules file: it is pure over a raw
eu-stack thread block (``Event.raw``) plus a loaded ``ThreadRoleRules``, and
NEVER touches the store, the CLI, the network, an LLM or a subprocess. Roles
come only from the versioned rules file — this module computes, it never
guesses, and it never routes classification through an LLM, an embedding or a
similarity score.

Determinism (D-03): a signature is the full ordered tuple of normalised frame
symbols, full depth, with instruction addresses excluded — two dumps of the
same stack (differing only in address) collapse to the same signature, and
classification is memoised per signature rather than per thread.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Shared, not copied (D-08): iter_frames and _condense_symbol live on the
# shipped adapter; a second frame regex here would be free to drift from it.
from sift.adapters.eustack import (
    _condense_symbol,  # pyright: ignore[reportPrivateUsage] — imported, never redeclared, so normalise() and the adapter's own condensing cannot drift apart (D-08)
    iter_frames,
)

_RULES_PACKAGE = "sift.rules"
_RULES_FILE = "eustack_roles.toml"

# The five buckets a signature's classification partitions into (success
# criterion 1). `unclassified` is the residual — never a rule role.
Role = Literal[
    "idle-parked", "blocked-on-external", "blocked-on-lock", "running", "unclassified"
]
# The four rule-assignable buckets (D-12): `unclassified` is illegal in the
# rules file because it is defined as "matched no rule below".
RuleRole = Literal["idle-parked", "blocked-on-external", "blocked-on-lock", "running"]
MatchKind = Literal["exact", "prefix", "contains"]
# D-07: the split between "no rule recognised this stack" and "this stack has
# no resolvable frame to test a rule against" — two different problems with
# two different fixes (curate a rule vs obtain symbols).
Reason = Literal["matched-no-rule", "no-resolvable-frame"]


class Rule(BaseModel):
    """One curated `[[rule]]` row. Validators (duplicate/normalisation
    rejection) are 15-04's scope — this model only shapes the row."""

    model_config = ConfigDict(extra="forbid")

    role: RuleRole
    subsystem: str
    match: MatchKind = "exact"  # D-09: omitting `match` means exact, never contains.
    pattern: str


class RulesMeta(BaseModel):
    """The `[meta]` table — provenance for a rules file with no git history
    of its own once loaded via `[eustack] rules_path` (D-11)."""

    model_config = ConfigDict(extra="forbid")

    version: int
    validated_against: str


class ThreadRoleRules(BaseModel):
    """The whole parsed rules file. `tomllib` preserves `[[rule]]`
    array-of-tables order verbatim as a list — that order IS the D-01
    precedence, so no separate `priority` field exists anywhere."""

    model_config = ConfigDict(extra="forbid")

    meta: RulesMeta
    rule: tuple[Rule, ...]


class Classification(BaseModel):
    """The result of classifying one signature. `pattern` is the matched
    rule's pattern TEXT, not its row index (D-04) — reordering the file never
    changes what a previously-reported result means."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    subsystem: str | None
    pattern: str | None
    frame_index: int | None
    reason: Reason | None


def normalise(symbol: str) -> str:
    """Canonicalise one frame symbol for signature and rule matching (D-05).

    Drops the ``- <lib> <source>:<line>`` tail (reusing the adapter's own
    ``_condense_symbol`` rather than re-implementing the split), then drops
    any version suffix by splitting on the FIRST ``@`` and keeping the head.
    Splitting on the first ``@`` rather than ``@@`` is load-bearing: the
    reference capture carries single-`@` suffixes
    (``clock_nanosleep@GLIBC_2.2.5``, ``cnd_timedwait@GLIBC_2.28``,
    ``pthread_rwlock_rdlock@GLIBC_2.2.5``) alongside the double-`@@` form, and
    a literal ``@@`` split would leave those three build-brittle. Template
    argument lists are KEPT — stripping them collapses 93 signatures to 88.
    """
    condensed = _condense_symbol(symbol)
    head, _, _tail = condensed.partition("@")
    return head.strip()


def signature_of(raw: str) -> tuple[str, ...]:
    """The full ordered tuple of normalised frame symbols for one raw eu-stack
    thread block, full depth, instruction addresses excluded (D-03)."""
    return tuple(normalise(body) for _, body in iter_frames(raw))


def load_rules(rules_path: str | None = None) -> tuple[ThreadRoleRules, str]:
    """Load and validate the thread-role rules file.

    With no argument, loads the packaged default via `importlib.resources`;
    with `rules_path`, reads that file instead (the `[eustack] rules_path`
    operator override). Returns the validated model plus a 16-character
    lowercase hex content hash (D-11) — writing that hash into `store.meta`
    is Phase 17's job, so no store import belongs here.
    """
    if rules_path is not None:
        source = rules_path
        text = Path(rules_path).read_text(encoding="utf-8")
    else:
        source = f"{_RULES_PACKAGE}/{_RULES_FILE}"
        text = (
            importlib.resources.files(_RULES_PACKAGE)
            .joinpath(_RULES_FILE)
            .read_text(encoding="utf-8")
        )
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # Never fall back to defaults silently on a malformed file (T-04-02
        # / config.py:186-192's convention, extended to the rules file).
        raise ValueError(f"invalid rules file {source}: {exc}") from exc
    rules = ThreadRoleRules.model_validate(data)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return rules, content_hash


def classify_signature(
    signature: tuple[str, ...], rules: ThreadRoleRules
) -> Classification:
    """Classify one signature: rule-major, first-match-wins in TOML file
    order (D-01).

    The OUTER loop is the rules in file order; the INNER loop is the
    signature's frames `#0`..`#N`. This ordering is the entire point — under
    a frame-major loop, stack depth rather than file order would decide
    precedence, and editing the rules file could not reorder outcomes
    (success criterion 2 would be unachievable). The first rule matching any
    frame wins immediately; no further rules or frames are scanned.
    """
    for rule in rules.rule:
        for index, frame in enumerate(signature):
            if rule.match == "exact":
                hit = frame == rule.pattern
            elif rule.match == "prefix":
                hit = frame.startswith(rule.pattern)
            else:  # "contains"
                hit = rule.pattern in frame
            if hit:
                return Classification(
                    role=rule.role,
                    subsystem=rule.subsystem,
                    pattern=rule.pattern,
                    frame_index=index,
                    reason=None,
                )
    return Classification(
        role="unclassified",
        subsystem=None,
        pattern=None,
        frame_index=None,
        reason="matched-no-rule",
    )
