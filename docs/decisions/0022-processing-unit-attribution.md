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

The frame list, the nine queue names and their index pairing were verified byte-for-byte against the
shipped `MicroStrategy_Support_Util.dll` v1.25, not transcribed on trust; the test
`test_pu_rules_reproduce_the_utilitys_table_verbatim` pins all three. That check found one
transcription error before it shipped (`Delivery(NCSPU)` had acquired a space), which is exactly the
class of drift that would leave an engineer comparing two reports side by side wondering whether two
spellings meant one queue.

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

### Divergence 4: the reported thread id is the kernel thread, not the debugger's counter

The utility's gdb/Linux header regex is `Thread (\d+) \(Thread (\w+)`, whose group 1 is gdb's own
**sequential** thread number and whose group 2 is the pthread handle. The LWP is not captured at all.
Sift reads the LWP instead (`Thread \d+ \(.*?LWP (\d+)\)`), falling back to the sequential number
only when gdb omits the LWP, as it does for a single-threaded target.

The LWP is the kernel thread id: it is what appears in `/proc`, in `top -H`, in a DSSErrors log line,
and in a second capture of the same process. gdb's counter is an artefact of one debugging session
and correlates with nothing outside it. Since the whole value of a thread id here is cross-referencing
it against other diagnostics, the counter is the wrong number to print.

The consequence is worth stating because it is visible: the same gdb dump yields different thread ids
in the two tools. `test_grammar_detection_and_thread_ids` pins both the LWP preference and the
fallback.

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

### The axis is gated, not merely tested

`eustack_detection_rate` scores an eu-stack golden case by *figure reproduction*: the case passes
when `analyse_eustack_bundle` reproduces every figure its `truth.yaml` declares. A new axis that no
truth file declares is therefore invisible to the gate — the metric would keep reading 1.00 while
attribution silently regressed. Adding the analysis without extending the truth schema would have
shipped it ungated.

`ExpectEustack` gains `processing_units` (a per-queue role split) and an optional
`processing_unit_names` (the complete attributed set). The split rather than a bare total is
load-bearing: on `eustack-hang-pool-warehouse`, 25 Query Engine threads waiting on the warehouse and
25 waiting at a lock are the same total and different incidents needing different fixes, so a
total-only expectation would score both identically. All three shipped eu-stack cases declare
measured figures, and the hang case's cosmetic-mutation twin reproduces them independently.

Both fields default to empty, so a truth file that declines to pin the axis keeps passing rather
than being retro-fitted with figures nobody measured. `processing_unit_names` defaults to `None`
rather than `[]` for the same reason in the other direction: an empty list would assert *no queues*,
which would make adding a `[[pu]]` row retroactively fail every case.

### Detection must accept exactly what parsing reads

Probing degenerate inputs found the sniff table compiling only `DumpGrammar.header` and not
`header_fallback`, so a gdb dump of a single-threaded target (`Thread 1 (process 4242):`, no LWP)
parsed correctly under a forced adapter override and fell through to `genericlog` without one.

That asymmetry is the worst failure mode available in this area, which is why it is recorded rather
than quietly fixed: the file still ingests, still reports full parse coverage, and yields zero
threads, so the operator sees a *missing* analysis rather than an error. The invariant is that
detection and parsing recognise the same set of files, and it is pinned by a test that asserts the
parser really does read what the sniff accepts, on every shape a grammar can match.

### The shipped nine are a snapshot, and there is a supported way off it

The nine queues in `eustack_roles.toml` are the utility's **compiled-in** table, which its
own specification records as dead in v1.25: constructed at static-init, never read at runtime.
The live mapping is the `taskmap` file fetched from the corporate share and cached under
`%ProgramData%\MSTRSuppUtil\taskmap`, and it is expected to outgrow the built-in list — the
`PUMap contains additional PUs that this version of the plugin cannot support` warning fires
exactly when it has.

So freezing nine rows recovered from a 2022 binary would give Sift a mapping with a shelf
life and no supported way to renew it. `sift taskmap` (`pipeline/taskmap.py`) converts a
taskmap into `[[pu]]` rows: an engineer with a current one — every MSTRSuppUtil install has
a local cache — regenerates the rows rather than hand-transcribing them, which is exactly
how `Delivery(NCSPU)` acquired a space it does not have.

The importer reproduces the utility's grammar but not two of its bugs, both recorded because
each would corrupt data rather than merely differ:

- **Header truncation.** The utility takes `substr(1, len-2)`, stripping the leading `:` *and
  one trailing character* — the CR of a CRLF file. On a header with no closing colon, which
  its own grammar permits, that silently renames the queue (`Cube Publication` becomes
  `Cube Publicatio`). A renamed queue is worse than a missing one: threads are attributed
  under a name that matches nothing an engineer can look up. The importer strips the `:`
  delimiter when present and handles line endings properly, so CRLF and LF agree.
- **The ten-entry cap.** Not reproduced, per divergence 2.

Every row is imported with `match = "contains"`, reproducing the utility's substring `Lookup`;
an `exact` import would silently stop matching stacks the utility matches. Output is a
fragment carrying no `[meta]`, so pasting it over a rules file fails loudly at load rather
than producing a file with no role rules, and unclassifiable lines are reported with their
line numbers rather than dropped.

`test_converted_taskmap_loads_and_attributes_correctly` closes the loop: a converted taskmap
is combined with the shipped role rules, loaded, and used to attribute threads — including to
a queue the 2022 table has never heard of. Without that round trip, the command would be a
text generator whose output happens to look plausible.

### Windows-sourced artefacts must survive their encoding

Both artefacts this axis depends on come from Windows tooling: the taskmap is cached and
edited under `%ProgramData%`, and thread dumps are routinely collected, zipped and mailed
through the same support workflow. Probing real encodings rather than assuming UTF-8 found
three failures, two of which corrupted silently:

- **A UTF-8 BOM in the taskmap.** It lands on the first line — whichever kind that is.
  Ahead of `LUT:` it loses the revision without a word; ahead of the first `:PU:` header it
  drops that queue, and on a header-first file (no `LUT:` line at all) drops the entire
  import, so the command reports "is this a taskmap file?" about a file that plainly is one.
- **A UTF-8 BOM in a thread dump.** The same first-line position defeats every anchored
  header pattern, so the dump sniffs 0.0, falls through to `genericlog`, and reports *full
  parse coverage with zero threads* — the same silently-missing-analysis failure class as
  the sniff/parse asymmetry above. This predates the processing-unit axis but blocks it on a
  realistic artefact, so it is fixed here rather than noted.
- **UTF-16.** Decoded as UTF-8 it becomes NUL-riddled mojibake parsing to zero entries.
  That at least fails loudly, but "is this a taskmap file?" points at the wrong problem, so
  the BOM is detected and the encoding named with a conversion command.

The adapter strips the BOM **after** the byte accounting, never before: `event_id` is
`sha256(source_file, byte_offset)`, so stripping earlier would shift every offset in the
file and silently break re-ingestion idempotency. That is `genericlog`'s own Pitfall 7 rule,
applied here; its `_detect_encoding` already solved this properly for plain logs, which is
why the eu-stack adapter's simpler UTF-8 assumption stood out as an oversight rather than a
decision.

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
