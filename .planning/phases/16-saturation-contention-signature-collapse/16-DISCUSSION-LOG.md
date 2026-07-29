# Phase 16: Saturation, Contention & Signature Collapse - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-25
**Phase:** 16-saturation-contention-signature-collapse
**Areas discussed:** Pool key, Lock convergence grouping key, External-wait dependency labels, Graded flags, Enclosing-frame identification, Lock fixture strategy, Output shape

---

## Pool key (EUS-03)

| Option | Description | Selected |
|--------|-------------|----------|
| subsystem | Pool = the rule's `subsystem` string; no new data; exactly why `subsystem` was made mandatory in Phase 15. Cost: `compute`/`lock` get a near-meaningless occupancy row. | ✓ |
| subsystem, pool-flagged in TOML | Add an optional `pool = true` marker so only genuine worker pools get an occupancy row. Costs a schema change + re-validation of all 24 rules. | |
| Signature prefix clustering | Derive pools from shared stack-frame prefixes. Model-free, no curation — but a heuristic with a tuning knob. | |

**User's choice:** subsystem
**Notes:** Scouting confirmed `Event.thread` is a bare TID (`TID <n>:`) — eu-stack carries no thread names, so a naming-convention-based pool key was never available. The meaningless-row consequence is accepted and reported uniformly rather than special-cased.

---

## Lock convergence grouping key (EUS-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Enclosing application frame | Same key as Phase 15's role classification — the first non-glibc frame above `__lll_lock_wait`. Reuses the existing frame walk; consistent with ADR 0015 (leaf = mechanism, enclosing frame = meaning). | ✓ |
| Leaf symbol only | Group by `__lll_lock_wait`/`pthread_mutex_lock` alone. Cheap, matches the one sound single-leaf signal — but collapses every unrelated lock into one number. | |
| Full signature | Each distinct signature is its own site; zero new logic. Precise but fragments a real 40-thread convergence into 6 sites of 5–9. | |

**User's choice:** Enclosing application frame
**Notes:** Confirmed during scouting that the shipped Rule 6 matches `__lll_lock_wait` via `match = "contains"`, so `frame_index` points at glibc, not at MicroStrategy code — the site must be walked to, which promoted the follow-up question below.

---

## External-wait dependency labels (EUS-05)

| Option | Description | Selected |
|--------|-------------|----------|
| subsystem verbatim | Dependency = the `subsystem` of blocked-on-external threads. No mapping layer, no second vocabulary. Consequence: the TOML curator owns the report's dependency axis. | ✓ |
| Curated mapping in Python | A separate `subsystem -> dependency` table so the axis stays stable. Costs a second edit site per rule; re-opens the coupling ADR 0015 closed. | |
| New `dependency` field in TOML | Rules carry both `subsystem` and an explicit `dependency`. Most precise; a third label per rule and a schema migration across 24 rules. | |

**User's choice:** subsystem verbatim
**Notes:** The curator-owns-the-axis coupling is deliberate — same single-source-of-truth property ADR 0015 chose. A `dependency` field is recorded as a deferred idea if `subsystem` later proves too fine-grained.

---

## Graded flags (Success Criterion 5)

| Option | Description | Selected |
|--------|-------------|----------|
| Composition-only flags | Flag only quantities with a non-arbitrary zero point: unclassified share, no-resolvable-frame share, lock convergence count. No occupancy-percentage flag. Healthy capture raises zero by construction. | ✓ |
| Add occupancy thresholds too | Also flag per-pool occupancy with permissive defaults. More immediately useful — but authors exactly the percentages EUSV2-03 deferred. | |
| No flags this phase | Report every figure raw, defer grading to Phase 17. Smallest diff — but Success Criterion 5 explicitly requires graded flags here. | |

**User's choice:** Composition-only flags
**Notes:** Adding an occupancy flag later is additive; removing a shipped wrong threshold is not. Zero-flags-on-the-healthy-capture is treated as a verification gate on the defaults, not an aspiration.

---

## Enclosing-frame identification (follow-up to EUS-04)

| Option | Description | Selected |
|--------|-------------|----------|
| First `::`-qualified frame | Walk up from `frame_index` to the first resolvable frame whose normalised symbol contains `::`. MicroStrategy is uniformly C++-namespaced; glibc is C and unqualified. Zero authored data; mirrors ADR 0013's qualified-name anchoring. | ✓ |
| Runtime-prefix denylist | Walk past a curated list (`__`, `pthread_`, `std::`, `boost::`). Explicit and tunable — but a second authored vocabulary in Python that will drift across builds. | |
| Fixed offset (`frame_index + 1`) | Take the next frame up. Smallest diff; wrong whenever glibc has more than one frame between the futex wait and our code — the normal case. | |

**User's choice:** First `::`-qualified frame
**Notes:** The "no qualified frame exists above the leaf" case must be handled explicitly — reported as unknown-but-counted, never dropped and never attributed to the leaf.

---

## Lock fixture strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-authored synthetic fixture | A small eu-stack fixture with N threads converging on one `__lll_lock_wait` site. The only way to exercise the code path; makes Success Criterion 2 testable. | ✓ |
| Structural test only | Test the grouping function on constructed `SignatureGroup` objects, no fixture file. Cheapest, proves the logic — but nothing exercises adapter-to-analysis end to end. | |
| Ship untested against real shape | Defer validation until a contended capture arrives. Leaves a load-bearing path with no coverage. | |

**User's choice:** Hand-authored synthetic fixture
**Notes:** Raised during discussion: the healthy reference capture matches the lock rule **zero** times by design (see the Rule 6 comment in `eustack_roles.toml`), so no real capture can validate EUS-04. The fixture must carry a provenance header marking it clearly synthetic — it is not a redacted real capture, unlike the existing `tests/fixtures/eustack/` derivatives.

---

## Output shape

| Option | Description | Selected |
|--------|-------------|----------|
| New `SaturationAnalysis` model | A separate frozen model consuming `EustackAnalysis`. Keeps Phase 15's model unchanged; gives Phase 17 one clear thing to render alongside the signature collapse. | ✓ |
| Extend `EustackAnalysis` | Add fields to the existing model — simpler call sites, but mutates a shipped `frozen=True` / `extra="forbid"` model pinned by Phase 15's tests, and blurs classification with analysis. | |

**User's choice:** New `SaturationAnalysis` model
**Notes:** Rated `costly` to reverse in CONTEXT.md D-10 — merging the models later would churn Phase 15's shipped tests.

---

## Claude's Discretion

- Exact model and field names (`SaturationAnalysis`, `PoolOccupancy`, `LockSite`, `DependencyWait`) and their module placement.
- Whether the three flag families share one `DiagnosticFlag` list or separate fields.
- Default threshold values, subject to zero flags on the healthy reference capture.
- Plan/task decomposition and wave structure.

## Deferred Ideas

- Graded saturation percentage thresholds (EUSV2-03) — deferred by the roadmap, reaffirmed as D-07.
- A `pool = true` marker in the rules file — revisit only if the Phase 17 report reads badly with `compute`/`lock` occupancy rows present.
- A separate `dependency` field per rule — revisit only if `subsystem` proves too fine-grained in practice.
- Reviewed but not folded: `2026-07-21-embedding-batch-composition-determinism.md` (already SEED-002/DET-01, Phase 20) and `2026-07-21-generation-context-unset.md` (LLM config; Phase 16 is model-free).
