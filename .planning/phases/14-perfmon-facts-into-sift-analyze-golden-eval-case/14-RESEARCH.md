# Phase 14: Perfmon Facts into `sift analyze` + Golden Eval Case - Research

**Researched:** 2026-07-20
**Domain:** Internal-codebase mirror — deterministic fact-block splice into the triage prompt + eval regression gate (Python 3.12, no new dependencies)
**Confidence:** HIGH (every mechanic already ships in this repo; all findings are `file:line` verified against the working tree)

## Summary

This phase is a near-verbatim mirror of the already-shipped **Phase 11 (MCM facts)**, one evidence-source out. Everything it needs exists and is read directly: `render_mcm_facts` (the renderer to copy), `_apply_mcm_block` + the sentinel regexes (the splice to copy), the `prompted_ids` union in `_assemble` (the citation chokepoint), the `mcm_facts.md` zero-digit fragment (the template to copy), `analyse_perfmon` + its frozen models (the figures source), `_hazard_unplaceable_samples` (the D-08 reuse target), and the golden-case eval harness (`eval/`, `sift eval`, `run_case`, `gate`). There is **no external/library research** — the stack is frozen (boring-tech constraint) and no package is added.

The work is genuinely mechanical **except one hard, non-obvious blocker** the planner must design around: **the real Hartford deny CSV+log pair can never produce a citable perfmon fact block through the episode path.** The CSV's last sample is `2026-04-07 12:39:39.397`; the deny log's earliest (and only) events are `12:39:47.142`+, with the denial at `12:39:47.146`. The MCM correlation span is `[window_start, denial_ts]` — entirely inside `12:39:47` — so **zero perfmon samples fall in-span**, `_hazard_non_overlap` (critical) fires, no `_counter_trends` are computed, and the only citable ids from an episode `TrendGroup` come from in-span samples' `at_denial_event_id`/`peak_event_id` — of which there are none (the group's `boundary_event_ids` are the two **dsserrors** span-end events, not perfmon). PERF-07 criterion 1 ("hypotheses cite perfmon evidence by event_id") and the PERF-08 golden case therefore **require an overlapping CSV+log fixture pair** — synthetic, or a re-timed slice — not the shipped `tests/fixtures/{dssperfmon,mcm}/hartford_deny_slice.*`. This is the single largest planning risk and is covered in detail below (Open Question 1, Common Pitfall 1).

**Primary recommendation:** Copy Phase 11's four artefacts almost line-for-line — `render_perfmon_facts()` (mirror `render_mcm_facts`), `_apply_perfmon_block`/`_PERFMON_BLOCK_RE`/`_PERFMON_MARKER_RE` (mirror the MCM trio), `prompts/perfmon_facts.md` (mirror `mcm_facts.md`), the `PERFMON_BLOCK` sentinel in `triage.md` after MCM — build the perfmon block at the same pre-generation chokepoint inside `hypothesise()`, union its printed ids into `prompted_ids`, and add a golden eval case whose MCM-sensitive metric mirror is `citation_validity_rate`. **Build the overlapping fixture pair first (Wave 0).**

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (prompt splice):** Add a **new, independent** `PERFMON_BLOCK_START`/`PERFMON_BLOCK_END` sentinel pair with a `<<PERFMON_FACTS>>` slot, placed **immediately after the existing MCM block** (final prompt order: KB → `Evidence:` → MCM facts → perfmon facts → cluster evidence lines). Each block is removed whole when its data is absent, exactly as MCM/KB today. Do **not** merge MCM and perfmon into one block. Mirror `_apply_mcm_block`/`_MCM_BLOCK_RE`/`_MCM_MARKER_RE` verbatim as `_apply_perfmon_block`/`_PERFMON_BLOCK_RE`/`_PERFMON_MARKER_RE`.
- **D-02 (byte-identity guards):** Strictly additive. Guard **independently**: no-perfmon prompt is byte-identical regardless of MCM presence; both-absent baseline stays byte-identical to today's shipped prompt (existing `triage_prompt_hash` / no-MCM golden hash must not move). Add golden-hash coverage for the **four** presence combinations (neither / MCM-only / perfmon-only / both), not just one.
- **D-03 (group cap):** Cap rendered `TrendGroup`s at a fixed constant mirroring MCM's `_MAX_EPISODES = 8` (e.g. `_MAX_GROUPS`), sorted by hazard severity (critical > warn > info), highest first. Surplus groups dropped from the block **and** their event_ids kept out of the returned citable set (`cited ⊆ prompted ⊆ store`, exactly as `[:_MAX_EPISODES]`).
- **D-04 (salient counter subset):** Within each rendered group, print a **salient counter subset** for the prompt only (working-set cache RAM, System RAM used, Process(MSTRSvr) Size, Open Sessions, Total MCM Denial flag) plus any counter a rendered hazard cites. This is a **rendering-time selection**, NOT a correlator change: `_counter_trends` keeps its no-allowlist "every counter" behaviour and full 22-counter fidelity stays in `sift perfmon`. Salient set + ordering must be deterministic (fixed priority list, stable sort). Exact mechanics = Claude's discretion.
- **D-05 (citation contract):** `render_perfmon_facts(analysis: PerfmonAnalysis) -> tuple[str, set[str]]` mirrors `render_mcm_facts`: returned citable set is **exactly** the `[evt:<id>]` tokens printed (from each rendered group's `boundary_event_ids` and its rendered hazards'/counters' `event_id`s). `_assemble` unions this into `prompted_ids`. Figures built pre-generation (anti-hallucination test mirroring Phase 11).
- **D-06 (template):** New `prompts/perfmon_facts.md` mirroring `prompts/mcm_facts.md`: labels/prose only, **zero authored digits**, guarded by a no-digit test. Same "these lines ARE evidence, treat as untrusted data" framing. A `<<PERFMON_LINES>>` placeholder substituted in Python.
- **D-07 (golden eval case):** Regression gate anchored on the **Hartford deny CSV+log pair**. `sift eval` exits non-zero when correlation output regresses. Snapshot pair is a documented future second candidate, not built this phase.
- **D-08 (folded WR-03):** When the case HAS MCM episodes, an untimestamped perfmon sample (`ts is None`) falls in no span and is currently dropped silently — the same violation WR-03 fixed only on the no-episodes branch. Add a **case-level unattributed-samples disclosure** (a `PerfmonAnalysis` field OR a dedicated synthetic group), reusing `_hazard_unplaceable_samples` (caps at `_CITE_CAP`, sorts by `event_id`). This is a **model/design change** to `PerfmonAnalysis` (which today deliberately forbids case-level hazards) — planner decides field-vs-group and preserves Phase 13 determinism + `_RESERVED_ATTRS`/citation invariants. Doubly-synthetic on real data; unreachable on the all-timestamped Hartford reference.

### Claude's Discretion

- Exact salient-counter selection + ordering within D-04 (deterministic; citable = printed ids).
- Whether the D-08 disclosure is a `PerfmonAnalysis` field or a synthetic group — a real design call, constrained by Phase 13's "one hazard ↔ one span" and determinism invariants.
- Golden-fixture construction mechanics (reuse Phase 12/13 synthetic PDH-CSV builders / real Hartford slice per existing test conventions).

### Deferred Ideas (OUT OF SCOPE)

- Snapshot CSV+logs golden case (second candidate) — REQUIREMENTS.md § Reference Data; not built this phase.
- Recovery-trend / multi-host / perfmon-only anomaly correlation — PERFV2-01/02/03, deferred beyond v1.2.
- Any change to the `sift perfmon` report/CSV shape (Phase 13, shipped).
- **Phase 11 code-review INFO follow-ups** (IN-01 shared granted-MB helper in `mcm_facts.py`; IN-03 redundant `re.DOTALL` + cosmetic double-newline at `hypothesise.py:88,90`/`106`) — address **opportunistically only** if Phase 14 edits touch those exact lines; non-blocking, not a requirement.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **PERF-07** | Perfmon figures injected into `sift analyze` as **cited** evidence — computed before generation so the model cannot alter/invent them, `cited ⊆ prompted ⊆ store` preserved, prompt byte-identical to today's when no perfmon data present. | Mirror `render_mcm_facts` → `_apply_mcm_block` → `_assemble` `prompted_ids` union (`mcm_facts.py`, `hypothesise.py:86-106,220-272,369-381`). Figures source: `analyse_perfmon` (`perfmon.py:648`). Anti-hallucination + byte-identity test patterns: `test_mcm_analyze.py:221-262`. **Blocker:** citable perfmon facts need an overlapping fixture (see Open Q1). |
| **PERF-08** | Regression-gated golden perfmon eval case; `sift eval` exits non-zero if correlation output degrades. | Golden-case wiring: `eval/cases/mcm-denial/`, `eval/runner.py:run_case`, `eval/thresholds.py:gate`. Perfmon-sensitive metric mirror = `citation_validity_rate` (see `test_eval_cases.py:233-268` MCM precedent). Needs overlapping CSV+log fixture pair to be non-vacuous. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Compute perfmon figures (at-denial/slope/peak) | Deterministic pipeline (`pipeline/perfmon.py`) | — | Already shipped Phase 13; pure/deterministic, no model, no store, no CLI. |
| Render figures → citable fact block | Deterministic pipeline (new `pipeline/perfmon_facts.py`) | Prompt template (`prompts/perfmon_facts.md`) | Mirrors `mcm_facts.py`: numbers in Python, wording in template. |
| Splice block + union citable ids | Hypothesis orchestration (`pipeline/hypothesise.py`) | — | `_assemble` is the single citation-integrity chokepoint; perfmon is the 2nd citable block. |
| Build analysis pre-generation | Hypothesis orchestration (`hypothesise()` body) | — | Same chokepoint as MCM (`hypothesise.py:369`) so the eval harness exercises injection too. |
| Regression gate | Eval harness (`eval/`, `sift eval`) | Golden fixture (`eval/cases/<perfmon-case>/`) | `run_case` reuses the exact analyze pipeline; gate on `citation_validity_rate`. |
| D-08 unattributed disclosure | Deterministic pipeline (`perfmon.py` model) | — | Model/shape change to `PerfmonAnalysis`; must preserve determinism invariants. |

## Standard Stack

No new dependencies. This phase uses only what is already imported by the mirrored modules.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stdlib `re` | 3.12 | sentinel-block regexes (`_PERFMON_BLOCK_RE`/`_PERFMON_MARKER_RE`) | Exact mirror of `hypothesise.py:58-61,87-90` `[VERIFIED: hypothesise.py]` |
| stdlib `importlib.resources` | 3.12 | load `perfmon_facts.md` from package data | Mirror `_load_mcm_fragment` (`mcm_facts.py:70-80`) `[VERIFIED: mcm_facts.py]` |
| Pydantic | 2.13.x (already pinned) | `PerfmonAnalysis`/`TrendGroup`/`CounterTrend`/`PerfmonHazard` frozen models | Already the model layer in `perfmon.py:98-184` `[VERIFIED: perfmon.py]` |
| `sift.render._util.sanitise` | in-repo | control-char / prompt-injection defence on every log-derived value | MCM renderer routes every value through it (`mcm_facts.py:30,105,120,137`) `[VERIFIED]` |

### Supporting (test-only, already present)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx.MockTransport` | 0.28.1 | fake OpenAI-compatible server (zero network) | Every analyze/eval test; autouse `_no_network` conftest `[VERIFIED: test_mcm_analyze.py:83-120]` |
| `typer.testing.CliRunner` | Typer 0.27 | drive `sift analyze`/`sift eval` end-to-end | `test_mcm_analyze.py:327-379` `[VERIFIED]` |
| `tests/_perfmon_fixtures.py` builders | in-repo | synthetic PDH-CSV construction (collision/drift/non-finite) | Fixture for the overlapping golden pair `[VERIFIED: _perfmon_fixtures.py]` |

**Installation:** none. `uv sync` already provides everything.

## Package Legitimacy Audit

Not applicable — this phase installs **zero** external packages. All code reuses in-repo modules and the frozen, already-installed dependency set (stdlib, Pydantic, httpx, Typer). No registry lookup required.

## Architecture Patterns

### System Data Flow (perfmon fact injection)

```
sift analyze <case>
  │
  ▼
hypothesise(store, client, ...)                         # pipeline/hypothesise.py:326
  │  events = store.query_events()                      # includes dssperfmon rows (store NOT filtered)
  │
  ├─▶ analyse_mcm(events, thresholds) ──▶ McmAnalysis    # already computed for MCM block (line 369-371)
  │        │
  │        ▼
  │   render_mcm_facts(mcm_analysis) ─▶ (mcm_text, mcm_ids)
  │
  ├─▶ analyse_perfmon(mcm_analysis, events) ─▶ PerfmonAnalysis   # NEW call, reuse the mcm_analysis + events
  │        │                                                     # perfmon.py:648
  │        ▼
  │   render_perfmon_facts(perfmon_analysis) ─▶ (perfmon_text, perfmon_ids)   # NEW: mirror render_mcm_facts
  │        - sort groups by hazard severity, take [:_MAX_GROUPS]  (D-03)
  │        - per group: print salient counter subset + hazard-cited counters (D-04)
  │        - citable ids = exactly the printed [evt:] tokens      (D-05)
  │
  ▼
_assemble(..., mcm_block=(mcm_text,mcm_ids), perfmon_block=(perfmon_text,perfmon_ids))   # hypothesise.py:220
  │   template = _apply_kb_block(...)          # KB: non-citable, removed-whole-when-absent
  │   template = _apply_mcm_block(...)         # MCM: citable
  │   template = _apply_perfmon_block(...)     # NEW: perfmon, citable, spliced AFTER mcm
  │   prompted_ids = set(cluster_ids) | mcm_ids | perfmon_ids     # NEW union term
  │
  ▼
constrained decode → validate → repair → citation_gate(cited ⊆ prompted) → persist
```

**Key insight:** perfmon events are visible to `analyse_perfmon` because `store.query_events()` **deliberately does NOT apply `EXCLUDED_FROM_RANKING`** (`store.py:683` comment; `EXCLUDED_FROM_RANKING = frozenset({"dssperfmon"})` at `store.py:335`). Exclusion only removes them from dedup/cluster/salience — they remain citable. `[VERIFIED: store.py]`

### Recommended file layout
```
src/sift/pipeline/perfmon_facts.py     # NEW — mirror of mcm_facts.py (render_perfmon_facts, _MAX_GROUPS, salient set)
src/sift/pipeline/hypothesise.py       # EDIT — add _apply_perfmon_block + regexes; perfmon_block param + union
src/sift/pipeline/perfmon.py           # EDIT (D-08 only) — case-level unattributed disclosure
src/sift/prompts/perfmon_facts.md      # NEW — zero-digit fragment (mirror mcm_facts.md)
src/sift/prompts/triage.md             # EDIT — add PERFMON_BLOCK sentinel after MCM_BLOCK_END
eval/cases/<perfmon-case>/             # NEW — golden case: input/ (overlapping CSV+log), truth.yaml, README.md
tests/test_perfmon_facts.py            # NEW — mirror test_mcm_facts.py
tests/test_perfmon_analyze.py          # NEW — mirror test_mcm_analyze.py (4-combo byte-identity, anti-halluc)
tests/test_eval_cases.py               # EDIT — add perfmon golden-case + citation-sensitivity test
```

### Pattern 1: Renderer — citable set == printed tokens
`render_mcm_facts` (`mcm_facts.py:83-141`) is the exact template. Copy its shape:
```python
# Source: src/sift/pipeline/mcm_facts.py:83-141 (mirror verbatim for perfmon)
def render_perfmon_facts(analysis: PerfmonAnalysis) -> tuple[str, set[str]]:
    if not analysis.groups:
        return "", set()                     # residue-free strip (mirror line 90-91)
    ids: set[str] = set()
    lines: list[str] = []
    selected = sorted(analysis.groups, key=_group_severity_rank)[:_MAX_GROUPS]  # D-03
    for group in selected:
        # print salient counters (+ hazard-cited counters, D-04); add each printed
        # [evt:<id>] token to `ids` (D-05); sanitise() every log-derived value.
        ...
    return _load_perfmon_fragment().replace(_PERFMON_LINES_SLOT, "\n".join(lines)), ids
```
Note MCM's `_episode_severity_rank` (`mcm_facts.py:57-67`) uses `_SEVERITY_ORDER = {"critical":0,"warn":1,"info":2}`; perfmon hazards use the **same** three literals (`perfmon.py:119`), so the group-severity rank is a direct copy.

### Pattern 2: Sentinel splice — remove-whole-block-when-absent
`_apply_mcm_block` (`hypothesise.py:93-106`) + its two regexes (`:87-90`). The perfmon copy is mechanically identical, substituting `PERFMON` for `MCM`. In `triage.md`, add after `<!-- MCM_BLOCK_END -->` (currently the last line, `triage.md:50`):
```
<!-- PERFMON_BLOCK_START (inserted only when the case has correlated perfmon groups; ... removes the whole block when absent so the no-perfmon prompt stays byte-identical) -->
<<PERFMON_FACTS>>
<!-- PERFMON_BLOCK_END -->
```

### Pattern 3: Pre-generation build inside `hypothesise()`
Build at the same chokepoint as MCM (`hypothesise.py:364-371`). Hoist `events = store.query_events()` into a local (currently called inline at line 370 and again at 355 via `store.query_clusters`/`query_events`; avoid a third decompress pass — `analyse_perfmon` needs the same `events` list and the `McmAnalysis`). Thread a `perfmon_block` kwarg through `_assemble` mirroring `mcm_block` (`hypothesise.py:229,250,271,378-381`).

### Anti-Patterns to Avoid
- **Merging MCM+perfmon into one sentinel block** — D-01 forbids; couples their independent byte-identity guards and caps.
- **Re-deriving figures in the renderer** — every number comes verbatim from `analyse_perfmon`; the renderer only selects and formats (mirror `mcm_facts.py` which never re-derives `value_pct`).
- **Adding an allowlist to `_counter_trends`** — D-04 is a render-time selection only; `perfmon.py:266-284` keeps the deliberate no-allowlist sweep.
- **Building a span from `denial_ts` string** — `_resolve_span` deliberately refuses that fallback (`perfmon.py:207-209`); do not reintroduce it in D-08 work.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sentinel block removal | A new parser | Copy `_MCM_BLOCK_RE`/`_MCM_MARKER_RE` (`hypothesise.py:87-90`) | Proven byte-identity semantics; IN-03 notes the `re.DOTALL` is redundant but harmless. |
| Citable-id tracking | A separate id registry | Renderer returns `(text, ids)`, `_assemble` unions (`hypothesise.py:271`) | The whole anti-hallucination guarantee rests on `cited ⊆ prompted`; do not add a second path. |
| Perfmon figures | Any recompute | `analyse_perfmon(mcm_analysis, events)` (`perfmon.py:648`) | Phase 13 shipped; deterministic, `event_id`-carrying, already tested. |
| Unplaceable-sample disclosure (D-08) | New hazard text | `_hazard_unplaceable_samples` (`perfmon.py:523-554`) | Same `_CITE_CAP`, same `event_id` sort, same "nothing disappears silently" wording. |
| Synthetic PDH-CSV | Hand-written CSV strings | `tests/_perfmon_fixtures.py` builders (`write_collision_csv`, etc.) | Path-guarded (`T-13-FIXPATH`), self-verified (`T-13-VACUOUS`). |
| Prompt-injection defence on counter names | Custom escaping | `sanitise()` on every value | Counter names originate in the customer CSV header — untrusted (V5). |

**Key insight:** every mechanic this phase needs already exists and is tested. The only genuinely *new* logic is (a) the salient-counter selection (D-04) and (b) the D-08 model-shape change — everything else is a rename-and-mirror.

## Runtime State Inventory

Not a rename/refactor/migration phase — greenfield additive code. No stored data, live-service config, OS-registered state, secrets, or build artefacts carry a renamed string.
- **Stored data:** None — no schema change to `case.db`; perfmon events already ingested by Phase 12. `triage_prompt_hash` meta value **will legitimately change** for cases that gain a perfmon block (that is the intended behaviour, not drift; the *no-data* baselines must not move — D-02).
- **Live service config / OS-registered state / secrets:** None.
- **Build artefacts:** New `prompts/perfmon_facts.md` must be packaged as package-data exactly like `mcm_facts.md` (loaded via `importlib.resources.files("sift.prompts")` — verify `pyproject.toml`/`hatch` already globs `sift/prompts/*.md`; MCM's fragment ships this way, so a `*.md` glob almost certainly already covers it — confirm, don't assume). `[ASSUMED — verify packaging glob]`

## Common Pitfalls

### Pitfall 1: The shipped Hartford fixture pair CANNOT yield citable perfmon facts (BLOCKER)
**What goes wrong:** Reusing `tests/fixtures/mcm/hartford_deny_slice.log` + `tests/fixtures/dssperfmon/hartford_deny_slice.csv` for the analyze/eval integration produces a `PerfmonAnalysis` whose only episode group is a **critical non-overlap hazard with zero counters** — no citable perfmon `event_id`s at all, so PERF-07 criterion 1 and the PERF-08 golden case are silently vacuous.
**Why it happens:** `[VERIFIED: fixture inspection]` deny log events span `12:39:47.142–.356` (denial at `.146`); CSV slice last row is `12:39:39.397` — ~8 s *before* the window. Correlation span `[window_start, denial_ts]` is `_in_span`-closed (`perfmon.py:238-263`) and the window start is derived from log events (all at `12:39:47`), so no CSV sample can be in-span. This holds for the **full real 2 MB CSV too**: it ends 6 s before the denial banner (REQUIREMENTS.md § Reference Data), and the deny log has no lead-up events before `12:39:47` to move the window start earlier. Episode-group `boundary_event_ids` are the two **dsserrors** span-end events (`perfmon.py:731`), not perfmon — so even the boundary contributes no perfmon id.
**How to avoid:** Build an **overlapping** CSV+log pair as Wave 0 (Claude's discretion per D-07): either (a) a synthetic dsserrors denial log whose lead-up window brackets synthetic PDH-CSV samples (extend `tests/_perfmon_fixtures.py`), or (b) re-time a real Hartford slice so ≥1 CSV sample lands inside the MCM window. Add a **fixture-guard test** (mirror `_perfmon_fixtures.py` self-checks) asserting `analyse_perfmon` yields a group with ≥1 non-`None` `CounterTrend.at_denial_event_id` — i.e. the fixture genuinely overlaps — so a future silent regression to non-overlap fails loudly.
**Warning signs:** golden case passes with an empty/critical-hazard perfmon block; `citation_validity_rate` sensitivity test shows no difference with injection on vs off.

### Pitfall 2: Counter short-names are qualified on collision — salient matching must handle both forms
**What goes wrong:** D-04's salient list uses human names (`Process(MSTRSvr) Size`, `System RAM used`); `CounterTrend.counter` holds the adapter's short name (`_short_counter_name` = last `\` segment, e.g. `Size(MB)`) — OR a two-segment qualified name (`Process(MSTRSvr)\Size(MB)`) when `_qualify_counter_names` detected a collision (`dssperfmon.py:118-140`). A naive exact-string match against one form silently drops the counter.
**How to avoid:** Match the salient priority list against the counter's *final* segment (`counter.rsplit("\\",1)[-1]`) or a substring set, deterministically. Keep the priority list a fixed tuple so ordering is stable (D-04). `[VERIFIED: dssperfmon.py:118-140]`

### Pitfall 3: D-08 breaks a documented `PerfmonAnalysis` invariant
**What goes wrong:** `PerfmonAnalysis` docstring states "**there is deliberately no case-level hazard collection**" and "**Every hazard is attributable to exactly one span**" (`perfmon.py:171-184`). Adding a case-level field or a synthetic group changes that contract; done carelessly it can perturb the Phase 13 determinism guarantee (`model_dump_json` byte-identical) or the `sift perfmon` report/CSV (out of scope to change).
**How to avoid:** See Open Question 1 for the field-vs-group analysis. Whichever is chosen, keep `dict.fromkeys`/sorted ordering (no `set` iteration), round at source, and add the new field/group in a fixed code position. Verify existing `test_perfmon.py` + `test_perfmon_report.py` golden assertions still pass (the Hartford reference is all-timestamped, so D-08 is unreachable there — those goldens should not move).

### Pitfall 4: `triage_prompt_hash` no-data baseline must not move (D-02)
**What goes wrong:** Any stray whitespace/newline difference in the removed-block path shifts the both-absent prompt hash, breaking Phase 11's shipped byte-identity guarantee.
**How to avoid:** Mirror `_MCM_BLOCK_RE` trailing-`\n` capture exactly (`hypothesise.py:88`). Add all four golden-hash combos (D-02) and assert the *neither* and *MCM-only* hashes equal their pre-phase values.

## Code Examples

### Union the perfmon citable ids (the load-bearing one-line inversion)
```python
# Source: src/sift/pipeline/hypothesise.py:271 (add the perfmon term)
prompted_ids: set[str] = (
    set(event_ids)
    | (mcm_block[1] if mcm_block else set())
    | (perfmon_block[1] if perfmon_block else set())   # NEW — makes perfmon facts citable
)
```

### Anti-hallucination test shape (mirror for perfmon)
```python
# Source: tests/test_mcm_analyze.py:221-249 — the model cannot alter a pre-computed figure.
# For perfmon: render the block from analyse_perfmon independently, drive the fake client to
# echo a WRONG counter value in its narrative, assert the verbatim block is in the prompt and
# the wrong figure is NOT (prompt built before the reply).
```

### Citation-sensitivity eval test (mirror for the golden perfmon case)
```python
# Source: tests/test_eval_cases.py:233-268 — monkeypatch render_*_facts to ("", set()); the same
# cited perfmon id is then no longer in prompted_ids, citation_validity_rate drops below 1.0,
# proving the golden case is not a vacuous gate (T-11-06 analogue).
```

## State of the Art

Not applicable — no external ecosystem movement. The relevant "state of the art" is entirely the internal Phase 11 precedent, which is current (shipped 2026-07-20) and being mirrored deliberately.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pyproject.toml`/build config already globs `sift/prompts/*.md` as package data, so `perfmon_facts.md` ships without a manifest edit | Runtime State Inventory | LOW — if wrong, `importlib.resources` raises at runtime; caught by the first renderer test. Verify the glob when planning. |
| A2 | The MCM-sensitive eval metric mirror for perfmon is `citation_validity_rate` (a perfmon-citing hypothesis is valid only via injection) | PERF-08 support | LOW — directly analogous to the proven MCM case (`test_eval_cases.py:233-268`); the alternative (`retrieval_hit_rate`) is insensitive to injection by construction. |

**All other claims are `[VERIFIED]` against the working tree at `file:line`.**

## Open Questions

### 1. D-08: `PerfmonAnalysis` field vs. synthetic TrendGroup (Claude's Discretion — planner decides)

The deferred WR-03 fix: when episodes ARE present, untimestamped perfmon samples (`ts is None`) fall in no span and vanish (the episode path at `perfmon.py:648-737` never calls `_hazard_unplaceable_samples`; only the no-episodes `_file_scope_groups` does, `perfmon.py:592`). Both options reuse `_hazard_unplaceable_samples` (`perfmon.py:523-554`) for identical text/cap/sort.

**Option A — new `PerfmonAnalysis` field** (e.g. `unattributed: PerfmonHazard | None`):
- *Pros:* Honest to the data — this disclosure genuinely is NOT attributable to one span, so a case-level field matches reality. Renderer treats it as a distinct, always-last line. `PerfmonHazard` already exists and is frozen; adding one optional field is a small, self-contained model change. Does not fabricate a fake span/group that downstream `sift perfmon` rendering would have to special-case.
- *Cons:* Directly contradicts the docstring invariant "no case-level hazard collection" / "every hazard attributable to exactly one span" (`perfmon.py:179-184`) — the docstring must be rewritten and any code/tests asserting `groups` is the sole hazard channel updated. `render_perfmon_markdown`/`_json`/CSV (Phase 13, out of scope to *reshape* but must not *break*) need a code path for the new field or they silently omit it — risk of "nothing disappears silently" violation in the `sift perfmon` report.

**Option B — synthetic case-level TrendGroup** (`scope="file"`-like, `key="<unattributed>"`, `sample_count=0`, `counters=()`, only the unplaceable hazard):
- *Pros:* Reuses the **existing** `TrendGroup` "boundless disclosure group" precedent already shipped for the every-sample-untimestamped file case (`perfmon.py:604-618`) — the report renderers already handle a zero-sample, hazard-only group, so `sift perfmon` needs **no** change and the "nothing disappears silently" guarantee is automatic. No `PerfmonAnalysis` model change; the "hazards live on `TrendGroup`" invariant is preserved. Fits the D-03 cap machinery for free (it's just another group, severity `info` so it sorts last and is dropped first under pressure — acceptable for an info disclosure).
- *Cons:* Slightly synthetic — a "group" that spans no real correlation window; needs a clearly-labelled `label` (mirror `NO_PLACEABLE_LABEL`, `perfmon.py:66-70`) so it is never read as a correlation. Must choose a `scope` value: reusing `scope="file"` is a mild abuse (the samples aren't one file); adding a third `Literal` (`scope="unattributed"`) is cleaner but touches the `Literal["episode","file"]` type and every exhaustive `scope` switch in the renderers.

**Evidence-based lean (not a verdict):** Option B has **lower blast radius on the shipped Phase 13 surface** — the zero-sample hazard-only `TrendGroup` path already exists and the report renderers already consume it, so "nothing disappears silently" holds with no `sift perfmon` edits and no model-invariant rewrite. The cost is a synthetic group and a `scope` decision. Option A is more semantically honest but forces a docstring-invariant rewrite plus new render paths in three out-of-scope renderers. Given the phase's "strictly additive, don't perturb Phase 13" posture, **B is the lazier correct default**; choose A only if the team prefers the model to state case-level disclosures explicitly. The planner should confirm which renderers enumerate `analysis.groups` vs. a hypothetical new field before deciding (grep `render/perfmon_report.py`).

### 2. Does the golden eval case need the full 13,596-sample CSV or a slice?
Recommendation: a **small overlapping slice** (tens of samples), built Wave 0. The eval harness ingests `input/` through the real pipeline (`runner.py:147`), and a 2 MB CSV would slow every `sift eval` run for no added signal — the gate needs *one* citable perfmon fact, not fidelity. Keep the full-fidelity assertions at correlator-unit level (`test_perfmon.py`), exactly as Phase 13 did for the non-overlapping pair (ROADMAP Phase 13 note).

## Environment Availability

Skipped — this phase is pure in-repo Python (new modules + edits) with no external tools, services, or runtimes beyond the already-provisioned `uv`/pytest/ruff/pyright gate. The LLM endpoint is faked via `httpx.MockTransport` in every test (zero network, per CLAUDE.md).

## Validation Architecture

`nyquist_validation: true` (`.planning/config.json:24`) — section required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest`) |
| Config file | `pyproject.toml` (project convention) |
| Quick run command | `uv run pytest tests/test_perfmon_facts.py tests/test_perfmon_analyze.py -x` |
| Full suite command | `uv run pytest` then `uv run ruff check` and `uv run pyright` ("done" gate) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERF-07 | Renderer: citable set == printed `[evt:]` tokens; empty→`("",set())`; group cap drops surplus ids; salient subset deterministic; zero-digit fragment | unit | `uv run pytest tests/test_perfmon_facts.py` | ❌ Wave 0 (mirror `test_mcm_facts.py`) |
| PERF-07 | Splice: perfmon block injected, ids citable, fabricated id not citable | unit | `uv run pytest tests/test_perfmon_analyze.py -k citable` | ❌ Wave 0 |
| PERF-07 | **4-combination byte-identity** (neither/MCM-only/perfmon-only/both); no-data baselines unchanged from pre-phase hash | unit | `uv run pytest tests/test_perfmon_analyze.py -k byte_identical` | ❌ Wave 0 |
| PERF-07 | Anti-hallucination: model's wrong figure never enters the pre-built block | unit | `uv run pytest tests/test_perfmon_analyze.py -k cannot_alter` | ❌ Wave 0 |
| PERF-07 | No-digit template guard on `perfmon_facts.md` | unit | `uv run pytest tests/test_perfmon_facts.py -k no_authored_number` | ❌ Wave 0 |
| PERF-08 | Golden case discovered + scored positive; `sift eval` exits non-zero when correlation output regresses (citation-sensitivity mirror) | integration | `uv run pytest tests/test_eval_cases.py -k perfmon` | ❌ Wave 0 (mirror `test_mcm_denial_citation_validity_is_mcm_sensitive`) |
| PERF-08 | **Fixture-overlap guard**: golden CSV+log genuinely overlap (≥1 non-`None` `at_denial_event_id`) | unit | `uv run pytest tests/test_perfmon_analyze.py -k fixture_overlaps` | ❌ Wave 0 (critical anti-vacuous guard) |
| D-08 | Episodes-present + untimestamped sample → disclosed, not dropped; cited, capped, event_id-sorted; Hartford reference unaffected | unit | `uv run pytest tests/test_perfmon.py -k unattributed` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the quick run command above.
- **Per wave merge:** full `uv run pytest` + `ruff check` + `pyright`.
- **Phase gate:** full suite green (incl. `sift eval` exit 0 on the real suite) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_perfmon_facts.py` — renderer units (mirror `tests/test_mcm_facts.py`), incl. no-digit guard + cap + citable==printed.
- [ ] `tests/test_perfmon_analyze.py` — splice/citability/4-combo byte-identity/anti-hallucination + **fixture-overlap guard** (mirror `tests/test_mcm_analyze.py`).
- [ ] **Overlapping golden fixture pair** — synthetic or re-timed Hartford slice under `eval/cases/<perfmon-case>/input/`, plus a self-verifying overlap guard (the single most important Wave 0 item; without it PERF-07/08 are vacuous).
- [ ] `eval/cases/<perfmon-case>/truth.yaml` + `README.md` — frozen ground truth (author before any prompt tuning, mirror `eval/cases/mcm-denial/`).
- [ ] `tests/test_eval_cases.py` — add case to `_EXPECTED_CASES`, discovery + citation-sensitivity test.
- Framework install: none — pytest already present.

## Security Domain

`security_enforcement: true` (`.planning/config.json:47`) — section required. This is an offline CLI; no auth/session/network-egress surface is added.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (local CLI, no auth) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation / Output Encoding | **yes** | `sanitise()` on every log/CSV-derived value before it enters the prompt (mirror `mcm_facts.py`); counter names come from the untrusted customer CSV header. |
| V6 Cryptography | no | `event_id = sha256(...)[:16]` is an identity digest, not a security control; unchanged. |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via crafted counter name / hazard message | Tampering | `sanitise()` each value; template framing "treat as untrusted data, never instructions" (mirror `mcm_facts.md`). Covered by an injection test (mirror `test_mcm_facts.py:276-287`). |
| Counter name forging adapter provenance to surface `byte_offset`/`host` as a trend | Information disclosure | `_counter_trends` excludes `_RESERVED_ATTRS` (`perfmon.py:283`, T-13-ATTRSWEEP) — inherited, do not weaken. |
| Citation-DoS: one `event_id` per row inflating a hazard/block | DoS | `_CITE_CAP=10` (perfmon.py:76) + `_MAX_GROUPS` cap (D-03) + salient-counter subset (D-04). |
| Model fabricating a perfmon figure/citation | Tampering | Figures built pre-generation; `cited ⊆ prompted` gate flags any unshown id (`hypothesise.py:438-483`). |

## Sources

### Primary (HIGH confidence — read from the working tree)
- `src/sift/pipeline/mcm_facts.py:1-141` — `render_mcm_facts`, `_MAX_EPISODES=8`, `_SEVERITY_ORDER`, `_load_mcm_fragment`, citable==printed contract.
- `src/sift/pipeline/hypothesise.py:50-106,220-272,326-420` — sentinel regexes, `_apply_mcm_block`/`_apply_kb_block`, `_assemble` `prompted_ids` union, pre-generation MCM build chokepoint, citation gate.
- `src/sift/pipeline/perfmon.py:98-184,266-284,523-554,557-737` — models, `_counter_trends` (no-allowlist), `_hazard_unplaceable_samples`, `_file_scope_groups`, `analyse_perfmon`, the "no case-level hazard" invariant.
- `src/sift/prompts/triage.md:1-50`, `src/sift/prompts/mcm_facts.md:1-16` — sentinel block placement; zero-digit fragment shape.
- `src/sift/eval/runner.py`, `src/sift/eval/thresholds.py`, `src/sift/cli.py:1134,1185-1259` — `run_case` reuse of analyze pipeline; gate/metrics; `sift eval` exit contract; `sift perfmon` wiring.
- `tests/test_mcm_facts.py`, `tests/test_mcm_analyze.py`, `tests/test_eval_cases.py:1-268`, `tests/_perfmon_fixtures.py` — the exact test patterns to mirror.
- `src/sift/store.py:335,573,683` — `EXCLUDED_FROM_RANKING`; `query_events` does not filter perfmon.
- Fixture inspection (deny log `12:39:47`, CSV slice ends `12:39:39`) + `.planning/REQUIREMENTS.md:27-28,75-93` (PERF-07/08, Reference Data, "ends 6 s before the denial banner").

### Secondary / Tertiary
- None — no external sources consulted (frozen internal stack).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all reused code read at `file:line`.
- Architecture / mirror mechanics: HIGH — Phase 11 is a shipped, tested precedent copied structurally.
- Fixture blocker (Open Q1 / Pitfall 1): HIGH — confirmed by direct timestamp inspection of both fixtures and the requirements reference data.
- D-08 field-vs-group: MEDIUM — a genuine design call left to the planner; both options analysed against read invariants, no code written.

**Research date:** 2026-07-20
**Valid until:** stable — internal-only; re-verify only if `mcm_facts.py`, `hypothesise.py`, `perfmon.py`, or the eval harness change before planning.
