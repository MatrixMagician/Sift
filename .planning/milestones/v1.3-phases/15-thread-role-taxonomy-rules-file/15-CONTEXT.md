# Phase 15: Thread-Role Taxonomy & Rules File - Context

**Gathered:** 2026-07-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Every thread in an eu-stack dump carries a deterministic role — `idle-parked`,
`blocked-on-external`, `blocked-on-lock`, `running` or `unclassified` — produced by a versioned
TOML rules file an engineer can edit without touching Python or reinstalling. Frames matching no
rule are counted and reported, never guessed into a known role.

Requirements: **EUS-01, EUS-02**.

This phase delivers the classifier and its rules file as a **library module plus tests**. It does
**not** deliver a CLI command (`sift eustack` belongs to Phase 17), saturation or contention
analysis (Phase 16), multi-dump progression (Phase 17), fact injection (Phase 18), or ranking
exclusion (Phase 19).

</domain>

<decisions>
## Implementation Decisions

Decisions already locked before this discussion — carried in from `.planning/REQUIREMENTS.md`
"Decisions folded into these requirements" and the v1.3 research pass. **Do not re-litigate:**

- Roles come from a hand-curated versioned rules file, never LLM classification. The deterministic
  core computes; the model only narrates.
- The rules file is **TOML**, not Markdown tables or YAML (`|` is the Markdown table delimiter and
  `operator||` is a real C++ symbol; TOML literal strings need zero escaping for `<`, `>`, `::`,
  `&`; stdlib `tomllib` is already imported at `src/sift/config.py:15`, so no new dependency).
- Classification reads **`Event.raw`**, not `Event.message` — `src/sift/adapters/eustack.py:151`
  caps `message` at `CONDENSED_FRAMES = 5` and the classifying frame sits 8–19 deep.
- Classification keys on the **enclosing application frame**, not the leaf alone. A leaf-only rules
  file misclassifies every idle pool as blocked — the measured 98.9% false positive.
- Work scales with **distinct stack signatures (93)**, not thread count (3,902).
- Packaging mirrors `src/sift/prompts/`: a new `src/sift/rules/` package loaded through
  `importlib.resources`, with a `[eustack] rules_path` config key as the user override.
- Deadlock detection is a **permanent non-goal** — eu-stack carries no monitor-ownership edges, so
  a wait-for graph cannot be constructed. Sift must never emit the word "deadlock".

### Frame-matching strategy

- **D-01:** Matching is **rule-major, first-match-wins in file order**: for each rule in file
  order, scan every frame `#0`→`#N`; the first rule matching anywhere wins. Row position in the
  TOML file **is** the precedence knob — no `priority` field. This is the only loop order under
  which success criterion 2 ("engineer edits the file and sees threads change role") is
  predictable, and the only one where a curator can place
  `MSIQTask::GetNextPreferredJob → idle-parked` above a libc-wait rule and have the 44% population
  read correctly. Rejected: frame-major leaf-outward (makes stack depth the precedence, so editing
  the file cannot reorder outcomes, and `pthread_cond_timedwait` at `#0` wins before the
  application frame at `#8` is reached); deepest-application-frame-first (requires an
  `is_app_frame()` predicate, a second implicit taxonomy hardcoded in Python and not editable in
  the rules file). — **Reversibility:** costly — changing loop order after Phases 16–19 build on it
  silently reclassifies every population and invalidates the golden fixtures EUS-12 gates on.

- **D-02:** **`running` is a rule-matched role like the other three.** `unclassified` is the sole
  residual, and its rate is the rules-drift signal. Rules for `running` cover the frames the 44
  changed threads actually showed: `_shi_allocBlock`, `_shi_allocVar`, `MemAllocPtr`,
  `CDSSSubsetEngine::GenCube`, `MCE::GetBaseRIbyID`. Rejected: `running` as the residual default —
  it would silently label every unrecognised stack as working (the guess EUS-02 forbids) and drive
  the unclassified count to near-zero, hiding the drift signal criterion 3 exists to expose.

- **D-03:** A **signature** is the full ordered tuple of normalised frame symbols, full depth,
  **instruction addresses excluded**. Classification is memoised per signature; threads fan out by
  count. Addresses must be excluded — Phase 19 criterion 3 requires classification to survive
  differing instruction addresses under cosmetic mutation. Full depth reproduces the measured 93
  signatures, and the same tuple is what Phase 16's signature-collapse ranking (EUS-06) consumes,
  so it is computed once here rather than twice. Rejected: depth-capped (the cap would be an
  authored number with no evidence — max observed depth is 19 — and `MAX_EVENT_LINES = 256` at
  `src/sift/adapters/eustack.py:47` already bounds what can arrive); leading-N-frames (collapses
  stacks differing only below the cap, which is exactly where the role lives).

- **D-04:** Classifying one signature returns **role + subsystem + matched pattern text + frame
  index**. Pattern **text**, not row index, so reordering the file does not change what a
  previously-reported result means. This makes "why did this thread read as idle-parked?"
  answerable from output alone — needed for criterion 2, and consumed by Phase 17's report and
  Phase 18's citation work. Rejected: role only (an engineer cannot confirm the rule they edited is
  the one that fired — the silent-guesser failure of `PITFALLS.md` Pitfall 3); full match trace
  (loses the early exit, turning the cheap ~353K-comparison budget into a full cross product, for a
  field nothing in Phases 16–19 consumes).

### Symbol normalisation

- **D-05:** `normalise(symbol)` strips **`@@GLIBC_x.y.z`-style version suffixes** and any
  ` - <lib> <src>:<line>` tail. It **keeps template argument lists**. Measured on the reference
  capture during this discussion: 3,552 frames carry `@@GLIBC` suffixes across only 3 distinct
  symbols (`pthread_cond_timedwait@@GLIBC_2.3.2`, `pthread_cond_wait@@GLIBC_2.3.2`,
  `__libc_start_main@@GLIBC_2.34`); 2,962 frames carry template arguments; 0 frames carry the
  ` - <lib>` tail (that path is defensive here); 0 frames are unresolved. Signature counts measured
  under each variant: raw **93**, GLIBC-stripped **93**, templates-stripped **88**, both **88**.
  Keeping templates preserves the 93 the roadmap cites and keeps report text faithful to the
  capture; template variance across builds is already handled by a `contains` rule on the pre-`<`
  prefix, so no lossy transform is needed. Rejected: also stripping templates (collapses 93→88
  signatures and 374→363 distinct symbols); no normalisation (a host with a different glibc drops
  every libc-anchored rule to unclassified with no diagnostic — the silent cross-build drift
  `PITFALLS.md` Pitfall 3 is written about).

- **D-06:** A rules-file pattern that is **not already normalised is rejected loudly at load**,
  with the canonical form in the error message. Follows the house discipline of failing at load
  time rather than silently at classification time (`McmThresholdsConfig`'s `extra="forbid"` at
  `src/sift/config.py:106`). Rejected: silent normalisation (lets two spellings of one rule live in
  the file, so a diff no longer tells you what is compared); matching patterns raw (a pasted
  `pthread_cond_timedwait@@GLIBC_2.3.2` matches nothing with no error — the rule looks present and
  is dead).

- **D-07:** An **unresolvable frame** (`??` or a bare address) **stays in the signature tuple** —
  it is part of the stack's identity — but is **never a match candidate**. A thread whose frames
  are all unresolvable is counted as its own reported category, `no resolvable frame`, **distinct
  from `matched no rule`**. `PITFALLS.md:120-122` asks for exactly this split; it keeps the
  unclassified rate readable as a rules-drift signal rather than a symbols-missing signal — two
  different problems with two different fixes (curate a rule vs obtain symbols). Rejected: one
  unresolved frame condemning the whole thread (throws away a stack with a clear application frame
  at `#8`); dropping unresolved frames entirely (collapses stacks differing only in what resolved,
  and the report can no longer state how much of the capture lacked symbols).

- **D-08:** The frame-splitting regex is **shared, not copied**. Expose a small
  `iter_frames(raw) -> Iterator[tuple[int, str]]` helper from `src/sift/adapters/eustack.py` built
  on the existing `_FRAME_RE` (`eustack.py:57`); the classifier imports it. Direct precedent in
  that same file: `byte_lines` is imported from `genericlog` with the comment "to avoid a drifting
  verbatim copy" (`eustack.py:45-46`). Rejected: the classifier owning its own regex (two regexes
  for one format, drift invisible until a format variant makes them disagree); the adapter writing
  frames into `Event.attrs` at ingest (changes the shipped adapter's output shape, inflates every
  stored event, and forces a re-ingest of existing cases — beyond this phase's boundary).

### Rules-file schema

- **D-09:** Match kinds are **`exact` / `prefix` / `contains`**, dispatched to `==` /
  `str.startswith` / `in`. **Omitting `match` means `exact`.** Looseness is therefore never
  accidental — it is always a word a curator typed and a reviewer can `grep 'match ='` for. This is
  the ADR 0013 lesson translated honestly: that ADR's `"MCM"` was 3 characters matched against
  64 KB of arbitrary content, whereas a pattern here is matched against one symbol of tens of
  characters, so the risk is real but smaller. `contains` stays available because template-bearing
  symbols like `MTimer::Timer<...>::Run()` genuinely need it once template args are kept (D-05).
  `fnmatch` is the documented escape hatch if globbing is ever needed — **do not add it now**
  (`STACK.md:75-80`). Rejected: `contains` as the default (every terse rule silently the loosest
  kind); `exact`/`prefix` only (2,962 template-bearing frames become awkward to match).

- **D-10:** Each `[[rule]]` carries a **required `subsystem`** field — `job-queue`, `evaluation`,
  `command-queue`, `warehouse`, `http`, `ipc`, and so on. Phase 16 groups by `(role, subsystem)`:
  per-pool occupancy (EUS-03) is that pairing inside `idle-parked`/`running`, and external-wait
  split by dependency (EUS-05) is the same pairing inside `blocked-on-external`. One field feeds
  both, and requiring it means Phase 16 never meets a null and every curated rule has declared
  where it belongs. Rejected: separate `pool` and `dependency` fields (each null for most roles,
  and "which one do I fill in?" on every new rule); role-only (Phase 16 would edit every rule to
  backfill, and the taxonomy would ship knowing it is incomplete).

- **D-11:** The file carries a top-level **`[meta]` table with `version` and `validated_against`**
  (the MicroStrategy build(s) and glibc the rules were validated on) — the cross-build drift
  diagnosis `PITFALLS.md:123-125` asks for, which can come from nowhere but the file. The loader
  also computes `sha256(text)[:16]` — the idiom already behind `cluster_label_prompt_hash` — and
  exposes it on the loaded object. **Writing it via `store.set_meta("eustack_rules_hash", ...)` is
  deferred to Phase 17**, where a command with a case to write to exists;
  `ARCHITECTURE.md:205-219` specifies unconditional-overwrite semantics for that write when it
  lands. Rejected: doing the store write here (acquires a store dependency this phase does not
  otherwise need, with no reader until Phase 17); no file metadata (a report could not state which
  build the rules were validated against, and a user running a copy via `[eustack] rules_path` has
  no git history at all).

- **D-12:** The loader is **strict Pydantic**: `extra="forbid"`, `role` constrained to a `Literal`
  of the **four rule-assignable buckets**, empty patterns rejected, and a duplicate
  `(match, pattern)` pair rejected as a dead rule — under D-01's rule-major first-match-wins the
  second copy is provably unreachable whatever role it claims. **`unclassified` is illegal as a
  rule role**: it is the residual by definition, so a rule asserting it would be a rule that
  matches and then claims not to have matched. Rejected: free-form role string (the five buckets
  stop partitioning the population, breaking success criterion 1); permissive dict parse (a
  misspelt `rol =` silently yields a rule that never fires — failing at classification time instead
  of load time).

### Output surface and layout

- **D-13:** Phase 15 ships a **library module plus fixture tests — no CLI command.** Direct
  precedent in this project: v1.1 split Phase 9 (MCM episode detection, compute-only) from Phase 10
  (`sift mcm` report + CSV), and v1.2 split Phase 12 (adapter + exclusion) from Phase 13
  (`sift perfmon`). This keeps `sift eustack` owned by one phase rather than grown by three, and
  leaves the roadmap's command allocation intact. Criterion 2 is asserted directly: edit the TOML,
  re-run the classifier, the population moves. Rejected: a minimal `sift eustack` now (three phases
  editing one command signature, and Phase 17's title would stop describing what Phase 17 does);
  surfacing through `sift show`/`sift ingest` (puts Phase 16's figures where Phase 17 must then
  move them from).

- **D-14:** CI runs against a **signature-preserving derivative fixture** — all 93 distinct
  signatures with per-signature thread counts capped (roughly 80 KB, inside this repo's fixture
  norms; the largest committed fixture today is 13 KB). Criterion 5's **93 reproduces exactly in
  CI**. Criterion 4's 1,715 and the 3,902 thread total are measured against the full out-of-repo
  capture at phase verification and recorded in the phase summary — exactly how ADR 0013 handled
  its 11-file out-of-repo corpus. The derivative's filename and PID must be sanitised; the frames
  themselves are C++ symbols and carry no identifiers. Rejected: committing the full 2.4 MB capture
  (180× the largest existing fixture, and it carries a customer environment identifier — awkward in
  a tool whose premise is not shipping customer diagnostics anywhere); a hand-authored synthetic
  fixture only (a fixture authored to match the detector, the named failure mode in `PITFALLS.md`
  that EUS-12 guards against, proving nothing about the real 93-signature population).

- **D-15:** Unclassified output is **per unclassified signature, ranked by thread count**, each
  entry carrying its thread count and its frames. Classification is signature-keyed anyway so this
  is free, and it is the artefact a curator needs: "these 212 threads share one unrecognised shape,
  write this rule next". **Full list, not a top-N** — it is bounded by signature count, and any
  capping is Phase 17's rendering decision to make visibly (the no-silent-caps principle).
  Rejected: an aggregate count plus one example frame (names one shape and hides the rest, making
  curation whack-a-mole); per unmatched frame symbol (a symbol inside a stack another frame
  classified is not a gap, so the list mixes gaps with noise).

- **D-16:** File layout — `src/sift/rules/` holds `__init__.py` and `eustack_roles.toml` as **pure
  package data**, mirroring `src/sift/prompts/` exactly. Everything executable (Pydantic models,
  loader, normaliser, classifier) lives in **`src/sift/pipeline/eustack.py`**, the single-module
  shape `mcm.py` and `perfmon.py` already have. Plus an `EustackConfig` in `src/sift/config.py`
  carrying `rules_path`, mirroring `McmConfig` (`config.py:116-121`), and the `iter_frames()`
  addition to `src/sift/adapters/eustack.py` from D-08. Rejected: splitting the loader into
  `sift/rules/loader.py` (`sift/prompts/` is pure data with no code, so this would make
  `sift/rules/` the first mixed package, and `mcm.py`/`perfmon.py` show the codebase's answer is
  one module per analysis); putting the TOML in `src/sift/pipeline/` (package-data globs and
  `importlib.resources` reaching into a code package, complicating the packaging Phase 8 settled).

### Claude's Discretion

No area was delegated with "you decide". Three questions were raised and explicitly not taken up —
they are open for the planner to settle with normal judgement:

- How many rules the initial curated `eustack_roles.toml` carries, and which subsystems it must
  cover on day one. The reference capture's top ten signatures
  (`MILESTONE-CONTEXT-v1.3.md:79-90`) are the obvious floor.
- Whether `[eustack] rules_path` needs a path-traversal or containment guard.
- Whether an ADR is written this phase for D-01 (rule-major first-match-wins) and D-05
  (normalisation policy), or folded into a single v1.3 eu-stack ADR later.
  `.planning/REQUIREMENTS.md:66` says each folded decision needs an ADR in `docs/decisions/`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope and locked decisions
- `.planning/REQUIREMENTS.md` — EUS-01 and EUS-02 wording; the "Decisions folded into these
  requirements" table (every row is locked, each needs an ADR); the "Out of Scope" table naming
  deadlock detection as a permanent non-goal
- `.planning/ROADMAP.md` §"Phase 15: Thread-Role Taxonomy & Rules File" — goal, the five success
  criteria, and the research flag naming frame-matching strategy as unresolved

### Measured evidence — do not contradict, research around
- `.planning/research/MILESTONE-CONTEXT-v1.3.md` — the reference capture's measured structure;
  §"THE CRITICAL FINDING" (identical-stack-after-60s is inverted, 98.9% on a healthy server);
  lines 79-90, the top-ten signature table that seeds the initial rules file
- `.planning/research/SUMMARY.md` §"Unresolved Questions" #3 — match precedence, resolved here by
  D-01

### Design guidance
- `.planning/research/STACK.md` §(a) TOML rules-file format, §(b) plain `str` matching over `re`
  and tries (with the measured 93 × 19 × 200 workload arithmetic), and the `fnmatch` escape-hatch
  note at lines 75-80
- `.planning/research/ARCHITECTURE.md` §2 lines 155-219 — `src/sift/rules/` packaging, the
  `[eustack] rules_path` override, and the rules-hash-into-`meta` recommendation deferred by D-11
- `.planning/research/PITFALLS.md` §"Pitfall 3: Symbol brittleness" lines 99-134 — the normalisation
  and unresolved-frame requirements behind D-05 and D-07

### Precedent to mirror
- `docs/decisions/0013-dsserrors-qualified-mcm-sniff.md` — the bare-substring collision class D-09
  guards against, and the out-of-repo-corpus measurement style D-14 follows
- `docs/decisions/0014-embedding-determinism-scope.md` — the "record the knobs" provenance pattern
  behind D-11
- `src/sift/adapters/eustack.py` — `_FRAME_RE` (line 57), `CONDENSED_FRAMES = 5` (line 51),
  `MAX_EVENT_LINES` (line 47), and the `byte_lines`-shared-from-`genericlog` precedent (lines 45-46)
- `src/sift/pipeline/mcm.py`, `src/sift/pipeline/perfmon.py` — the single-module-per-analysis shape
  D-16 follows
- `src/sift/config.py` lines 94-121 — `McmThresholdsConfig` / `McmConfig`, the `extra="forbid"`
  and nested-config-key shapes D-10 and D-12 mirror
- `src/sift/prompts/__init__.py` — the pure-data package + `importlib.resources` pattern
  `src/sift/rules/` copies

### Reference data (out of repo, not committed)
- `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/` — two native eu-stack dumps of PID
  1363967 captured 60 s apart. Source for the D-14 derivative fixture and for the verification-time
  measurements of criteria 4 and 5

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sift/adapters/eustack.py:57` `_FRAME_RE` — the frame regex the classifier reuses via the new
  `iter_frames()` helper (D-08). Already anchored and linear-scan, per the file's own no-ReDoS
  convention.
- `src/sift/config.py:15` `tomllib` — already imported for `config.toml`; the rules loader adds no
  dependency.
- `src/sift/config.py:94-121` `McmThresholdsConfig` / `McmConfig` — the `extra="forbid"` discipline
  and the nested-config-key shape `EustackConfig` copies.
- `src/sift/prompts/__init__.py` + `importlib.resources.files(...)` usage in
  `pipeline/mcm_facts.py:77`, `pipeline/perfmon_facts.py:101`, `pipeline/cluster.py:210` — the
  package-data loading idiom `src/sift/rules/` reuses verbatim.
- `sha256(text)[:16]` as used for `cluster_label_prompt_hash` — the content-hash idiom D-11 reuses.

### Established Patterns
- **Compute phase before command phase.** Phase 9→10 (MCM) and Phase 12→13 (perfmon) both shipped
  the deterministic analysis a phase ahead of its CLI surface. D-13 follows.
- **One module per analysis.** `pipeline/mcm.py` and `pipeline/perfmon.py` each hold models,
  detection and computation in a single file. `pipeline/eustack.py` matches.
- **Fail at load, not at use.** Every config surface in the codebase uses `extra="forbid"` so a
  typo is a load-time error. D-06 and D-12 extend it to the rules file.
- **Never copy a parser.** `eustack.py:45-46` imports `byte_lines` from `genericlog` explicitly to
  avoid a drifting verbatim copy. D-08 applies the same rule to `_FRAME_RE`.
- **Small committed fixtures, real corpus measured out of repo.** Largest committed fixture is
  13 KB; ADR 0013's evidence came from an 11-file out-of-repo corpus. D-14 follows both halves.

### Integration Points
- `src/sift/adapters/eustack.py` gains `iter_frames()` — the only edit to shipped ingestion code,
  and it is additive (no change to `parse()` output, no re-ingest needed).
- `src/sift/config.py` gains `EustackConfig` with `rules_path`, wired into `SiftConfig`
  (`config.py:124`) and the existing CLI > env > file > default precedence.
- `pyproject.toml` package data must include `src/sift/rules/*.toml` — verify against
  `tests/test_packaging.py`, which already guards the prompts equivalent.
- **Consumed by Phase 16:** the `(role, subsystem)` pairing (D-10) and the signature tuple (D-03)
  are the inputs EUS-03/EUS-05/EUS-06 group over. **Consumed by Phase 17:** the rules content hash
  (D-11) and the unclassified-per-signature list (D-15). **Consumed by Phase 18:** the matched
  pattern + frame index (D-04) for aggregate-fact citation.

</code_context>

<specifics>
## Specific Ideas

- The 1,715 `MSIQTask::GetNextPreferredJob` threads (44% of the capture) reading as `idle-parked`
  rather than blocked is the phase's headline acceptance check — it is the exact composition-blind
  false positive v1.3 exists to eliminate. It sits under `Semaphore::SmartLock::WaitForResource`,
  itself under a libc wait leaf, which is why D-01's loop order is load-bearing rather than
  stylistic.
- Rule rows should read like the `STACK.md:38-44` example: `role`, `subsystem`, optional `match`,
  and a single-quoted TOML literal `pattern` needing no escaping.
- The `blocked-on-lock` rules should anchor on `__lll_lock_wait` — glibc reaches it only on the
  contended futex slow path, making it the one sound single-leaf contention signal. All such
  findings stay ownership-blind.

</specifics>

<deferred>
## Deferred Ideas

- **Graded saturation thresholds** ("N% busy = warning") — already backlogged as EUSV2-03; research
  explicitly declined to invent numbers with no authoritative source.
- **`/proc/<tid>/stat` state codes** alongside eu-stack frames — backlogged as EUSV2-02; needs a
  capture-pipeline change outside this milestone's ingestion format.
- **Symbol re-demangling of stripped binaries** — permanently out of scope; absent symbols degrade
  to the D-07 `no resolvable frame` category, never guessed.

### Reviewed Todos (not folded)
- `2026-07-21-embedding-batch-composition-determinism.md` — matched on generic keywords only; it
  already carries `resolves_phase: 20` (DET-01 / SEED-002) and belongs there.
- `2026-07-21-generation-context-unset.md` — matched on the word "toml" alone; it concerns
  `generation.context` and the prompt budget, unrelated to thread classification.

</deferred>

---

*Phase: 15-thread-role-taxonomy-rules-file*
*Context gathered: 2026-07-25*
