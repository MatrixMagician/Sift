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

import importlib.resources
import re
import tomllib
from collections import Counter, defaultdict
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
from sift.pipeline._shared import short_hash
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


class PuRule(BaseModel):
    """One curated ``[[pu]]`` row: a processing-unit (Intelligence Server work
    queue) and the dispatch frame that identifies it (ADR 0022).

    Orthogonal to ``Rule``: a ``Rule`` answers *what is this thread doing*, a
    ``PuRule`` answers *which queue is it doing it for*. Deliberately a
    separate model rather than optional fields on ``Rule`` — the two axes have
    different match semantics (file order versus stack depth), so one model
    carrying both would have to document two contradictory precedence rules.

    ``index`` is the plugin's own PU number, carried as PROVENANCE only so a
    finding can be traced back to the utility an engineer may already know. It
    is never precedence, never an array position, and never bounds-checked
    against ten (see ADR 0022 and the ``[[pu]]`` header comment in
    ``eustack_roles.toml``).
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    name: str
    subsystem: str
    match: MatchKind = "exact"  # D-09: omitting `match` means exact, never contains.
    pattern: str
    description: str

    @field_validator("name", "subsystem", "description")
    @classmethod
    def _text_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pu name, subsystem and description must not be empty")
        return value

    @field_validator("pattern")
    @classmethod
    def _pattern_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pu pattern must not be empty")
        return value

    @field_validator("pattern")
    @classmethod
    def _pattern_must_be_normalised(cls, value: str) -> str:
        canonical = normalise(value)
        if canonical != value:
            raise ValueError(
                f"pu pattern {value!r} is not normalised; use {canonical!r}"
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
    # Default () for the same reason, and additionally so a rules file written
    # before the PU axis existed still loads: every signature then carries
    # pu=None, which reads as "no PU axis configured" rather than an error.
    pu: tuple[PuRule, ...] = ()

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

    @model_validator(mode="after")
    def _no_duplicate_pu_rules(self) -> ThreadRoleRules:
        """Two ``[[pu]]`` rows matching identically would make attribution
        depend on row order — precisely what depth-wins matching exists to
        avoid — so the ambiguity is rejected at load time rather than resolved
        silently. A duplicate ``name`` across DIFFERENT patterns is legal and
        deliberate: one queue can have several dispatch frames, and they
        aggregate into one reported row.
        """
        seen: set[tuple[MatchKind, str]] = set()
        for p in self.pu:
            key = (p.match, p.pattern)
            if key in seen:
                raise ValueError(
                    f"duplicate pu rule (match={p.match!r}, pattern={p.pattern!r})"
                )
            seen.add(key)
        return self

    @model_validator(mode="after")
    def _pu_name_index_agree(self) -> ThreadRoleRules:
        """One PU name always carries one index, and one index always carries
        one name. Both directions matter: reporting is keyed on ``name``, so a
        name with two indices would render one row whose provenance is
        ambiguous, and an index reused by two names would break the trace back
        to the utility's own numbering that ``index`` exists to provide.
        """
        by_name: dict[str, int] = {}
        by_index: dict[int, str] = {}
        for p in self.pu:
            if by_name.setdefault(p.name, p.index) != p.index:
                raise ValueError(
                    f"pu name {p.name!r} carries conflicting indices "
                    f"{by_name[p.name]} and {p.index}"
                )
            if by_index.setdefault(p.index, p.name) != p.name:
                raise ValueError(
                    f"pu index {p.index} carries conflicting names "
                    f"{by_index[p.index]!r} and {p.name!r}"
                )
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
    content_hash = short_hash(text)
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


def _lock_site_for(group: SignatureGroup) -> str:
    """The lock site one `blocked-on-lock` signature group converges on.

    The single walk-and-sentinel step behind both lock tables: the global one
    `analyse_saturation` builds and the per-PU one `analyse_pu_health` builds.
    Two copies of it could disagree about the same threads.

    `frame_index` is structurally non-None on a `blocked-on-lock` group:
    `classify_signature()` sets it whenever a rule matched, and `unclassified`
    is the sole role without one. Asserted rather than silently skipped, so a
    future role change that drops `frame_index` fails loudly instead of quietly
    dropping threads out of the count.
    """
    assert group.frame_index is not None, (
        "blocked-on-lock groups always carry a matched frame_index"
    )
    found = enclosing_application_frame(group.frames, group.frame_index)
    return found if found is not None else UNKNOWN_LOCK_SITE


class PuAttribution(BaseModel):
    """Which processing unit a signature serves, and the frame that says so.

    ``frame_index`` is the DEEPEST matching frame's index — the evidence for
    the attribution, so "why is this thread attributed to Evaluation?" is
    answerable from the output alone, exactly as ``Classification.frame_index``
    does for the role axis.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int
    name: str
    subsystem: str
    description: str
    pattern: str
    frame_index: int


def attribute_pu(
    signature: tuple[str, ...], rules: ThreadRoleRules
) -> PuAttribution | None:
    """Attribute one signature to a processing unit: DEEPEST-frame-wins,
    ties broken by ``[[pu]]`` file order (ADR 0022).

    Frames run leaf-first (``#0`` is where the thread currently is) toward the
    thread entry point, so the DEEPEST match — the highest index — is the
    outermost dispatch frame, which is the queue that actually owns the
    thread. Everything shallower is work that queue called into.

    This is the deliberate divergence from the utility this mapping came from,
    whose ``TaskMap::Lookup`` returns the lowest PU index that appears anywhere
    in the block. Measured on the v1.3 reference capture, three signatures
    carry ``CDSSSQLEngineServer`` at frames #2/#8/#11 and
    ``MSIEvaluationTask::Run`` at #25/#18/#33: the utility calls all three SQL
    Engine; they are Evaluation threads that called a SQL-engine helper. Depth
    is a property of the stack, so it stays sound as rows are added; index
    order is a property of the file, so it must be curated to stay sound.

    Unresolvable frames (``_is_resolvable``, reused rather than
    re-implemented) are never match candidates, exactly as on the role axis.
    Returns ``None`` when no ``[[pu]]`` row matches anywhere — the honest
    "this thread serves no queue we can name" state, which for a healthy
    server is the correct answer for most infrastructure threads and is never
    collapsed into a catch-all bucket the way the utility's sentinel index 10
    collapses both "no match" and "PU out of range".
    """
    best: PuAttribution | None = None
    for index, frame in enumerate(signature):
        if not _is_resolvable(frame):
            continue
        for pu in rules.pu:
            if pu.match == "exact":
                hit = frame == pu.pattern
            elif pu.match == "prefix":
                hit = frame.startswith(pu.pattern)
            else:  # "contains"
                hit = pu.pattern in frame
            if hit:
                # Strictly greater, so the FIRST matching row at a given depth
                # wins the tie and the walk stays a single pass.
                if best is None or index > best.frame_index:
                    best = PuAttribution(
                        index=pu.index,
                        name=pu.name,
                        subsystem=pu.subsystem,
                        description=pu.description,
                        pattern=pu.pattern,
                        frame_index=index,
                    )
                break
    return best


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
    # The orthogonal PU axis (ADR 0022). Defaulted so every existing
    # construction site — tests included — stays valid, and so `None` keeps
    # its single meaning: no [[pu]] row matched this signature.
    pu: PuAttribution | None = None


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
                pu=attribute_pu(signature, rules),
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


class LockSite(BaseModel):
    """One enclosing application frame that threads are converging on while
    waiting inside ``__lll_lock_wait`` (EUS-04, D-03/D-05).

    ``site`` is typed ``str``, never ``str | None`` — ``UNKNOWN_LOCK_SITE``
    is substituted at construction so the sort key ``(-thread_count, site)``
    stays total (16-RESEARCH.md Pitfall 4: comparing ``None`` against ``str``
    raises ``TypeError``). This record carries a count of threads observed
    at a site and nothing more — it reports contention, never lock
    possession; eu-stack carries no monitor-ownership edges, so a wait-for
    graph cannot be built at all (see ADR 0015's permanent non-goal).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    thread_count: int
    signature_count: int


class DependencyWait(BaseModel):
    """One external dependency's wait concentration (EUS-05, D-06).

    ``subsystem`` is the verbatim ``Rule.subsystem`` of every
    ``blocked-on-external`` signature grouped into this row — never a mapped
    or renamed vocabulary. ``Rule.subsystem`` is a REQUIRED non-optional
    field, so every ``blocked-on-external`` group carries a real ``str``;
    the only groups carrying ``subsystem=None`` are ``unclassified``, and
    those never reach this pass (D-02). Typed ``str``, never ``str | None``,
    for exactly that reason.

    Grouping is on ``subsystem``, not on the matched pattern text: rules 16
    and 19 in ``eustack_roles.toml`` (``CDSSQueryEngine::WaitUntilFinished``
    and ``MDb::Wrapper::InterpretStatus``) both carry ``subsystem =
    "warehouse"`` and must aggregate into ONE row, or the same dependency
    would misleadingly appear to be two.

    Accepted consequence (D-06, stated so it is not a surprise later): the
    TOML curator owns this report's dependency axis. Adding a rule with a
    new ``subsystem`` silently adds a report row here, with no Python edit —
    the same single-source-of-truth coupling ADR 0015 chose over a second
    ``subsystem -> dependency`` mapping table living in Python.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subsystem: str
    thread_count: int
    signature_count: int


# --- Processing-unit health (ADR 0022) ---
#
# The PU axis crossed with the role axis: for each Intelligence Server work
# queue, how many of its threads are stuck at a lock, waiting on something
# external, parked idle, or running. This is the cross-tabulation that answers
# "which type of PU's threads are locked or slow", which neither axis answers
# alone.

# The label for threads no [[pu]] row matched. A real category (most
# infrastructure threads on a healthy server serve no named queue), never a
# failure, and typed as a distinct `pu_name is None` row rather than this
# string so it can never collide with a queue genuinely called "unattributed".
UNATTRIBUTED_PU: str = "unattributed"

# D-05's prohibition applies verbatim to this axis too: a PU can be reported
# as having threads waiting at a lock site, never as holding or being blocked
# BY another PU. Carried on the analysis so a renderer cannot omit it.
PU_FINDING_NOTE: str = (
    "Processing-unit attribution names the work queue a thread serves, read "
    "from its deepest dispatch frame. Thread counts per role are observations "
    "of one moment; eu-stack output carries no lock-acquisition edges and no "
    "queue-depth or wait-time figures, so no ordering between queues can be "
    "established from this data alone."
)


class PuHealth(BaseModel):
    """One processing unit's thread population, split by role.

    The row an engineer reads to answer "is the Query Engine wedged?": every
    role bucket is present and zero-filled, so a reader never meets a missing
    key and a zero is always visibly a measured zero.

    ``blocked_threads`` is deliberately the SUM of ``blocked-on-lock`` and
    ``blocked-on-external`` rather than a third independent tally: the two are
    reported separately in their own fields, and a reader who wants "not
    progressing for any reason" would otherwise add them by hand and risk
    including ``idle-parked``, which is healthy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # None is the single unattributed row (mirrors PoolOccupancy.subsystem's
    # None convention exactly).
    pu_name: str | None
    pu_index: int | None
    description: str | None
    total_threads: int
    signature_count: int
    threads_by_role: dict[Role, int]
    blocked_on_lock_threads: int
    blocked_on_external_threads: int
    blocked_threads: int
    idle_threads: int
    running_threads: int
    # Share of this PU's threads that are blocked for any reason, 0-100.
    # Reported, never graded: a queue waiting on the warehouse is doing its
    # job, so this figure has no defensible zero point (see analyse_saturation
    # and the config docstring for the measurement that settled it).
    blocked_pct: float
    # Where this PU's lock-waiting threads converge, if any — derived through
    # _lock_site_for, the single enclosing-application-frame walk
    # analyse_saturation also calls, so the PU table and the lock-site table
    # can never name different sites for the same threads.
    lock_sites: tuple[LockSite, ...] = ()


def analyse_pu_health(analysis: EustackAnalysis) -> tuple[PuHealth, ...]:
    """Cross-tabulate the PU axis against the role axis (ADR 0022).

    Pure and deterministic over ``EustackAnalysis.signatures``, read-only,
    with the same discipline as ``analyse_saturation``: insertion-ordered
    ``defaultdict`` accumulation, no ``set`` iteration on the output path, and
    an explicit total sort key.

    Rows are ordered by blocked threads descending FIRST, not by total threads:
    this table exists to surface the queue in trouble, and a queue with 4 000
    healthy idle workers should not outrank one with 12 threads stuck at a
    lock. Ties fall back to total threads descending, then attributed rows
    ahead of the single unattributed row, then name ascending — total, so the
    output is byte-identical on re-run.
    """
    totals: defaultdict[str | None, int] = defaultdict(int)
    signature_counts: defaultdict[str | None, int] = defaultdict(int)
    by_role: defaultdict[str | None, defaultdict[Role, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    meta: dict[str | None, tuple[int | None, str | None]] = {}
    lock_totals: defaultdict[str | None, defaultdict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    lock_signature_counts: defaultdict[str | None, defaultdict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for group in analysis.signatures:
        key = group.pu.name if group.pu is not None else None
        meta.setdefault(
            key,
            (group.pu.index, group.pu.description)
            if group.pu is not None
            else (None, None),
        )
        totals[key] += group.thread_count
        signature_counts[key] += 1
        by_role[key][group.role] += group.thread_count
        if group.role == "blocked-on-lock":
            # _lock_site_for is the same call analyse_saturation makes, not a
            # second derivation, so the two tables cannot disagree.
            site = _lock_site_for(group)
            lock_totals[key][site] += group.thread_count
            lock_signature_counts[key][site] += 1

    rows: list[PuHealth] = []
    for key, total in totals.items():
        roles: dict[Role, int] = {
            role: by_role[key].get(role, 0) for role in _ALL_ROLES
        }
        blocked_on_lock = roles["blocked-on-lock"]
        blocked_on_external = roles["blocked-on-external"]
        blocked = blocked_on_lock + blocked_on_external
        pu_index, description = meta.get(key, (None, None))
        sites = [
            LockSite(
                site=site,
                thread_count=count,
                signature_count=lock_signature_counts[key][site],
            )
            for site, count in lock_totals[key].items()
        ]
        sites.sort(key=lambda s: (-s.thread_count, s.site))
        rows.append(
            PuHealth(
                pu_name=key,
                pu_index=pu_index,
                description=description,
                total_threads=total,
                signature_count=signature_counts[key],
                threads_by_role=roles,
                blocked_on_lock_threads=blocked_on_lock,
                blocked_on_external_threads=blocked_on_external,
                blocked_threads=blocked,
                idle_threads=roles["idle-parked"],
                running_threads=roles["running"],
                # `total` is structurally non-zero — a key exists only when a
                # signature carried it — so no division guard is needed.
                blocked_pct=round(blocked / total * 100, 1),
                lock_sites=tuple(sites),
            )
        )
    # The `pu_name is None` term keeps None out of a direct comparison against
    # str (a TypeError in Python 3) as well as fixing the unattributed row's
    # position last within its rank.
    rows.sort(
        key=lambda r: (
            -r.blocked_threads,
            -r.total_threads,
            r.pu_name is None,
            r.pu_name or "",
        )
    )
    return tuple(rows)


class SaturationAnalysis(BaseModel):
    """Phase 16's aggregate surface over ``EustackAnalysis`` (D-10): a NEW
    frozen model consuming Phase 15's output read-only. Phase 17 renders both
    objects. No ``signatures`` field is ever added (EUS-06 is satisfied by
    reading ``EustackAnalysis.signatures`` directly; duplicating it here is
    exactly what the signature-passthrough test guards against).

    ``lock_finding_note`` lives here rather than on each ``LockSite`` row so
    the ownership-blind label (D-05) appears exactly once per report and
    Phase 17 cannot render the lock table without it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pools: tuple[PoolOccupancy, ...]
    lock_sites: tuple[LockSite, ...] = ()
    lock_finding_note: str = LOCK_FINDING_NOTE
    dependencies: tuple[DependencyWait, ...] = ()
    # The PU x role cross-tabulation (ADR 0022). Defaulted so every existing
    # construction site stays valid; an empty tuple means either no threads or
    # no [[pu]] rows configured, both of which the renderer states plainly.
    pu_health: tuple[PuHealth, ...] = ()
    pu_finding_note: str = PU_FINDING_NOTE
    flags: tuple[SaturationFlag, ...]


def analyse_saturation(  # noqa: C901, PLR0912, PLR0915 -- per-subsystem saturation tallying plus idle-parked totals (D-12)
    analysis: EustackAnalysis, thresholds: EustackThresholdsConfig
) -> SaturationAnalysis:
    """Pure, deterministic, model-free (D-12) grouping over
    ``EustackAnalysis.signatures``. A zero-thread analysis yields empty tuples
    rather than an exception, mirroring ``analyse_eustack()``'s own contract.
    """
    # One pass, tallying per-subsystem totals and idle-parked totals plus a
    # signature count. Plain defaultdict accumulation (insertion-ordered, so
    # determinism holds; never Counter.most_common(), never set iteration)
    # matches analyse_eustack()'s own discipline.
    # `subsystem` stays typed str | None throughout and is never stringified
    # — a literal "None" subsystem string could otherwise collide with the
    # unclassified row's None key (D-02).
    totals: defaultdict[str | None, int] = defaultdict(int)
    idle_totals: defaultdict[str | None, int] = defaultdict(int)
    signature_counts: defaultdict[str | None, int] = defaultdict(int)
    for group in analysis.signatures:
        totals[group.subsystem] += group.thread_count
        signature_counts[group.subsystem] += 1
        if group.role == "idle-parked":
            idle_totals[group.subsystem] += group.thread_count

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

    # --- Lock convergence (EUS-04, D-03/D-04) ---
    # Filter to blocked-on-lock signatures and walk each to its enclosing
    # application frame through _lock_site_for, the same call analyse_pu_health
    # makes for its per-PU table.
    lock_totals: defaultdict[str, int] = defaultdict(int)
    lock_signature_counts: defaultdict[str, int] = defaultdict(int)
    for group in analysis.signatures:
        if group.role != "blocked-on-lock":
            continue
        site = _lock_site_for(group)
        lock_totals[site] += group.thread_count
        lock_signature_counts[site] += 1

    lock_sites: list[LockSite] = [
        LockSite(
            site=site,
            thread_count=count,
            signature_count=lock_signature_counts[site],
        )
        for site, count in lock_totals.items()
    ]
    # Explicit total order: thread count descending, ties broken ascending on
    # the site string. Never Counter.most_common(), never set iteration.
    lock_sites.sort(key=lambda s: (-s.thread_count, s.site))

    # --- Dependency split (EUS-05, D-06) ---
    # Filter to blocked-on-external signatures and group by verbatim
    # `subsystem` — not by matched pattern text, because rules 16 and 19
    # (CDSSQueryEngine::WaitUntilFinished, MDb::Wrapper::InterpretStatus)
    # both carry subsystem="warehouse" and must aggregate into one row.
    # `Rule.subsystem` is a required non-optional field, so every group
    # reaching this pass carries a real str; unclassified groups (the only
    # ones carrying None) never have role == "blocked-on-external".
    dependency_totals: defaultdict[str, int] = defaultdict(int)
    dependency_signature_counts: defaultdict[str, int] = defaultdict(int)
    for group in analysis.signatures:
        if group.role != "blocked-on-external":
            continue
        assert group.subsystem is not None, (
            "blocked-on-external groups always carry a rule subsystem"
        )
        dependency_totals[group.subsystem] += group.thread_count
        dependency_signature_counts[group.subsystem] += 1

    dependencies: list[DependencyWait] = [
        DependencyWait(
            subsystem=subsystem,
            thread_count=count,
            signature_count=dependency_signature_counts[subsystem],
        )
        for subsystem, count in dependency_totals.items()
    ]
    # Explicit total order: thread count descending, ties broken ascending on
    # the subsystem name. Never Counter.most_common(), never set iteration.
    dependencies.sort(key=lambda d: (-d.thread_count, d.subsystem))

    # --- Processing-unit health (ADR 0022) ---
    # Computed before the flag pass so the pu_lock_blocked_count flags can walk
    # these rows in lockstep rather than re-deriving their figures.
    pu_health = analyse_pu_health(analysis)

    # Fixed, authored check order (mcm.compute_flags' precedent): unclassified
    # share, then no-resolvable-frame share, then lock convergence.
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
        # No-resolvable-frame share: the SECOND flag, inserted between
        # unclassified share and lock convergence per the fixed authored
        # order — mcm.compute_flags' precedent is a fixed append order
        # rather than a sort, so this insertion point is what keeps the
        # order correct; a later addition in the wrong place would quietly
        # break it. Divides by the SAME thread-weighted denominator the
        # unclassified-share flag uses (S-5/D-07 amended), never by
        # unclassified threads only — this is a distinct quantity from a
        # symbols-missing problem (obtain symbols) versus a rules-drift
        # problem (curate a rule), the same two-reason split ADR 0015's
        # T-15-11 control exists to preserve; one merged figure would
        # actively mislead which fix applies. Earns a flag under D-07
        # because it has a non-arbitrary zero point: perfect symbol
        # resolution.
        no_resolvable_frame_threads = sum(
            group.thread_count
            for group in analysis.unclassified
            if group.reason == "no-resolvable-frame"
        )
        no_resolvable_frame_pct = round(
            no_resolvable_frame_threads / analysis.total_threads * 100, 1
        )
        no_resolvable_severity = cast(
            "FlagSeverity",
            _grade(
                no_resolvable_frame_pct,
                thresholds.no_resolvable_frame_pct.warn,
                thresholds.no_resolvable_frame_pct.critical,
            ),
        )
        flags.append(
            SaturationFlag(
                dimension="no_resolvable_frame_pct",
                severity=no_resolvable_severity,
                value=no_resolvable_frame_pct,
                unit="percent",
                warn=thresholds.no_resolvable_frame_pct.warn,
                critical=thresholds.no_resolvable_frame_pct.critical,
                message=(
                    f"{no_resolvable_frame_pct}% of threads have no resolvable "
                    "frame."
                ),
            )
        )
    # No per-pool occupancy flag is emitted — D-07 forbids it and EUSV2-03 is
    # deferred; no authoritative source exists for "N% busy = warning".

    # One flag per over-threshold LockSite row, iterating lock_sites in its
    # already-sorted order so the flag sub-list inherits that explicit order
    # without needing a second sort key. Zero lock sites therefore emits zero
    # lock flags — exactly why the healthy reference capture raises none
    # (D-09): Rule 6 (__lll_lock_wait) matches it zero times by design.
    for site in lock_sites:
        lock_severity = cast(
            "FlagSeverity",
            _grade(
                float(site.thread_count),
                thresholds.lock_convergence_count.warn,
                thresholds.lock_convergence_count.critical,
            ),
        )
        flags.append(
            SaturationFlag(
                dimension="lock_convergence_count",
                severity=lock_severity,
                value=float(site.thread_count),
                unit="threads",
                warn=thresholds.lock_convergence_count.warn,
                critical=thresholds.lock_convergence_count.critical,
                message=(
                    f"{site.thread_count} threads are converging on the lock "
                    f"site {site.site}."
                ),
            )
        )

    # One flag per processing unit with threads waiting at a lock site,
    # iterating pu_health in its already-sorted order so the flag sub-list
    # inherits that order without a second sort key. The unattributed row is
    # SKIPPED: it is not a work queue, so "the unattributed PU has threads at
    # a lock" names nothing an engineer can act on, and those threads are
    # already counted by the per-site lock_convergence_count flags.
    #
    # LOCK-blocked threads, never blocked-on-external, and a COUNT, never the
    # blocked_pct share. Both restrictions were forced by measurement rather
    # than chosen: on the healthy reference eval case the Query Engine is 100%
    # blocked-on-external — three threads parked in
    # CDSSQueryEngine::WaitUntilFinished, which is a Query Engine thread doing
    # exactly its job — so a graded share flag reads `critical` on a server
    # with nothing wrong with it. Waiting on the warehouse is a queue's normal
    # working state and has no defensible zero point, which is the same reason
    # D-07 refuses to grade per-pool occupancy. Waiting at a lock does have
    # one: nothing.
    #
    # Not redundant with lock_convergence_count, which grades one SITE: a
    # queue whose threads are spread over four sites at five threads each
    # trips no per-site threshold while twenty of one queue's threads are
    # nonetheless stuck. The two dimensions answer "is this lock hot?" and
    # "is this queue wedged?" respectively.
    for pu_row in pu_health:
        if pu_row.pu_name is None or not pu_row.blocked_on_lock_threads:
            continue
        pu_severity = cast(
            "FlagSeverity",
            _grade(
                float(pu_row.blocked_on_lock_threads),
                thresholds.pu_lock_blocked_count.warn,
                thresholds.pu_lock_blocked_count.critical,
            ),
        )
        flags.append(
            SaturationFlag(
                dimension="pu_lock_blocked_count",
                severity=pu_severity,
                value=float(pu_row.blocked_on_lock_threads),
                unit="threads",
                warn=thresholds.pu_lock_blocked_count.warn,
                critical=thresholds.pu_lock_blocked_count.critical,
                message=(
                    f"{pu_row.blocked_on_lock_threads} of the {pu_row.pu_name} "
                    f"processing unit's {pu_row.total_threads} threads are "
                    "waiting at a lock site."
                ),
            )
        )

    # One flag per named processing unit whose blocked threads make up a
    # significant share of the WHOLE SERVER's threads.
    #
    # This is the concentration flag, and its denominator is the load-bearing
    # choice. Grading blocked threads against the QUEUE's own total was
    # implemented, measured and rejected (see the config docstring): a healthy
    # Query Engine parked in CDSSQueryEngine::WaitUntilFinished reads 100% of
    # its own queue, so that ratio reports `critical` on a healthy server.
    # Against the server's total the same population reads 2.1%, because three
    # threads out of 144 is what a healthy warehouse wait actually looks like.
    #
    # Measured separation across every capture available (2026-08-04):
    # healthy 2.1%, the 93-signature reference capture 10.5%, the shipped
    # warehouse-hang fixture 71.4% and its independent mutated twin 71.4%. The
    # 25/35 default sits above the two healthy figures and below both hang
    # figures, so it is calibrated at the boundary rather than guessed at.
    #
    # Why this earns a flag where per-pool occupancy does not (D-07, unchanged):
    # it has a non-arbitrary zero point — no queue monopolising the server —
    # and it is the ONE figure that separates the two shipped fixtures. Without
    # it, `sift eustack` prints a byte-identical all-info flag set for a
    # healthy server and for a total warehouse stall, so the operator's summary
    # line carries no signal on exactly the incident this axis exists to find.
    #
    # Deliberately blocked threads of BOTH kinds, unlike pu_lock_blocked_count
    # above: at this scale the question is "is one queue consuming the server",
    # for which a warehouse stall and a lock convergence both qualify. The
    # per-queue table alongside says which, and the message names the split so
    # the two are never confused.
    for pu_row in pu_health:
        if pu_row.pu_name is None or not pu_row.blocked_threads:
            continue
        concentration = round(pu_row.blocked_threads / analysis.total_threads * 100, 1)
        concentration_severity = cast(
            "FlagSeverity",
            _grade(
                concentration,
                thresholds.pu_blocked_share_of_server_pct.warn,
                thresholds.pu_blocked_share_of_server_pct.critical,
            ),
        )
        flags.append(
            SaturationFlag(
                dimension="pu_blocked_share_of_server_pct",
                severity=concentration_severity,
                value=concentration,
                unit="percent",
                warn=thresholds.pu_blocked_share_of_server_pct.warn,
                critical=thresholds.pu_blocked_share_of_server_pct.critical,
                message=(
                    f"{concentration}% of all threads are blocked in the "
                    f"{pu_row.pu_name} processing unit "
                    f"({pu_row.blocked_on_lock_threads} at a lock site, "
                    f"{pu_row.blocked_on_external_threads} on an external "
                    f"dependency, of {analysis.total_threads} threads total)."
                ),
            )
        )

    return SaturationAnalysis(
        pools=tuple(pools),
        lock_sites=tuple(lock_sites),
        lock_finding_note=LOCK_FINDING_NOTE,
        dependencies=tuple(dependencies),
        pu_health=pu_health,
        pu_finding_note=PU_FINDING_NOTE,
        flags=tuple(flags),
    )
