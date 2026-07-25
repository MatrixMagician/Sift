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

Determinism contract (mirrors ``perfmon.py``'s wording verbatim, extended to
this module's aggregate output): ``model_dump_json`` is byte-identical on
re-run — no ``set`` iteration anywhere on the path, all ordering explicit.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

if TYPE_CHECKING:
    from sift.models import Event

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
    """One curated `[[rule]]` row. `pattern` must already be in `normalise()`
    canonical form (D-06) — a curator who pastes a raw versioned symbol is
    told the canonical form to use, not silently corrected."""

    model_config = ConfigDict(extra="forbid")

    role: RuleRole
    subsystem: str
    match: MatchKind = "exact"  # D-09: omitting `match` means exact, never contains.
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _pattern_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rule pattern must not be empty")
        return value

    @field_validator("pattern")
    @classmethod
    def _pattern_must_be_normalised(cls, value: str) -> str:
        canonical = normalise(value)
        if canonical != value:
            raise ValueError(
                f"rule pattern {value!r} is not normalised; use {canonical!r}"
            )
        return value


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
    # Default () so a [meta]-only file is valid: every signature then
    # classifies unclassified, a legitimate diagnostic state, not an error.
    rule: tuple[Rule, ...] = ()

    @model_validator(mode="after")
    def _no_duplicate_rules(self) -> ThreadRoleRules:
        seen: set[tuple[MatchKind, str]] = set()
        for r in self.rule:
            key = (r.match, r.pattern)
            if key in seen:
                raise ValueError(
                    f"duplicate rule (match={r.match!r}, pattern={r.pattern!r})"
                )
            seen.add(key)
        return self


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
        path = Path(rules_path)
        if not path.is_file():
            # An override that silently reverts to the packaged default is
            # the same failure class D-06 exists to prevent: the operator
            # believes their edit is live and it is not.
            raise ValueError(f"rules file not found: {rules_path}")
        text = path.read_text(encoding="utf-8")
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


# A bare, unresolved instruction address left in place of a symbol name.
_BARE_ADDRESS_RE = re.compile(r"^0x[0-9A-Fa-f]+$")


def _is_resolvable(symbol: str) -> bool:
    """D-07: is `symbol` (already `normalise()`d) a real match candidate?

    `??` and a bare hexadecimal address are eu-stack's own spellings of "no
    symbol resolved here" — such a frame stays in the signature tuple (it is
    part of the stack's identity) but is never tested against a rule.
    """
    if not symbol or symbol == "??":
        return False
    return _BARE_ADDRESS_RE.match(symbol) is None


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

    An unresolvable frame (D-07, ``_is_resolvable``) is SKIPPED as a match
    candidate — it never fires a rule — but stays part of `signature` and is
    still visible at its own index if some other rule matches elsewhere. When
    no rule matches anywhere, the residual splits on whether the signature
    held any resolvable frame at all: none resolvable is a symbols-missing
    problem (`no-resolvable-frame`); at least one resolvable frame that still
    matched nothing is a rules-drift problem (`matched-no-rule`). Both keep
    `role="unclassified"` — the split is a reason within the residual bucket,
    never a sixth role.
    """
    for rule in rules.rule:
        for index, frame in enumerate(signature):
            if not _is_resolvable(frame):
                continue
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
    reason: Reason = (
        "matched-no-rule"
        if any(_is_resolvable(frame) for frame in signature)
        else "no-resolvable-frame"
    )
    return Classification(
        role="unclassified",
        subsystem=None,
        pattern=None,
        frame_index=None,
        reason=reason,
    )


# The five buckets, in a fixed explicit order — used to zero-fill both
# per-role dicts so every key always exists (no reader ever meets a
# KeyError) and so no ``set``/``Literal`` introspection is needed on the
# output path (determinism contract above).
_ALL_ROLES: tuple[Role, ...] = (
    "idle-parked",
    "blocked-on-external",
    "blocked-on-lock",
    "running",
    "unclassified",
)


class SignatureGroup(BaseModel):
    """One distinct stack signature, its thread count and its classification.

    The record Phase 16 groups over and Phase 17 renders (D-04): role,
    subsystem, the matched pattern TEXT and the frame index answer "why did
    this thread read as idle-parked?" from the output alone, with no re-run.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    frames: tuple[str, ...]
    thread_count: int
    role: Role
    subsystem: str | None
    pattern: str | None
    frame_index: int | None
    reason: Reason | None


class EustackAnalysis(BaseModel):
    """The aggregate surface Phases 16-18 consume: the five-bucket thread and
    signature partition, the ranked signature collapse, and the full,
    never-capped unclassified report (D-15)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_threads: int
    total_signatures: int
    threads_by_role: dict[Role, int]
    signatures_by_role: dict[Role, int]
    signatures: tuple[SignatureGroup, ...]
    unclassified: tuple[SignatureGroup, ...]
    rules_hash: str
    rules_version: int
    rules_validated_against: str


def analyse_eustack(
    events: list[Event], rules: ThreadRoleRules, rules_hash: str
) -> EustackAnalysis:
    """Turn a list of events into the deterministic five-bucket partition.

    Selects thread events via ``event.thread is not None`` — exactly the
    adapter's own marker for a thread record versus a preamble or
    cap-overflow fallback record (no second notion of "is this a thread" is
    invented here). Classifies once per DISTINCT signature and fans the
    result out by thread count (success criterion 5) — never once per
    thread. Zero events (or zero thread events) yields a zero-valued
    analysis with all five role keys present, never an exception.
    """
    counts: Counter[tuple[str, ...]] = Counter(
        signature_of(event.raw) for event in events if event.thread is not None
    )

    groups: list[SignatureGroup] = []
    for signature, thread_count in counts.items():
        classification = classify_signature(signature, rules)
        groups.append(
            SignatureGroup(
                frames=signature,
                thread_count=thread_count,
                role=classification.role,
                subsystem=classification.subsystem,
                pattern=classification.pattern,
                frame_index=classification.frame_index,
                reason=classification.reason,
            )
        )
    # Explicit total order: thread count descending, ties broken ascending on
    # the frames tuple. Never Counter.most_common() (its tie behaviour is
    # unspecified) and never a set iteration.
    groups.sort(key=lambda g: (-g.thread_count, g.frames))

    threads_by_role: dict[Role, int] = {role: 0 for role in _ALL_ROLES}
    signatures_by_role: dict[Role, int] = {role: 0 for role in _ALL_ROLES}
    for group in groups:
        threads_by_role[group.role] += group.thread_count
        signatures_by_role[group.role] += 1

    return EustackAnalysis(
        total_threads=sum(counts.values()),
        total_signatures=len(groups),
        threads_by_role=threads_by_role,
        signatures_by_role=signatures_by_role,
        signatures=tuple(groups),
        unclassified=tuple(g for g in groups if g.role == "unclassified"),
        rules_hash=rules_hash,
        rules_version=rules.meta.version,
        rules_validated_against=rules.meta.validated_against,
    )
