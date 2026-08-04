# ADR 0022: processing-unit attribution — a second axis, adapted from the MicroStrategy Support Utility

**Status:** Accepted
**Date:** 2026-08-04
**Answers:** How does Sift decide which Intelligence Server work queue a thread is serving, and what
does it deliberately do differently from the reverse-engineered Notepad++ utility the concept came
from? Cross-refs ADR 0015 (thread-role taxonomy), ADR 0016 (saturation analysis), and the PU-mapping
specification recovered from `MicroStrategy_Support_Util.dll` v1.25.

## Context

ADR 0015 gave Sift one classification axis: a thread's **role** — `idle-parked`,
`blocked-on-external`, `blocked-on-lock`, `running`, `unclassified` — read from which application
frame its stack passes through. That axis answers *what is this thread doing*.

It does not answer *what is it doing it for*. On the v1.3 reference capture, 15 threads read
`blocked-on-external` and 45 read `idle-parked`; both figures are true of the whole server and
actionable for none of it. An engineer triaging a hang asks a narrower question: **is the Query
Engine wedged, or is it the Command PU?** Those are different incidents with different fixes, and
the role axis reports them identically.

The MicroStrategy Support Utility — a Notepad++ plugin used inside MicroStrategy support, version
1.25 (2022), reverse-engineered from the shipped DLL — already models exactly this concept. It calls
it a **PU** (processing unit): the work queue a thread belongs to. Its `TaskMap::Lookup` walks a
thread's stack text for a table of C++ symbol signatures and reports which queue matched, together
with a sub-task description. Its compiled-in table names nine real queues plus a
"Not Yet Implemented" sentinel.

The concept is sound and the frame list is genuinely valuable domain knowledge. The mechanism is
not reusable: the table is fetched from a corporate SMB share at runtime, and three of the matching
decisions are wrong in ways that are measurable against Sift's own reference capture.

## Decision

**Adopt the PU concept as a second, orthogonal axis. Re-implement the matching. Keep the frame
list.**

Processing-unit rules live in the same versioned `src/sift/rules/eustack_roles.toml` the role rules
live in, as `[[pu]]` rows, loaded and content-hashed by the same `load_rules`. `SignatureGroup`
gains a defaulted `pu: PuAttribution | None`; `SaturationAnalysis` gains `pu_health`, the
PU-crossed-with-role table. Both axes are computed from the same signature, independently, and
neither can override the other.

### Divergence 1: deepest-frame-wins, not lowest-PU-index-wins

The utility returns the **lowest PU index** appearing anywhere in the block: it walks its
`std::map<int, ...>` in ascending key order and returns on the first signature that appears as a
substring. Its own worked example concedes the consequence — a thread containing both
`MSIDSSCommand::Process` (PU 0) and `CDSSQueryEngineServer` (PU 2) is attributed to PU 0, noting
"PU 0 wins even though `CDSSQueryEngineServer` is the more specific frame. Ordering is by PU index,
not by stack depth."

Sift takes the **deepest** matching frame, ties broken by `[[pu]]` file order.

Measured, not argued: three signatures in the committed reference capture carry both
`CDSSSQLEngineServer` (PU 1, at frames #2, #8 and #11) and `MSIEvaluationTask::Run` (PU 8, at frames
#25, #18 and #33). The utility calls all three **SQL Engine**. Reading the full stack shows what they
are — `MSIEvaluationTask::Run` → `CDSSRWDataModel::ViewEvaluation` → `CDSSRWEvaluator::Run` →
`MCE::GenJoinedCube` → a cube-join chain → `CDSSSQLEngineServer::ResolveAllLevelHelper` — Evaluation
threads that called a SQL-engine helper deep in a cube join. Attributing them to the SQL Engine
points an engineer at the wrong subsystem.

Depth is sound because frames run leaf-first toward the thread entry point, so the deepest match is
the outermost dispatch frame, which is by construction the queue that owns the thread; everything
shallower is work that queue called into. Depth is also a property of the stack, so it stays sound
as rows are added. Index order is a property of the file, so it must be curated to stay sound — the
same trap ADR 0015 documents for `[[rule]]` ordering, which is why `[[pu]]` deliberately does **not**
inherit that ordering convention.

`test_deepest_frame_wins_over_lowest_pu_index` and
`test_deepest_frame_rule_holds_on_the_reference_capture` pin both directions; the latter recomputes
the three-overlap measurement rather than quoting it, and asserts the SQL frame really is the
shallower one, so it proves the utility's answer wrong rather than merely different.

**Reversibility: cheap.** Attribution is one function over a signature tuple. Nothing in the
grouping or rendering depends on which frame won, only on which queue it named.

### Divergence 2: `index` is provenance, never precedence, and never bounded

The utility's `index` is load-bearing three times over: it is the map key, the precedence order, and
an array position into a ten-entry `PUMap` whose bounds check renders anything above nine as
`Out of Bounds`. Its no-match sentinel is also 10, so "no rule matched" and "PU index out of range"
render identically — and its version-skew warning exists because a newer taskmap can silently exceed
an older plugin's array.

Sift carries `index` as **provenance only**: it lets a finding be traced back to the numbering an
engineer may already know from the utility. It is not a key, not precedence, not a position, and has
no upper bound. A model validator enforces that one name carries one index and one index carries one
name, so the trace stays meaningful, and `test_pu_index_is_provenance_and_never_precedence` proves
reversing the file changes no outcome.

An unattributed thread is `pu=None` and reports as its own explicit row, never sharing a bucket with
anything else. On a healthy server this is the correct answer for most infrastructure threads — 70 of
105 in the reference capture — which is a finding about the rules file's coverage, not a failure.

### Divergence 3: the mapping is a reviewed repo artefact, not a network fetch

The utility's taskmap lives at `\\supp-fs-was\...\taskmap`, is cached under `%ProgramData%`, and is
refreshed by comparing an `LUT:` revision counter over SMB, warning that "PU information may be
incorrect" when off-network. Sift's rules file is in the repository, reviewed in pull requests,
content-hashed into the report, and overridable via `[eustack] rules_path`. This follows directly
from the zero-network-egress invariant; it is recorded here because it also changes the failure mode
from *silently stale* to *visibly versioned*.

### Kept deliberately: substring matching over the whole stack

One property is adopted unchanged. A `[[pu]]` pattern hits as a substring of a frame, so
`CDSSSQLEngineServer` matches `CDSSSQLEngineServerImpl::Foo` too, and the whole stack is searched
rather than just the top frames. The utility's own note applies verbatim: this is what makes the
mapping work at all, because the PU-identifying frame sits deep while the top frames are generic
runtime and lock code. The safeguard is the same one ADR 0015 relies on — patterns must be
fully-qualified C++ symbols, in `normalise()` canonical form, enforced at load time.

## Consequences

### The cross-tabulation is the deliverable

`PuHealth` reports, per queue: total threads, threads waiting at a lock site, threads waiting on an
external dependency, idle, running, unclassified, and the lock sites its threads converge on. Rows
rank by **lock-blocked threads first**, then total — a queue with four thousand healthy idle workers
must not outrank one with twelve threads stuck at a lock, because this table exists to surface the
queue in trouble.

Lock sites per queue reuse `enclosing_application_frame` and `UNKNOWN_LOCK_SITE` from ADR 0016
rather than re-deriving them, so the per-queue and global lock tables can never name different sites
for the same threads (`test_pu_lock_sites_agree_with_the_global_lock_table`).

### One graded dimension, and one deliberately absent

`pu_lock_blocked_count` grades how many of one queue's threads wait at a lock site. It complements
ADR 0016's per-*site* `lock_convergence_count`: a queue whose threads spread thinly across four sites
trips no per-site threshold while the queue itself is wedged.

A per-queue **blocked-share** threshold was implemented, measured and removed. On the healthy
`eustack-healthy` eval case the Query Engine measures 100% blocked — three threads parked in
`CDSSQueryEngine::WaitUntilFinished`, waiting on the warehouse, which is a Query Engine doing its job
— so grading that share reported `critical` on a server with nothing wrong with it. Waiting on an
external dependency is a queue's normal working state and has no defensible zero point, exactly the
reasoning ADR 0016's D-07 used to refuse a per-pool occupancy flag. Waiting at a lock does have one:
nothing. The share is still reported in the table, ungraded.

This is recorded because the failure was caught by running the analyser against the healthy fixture,
not by review — and a future contributor proposing the same threshold should find the measurement
here rather than repeat it.

### The ownership prohibition extends unchanged

ADR 0015's permanent non-goal is a property of the data, not of an axis: neither eu-stack nor pstack
carries monitor-ownership edges. A queue is reported as having threads *waiting at* a site, never as
holding anything and never as blocked *by* another queue. `PU_FINDING_NOTE` carries this on the
analysis so a renderer cannot omit it, and the vocabulary gate runs over the processing-unit output
too.

### Multi-format support falls out of the same insight

The utility's stack-format menu is a table of *thread delimiter* + *thread-header regex* pairs, and
its specification states the consequence plainly: only where a thread block starts and how the
thread id is read are format-dependent; everything downstream operates on raw block text and is
identical across formats.

`adapters/threaddump.py` is that table as data. `DumpGrammar` covers eu-stack, Solaris `pstack` and
gdb/Linux `pstack`; adding AIX `dbx` or WinDBG is a new grammar and a registration, with no change to
the adapter, the classifier, the PU mapping or any renderer. Detection is per thread block, so a
concatenation of captures from hosts in different formats still parses.

One thing does not generalise: **argument stripping is per grammar**. eu-stack prints a demangled
type signature, identical for every thread in a function, and dropping it collapses the reference
capture from 93 signatures to 88 by merging genuine overloads — so it is kept. gdb prints argument
*values* and Solaris prints raw argument *words*, both of which differ per thread, so keeping them
would give every thread its own signature and defeat grouping entirely. That is the same failure the
utility documents as its own sharp edge, where hit-count dedup "is only meaningful for symbol-only
stack formats"; stripping arguments is what lets Sift group pstack captures at all.

Frame indices are **positions within the block**, not the numbers the dump prints, because Solaris
pstack prints no frame numbers at all and every existing consumer of `frame_index` was a position
already.

### Not adopted

The utility's `Is Locked` / `Is Idle` booleans are a flat substring scan over six lock frames and
three idle frames. Sift's rules file already covers this ground with more precision and an explicit
residual, so adopting them would add a second, coarser taxonomy answering the same question. Its
exact-text hit-count dedup is superseded by signature grouping, which is address-insensitive. Its
`LUT:` staleness flow, patched-library MD5 map and `MA_.xml` log parsing are outside this axis.
