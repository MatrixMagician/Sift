# Phase 7: Evaluation Harness & Golden Cases - Context

**Gathered:** 2026-07-18
**Status:** Ready for planning

> **Auto mode (`--auto`).** All gray areas were auto-selected and resolved with
> recommended defaults grounded in SPEC.md §6 (the authoritative eval-harness
> spec). Each decision below is a recommended default a downstream planner may
> refine; none contradict the locked SPEC. No user questions were asked.

<domain>
## Phase Boundary

Deliver a **golden-case evaluation harness** that makes hypothesis quality
measurable and regression-gated instead of vibes-based. Concretely: a committed
suite of ≥5 synthetic-but-realistic golden cases, and a `sift eval` command that
runs the suite, prints a metric table (retrieval hit rate, hypothesis hit@k,
citation validity rate, determinism drift), honours `eval/thresholds.toml`, and
exits non-zero on a planted regression. Optional local LLM-as-judge grading is
reported **alongside** (never instead of) keyword scores.

**In scope:** EVAL-01 (golden suite), EVAL-02 (`sift eval` metric table),
EVAL-03 (threshold-gated non-zero exit), EVAL-04 (optional LLM-as-judge).
**Out of scope (own phases / deferred):** real sanitised customer cases
(added privately later per SPEC §6); the report redaction/sanitisation pass
(REPT-05, its own concern); packaging/CI wiring beyond a CI-friendly exit code
(Phase 8); salience-weight retuning (SPEC open question #4 — informed by these
metrics but not changed here).
</domain>

<decisions>
## Implementation Decisions

### Golden Suite Composition (EVAL-01)
- **D-01:** Author **6** synthetic-but-realistic cases under `eval/cases/<name>/`,
  covering the five SPEC §6 exemplars — memory-watermark cascade, SMTP relay
  rejection storm, thread-pool exhaustion, disk-full, dependency-service timeout —
  and guaranteeing the three ROADMAP-mandated shapes are all present: designate
  the **dependency-service-timeout** case as the **mixed-timezone** case, add a
  distinct **quiet-cause** case (root cause is a low-severity/early signal, not the
  loudest error), and add a **negative (no-incident)** case (healthy logs → no
  confident root cause). `[auto] recommended default — satisfies ROADMAP SC1 (≥5
  incl. quiet-cause + mixed-tz + negative) and SPEC §6 exemplar list.`
- **D-02:** Each case ships `input/` (sanitised artefacts), `truth.yaml`, and
  `README.md`. **`truth.yaml` is committed before any prompt tuning** and treated
  as frozen ground truth (ROADMAP SC1 / SPEC §6). `[auto] recommended default.`

### truth.yaml Schema & Matching Semantics (EVAL-02)
- **D-03:** `truth.yaml` fields: `root_cause` (descriptive string),
  `required_evidence` (list of **regex** patterns), `acceptable_keywords` (list
  for hit@k). **Retrieval hit rate** = fraction of `required_evidence` patterns
  present in the cluster exemplars/templates fed to the model. **Hypothesis
  hit@k** = any of the top-k hypotheses matches ground truth by
  case-insensitive **any-of** keyword match against title+narrative. `[auto]
  recommended default — mirrors SPEC §6 metric definitions.`
- **D-04:** The **negative case** asserts the *absence* of a confident hypothesis
  (degraded/empty triage is the correct outcome), so `truth.yaml` supports a
  `expect_no_incident: true` marker scored as a pass when no over-confident root
  cause is emitted. `[auto] recommended default.`

### `sift eval` CLI & Metrics (EVAL-02)
- **D-05:** Signature `sift eval [--suite <dir>] [--json]` (SPEC §5-CLI), default
  suite `eval/cases/`. Plain-text metric table by default; `--json` emits the
  machine-readable table. Fills the existing stub at `src/sift/cli.py:956`.
  `[auto] recommended default.`
- **D-06:** **Determinism drift** = run `analyze` **N=2** times per case (config-
  overridable) and compare the normalised JSON via the Phase 6
  `normalise_for_determinism` helper (`src/sift/render/json_out.py`) for
  byte-equality; drift metric = fraction of cases whose repeated runs are
  byte-identical. `[auto] recommended default — reuses the M6 determinism seam,
  no new normalisation logic.`

### Threshold Gating & CI Exit (EVAL-03)
- **D-07:** `eval/thresholds.toml` holds per-metric floors
  (`retrieval_hit_rate`, `hypothesis_hit_at_k`, `citation_validity_rate`,
  `determinism_drift`). `sift eval` exits **non-zero if any keyword metric is
  below its floor**; clean pass exits 0. Follows the exit-code discipline of ADRs
  0005 (analyze) / 0007 (report). `[auto] recommended default.`

### LLM-as-judge (EVAL-04)
- **D-08:** `--judge` is **opt-in, off by default**. The judge prompt is a
  versioned template `src/sift/prompts/judge.md` (prompts never require touching
  Python, per CLAUDE.md). Judge scores are **advisory-only — reported alongside,
  never gating** the exit code (SPEC §6 "alongside, never instead of"). `[auto]
  recommended default.`
- **D-09:** The default keyword-scored eval run is **fully offline** (network-free
  per EVAL-05) using the injectable fake client. The judge path needs the real
  local model, so its test is marked `@pytest.mark.live` and **excluded from the
  socket-blocked default suite** — the same live-test pattern already used for
  REPT-04 (PDF) and EVAL-05. `[auto] recommended default.`

### Harness Architecture
- **D-10:** Case-running logic lives in a new `src/sift/eval/` package invoked by
  the `sift eval` CLI command; it drives the existing pipeline
  (ingest → dedup/cluster → retrieve → hypothesise) against a **temp `case.db`
  per case**, with the fake OpenAI-compatible client injected for offline runs.
  Add **PyYAML** for `truth.yaml` parsing (already sanctioned for M7 in CLAUDE.md
  / stack notes). `[auto] recommended default.`

### Claude's Discretion
- Exact synthetic log content and volume per golden case, regex specificity in
  `truth.yaml`, table column formatting, and the default `k` for hit@k (suggest
  k = number of hypotheses `analyze` emits, typically 3) — planner/executor may
  choose within the decisions above.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Evaluation harness spec (authoritative — locked)
- `SPEC.md` §6 (Evaluation Harness) — golden suite layout, `truth.yaml`
  contents, the four metrics, LLM-as-judge, `eval/thresholds.toml`, non-zero
  exit. **MUST read before planning.**
- `SPEC.md` §5.5 / §8 (M7 acceptance) — `sift eval` runs the suite, prints the
  metric table, honours thresholds, exits non-zero on planted regression.
- `.planning/ROADMAP.md` → Phase 7 — Success Criteria (≥5 cases incl.
  quiet-cause, mixed-timezone, negative; metric table; CI thresholds; optional
  judge alongside keyword scores).
- `.planning/REQUIREMENTS.md` — EVAL-01, EVAL-02, EVAL-03, EVAL-04, and the
  already-satisfied EVAL-05 (tests never touch the network; injectable client +
  fake server).

### Precedent / reuse
- `docs/decisions/0005-analyze-exit-codes.md`, `docs/decisions/0007-report-exit-codes.md`
  — exit-code discipline the `sift eval` non-zero-on-regression contract follows.
- `docs/decisions/0008-report-determinism-scope.md` — determinism is
  renderer-scoped; the drift metric measures normalised-JSON byte-equality via
  the same seam.
- `src/sift/render/json_out.py` — `normalise_for_determinism` reused for the
  determinism-drift metric.
- `src/sift/cli.py:956` — existing `sift eval` stub to fill.
- `CLAUDE.md` — PyYAML sanctioned for `truth.yaml` (M7 only); prompts are
  versioned template files.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sift/cli.py:956` `eval_()` — stub command to implement (currently prints
  "eval arrives in Phase 7" and exits 1).
- `src/sift/render/json_out.py` `normalise_for_determinism` — drives the
  determinism-drift metric without new normalisation code.
- Injectable client seam `_make_http_client` (`cli.py`) + fake OpenAI-compatible
  server pattern (EVAL-05) — the harness runs the full pipeline offline.
- The full pipeline (`pipeline/dedup.py`, clustering, `retrieve.py`,
  `hypothesise.py`) and the citation gate (cited ⊆ prompted ⊆ store) — the
  citation-validity-rate metric reads directly off this.

### Established Patterns
- **Live-vs-offline split:** `@pytest.mark.live` marks tests needing the real
  local model (REPT-04, EVAL-05); the default suite is socket-blocked. The
  `--judge` path follows this exactly.
- **Exit-code contracts** live in ADRs (0005/0007); a new ADR should record the
  `sift eval` threshold-gated exit semantics (per the project's ADR convention).

### Integration Points
- New `src/sift/eval/` package ↔ `sift eval` CLI command.
- `eval/` repo dir (cases + `thresholds.toml` + README) is new top-level content
  per SPEC §4 layout.
</code_context>

<specifics>
## Specific Ideas

- Fold the three ROADMAP-mandated special shapes into the SPEC exemplar list
  rather than adding them as extras: dependency-timeout **is** the mixed-tz case;
  quiet-cause and negative are distinct cases. Keeps the suite at a lean 6 while
  satisfying every acceptance clause.
</specifics>

<deferred>
## Deferred Ideas

- Real sanitised customer cases in the golden suite — added privately later
  (SPEC §6), not part of this phase.
- Report redaction/sanitisation pass (REPT-05) — reusable for turning real cases
  into golden ones, but its own concern.
- Salience-weight retuning informed by the new metrics (SPEC open question #4) —
  a later tuning pass, not this phase.
- Wiring `sift eval` into an actual CI pipeline — Phase 8 (Packaging & Deploy);
  this phase only guarantees the CI-friendly non-zero exit.
</deferred>

---

*Phase: 7-Evaluation Harness & Golden Cases*
*Context gathered: 2026-07-18*
