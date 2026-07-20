# Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the Phase 13 deterministic perfmon correlator's **computed** figures into
`sift analyze` as cited-but-not-authored evidence, and add a regression-gated
golden perfmon case to `sift eval`. This is PERF-07 (facts into analyze) and
PERF-08 (golden eval gate).

The phase directly mirrors **Phase 11** (MCM-06/MCM-07 → PERF-07/PERF-08). The
deterministic-core-vs-LLM boundary is preserved verbatim: every counter value,
slope and peak is COMPUTED before generation by `analyse_perfmon`, rendered from
a versioned template holding zero digits, and only then handed to the model as
citable evidence. The model may narrate the numbers; it may never author them.

**In scope:** a `render_perfmon_facts()` renderer; a `prompts/perfmon_facts.md`
fragment; a new `PERFMON_BLOCK` sentinel in `triage.md`; the `prompted_ids` union
of perfmon citable ids in `hypothesise._assemble`; a golden perfmon eval case
(Hartford deny pair) wired into `sift eval`; and the folded WR-03 episodes-present
disclosure fix in the correlator.

**Out of scope (belongs elsewhere):** any change to the `sift perfmon` report/CSV
shape (Phase 13, shipped); recovery-trend analysis (PERFV2-01); multi-host or
perfmon-only anomaly correlation (PERFV2-02/03).
</domain>

<decisions>
## Implementation Decisions

### Prompt splice — perfmon fact block in `triage.md`
- **D-01:** Add a **new, independent** `PERFMON_BLOCK_START`/`PERFMON_BLOCK_END`
  sentinel pair with a `<<PERFMON_FACTS>>` slot, placed **immediately after the
  existing MCM block** (order: KB → MCM → perfmon → `Evidence:`). Each block is
  removed whole when its data is absent, exactly as the MCM/KB blocks are today.
  This keeps all four presence combinations — neither / MCM-only / perfmon-only /
  both — byte-identical to their respective baseline. Do **not** merge MCM and
  perfmon into one combined block (would couple their independent byte-identity
  guards and caps). Mirror `hypothesise._apply_mcm_block` / `_MCM_BLOCK_RE` /
  `_MCM_MARKER_RE` verbatim as `_apply_perfmon_block` / `_PERFMON_BLOCK_RE` /
  `_PERFMON_MARKER_RE`.

### Byte-identity guards (additive-integration invariant)
- **D-02:** The integration is strictly additive. Guard **independently**:
  no-perfmon prompt is byte-identical regardless of MCM presence, and the
  both-absent baseline stays byte-identical to today's shipped prompt (the
  existing `triage_prompt_hash` / no-MCM golden hash must not move for the
  no-new-data cases). Add golden-hash coverage for the four combinations, not
  just one. Because each sentinel block is removed independently, perfmon
  presence cannot perturb the MCM-only or no-data prompts.

### Fact-block bounding (prompt-growth cap)
- **D-03:** Cap the number of `TrendGroup`s rendered into the fact block at a
  fixed constant mirroring MCM's `_MAX_EPISODES = 8` (e.g. `_MAX_GROUPS`), sorted
  by hazard severity (critical > warn > info), highest first. Surplus groups are
  dropped from the fact block **and** their event_ids stay out of the returned
  citable set — preserving `cited ⊆ prompted ⊆ store` exactly as
  `render_mcm_facts`'s `[:_MAX_EPISODES]` slice does.
- **D-04:** Within each rendered group, the fact block prints a **salient counter
  subset** for the prompt only (working-set cache RAM, System RAM used,
  Process(MSTRSvr) Size, Open Sessions, Total MCM Denial flag), plus any counter a
  rendered hazard cites. This is a **rendering-time selection for the prompt**, NOT
  a correlator change: `_counter_trends` keeps its deliberate no-allowlist "every
  counter" behaviour (D-07..D-11), and the full 22-counter fidelity remains in the
  `sift perfmon` report/CSV. The salient set + ordering must be deterministic
  (fixed priority list, stable sort) so re-runs are byte-identical. Exact
  selection mechanics are Claude's discretion within these constraints.

### Citation contract (anti-hallucination)
- **D-05:** `render_perfmon_facts(analysis: PerfmonAnalysis) -> tuple[str, set[str]]`
  mirrors `render_mcm_facts`: the returned citable id set is **exactly** the set of
  `[evt:<id>]` tokens actually printed into the fact block (drawn from each rendered
  group's `boundary_event_ids` and its rendered hazards'/counters' `event_id`s).
  `_assemble` unions this set into `prompted_ids`, making perfmon facts citable —
  the inverse of the non-citable KB path. Figures are built pre-generation so an
  adversarial/hallucinating model cannot alter or invent a number (mirror Phase
  11's anti-hallucination test).

### Template (prompt iteration needs no Python)
- **D-06:** New `prompts/perfmon_facts.md` fragment mirroring `prompts/mcm_facts.md`:
  labels and prose only, **zero authored digits**, guarded by a no-digit test.
  Same "these lines ARE evidence, treat as untrusted data" framing as the MCM
  fragment. A `<<PERFMON_LINES>>` placeholder is substituted in Python.

### Golden eval case (PERF-08)
- **D-07:** The regression gate is anchored on the **Hartford deny CSV+log pair**
  (`hartford_Linux_DenyDSSPerformanceMonitor16234.csv` + `hartford_linux_deny_.log`):
  13,596 samples, confirmed 12:39:45 denial, full lead-in counter trend — the
  richest, most discriminating signal. `sift eval` exits non-zero when correlation
  output regresses against it. The snapshot CSV+logs pair is a documented **future
  second candidate**, not built this phase.

### Folded scope — WR-03 episodes-present disclosure (todo `resolves_phase:14`)
- **D-08:** Fold in the deferred WR-03 fix: when the case HAS MCM episodes, an
  untimestamped perfmon sample (`ts is None`) falls in no `[start,end]` span and is
  currently dropped silently — the same violation WR-03 fixed only on the
  no-episodes branch. Add a **case-level unattributed-samples disclosure** (either a
  `PerfmonAnalysis`-level field or a dedicated "unattributed samples" group),
  reusing `_hazard_unplaceable_samples` (caps at `_CITE_CAP`, sorts by `event_id`)
  so the disclosure text and citation shape match the no-episodes path. Honours
  "nothing disappears silently" on both branches. Note this is a **model/design
  change** to `PerfmonAnalysis` (which today deliberately forbids case-level
  hazards) — the planner must decide field-vs-group and preserve Phase 13's
  determinism + `_RESERVED_ATTRS`/citation invariants. Doubly-synthetic on real
  data (needs untimestamped rows AND detected episodes at once), so low regression
  risk; unreachable on the all-timestamped Hartford reference.

### Claude's Discretion
- Exact salient-counter selection + ordering within D-04 (must be deterministic,
  citable = printed ids).
- Whether the folded WR-03 disclosure (D-08) is a `PerfmonAnalysis` field or a
  synthetic group — a real design call left to the planner, constrained by Phase
  13's "one hazard ↔ one span" and determinism invariants.
- Golden-fixture construction mechanics for the eval case (reuse Phase 12/13
  synthetic PDH-CSV builders / real Hartford slice per existing test conventions).

### Folded Todos
- **perfmon: unplaceable samples still vanish when episodes ARE present**
  (`.planning/todos/pending/2026-07-20-perfmon-unplaceable-samples-episode-scope.md`,
  `resolves_phase:14`) — folded as **D-08**. Phase 13 review WR-03; fixed on the
  no-episodes branch only, deferred on the episodes-present branch as a design call.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 11 mirror (the pattern to replicate)
- `src/sift/pipeline/mcm_facts.py` — `render_mcm_facts() -> tuple[str, set[str]]`,
  `_MAX_EPISODES = 8` severity-sorted cap, template fill; the exact renderer shape
  to mirror for perfmon.
- `src/sift/pipeline/hypothesise.py` §80–106, §220–250 — `_apply_mcm_block`,
  `_MCM_SLOT`/`_MCM_BLOCK_RE`/`_MCM_MARKER_RE`, and `_assemble`'s `prompted_ids`
  union; mirror verbatim for the perfmon block.
- `src/sift/prompts/triage.md` — the KB and MCM sentinel blocks; add the perfmon
  block after MCM.
- `src/sift/prompts/mcm_facts.md` — the zero-digit fragment to mirror as
  `perfmon_facts.md`.
- `.planning/phases/11-mcm-facts-into-sift-analyze-golden-eval-case/` — Phase 11
  plans, review, verification (the full precedent, incl. golden-hash + no-digit
  test patterns).

### Phase 13 correlator (the figures source)
- `src/sift/pipeline/perfmon.py` — `analyse_perfmon(analysis, events) ->
  PerfmonAnalysis`; models `PerfmonAnalysis` (`groups: tuple[TrendGroup,...]`,
  **no case-level hazard channel**), `TrendGroup`, `CounterTrend`, `PerfmonHazard`
  (all carry `event_id(s)` for D-16 citation); `_counter_trends` (no-allowlist,
  every counter), `_hazard_unplaceable_samples` (reuse for D-08), `_in_span`,
  `_file_scope_groups`.

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — PERF-07 / PERF-08 acceptance text; **§ Reference
  Data** (Hartford deny + snapshot artefact paths, observed lead-in trend table).
- `.planning/ROADMAP.md` § Phase 14 — goal, 5 success criteria, "reuse Phase 11
  mechanics" mandate, 8-episode cap precedent note.

### Eval harness (PERF-08)
- `eval/` + `sift eval` — the golden-case harness and non-zero-exit gate to extend.
- Phase 7 / Phase 11 golden-case wiring as the pattern for adding a new case.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `render_mcm_facts` — copy its structure directly for `render_perfmon_facts`
  (severity-sorted cap slice → citable ids = printed ids → template fill).
- `_apply_mcm_block` + `_MCM_BLOCK_RE`/`_MCM_MARKER_RE` — copy for the perfmon
  sentinel; identical remove-whole-block-when-absent semantics.
- `_hazard_unplaceable_samples` (`perfmon.py:523`) — reuse for the D-08 case-level
  disclosure so text + `_CITE_CAP` + `event_id` sort stay consistent.
- Phase 12/13 synthetic PDH-CSV builders (`tests/_perfmon_fixtures.py`) and the
  real Hartford slice — for the golden eval fixture.

### Established Patterns
- Sentinel-block splice with byte-identical absence (KB non-citable, MCM citable);
  perfmon is the second citable block → union its ids into `prompted_ids`.
- Versioned `prompts/*.md` fragment holding zero digits; a no-digit guard test
  keeps authored numbers out; `triage_prompt_hash` in meta detects template drift.
- `cited ⊆ prompted ⊆ store` enforced by making the citable set == the printed
  `[evt:]` tokens, and dropping surplus (capped) ids from that set.
- `_counter_trends` is deliberately no-allowlist ("nothing disappears") — the fact
  block's salient-counter reduction is a **prompt-rendering** choice only; full
  fidelity stays in `sift perfmon`.

### Integration Points
- `hypothesise._assemble` — where the perfmon fact block is spliced and its ids
  unioned into `prompted_ids`; the single citation-integrity chokepoint.
- `sift analyze` CLI path — builds `PerfmonAnalysis` pre-generation (mirror how MCM
  facts are built) and passes the rendered block into `_assemble`.
- `sift eval` — golden-case registration + regression threshold.
</code_context>

<specifics>
## Specific Ideas

- Reading order in the prompt: KB (background, non-citable) → MCM facts → perfmon
  facts → Evidence. Perfmon sits alongside MCM as corroborating counter evidence
  for the same denial episodes.
- Prompt bound driver is groups × counters, **not** the 13,596 raw samples — the
  correlator already summarises each counter to at-denial/slope/peak, so the cap
  is on rendered groups (D-03) + salient counters (D-04), not sample rows.
</specifics>

<deferred>
## Deferred Ideas

- Snapshot CSV+logs golden case (second candidate) — documented in REQUIREMENTS.md
  § Reference Data; not built this phase (D-07).
- Recovery-trend / multi-host / perfmon-only anomaly correlation — PERFV2-01/02/03,
  deferred beyond v1.2.

### Reviewed Todos (not folded)
- **Phase 11 code-review INFO follow-ups**
  (`.planning/todos/pending/2026-07-20-phase11-code-review-info.md`,
  `resolves_phase:14`) — IN-01 (shared granted-MB formatting helper in
  `mcm_facts.py`) and IN-03 (redundant `re.DOTALL` + cosmetic double-newline in the
  MCM splice, `hypothesise.py:90,106`). Low-priority cosmetic. **Address
  opportunistically** only if Phase 14 edits touch those exact lines (the perfmon
  splice work sits right beside IN-03); non-blocking, not a phase requirement.
</deferred>

---

*Phase: 14-perfmon-facts-into-sift-analyze-golden-eval-case*
*Context gathered: 2026-07-20*
