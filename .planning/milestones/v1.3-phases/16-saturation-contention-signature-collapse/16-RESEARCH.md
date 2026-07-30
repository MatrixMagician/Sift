# Phase 16: Saturation, Contention & Signature Collapse - Research

**Researched:** 2026-07-25
**Domain:** Deterministic groupings over an existing classified-thread model (no new ingestion, no new I/O, no LLM)
**Confidence:** HIGH

## Summary

Phase 16 is four pure functions over `EustackAnalysis.signatures` (Phase 15's shipped output) plus a
graded-flag pass. There is no new parsing, no new dependency, and — per D-12 — no LLM anywhere in the
path. The entire phase is `analyse_eustack(...) -> EustackAnalysis` (already shipped) piped into a new
`SaturationAnalysis` model, computed by grouping and walking the same frame tuples Phase 15 already
produced and classified.

The one piece of genuinely new logic is the D-04 enclosing-frame walk for lock convergence (EUS-04) — a
short, well-specified helper over an already-normalised frame tuple. Everything else (EUS-03 pool
occupancy, EUS-05 dependency split, the D-07 composition flags) is a `groupby`-shaped aggregation with an
explicit, named sort key, following the exact discipline `analyse_eustack` itself uses
(`groups.sort(key=lambda g: (-g.thread_count, g.frames))`, never `Counter.most_common()`).

The most consequential research finding is a **precedent conflict inside D-08**: D-08 says "reuse the
shipped MCM-03 pattern: `DiagnosticFlag` ... and the `_grade()` ... helper," but `DiagnosticFlag.value_pct`
is explicitly documented as "ALWAYS a ratio ... never an absolute GB" — and D-07's third flag (lock
convergence) is an absolute thread **count**, not a ratio. `perfmon.py` hit this exact mismatch in Phase
12-14 and resolved it by **not** reusing `DiagnosticFlag`, minting its own `PerfmonHazard` instead, with an
explicit code comment naming the reason. That comment is direct, in-repo evidence for how this phase
should resolve the same conflict for its count-based flag. See "Don't Hand-Roll" and Research Question 1
below.

**Primary recommendation:** import `mcm._grade` verbatim (pure, stateless, safe to reuse — same "shared,
not copied" pattern already used for `_condense_symbol`/`_RESERVED_ATTRS`/`_DRIFT_ATTR`); reuse
`DiagnosticFlag` verbatim for the two true ratio flags; do not force the lock-convergence count into
`value_pct` — mint one small sibling flag record (mirroring `PerfmonHazard`'s generic `value: float | None`
shape) that all three flags can share uniformly, so the field name never lies about its own contract.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-pool occupancy grouping (EUS-03) | Deterministic analyser (`pipeline/`) | — | Pure aggregation over `EustackAnalysis.signatures`; no I/O, no rendering |
| Lock-site enclosing-frame walk (EUS-04) | Deterministic analyser (`pipeline/`) | — | Pure function over an already-classified frame tuple |
| Dependency-wait split (EUS-05) | Deterministic analyser (`pipeline/`) | — | Pure aggregation, same shape as EUS-03 |
| Signature collapse ranking (EUS-06) | Already delivered (Phase 15, `pipeline/eustack.py`) | — | `EustackAnalysis.signatures` is already the ranked collapse; Phase 16 does not re-derive it |
| Graded composition flags (Success Criterion 5) | Deterministic analyser (`pipeline/`) | Config (`config.py`) | Grading logic and threshold values are code; thresholds are config keys per D-08 |
| Config threshold storage | Config (`config.py`) | — | Extends `EustackConfig` under `[eustack]`, mirrors `McmThresholdsConfig` |
| Rendering / CLI | Out of scope this phase | — | Phase 17 owns `sift eustack` and Markdown/CSV; Phase 16 is library-only |

## User Constraints

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** A "pool" is the rule's `subsystem` string. Occupancy for a pool is
  `1 - (idle-parked threads in that subsystem / all threads in that subsystem)`, computed by grouping
  `EustackAnalysis.signatures` on `subsystem`. No allowlist of "real" pools — `compute`, `lock` and
  `cube-generation` are subsystems too and are reported uniformly. Saturation is strictly per-pool, never
  process-wide.
- **D-02:** `unclassified` threads have `subsystem = None`. Counted and reported as their own row, never
  folded into any pool.
- **D-03:** A lock "site" is the enclosing application frame, not the leaf (`frame_index` points at
  glibc). The site is found by walking *up* from `frame_index`.
- **D-04:** The enclosing application frame is the first resolvable frame above `frame_index` whose
  normalised symbol contains `::`. Edge case: no such frame exists — report unknown-but-counted, never
  dropped, never attributed to the leaf. Rejected alternatives: runtime-prefix denylist, `frame_index + 1`.
- **D-05:** Every lock output is ownership-blind at the point of reporting; vocabulary must never contain
  "deadlock", "owner", or "holder".
- **D-06:** The dependency axis is the verbatim `subsystem` of `blocked-on-external` threads. No mapping
  layer. Target figures: 79 warehouse waits, 78 HTTP waits, separately visible.
- **D-07:** Flag only quantities with a non-arbitrary zero point: (1) unclassified thread share, (2)
  no-resolvable-frame share, (3) lock convergence — thread count at a single site above a configured
  count. **No per-pool occupancy flag ships this phase** (EUSV2-03 deferred).
- **D-08:** Flags reuse the shipped MCM-03 pattern: `DiagnosticFlag` with severity info/warn/critical and
  the `_grade()` two-cut-point helper in `mcm.py`. Every flag prints its raw computed value beside the
  configured threshold. Thresholds are config keys under `[eustack]`.
- **D-09:** The healthy reference capture must raise **zero** flags — a verification gate on chosen
  defaults, not an aspiration.
- **D-10:** Figures live in a **new** frozen Pydantic model (`SaturationAnalysis`) consuming
  `EustackAnalysis`. `EustackAnalysis` stays frozen and unchanged.
- **D-11:** EUS-04 validated by a **hand-authored synthetic fixture** — the healthy capture matches the
  lock rule zero times by design. Must be clearly labelled synthetic, not a redacted real capture.
- **D-12:** All figures computed model-free. No LLM anywhere in this phase.

### Claude's Discretion

- Exact model/field names (`SaturationAnalysis`, `PoolOccupancy`, `LockSite`, `DependencyWait`) and the
  module they live in.
- Whether the three flag families share one `DiagnosticFlag` list or separate fields.
- Default threshold values, subject to D-09 (zero flags on the healthy capture).
- Plan/task decomposition and wave structure.

### Deferred Ideas (OUT OF SCOPE)

- Graded saturation percentage thresholds (EUSV2-03) — no authoritative "N% busy = warning" source exists;
  explicitly not to be invented.
- A `pool = true` marker in the rules file — revisit only if the Phase 17 report reads badly with
  meaningless rows present.
- A separate `dependency` field per rule — revisit only if `subsystem` proves too fine-grained.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EUS-03 | Per-pool occupancy so an idle pool of parked workers reads healthy, not saturated | `EustackAnalysis.signatures` grouped by `subsystem`; occupancy formula and ordering specified below (Determinism section) |
| EUS-04 | Threads converging on a lock-acquisition path, always ownership-blind | D-04 enclosing-frame walk fully specified with edge cases (Research Question 2 below); D-11 synthetic-fixture strategy recommended (Research Question 5) |
| EUS-05 | External-wait concentration split by dependency (warehouse, HTTP, IPC) | `blocked-on-external` signatures grouped by verbatim `subsystem`; reference figures 79/78 confirmed reachable from the shipped rules (rules 16/17 in `eustack_roles.toml`) |
| EUS-06 | Thread population collapsed to distinct stack signatures, ranked by thread count | Already delivered by Phase 15 (`EustackAnalysis.signatures`) — Phase 16 reads it, does not re-derive it |
</phase_requirements>

## Standard Stack

### Core

No new dependency. Everything needed is already in the dependency graph:

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.13.x (already pinned) | `SaturationAnalysis` and its sub-models, frozen + `extra="forbid"` | Matches every other analysis model in the codebase (`EustackAnalysis`, `McmEpisode`, `PerfmonHazard`) |
| stdlib `collections` | 3.12+ stdlib | Grouping signatures by `subsystem` | `defaultdict`/`Counter`-shaped aggregation is exactly what `analyse_eustack` itself already does |
| stdlib `tomllib` (indirect, via `config.py`) | 3.12+ stdlib | Reading the extended `[eustack]` threshold config keys | Already the config-loading mechanism; no new parsing code needed |

### Supporting

Nothing to add. `mcm._grade` (pure function) is proposed for reuse — see "Don't Hand-Roll" below; it is
an existing in-repo function, not a library.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Grouping via plain `dict`/`defaultdict` | `itertools.groupby` | `groupby` requires pre-sorted input and is more surprising to a future reader for a one-pass tally; the existing codebase (`analyse_eustack`, `_counter_trends` in `perfmon.py`) uses plain dict accumulation, not `groupby` — follow that precedent for consistency, not because `groupby` is wrong |
| A new sibling flag model (`SaturationFlag`, recommended) | Forcing `DiagnosticFlag.value_pct` to also hold a raw count | `DiagnosticFlag`'s own docstring locks `value_pct` as "ALWAYS a ratio ... never absolute" — violating that documented invariant is exactly the kind of thing `perfmon.py`'s `PerfmonHazard` was created to avoid (see Research Question 1) |

**Installation:** none required.

**Version verification:** N/A — no new packages.

## Package Legitimacy Audit

**Not applicable.** This phase introduces zero new external packages (stdlib + already-installed
`pydantic` only), per D-12 and the phase's own "no CLI, no rendering, no LLM" boundary. No
`gsd-tools query package-legitimacy check` run was needed.

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```
EustackAnalysis                                SaturationAnalysis (NEW, Phase 16)
(Phase 15, unchanged)                          ┌──────────────────────────────────┐
┌──────────────────┐                            │                                    │
│ .signatures       │──group by subsystem──────▶│ pools: tuple[PoolOccupancy, ...]  │  EUS-03
│  (role, subsystem,│                            │                                    │
│   frames tuple,   │──filter role==             │                                    │
│   frame_index,    │  "blocked-on-lock"          │                                    │
│   thread_count)   │  ──walk frames[frame_index+1:]──▶│ lock_sites: tuple[LockSite, ...]  │  EUS-04
│                    │      (D-04 enclosing-frame walk)│                                    │
│                    │                            │                                    │
│                    │──filter role==             │                                    │
│                    │  "blocked-on-external"      │                                    │
│                    │  ──group by subsystem──────▶│ dependencies: tuple[DependencyWait,│  EUS-05
│                    │                            │   ...]                             │
│                    │                            │                                    │
│                    │──(read-only, no re-derive)─▶ (EUS-06: renderer reads             │
│                    │                            │  EustackAnalysis.signatures         │
│                    │                            │  directly — Phase 16 adds nothing   │
│                    │                            │  here)                              │
└──────────────────┘                            │                                    │
                                                  │ flags: tuple[<flag-record>, ...]  │  Success
   config.eustack.thresholds ──_grade() (imported │   (unclassified share,            │  Criterion 5
   from mcm.py, pure)────────────────────────────▶│    no-resolvable-frame share,     │
                                                  │    lock convergence count)        │
                                                  └──────────────────────────────────┘
                                                        │
                                                        ▼
                                            Phase 17 (sift eustack report + CSV)
                                            Phase 18 (fact injection into sift analyze)
```

### Recommended Project Structure

```
src/sift/
├── pipeline/
│   └── eustack.py           # EXTEND in place (D-10: EustackAnalysis unchanged, new symbols added
│                             # alongside it) — SaturationAnalysis, PoolOccupancy, LockSite,
│                             # DependencyWait, analyse_saturation(), the D-04 frame-walk helper.
│                             # Rationale: CONTEXT.md's own precedent phrase is "executable code in
│                             # src/sift/pipeline/eustack.py mirroring mcm.py/perfmon.py" — and
│                             # mcm.py/perfmon.py each keep their WHOLE domain (detection + flags)
│                             # in one file, not split across sibling modules. A new sibling module
│                             # (e.g. eustack_saturation.py) is a defensible alternative if eustack.py
│                             # is judged to be getting crowded — flag this choice explicitly in the
│                             # plan rather than deciding silently either way.
└── config.py                 # EXTEND EustackConfig with a nested thresholds table, mirroring
                              # McmConfig/McmThresholdsConfig's [mcm.thresholds] shape exactly:
                              # [eustack.thresholds] unclassified_thread_pct, no_resolvable_frame_pct,
                              # lock_convergence_count (ThresholdPair-shaped where it's a ratio,
                              # a bare warn/critical int pair for the count).
tests/
└── test_eustack_rules.py     # EXTEND (or a new tests/test_eustack_saturation.py sibling, matching
                              # whichever module-split choice is made above) with pool/lock/dependency/
                              # flag tests, reusing the existing _thread_raw()/_event() helpers.
```

### Pattern 1: Grouping over an already-classified tuple (EUS-03, EUS-05)

**What:** A single pass over `EustackAnalysis.signatures`, bucketing by `subsystem`, tallying
`thread_count` and `signature_count` per bucket — the exact shape `threads_by_role`/`signatures_by_role`
already use in `analyse_eustack`.

**When to use:** Both EUS-03 (all signatures, bucket by subsystem, split idle-parked vs everything-else
within each bucket) and EUS-05 (filter to `role == "blocked-on-external"` first, then bucket by
subsystem).

**Example:**
```python
# Source: mirrors sift/pipeline/eustack.py's existing threads_by_role accumulation pattern
from collections import defaultdict

pool_totals: dict[str | None, int] = defaultdict(int)
pool_idle: dict[str | None, int] = defaultdict(int)
for group in analysis.signatures:
    pool_totals[group.subsystem] += group.thread_count
    if group.role == "idle-parked":
        pool_idle[group.subsystem] += group.thread_count
```

Note `group.subsystem` is `None` for `unclassified` groups (D-02) — the dict key type must be
`str | None` and the `unclassified` row must be reported, never dropped, mirroring D-02's own wording.

### Pattern 2: The D-04 enclosing-frame walk (EUS-04)

**What:** Starting at `frame_index + 1` (walking toward the OUTER/entry-point end of the frames tuple —
see Research Question 2 for the index-direction proof), scan forward for the first frame that is both
resolvable (`_is_resolvable`) and contains `"::"`. `SignatureGroup.frames` entries are **already
normalised** (`signature_of()` applies `normalise()` before storing) — do not re-normalise inside the
walk.

**When to use:** Only for `SignatureGroup`s with `role == "blocked-on-lock"` (structurally the only role
whose `frame_index` is guaranteed non-`None`, since `classify_signature` only sets `frame_index` when a
rule matched).

**Example:**
```python
# Source: derived from sift/pipeline/eustack.py's _is_resolvable() and the D-04 wording
def _find_enclosing_frame(frames: tuple[str, ...], frame_index: int) -> str | None:
    """D-03/D-04: the first resolvable, '::'-qualified frame ABOVE frame_index.

    `frames` entries are already normalise()'d (signature_of() applies it), so no
    re-normalisation happens here. Returns None when no such frame exists — the
    caller reports this as unknown-but-counted (D-04), never drops the thread and
    never attributes it to the leaf.
    """
    for frame in frames[frame_index + 1 :]:
        if _is_resolvable(frame) and "::" in frame:
            return frame
    return None
```

### Pattern 3: Fixed declared-order flags, not a sorted list (Success Criterion 5)

**What:** `compute_flags` in `mcm.py` appends flags in the fixed order its checks are written in the
source — it does not sort them at construction time (sorting for display order is `mcm_facts.py`'s job,
at render time, via `_SEVERITY_ORDER`). Phase 16 should mirror this: three checks, appended in a fixed,
authored order (unclassified-share check, then no-resolvable-frame check, then lock-convergence check).
This needs no sort key and is trivially deterministic — the same discipline as the `_ALL_ROLES` tuple in
`eustack.py`.

**When to use:** Building `SaturationAnalysis.flags`. If lock convergence produces **one flag per
over-threshold site** (plural), that sub-list needs its own explicit sort key — reuse the same
`(-thread_count, site)` key the `lock_sites` list itself uses (see Determinism section).

### Anti-Patterns to Avoid

- **Re-normalising frames inside the D-04 walk:** `SignatureGroup.frames` is already `normalise()`'d.
  Calling `normalise()` again is redundant and risks silently masking a future normalisation bug (two
  code paths that should agree but are never actually compared).
- **Forcing the lock-convergence count into `DiagnosticFlag.value_pct`:** violates that field's own
  documented "always a ratio" contract. See Research Question 1.
- **A hidden allowlist of "real" pools:** D-01 explicitly forbids this — `compute`, `lock`, and
  `cube-generation` subsystems get an occupancy row too, even though the figure means little in isolation.
- **`Counter.most_common()` for any of the three new orderings (pools, lock sites, dependencies):** its
  tie behaviour is unspecified; `analyse_eustack` already avoids it for exactly this reason. Every new
  list needs an explicit `sort(key=...)` with a named tie-break.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Two-cut-point info/warn/critical grading | A second `_grade`-shaped comparator | Import `mcm._grade` directly (pure, stateless, takes any float — doesn't care whether the value is a ratio or a count) | Identical logic already shipped, tested, and D-08 explicitly names it. See Research Question 1 for the exact import shape. |
| Frame-line splitting / condensing | A second frame regex | `iter_frames`/`_condense_symbol` (already imported by `eustack.py` from `adapters/eustack.py`, D-08 "shared, not copied") | Phase 16 never needs to touch raw frame text directly — it only ever reads the already-`SignatureGroup.frames` tuple, which is already split and normalised |
| Resolvable-frame test | A second `??`/bare-address regex | `eustack.py::_is_resolvable()` (same module, import or call directly since Phase 16 likely lives in the same file) | One definition of "no symbol resolved here" for the whole eu-stack path |

**Key insight:** every piece of frame-level machinery this phase needs (splitting, normalising,
resolvability) was already built and tested in Phase 15. The only genuinely new logic is the upward walk
itself (Pattern 2 above) and the three grouping passes (Pattern 1) — both are a few lines of pure Python
over data structures that already exist.

## Runtime State Inventory

Not applicable — this is not a rename/refactor/migration phase. No stored data, live service config,
OS-registered state, secrets, or build artefacts are touched. `EustackAnalysis` (D-10) is explicitly
**unchanged**; Phase 16 only adds new symbols alongside it.

## Common Pitfalls

### Pitfall 1: Forcing `DiagnosticFlag.value_pct` to double as a raw count

**What goes wrong:** D-08 says "reuse `DiagnosticFlag`," but its `value_pct` field is documented as
"ALWAYS a ratio `part / whole * 100` — never an absolute GB." D-07's third flag (lock convergence, "thread
count at a single site above a configured count") is a raw count, not a ratio.

**Why it happens:** D-08 was written before the count-vs-ratio mismatch in D-07's own third bullet was
cross-checked against `DiagnosticFlag`'s locked contract.

**How to avoid:** `perfmon.py` already solved this exact problem for its own hazards — read its
`PerfmonHazard` docstring (`src/sift/pipeline/perfmon.py:118-131`) verbatim before deciding. Recommended
resolution: reuse `_grade()` (the pure comparator) for all three flags; reuse `DiagnosticFlag` verbatim
for the two true ratios; mint one small sibling record (generic `value: float`, not `value_pct`) for the
count-based flag, or — simpler still, since D-10 already mandates one new model file anyway — define a
single new flag record used by all three, with a generic field name, so the type never lies about its own
semantics.

**Warning signs:** a test or docstring asserting "value_pct is always 0-100" would fail against the lock
flag if this is not resolved before implementation.

### Pitfall 2: Walking the frame tuple in the wrong direction

**What goes wrong:** "Enclosing frame" and "walking up" both intuitively suggest walking toward LOWER
indices (toward the top/leaf of a printed stack trace). In this codebase's frame numbering, index 0 is the
**deepest/leaf** frame (`#0` in eu-stack output) and increasing index walks toward the **thread entry
point** — confirmed directly in the shipped tracer test (`test_eustack_rules.py:33-47`): `#0
pthread_cond_timedwait` (leaf) ... `#3 MSIQTask::GetNextPreferredJob` (the classifying/enclosing frame)
... `#4 MSIThread::Run()` (entry point). "Walking up from `frame_index`" therefore means iterating
`frame_index + 1, frame_index + 2, ...` — **increasing** index, not decreasing.

**Why it happens:** "up the stack" is ambiguous English; eu-stack's own `#N` numbering is the opposite of
some other tools' conventions (e.g. some debuggers number frame 0 as "innermost" too, but a reader
unfamiliar with THIS adapter's specific frame order could still get it backwards).

**How to avoid:** the tracer test above is the canonical worked example — cite it directly in the new
helper's docstring and in its own unit test.

**Warning signs:** a lock fixture where the expected enclosing frame comes back as `None` or as a glibc
symbol when a real application frame exists further along the tuple.

### Pitfall 3: The `std::`/`boost::` misfire on `contains("::")`

**What goes wrong:** D-04's own rationale states "MicroStrategy code is uniformly C++-namespaced; glibc/
pthread is C and unqualified" — true for glibc, but **C++ runtime library frames also contain `::`** and
are not MicroStrategy application code. This is not hypothetical: the shipped
`reference_capture_derivative.txt` fixture contains real examples of exactly this stack shape, e.g. (lines
114-117):
```
#0  __futex_abstimed_wait_common
#1  pthread_cond_wait@@GLIBC_2.3.2
#2  std::condition_variable::wait(std::unique_lock<std::mutex>&)
#3  ParallelBursting::ThreadPool::WorkLoop(unsigned long)
```
If a `__lll_lock_wait`-matching rule fired at frame `#0` or `#1` of a stack shaped like this, the D-04 walk
as literally specified would stop at frame `#2` (`std::condition_variable::wait`, a libstdc++ runtime
frame — it does contain `::`) rather than continuing to frame `#3`
(`ParallelBursting::ThreadPool::WorkLoop`, the genuine MicroStrategy enclosing frame). The same shape
recurs with `boost::asio::detail::scheduler::*` frames at lines 89-91, 97-101, 107-109 of the same
fixture.

**Why it happens:** `contains("::")` cannot distinguish "MicroStrategy namespace" from "any C++ namespace,"
and CONTEXT.md's D-04 rationale explicitly **rejected** a runtime-prefix denylist (`std::`, `boost::`,
`__gnu_cxx::`) as "a second authored vocabulary living in Python rather than the TOML, which will drift
across build variants."

**How to avoid:** this is not a bug to fix silently — it is a known, accepted imprecision consistent with
ADR 0015's own precedent (the ADR documents a similar single-thread misclassification as "known ... not
silently fixed or silently accepted," i.e. recorded openly). The plan should: (1) implement the walk
exactly as D-04 specifies (no denylist — that is a locked decision), (2) add a test using a synthesised
stack shaped like the real `std::condition_variable::wait` → `ParallelBursting::ThreadPool::WorkLoop`
example above, asserting the walk's actual (imprecise but D-04-compliant) behaviour, so future
maintainers see the limitation exercised in CI rather than discovering it by surprise, and (3) note the
limitation in the module docstring next to the walk helper, citing this exact fixture evidence.

**Warning signs:** a lock-convergence report where the "site" column is dominated by generic
`std::mutex::lock`/`boost::asio::...` entries rather than MicroStrategy call sites — a real signal this
imprecision is materially affecting the report, worth revisiting (but not blocking Phase 16).

### Pitfall 4: `None` vs `str` in a sort key for lock sites

**What goes wrong:** D-04's "unknown-but-counted" outcome means `LockSite.site` (or equivalent field) can
legitimately be absent. Sorting a list of `(thread_count, site)` tuples where `site` is sometimes `None`
and sometimes `str` raises `TypeError` in Python 3 (`None` and `str` are not orderable against each
other).

**How to avoid:** never leave the field as `Optional` in the sortable/orderable sense — populate a fixed
sentinel string (e.g. `"<no application frame found>"`) for the unknown case at construction time, exactly
as D-04 itself demands ("reported as unknown-but-counted, never dropped"). The field can still be typed
`str` (not `str | None`) if the sentinel is always substituted before the model is built.

### Pitfall 5: Double-counting or dropping `unclassified` in the pool denominator

**What goes wrong:** D-02 requires `unclassified` threads (subsystem=`None`) to be counted as their own
row and never folded into any subsystem's denominator. A naive `groupby(subsystem)` that silently
coalesces `None` keys with an existing bucket (e.g. via `str(subsystem)` coercion producing `"None"` that
collides with a literal `"None"` subsystem string) would violate this.

**How to avoid:** keep the dict key typed `str | None` throughout, never stringify it before the final
render step, and add a test asserting the `None`-keyed row's `thread_count` matches
`EustackAnalysis.threads_by_role["unclassified"]` exactly.

## Code Examples

### Grading a flag with the imported `_grade` helper

```python
# Source: sift/pipeline/mcm.py:609-624 (reused verbatim, not re-derived)
from sift.pipeline.mcm import (
    _grade,  # pyright: ignore[reportPrivateUsage] — imported, never redeclared, mirrors the
             # existing _condense_symbol/_RESERVED_ATTRS/_DRIFT_ATTR cross-module reuse pattern
             # already established in eustack.py and perfmon.py (D-08's "shared, not copied" rule).
)

unclassified_pct = round(unclassified_threads / total_threads * 100, 1) if total_threads else 0.0
severity = _grade(unclassified_pct, warn=thresholds.unclassified_thread_pct.warn,
                   crit=thresholds.unclassified_thread_pct.critical)
```

### Threshold config shape (extends `EustackConfig`)

```python
# Source: mirrors sift/config.py's McmThresholdsConfig/ThresholdPair/McmConfig nesting exactly
class EustackThresholdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unclassified_thread_pct: ThresholdPair = ThresholdPair(warn=5.0, critical=15.0)
    no_resolvable_frame_pct: ThresholdPair = ThresholdPair(warn=5.0, critical=15.0)
    lock_convergence_count: ThresholdPair = ThresholdPair(warn=5.0, critical=20.0)


class EustackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules_path: str | None = None
    thresholds: EustackThresholdsConfig = EustackThresholdsConfig()
```

`ThresholdPair` is reused as-is (it is just `{warn: float, critical: float}`) even for the count-based
threshold — `_grade()` compares floats regardless of what they represent, so no new pair type is needed.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| "Identical stack after N seconds = stuck thread" | Composition-based classification (Phase 15) | Falsified during v1.3 scoping (98.9% false-positive on a healthy server) | Phase 16 builds strictly on the composition signal; no motion-based check may be reintroduced (STATE.md decision log) |

No external "state of the art" applies here — this is entirely internal aggregation logic over an
already-shipped internal model, not a domain with an evolving external ecosystem.

**Deprecated/outdated:** N/A.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default thresholds `unclassified_thread_pct(warn=5.0, critical=15.0)` and `no_resolvable_frame_pct(warn=5.0, critical=15.0)` are non-arbitrary defaults chosen with margin over the measured healthy-capture figure (1.33% unclassified thread share, ADR 0015) but are not independently calibrated against a second real capture | Common Pitfalls / Code Examples | If the only available real capture is this one healthy sample, the "non-arbitrary" claim rests on a single data point; a second real capture (if one is ever obtained per REQUIREMENTS.md's "Known evidence gap") could show these defaults are too tight or too loose |
| A2 | The `no-resolvable-frame` share specifically (as opposed to the combined `unclassified` share) has not been separately measured against the real 3,902-thread capture — only the combined `unclassified` figure (52 threads / 1.33%) is recorded in ADR 0015; the `no-resolvable-frame` vs `matched-no-rule` split within that 52 is not reported anywhere in Phase 15's artifacts | Research Question 3 / thresholds | The recommended default (same warn/critical pair as flag 1, since it is mathematically a subset bounded by 1.33%) is safe for D-09's "zero flags" gate regardless, but is not independently calibrated to the real sub-figure |
| A3 | Lock-convergence default thresholds (`warn=5, critical=20` threads at one site) are round, conservative starting points with **zero calibration data** — no real hung-server capture exists (REQUIREMENTS.md "Known evidence gap"), and the healthy capture matches the lock rule zero times, so D-09's gate is trivially satisfied by any positive threshold | Code Examples / Pitfall 1 | These numbers should be treated as a placeholder needing the D-11 synthetic fixture to exercise multiple counts (e.g. 3/8/25 threads) rather than as calibrated, evidence-backed defaults |
| A4 | The recommendation to extend `eustack.py` in place (rather than a new sibling module) is a reading of CONTEXT.md's "the established precedent is executable code in `src/sift/pipeline/eustack.py` mirroring `mcm.py`/`perfmon.py`" combined with the observation that `mcm.py`/`perfmon.py` each keep their whole domain in one file — not an explicit instruction | Recommended Project Structure | If the planner judges `eustack.py` (currently 374 lines) would become too large or too mixed-concern with Phase 16's additions, a sibling module is an equally valid, D-10-compliant choice; CONTEXT.md leaves this to discretion explicitly |

## Open Questions

1. **Should the D-04 walk live as a private helper inside the extended `eustack.py`, or be exported for
   direct unit testing?**
   - What we know: `_is_resolvable` (also D-07 machinery) is currently module-private with no public
     re-export, and is tested indirectly via `classify_signature`/`analyse_eustack`.
   - What's unclear: whether the plan wants the frame-walk helper directly unit-testable (recommended,
     given Pitfall 2's directionality risk) or only exercised through the full `analyse_saturation` path.
   - Recommendation: export it (no leading underscore) given its correctness is subtle enough (Pitfalls 2
     and 3) to warrant a direct, focused unit test independent of the full aggregation pipeline.

2. **Exact denominator for `no_resolvable_frame_pct` — all threads, or unclassified threads only?**
   - What we know: D-07 says "no-resolvable-frame share (missing symbols)" without specifying the
     denominator; flag 1 ("unclassified thread share") is unambiguous by comparison — total threads.
   - What's unclear: whether "share" here means share-of-total (consistent with flag 1, more directly
     actionable — "X% of the whole capture has no symbols at all") or share-of-unclassified (a breakdown
     of the residual bucket).
   - Recommendation: share-of-total, for consistency with flag 1's denominator and because it is the more
     operationally meaningful number; record this as an explicit decision at plan time since D-07's wording
     does not settle it.

## Environment Availability

Not applicable — this phase has no external tool, service, runtime, or CLI dependency beyond the Python
environment already required for the whole project (stdlib + pydantic, already verified present).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (version pinned in `uv.lock`; confirmed 9.1.1 during Phase 6 reconciliation per project history) |
| Config file | `pyproject.toml` (no dedicated `[tool.pytest.ini_options]` block found; default rootdir discovery from `tests/`) |
| Quick run command | `uv run pytest tests/test_eustack_rules.py -k saturation` (or the new sibling test file, once named) |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EUS-03 | Pool occupancy splits busy vs parked per subsystem; `unclassified` never folded into a pool | unit | `uv run pytest tests/test_eustack_rules.py -k pool_occupancy -x` | ❌ Wave 0 |
| EUS-03 | The reference-capture-derivative's `MSIQTask::GetNextPreferredJob` population reads as an idle pool (via the derivative fixture) | unit (fixture-based) | `uv run pytest tests/test_eustack_rules.py -k reference_derivative_occupancy -x` | ❌ Wave 0 (fixture already exists: `tests/fixtures/eustack/reference_capture_derivative.txt`) |
| EUS-04 | Lock-site walk finds the correct enclosing `::`-qualified frame above a `blocked-on-lock` leaf | unit | `uv run pytest tests/test_eustack_rules.py -k lock_site_walk -x` | ❌ Wave 0 |
| EUS-04 | No `::`-qualified frame above the leaf reports unknown-but-counted, never dropped | unit | `uv run pytest tests/test_eustack_rules.py -k lock_site_unknown -x` | ❌ Wave 0 |
| EUS-04 | Output vocabulary never contains "deadlock"/"owner"/"holder" (mirrors the shipped `test_no_ownership_attributed_lock_language_in_shipped_surface` pattern, extended to the new module) | unit | `uv run pytest tests/test_eustack_rules.py -k ownership_blind -x` | ❌ Wave 0 |
| EUS-05 | `blocked-on-external` threads split by verbatim `subsystem`, warehouse and HTTP separately visible | unit | `uv run pytest tests/test_eustack_rules.py -k dependency_split -x` | ❌ Wave 0 |
| EUS-05 | Reference-derivative reproduces 79 warehouse / 78 HTTP figures at full-capture verification time (not CI, since the derivative is capped) — CI half asserts the SPLIT exists and is non-merged | unit (fixture-based, CI half only) | `uv run pytest tests/test_eustack_rules.py -k reference_derivative_dependency -x` | ❌ Wave 0 |
| EUS-06 | `EustackAnalysis.signatures` is read directly, not re-derived | unit (a "no new code" assertion — could be a short integration test confirming `SaturationAnalysis` does not duplicate the signature list) | `uv run pytest tests/test_eustack_rules.py -k signature_passthrough -x` | ❌ Wave 0 |
| Success Criterion 5 | Every graded flag prints its raw computed value beside the configured threshold | unit | `uv run pytest tests/test_eustack_rules.py -k flag_value_and_threshold -x` | ❌ Wave 0 |
| Success Criterion 5 / D-09 | The healthy reference-derivative capture raises zero flags | unit (fixture-based, the real verification gate) | `uv run pytest tests/test_eustack_rules.py -k reference_derivative_zero_flags -x` | ❌ Wave 0 |
| D-11 | Synthetic lock-convergence scenario exercises the `blocked-on-lock` path (real capture never does) | unit (inline-constructed, see Research Question 5) | `uv run pytest tests/test_eustack_rules.py -k synthetic_lock_convergence -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_eustack_rules.py -k <new-test-name> -x`
- **Per wave merge:** `uv run pytest` (full suite — this phase touches shared config (`config.py`) and a
  shared module (`eustack.py`), so a full-suite run is cheap insurance against regressing Phase 15's
  shipped tests)
- **Phase gate:** Full suite green before `/gsd-verify-work`, plus `ruff check` and `pyright` clean
  (per CLAUDE.md's "done" definition)

### Wave 0 Gaps

- [ ] No new test file infra needed — `tests/test_eustack_rules.py` already exists with the exact
  `_thread_raw()`/`_event()`/`_parse_derivative_fixture()` helpers Phase 16's tests need (see Research
  Question 5). If a sibling module (`eustack_saturation.py`) is chosen instead, a new
  `tests/test_eustack_saturation.py` needs the same three helpers duplicated or imported.
- [ ] Framework install: none — pytest already present.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Library-only phase, no auth surface |
| V3 Session Management | No | No session concept in this phase |
| V4 Access Control | No | No access-control surface |
| V5 Input Validation | Yes | Extending `EustackConfig`/`SiftConfig` with new `[eustack.thresholds]` keys via strict Pydantic (`extra="forbid"`) — a typo'd threshold key fails loudly at config-load time, exactly as every other config section already does (T-04-02 convention) |
| V6 Cryptography | No | No cryptographic material introduced |
| V11 Business Logic | Yes | The ownership-blind vocabulary constraint (D-05) is a business-logic invariant enforceable the same mechanical way Phase 15 enforces it: `test_no_ownership_attributed_lock_language_in_shipped_surface` reads the forbidden term from `REQUIREMENTS.md` at runtime and asserts it appears nowhere in the new module's source — that pattern should be extended (or reused verbatim if the new code lives inside `eustack.py`) to cover Phase 16's additions |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent misclassification presented as authoritative (e.g. a `std::`/`boost::` frame reported as "the" MicroStrategy call site, Pitfall 3) | Repudiation-adjacent (an engineer could act on a misleading root-cause site with no way to tell it's imprecise) | Not a traditional security threat, but the same repudiation-class control Phase 15 already applies (T-15-11: two distinct reason codes so a symbols-missing problem is never mistaken for a rules-drift problem) — document the D-04 walk's known imprecision plainly in output/docs rather than presenting it as ground truth |
| Config typo silently reverting to a wrong default threshold | Tampering/availability (a curator believes they raised a threshold; a typo means the old default silently still applies) | `extra="forbid"` on the new `EustackThresholdsConfig`/`EustackConfig` nesting — a typo'd key raises `ValidationError` at load time, never silently ignored (same mitigation already used across every `SiftConfig` section) |

## Sources

### Primary (HIGH confidence — direct repository reads this session)

- `src/sift/pipeline/eustack.py` — full read: `Role`, `RuleRole`, `Reason`, `Rule`, `Classification`,
  `SignatureGroup`, `EustackAnalysis`, `normalise()`, `signature_of()`, `_is_resolvable()`,
  `classify_signature()`, `analyse_eustack()`
- `src/sift/rules/eustack_roles.toml` — all 24 shipped rules, subsystem values, rule 6 (`__lll_lock_wait`)
- `src/sift/pipeline/mcm.py` — `DiagnosticFlag` (lines 219-234), `_grade()` (lines 609-624)
- `src/sift/pipeline/perfmon.py` — `PerfmonHazard` (lines 118-135) and its explicit "why `DiagnosticFlag`
  is not reused" docstring; `_hazard_non_overlap` (lines 380-398) as a second confirming instance
- `src/sift/config.py` — `EustackConfig`, `McmThresholdsConfig`, `ThresholdPair`, `McmConfig`,
  `SiftConfig`, `_ENV_SCALARS`
- `src/sift/adapters/eustack.py` — `iter_frames()`, `_condense_symbol()`, `_TID_RE`, `_FRAME_RE`,
  `CONDENSED_FRAMES`
- `src/sift/pipeline/mcm_facts.py` — full read, the render-time-consumption contract precedent for
  `SaturationAnalysis`'s downstream shape
- `tests/fixtures/eustack/derive_reference_capture_derivative.py` — the fixture provenance-tool
  convention, `build_preamble()`
- `tests/fixtures/eustack/reference_capture_derivative.txt` — real evidence for Pitfall 3 (lines 68,
  89-91, 97-101, 107-109, 114-117)
- `tests/test_eustack_rules.py` — full read, existing test helpers (`_thread_raw`, `_event`,
  `_parse_derivative_fixture`) and the `test_no_ownership_attributed_lock_language_in_shipped_surface`
  pattern
- `docs/decisions/0015-eustack-thread-role-taxonomy.md` — full read, day-one coverage figures (98.67%
  thread / 56.99% signature, 52 unclassified threads), the shared-ancestor ordering trap, D-05's refined
  normalisation rule
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/config.json`,
  `.planning/phases/16-saturation-contention-signature-collapse/16-CONTEXT.md` — full reads

### Secondary (MEDIUM confidence)

None — every claim in this document traces to a direct repository read this session; there was no need
for external web search or documentation lookup (pure internal-aggregation phase, stdlib + already-vetted
pydantic only).

### Tertiary (LOW confidence)

None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, every reused symbol read directly from source this session
- Architecture: HIGH — every pattern (grouping, frame walk, flag grading) is derived from shipped,
  tested code in this exact repository
- Pitfalls: HIGH — Pitfall 3 (std::/boost:: misfire) is backed by concrete line numbers in a committed
  fixture, not a hypothetical

**Research date:** 2026-07-25
**Valid until:** No external dependency drift risk (stdlib + internal code only) — this research stays
valid until Phase 15's shipped `eustack.py`/`eustack_roles.toml` change, which is not anticipated.
