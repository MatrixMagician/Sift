# Feature Research

**Domain:** Native-stack-dump hang/slowdown diagnosis (v1.3 EU-Stack capability) + whole-product feature landscape (v1.0 baseline, preserved below)
**Researched:** 2026-07-25 (v1.3 pass); 2026-07-16 (v1.0 baseline, preserved as an appendix)
**Confidence:** MEDIUM (cross-checked primary sources — man7.org, POSIX/IBM docs, Oracle jstack docs, HPCToolkit peer-reviewed paper — for load-bearing claims; LOW-confidence single-source blog claims are marked inline and excluded from anything prescriptive)

This file now leads with the **v1.3 EU-Stack Hang & Slowdown Diagnosis** research (the current
milestone). The original whole-product ecosystem research from the v1.0 milestone is preserved
verbatim in the Appendix — it's still accurate for the rest of Sift and still feeds general
roadmap decisions; it just isn't what this research pass was scoped to answer.

---

# Part A — v1.3: EU-Stack Hang & Slowdown Diagnosis

## Framing: what is and isn't inferable from this input

Sift's `eustack` input is TID + frame index + instruction address + demangled symbol, per thread,
per dump. It has **no lock-ownership edges** (`waiting to lock <addr>, held by <thread>` — the
datum JVM `jstack`/`!analyze` deadlock detection is built on), **no thread names**, **no per-thread
timestamps**, and (per the reference capture format) **no `/proc/<tid>/stat` state code** attached
per thread. Every technique below is filtered through that constraint. Where a mature tool's
technique needs data eu-stack doesn't have, that is stated explicitly rather than papered over —
per the milestone's quality gate, an unsound inference stated confidently is worse than an absent
one.

## 1. Thread-state taxonomies in practice

Mature tools converge on the same handful of buckets, reached by different routes:

- **async-profiler / JFR** (wall-clock mode) distinguishes exactly two states per sample —
  `STATE_RUNNABLE` and `STATE_SLEEPING` — determined by whether the JVM's own thread-state field
  says the thread is on-CPU/runnable or blocked/parked at sample time; CPU-mode samples carry no
  state distinction at all (`STATE_DEFAULT`). This is a **coarse binary**, not a rich taxonomy, and
  it's only possible because the JVM maintains an authoritative thread-state field Sift's native
  target does not have (confidence: MEDIUM — cross-checked GitHub issue #279 discussion + Baeldung
  guide).
- **Linux `/proc/<pid>/stat`** (`man7.org proc_pid_stat(5)`, cross-checked against the Ubuntu
  manpage) exposes the kernel's own state code: `R` running, `S` interruptible sleep, `D`
  uninterruptible sleep (classically I/O), `T`/`t` stopped/tracing, `Z` zombie. This is the
  **ground-truth OS state** and is orthogonal to which frame the thread is in — `S` covers
  virtually everything blocked in userspace (futex wait, cond wait, poll, select, read). **Sift's
  eu-stack input does not carry this code**; if a future capture pipeline collects
  `/proc/<pid>/task/<tid>/stat` alongside eu-stack, the `D` vs `S` distinction would be a genuinely
  new, orthogonal corroborating signal (D specifically suggests a stuck syscall, often disk/NFS)
  worth flagging as a documented gap, not something to fabricate from the stack alone. Confidence:
  HIGH for the code meanings (primary kernel docs, cross-checked).
- **`pstack` / `gdb thread apply all bt`** workflows (cross-checked against Red Hat's own KB
  article and the GDB manual) classify a thread purely by pattern-matching its top frames against a
  known list of blocking library calls (`pthread_cond_wait`, `pthread_mutex_lock`, `poll`, `select`,
  `recv`) vs. application code (implies on-CPU/running). GDB itself never labels a thread's OS
  state — that inference is entirely frame-pattern-based, exactly the technique the milestone
  scopes Sift to. Confidence: MEDIUM.
- **Windows DebugDiag / `!analyze` hang rules** (cross-checked against Sukesh's IIS blog + Tess
  Ferrandez's "Analyzing Debug Diag output") report threads blocked in a critical section
  (`RtlEnterCriticalSection`), waiting on a kernel handle (`WaitForSingleObject`/
  `NtWaitForSingleObject`), or genuinely running. Critically, DebugDiag's own "many threads at the
  same stack" heuristic is a documented **false-positive source** in exactly the shape this
  milestone measured — the tool flags it as a possible hint, never as a proven deadlock, precisely
  because it cannot see lock ownership either in the general case. Confidence: MEDIUM.
- **`jstack` deadlock detection** (Oracle's own tool docs, cross-checked) is the one technique that
  is **categorically inapplicable**: it works only because the JVM's monitor implementation records
  `waiting to lock Monitor@0x...(Object@0x...)`, held by `<thread>`, letting jstack build an
  explicit wait-for graph and run cycle detection. eu-stack has none of that. **Do not build
  anything that presents itself as "deadlock detection"** — Sift can at best report lock-*site*
  convergence (§3), never a proven cycle. Confidence: HIGH (primary Oracle docs).

### Concrete frame → inference table (the versioned-rules-file seed)

Every row states what the frame *is*, what can *soundly* be inferred, and where the inference
breaks. This is written for direct transcription into the hand-curated rules file — the enclosing
frames (not just the leaf) are load-bearing for every row.

| Leaf/near-leaf frame | What it structurally means | Sound inference | Where it breaks / unsound leap |
|---|---|---|---|
| `pthread_cond_wait` | Blocked indefinitely on a condition variable; associated mutex released while waiting. No self-wake. | Thread is not running, not holding the paired mutex, will not resume until externally signalled. | Cannot tell *which* condvar, whether the signaller still exists, or how long it's been waiting (no per-thread timestamp). The enclosing frame (e.g. `EventImpl::Wait`) — not the leaf — tells you whether this is a healthy idle-evaluator pattern or a stalled consumer; the leaf alone is ambiguous between both. |
| `pthread_cond_timedwait` | Same as above but with a wall-clock deadline — thread **will** wake on timeout regardless of signal, i.e. this is a poll loop, not an indefinite block. This is the single most common leaf in a healthy process (reference capture: 44%+28%+6%+3%+2%+1% of all threads sit here across six different pools). | Thread is bounded-blocked and self-recovering; presence alone is **not** evidence of a stall — this is the frame that falsifies "identical stack after N seconds = stuck." | Cannot distinguish "waiting for real work, correctly idle" from "waiting for work that will never arrive because upstream silently died" from the frame alone — that distinction needs the *enclosing* frame's role (idle-worker pool vs. something that should never be idle) plus, ideally, corroborating evidence (queue depth, external logs) Sift doesn't have. |
| `__select` / `poll` / `__poll` | Blocked in `select(2)`/`poll(2)`, typically on file descriptors — sockets, pipes. May be bounded (finite timeout arg) or unbounded (`-1`); eu-stack shows neither the fd list nor the timeout value. | Thread is I/O-blocked, not CPU-bound, not obviously holding an app-level lock. | Cannot assume network vs IPC vs bounded vs unbounded without the enclosing frame naming the subsystem (reference capture: `CrossProcessEventImpl::WaitOnPipe` under `__select` = local IPC, not network — the leaf alone would mislabel this as "possibly network"). |
| `epoll_wait` | Reactor/event-loop thread idling for I/O readiness (reference capture: `boost::asio::detail::scheduler::run`). | Thread is a reactor, currently idle, not doing per-request work. | Says nothing about backlog size on its own; one thread here is normal, many threads simultaneously here (beyond the expected reactor-thread count) is the only thing worth flagging, and even that needs a configured expectation of "how many reactors should exist," which Sift does not have a source for and should not guess. |
| `semtimedop` | Blocked on a System V semaphore with a timeout — the cross-process analogue of `cond_timedwait` (reference capture: `SharedMemoryImpl::WaitOnSemaphore`). | Bounded wait on cross-process signalling; self-recovering like `cond_timedwait`. | Cannot see the semaphore's current value or which process would post it — that state lives outside this one process's stack dump entirely. |
| `clock_nanosleep` | Thread deliberately sleeping a fixed duration — a backoff/poll loop, not blocked on any external event. | Guaranteed periodic self-wake; **never** classify this as "stuck." | Cannot infer the sleep duration or whether the loop is doing useful work between sleeps vs. busy-waiting on something else — needs the enclosing frame. |
| `pthread_rwlock_rdlock` | Thread wants a shared/read lock, has not yet returned from the acquire call. | A single thread caught here at all is mildly informative (the uncontended fast path is usually too fast to sample), but **weak on its own**. | **Unsound** to call this "contention" from one thread in one dump — could be an artefact of sampling timing. Becomes a much stronger (still probabilistic, not proven) signal only when **multiple threads** are simultaneously inside the **same named lock site** in the enclosing frames (reference capture: `MSynch::RWLock::ReadSmartLock`) — report as a convergence count with a confidence label, never as a fact about the lock's actual state. |
| `__lll_lock_wait` (glibc low-level-lock internals) | glibc's mutex/rwlock fast path is a userspace CAS; this specific function is **only reached on the contended slow path** that falls through to the kernel futex wait. | This is the **soundest single-leaf signal of genuine contention** in the whole taxonomy — its presence, by construction of glibc's implementation, cannot occur on an uncontended acquisition. | Still cannot say who holds the lock, for how long, or whether it will resolve — no ownership edge exists in eu-stack. Do not upgrade "contention observed at this site" into "root cause is this lock." |
| `futex` (raw syscall, e.g. via a bare `syscall`/`futex_wait` frame with no pthread wrapper visible) | The generic kernel primitive underlying pthread mutexes, cond vars, rwlocks, and semaphores. Least specific frame in the entire taxonomy — everything eventually funnels through it. | Thread is blocked in the kernel. | **Always unsound in isolation.** Classification must defer to the next frame up (`pthread_cond_wait` vs `pthread_mutex_lock` vs `sem_wait`, etc.); a bare `futex` leaf with no identifiable caller above it should be reported as its own low-confidence bucket, not force-mapped into `blocked-on-lock`. |

**Rule for the taxonomy file, generalised from the table:** the leaf frame narrows the *mechanism*
(timed vs untimed, syscall family), but the **enclosing application frame** supplies the *role*
(idle-worker vs blocked-consumer vs external-wait vs lock-contended). Match on enclosing frame +
leaf pair, not leaf alone — a rules file keyed only on leaf frames will misclassify every idle pool
as "blocked" and every genuinely stuck consumer as "fine," because the same leaf frame appears in
both.

## 2. Saturation / pool-exhaustion heuristics

The reference capture's headline number — 44% of all threads parked in one idle-worker frame on a
*healthy* server — is the single fact every saturation heuristic must survive.

Standard practitioner approach (cross-checked against .NET ThreadPool-starvation guidance and
HikariCP-style pending-request monitoring, both consistent): **occupancy is computed within a
pool, not across the whole process.**

```
occupancy(pool) = 1 − (threads currently in that pool's known idle-wait frame) / (pool's total thread count)
```

- Reference capture's `MSIQTask::GetNextPreferredJob` pool: 1,715 threads, **all** in the idle frame
  → occupancy 0%. This is definitionally healthy: a pool cannot be exhausted while it still has
  threads parked in its own "waiting for work" shape — that's headroom by construction, not a
  symptom.
- A **defensible, non-arbitrary** threshold falls straight out of the same count: occupancy at or
  near 100% (i.e., **zero or near-zero threads remaining in the pool's idle frame**) is the
  structural definition of exhaustion — it is a direct count, not an estimated percentage pulled
  from an APM vendor's default. Contrast with common arbitrary thresholds in the wild ("80% busy =
  warning" style knobs seen in Tomcat/Jetty pool monitoring and .NET starvation blog posts,
  confidence: LOW, single-source) — those are legitimate *early-warning* tunables but are opinions,
  not facts, and should be optional/configurable, never the headline figure.
- What actually distinguishes **idle-parked** from **saturated**, concretely: idle-parked pools
  show a nonzero, often large, count in the pool's own idle-wait frame; a saturated pool shows that
  count collapse toward zero while the pool's total thread count (if the pool grows dynamically) or
  the count of threads in worker-body frames rises. Sift can compute the first half (idle count vs.
  pool total) from a single dump; the second half (rising worker-body population, or an actual
  queue-depth counter) either needs a second dump's population delta (§4) or an external counter
  Sift doesn't have access to from eu-stack alone — report occupancy as the sound single-dump fact
  and gate any "trending toward saturation" language behind having ≥2 dumps.
- Do **not** synthesise a pool identity from co-location under one signature alone without the
  idle-frame anchor — "many threads share a stack signature" is a *description*, not evidence of
  either health or saturation; only comparing the idle-count to the pool total makes it
  interpretable, exactly the gap the reference capture exposed.

## 3. Lock contention from stack samples alone

Sound and unsound inferences, given no ownership edges (grounded in Rice University's HPCToolkit
blame-shifting work — Tallent & Mellor-Crummey, PPoPP 2010 — the closest peer-reviewed treatment of
this exact problem; confidence: MEDIUM, single paper but authoritative and directly on-point):

**Sound:**
- N threads simultaneously observed inside the **same named lock-acquisition call path**
  (matching enclosing frames, e.g. `MSynch::RWLock::ReadSmartLock`) is legitimate evidence that lock
  site is *currently* more contended than a briefly-held, uncontended lock would produce — the
  underlying argument (also HPCToolkit's) is probabilistic: an instantaneous sample is far less
  likely to catch a thread mid-acquisition if acquisition is fast, so catching several at once at
  the same site implies above-typical residence time there.
- The `__lll_lock_wait` leaf specifically (§1) confirms the futex *slow path* was actually entered
  — real kernel-level contention, not merely "somewhere inside the pthread API."
- Expressing this as a **plain count** ("N threads observed at lock-acquisition frame X in this
  dump") is a computed, citable fact exactly like every other Sift figure.

**Unsound — must not be inferred, and must be stated as such if reported at all:**
- **Who holds the lock.** No ownership edge exists in eu-stack; do not name a "holder" thread.
- **Deadlock.** No wait-for graph is constructible; never use the word "deadlock" for anything
  Sift's eustack analyser reports — this is the JVM/`jstack` technique the milestone explicitly
  rules inapplicable (§1).
- **Duration of the block.** No per-thread timestamps exist; only across-dump deltas at
  population/site granularity are available (§4), never a per-thread "blocked for Ns" claim.
- **Root-cause vs. symptom.** A lock convergence can itself be caused by something upstream (e.g. a
  slow warehouse call inside the critical section) — Sift should surface the convergence as
  evidence, not assert it is the primary cause.

**How to express confidence:** report the raw thread count at the site as the cited fact, and
attach a qualitative label (e.g. "elevated relative to baseline" vs. "typical") only if a
configured or computed baseline exists for that site — and always phrase the label as a heuristic
interpretation layered on the fact, never merge the two into one assertion the model could cite as
if it were the count itself.

## 4. Multi-sample / progression analysis

Sampling profilers (async-profiler, `perf`, JFR) get statistical power from **many** samples per
thread over time — flame graphs need hundreds to thousands of samples to be meaningful. Sift's
regime (1–2 eu-stack captures, humans triggering them by hand) is nowhere near that population size
and must not borrow profiler-style statistical claims.

Hang-triage folklore (the "capture 3 dumps 10s apart, identical = stuck" pattern, cross-checked
across a Medium "How to Read Thread Dumps" guide and a ycrash troubleshooting article — confidence:
LOW/MEDIUM, blog-tier but consistent across two independent sources) is **exactly the mechanism
this milestone's own measurement falsified**: on a healthy, near-idle server, 98.9% of threads have
an identical stack across two dumps, because pool workers in `pthread_cond_timedwait` are *designed*
to look frozen. That folklore assumes a request-serving thread-per-connection model where idle
threads simply don't exist in large numbers — it does not hold for a large-pool-of-idle-workers
architecture like the Intelligence Server's.

**What's reliable at N=2** (concrete, and gated by the taxonomy, not applied uniformly):

- **Per-signature population deltas.** A signature's thread count moving from near-zero to
  substantial between two dumps (e.g. "blocked on warehouse" going from 2→200) is sound and doesn't
  depend on tracking individual TIDs — pure count arithmetic.
- **Thread-count growth within a role bucket** (a pool growing, or a normally-small idle-count
  shrinking toward zero — tying back to §2's occupancy definition) across two dumps is a legitimate
  trend, computed from two counts.
- **New signatures appearing** (a stack shape present in dump B, absent in dump A) flags emergent
  behaviour worth surfacing, with no claim about *why*.
- **Same-TID persistence, but only inside a priori non-idle buckets.** A specific TID sitting in
  `CDSSQueryEngine::WaitUntilFinished` (blocked-on-external) in *both* dumps is meaningfully
  different from a TID idling in `GetNextPreferredJob` (idle-by-design) in both — the former is
  "still blocked after 60s," the latter is "still correctly idle," and they must not be reported
  with the same phrasing. **This is the concrete rule the reference capture demands:** gate any
  same-stack-persistence check by the thread's taxonomy category (§1) — apply it only to
  blocked-on-external / blocked-on-lock / running buckets, never to idle-parked. Applying it
  uniformly is precisely the falsified mechanism.
- Even within a legitimately "working" bucket, catching the **same** deep application frame at both
  T0 and T+60s (e.g. `CDSSSubsetEngine::GenCube` twice) is *suspicious, not proof* — it could be a
  naturally slow phase on a large item rather than a wedge. Two samples 60s apart cannot distinguish
  those without a third dump or an external duration expectation Sift doesn't have; report it as a
  flagged observation, not a conclusion.

**What needs N≫2** (explicitly out of reach at Sift's 1–2 dump scale, and must not be attempted):
leaf-frame churn as a progress signal (needs closely-spaced samples to see a thread move between
several frames); statistical time-in-state distributions; flame-graph-style proportional
attribution; confidently declaring "no forward progress" for a working thread from just two
snapshots.

**At N=1:** full role/composition classification (§1), per-pool occupancy (§2), and lock-site
convergence (§3) are all computable — this is why the milestone scopes "1 dump gives full
classification." Multi-dump only *adds* the population-delta and gated-persistence signals above;
it enables nothing at N=1 that structurally requires it, and its absence must degrade loudly
(explicit "single-dump mode — no progression signals available" in the report), never silently.

## 5. Report shape

Cross-checked patterns from thread-dump triage guides, DebugDiag's own report structure (leads with
an "Analysis Summary"), and WinDbg's `!analyze -v` convention (leads with a probable-cause bucket,
then supporting evidence) all agree on the same ordering principle: **aggregate verdict first, raw
per-thread detail last.** Recommended order for `sift eustack`:

1. **Headline composition summary** — thread count, distinct signature count, unclassified count.
   The single most-checked line; mirrors DebugDiag's Analysis Summary.
2. **Per-pool occupancy table** (§2) — busy vs. idle per identified pool. This answers "is anything
   actually exhausted," the first question an engineer asks after the headline.
3. **External-wait concentration** (warehouse / HTTP / IPC counts) — usually points *outside* the
   process, so engineers check this early to rule Sift's own process in or out.
4. **Lock-contention convergence table** (§3) — site, thread count, confidence label.
5. **Unclassified-frame list**, with counts and an example stack — surfaced explicitly, never
   buried, both because it's genuinely useful triage information and because Sift's own ethos
   forbids silent guessing; this is also where a human decides the rules file needs an addition.
6. **Multi-dump section** (only rendered when ≥2 dumps present) — population deltas per signature,
   gated persistence findings (§4), newly-appeared signatures. Must say plainly when it's absent
   rather than omit the heading.
7. **Raw per-thread appendix / CSV** — last. Engineers drop to this only when the aggregate views
   didn't explain the incident; it must never be the report's lead, which is the classic failure
   mode of raw `eu-stack`/`jstack` output (thousands of lines of undifferentiated text).

**Noise to avoid:** leading with raw stack text; reporting every idle pool's 100%-idle state as if
it were a finding (collapse to one summary line: "N idle pools, fully parked, no signal"); any
per-thread duration or ownership claim the input cannot support (§§1–3).

## v1.3 Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Frame→role/subsystem taxonomy (versioned rules file) | Foundation for every other feature; mirrors the existing `sift/prompts/*.md` versioned-file pattern users already trust | LOW–MEDIUM | Mostly data curation (frame-pattern → role table) + enclosing/leaf pair matching (§1); no new architecture, but correctness depends on getting the enclosing-frame-carries-role rule right from the start |
| Unclassified-frame surfacing (count + example, never guessed) | Matches Sift's existing "nothing disappears silently" invariant (unparseable regions → `severity="unknown"`) | LOW | Mechanical byproduct of a taxonomy lookup miss; requires no new mechanism, just refusing to force a match |
| Per-signature composition report (stack collapse + counts) | This is the actual signal per the reference capture (93 signatures from 3,902 threads) — without it there is no analysis, only a wall of raw stacks | MEDIUM | Needs an exact-symbol-sequence signature key (not regex-masked text like log dedup — eu-stack frames are already address-free symbol names, so the natural key is simpler than the existing template-dedup masking) |
| Per-pool occupancy (busy vs idle) table | Answers "is anything exhausted," the first question after composition | MEDIUM | Depends on taxonomy existing; needs a pool-identity concept (group by idle-frame shape) distinct from a bare signature |
| `sift eustack <case>` standalone report + CSV | Mirrors the already-shipped `sift mcm` / `sift perfmon` contract users now expect from every analyser | LOW–MEDIUM | Third analyser of this shape — deterministic compute → Markdown + CSV → facts module is an established, low-risk pattern to replicate, not a new design |
| Eu-stack facts into `sift analyze` as cited-not-authored evidence | Preserves the load-bearing `cited ⊆ prompted ⊆ store` boundary already enforced for MCM/perfmon facts | LOW–MEDIUM | Direct copy of the MCM-06/PERF-07 pattern; the work is in the fact *content* (zero-digit template), not new plumbing |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-dump population-delta + taxonomy-gated per-TID persistence signal | This is the concrete rule that avoids the falsified "identical stack = stuck" trap (§4) — a generic `diff two eu-stack dumps` tool would walk straight into the 98.9% false-positive rate this milestone measured; gating by taxonomy category is the differentiating insight | MEDIUM–HIGH | Depends on: taxonomy (table stakes) existing first, and correct TID matching across dumps (already solved by the adapter's `event_id`/TID data) |
| Lock-contention convergence with explicit confidence labelling (count as fact, label as heuristic) | Sound-inference discipline (§3) is exactly what a naive "N threads on the same stack = deadlock" tool gets wrong; explicitly refusing to say "deadlock" or name a lock holder is a trust differentiator for a tool whose whole pitch is not fabricating | MEDIUM | Depends on taxonomy + occupancy machinery; the work is mostly in wording/templating discipline, not algorithms |
| External-wait attribution split by subsystem (warehouse / HTTP / IPC) | Immediately tells an engineer whether to look inside or outside the process — directly actionable | MEDIUM | Mirrors the MCM/PERF fact-feeding pattern; subsystem split comes for free once taxonomy roles are curated per-subsystem rather than one generic "external" bucket |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| "Identical stack after N seconds = stuck thread" | Intuitive, matches JVM-world folklore (jstack "3 dumps, identical = stuck") | Empirically falsified: flags 98.9% of threads on a demonstrably healthy server (measured, not estimated) — an inverted signal, not a weak one | Composition/role-based occupancy (§2) + taxonomy-gated persistence only within non-idle buckets (§4) |
| Deadlock cycle detection ("Thread A waiting on lock held by Thread B") | Familiar from `jstack`/`!analyze`; feels like the "real" answer | Structurally impossible — eu-stack carries no lock-ownership edge or wait-for graph; any such report fabricates data the input cannot support | Lock-acquisition-site convergence count with an explicit "ownership/cycles cannot be determined from this input" caveat baked into the fact template |
| LLM-inferred thread classification (ask the model whether a thread "looks stuck" from raw stack text) | Feels flexible, no rules file to maintain | Violates the deterministic-core-vs-LLM boundary that is Sift's core differentiator; the model may narrate a pre-computed label, never assign one | Hand-curated versioned rules file (as already scoped), unclassified when no rule matches |
| Arbitrary numeric saturation thresholds reported as bare facts (e.g. "80% busy = WARNING") without the underlying occupancy count | Common in APM dashboards (Tomcat/HikariCP-style pool monitors) | The threshold is an opinion, not a measurement — presenting it undifferentiated from a computed fact blurs Sift's fact/narration boundary | Report the raw occupancy count always; make any graded threshold an explicitly optional, clearly-labelled, configurable heuristic layer |
| Per-thread wait-duration claims ("blocked for 47s") | Natural-sounding, matches what users actually want to know | No per-thread timestamps exist in eu-stack; only dump-capture-time-level deltas (whole dumps, not individual threads) are computable | Report only dump-to-dump timing (already known: 60s between the two reference dumps) and per-signature/per-pool population deltas, never a single-thread duration |
| Force-classifying an unrecognised frame into the "closest" known bucket | Reduces visible `unclassified` count, looks more complete | Directly violates "unknown frames are reported as unclassified, never guessed" — the same anti-hallucination discipline already load-bearing elsewhere in Sift | Leave unclassified, surface count + example in the report, let a human extend the rules file |

## v1.3 Feature Dependencies

```
Frame→role taxonomy (rules file)
    └──requires──> nothing new (pure data curation over existing eustack Event/frame data)

Per-signature composition report
    └──requires──> Frame→role taxonomy (roles label the top signatures; raw signatures alone are uninterpretable, per §2)

Per-pool occupancy table
    └──requires──> Frame→role taxonomy
    └──requires──> Per-signature composition report (pool = a role's signature population)

Lock-contention convergence
    └──requires──> Frame→role taxonomy (needs the blocked-on-lock bucket + enclosing lock-site names)

External-wait attribution (warehouse/HTTP/IPC split)
    └──requires──> Frame→role taxonomy (subsystem-specific roles, not one generic "external" bucket)

Multi-dump population deltas
    └──requires──> Per-signature composition report (deltas are computed per signature)

Taxonomy-gated per-TID persistence signal
    └──requires──> Frame→role taxonomy (the gate itself IS the taxonomy category)
    └──requires──> Multi-dump population deltas (needs ≥2 dumps to exist at all)

sift eustack report + CSV
    └──requires──> All of the above computed facts (it is the rendering layer, not a new computation)

Eu-stack facts into sift analyze
    └──requires──> sift eustack report machinery (same computed facts, second rendering target)
    └──enhances──> sift analyze hypothesis quality (adds cited evidence, mirrors MCM-06/PERF-07)

Deadlock cycle detection ──conflicts──> eu-stack's data model (no ownership edges exist; do not attempt)
```

### Dependency Notes

- **Everything downstream requires the taxonomy first.** It is the one genuinely new artefact
  (a hand-curated rules file, sibling to `sift/prompts/*.md`); every other feature is either a
  grouping/aggregation over taxonomy-labelled threads or a rendering layer over those aggregations.
  This should be phase 1 of the roadmap slice for this capability.
- **Multi-dump signals require the taxonomy for correctness, not just for existence** — the
  gated-persistence rule (§4) is specifically "apply persistence-checking only within non-idle
  taxonomy categories," so it cannot be built before the taxonomy exists without risking exactly
  the falsified mechanism this milestone was scoped to avoid.
- **Deadlock detection conflicts with the input, permanently** — this isn't a "defer to v2" item,
  it's a "the data model this milestone is built on cannot ever support it" item, and should be
  recorded as an explicit non-goal rather than a backlog entry, so a future contributor doesn't
  reintroduce it assuming eu-stack could be extended to carry ownership info (it structurally
  cannot, short of a different capture tool entirely).

## v1.3 MVP Definition

### Launch With (v1.3)

- [ ] Frame→role/subsystem taxonomy rules file (idle-parked / blocked-on-external /
      blocked-on-lock / running / unclassified) — everything else depends on it
- [ ] Per-signature composition report + per-pool occupancy table — this is the actual "why is it
      slow" answer for the single-dump case, which the milestone requires to work standalone
- [ ] Unclassified-frame surfacing — non-negotiable per Sift's existing anti-hallucination
      invariant, essentially free once the taxonomy lookup exists
- [ ] `sift eustack <case>` report + CSV, no-DSSErrors-log-required — matches the shipped
      `mcm`/`perfmon` UX contract exactly

### Add After Validation (v1.3, once single-dump is solid)

- [ ] Lock-contention convergence with confidence labelling — needs the taxonomy's
      blocked-on-lock bucket proven correct first, or it will mislabel healthy `rdlock` samples as
      contention
- [ ] External-wait subsystem split (warehouse/HTTP/IPC) — trivial once taxonomy roles are curated
      per-subsystem, but sequenced after the core taxonomy is validated against the reference
      capture
- [ ] Multi-dump population deltas + taxonomy-gated persistence signal — explicitly requires ≥2
      dumps to exist and the single-dump taxonomy to already be trustworthy, or the gating logic
      has nothing correct to gate against
- [ ] Eu-stack facts into `sift analyze` — sequenced last because it's a second rendering target
      for facts that must already be correct in the standalone report

### Future Consideration (beyond v1.3)

- [ ] Configurable, clearly-labelled graded saturation thresholds (e.g. "80% busy = warning") as an
      optional layer on top of the raw occupancy count — defer because it's an opinion needing user
      validation, not a measurement; the raw count is the v1.3 deliverable
- [ ] Corroborating `/proc/<tid>/stat` state codes if a future capture pipeline collects them
      alongside eu-stack — genuinely new orthogonal signal, but not available in the current
      ingestion format and out of scope until the adapter/capture tooling changes

## v1.3 Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| Frame→role taxonomy rules file | HIGH | MEDIUM | P1 |
| Per-signature composition + per-pool occupancy | HIGH | MEDIUM | P1 |
| Unclassified-frame surfacing | MEDIUM | LOW | P1 |
| `sift eustack` report + CSV | HIGH | LOW–MEDIUM | P1 |
| Lock-contention convergence w/ confidence labels | MEDIUM | MEDIUM | P2 |
| External-wait subsystem split | MEDIUM | MEDIUM | P2 |
| Multi-dump deltas + gated persistence | HIGH | MEDIUM–HIGH | P2 |
| Eu-stack facts into `sift analyze` | MEDIUM | LOW–MEDIUM | P2 |
| Configurable graded thresholds | LOW | LOW | P3 |
| `/proc` state-code corroboration | LOW (not available in current format) | HIGH (needs new capture tooling) | P3 |

**Priority key:**
- P1: Must have — the single-dump, no-DSSErrors-log analyser the milestone requires
- P2: Should have — the multi-dump/facts-integration half of the milestone's scoped feature list
- P3: Future consideration — needs either user validation (arbitrary thresholds) or new capture
  tooling (`/proc` state) that is out of scope for this milestone

## v1.3 Analogue Comparison (no direct competitor product exists)

There is no direct competitor product (a "native eu-stack hang analyser" is not a commercial
category); the useful comparison is against the analogous JVM/Windows tools whose techniques were
evaluated for transferability:

| Capability | JVM world (`jstack`/async-profiler/JFR) | Windows world (DebugDiag/`!analyze`) | Sift's approach |
|---|---|---|---|
| Thread classification | JVM-maintained authoritative thread-state field | OS handle-wait APIs (`WaitForSingleObject`) | Frame-pattern matching only — no authoritative state field exists for native eu-stack threads, so classification is entirely rules-file-driven (§1) |
| Deadlock detection | Wait-for graph + cycle detection from monitor-owner data | Critical-section owner tracking | **Not implemented** — structurally impossible without ownership edges; explicitly a non-goal, not a gap |
| Saturation detection | Thread-pool metrics APIs (queue length, active count) exposed by the runtime | Handle/queue counters via ETW | Computed from stack composition alone (occupancy = 1 − idle/total per pool, §2) — no runtime-exposed counters available for a native process snapshot |
| Multi-sample analysis | Statistical, many-sample flame graphs | Multiple dumps compared by a human, ad hoc | Two-dump population deltas + taxonomy-gated persistence — a narrower, more defensible claim set than either JVM statistical profiling (needs far more samples) or ad hoc Windows dump comparison (no taxonomy gating, prone to the falsified "identical = stuck" trap) |

## v1.3 Sources

- https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html — `/proc/pid/stat` state codes, primary kernel docs — HIGH (cross-checked against Ubuntu manpage)
- https://manpages.ubuntu.com/manpages/noble/man5/proc_pid_stat.5.html — cross-check for state codes — HIGH
- https://github.com/jvm-profiling-tools/async-profiler/issues/279 — JFR `STATE_RUNNABLE`/`STATE_SLEEPING` wall-clock classification — MEDIUM
- https://www.baeldung.com/java-async-profiler — async-profiler wall vs. CPU mode, `--state` filtering — MEDIUM
- https://docs.oracle.com/javase/8/docs/technotes/guides/troubleshoot/tooldescr016.html — `jstack` deadlock detection mechanism (wait-for graph, monitor-owner reporting) — HIGH (primary vendor docs)
- https://blogs.iis.net/sukesh/ddintro/ and https://www.tessferrandez.com/blog/2009/01/23/net-hang-analyzing-debug-diag-output.html — DebugDiag hang-analysis rule structure, report ordering — MEDIUM
- https://www.cs.rice.edu/~johnmc/papers/hpctoolkit-ppopp-2010.pdf (Tallent & Mellor-Crummey, PPoPP 2010) — blame-shifting lock-contention analysis from stack samples without ownership data — MEDIUM (single paper, peer-reviewed, directly on-point)
- https://linux.die.net/man/3/pthread_cond_wait and https://pubs.opengroup.org/onlinepubs/7908799/xsh/pthread_cond_wait.html — POSIX semantics of `pthread_cond_wait`/`pthread_cond_timedwait` — HIGH (primary POSIX spec)
- http://www.rkoucha.fr/tech_corner/the_futex.html and https://lwn.net/Articles/360699/ — futex mechanics underlying pthread primitives — MEDIUM
- https://medium.com/@RamLakshmanan/how-to-read-thread-dumps-easily-efficiently-c74330144c4b and https://blog.ycrash.io/jvm-production-troubleshooting-guide/ — "N dumps, compare, identical = stuck" hang-triage folklore, cited specifically as the falsified-by-measurement mechanism — LOW/MEDIUM (blog-tier, but consistent across independent sources, and directly contradicted by this milestone's own measured data)
- `.planning/research/MILESTONE-CONTEXT-v1.3.md` — the measured reference-capture evidence this entire document is scoped around — HIGH (first-party, measured)

---

# Appendix — v1.0 whole-product feature landscape (preserved, unchanged, 2026-07-16)

**Domain:** Local-first LLM-powered incident/log triage CLI
**Researched:** 2026-07-16
**Overall confidence:** MEDIUM (web-verified across multiple independent sources; no single authoritative spec for the category)

## How the Ecosystem Splits

Four families of prior art, each defining a slice of user expectations:

1. **CLI log viewers** (lnav, angle-grinder, GoAccess) — set expectations for ingestion UX: auto-detect formats, handle compressed/rotated files, merge multi-file timelines, filter, "point at a directory and it works".
2. **Log-mining libraries** (Drain3, LogAI, LogPAI ecosystem) — set expectations for the analysis core: template mining, dedup, clustering, anomaly detection. Libraries, not products; no end-user workflow.
3. **LLM triage agents** (k8sgpt, HolmesGPT) — set expectations for AI output: human-readable explanations, ranked findings, suggested next steps, runbook/knowledge integration. Both are cloud-LLM-first and Kubernetes-scoped; HolmesGPT is agentic (nondeterministic ReAct loop), k8sgpt is deterministic analyzers + LLM explanation.
4. **Commercial AIOps** (BigPanda, PagerDuty AIOps, Datadog Event Management, Splunk ITSI) — set expectations for the pipeline shape: normalise → deduplicate (70–85% compression is the marketed norm) → correlate → root-cause → reduce noise. This is exactly Sift's pipeline, minus the SaaS.

The local/offline niche is nearly empty: existing "local LLM log analysis" tools are single-file Ollama prompt wrappers with no event schema, no dedup, no citations, no eval. Sift's SPEC already targets the actual gap. (Confidence: LOW→MEDIUM — absence of tooling is hard to prove, but repeated searches surfaced only prototypes.)

## Table Stakes

Features users expect. Missing = product feels incomplete. "SPEC" column = already covered by SPEC.md v0.1.

| Feature | Why Expected | Complexity | SPEC? | Notes |
|---------|--------------|------------|-------|-------|
| Normalise heterogeneous inputs to one event schema | Universal AIOps baseline; lnav's core trick | Med | Yes (§5.1–5.2) | Canonical `Event` + adapters |
| Format auto-detection | lnav sets the bar ("point at a directory") | Low | Yes (§5.2 sniff) | 64 KB sniff + genericlog fallback |
| Robust generic/fallback parser (nothing dropped silently) | Users judge tools by the file it *can't* parse | Med | Yes (§5.2 rule) | `severity="unknown"` events + parse-coverage metric is stronger than most tools |
| Deduplication with counts (template mining) | 70–85% compression is the marketed AIOps norm; Drain-style masking is standard | Med | Yes (§5.4) | Cheap-first masking before ML matches industry practice |
| Correlation/clustering of related events | Core AIOps value: alerts → few incidents | Med | Yes (§5.4) | Embeddings + HDBSCAN |
| Ranked root-cause findings, human-readable | k8sgpt/HolmesGPT norm | High | Yes (§5.5) | |
| Suggested next steps per hypothesis | Present in every LLM triage tool | Low | Yes (§5.5 JSON) | |
| Timeline reconstruction | Incident responders think in timelines | Med | Yes (§5.5, §5.7) | |
| Machine-readable output (JSON) + stable exit codes | CLI tools live in scripts/CI | Low | Mostly | JSON yes; **gap:** define exit-code contract for `analyze` (e.g. non-zero on degraded run) |
| Compressed/rotated file handling (.gz, .zst, .bak siblings) | lnav auto-decompresses; rotated logs are the normal case | Low | **Partial gap** | SPEC covers dsserrors `.bak` but not gzip/zstd inputs generally — add to genericlog/ingest |
| Time-window scoping (`--since`/`--until`) | journalctl/lnav muscle memory; triage is time-anchored | Low | **Gap** | SPEC has `--hint` free text only; a hard time filter on analyse (and ideally ingest) is expected |
| Progress feedback on long operations | 2 GB ingest + local-LLM latency; silent CLI = "is it hung?" | Low | **Gap** | Coverage stats exist post-hoc; add progress reporting during ingest/embed/generate |
| Inspection commands (query events/clusters before trusting AI) | lnav's SQLite querying; engineers verify | Med | Yes (§5.8 `sift show`) | Filterable show is the trust bridge |
| Health check of dependencies | Local inference is flaky; k8sgpt has `auth`/backend checks | Low | Yes (`sift doctor`) | |
| Easy install, no daemon | "Simple tools win" — recurring theme in CLI tool adoption | Low | Yes (§M8, SQLite) | |

## Differentiators

Not expected, but valued — Sift's competitive edge for its niche.

| Feature | Value Proposition | Complexity | SPEC? | Notes |
|---------|-------------------|------------|-------|-------|
| Hard citation validation (claims must cite real event IDs) | Directly answers the #1 adoption blocker: hallucination/trust (51% rate it top challenge; CISOs distrust conclusions that don't match evidence). No surveyed tool enforces this | Med | Yes (§5.5) | The load-bearing differentiator — keep it hard-fail |
| `unexplained_signals` honesty section | Anti-automation-bias: showing what the model *can't* explain builds trust faster than confident narrative | Low | Yes (§5.5 JSON) | Rare in the wild; keep |
| Fully offline, backend-agnostic (OpenAI-compatible only), loopback-enforced | The niche driver: regulated/air-gapped users (GDPR/HIPAA/SOC2). Existing local tools are prototypes; agents are cloud-first | Med | Yes (§5.6) | Refuse-non-loopback is itself a marketable feature |
| Determinism + reproducible reports | Auditable RCA; agentic competitors (HolmesGPT) are inherently nondeterministic | Med | Yes (§5.7) | Pairs with eval harness |
| Evaluation harness with golden incidents + CI thresholds | No local tool measures itself; converts "vibes" into regression-tested quality | High | Yes (§6) | Also a credibility asset in the README |
| Deep domain adapters (dsserrors, eustack) | Encodes MicroStrategy expertise no generic tool has; multi-line MCM blocks, SIDs, multi-node tags | Med–High | Yes (§5.2) | The moat for the author's user base |
| Local knowledge-base retrieval (runbooks/prior RCAs) | HolmesGPT's runbooks are its most-praised feature; Sift gets the same effect statically and deterministically | Med | Yes (§5.5) | |
| Evidence appendix with file:line provenance | Reviewers can jump from claim to raw text; deeper than any surveyed tool's output | Low | Yes (§5.7) | |
| Report redaction/sanitisation pass | Privacy users eventually need to *share* the report (vendor support, tickets) even though inputs stay local; masking hostnames/IPs/SIDs on render extends the privacy story end-to-end | Med | **Gap (v1.x candidate)** | Also needed anyway to sanitise real cases into golden eval cases — consider building once, using twice |
| Event-volume histogram in report (counts over time per cluster) | lnav's histogram is beloved; a burstiness sparkline/table strengthens the timeline | Low | **Gap (cheap add)** | Data already exists (first/last_ts, counts); render-only |
| Case baseline diff ("what's new vs a known-good case") | Classic triage question; LogReducer-style delta analysis | High | Gap (defer to v2) | Needs two-case comparison machinery; note in roadmap, don't build |

## Anti-Features

Features to explicitly NOT build — each is somewhere in the ecosystem and would damage this product.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Agentic tool-calling investigation loop (HolmesGPT-style ReAct) | Nondeterministic, unbounded token cost on local hardware, breaks citation auditing and reproducibility — the opposite of Sift's trust model | Fixed pipeline: salience-ranked retrieval → one constrained generation → validation |
| Chat/conversational interface | Invites automation bias; unauditable; scope creep towards a product Sift isn't | `--hint` for user context; reviewable reports as the interaction surface |
| Cloud LLM fallback ("degrade to OpenAI when local is slow") | Destroys the only reason the product exists; one accidental egress = trust gone | Hard loopback/RFC1918 refusal (already in SPEC §5.6) |
| Auto-remediation / suggested-command execution | Acting on hallucinated RCA is the nightmare scenario the trust literature warns about | `suggested_next_steps` as text; humans act |
| Live streaming/tail mode | Different architecture (stateful watch, alerting); batch determinism is the v1 identity | Batch cases; re-ingest is idempotent and cheap |
| Deep-learning anomaly-detection suite (LogAI-style CNN/LSTM/Transformer) | Heavy deps, GPU entanglement, training data Sift doesn't have; LogAI exists for researchers | Template dedup + embeddings + HDBSCAN covers the triage need |
| Alerting/notification integrations (Slack, PagerDuty, webhooks) | Network egress by definition; SaaS-platform territory | JSON output; users pipe it wherever they like |
| Model management (download/quantise/serve) | llama.cpp and Lemonade own this; duplicating it is a maintenance tar pit | `sift doctor` diagnoses the endpoint; README documents setup |
| Web UI/TUI in v1 | "Simple CLI tools win"; UI triples surface area before the pipeline is proven | Markdown/PDF reports are the UI; revisit post-v1 |
| Telemetry/usage analytics | Instant disqualification for the target audience | None. Ever. |

## Feature Dependencies

```
Event schema → adapters (genericlog → journald/dsserrors/eustack)
Event schema → case store → template dedup → semantic clustering
Inference client → doctor
Inference client + clustering → cluster labels → salience → RAG hypothesis generation
Hypothesis generation → citation validation → renderers (MD → JSON → PDF)
KB retrieval → RAG (optional input)
Full pipeline → eval harness (golden cases exercise everything)
Renderers → redaction pass (gap; render-time feature)
Cluster stats (first/last_ts, count) → histogram rendering (gap; render-time feature)
Time-window filter (gap) → sits at ingest/analyse boundary; independent of LLM features
```

Notably, all three cheap gap-fills (time filter, progress reporting, histogram) have no dependency on the LLM stack — they slot into M1–M2 and M6 respectively without touching the RAG core.

## MVP Recommendation

The SPEC's M1–M8 ordering already matches the ecosystem's dependency structure (pipeline before AI, AI before polish). Adjustments from this research:

1. **Fold the three cheap table-stakes gaps into existing milestones:** gzip/zstd input handling + `--since/--until` + progress reporting into M1–M2; exit-code contract into M4; histogram into M6. All Low complexity.
2. **Keep citation validation and the eval harness sacred** — they are the answer to the domain's #1 complaint (hallucination/trust) and no competitor has them locally.
3. **Defer, but record:** report redaction (v1.x — build alongside golden-case sanitisation in M7 if it falls out naturally), case baseline diff (v2), TUI/web view (v2).
4. **Resist:** everything in the anti-features table, especially agentic loops and cloud fallback — the surveyed products that have them serve a different (cloud, interactive) market.

## Sources

- [HolmesGPT: Agentic troubleshooting (CNCF blog)](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/) — MEDIUM
- [HolmesGPT documentation](https://holmesgpt.dev/0.35.0/) — MEDIUM
- [Open Source AI SRE tools comparison (Arvo)](https://www.aurorasre.ai/blog/open-source-ai-sre-aurora-vs-holmesgpt-vs-k8sgpt) — LOW (vendor blog, cross-checked with CNCF/docs)
- [salesforce/logai (GitHub)](https://github.com/salesforce/logai) + [LogAI paper](https://arxiv.org/pdf/2301.13415) — MEDIUM
- [lnav features (official)](https://lnav.org/features) + [tstack/lnav](https://github.com/tstack/lnav) — MEDIUM
- [AIOps features overview (Splunk)](https://www.splunk.com/en_us/blog/learn/aiops.html), [Selector AIOps tools guide](https://www.selector.ai/learning-center/aiops-tools-key-features-and-top-8-solutions/) — MEDIUM (consistent across vendors)
- [Local LLM log analysis prototypes: llm-rca-assistant](https://github.com/Mustafa3946/llm-rca-assistant), [stratosphereips/llm-log-analyzer](https://github.com/stratosphereips/llm-log-analyzer), [Ollama log analysis write-up](https://dev.to/devopsstart/local-llm-for-log-analysis-privacy-first-debugging-with-ollama-361o) — LOW
- [AI hallucination trust surveys/commentary (Dropzone AI)](https://www.dropzone.ai/blog/when-ai-gets-it-wrong-the-critical-importance-of-context-engineering), [CSO Online](https://www.csoonline.com/article/4143444/9-ways-cisos-can-combat-ai-hallucinations.html) — MEDIUM (consistent across sources)
