# Architecture Research — v1.3 EU-Stack Integration

**Domain:** Integration of a new analysis layer into an existing deterministic-core-then-LLM
incident triage pipeline (Sift, Python/SQLite/local-LLM)
**Researched:** 2026-07-25
**Confidence:** HIGH (every claim below is verified against the actual v1.2 source, not inferred
from module names or docs)

## Executive verdicts (for the planner)

1. **Sibling module, not shared abstraction.** `pipeline/eustack.py` (analysis) is a third
   `mcm.py`/`perfmon.py`-shaped module. No shared base class. See §1.
2. **Rules file mirrors `prompts/*.md` exactly**: `src/sift/rules/eustack_roles.toml` (a new
   package sibling to `prompts/`), loaded via `importlib.resources`, versioned by content hash
   recorded in case `meta`. User override via `~/.config/sift/` is a new, narrow mechanism —
   recommend a single config key (`eustack.rules_path`), not a second lookup layer. See §2.
3. **`EXCLUDED_FROM_RANKING` should gain `"eustack"`.** Removing genuinely useful eu-stack-only
   clustering behaviour is a real cost, but it is a cost `sift eustack` (the new standalone report)
   replaces directly — see §3 for the full argument and why the composition-dependent middle option
   is rejected outright.
4. **Multi-dump grouping keys on `source_file`, ordered by filename-embedded stamp advisory-only,
   never as `Event.ts`.** See §4.
5. **Fact injection is a fourth copy-paste of the MCM/perfmon block pattern** in
   `hypothesise.py` — four call sites, three regexes, one `_assemble` union. See §5.
6. **Vector reuse belongs in `cluster.py`, keyed on `template_id`, gated by the existing
   `embedding_dim`/`embedding_model` guards** plus a new explicit choice for the batch-knob
   question. See §6.
7. **Build order**: rules file + role classifier (no store dependency) → deterministic saturation
   analysis (pure, testable in isolation) → `EXCLUDED_FROM_RANKING` decision (store seam, one-line
   but must land before eval fixtures are authored) → `sift eustack` CLI + report (mirrors `mcm`)
   → fact renderer + `hypothesise.py` splice → SEED-002 vector reuse (independent, can run in
   parallel with the eustack work) → golden eval. See §7.

---

## 1. Module placement and shape

### What `mcm.py` and `perfmon.py` actually share

Read side by side, `src/sift/pipeline/mcm.py` (977 lines) and `src/sift/pipeline/perfmon.py`
(812 lines) share a *contract*, not reusable code:

| Shared contract element | Evidence |
|---|---|
| Typer-free, print-free, SQL-free, network-free | `mcm.py:1-9`, `perfmon.py:1-11` docstrings state it identically |
| Input is `list[Event]` from `store.query_events()`, never re-sorted (trusts D-06 canonical order) | `mcm.py:390-402` (`_line_stream`), `perfmon.py:259-284` (`_in_span` sorts *defensively*, not because input order is untrusted — see its own docstring on why it re-sorts anyway: WR-02, "a caller may have assembled in any order") |
| Every emitted figure carries the `event_id` it was parsed from (D-16 provenance) | `mcm.py:227-259` (`DiagnosticFlag.event_ids`, `AttributionRow.event_ids`), `perfmon.py:142` (`PerfmonHazard.event_ids`) |
| Frozen Pydantic models, `extra="forbid"` | every model class in both files |
| One composing entry point the CLI calls (`analyse_mcm`, `analyse_perfmon`) | `mcm.py:956-976`, `perfmon.py:712-811` |
| "Nothing disappears silently" — absence is a typed `None`/empty tuple, never a raised exception or a dropped row | `mcm.py:94-106` (`_get`), `perfmon.py:544-575` (`_hazard_unplaceable_samples`) |
| Deterministic ordering discipline: no `set` iteration, explicit sort keys, `dict.fromkeys` for dedup | `mcm.py:857` docstring, `perfmon.py:437` (`_cited`), both call out D-05/D-21 |
| Graded hazard/flag model with `severity: Literal["info","warn","critical"]`, a `message`, and `event_ids` | `mcm.DiagnosticFlag` (`mcm.py:221-238`) vs `perfmon.PerfmonHazard` (`perfmon.py:119-144`) |
| A "no signal detected" fallback that still returns a valid, renderable analysis (`episodes=()` / `groups=()`) | `mcm.py:297-306`, `perfmon.py:192-201` |

**But the two flag/hazard models are deliberately NOT unified**, and the reasoning is explicit in
the code, not an oversight: `perfmon.py:122-131` states outright that `mcm.DiagnosticFlag` is "not
reused" because its `value_pct` is *locked* as a ratio (`part/whole*100`, the machine-independence
invariant), while a perfmon hazard's figure is "an absolute counter reading or nothing at all" —
different value semantics, so a shared model would need an escape hatch (`value: float | None`
meaning two different things) that is worse than two small models. Similarly `perfmon.py:121-126`
notes `mcm._grade` (the two-cut-point severity grader, `mcm.py:609-624`) is deliberately not
called from perfmon — perfmon's hazards grade *structural* conditions (span resolved or not), not
ratios, so the grader has nothing to compare.

`perfmon.py` **does** import one real thing from `mcm.py`: `analyse_perfmon(analysis: McmAnalysis,
events)` takes the already-computed `McmAnalysis` as an argument (`perfmon.py:712`) and consumes
`EpisodeAnalysis`/`McmAnalysis` under `TYPE_CHECKING` (`perfmon.py:27`) — this is a genuine
*data* dependency (perfmon correlates against MCM's episode windows), not a shared base class or
mixin. There is no `BaseAnalyser`, no shared `Hazard` protocol, no shared "span resolution" helper
between the two files — each re-implements its own span/window logic because the window semantics
differ (MCM's `EpisodeWindow` is an AvailableMCM-descent threshold crossing; perfmon's `_Span` is a
timestamp-bounded interval).

### Verdict: sibling, not abstraction

Per the milestone-context instruction ("bias toward the sibling unless duplication is severe and
mechanical — an abstraction over two instances is usually premature, over three sometimes
justified"): the two existing instances share a *contract* (typed hazard/flag shape, provenance
discipline, ordering discipline) that is already enforced by convention and cross-referencing
docstrings, not by inheritance. The one place a genuine three-instance abstraction might tempt
someone — a shared `Hazard(dimension, severity, message, event_ids, value)` base — is exactly the
thing `perfmon.py:122-131` argues against for a *two*-instance case, and the eu-stack module adds a
*third* value semantic (a thread/pool *count*, not a ratio and not an absolute reading), which
would force the same model to serve three incompatible meanings of `value`. This is the "severe
and mechanical" bar failing to clear, not clearing it — a third parallel model
(`ThreadRoleFlag`/`SaturationHazard` or similar) is the correct call, following the same
`severity: Literal[...]`, `event_ids: tuple[str, ...]`, `message: str` shape by convention.

**New module: `src/sift/pipeline/eustack.py`** (analysis — distinct from the existing
`src/sift/adapters/eustack.py`, which is ingestion and is untouched by v1.3). Its public surface,
mirroring `analyse_mcm(events, thresholds) -> McmAnalysis` and
`analyse_perfmon(mcm_analysis, events) -> PerfmonAnalysis`:

```python
def analyse_eustack(events: list[Event], rules: ThreadRoleRules) -> EustackAnalysis
```

taking `list[Event]` filtered to `source == "eustack"` (mirroring `mcm.detect_episodes`'s
`dss = [e for e in events if e.source == "dsserrors"]` at `mcm.py:815`) and a loaded rules object
(§2), returning one frozen model tree: per-dump thread classifications, per-pool saturation
figures, and — when 2+ dumps are present — progression deltas. No episodes/windows exist in this
domain (no MCM-style denial marker to anchor on), so the composing entry point is flatter than
`analyse_mcm`: one call, no per-item sub-assembly loop, closer to `perfmon.py`'s `_file_scope_groups`
shape (one group per dump) than to `mcm.py`'s per-episode shape.

### The one thing that must NOT be reused from the adapter's output as-is

`adapters/eustack.py:150-152` builds the `Event.message` for a thread event as
`"\n".join(rec.frames)`, and `rec.frames` is capped at `CONDENSED_FRAMES = 5`
(`adapters/eustack.py:51,226-230`) — only the first five frames (innermost first, since eu-stack
frames are numbered `#0` = innermost outward). The milestone context's own classification signal
is the **deepest MicroStrategy frame** (e.g. 1,715 threads classify by `MSIQTask::GetNextPreferredJob`
appearing *under* `Semaphore::SmartLock::WaitForResource`), and the measured stack-depth histogram
shows most threads are 8–19 frames deep (`MILESTONE-CONTEXT-v1.3.md:66`) — deeper than the
condensed 5. **The role classifier cannot work off `Event.message`; it must re-parse `Event.raw`**,
exactly the way `mcm.py:390-402` (`_line_stream`) re-parses `event.raw` rather than trusting the
adapter's condensed `message` field. `adapters/eustack.py:171` confirms `raw` keeps every frame
line (`raw = "".join(rec.raw_parts)`, uncapped by `CONDENSED_FRAMES`), so the full stack is present
— it is simply not in `message`. This is a direct structural analogue of D-01 in `mcm.py`'s
docstring ("re-parse raw, never enrich the adapter").

---

## 2. Where the versioned rules file lives and how it loads

### How the existing prompt templates are packaged and loaded (the pattern to mirror)

- **Location:** `src/sift/prompts/*.md`, a real Python package (`src/sift/prompts/__init__.py`
  exists, 392 B).
- **Packaging:** `pyproject.toml` uses `uv_build` (`build-system.build-backend = "uv_build"`,
  `pyproject.toml:38-40`) with no explicit `package-data`/`include` stanza for `prompts/` — `.md`
  files under a package directory ship by default under `uv_build`'s convention (confirmed
  empirically: `cluster_label.md`, `mcm_facts.md`, `perfmon_facts.md`, `judge.md`, `triage.md` are
  all already loaded this way in shipped code with no extra packaging config).
- **Loading:** `importlib.resources.files(_PROMPT_PACKAGE).joinpath(_FILE).read_text(encoding="utf-8")`
  — identical idiom in `cluster.py:207-213` (`_load_template`), `mcm_facts.py:70-80`
  (`_load_mcm_fragment`), `perfmon_facts.py:94-104` (`_load_perfmon_fragment`), and
  `hypothesise.py:180-186` (`_load_triage_template`). Every one of these four functions is a
  ~5-line verbatim copy of the same three-call chain, with only the package/filename constants
  differing — this is the existing precedent for "small, repeated, not worth abstracting" that
  directly supports the §1 sibling verdict.
- **Versioning:** not a version *number* in the file — a **content hash** recorded in case `meta`.
  `cluster.py:216-218` (`_template_hash`) is `sha256(template)[:16]`, and `cluster.py:399`
  (`store.set_meta("cluster_label_prompt_hash", _template_hash(template))`) records it — the same
  `sha256(...)[:16]` idiom as `event_id`/`template_id`. There is no equivalent hash-recording call
  yet for `triage.md`, `mcm_facts.md` or `perfmon_facts.md` — only the cluster-label prompt is
  hash-pinned in `meta` today. This is worth flagging to the planner as a pattern gap, not
  something to silently fix: v1.3 should at minimum follow the *existing* `cluster_label_prompt_hash`
  precedent for its own new fragment, without being asked to retrofit the other three.
- **Editable without touching Python:** confirmed structurally — none of `mcm_facts.md`/
  `perfmon_facts.md` contain a single digit (their own docstrings assert a "no-digit guard test",
  `mcm_facts.md:1-6`, `perfmon_facts.md:1-7`), and all wording lives in the `.md`, all figures in
  Python.

### Applying this to the rules file

The eu-stack rules file is data (a frame-pattern → role/subsystem table), not prose glued around a
computed-figure slot like `mcm_facts.md` — so it is closer in *kind* to `cluster_label.md` (a
static template) than to the fact fragments, but it still wants the exact same packaging and
loading mechanism:

- **New package: `src/sift/rules/`** (sibling to `src/sift/prompts/`), with `__init__.py` and
  `eustack_roles.toml` (or `.md` — see below) as the shipped default. A new top-level package
  rather than cramming a data table into `src/sift/prompts/` keeps the naming honest: this is a
  classification table, not a prompt.
- **Format:** the milestone description ("hand-curated frame-pattern → role/subsystem table")
  reads more naturally as structured rows than as prose — recommend **TOML**, not Markdown, for the
  rules file itself, breaking from the `.md` convention deliberately. Justification: the project
  already treats TOML as its config format (`config.py`, `tomllib`, stdlib, zero new dependency —
  `pyproject.toml` has no `pyyaml`-for-config precedent; `pyyaml` is scoped M7-eval-only per
  `pyproject.toml:11-13`), and a frame-pattern table is naturally `[[rule]] pattern = "..." role =
  "..." subsystem = "..."` repeated blocks, which TOML expresses better than a Markdown table a
  regex has to re-parse. **Do not invent a bespoke line-based mini-format** — `tomllib` is already
  imported in `config.py:15` and is stdlib, so this costs zero new dependencies and reuses a parser
  already in the codebase. This is the one place this research disagrees with a literal
  ".md sibling" reading of "sibling to `sift/prompts/*.md`" — the *packaging and loading mechanism*
  should mirror the prompts exactly; the *file format inside the package* should not, because the
  content is tabular data, not natural-language prose, and TOML is boring, stdlib, and already used
  for exactly this kind of "labelled rows of config" shape (`McmThresholdsConfig`,
  `ClusteringConfig`).
- **Loading:** identical `importlib.resources.files("sift.rules").joinpath("eustack_roles.toml")`
  + `tomllib.loads(...)`, parsed once into a frozen Pydantic model list (mirroring
  `McmThresholdsConfig`'s `extra="forbid"` discipline) so a typo'd rule key fails loudly at load
  time, not silently at classification time — matching every other config surface in the codebase.

### User override

- **Location:** the existing config precedent is `config.py:184-192` — a single file at
  `$XDG_CONFIG_HOME/sift/config.toml` (defaulting to `~/.config/sift/config.toml`), read once by
  `load_config`. There is no existing precedent for a *second* file dropped loose into
  `~/.config/sift/` (e.g. a bare `eustack_roles.toml` sitting next to `config.toml`) — every
  existing user-supplied artefact is either a scalar/table **inside** `config.toml` (thresholds,
  timezones, adapters) or an explicit CLI-flag **path** to an arbitrary location (`--kb <dir>`,
  ADR 0009, which points anywhere the user chooses, not into `~/.config/sift/` specifically).
- **Recommendation:** add one new config key, `[eustack] rules_path` (optional, `str | None`,
  mirroring `McmConfig`'s `[mcm.thresholds]` wrapper shape at `config.py:116-121`), resolved through
  the same `load_config` precedence (CLI flag > `SIFT_*` env > `config.toml` > default). When unset,
  load the packaged default via `importlib.resources`; when set, `tomllib.loads(Path(rules_path)
  .read_text())` instead. This reuses the *existing* override mechanism (a config-file path field)
  rather than inventing a second "well-known loose file in `~/.config/sift/`" convention that has
  no precedent anywhere else in the codebase. Do **not** add a bare-filename-in-config-dir
  convention — it has no analogue in Sift today and would be the first of its kind for no clear
  gain over a config key.

### Recording rules-file version in case `meta` for provenance

Mirror ADR 0014's embedding-knob recording (`store.py:816-835`,
`record_embedding_batch_knobs`) exactly: **content-hash the resolved rules text** (packaged or
user-overridden — the hash does not care which) using the same `sha256(text)[:16]` idiom already
used for `cluster_label_prompt_hash`, and write it unconditionally via `store.set_meta(
"eustack_rules_hash", hash)` on every `sift eustack` / `sift analyze` run that touches eu-stack
data. Unconditional overwrite, no mismatch guard — like the batch knobs (`store.py:826-831`
explicitly contrasts this "legitimately varies between runs" semantics against
`record_embedding_identity`'s hard-fail guard) and *unlike* `embedding_dim`
(`store.py:770-796`, which hard-fails on mismatch because a dimension change invalidates existing
vectors). A rules-file edit does not invalidate anything already stored — it only changes how the
*next* run classifies threads — so overwrite semantics, not a guard, are correct. This gives a
divergent report ("why did this dump classify differently from last week's run of the same file?")
the same diagnosability ADR 0014 gives embedding-layout drift.

---

## 3. The `EXCLUDED_FROM_RANKING` decision

### What the seam actually does today

`store.py:335`: `EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon"})`. It has exactly
one production reader — `store.py:641-670` (`iter_event_summaries`), which excludes these sources
from the query every ranking stage inherits from: dedup, cluster exemplars, hypothesis excerpts,
and the eval runner (`store.py:649-654` names all four callers explicitly). The companion method
`iter_event_rows` (`store.py:672-703`) **deliberately does not** apply the filter — citation and
`show events` must never lose evidence, only ranking is held out (`store.py:683-689`). This
asymmetry is the whole feature: exclusion from **ranking**, never from **the store or citations**.
It is referenced in exactly four places in the codebase (`store.py:335`, two docstrings at
`store.py:647` and `store.py:683`, and the one usage at `store.py:659`) plus one deliberate
non-import note in `perfmon.py:271-272` ("`EXCLUDED_FROM_RANKING` is deliberately not imported [in
`_in_span`]: it means 'held out of ranking', which is a different concept from 'is a perfmon
sample'") — confirming the seam is intentionally narrow and single-purpose, not a general-purpose
source-kind flag reached for elsewhere.

### The two real options, with evidence

**Option A — add `"eustack"` to `EXCLUDED_FROM_RANKING`.**

- *What this removes*: the milestone context states an eu-stack-only case currently produces
  "~46 clusters and useful hypotheses" through the existing dedup→embed→HDBSCAN→salience path
  (reported evidence, not independently re-derived in this research pass — treat as measured
  input, not a repo artefact). That is real, already-working behaviour this option would delete
  for any case that previously benefited from it.
- *What replaces it*: `sift eustack` (§1, new standalone report) plus eu-stack facts into
  `sift analyze` (§5) is a **direct, better-targeted replacement** for exactly the value the
  milestone context says the clustering path was providing — the same composition signal
  ("3,902 threads collapse to 93 signatures, top signature = idle job-queue worker") is *already
  the deterministic-core output* v1.3 is building, computed once and cited, rather than
  rediscovered incidentally through embedding+HDBSCAN on masked thread-dump text. The milestone's
  own "critical finding" section (`MILESTONE-CONTEXT-v1.3.md:68-96`) is explicit that the
  stack-diffing/clustering-shaped read of this data is the wrong mechanism ("the intuitive
  mechanism is dead") — so the clustering path's "46 clusters" was working by incidental template
  grouping, not by the composition analysis the milestone is purpose-building. Losing the
  incidental path in favour of the purpose-built deterministic one is not a net loss of
  capability.
- *Named risk*: an eu-stack-only case with no other ranked source now produces **zero** clusters
  from `sift analyze`'s clustering stage, and the standalone `sift eustack` report becomes the
  only way to see thread-dump signal. If a user runs `sift analyze` alone (not `sift eustack`) on
  such a case expecting cluster-based hypotheses, they get nothing from clustering — mitigated by
  eu-stack facts flowing into `sift analyze`'s prompt directly (§5), so the *analyze* command still
  surfaces eu-stack signal, just not via the clustering/salience path.

**Option B — leave eu-stack events flowing through ranking (status quo, do nothing).**

- *What this keeps*: the "~46 clusters" behaviour on an eu-stack-only case, unchanged.
- *Named risk (the milestone's own framing)*: on a **joint** DSSErrors+eustack case, "thousands of
  near-identical thread events could dominate salience" — 3,903 near-duplicate template groups per
  dump is exactly the volume the `dssperfmon` exclusion (PERF-03) was built to prevent for a
  structurally identical reason: `store.py:327-332`'s own comment on why `dssperfmon` is excluded
  ("periodic observations, not diagnostics... thousands of near-identical rows would dominate
  template counts") describes eu-stack's `MSIQTask::GetNextPreferredJob`-under-`Semaphore::
  SmartLock::WaitForResource` idle-worker signature (1,715 of 3,902 threads, 44%,
  `MILESTONE-CONTEXT-v1.3.md:81`) almost word for word. This is the same failure mode PERF-03
  already exists to prevent, now reappearing at a *larger* per-dump volume (3,903 events vs
  perfmon's typically-smaller CSV row counts) in the one case (joint DSSErrors+eustack) v1.3 is
  explicitly meant to serve — a hang investigation with both a log and a stack dump is the primary
  target scenario, not an edge case.

### The composition-dependent third option — explicitly rejected

"Exclude only when another ranked source is present" would make cluster output depend on which
adapters happened to ingest into the case — the same case's `sift analyze` clustering behaviour
would differ between "eu-stack dump alone" and "eu-stack dump + one DSSErrors line", which directly
violates the determinism framing this project holds as load-bearing (`event_id` idempotence,
"identical case + config + model + seed → byte-identical JSON" — CLAUDE.md, PROJECT.md
Constraints). Determinism here is per-run reproducibility given fixed inputs, and case-composition-
dependent exclusion doesn't break *that* narrower guarantee — but it does break the more important
property PERF-03 established: **exclusion is a property of the source kind, not of the case or the
caller** (`store.py:333-334`'s own comment, "Owned here, never caller-supplied: exclusion is a
property of the source kind, not of the caller (D-07)"). A composition-dependent rule is exactly
the caller/context-dependent behaviour D-07 was written to rule out, and it means a user who adds a
second file to an existing case can watch their previously-shown eu-stack clusters silently vanish
from the *next* `sift analyze` run — a worse, harder-to-explain surprise than either A or B.
**Rejected on the same principle PERF-03 already encodes, not merely on cost.**

### Recommendation

**Add `"eustack"` to `EXCLUDED_FROM_RANKING`** (Option A) — a one-line change at `store.py:335`
(`frozenset({"dssperfmon", "eustack"})`) — **but only after** the deterministic saturation analysis
(§1) and its `sift eustack` report + `sift analyze` fact injection (§5) are built and shipped in
the *same* v1.3 milestone, so the "46 clusters" capability is replaced, not merely deleted, in the
same release. This is a sequencing constraint for §7's build order, not just a config flip:
landing the exclusion before the replacement analysis exists would be a regression window.
Citations are unaffected either way (`iter_event_rows` is not filtered, `store.py:683-689`), so
`show events` and hypothesis citations against eu-stack events keep working regardless of this
decision — only the clustering/salience/dedup path changes.

---

## 4. Multi-dump handling in the store

### What exists today

Every `Event` already carries `source_file` (`models.py` — confirmed field), and
`adapters/eustack.py:134-136` computes it as
`path.relative_to(self.input_root).as_posix()` (or `Path(path.name).as_posix()` with no
`input_root`) — i.e. one dump file = one `source_file` value, and every thread event from that dump
shares it. **There is no explicit "dump" grouping construct in the store or pipeline today** — the
natural key is simply `Event.source_file`, exactly as `perfmon._file_scope_groups`
(`perfmon.py:578-602`) already groups DSSPerformanceMonitor samples "by `Event.source_file`... so
first-appearance order is preserved" when there is no MCM episode to correlate against. The eu-stack
analyser should use the identical `by_file: dict[str, list[Event]] = {}` /
`by_file.setdefault(event.source_file, []).append(event)` idiom (`perfmon.py:603-605`) to group
raw thread events into per-dump populations — this is a direct, already-proven pattern in the
codebase, not a new design.

### The timestamp problem, verified against the real reference capture

`adapters/eustack.py:19-22`'s own docstring states the constraint precisely: "A thread dump carries
at most one dump-time timestamp (not per-thread); when present it stamps *every* thread from the
dump, when absent every thread is `ts=None`/`ts_confidence='missing'`". The milestone context
confirms the reference capture hits the absent case: both reference dumps have `ts=None`,
`ts_confidence="missing"` (`MILESTONE-CONTEXT-v1.3.md:20-22`, restated in `PROJECT.md`'s eu-stack
bullet). The only place a real per-dump time exists for these two files is the **filename**, and
the milestone context flags this as "a hazard: the reference files embed both a UTC-ish stamp and
a local-time parenthetical" — i.e. the filename format is ambiguous between two candidate readings,
exactly the situation ADR 0012 already faced and rejected for perfmon (a declared bias that could
not be resolved reliably from documentation, `0012:65-71`) and exactly the situation ADR 0012's
"infer the offset by maximising CSV/log window overlap" alternative was rejected for on principle
(`0012:124-125`, "it can invent an alignment that is not real... Rejected on principle, not cost" —
this is REQUIREMENTS.md's own Out-of-Scope rule, not just this ADR's local reasoning).

### Recommended approach

**Order dumps by `source_file` string sort as the deterministic fallback, and treat any
filename-embedded timestamp as advisory display metadata only — never as `Event.ts`, never as an
ordering key with silent-failure semantics.** Concretely:

1. **Grouping**: `by_file` keyed on `Event.source_file`, built via
   `dict.fromkeys`-preserving first-appearance order over the canonically-ordered event list
   (mirroring `perfmon._file_scope_groups`, `perfmon.py:589-591`'s own comment on why: "no `set`
   iteration can vary the output between runs").
2. **Ordering for the "which dump is earlier" question multi-dump progression needs**: attempt to
   parse a candidate timestamp out of the filename via a narrow, explicitly-labelled regex, and
   **loudly disclose both the parsed value and its ambiguity** rather than silently picking one
   reading. Given the milestone's own evidence that the filename carries *two* candidate stamps
   (a UTC-ish one and a local-time parenthetical) that could disagree, this is structurally the
   same "ambiguous, undocumented bias" problem ADR 0012 hit — so the same resolution applies:
   **record what was parsed as evidence, do not silently apply it as if authoritative.** A
   dump-order field (`EustackDump.order_confidence: Literal["filename-parsed","file-sort-fallback"]`
   or similar) makes the provenance explicit in the output model, mirroring `ts_confidence` on
   `Event` itself.
3. **Degradation, loudly**: when the filename does not parse (or when the two embedded stamps
   disagree — e.g. the local-time parenthetical does not correspond to the UTC-ish stamp under any
   plausible timezone), fall back to lexicographic `source_file` sort, deterministic across runs
   because sort order over a fixed string set never varies. Emit this as a graded disclosure
   (mirroring `perfmon.HAZARD_UNPLACEABLE_SAMPLES`'s "count and cite, never drop" pattern,
   `perfmon.py:544-575`) — e.g. "dump order could not be established from filenames; falling back
   to lexicographic file order; progression deltas may not reflect chronological sequence" — rather
   than a silent assumption that alphabetical happens to equal chronological (which is true for the
   two reference files by construction of their naming, but must not be trusted in general).
4. **Never invent a per-thread timestamp.** `Event.ts` stays `None` for these events exactly as the
   adapter already emits it (`adapters/eustack.py:21-22`) — the analyser must not "fix" this by
   writing a derived timestamp back, which would violate the adapter/analyser boundary the mcm/
   perfmon precedent already respects (analysers read `Event`, never mutate or re-derive its
   core fields; `mcm.py`'s docstring: "re-parse raw, never enrich the adapter").

This gives multi-dump progression (population deltas, "which threads advanced") a defensible,
disclosed ordering without inventing timestamps the adapter correctly refused to fabricate, and it
follows the exact "record, do not apply an ambiguous bias" resolution ADR 0012 already established
for a structurally identical problem.

---

## 5. Fact injection into `sift analyze`

### The exact mechanism, traced end to end

`hypothesise.py` is the single chokepoint (its own comment at `hypothesise.py:417-424` states this
explicitly: "Built at this chokepoint so the eval harness... exercises injection too"). The full
path for MCM (perfmon is byte-identical in shape, just its own slot/regex triple):

1. **Compute once, before generation** (`hypothesise.py:425-428`):
   ```python
   events = store.query_events()
   mcm_analysis = analyse_mcm(events, mcm_thresholds or McmThresholdsConfig())
   mcm_block = render_mcm_facts(mcm_analysis)          # -> (text: str, ids: set[str])
   perfmon_block = render_perfmon_facts(analyse_perfmon(mcm_analysis, events))
   ```
   `store.query_events()` decompresses the whole case exactly once and is reused by both renderers
   (comment at `hypothesise.py:423-424`: "no third pass") — the eu-stack analysis should reuse this
   same `events` list rather than re-querying, and (once §6 lands) reuse whatever vector-aware
   query path exists rather than adding a fourth pass.

2. **Render returns `(block_text, citable_ids)`** — `render_mcm_facts(analysis) -> tuple[str,
   set[str]]` (`mcm_facts.py:83`), `render_perfmon_facts(analysis) -> tuple[str, set[str]]`
   (`perfmon_facts.py:116`). Both return `("", set())` on no-data (`mcm_facts.py:90-91`,
   `perfmon_facts.py:123-124`) — the residue-free-strip contract an `eustack_facts.py` must
   replicate exactly.

3. **Splice into the template via a matched pair of HTML-comment sentinels + a slot token**
   (`hypothesise.py:82-142`): `_MCM_BLOCK_RE` / `_MCM_MARKER_RE` / `_MCM_SLOT = "<<MCM_FACTS>>"` and
   the near-identical perfmon triple. `_apply_mcm_block`/`_apply_perfmon_block` each do exactly one
   of two things: **no data → remove the whole `<!-- X_BLOCK_START -->...<!-- X_BLOCK_END -->`
   span (byte-identical-additive when absent)**; **data present → drop just the two marker lines
   and replace the slot** (`hypothesise.py:95-108`, `127-142`). An `eustack_facts.md` fragment
   needs the same `<!-- EUSTACK_BLOCK_START -->`/`<<EUSTACK_FACTS>>`/`<!-- EUSTACK_BLOCK_END -->`
   triple added to `triage.md`, and a fourth `_apply_eustack_block` function following the identical
   two-branch shape — this is intentionally not parameterised into one generic "apply named block"
   helper even for two instances (`_apply_kb_block` is the odd one out already, non-citable), so a
   third near-identical function is consistent with the existing three-copy pattern, not a
   deviation from it.

4. **Every rendered line begins with an `[evt:<id>]` token, and the returned `ids` set is *exactly*
   those printed ids** — both renderers' docstrings state "the exemplar contract — never expose an
   id the model was not shown" (`mcm_facts.py:13-14`, `perfmon_facts.py:12-14`). This is enforced
   structurally: every place a figure is appended to `lines`, the same call also does
   `ids.add(eid)` (`mcm_facts.py:106,118,134`) or goes through the shared `_cite_prefix` helper that
   does both atomically (`perfmon_facts.py:107-113`). An `eustack_facts.py` renderer must follow
   this exact discipline — one line, one citation prefix, one `ids.add` in the same statement or
   via an equivalent `_cite_prefix` helper, never a figure line with no accompanying id.

5. **`_assemble` unions the ids into `prompted_ids`** (`hypothesise.py:320-324`):
   ```python
   prompted_ids: set[str] = (
       set(event_ids)
       | (mcm_block[1] if mcm_block else set[str]())
       | (perfmon_block[1] if perfmon_block else set[str]())
   )
   ```
   This is the one line that needs a third `|` term:
   `| (eustack_block[1] if eustack_block else set[str]())`. Everything upstream of this union
   (rendering, splicing) is independent per fact-kind; this union is the single place all three
   become citable evidence simultaneously.

6. **Citation gate consumes `prompted_ids` unchanged** (`hypothesise.py:454-456`,
   `_citation_gate(client, hset, chat_messages, rf, prompted_ids, prompt_hash)`) — no change needed
   here at all; it already treats `prompted_ids` as an opaque set regardless of what contributed to
   it.

### Invariants the new fact block must preserve (explicit checklist for the planner)

- **`cited ⊆ prompted ⊆ store`**: every `[evt:<id>]` token the eustack renderer prints must be an
  id that exists in `store.query_events()` output — trivially true since the renderer only ever
  reads `event_id` off `Event`/analysis objects sourced from that same query, exactly as MCM/perfmon
  do.
- **Byte-identical-additive when absent**: a case with no eu-stack events must produce a prompt
  **byte-for-byte identical** to today's (no eu-stack block, no MCM/perfmon interaction change).
  This is testable the same way the existing suite already tests it (test names visible via the
  `EXCLUDED_FROM_RANKING`-adjacent docstrings reference a "no-MCM/no-perfmon byte-identical prompt
  guard" pattern) — an `eustack_facts.md`-absent prompt hash must equal the pre-v1.3 hash for the
  same case.
- **`_MCM_BLOCK_RE`/`_PERFMON_BLOCK_RE` independence**: `_apply_perfmon_block`'s own docstring notes
  "stripped independently of the MCM block so perfmon presence can never perturb the no-perfmon or
  MCM-only prompt bytes" (`hypothesise.py:136-138`) — the eu-stack block regex/removal must be
  equally independent, applied as its own `template = _apply_eustack_block(template, ...)` call in
  the same sequential chain (`hypothesise.py:295-299`), never combined into a shared multi-slot
  regex.
- **Budget/truncation interaction**: fact blocks are **not** run through `PromptBudget.fit` the way
  cluster exemplars are (`_assemble`'s `budget.fit(excerpts)` at `hypothesise.py:312` only trims the
  exemplar excerpts list, not the fact blocks) — MCM/perfmon facts are capped by their own
  `_MAX_EPISODES`/`_MAX_GROUPS` constants (`mcm_facts.py:54`, `perfmon_facts.py:78`) applied
  *before* rendering, not by the token budgeter after. An `eustack_facts.py` needs an equivalent
  fixed cap (e.g. `_MAX_DUMPS` or per-pool row cap) chosen the same way — a `ponytail:`-flagged
  fixed ceiling, not budget-aware trimming, matching both existing precedents' explicit comments
  that this is a deliberate simplification (`mcm_facts.py:52-53`, `perfmon_facts.py:76-77`).
- **Leaf-module import direction**: both existing fact renderers state "This is a leaf module... It
  must NOT import from `sift.pipeline.hypothesise` or `sift.cli`" (`mcm_facts.py:20-22`,
  `perfmon_facts.py:29-31`) — `eustack_facts.py` must observe the same direction (hypothesise
  imports it, never the reverse), keeping the dependency graph a DAG rooted at `cli.py`.

---

## 6. SEED-002 vector reuse integration

### Where the unconditional embed call lives today

`cluster.py:327-334` (`cluster_and_label`):
```python
groups = store.query_template_groups()
if not groups:
    return 0
messages = _exemplar_messages(store, groups)
texts = [exemplar_text(group, messages) for group in groups]
vectors = client.embed(texts)          # <-- unconditional, every call
dim = len(vectors[0])
```
followed by `store.upsert_vectors(vector_rows)` inside the single `store.transaction()` at
`cluster.py:373-399`, which **deletes then re-inserts every chunk_id's vector row** every run
(`store.py:837-854`, `upsert_vectors`: "vec0 does not support `INSERT OR REPLACE`, so a prior row
for the same chunk_id is deleted first").

### Where the reuse seam belongs

**In `cluster.py`, not in `store.py` and not behind the LLM client.** Reasoning:

- `store.py` owns *persistence primitives* (`upsert_vectors`, `ensure_vectors_table`,
  `record_embedding_identity`) but has no concept of "which exemplar text maps to which existing
  vector" — that mapping is `cluster.py`'s own `exemplar_text(group, messages)` /
  `_template_hash`-adjacent logic (template_id is already `sha256(template)[:16]`,
  `store.py:418`), i.e. the reuse *decision* (same text → same vector, skip the embed call) is a
  clustering-stage concern, matching where `_exemplar_messages`/`exemplar_text` already live
  (`cluster.py:85-118`).
- Behind the LLM client would hide the decision from the one place the "N reused / M embedded"
  observability requirement (below) needs to report from, and would make the client responsible
  for store-shaped state (which `chunk_id`/`template_id` already has a vector) that it has no other
  reason to know about — `client.embed` is deliberately a thin, store-unaware HTTP wrapper
  everywhere else in the codebase (`sift/llm/` is "the only module that talks HTTP", CLAUDE.md).
- Concretely: before calling `client.embed(texts)`, look up existing `(template_id, vector)` pairs
  already in the store (a new `store.get_vectors_by_template_id(template_ids) ->
  dict[str, list[float]]`-shaped read, mirroring the existing `get_events_by_ids` id-keyed lookup
  idiom at `store.py:600-639`), split `texts`/`template_ids` into hit/miss lists preserving order,
  call `client.embed` only on the miss list, then splice hits and misses back into the original
  `groups` order before `upsert_vectors` — exactly the "preserve `embed`'s existing order-
  preservation contract when splicing hits and misses back together" the seed's own sketch
  specifies (`SEED-002-embedding-vector-reuse.md:53-56`).

### What must invalidate reuse

- **Embedding model change**: already hard-guarded — `store.record_embedding_identity(model, dim)`
  (`store.py:798-814`) raises `ValueError` on a dimension mismatch against the recorded
  `embedding_dim`, and (new, for reuse) a *model name* mismatch against the recorded
  `embedding_model` should invalidate stored vectors even at the same dimension (two different
  1024-dim models are not interchangeable) — this is a new guard, since today
  `record_embedding_identity` only compares `dim`, not `model`, on repeat calls
  (`store.py:807-810` — no `elif model != existing_model` branch exists yet). Recommend adding one:
  a changed `embedding_model` at the same `dim` should force full re-embed, not silent reuse of a
  stale vector under a new model's identity.
- **Dimension change**: already a hard `ValueError` via `ensure_vectors_table`
  (`store.py:780-785`) — reuse logic sits downstream of this guard and never needs its own
  dimension check; a dimension change already aborts before reuse is even considered.
- **The open question — batch-knob changes (`embeddings.context`/`batch_size`/`max_input_chars`)**:
  the seed's own open question (`SEED-002-embedding-vector-reuse.md:69-72`) is "genuinely two-sided"
  and this research does not attempt to resolve it definitively — but it recommends a specific
  default, given ADR 0014's own framing: **do not invalidate on a knob change by default.** ADR
  0014 (`0014-embedding-determinism-scope.md:89-92`) already establishes the precedent that these
  three knobs use "overwrite semantics deliberately... a legitimate reconfiguration... must never
  wedge a re-analyze" — the same reasoning that justifies *not* hard-failing on a knob change today
  argues against invalidating reuse on one either, since ADR 0014 itself frames vector reuse as the
  fix that "closes the exposure" the knobs merely document (`0014:77-81`). Reusing a persisted
  vector regardless of which knobs produced it is *more* deterministic than re-embedding under
  possibly-different knobs, not less — reuse is the whole point. **Recommend**: knob changes are
  recorded (already true, `record_embedding_batch_knobs`) but never gate reuse; the CLI escape
  hatch (`analyze --re-embed`, flagged as "probably yes" in the seed) is the correct mechanism for
  an operator who wants a knob change to take effect immediately, not an automatic invalidation
  that would silently reintroduce the very re-embed-every-run cost SEED-002 exists to remove.

### Observability

"N reused / M embedded" must be surfaced from `cluster_and_label`'s return path — today it returns
only `len(clusters)` (`cluster.py:400`). Recommend widening the return (or adding a sibling
observability object, matching `ParseStats`'s role for adapters — `adapters/base.py`'s
`last_stats` idiom, `eustack.py:258`'s `self.last_stats = stats`) so `sift analyze`'s CLI output can
print a line like MCM's own stdout summary pattern (`cli.py:1185-1199`, "Analysed N MCM denial
episode(s)..."): e.g. "Embedded 12 new exemplars, reused 1769 stored vectors." This is the
"testable from outside" bar the seed sets (`SEED-002-embedding-vector-reuse.md:65-67`) — a test can
assert the printed/returned counts without inspecting internal call counts on a mock client.

---

## 7. Suggested build order

Dependencies are made explicit; items on the same numbered step have no dependency on each other
and can run in parallel (separate plans/waves).

1. **Rules file + loader** (`src/sift/rules/eustack_roles.toml` + load function + Pydantic model).
   No store dependency, no other v1.3 component depends on it existing first except the classifier
   below — build and unit-test in isolation against literal frame strings.
2. **Thread-role classifier + saturation/contention analysis** (`pipeline/eustack.py`,
   `analyse_eustack`). Depends on (1). Pure function over `list[Event]` — testable with hand-built
   `Event` fixtures, no store, no CLI, no LLM. This is the highest-value, highest-risk item (the
   milestone context's "critical finding" already burned one wrong hypothesis here) so it should
   land first and get the most eval scrutiny.
3. **Multi-dump grouping + ordering** (§4), built as part of (2) or immediately after — depends on
   (2)'s per-dump classification existing to have something to diff between dumps.
4. **`EXCLUDED_FROM_RANKING` decision** (§3) — a one-line store change, but sequence it **after**
   (2) exists (so the replacement capability is real, not aspirational) and **before** golden eval
   fixtures are authored (item 7), so the eval fixtures reflect final ranking behaviour, not a
   moving target.
5. **`sift eustack` CLI command + report/CSV renderer** (mirrors `mcm`/`perfmon` exactly —
   `cli.py`'s `mcm`/`perfmon` commands, `render/mcm_report.py`/`render/perfmon_report.py` pattern).
   Depends on (2). Independent of (4)/(6).
6. **`eustack_facts.py` renderer + `triage.md` block + `hypothesise.py` splice** (§5). Depends on
   (2). Can run in parallel with (5) — both consume `analyse_eustack` output independently.
7. **SEED-002 vector reuse** (§6, `cluster.py` + new `store.get_vectors_by_template_id`). **Fully
   independent of all eu-stack work** — it touches only the embed/cluster path and can be planned
   and executed in parallel with items 1–6 by a different wave, provided both land before the final
   quality gate. The milestone context ties it to eu-stack only because "the ranking-exclusion
   decision touches the clustering/embedding pipeline" (PROJECT.md) — that is a *scheduling*
   coincidence (both changes touch `cluster.py`/`store.py` in the same milestone), not a functional
   dependency; sequence it to avoid the two changes' diffs conflicting in the same files, not
   because either needs the other's output.
8. **Regression-gated golden eval** (real healthy capture as negative case, synthetic hang shapes as
   positive fixtures). Depends on (2)–(6) all being feature-complete, since the eval exercises the
   full `sift eustack` + `sift analyze` fact-injection path end to end, mirroring how MCM-07/PERF-08
   gated the previous two milestones only once their respective analysers were done.

---

## Sources

All claims verified by direct reading of the shipped v1.2 source (not inferred from names or
prose) on 2026-07-25:

- `src/sift/pipeline/mcm.py` (full file, 977 lines)
- `src/sift/pipeline/perfmon.py` (full file, 812 lines)
- `src/sift/pipeline/cluster.py` (full file, 401 lines)
- `src/sift/adapters/eustack.py` (full file, 258 lines)
- `src/sift/pipeline/hypothesise.py:1-460`
- `src/sift/pipeline/mcm_facts.py`, `src/sift/pipeline/perfmon_facts.py` (full files)
- `src/sift/store.py:300-860, 1087-1095` (`EXCLUDED_FROM_RANKING`, `iter_event_summaries`,
  `iter_event_rows`, `ensure_vectors_table`, `record_embedding_identity`,
  `record_embedding_batch_knobs`, `upsert_vectors`, `get_meta`/`set_meta`)
- `src/sift/config.py` (full file read to line 210 — `SiftConfig`, `McmConfig`, `load_config`)
- `src/sift/cli.py:1115-1265` (`mcm`, `perfmon` CLI commands)
- `src/sift/prompts/mcm_facts.md`, `src/sift/prompts/perfmon_facts.md`
- `docs/decisions/0009-kb-index-per-case.md`, `0012-perfmon-naive-timestamps.md`,
  `0014-embedding-determinism-scope.md`
- `pyproject.toml` (build-system, dependencies)
- `.planning/research/MILESTONE-CONTEXT-v1.3.md`, `.planning/PROJECT.md`,
  `.planning/seeds/SEED-002-embedding-vector-reuse.md` (measured evidence and scope, treated as
  given input, not re-derived)
- `grep -rn "EXCLUDED_FROM_RANKING"` across `src/` and `tests/` — confirmed exactly four
  occurrences (definition + two docstrings + one query usage), no other reader

---
*Architecture research for: Sift v1.3 EU-Stack Hang & Slowdown Diagnosis (integration research)*
*Researched: 2026-07-25*
