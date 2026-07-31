"""Deterministic eu-stack fact renderer (EUS-10, Plans 18-01/18-02).

``render_eustack_facts(bundle, events) -> (block_text, citable_ids)`` is the
model-free, byte-identical-on-re-run source of truth for every eu-stack figure
surfaced to the triage prompt. It fills the versioned
``prompts/eustack_facts.md`` fragment (labels and prose only — D-16) with
figures read from ``EustackBundle`` (Phases 15-17's frozen analysis of the LAST
dump, D-11): the role-composition grouping, the three remaining Phase 16
groupings (per-pool occupancy, lock-site convergence, external-wait
concentration), each graded ``SaturationFlag``, and a capped, drop-disclosing
per-signature listing. Numbers originate in Python; wording lives in the
template.

Aggregate -> citable ``event_id`` set (the ROADMAP's flagged design question,
resolved in ``CONTEXT.md``): none of ``EustackAnalysis``/``SaturationAnalysis``/
``ProgressionAnalysis`` carries an ``event_id`` (an aggregate is one-to-many,
unlike an MCM episode or a perfmon sample), so this module independently
re-derives a ``signature -> event_id`` map from ``events`` via
``sift.pipeline.eustack.signature_of`` (D-15 leaf-module boundary: it does the
re-grouping, never widens the frozen analysis models). A population figure
cites a **bounded exemplar sample**, not the full population (D-01): the lowest
``_EXEMPLAR_K`` event_ids in sort order (D-02), reusing the existing
``[evt:<id>]`` citation token unchanged. The block states in words that it is
sampling — both the exemplar count and the true population size (D-03), via
the single-definition-site ``_sampling_sentence`` helper — so an aggregate
figure is never presented as if the population had been enumerated. For a
multi-signature aggregate the contributing signatures' event pools are
unioned FIRST, then the lowest ``_EXEMPLAR_K`` are taken (D-17), keeping the
"N of M cited as exemplars" sentence honest for the aggregate's own M.

Every emitted line begins with an ``[evt:<id>]`` citation token, and the
returned id set is **exactly** those printed ids (the D-05 exemplar contract —
never expose an id the model was not shown). Emptiness gate:
``bundle.analysis.total_threads == 0`` — the true absence of ingested eu-stack
data — never ``bundle.saturation.flags`` being empty, since a healthy,
zero-flag capture is the common case and must still render a useful block
("nothing is flagged" is itself a finding, CONTEXT.md ``<specifics>``). Every
role/subsystem/site/dimension/message string is routed through
``render._util.sanitise`` before interpolation (V5 prompt-injection defence),
mirroring ``mcm_facts``/``perfmon_facts``.

Per-signature listing (D-06/D-07/D-08): capped at ``_MAX_SIGNATURES = 8``, a
plain slice of ``bundle.analysis.signatures`` (already thread-count-descending
sorted by ``analyse_eustack`` — no second sort here). Composition-independent:
a flagged signature below the cut is never force-included. Dropped signatures
are stated as dropped whenever any exist, never mentioned when none are.

Multi-dump progression (D-09/D-10/D-11, Plan 18-03): when the resolved dump
order (``bundle.progression.order_basis``, read directly — never re-derived)
is the unverified sorted-filename fallback, or fewer than two dumps are
present, NO delta figure is emitted anywhere — a real figure carried in the
wrong order is indistinguishable from a correct one to citation validation,
so the whole layer is withheld rather than guessed at. Otherwise the resolved
dump sequence is stated, followed by capped, cited population deltas for
CHANGED signatures only, under the same ``_MAX_SIGNATURES`` cap.
``bundle.progression.scope_note`` is emitted verbatim in every branch so the
population-level-only caveat can never be omitted by construction.

This is a leaf module: it reads the analyser's model tree and the prompt
fragment only. It must NOT import from ``sift.pipeline.hypothesise`` or
``sift.cli`` (hypothesise imports this, not the reverse).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sift.pipeline._shared import load_prompt
from sift.pipeline.eustack import (
    UNKNOWN_LOCK_SITE,
    enclosing_application_frame,
    signature_of,
)
from sift.pipeline.eustack_progression import ORDER_BASIS_FILENAME, group_dumps

# Shared, not copied: perfmon_facts._cite_prefix is the single implementation
# of the D-05 printed-token contract — a second copy here could drift from it.
from sift.pipeline.perfmon_facts import (
    _cite_prefix,  # pyright: ignore[reportPrivateUsage]
)
from sift.render._util import sanitise

if TYPE_CHECKING:
    from sift.models import Event
    from sift.pipeline.eustack import SignatureGroup
    from sift.pipeline.eustack_progression import DumpSlice, EustackBundle

_EUSTACK_FILE = "eustack_facts.md"
_EUSTACK_LINES_SLOT = "<<EUSTACK_LINES>>"

# D-02: the lowest K event_ids (sort order) cited per aggregate. event_id is
# sha256(source_file, byte_offset)[:16], so this selection is stable by
# construction and needs no tie-break rule.
_EXEMPLAR_K = 3

# D-06: the per-signature listing cap. One consistent ceiling across all four
# fact modules (mcm_facts._MAX_EPISODES, perfmon_facts._MAX_GROUPS).
# ponytail: fixed group ceiling; swap for budget-aware trimming only if real
# cases ever carry more than this many signatures worth surfacing.
_MAX_SIGNATURES = 8


def _load_eustack_fragment() -> str:
    """Load the versioned eu-stack fragment from package data (CLI-02)."""
    return load_prompt(_EUSTACK_FILE)


def _sampling_sentence(k: int, population: int) -> str:
    """D-03: state both the exemplar count and the aggregate's own true
    population, so a sampled citation set is never read as an enumeration.

    Single definition site — every grouping's sampling parenthetical routes
    through this helper so the wording cannot drift between groupings.
    """
    return f"({k:,} of {population:,} thread events cited as exemplars)"


def _signature_event_ids(dump_events: list[Event]) -> dict[tuple[str, ...], list[str]]:
    """One dump's signature -> ALL its event_ids, sorted ascending (D-02).

    Feeds ``signature_of`` the event's ``raw`` field, never ``message`` — the
    adapter caps ``message`` at ``CONDENSED_FRAMES = 5``, so a message-derived
    signature would not match the analyser's. Events with ``thread is None``
    (preamble/fallback records) are skipped, mirroring ``analyse_eustack``'s
    own thread-event selection.
    """
    acc: dict[tuple[str, ...], list[str]] = {}
    for event in dump_events:
        if event.thread is None:
            continue
        acc.setdefault(signature_of(event.raw), []).append(event.event_id)
    for event_ids in acc.values():
        event_ids.sort()
    return acc


def _events_by_dump_in_order(
    events: list[Event], dumps: tuple[DumpSlice, ...]
) -> list[list[Event]]:
    """Per-dump event lists in the SAME resolved order as ``dumps``.

    ``group_dumps`` is reused rather than re-implemented (D-08 precedent) —
    this only indexes its result by each ``DumpSlice.source_file``.
    """
    by_file = group_dumps(events)
    return [by_file.get(d.source_file, []) for d in dumps]


def _union_exemplars(
    frame_tuples: list[tuple[str, ...]],
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
) -> tuple[str, ...]:
    """D-17: union every contributing signature's full id list, then sample.

    Each signature's ids are resolved by the most-recent-dump-where-present
    rule — walking ``reversed(per_dump_sig_ids)`` and taking the first dump
    whose map holds that frames tuple — the identical idiom
    ``eustack_progression.compute_progression`` already uses to resolve
    display fields, so citation and classification can never disagree about
    which dump a signature means. Returns an empty tuple when none of
    ``frame_tuples`` is present in any dump.
    """
    union: set[str] = set()
    for frames in frame_tuples:
        for sig_ids in reversed(per_dump_sig_ids):
            if frames in sig_ids:
                union.update(sig_ids[frames])
                break
    return tuple(sorted(union)[:_EXEMPLAR_K])


def _lock_site_of(group: SignatureGroup) -> str:
    """The enclosing-application-frame site a ``blocked-on-lock`` group
    converges on, substituting ``UNKNOWN_LOCK_SITE`` exactly as
    ``analyse_saturation`` does — the shipped walk and sentinel are reused,
    never re-derived, so the two can never disagree about a group's site."""
    assert group.frame_index is not None, (
        "blocked-on-lock groups always carry a matched frame_index"
    )
    found = enclosing_application_frame(group.frames, group.frame_index)
    return found if found is not None else UNKNOWN_LOCK_SITE


def _pool_lines(
    bundle: EustackBundle,
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
    ids: set[str],
) -> tuple[list[str], dict[str | None, tuple[str, ...]]]:
    """EUS-03 per-pool occupancy lines, plus the per-subsystem exemplar map
    (reused by ``_flag_lines`` for the ``unclassified_thread_pct`` flag so
    that figure is never re-derived from a second pass)."""
    lines: list[str] = []
    exemplars_by_subsystem: dict[str | None, tuple[str, ...]] = {}
    for pool in bundle.saturation.pools:
        # subsystem stays typed str | None and is compared, never stringified
        # (a literal "None" subsystem string could collide with the
        # unclassified row's None key).
        frame_tuples = [
            group.frames
            for group in bundle.analysis.signatures
            if group.subsystem == pool.subsystem
        ]
        exemplars = _union_exemplars(frame_tuples, per_dump_sig_ids)
        exemplars_by_subsystem[pool.subsystem] = exemplars
        if not exemplars:
            # No line without an [evt:] token — an uncited figure is forbidden.
            continue
        prefix = _cite_prefix(exemplars, ids)
        label = (
            sanitise(pool.subsystem) if pool.subsystem is not None else "unclassified"
        )
        lines.append(
            f"{prefix} eu-stack {label} pool occupancy: {pool.busy_threads:,} busy "
            f"threads, {pool.idle_threads:,} idle threads of {pool.total_threads:,} "
            f"total threads across {pool.signature_count:,} signatures "
            f"({pool.occupancy * 100:.2f}% occupancy). "
            f"{_sampling_sentence(len(exemplars), pool.total_threads)}"
        )
    return lines, exemplars_by_subsystem


def _lock_site_lines(
    bundle: EustackBundle,
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
    ids: set[str],
) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    """EUS-04 lock-site convergence lines, plus the per-site exemplar map
    (reused by ``_flag_lines`` for ``lock_convergence_count`` flags).

    ``lock_finding_note`` (the ownership-blind label, D-05) is emitted exactly
    once, ahead of the site lines, and only when at least one site line
    actually rendered — never a floating disclaimer over an empty section.
    The emitted lines report only that threads were observed converging at a
    site; they never state or imply lock possession or a wait-for graph.
    """
    exemplars_by_site: dict[str, tuple[str, ...]] = {}
    site_lines: list[str] = []
    for site in bundle.saturation.lock_sites:
        frame_tuples = [
            group.frames
            for group in bundle.analysis.signatures
            if group.role == "blocked-on-lock" and _lock_site_of(group) == site.site
        ]
        exemplars = _union_exemplars(frame_tuples, per_dump_sig_ids)
        exemplars_by_site[site.site] = exemplars
        if not exemplars:
            continue
        prefix = _cite_prefix(exemplars, ids)
        site_lines.append(
            f"{prefix} eu-stack lock-site convergence: {site.thread_count:,} threads "
            f"across {site.signature_count:,} signatures observed converging at "
            f"{sanitise(site.site)}. "
            f"{_sampling_sentence(len(exemplars), site.thread_count)}"
        )
    if not site_lines:
        return [], exemplars_by_site
    return [bundle.saturation.lock_finding_note, *site_lines], exemplars_by_site


def _dependency_lines(
    bundle: EustackBundle,
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
    ids: set[str],
) -> list[str]:
    """EUS-05 external-wait concentration lines. Grouped on the row's
    ``subsystem`` (never on the matched pattern text), because two distinct
    rules can share one subsystem and must aggregate into one row."""
    lines: list[str] = []
    for dep in bundle.saturation.dependencies:
        frame_tuples = [
            group.frames
            for group in bundle.analysis.signatures
            if group.role == "blocked-on-external" and group.subsystem == dep.subsystem
        ]
        exemplars = _union_exemplars(frame_tuples, per_dump_sig_ids)
        if not exemplars:
            continue
        prefix = _cite_prefix(exemplars, ids)
        lines.append(
            f"{prefix} eu-stack external-wait concentration: {dep.thread_count:,} "
            f"threads across {dep.signature_count:,} signatures waiting on "
            f"{sanitise(dep.subsystem)}. "
            f"{_sampling_sentence(len(exemplars), dep.thread_count)}"
        )
    return lines


def _flag_lines(
    bundle: EustackBundle,
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
    pool_exemplars: dict[str | None, tuple[str, ...]],
    lock_site_exemplars: dict[str, tuple[str, ...]],
    ids: set[str],
) -> list[str]:
    """One graded line per ``SaturationFlag``, giving each flag the exemplar
    triple of the aggregate it grades — never printing an uncited figure.

    ``lock_convergence_count`` flags are emitted by ``analyse_saturation()``
    exactly once per ``lock_sites`` row, in that same order (S-6, ADR 0016) —
    a plain iterator walks both in lockstep rather than matching on ``value``,
    which would be ambiguous under a thread-count tie between two sites. The
    iterator is asserted fully consumed afterwards (WR-01) so a future
    ``analyse_saturation`` change that breaks the 1:1 flags/lock_sites
    correspondence fails loudly instead of silently mis-citing.

    D-03 requires every line here to carry the same mandatory sampling
    disclosure every other grouping in this module carries: each branch below
    threads its own aggregate's true population alongside its exemplar tuple,
    never the flag's own percentage/count ``value``, so the arithmetic in the
    sentence is honest for the population the exemplars were actually drawn
    from (CR-01).
    """
    no_resolvable_frame_tuples = [
        group.frames
        for group in bundle.analysis.signatures
        if group.role == "unclassified" and group.reason == "no-resolvable-frame"
    ]
    no_resolvable_exemplars = _union_exemplars(
        no_resolvable_frame_tuples, per_dump_sig_ids
    )
    no_resolvable_population = sum(
        group.thread_count
        for group in bundle.analysis.signatures
        if group.role == "unclassified" and group.reason == "no-resolvable-frame"
    )

    lines: list[str] = []
    lock_sites_in_order = iter(bundle.saturation.lock_sites)
    for flag in bundle.saturation.flags:
        if flag.dimension == "unclassified_thread_pct":
            exemplars = pool_exemplars.get(None, ())
            population = bundle.analysis.threads_by_role["unclassified"]
        elif flag.dimension == "no_resolvable_frame_pct":
            exemplars = no_resolvable_exemplars
            population = no_resolvable_population
        elif flag.dimension == "lock_convergence_count":
            site = next(lock_sites_in_order, None)
            exemplars = (
                lock_site_exemplars.get(site.site, ()) if site is not None else ()
            )
            population = site.thread_count if site is not None else 0
        else:
            # WR-02: an unrecognised dimension must never disappear silently
            # (CLAUDE.md "nothing disappears silently") — fail loudly so a
            # future analyse_saturation addition is caught here rather than
            # quietly vanishing from the prompt.
            raise AssertionError(
                f"unhandled SaturationFlag.dimension {flag.dimension!r}"
            )
        if not exemplars:
            continue
        prefix = _cite_prefix(exemplars, ids)
        lines.append(
            f"{prefix} eu-stack saturation flag ({sanitise(flag.severity)}) "
            f"{sanitise(flag.dimension)}: {flag.value:,} {sanitise(flag.unit)} "
            f"(warn {flag.warn:,}, critical {flag.critical:,}). "
            f"{sanitise(flag.message)} "
            f"{_sampling_sentence(len(exemplars), population)}"
        )
    assert next(lock_sites_in_order, None) is None, (
        "lock_convergence_count flag count must equal len(lock_sites)"
    )
    return lines


def _signature_listing_lines(
    bundle: EustackBundle,
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
    ids: set[str],
) -> list[str]:
    """The capped, most-populous-first per-signature listing (D-06/D-07/D-08).

    A plain slice of ``bundle.analysis.signatures`` — ``analyse_eustack``
    already applies the explicit total order ``(-thread_count, frames)``, so
    a re-sort here would be a second ordering that could silently drift from
    the analyser's. Composition-independent: a signature carrying a
    saturation flag is never force-included when it falls below the cut.
    """
    selected = bundle.analysis.signatures[:_MAX_SIGNATURES]
    lines: list[str] = []
    for group in selected:
        exemplars = _union_exemplars([group.frames], per_dump_sig_ids)
        if not exemplars:
            continue
        prefix = _cite_prefix(exemplars, ids)
        parts = [f"{prefix} eu-stack signature: {group.thread_count:,} threads, "
                 f"role {sanitise(group.role)}."]
        if group.subsystem is not None:
            parts.append(f" subsystem {sanitise(group.subsystem)}.")
        if group.pattern is not None:
            parts.append(f" matched pattern {sanitise(group.pattern)}.")
        if group.frame_index is not None:
            parts.append(f" matched frame {sanitise(group.frames[group.frame_index])}.")
        if group.reason is not None:
            parts.append(f" reason {sanitise(group.reason)}.")
        parts.append(f" {_sampling_sentence(len(exemplars), group.thread_count)}")
        lines.append("".join(parts))

    dropped = bundle.analysis.total_signatures - len(selected)
    if dropped > 0:
        lines.append(
            f"{dropped:,} further signatures not shown "
            f"(of {bundle.analysis.total_signatures:,} total signatures)."
        )
    return lines


# D-10/D-11: the single sentence emitted whenever the multi-dump progression
# layer is suppressed. No delta figure is emitted anywhere else in the block
# alongside this line, in either triggering case: a real figure carried in a
# wrong or absent order is indistinguishable from a correct one to citation
# validation, so the whole layer is withheld rather than guessed at. Worded to
# name both possible reasons (an unverified order, or too few dumps to
# compare) so it stays truthful regardless of which one applies.
_SUPPRESSION_STATEMENT = (
    "Signature-population progression across dumps was not reported for "
    "this case: either the dump order could not be verified, or fewer "
    "than two dumps were available, so no population-change figure "
    "appears anywhere in this block."
)


def _progression_lines(
    bundle: EustackBundle,
    per_dump_sig_ids: list[dict[tuple[str, ...], list[str]]],
    ids: set[str],
) -> list[str]:
    """The multi-dump progression section (D-09/D-10/D-11).

    Suppressed entirely — no delta figure anywhere — whenever the resolved
    order basis is ``ORDER_BASIS_FILENAME`` (the unverified sorted-filename
    fallback) or fewer than two dumps are present. The basis is read
    directly off ``bundle.progression.order_basis``, never re-derived: the
    ordering decision was already made once by ``resolve_dump_order``.
    ``bundle.progression.ordering_flags`` (only ever non-empty in the
    unverified case) is carried through as graded lines so the structural
    fact and its severity reach the model, with no direction-of-travel claim
    attached. ``bundle.progression.scope_note`` is emitted verbatim in EVERY
    branch so the population-level-only caveat can never be omitted.
    """
    lines = [bundle.progression.scope_note]

    unverified = (
        bundle.progression.order_basis == ORDER_BASIS_FILENAME
        or len(bundle.progression.dumps) < 2
    )
    if unverified:
        lines.append(_SUPPRESSION_STATEMENT)
        for flag in bundle.progression.ordering_flags:
            lines.append(
                f"eu-stack dump-ordering flag ({sanitise(flag.severity)}) "
                f"{sanitise(flag.dimension)}: {sanitise(flag.message)}"
            )
        return lines

    # Verified branch (D-09): the resolved dump sequence, then capped,
    # cited per-signature population deltas for CHANGED signatures only —
    # never re-sorted, sliced from bundle.progression.signatures' own rank
    # order (-abs(overall_delta), -counts[-1], frames).
    for dump in bundle.progression.dumps:
        ts = sanitise(dump.ts) if dump.ts is not None else "no timestamp recorded"
        lines.append(
            f"eu-stack dump: {sanitise(dump.source_file)}, {ts} "
            f"(confidence {sanitise(dump.ts_confidence)}), "
            f"{dump.thread_count:,} threads."
        )

    changed = [
        sig
        for sig in bundle.progression.signatures
        if sig.overall_delta != 0 or any(d != 0 for d in sig.step_deltas)
    ]
    selected = changed[:_MAX_SIGNATURES]
    for sig in selected:
        exemplars = _union_exemplars([sig.frames], per_dump_sig_ids)
        if not exemplars:
            # No line without an [evt:] token — an uncited figure is forbidden.
            continue
        population = 0
        for sig_ids in reversed(per_dump_sig_ids):
            if sig.frames in sig_ids:
                population = len(sig_ids[sig.frames])
                break
        prefix = _cite_prefix(exemplars, ids)
        step_deltas = ", ".join(f"{d:+,}" for d in sig.step_deltas)
        parts = [
            f"{prefix} eu-stack signature population change: role "
            f"{sanitise(sig.role)}."
        ]
        if sig.subsystem is not None:
            parts.append(f" subsystem {sanitise(sig.subsystem)}.")
        parts.append(
            f" step deltas {step_deltas}; overall change "
            f"{sig.overall_delta:+,} threads."
        )
        parts.append(f" {_sampling_sentence(len(exemplars), population)}")
        lines.append("".join(parts))

    dropped = len(changed) - len(selected)
    if dropped > 0:
        lines.append(
            f"{dropped:,} further changed signatures not shown "
            f"(of {len(changed):,} changed signatures)."
        )
    return lines


def render_eustack_facts(
    bundle: EustackBundle, events: list[Event]
) -> tuple[str, set[str]]:
    """Render the eu-stack fact block and the set of ids it makes citable.

    Returns ``("", set())`` when ``bundle.analysis.total_threads == 0`` — the
    true absence of ingested eu-stack data (residue-free strip). A healthy,
    zero-flag capture still renders: emptiness is never gated on
    ``bundle.saturation.flags``. Each id in the returned set corresponds to an
    ``[evt:<id>]`` token actually printed in the block — nothing more (D-05).
    """
    if bundle.analysis.total_threads == 0:
        return "", set()

    ids: set[str] = set()
    lines: list[str] = []

    per_dump_sig_ids = [
        _signature_event_ids(dump_events)
        for dump_events in _events_by_dump_in_order(events, bundle.progression.dumps)
    ]

    signatures_by_role: dict[str, list[tuple[str, ...]]] = {}
    for group in bundle.analysis.signatures:
        signatures_by_role.setdefault(group.role, []).append(group.frames)

    # Iterate threads_by_role in its own key order — the dict is built
    # zero-filled in a fixed role order by analyse_eustack, so this needs no
    # import of any private role tuple and is deterministic.
    for role, threads in bundle.analysis.threads_by_role.items():
        if threads == 0:
            continue
        frame_tuples = signatures_by_role.get(role, [])
        exemplars = _union_exemplars(frame_tuples, per_dump_sig_ids)
        if not exemplars:
            # A line with no [evt:] token would be an uncited figure, which
            # the D-05 contract forbids.
            continue
        prefix = _cite_prefix(exemplars, ids)
        signature_count = bundle.analysis.signatures_by_role[role]
        lines.append(
            f"{prefix} eu-stack {sanitise(role)} threads: {threads:,} of "
            f"{bundle.analysis.total_threads:,} total threads across "
            f"{signature_count:,} signatures. "
            f"{_sampling_sentence(len(exemplars), threads)}"
        )

    pool_lines, pool_exemplars = _pool_lines(bundle, per_dump_sig_ids, ids)
    lines.extend(pool_lines)

    lock_lines, lock_site_exemplars = _lock_site_lines(bundle, per_dump_sig_ids, ids)
    lines.extend(lock_lines)

    lines.extend(_dependency_lines(bundle, per_dump_sig_ids, ids))

    lines.extend(
        _flag_lines(bundle, per_dump_sig_ids, pool_exemplars, lock_site_exemplars, ids)
    )

    lines.extend(_signature_listing_lines(bundle, per_dump_sig_ids, ids))

    lines.extend(_progression_lines(bundle, per_dump_sig_ids, ids))

    return _load_eustack_fragment().replace(_EUSTACK_LINES_SLOT, "\n".join(lines)), ids


__all__ = ["render_eustack_facts"]
