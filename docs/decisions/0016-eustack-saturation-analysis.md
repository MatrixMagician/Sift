# ADR 0016: eu-stack saturation & contention analysis — module placement, flag record, calibration and the D-09 gate

**Status:** Accepted (implemented in Phase 16 / v1.3)
**Date:** 2026-07-25
**Answers:** How does a new aggregation layer over Phase 15's classified-thread model turn `EustackAnalysis`
into per-pool occupancy, ownership-blind lock convergence, external-wait concentration and graded
composition flags — and what evidence backs the shipped thresholds? Cross-refs REQUIREMENTS.md
EUS-03/EUS-04/EUS-05/EUS-06, ADR 0015 (the classifier this phase consumes read-only), ADR 0013 (the
qualified-name anchoring precedent D-04's `::` test follows), and
`.planning/phases/16-saturation-contention-signature-collapse/16-01-PLAN.md` §"Settled design decisions"
(S-1 through S-6), `16-02-PLAN.md` §S-7, and `16-04-PLAN.md` §S-8.

This records decisions settled during Phase 16 planning and execution; it does not re-argue ADR 0015's
Phase 15 decisions, which this phase builds on unchanged.

## Context

Phase 15 delivered `EustackAnalysis` — every eu-stack thread classified into one of five roles, collapsed
to distinct stack signatures, ranked by thread count. Phase 16 adds nothing to that classification; it is
a pure aggregation layer that consumes `EustackAnalysis` read-only and answers four questions research and
CONTEXT.md left open: which pool is saturated (EUS-03), where are threads converging while waiting on a
lock (EUS-04, always ownership-blind — eu-stack carries no monitor-ownership edges), which external
dependency is concentrating waits (EUS-05), and how does a curator know a shipped default is not
mis-calibrated against a fixture rather than a server (the D-09 verification gate underlying all three
graded flags, Success Criterion 5). EUS-06 (ranked signature collapse) was already satisfied by Phase 15's
`EustackAnalysis.signatures`; Phase 16 reads it directly and adds no field.

## Decision

### S-1 — Module placement: extend `src/sift/pipeline/eustack.py` in place

Rejected: a sibling `eustack_saturation.py`. Two reasons, one of them decisive. First, the precedent:
`mcm.py` and `perfmon.py` each keep their whole domain — detection, grouping and flags — in one file;
`eustack.py` growing from 373 to roughly 600 lines stays well inside that precedent, and a sibling module
has no analogue anywhere in this codebase. Second, and more important: the shipped
`test_no_ownership_attributed_lock_language_in_shipped_surface` (D-05's mechanical guard) reads
`eustack.py`'s full source at runtime and asserts the forbidden term is absent. Extending in place puts
every line Phase 16 adds under that guard with zero test changes. A sibling module would need a second,
hand-added `Path(...)` read inside the same test — a second edit site for a security-relevant invariant,
which is exactly the drift ADR 0013 and this codebase's "shared, not copied" convention exist to prevent.
A missed second edit site would mean a future ownership-attributing string in the sibling module ships
silently unguarded.

### S-2 — `mcm._grade` reuse: import it as-is, do not promote it

`from sift.pipeline.mcm import _grade` with a `# pyright: ignore[reportPrivateUsage]` marker and an inline
comment, following the exact convention already established for `_condense_symbol`/`iter_frames` at the
top of `eustack.py`. Promoting `_grade` to a shared module would edit `mcm.py`'s shipped, tested surface
for zero behavioural gain. Verified safe: `mcm.py` imports nothing from `sift.pipeline`, so the
`eustack.py -> mcm.py` import introduces no cycle, and `tests/test_mcm.py` stays green untouched.

### S-3 — One `SaturationFlag` record shared by all three flag families

`mcm.DiagnosticFlag` is deliberately NOT reused. Its `value_pct` field is locked as a ratio
`part / whole * 100` — documented verbatim as "ALWAYS a ratio ... never an absolute" (the milestone
machine-independence invariant). Two of the three Phase 16 flags (`unclassified_thread_pct`,
`no_resolvable_frame_pct`) are true ratios and would fit; the third (`lock_convergence_count`) is a raw
thread count and does not — forcing it into `value_pct` would violate that documented contract.
`perfmon.py` hit the identical mismatch for its own hazards and resolved it by minting `PerfmonHazard`
rather than bending `DiagnosticFlag`. `SaturationFlag` follows that precedent, but goes one step further:
rather than minting a second sibling record for the count flag alongside `DiagnosticFlag` for the two
ratios, ONE record type serves all three families. Two reasons. First, Success Criterion 5 requires every
flag to print its raw value beside the configured threshold, and `DiagnosticFlag` carries no threshold
fields — a renderer would have to re-read config to satisfy that criterion for the two ratio flags. Second,
a `tuple[DiagnosticFlag | SaturationFlag, ...]` return type would force every downstream consumer (Phase
17's report, Phase 18's fact injection) to type-narrow a union for no benefit. `SaturationFlag` deliberately
carries no `event_ids`: `SignatureGroup` has no per-thread event-id concept the way an MCM denial or
perfmon sample does, and resolving an aggregate figure back to a citable event set is Phase 18's open
design question (STATE.md Blockers). The omission is a decision, documented in the model's own docstring,
not an oversight.

### S-4 — Default cut-points and their honest calibration status

| Config key | warn | critical | Reference-capture value | Margin to warn |
|---|---|---|---|---|
| `unclassified_thread_pct` | 5.0 | 15.0 | 52 / 3,902 = **1.33%** | 3.8x |
| `no_resolvable_frame_pct` | 5.0 | 15.0 | subset of those 52, so **<= 1.33%**; measured **0.0%** on the committed derivative | >= 3.8x |
| `lock_convergence_count` | 5.0 | 20.0 | `__lll_lock_wait` matches **zero** times on the healthy capture, so **zero sites** | n/a — no flag is emitted at all |

Every default leaves the healthy reference capture graded `info`, satisfying D-09 with margin. The honest
limit of that evidence: the two ratio pairs rest on ONE real capture (a single data point), and the count
pair has NO calibration data at all — no real hung-server capture exists anywhere in this project's
possession, so `lock_convergence_count`'s numbers are round, conservative placeholders exercised only by
the D-11 hand-authored synthetic fixture, never by a real hang. Both facts are recorded verbatim in
`EustackThresholdsConfig`'s own docstring so a future reader does not mistake round numbers for measured
evidence.

### S-5 — Both ratio flags use the thread-weighted denominator

`unclassified_thread_pct` and `no_resolvable_frame_pct` both divide by `EustackAnalysis.total_threads`,
never by a signature count. This is load-bearing, not cosmetic: on the reference capture the unclassified
share is 1.33% thread-weighted but 43.01% signature-weighted — the two figures differ by more than an
order of magnitude. A long tail of one-thread signatures is a curation backlog (each one costs a rule to
fix but touches at most a handful of threads), not an operational signal an on-call engineer needs raised
as a flag. D-09 requires the healthy capture to read zero flags above `info`; grading on the
signature-weighted figure would fail that gate outright (43.01% is nowhere near `info` against any
sane threshold), which would force either a nonsensical threshold or abandoning the gate. The
signature-weighted figure is still *reported* — Phase 15 already emits the full, uncapped unclassified
list per D-15 — it simply never drives a flag.

### S-6 — Flags are emitted at every severity, including `info`

`analyse_saturation()` mirrors `mcm.compute_flags`' discipline: every flag it computes is appended
regardless of grade. A flag suppressed at `info` would never print its healthy value, contradicting
Success Criterion 5's "every graded flag prints its raw computed value beside its configured threshold."
"The healthy reference capture raises zero flags" (D-09) therefore means precisely **zero flags graded
`warn` or `critical`**, never "zero flags exist." The one exception: a ratio flag whose denominator is
zero (an analysis with no thread events at all) is not emitted — mirroring `compute_flags`' own
guard-before-dividing discipline — because a missing signal must never present as a fabricated `0.0%`.

### S-7 — The ownership-blind guard is extended over EMITTED OUTPUT, not source text

D-05 prohibits three terms — the milestone's own permanently-forbidden word plus "owner" and "holder" —
from the output vocabulary. The shipped
`test_no_ownership_attributed_lock_language_in_shipped_surface` greps `eustack.py`'s whole source for the
one term REQUIREMENTS.md names by name, and because S-1 keeps Phase 16 inside `eustack.py`, that grep
already covers every line this phase adds with zero changes.

It could not simply be widened to all three terms over source text: `src/sift/rules/eustack_roles.toml`
already contains the word "holder" in a prose comment explaining the permanent non-goal ("contention can be
observed but never attributed to a ..."), which is documentation describing what the classifier does NOT
claim, not output the classifier emits. Rewriting a shipped Phase 15 comment to satisfy a Phase 16 test
would be the tail wagging the dog. Settled: the existing whole-source grep is kept exactly as shipped, and
a SECOND assertion was added to that same test, checking all three terms — word-boundary matched,
case-insensitive — against strings the code actually EMITS at runtime: `LOCK_FINDING_NOTE`,
`UNKNOWN_LOCK_SITE`, every `LockSite.site`, and every `SaturationFlag.message`, produced by running both
the committed derivative fixture and a synthetic lock scenario through `analyse_saturation()`. A behaviour
assertion over real emitted strings is strictly stronger than a source grep, and it never touches Phase
15's shipped rules file. Word-boundary matching is required so an innocuous word such as "placeholder"
cannot false-positive on the substring "holder".

### S-8 — The D-09 gate cannot run on the committed derivative fixture; split it across two tests

Measured during 16-04 planning by running the shipped analyser over
`tests/fixtures/eustack/reference_capture_derivative.txt`:

| Figure | Committed derivative | Real reference capture | Ratio |
|---|---|---|---|
| total threads | 105 | 3,902 | — |
| unclassified threads | 40 | 52 | — |
| **unclassified THREAD share** | **38.10%** | **1.33%** | **28x inflated** |
| no-resolvable-frame threads | 0 (0.00%) | subset of the 52 | — |
| `blocked-on-lock` signatures | 0 | 0 | — |

The cause is structural, not a fixture defect: the derivative preserves all 93 signatures but caps thread
counts at 1 per signature (5 for the three highest-population ones). Forty of the 93 signatures are
unclassified, and the three capped signatures are all classified — so capping deflates the classified
population by roughly 3,000 threads while leaving the unclassified population nearly intact. The fixture
is faithful to signature composition and deliberately unfaithful to thread weight.

Two resolutions were considered and both rejected outright:

- **Raise `unclassified_thread_pct.warn` above 38.1%** so the fixture passes. Rejected: that ships a
  threshold calibrated against a cap policy rather than against a server, and it makes the flag nearly
  useless — rules drift would have to consume more than 40% of a real thread population before warning.
  A default chosen to make a test pass is exactly the failure mode D-09 exists to prevent.
- **Re-derive a thread-weight-faithful fixture.** Rejected: only three of the 93 raw per-signature thread
  counts (1,715 / 1,110 / 247) are recorded anywhere in the repository, so the remaining 90 cannot be
  reconstructed without the out-of-repo capture. A fixture built from invented weights would be exactly the
  "written to match the detector" artefact `.planning/research/PITFALLS.md` Pitfall 5 names.

**Settled: split the gate across two tests.** `test_reference_derivative_zero_flags` runs the committed
fixture and asserts zero warn-or-critical flags for the two families the fixture CAN faithfully exercise —
`no_resolvable_frame_pct` (genuinely 0.0% there) and `lock_convergence_count` (genuinely zero sites,
because Rule 6 matches a healthy capture zero times by design). It asserts the `unclassified_thread_pct`
flag's value equals 38.1 and states in its own docstring, with the arithmetic, that this figure is a
cap-policy artefact deliberately excluded from the gate. `test_measured_reference_composition_raises_
zero_flags` is the real D-09 gate: it constructs an `EustackAnalysis` directly at the real capture's
MEASURED composition (3,902 threads, 52 unclassified, zero no-resolvable-frame, zero `blocked-on-lock`) —
figures taken from ADR 0015 and 16-CONTEXT.md, not from the detector — and asserts every flag grades `info`
against the SHIPPED defaults (`EustackThresholdsConfig()` with no arguments). Constructing the input model
directly rather than synthesising 3,902 raw thread blocks is the right level: `analyse_saturation()` is the
unit under test and `EustackAnalysis` is its public, frozen input contract (D-10). The numbers come from
measured reality upstream of the code being tested, so this is not a fixture shaped to agree with its
detector.

## Known limitations

**The lock-site enclosing-frame denylist (D-04) is a four-entry allowlist-of-exclusions, not a complete
one.** It covers exactly `std::`, `boost::`, `__gnu_cxx::` and `abi::` — the two third-party namespaces
measured in the reference capture (`std::` 14 frames, `boost::` 10) plus two defensive entries for the same
libstdc++/libgcc family. A C++ runtime namespace outside those four — one not present in this project's
one reference capture — would still be reported as a lock site rather than skipped. This is a known,
accepted imprecision recorded openly (following ADR 0015's own precedent of disclosing rather than silently
fixing or silently accepting a limitation), not a bug: the denylist is deliberately four entries rather
than an allowlist of the roughly 110 MicroStrategy namespaces observed, which would grow with every build.

**No per-pool occupancy flag ships in this phase.** EUSV2-03 (graded saturation percentages) is
deliberately deferred: no authoritative source exists for "N% busy = warning," and inventing one would be
exactly the unfounded threshold this milestone's own composition-based approach exists to avoid. Occupancy
is reported as a raw figure per pool; nothing about it is graded.

## Consequences

**Positive.** All four Phase 16 requirements (EUS-03 through EUS-06) close at the library level with zero
new dependencies, zero LLM calls (D-12), and the D-09 gate now runs the shipped defaults against the real
capture's measured composition rather than a fixture whose cap policy would otherwise silently determine
what "healthy" means. Every graded flag prints its raw value beside its threshold (Success Criterion 5),
proven across all three families independently of `analyse_saturation()`'s own severity computation. The
ownership-blind guard covers both the shipped source and everything the code actually emits.

**Negative / accepted.** The lock-site denylist and the lock-convergence thresholds both rest on a single
reference capture or no calibration data at all — honestly disclosed above rather than presented as
measured. The derivative fixture's `unclassified_thread_pct` flag is untestable in CI at its true value;
this is disclosed in the test itself rather than worked around with an invented number.

## Alternatives considered

Documented inline above per decision (a sibling `eustack_saturation.py` module for S-1; promoting `_grade`
to a shared module for S-2; a `DiagnosticFlag`/`SaturationFlag` union or reusing `DiagnosticFlag` for the
two ratios for S-3; a signature-weighted denominator for S-5; suppressing `info`-graded flags for S-6;
widening the source grep to all three D-05 terms for S-7; raising the shipped default or re-deriving a
thread-weight-faithful fixture for S-8). None are repeated here to keep this ADR the length of its
neighbours; see the "Decision" section above for each alternative and its rejection reason.
