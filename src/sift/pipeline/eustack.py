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
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

if TYPE_CHECKING:
    from sift.config import EustackThresholdsConfig
    from sift.models import Event

# Shared, not copied (D-08): iter_frames and _condense_symbol live on the
# shipped adapter; a second frame regex here would be free to drift from it.
from sift.adapters.eustack import (
    _condense_symbol,  # pyright: ignore[reportPrivateUsage] — imported, never redeclared, so normalise() and the adapter's own condensing cannot drift apart (D-08)
    iter_frames,
)

# Shared, not copied (S-2/D-08): _grade is mcm.py's pure, stateless two-cut-point
# grader — reused as-is rather than promoted to a shared home, so mcm.py's
# shipped, tested surface stays untouched. mcm.py imports nothing from
# sift.pipeline, so this import introduces no cycle.
from sift.pipeline.mcm import _grade  # pyright: ignore[reportPrivateUsage]

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


# --- Lock-site attribution (Phase 16 EUS-04, D-03/D-04) ---
#
# A lock "site" is the ENCLOSING APPLICATION FRAME, never the leaf: the
# shipped `blocked-on-lock` rule is a `contains` match on `__lll_lock_wait`
# (a glibc leaf), so `SignatureGroup.frame_index` points at glibc. Reporting
# the leaf would attribute every contention finding to the same futex symbol
# and tell an engineer nothing — the walk below is what makes the finding
# actionable.

# D-04 AMENDED denylist evidence: counted over the real reference capture,
# ~110 distinct top-level namespaces appear and exactly two are third-party
# (`std::` 14 frames, `boost::` 10); `__gnu_cxx::` and `abi::` are defensive
# entries for the same libstdc++/libgcc family. Every other top-level
# namespace — `MSynch::`, `CDSSQueryEngine::`, `MSIThread::`,
# `MSIThreadPoolTask::`, `MCE::`, `MDb::` and so on — is MicroStrategy, which
# is why this is a denylist of four rather than an allowlist of ~110 that
# would grow with every build.
_RUNTIME_NAMESPACES: tuple[str, ...] = ("std::", "boost::", "__gnu_cxx::", "abi::")

# D-04 edge case 1: no qualifying frame above the leaf is unknown-but-counted
# — never dropped, never attributed to the leaf. A `str | None` site field
# would make the `(-thread_count, site)` sort key raise `TypeError` when
# `None` and `str` are compared (16-RESEARCH.md Pitfall 4); substituting this
# sentinel at construction keeps `LockSite.site` typed `str` and the sort key
# total. Plain British English, no digits, none of the three D-05-prohibited
# terms.
UNKNOWN_LOCK_SITE: str = "no application call site resolved above the lock wait"

# D-05: the ownership-blind label carried on SaturationAnalysis and emitted
# at the point of reporting. States that the finding is a count of threads
# observed at a site, and that eu-stack output carries no lock-acquisition
# edges, so nothing beyond the site itself can be established. Written
# around the three prohibited terms, never paraphrasing them.
LOCK_FINDING_NOTE: str = (
    "This finding is a count of threads observed waiting at a lock site. "
    "eu-stack output carries no lock-acquisition edges, so nothing beyond "
    "the site and the thread count can be established from this data alone."
)


def enclosing_application_frame(
    frames: tuple[str, ...], frame_index: int
) -> str | None:
    """D-03/D-04: the first resolvable, non-runtime, `::`-qualified frame
    ABOVE `frame_index` (the classification's own reported index, never a
    fresh re-scan — D-04 edge case 5).

    "Above" means INCREASING index: `iter_frames()` yields `#1`, `#2`, `#3`…
    from leaf toward the thread entry point — see
    `test_tracer_thread_block_classifies_via_packaged_rules`'s worked
    example (`#0` leaf pthread_cond_timedwait -> `#3` the classifying frame
    -> `#4` MSIThread::Run(), the entry point). `frames[frame_index + 1:]` is
    therefore the walk, and a slice past the end of the tuple is empty, not
    an error — exactly how D-04 edge case 4 (the leaf is the last frame)
    resolves to `None` with no bounds check.

    An unresolvable frame (`_is_resolvable()`, reused rather than
    re-implemented) is walked PAST, never a stopping point (D-04 edge case
    2). `str.startswith(_RUNTIME_NAMESPACES)` gives the LEADING-namespace
    test for free — a prefix test, never a substring test — so a genuine
    `MBase::` frame nested inside a `std::` template argument list such as
    `std::thread::_State_impl<std::tuple<MBase::ThreadedRepeater...>>` is
    judged on its leading `std::` (correctly a runtime frame) while a frame
    whose own leading namespace is `MBase::` and which merely mentions
    `std::` inside its template arguments is correctly kept (D-04 edge
    case 3).

    `frames` entries are already `normalise()`d by `signature_of()` — this
    walk never re-normalises them; two code paths that should agree but are
    never compared is how a normalisation bug hides.

    Known, accepted imprecision (recorded openly, following ADR 0015's own
    precedent): the denylist covers the two third-party namespaces measured
    in the reference capture, so a C++-runtime namespace outside those four
    would still be reported as a site.

    Returns `None` when no such frame exists — the caller substitutes
    `UNKNOWN_LOCK_SITE` (D-04 edge case 1: unknown-but-counted, never
    dropped, never attributed to the leaf).
    """
    for frame in frames[frame_index + 1 :]:
        if not _is_resolvable(frame):
            continue
        if "::" not in frame:
            continue
        if frame.startswith(_RUNTIME_NAMESPACES):
            continue
        return frame
    return None


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


# --- Saturation & contention (Phase 16: EUS-03/04/05/06, D-10) ---
#
# Everything below consumes EustackAnalysis read-only (D-10) — the model
# above stays frozen and unchanged. This tracer (16-01) lands the first
# grouping, EUS-03 per-pool occupancy, end to end: config -> grouping ->
# grading -> a new frozen SaturationAnalysis. 16-02/16-03 add lock_sites and
# dependencies additively; both default so this task's callers never break.

FlagSeverity = Literal["info", "warn", "critical"]
FlagUnit = Literal["percent", "threads"]


class SaturationFlag(BaseModel):
    """One graded Phase 16 diagnostic signal (Success Criterion 5, D-08 AMENDED).

    ``mcm.DiagnosticFlag`` is deliberately NOT reused: its ``value_pct`` is
    locked as a ratio ``part / whole * 100`` (the milestone machine-independence
    invariant, verbatim in its own docstring), but D-07's lock-convergence flag
    is a raw thread COUNT, not a ratio — forcing it into ``value_pct`` would
    violate that documented contract. ``perfmon.py`` hit the identical mismatch
    for its own hazards and resolved it by minting ``PerfmonHazard`` rather than
    bending ``DiagnosticFlag``; this record follows that precedent, generalised
    to one type shared by all three Phase 16 flag families (S-3) so a renderer
    never has to type-narrow a ``DiagnosticFlag | SaturationFlag`` union.

    ``warn``/``critical`` travel on the record alongside ``value`` (Success
    Criterion 5): a renderer prints the computed figure beside its configured
    threshold without re-reading config. ``severity`` is a ``Literal`` rather
    than bare ``str`` — mirroring ``PerfmonHazard``'s WR-04 reasoning — so
    Pydantic rejects a typo'd severity at construction and pyright catches one
    at the call site.

    ``event_ids`` is deliberately absent: ``SignatureGroup`` has no per-thread
    event-id concept the way an MCM denial or perfmon sample does, and
    resolving an aggregate figure back to a citable event set is Phase 18's
    open design question (STATE.md Blockers). The omission is a decision, not
    an oversight.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str  # the config key graded, e.g. "unclassified_thread_pct"
    severity: FlagSeverity
    value: float
    unit: FlagUnit
    warn: float
    critical: float
    message: str  # British-English one-liner with the value inline


class PoolOccupancy(BaseModel):
    """One subsystem's busy/idle split (EUS-03).

    Occupancy is ``1 - (idle-parked threads in this subsystem / all threads in
    this subsystem)``, grouping ``EustackAnalysis.signatures`` on ``subsystem``
    (D-01). ``compute``, ``lock`` and ``cube-generation`` get a row on
    identical terms to ``job-queue`` — no allowlist of "real" pools exists.
    ``subsystem is None`` is the single ``unclassified`` row (D-02): those
    threads are counted here as their own row and appear in no other pool's
    denominator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subsystem: str | None
    total_threads: int
    idle_threads: int
    busy_threads: int
    occupancy: float
    signature_count: int


class SaturationAnalysis(BaseModel):
    """Phase 16's aggregate surface over ``EustackAnalysis`` (D-10): a NEW
    frozen model consuming Phase 15's output read-only. Phase 17 renders both
    objects. ``lock_sites`` (16-02) and ``dependencies`` (16-03) are added by
    later plans, each with a default so this task's callers never break — no
    placeholder fields exist here for them, and no ``signatures`` field is
    ever added (EUS-06 is satisfied by reading ``EustackAnalysis.signatures``
    directly; duplicating it here is exactly what 16-03's passthrough test
    guards against).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pools: tuple[PoolOccupancy, ...]
    flags: tuple[SaturationFlag, ...]


def analyse_saturation(
    analysis: EustackAnalysis, thresholds: EustackThresholdsConfig
) -> SaturationAnalysis:
    """Pure, deterministic, model-free (D-12) grouping over
    ``EustackAnalysis.signatures``. A zero-thread analysis yields empty tuples
    rather than an exception, mirroring ``analyse_eustack()``'s own contract.
    """
    # One pass, tallying per-subsystem totals and idle-parked totals plus a
    # signature count. Plain dict accumulation (never Counter.most_common(),
    # never set iteration) matches analyse_eustack()'s own discipline.
    # `subsystem` stays typed str | None throughout and is never stringified
    # — a literal "None" subsystem string could otherwise collide with the
    # unclassified row's None key (D-02).
    totals: dict[str | None, int] = {}
    idle_totals: dict[str | None, int] = {}
    signature_counts: dict[str | None, int] = {}
    for group in analysis.signatures:
        totals[group.subsystem] = totals.get(group.subsystem, 0) + group.thread_count
        signature_counts[group.subsystem] = signature_counts.get(group.subsystem, 0) + 1
        if group.role == "idle-parked":
            idle_totals[group.subsystem] = (
                idle_totals.get(group.subsystem, 0) + group.thread_count
            )

    pools: list[PoolOccupancy] = []
    for subsystem, total in totals.items():
        # `total` is structurally non-zero — a key only exists when a
        # signature carried it — so no division guard is needed here.
        idle = idle_totals.get(subsystem, 0)
        pools.append(
            PoolOccupancy(
                subsystem=subsystem,
                total_threads=total,
                idle_threads=idle,
                busy_threads=total - idle,
                occupancy=round(1 - idle / total, 4),
                signature_count=signature_counts[subsystem],
            )
        )
    # Explicit total order: thread count descending, then classified pools
    # ahead of the single None row, then subsystem name ascending. The
    # `subsystem is None` term is load-bearing twice: it fixes the None row's
    # position AND keeps None out of a direct comparison against str, which
    # raises TypeError in Python 3.
    pools.sort(key=lambda p: (-p.total_threads, p.subsystem is None, p.subsystem or ""))

    # Fixed, authored check order (mcm.compute_flags' precedent) — this
    # tracer emits the first check only; 16-02/16-03 append the rest.
    flags: list[SaturationFlag] = []
    if analysis.total_threads:
        unclassified_pct = round(
            analysis.threads_by_role["unclassified"] / analysis.total_threads * 100, 1
        )
        # _grade() returns plain str (mcm.DiagnosticFlag.severity is also bare
        # str); SaturationFlag deliberately types severity as the Literal
        # FlagSeverity (S-3/WR-04), so the cast documents that _grade()'s
        # value set is a strict subset of the three graded levels.
        severity = cast(
            "FlagSeverity",
            _grade(
                unclassified_pct,
                thresholds.unclassified_thread_pct.warn,
                thresholds.unclassified_thread_pct.critical,
            ),
        )
        flags.append(
            SaturationFlag(
                dimension="unclassified_thread_pct",
                severity=severity,
                value=unclassified_pct,
                unit="percent",
                warn=thresholds.unclassified_thread_pct.warn,
                critical=thresholds.unclassified_thread_pct.critical,
                message=f"{unclassified_pct}% of threads are unclassified.",
            )
        )
    # No per-pool occupancy flag is emitted — D-07 forbids it and EUSV2-03 is
    # deferred; no authoritative source exists for "N% busy = warning".

    return SaturationAnalysis(pools=tuple(pools), flags=tuple(flags))
