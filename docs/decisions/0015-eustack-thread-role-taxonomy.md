# ADR 0015: eu-stack thread-role taxonomy — matching semantics, normalisation and residual policy

**Status:** Accepted (implemented in Phase 15 / v1.3)
**Date:** 2026-07-25
**Answers:** How does a curated, versioned rules file turn one eu-stack thread's raw call stack into a
deterministic role, and what contract does that matching engine make with the curator who edits the
file? Cross-refs REQUIREMENTS.md EUS-01/EUS-02, the "Decisions folded into these requirements" table,
the "Out of Scope" table's permanent lock-ownership non-goal, and
`.planning/phases/15-thread-role-taxonomy-rules-file/15-CONTEXT.md` D-01 through D-16.

This records decisions already made during Phase 15 scoping and research; it does not re-argue them.

## Context

An eu-stack thread dump captures one call stack per thread, with no scheduler state, no
`/proc/<tid>/stat`, and no monitor-ownership edges. The milestone's own falsified mechanism —
"identical stack after 60 s = stuck thread" — flags 98.9% of threads on a healthy server, because an
idle IServer parks thousands of pool workers in `pthread_cond_timedwait` by design. Composition, not
motion, is the signal: 3,902 threads on the reference capture collapse to 93 distinct stack
signatures, and each signature's role is recoverable from which application frame it passes through,
not from comparing two dumps.

Phase 15 built the classifier (`src/sift/pipeline/eustack.py`) and its curated rules file
(`src/sift/rules/eustack_roles.toml`) against this constraint. The decisions below are the contract
between the classifier and the rules-file curator — what changing a row in the TOML file is allowed
to do, and what it can never silently do.

## Decision

### Rule-major, first-match-wins in file order (D-01)

For each rule in file order, every frame of a signature is scanned; the first rule matching anywhere
in the stack wins. Row position in `eustack_roles.toml` **is** the precedence knob — there is no
`priority` field.

This is the only loop order under which editing the file predictably reorders outcomes (success
criterion 2). Under it, a curator can place the job-queue rule above a libc-wait rule and have the
1,715-thread `MSIQTask::GetNextPreferredJob` population read `idle-parked` correctly, at frame index 3,
rather than blocked at frame index 0.

Rejected alternatives:

- **Frame-major, leaf-outward.** Scanning frame `#0` against every rule before frame `#1` makes stack
  depth the precedence, not file order — `pthread_cond_timedwait` at `#0` would win before the
  application frame at `#3`–`#19` is ever reached, and no amount of file editing could change that.
- **Deepest-application-frame-first.** Requires an `is_app_frame()` predicate — a second, implicit
  taxonomy hardcoded in Python and invisible in the editable rules file, exactly the kind of
  Python-coupling EUS-01 exists to avoid.

**Reversibility: costly.** Phases 16–19 build directly on this loop order (the `(role, subsystem)`
grouping, the signature-collapse ranking, the ranking-exclusion decision); changing it later silently
reclassifies every population and invalidates any golden fixture built against the current order.

### Rule-major matching surfaced a shared-ancestor ordering trap (empirical finding)

Because matching tests "does this pattern appear anywhere in the stack," not "is this the frame
nearest the wait primitive," a rule keyed on a task-dispatch or pool-loop frame can be a shared
ancestor of BOTH a task's idle-wait call chain and its active-work call chain. The shipped example:
`MSIEvaluationTask::Run` is the milestone's own cited self-labelling frame for the 1,110-thread idle
evaluation population, but it is *also* an ancestor frame in genuinely busy cube-generation call
chains — five distinct signatures in the reference capture contain it alongside a `running`-rule frame,
not one.

The review rule this generalises to: any rule keyed on a task-dispatch or pool-loop frame must sit
**after** the rules identifying that same task's active-work frames, not merely after generic
wait-primitive rules. In the shipped 24-rule set, the five `running` rules (D-02's locked frame list)
are placed first for exactly this reason — rule 1 (`_shi_allocBlock`) matches a busy signature and
wins before the `MSIEvaluationTask::Run` idle rule is ever tested. Reversing that order reclassifies
44% of the milestone's own headline population as idle. A comment above the evaluation rule in
`eustack_roles.toml` states this dependency by name, and
`tests/test_eustack_rules.py::test_running_rule_precedes_evaluation_ancestor_rule` pins both
directions in CI.

One disclosed residual: a single-thread signature (`pthread_rwlock_rdlock` → `IsFeatureEnabled` → deep
cube-join chain → `MSIEvaluationTask::Run`) matches none of D-02's five locked `running` patterns and
does not reach `__lll_lock_wait`'s contended slow path, so it falls through to the evaluation rule and
reads `idle-parked`. D-02's running-rule list is locked; this plan does not expand it to chase one
thread. This is a known one-thread inaccuracy, not a population-level error, and is recorded here
rather than silently fixed or silently accepted.

### Symbol normalisation splits on the FIRST `@`, not `@@` (D-05, as refined)

`normalise(symbol)` strips a version suffix by splitting on the first `@` and keeping the head, then
strips any ` - <lib> <source>:<line>` tail. Template argument lists are KEPT.

CONTEXT.md's D-05 was worded around `@@GLIBC_x.y.z`, but the reference capture also carries three
symbols with a SINGLE `@` before the version (`clock_nanosleep@GLIBC_2.2.5`,
`cnd_timedwait@GLIBC_2.28`, `pthread_rwlock_rdlock@GLIBC_2.2.5`) alongside the double-`@@` form
(`pthread_cond_timedwait@@GLIBC_2.3.2`, `pthread_cond_wait@@GLIBC_2.3.2`,
`__libc_start_main@@GLIBC_2.34`). A literal `@@`-only split would leave the single-`@` three
build-brittle — precisely the cross-build symbol drift D-05 exists to prevent. Measured on the
reference capture: 3,552 frames carry `@@GLIBC` suffixes across those 3 double-`@` symbols.

Signature counts measured under each normalisation variant: raw **93**, GLIBC-stripped **93**,
templates-stripped **88**, both **88**. Template argument lists are kept because stripping them
collapses the 93 signatures the roadmap cites down to 88 — a lossy transform this taxonomy does not
need, since template variance across builds is already handled by a `contains` rule on the pre-`<`
prefix (e.g. `MTimer::Timer<`).

### Match kinds are exact / prefix / contains, with `exact` the default (D-09)

Three match kinds, dispatched to `==` / `str.startswith` / `in`. Omitting `match` means `exact`.
Looseness is therefore never accidental — every `contains` in `eustack_roles.toml` is a word a curator
typed and a reviewer can `grep 'match = "contains"'` for.

This ties directly to ADR 0013's bare-substring collision (`"MCM"` colliding with a PDH counter path),
with an honestly stated difference in scale: ADR 0013's three-character marker was matched against
64 KB of arbitrary file content; a pattern here is matched against one symbol of tens of characters.
The risk is real but smaller — a curated `contains` pattern like `CDSSSubsetEngine::GenCube` cannot
plausibly collide the way a bare `"MCM"` did.

`fnmatch` is the documented escape hatch for glob-style matching, deliberately **not added now** — no
shipped rule needs it, and adding an unused match kind would be exactly the kind of speculative
flexibility this taxonomy avoids.

### `unclassified` is the sole residual and is illegal as a rule role (D-02, D-12)

`running` is a rule-matched role like `idle-parked`, `blocked-on-external` and `blocked-on-lock` — not
a fallback default. `unclassified` is the sole residual for a signature that matched no rule, and its
rate is the rules-drift signal a curator watches.

A residual `running` default was rejected: it would silently label every unrecognised stack as
working, which is exactly the guess EUS-02 forbids, and it would drive the unclassified count toward
zero, hiding the signal success criterion 3 exists to expose. The Pydantic loader enforces this
structurally — `role` in a `[[rule]]` table is a `Literal` of the four rule-assignable buckets, and
`"unclassified"` is rejected loudly at load if a curator tries to author it as a rule.

### `no resolvable frame` is a reported reason within `unclassified`, not a sixth role (D-07)

An unresolvable frame (`??` or a bare hex address) stays in the signature tuple — it is part of the
stack's identity, so two signatures differing only in what resolved must not collapse — but is never a
match candidate. When no rule matches a signature, the residual splits on whether the signature held
ANY resolvable frame: none resolvable reports `reason="no-resolvable-frame"` (a symbols-missing
problem); at least one resolvable frame that still matched nothing reports
`reason="matched-no-rule"` (a rules-drift problem). Both keep `role="unclassified"` — this is a reason
field within the one residual bucket, never a sixth role, so success criterion 1's five-bucket
partition still holds exactly.

### No containment guard on `[eustack] rules_path`

`rules_path` performs a local file read of a path the operator already has read access to — it is not
a network fetch, and nothing is written to it. This matches the shipped `--kb <dir>` precedent
(ADR 0009), which points anywhere the user chooses with no containment check. `tomllib` has no
tag/anchor/code-execution mechanism the way YAML's `!!python/object` does, so a malformed override can
only fail to parse or fail Pydantic validation — never execute attacker content.

Recorded here so the absence of a guard is a decision on the record, not an oversight: if a future
security review disagrees, the fix is a one-line existence check, not an architecture change.

### Deadlock detection is a permanent non-goal

eu-stack output carries no monitor-ownership edges — a thread's stack shows what it is waiting on, but
never who holds the lock it is waiting for. A wait-for graph cannot be constructed from this data at
all; this is a structural data limitation, not a missing feature to build toward. Every lock finding
Sift produces is therefore ownership-blind by construction, worded consistently with
REQUIREMENTS.md's own "Out of Scope" row, which states Sift must never emit that word.
`tests/test_eustack_rules.py::test_no_ownership_attributed_lock_language_in_shipped_surface` reads the
forbidden term from REQUIREMENTS.md at runtime and asserts it appears nowhere in the shipped rules
file or classifier module.

## Consequences

**Day-one coverage (measured, reference capture, dump A):** the shipped 24-rule set classifies
**3,850/3,902 threads (98.67%) and 53/93 signatures (56.99%)**. By role: `idle-parked` 3,651 threads /
33 signatures, `blocked-on-external` 194 threads / 15 signatures, `blocked-on-lock` 0 threads / 0
signatures (the reference capture is healthy — no lock contention observed), `running` 5 threads / 5
signatures, `unclassified` 52 threads / 40 signatures. The headline criterion-4 signature
(`MSIQTask::GetNextPreferredJob`, 1,715 threads) reads `idle-parked/job-queue` at frame index 3, not
blocked — the exact composition-blind false positive v1.3 exists to eliminate. The residual ships as
disclosed, by-design `unclassified`, not chased to zero; the coverage curve was measured to flatten
past 24 rules (each further rule buys roughly one more signature, at most 13 threads), so stopping here
and treating the remainder as a rules-drift signal is a deliberate stopping point, not an oversight.

**What a future curator must check when adding a rule:**

1. **The shared-ancestor ordering rule** — a new rule keyed on a task-dispatch or pool-loop frame must
   sit after any rule identifying that same task's active-work frames, or it risks silently
   reclassifying busy threads as idle. Review the file's header comment and this ADR's "shared-ancestor
   ordering trap" section before adding such a rule.
2. **The pattern must already be normalised** — no `@GLIBC_...`/`@@GLIBC_...` suffix, no
   ` - <lib> <src>:<line>` tail — or the loader rejects it loudly at load time, quoting the canonical
   form to use.
3. **Do not add a catch-all or generic ancestor-frame rule** (e.g. a bare `MSIThread::Run`) purely to
   raise the coverage number — `unclassified` is the sole residual and its rate is the signal a curator
   relies on; a catch-all destroys that signal.

**Positive.** Row position alone decides precedence, so success criterion 2 ("engineer edits the file
and sees threads change role") is satisfiable with no Python change. The strict Pydantic loader
(`extra="forbid"`, `Literal` role, non-empty and normalised-pattern validators, duplicate-rule
rejection) turns a typo into a load-time error rather than a silently dead or silently wrong rule.

**Negative / accepted.** `contains` matching against tens-of-characters symbols carries a smaller but
non-zero collision risk, mitigated by the `exact`-by-default discipline rather than eliminated. The
one disclosed single-thread mis-ordering case (feature-flag check under `MSIEvaluationTask::Run`)
remains `idle-parked` rather than `running`, accepted rather than fixed by expanding D-02's locked
list. No containment guard exists on `rules_path`, consistent with the `--kb` precedent but a
deliberate scope decision, not an audited-safe guarantee.

## Alternatives considered

Documented inline above per decision (frame-major leaf-outward and deepest-application-frame-first for
D-01; also-stripping-templates and no-normalisation for D-05; `contains`-as-default and
`exact`/`prefix`-only for D-09; `running`-as-residual-default for D-02; one-unresolved-frame-condemns-
the-whole-thread and dropping-unresolved-frames-entirely for D-07). None are repeated here to keep this
ADR the length of its neighbours; see the "Decision" section above for each alternative and its
rejection reason.
