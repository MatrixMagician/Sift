# Phase 11: MCM Facts into `sift analyze` + Golden Eval Case - Context

**Gathered:** 2026-07-19
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 4 grey areas proposed, all recommended defaults accepted by user

<domain>
## Phase Boundary

Phase 11 is the additive LLM-integration layer over the deterministic MCM analyser
built in Phases 9–10. It delivers exactly two requirements:

- **MCM-06**: Structured MCM facts (episode summary, denial-time memory breakdown,
  graded diagnostic flags, top attributions) are fed into `sift analyze` as **cited
  evidence**, preserving the `cited ⊆ prompted ⊆ store` citation invariant. The figures
  are computed by the deterministic analyser and are **never authored by the model**.
- **MCM-07**: An MCM golden eval case (a denial episode with a known breakdown) is added
  to the eval suite with `truth.yaml`, and `sift eval` exits non-zero when its scores
  regress.

**In scope:** the citable MCM fact block, its versioned prompt template, the
prompted-ids wiring that makes MCM `event_id`s citable, the byte-identical-when-empty
additivity guard, and the golden eval case.

**Out of scope:** any change to the numeric analyser (`pipeline/mcm.py`) beyond what
Phase 11 strictly needs to *read* facts; the `sift mcm` report/CSV (shipped in Phase 10);
DSSPerformanceMonitor CSV correlation (PERF-01, deferred to v2 / SEED-001).

</domain>

<decisions>
## Implementation Decisions

### MCM injection into `sift analyze`
- **D-17: Automatic + additive — no CLI flag.** The MCM fact block is injected into the
  triage prompt whenever the case contains dsserrors MCM denial episodes (i.e.
  `analyse_mcm` returns ≥1 episode). When no MCM data is present, the triage prompt is
  **byte-identical** to today — satisfying success-criterion 5 mechanically (a golden
  prompt-hash test asserts it). No `--mcm`/`--no-mcm` flag is added.
- **Rejected:** *opt-out `--no-mcm`* and *opt-in `--mcm`* — both add CLI surface and hide
  or complicate a feature that is meant to be purely additive and on-by-default.

### Golden eval case data (MCM-07)
- **D-18: Reuse an existing committed MCM fixture slice.** The golden eval case input is
  an existing redacted denial slice already committed under `tests/fixtures/mcm/`
  (e.g. `hartford_deny_slice.log`), copied/referenced into `eval/cases/<mcm-case>/`, with
  `truth.yaml` asserting its known deterministic breakdown figures. No new customer-data
  decision, no synthetic authoring — these slices are already validated against the real
  Hartford episode and already shippable.
- **Rejected:** *author a new synthetic/redacted fixture* — more work, and a synthetic
  episode risks not matching a real denial's shape as faithfully as the validated slices.

### MCM fact-block scope (what enters the cited prompt)
- **D-19: Summary + breakdown + graded flags + top-5 attributions per dimension.** The
  block carries: episode summary (denial time, `AvailableMCM` headroom descent),
  denial-time memory breakdown as **% of HWM/total** (not raw GB in headline figures,
  matching D-11), the graded diagnostic flags (info/warn/critical + triggering %), and the
  **top-5** attribution rows per dimension (OID / Source / SID) by granted memory. The
  block is **token-bounded** so it fits the existing prompt budget without crowding out
  cluster exemplars.
- **Rejected:** *summary+flags only* (drops the "which object/session drove it" evidence);
  *all attribution rows* (unbounded; can push exemplars out of budget on large cases).

### Versioned prompt template shape
- **D-20: Separate fragment `src/sift/prompts/mcm_facts.md`, spliced via a sentinel.**
  Python computes and formats every figure, renders the fragment, and injects it into the
  triage prompt at a sentinel marker (mirroring the existing `--kb` block precedent).
  `triage.md` stays byte-identical when there is no MCM data. Changing the fragment's
  wording touches **no Python** (constraint: prompts are versioned template files) — but
  the *numbers* come from the analyser, so the template holds only labels/wording and
  placeholders, never authored values.
- **Rejected:** *new conditional section inside `triage.md`* — couples MCM wording to the
  main template and complicates the byte-identical-when-empty guard.

### Claude's Discretion
- Exact sentinel marker string, fragment field ordering, and the precise Pydantic/dataclass
  shape carrying facts into the renderer are the planner's/executor's call, provided the
  four decisions above and the carried-forward invariants below hold.
- Final `truth.yaml` metric selection for the MCM golden case (which figures to assert,
  tolerance) is the planner's call, provided the case regression-gates (`sift eval` exits
  non-zero on regression) per MCM-07.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sift/pipeline/mcm.py` — the deterministic analyser. `analyse_mcm(...)` is the single
  orchestration entry (03/10 decisions); returns `McmEpisode`s carrying `MemoryBreakdown`,
  graded flags, and per-dimension `AttributionRow`s where **every row already carries its
  owning `event_id`(s)** (D-16) — the citation provenance Phase 11 consumes.
- `src/sift/pipeline/hypothesise.py` — builds the triage prompt and enforces the citation
  gate. Prior decision (04-04): **`prompted_ids` (the printed exemplar ids) IS the citation
  gate's allowed set; `cited ⊆ prompted` transitively guarantees `cited ⊆ store`.** Phase 11
  extends `prompted_ids` with the MCM fact block's `event_id`s so those facts are *citable*
  (the opposite of KB, which is deliberately non-citable).
- `src/sift/prompts/{triage,cluster_label,judge}.md` — versioned prompt templates. Phase 11
  adds `mcm_facts.md` alongside them.
- `src/sift/cli.py` — `analyze` command at ~line 661 (`--kb` threads NON-citable context via
  a sentinel-delimited block at ~824–826); `mcm` command at ~line 1003. The `--kb` sentinel
  splice is the structural precedent for the MCM fragment injection.
- `eval/cases/*/` — 6 golden cases, each `README.md` + `truth.yaml`; `eval/thresholds.toml`;
  `sift eval` gate already exits non-zero on regression (EVAL-03, ADR 0010). Phase 11 adds a
  7th (MCM) case.
- `tests/fixtures/mcm/{hartford_deny_slice,hartford_deny_double,hartford_deny_predenial_multisid,hartford_two_episode_partial}.log`
  — committed redacted denial slices; the golden-case data source (D-18).

### Established Patterns
- **Prompt additivity via sentinel splice** (`--kb`): a block is rendered and spliced into
  `triage.md` at a marker; the no-block prompt is byte-identical (guarded by a golden hash).
  MCM reuses this exact pattern.
- **Citation gate** = membership in `prompted_ids`. Citable ⇒ add ids to the set; non-citable
  (KB) ⇒ leave the set unchanged.
- **Determinism**: MCM figures are computed, never generated — the module is model-free, so
  the fact block is byte-identical across runs for a fixed case.
- **TDD RED→GREEN→gate** per plan task (project convention): failing test → impl → `ruff` +
  `pyright` + full `pytest` green → docs commit, each atomic.

### Integration Points
- `hypothesise.py` prompt assembly — inject the MCM fragment + extend `prompted_ids`.
- `cli.py analyze` — call `analyse_mcm` when dsserrors/MCM data present; thread facts into the
  hypothesise path (additive; independent of, and composable with, `--kb`).
- `eval/cases/` + `truth.yaml` schema (Pydantic `Truth`, `yaml.safe_load`, extra=forbid) — add
  the MCM golden case.

</code_context>

<specifics>
## Specific Ideas

- The determinism proof (criterion 2) is a **test that mutates the model's echoed numbers and
  asserts the surfaced figures still equal the analyser's verbatim output** — i.e. the model
  cannot alter or invent MCM figures. This is the load-bearing anti-hallucination test for the
  phase; it must exist.
- Headline figures are framed as **% of HWM/total**, never absolute GB (consistency with D-11).
- The MCM fact block must coexist cleanly with a `--kb` block in the same `analyze` run
  (citable MCM + non-citable KB simultaneously).

</specifics>

<deferred>
## Deferred Ideas

- DSSPerformanceMonitor PDH-CSV time-series correlation (PERF-01) — already deferred to v2
  (SEED-001); not reopened here.
- Per-run CLI threshold/window knobs for MCM — deferred in Phase 10 (D-12/D-13); Phase 11 does
  not reintroduce them.

</deferred>
