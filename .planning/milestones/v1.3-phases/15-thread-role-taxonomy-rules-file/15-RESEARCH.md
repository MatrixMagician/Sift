# Phase 15: Thread-Role Taxonomy & Rules File - Research

**Researched:** 2026-07-25
**Domain:** Deterministic frame-pattern classification of eu-stack thread dumps (TOML rules file + Pydantic loader + pure classifier), library-only (no CLI)
**Confidence:** HIGH

## Summary

Phase 15's implementation unknowns are narrower than the v1.3 milestone research already resolved
(TOML format, `str` matching, sibling-module placement, `EXCLUDED_FROM_RANKING` sequencing — all
settled in `.planning/research/{STACK,ARCHITECTURE,PITFALLS}.md`). What is left is *how the 16
locked decisions in CONTEXT.md compose into working code*: the exact Pydantic loader shape, the
packaging mechanics of a new data-only package, the config wiring, the frame-iteration seam on the
shipped adapter, and — the highest-value piece — what an initial curated rules file actually looks
like when run against the real reference capture.

This research parses both reference dumps directly (`/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`)
with throwaway Python (not committed) and simulates D-01's rule-major, first-match-wins engine
against a candidate 24-rule initial set. Measured result: **98.67% of threads (3,850/3,902) and
56.99% of distinct signatures (53/93) classify**, with the headline criterion-4 signature (the
1,715-thread `MSIQTask::GetNextPreferredJob` population) correctly reading `idle-parked/job-queue`.
The residual 40 unclassified signatures are almost all singleton or near-singleton background
threads (Kafka client internals, per-feature index/session-backup daemons, timer tasks) — a long
tail where each additional rule buys one more specific singleton, not broad population coverage.
This bounds the "how many rules on day one" discretion call with real numbers instead of guesswork.

A second finding is structural, not just numeric: because D-09 matching is "does this frame text
appear anywhere in the stack" rather than "is this the frame closest to the wait primitive," **rule
order does load-bearing work beyond D-01's headline case.** `MSIEvaluationTask::Run()` — the
milestone's own cited self-labelling frame for the 1,110-thread idle-evaluation population — also
appears as a *distant ancestor* frame in genuinely busy evaluation stacks (deep cube-generation call
chains that still pass through the same task-dispatch frame near the bottom of the stack). The only
way an `idle-parked/evaluation` rule keyed on that frame text doesn't misclassify busy evaluation
threads is if the `running` rules (D-02's five specific frames) are placed *before* it in the file.
This is verified empirically below, not assumed.

**Primary recommendation:** ship an initial rules file with the 24 rules cataloged in "Seeding the
initial rules file" below, in the file order given (running rules first, then blocked-on-lock, then
the idle/external rules, evaluation-idle last among idle rules); build a signature-preserving CI
fixture at `cap=1` thread per signature (measured 140 KB, not the ~80 KB estimated in CONTEXT.md —
see "Building the signature-preserving fixture" for the corrected figure and the reasoning gap).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Frame iteration over raw thread text | Adapter (ingestion) | — | `iter_frames()` is a thin regex-reuse helper on `src/sift/adapters/eustack.py`; it does not classify, only splits |
| Symbol normalisation (D-05) | Analysis (`pipeline/eustack.py`) | — | Classification-specific transform; the adapter must not know about roles |
| Rules loading + validation | Analysis (`pipeline/eustack.py`) | Config (`config.py` resolves the path) | Pydantic models + `tomllib` live with the classifier, mirroring `mcm.py`/`perfmon.py`; `config.py` only resolves *which* file to load |
| Classification (role/subsystem assignment) | Analysis (`pipeline/eustack.py`) | — | Pure function over `list[Event]` + loaded rules, no store/CLI/network dependency |
| Rules file packaging | Package data (`src/sift/rules/`) | — | Data-only sibling to `src/sift/prompts/`, no executable code |
| User rules-file override | Config (`config.py` `EustackConfig.rules_path`) | — | Mirrors `McmConfig`'s nested-key shape; resolved through the existing CLI>env>toml>default precedence chain |

This phase touches only the Analysis/Config/Package-data tiers. No Browser, Frontend-SSR, CDN, or
Database tier exists in Sift's CLI-only architecture; the eventual `sift eustack` CLI surface
(Phase 17) is out of this phase's scope by D-13.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EUS-01 | Every thread classified into one of 5 roles, driven by a versioned, Python-free-editable rules file | "Seeding the initial rules file" measures achievable coverage; "The loader's exact shape" gives the Pydantic/tomllib composition that makes edits require no Python change; "Rules-file schema" cross-references are pre-resolved by CONTEXT.md D-09/D-10/D-11/D-12, verified against `config.py`'s existing nested-model precedent |
| EUS-02 | Unrecognised frames counted and reported as `unclassified`, never guessed | "Common Pitfalls" documents the rule-ordering trap that can silently turn EUS-02 into a guesser if running rules are misordered relative to ancestor-frame idle rules; "Validation Architecture" SC3 gives the executable assertion |
</phase_requirements>

## Standard Stack

### Core

No new dependency. Confirmed against the shipped `pyproject.toml` [VERIFIED: repo] — stdlib
`tomllib` (already imported at `src/sift/config.py:15`), Pydantic (already a runtime dependency,
`pydantic>=2.13.4`), stdlib `re`/`collections.Counter`. `.planning/research/STACK.md` already
settled TOML-over-YAML/Markdown and plain-`str`-matching-over-regex/trie for this exact phase; this
research does not re-derive those findings, only builds on them.

### Package Legitimacy Audit

**Not applicable — this phase installs no external packages.** Every capability (TOML parsing,
schema validation, string matching, signature grouping) resolves to stdlib or an already-declared
dependency. No `npm view`/`pip index versions`/legitimacy-check invocation is needed.

## Architecture Patterns

### System Architecture Diagram

```
Event (source="eustack", store.query_events() output)
        │  .raw  (full thread block text: "TID n:\n#0 ...\n#1 ...")
        ▼
adapters/eustack.py: iter_frames(raw) -> Iterator[tuple[int, str]]
        │  (index, full frame symbol text incl. optional " - lib src:line" tail)
        ▼
pipeline/eustack.py: normalise(symbol) -> str          [D-05]
        │  strip "@@GLIBC_x.y.z" suffix + " - lib src:line" tail; keep template args
        ▼
pipeline/eustack.py: signature = tuple(normalise(f) for f in frames)   [D-03]
        │
        ▼
collections.Counter({signature: thread_count})           ← one pass over all eustack Events
        │
        │         ┌─────────────────────────────────────────┐
        │         │ src/sift/rules/eustack_roles.toml        │
        │         │  (packaged default, OR user override via │
        │         │   [eustack] rules_path in config.toml)   │
        │         └───────────────┬───────────────────────────┘
        │                         ▼
        │          pipeline/eustack.py: load_rules() -> ThreadRoleRules
        │                         │  tomllib.load + Pydantic (extra="forbid")
        ▼                         ▼
pipeline/eustack.py: classify(signature, rules) -> (role, subsystem, pattern, frame_idx)  [D-01/D-04]
        │  for each rule in file order: scan frames #0..#N; first match wins
        │  no match after all rules -> "unclassified"
        │  no resolvable frame at all -> "no resolvable frame"                            [D-07]
        ▼
broadcast classification to every thread sharing that signature (Pitfall 6: O(signatures), not O(threads))
        ▼
EustackAnalysis  (per-role thread/signature counts, per-signature unclassified list)
```

### Recommended Project Structure

```
src/sift/
├── rules/
│   ├── __init__.py            # empty; package-data marker, mirrors prompts/__init__.py
│   └── eustack_roles.toml     # [meta] + [[rule]] array-of-tables, packaged default
├── pipeline/
│   └── eustack.py             # NEW: Pydantic models, loader, normalise(), classify(), analyse_eustack()
├── adapters/
│   └── eustack.py             # ADDITIVE: gains iter_frames(); parse()/ParseStats unchanged
└── config.py                  # ADDITIVE: gains EustackConfig, wired into SiftConfig.eustack
```

### Pattern: Rules-file schema (composes D-06/D-09/D-10/D-11/D-12 in one model tree)

**What:** A `[meta]` table plus an ordered `[[rule]]` array-of-tables, parsed in one
`tomllib.load()` call, validated by strict Pydantic models mirroring `McmThresholdsConfig`/
`McmConfig` (`src/sift/config.py:94-121`).

**Why this shape:** `tomllib`'s array-of-tables preserves file order 1:1 as a Python `list`
(dict/list insertion order is guaranteed since Python 3.7) — first-match-wins (D-01) falls out of
iterating the list, no separate `priority` field needed. `extra="forbid"` on every model
(`config.py:106` precedent) makes a typo'd key (`rol =` instead of `role =`) a load-time
`ValidationError`, not a silently-dead rule.

**Example:**
```python
# Source: mirrors src/sift/config.py:94-121 (McmThresholdsConfig/McmConfig) — this repo, verified
from typing import Literal
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Role = Literal["idle-parked", "blocked-on-external", "blocked-on-lock", "running"]
# D-12: "unclassified" is illegal as a rule role — it is the residual, never authored.

MatchKind = Literal["exact", "prefix", "contains"]

class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    subsystem: str                       # D-10: required, no default — every rule declares one
    match: MatchKind = "exact"           # D-09: omitting `match` means exact
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _pattern_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rule pattern must not be empty")
        return value

    @field_validator("pattern")
    @classmethod
    def _pattern_must_be_normalised(cls, value: str) -> str:
        # D-06: a pattern that is not already normalised is rejected loudly at load,
        # with the canonical form in the error message.
        canonical = normalise(value)
        if canonical != value:
            raise ValueError(
                f"rule pattern {value!r} is not normalised; use {canonical!r}"
            )
        return value


class RulesMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    validated_against: str               # D-11: MicroStrategy build(s) + glibc, free text


class ThreadRoleRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: RulesMeta
    rule: tuple[Rule, ...]                # tomllib preserves [[rule]] order verbatim

    @model_validator(mode="after")
    def _no_duplicate_rules(self) -> "ThreadRoleRules":
        # D-12: a duplicate (match, pattern) pair is a dead rule under first-match-wins.
        seen: set[tuple[str, str]] = set()
        for r in self.rule:
            key = (r.match, r.pattern)
            if key in seen:
                raise ValueError(f"duplicate rule (match={r.match!r}, pattern={r.pattern!r})")
            seen.add(key)
        return self
```

**Loading (mirrors `config.py:181-192`'s exact error-surfacing pattern):**
```python
# Source: mirrors src/sift/config.py:186-192 — TOMLDecodeError -> ValueError naming the file;
# ValidationError bubbles up raw for schema violations, matching test_config.py's
# test_unknown_config_key_is_a_loud_error_naming_the_key / test_malformed_toml_is_a_loud_error.
import hashlib
import importlib.resources
import tomllib
from pathlib import Path

_RULES_PACKAGE = "sift.rules"
_RULES_FILE = "eustack_roles.toml"

def load_rules(rules_path: str | None = None) -> tuple[ThreadRoleRules, str]:
    """Returns (validated rules, sha256(text)[:16] content hash) — D-11."""
    if rules_path:
        path = Path(rules_path)
        text = path.read_text(encoding="utf-8")
        source = str(path)
    else:
        text = (
            importlib.resources.files(_RULES_PACKAGE)
            .joinpath(_RULES_FILE)
            .read_text(encoding="utf-8")
        )
        source = f"packaged:{_RULES_FILE}"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid rules file {source}: {exc}") from exc
    rules = ThreadRoleRules.model_validate(data)  # ValidationError bubbles up raw
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return rules, content_hash
```

This composes cleanly: `tomllib.TOMLDecodeError` (malformed syntax) becomes a `ValueError` naming
the source, exactly like `config.py:190-192`; a schema violation (missing `subsystem`, illegal
`role`, un-normalised `pattern`, duplicate rule) raises Pydantic's `ValidationError` unwrapped,
exactly like `SiftConfig.model_validate` today — `tests/test_config.py`'s
`test_unknown_config_key_is_a_loud_error_naming_the_key` and
`test_malformed_toml_is_a_loud_error` are the direct test-shape precedents to mirror for the rules
loader's own test file. `content_hash` is the sha256-truncated-to-16 idiom already used for
`cluster_label_prompt_hash`/`event_id`/`template_id` — this phase computes it and returns it (D-11)
but does **not** write it to `store.meta` (deferred to Phase 17 per D-11 — no store dependency
exists in this phase).

### Anti-Patterns to Avoid

- **A catch-all `idle-parked` rule on a generic ancestor frame** (e.g. `MSIThread::Run()`) to
  force higher signature coverage: this is exactly the "residual default" anti-pattern D-02
  explicitly rejects for `running`, applied symmetrically to `idle-parked`. It is NOT in the
  recommended 24-rule set below and should not be added without a specific, deep, single-purpose
  pattern for each additional case.
- **A generic `idle-parked/evaluation` rule placed *before* the `running` rules**: verified below to
  misclassify genuinely-busy evaluation threads, because `MSIEvaluationTask::Run()` is a shared
  ancestor frame of both the idle-wait and busy-cube-generation call paths.

## Seeding the initial `eustack_roles.toml`

**Method:** parsed both reference dumps directly with throwaway Python (not committed to the repo;
scratch scripts only). Confirmed the milestone context's own measured baseline exactly: 3,902
threads, 93 distinct signatures, 38,493 frames, 3,552 frames carrying `@@GLIBC_x.y.z` suffixes
across exactly the 3 named symbols (`pthread_cond_timedwait@@GLIBC_2.3.2`,
`pthread_cond_wait@@GLIBC_2.3.2`, `__libc_start_main@@GLIBC_2.34`) — this cross-checks D-05's own
measurement bit-for-bit [VERIFIED: direct capture parse].

Then simulated D-01's classification engine (rule-major, first-match-wins, scan every frame per
rule) against a candidate rule set built from the locked decisions plus the milestone's own top-10
signature table.

**Candidate initial rule set (24 rules, in file order — order is load-bearing, see below):**

| # | Role | Subsystem | Match | Pattern |
|---|------|-----------|-------|---------|
| 1 | running | compute | contains | `_shi_allocBlock` |
| 2 | running | compute | contains | `_shi_allocVar` |
| 3 | running | compute | contains | `MemAllocPtr` |
| 4 | running | cube-generation | contains | `CDSSSubsetEngine::GenCube` |
| 5 | running | cube-generation | contains | `MCE::GetBaseRIbyID` |
| 6 | blocked-on-lock | lock | contains | `__lll_lock_wait` |
| 7 | idle-parked | job-queue | contains | `MSIQTask::GetNextPreferredJob` |
| 8 | idle-parked | job-queue | contains | `MSIQTask::GetNextJob` |
| 9 | idle-parked | command-queue | contains | `MSICommandQTask::GetNextCommand` |
| 10 | idle-parked | ipc | contains | `CrossProcessEventImpl::WaitOnPipe` |
| 11 | idle-parked | generic-pool | contains | `ThreadPoolImpl::GetNextRunnable` |
| 12 | idle-parked | bursting-pool | contains | `ParallelBursting::ThreadPool::WorkLoop` |
| 13 | idle-parked | asio-reactor | contains | `boost::asio::detail::scheduler::run` |
| 14 | idle-parked | cache-backup | contains | `CacheBackupRunnable` |
| 15 | idle-parked | evaluation | contains | `MSIEvaluationTask::Run` |
| 16 | blocked-on-external | warehouse | contains | `CDSSQueryEngine::WaitUntilFinished` |
| 17 | blocked-on-external | http | contains | `curl_multi_poll` |
| 18 | blocked-on-external | ipc | contains | `SharedMemoryImpl::WaitOnSemaphore` |
| 19 | blocked-on-external | warehouse | contains | `MDb::Wrapper::InterpretStatus` |
| 20 | idle-parked | timer | contains | `MTimer::Timer<` |
| 21 | idle-parked | scheduled | contains | `MSIRecurrentTask::Run` |
| 22 | idle-parked | network-reactor | contains | `MSINetReactorModern` |
| 23 | idle-parked | kafka | contains | `rd_kafka_broker_thread_main` |
| 24 | idle-parked | kafka | contains | `rd_kafka_thread_main` |

**Measured coverage (dump A, 3,902 threads / 93 signatures):**

| Rule count | Threads classified | Signatures classified |
|---|---|---|
| 16 (rules 1-17 minus 18/19, i.e. the decisions/specifics-only floor) | 3,801 / 3,902 (97.41%) | 33 / 93 (35.48%) |
| **24 (recommended)** | **3,850 / 3,902 (98.67%)** | **53 / 93 (56.99%)** |

By role at 24 rules: `idle-parked` 3,651 threads / 33 signatures, `blocked-on-external` 194 threads
/ 15 signatures, `blocked-on-lock` 0 threads / 0 signatures (the reference capture is healthy — no
lock contention observed, consistent with the milestone's own framing), `running` 5 threads / 5
signatures, `unclassified` 52 threads / 40 signatures.

**Criterion-4 check (measured, not assumed):** the 1,715-thread signature classifies as
`role='idle-parked' subsystem='job-queue' pattern='MSIQTask::GetNextPreferredJob' frame_idx=3` —
criterion 4 holds under this rule set.

**Residual unclassified signatures (40 at 24 rules)** are almost entirely singletons: one thread
each for Kafka message-reprocessor internals, per-index-manager background threads
(`MIndexManager::RealTimeUpdateThread::Run`, `ElementDatasetUpdateThread::Run`), session backup
manager sub-tasks (`BackgroundSessionBackupManagerImpl::Run{,DiskScan,ActiveMessageBackup}`),
event-services update tasks (4 near-identical `MSI*EventServicesUpdateTask::Run` variants), perfmon
counter loggers, RAG index update threads, and a handful of deep query-status-polling signatures
under `MDb::Wrapper::InterpretStatus` variants not caught by rule 19's narrower match. The single
largest remaining gap is a 13-thread signature whose enclosing frame is bare `MSIThread::Run()` with
no further identifying method — genuinely under-specified; adding a rule for it would require a
generic ancestor-frame pattern, which is the anti-pattern flagged above. **This is exactly what
"Claude's Discretion" in CONTEXT.md leaves open** — the planner can pick a stopping point anywhere
from the 16-rule floor to the 24-rule set to a further-expanded set that names each singleton; this
research demonstrates the coverage/rule-count curve is flattening fast past 24 rules (each further
rule buys ~1 signature, ≤13 threads), so diminishing returns argue for stopping around here and
treating the remainder as expected, disclosed `unclassified` — consistent with D-02's framing of the
unclassified rate as a rules-drift *signal*, not a defect to be driven to zero.

**Rule-ordering finding (empirically verified, not in CONTEXT.md as written):** `MSIEvaluationTask::Run()`
— the milestone's own cited self-labelling frame for the idle-evaluation population — is **also** an
ancestor frame in the genuinely-busy `_shi_allocBlock`/cube-generation signature captured in the
reference dump (a real, single-thread example of D-02's "44 changed threads" class present even in
one static dump, not only visible via diffing). Because D-09 matching tests "does this frame text
appear anywhere in the stack," an `idle-parked/evaluation` rule keyed on `MSIEvaluationTask::Run`
placed *before* the `running` rules (1-5) would misclassify that busy thread as idle. Placing the
`running` rules first (as in the table above) resolves this correctly: rule 1 (`_shi_allocBlock`)
matches the busy signature and wins before rule 15 is ever tested. **This generalises**: any rule
keyed on a task-dispatch/pool-loop frame that is common to both a task's idle-wait state and its
active-work call chain must sit *after* any rule identifying that task's specific working frames,
not merely after generic wait-primitive rules. The planner should flag this explicitly as a review
checklist item when curating additional rules, not just for the shipped evaluation rule.

**One residual mis-ordering risk even in the 24-rule set:** a single-thread signature exists in the
reference capture with frames `pthread_rwlock_rdlock@GLIBC_2.2.5` → `MBase::FeatureFlagMgr::IsFeatureEnabled`
→ (deep cube-join call chain) → `MSIEvaluationTask::Run()`. This is one of the "44 changed" real-work
frames PITFALLS.md names, but it does not match any of the D-02 running patterns (it is a feature-flag
check inside cube generation, not allocation/GenCube/GetBaseRIbyID) and does not hit `__lll_lock_wait`
(the rwlock acquire here is not on the contended slow path in this capture). Under the 24-rule set it
falls through to rule 15 and reads `idle-parked/evaluation` — one thread, not a population-level
error, but worth naming: **D-02's running-rule list is locked and this research does not propose
expanding it**, so this single-thread edge case is disclosed here for the planner's awareness rather
than silently accepted or silently "fixed" by relitigating D-02.

## The loader's exact shape under `pyright` strict

Covered above under "Pattern: Rules-file schema" — the composition of D-06 (load-time rejection),
D-11 (`[meta]` + content hash), and D-12 (strict Pydantic, `Literal` role, duplicate-rule rejection)
in one `tomllib.load` → Pydantic model tree, directly mirroring
`McmThresholdsConfig`/`McmConfig` (`src/sift/config.py:94-121`). All types are concrete (`Literal`,
`tuple[Rule, ...]`, `str`) — no `Any`, no untyped dict passthrough — so this passes `pyright --strict`
by construction, matching every other model in `config.py`. Validation-error surfacing matches
`config.py:186-192` exactly: `tomllib.TOMLDecodeError` → `ValueError` naming the file;
Pydantic `ValidationError` bubbles up unwrapped for schema violations. Test-shape precedent:
`tests/test_config.py::test_unknown_config_key_is_a_loud_error_naming_the_key` and
`::test_malformed_toml_is_a_loud_error`.

## Packaging the `src/sift/rules/` data package

**[VERIFIED: direct build test, this session]** Confirmed empirically, not by analogy: temporarily
added `src/sift/rules/__init__.py` + a placeholder `eustack_roles.toml` to the real source tree, ran
`uv build --wheel`, and inspected the resulting wheel's file list —

```
sift/rules/
sift/rules/__init__.py
sift/rules/eustack_roles.toml
```

— both files ship automatically under `uv_build` with **zero `pyproject.toml` changes**, exactly
mirroring how `src/sift/prompts/*.md` already ships with no explicit `package-data`/`include`
stanza (`pyproject.toml:38-40`, `build-system.build-backend = "uv_build"`). The test artefacts were
removed after the check; `git status` confirms the working tree is clean of the probe files.

**`tests/test_packaging.py` does NOT need a new assertion for this** — it is an opt-in,
`-m packaging`-gated end-to-end offline-install smoke test (`pyproject.toml:49-53`) that checks
`sift --help`/`sift --version`/`sift new` work after a real `uv tool install`; it does not currently
enumerate individual package-data files (`test_packaging.py:1-191`, read in full — no per-file
assertion exists even for `prompts/*.md`). Following that precedent, the phase does **not** need to
add a packaging-marker test for the rules `.toml`.

**Recommend instead**: a cheap, default-suite unit test (no `-m packaging` needed, runs on every
`pytest` invocation) directly on `importlib.resources`:

```python
def test_packaged_rules_file_is_importable_resource() -> None:
    path = importlib.resources.files("sift.rules").joinpath("eustack_roles.toml")
    assert path.is_file()
```

This catches a future packaging regression (e.g. someone adding a restrictive `[tool.uv.build-backend]`
include glob) immediately in CI, rather than only in the slow opt-in packaging suite — cheaper and
faster feedback than extending `test_packaging.py`.

## The `[eustack] rules_path` config key end-to-end

Mirror `McmConfig` exactly (`src/sift/config.py:116-121`):

```python
class EustackConfig(BaseModel):
    """``[eustack]`` wrapper, mirrors McmConfig's nested-key shape."""

    model_config = ConfigDict(extra="forbid")

    rules_path: str | None = None   # None -> load the packaged default via importlib.resources
```

Add `eustack: EustackConfig = EustackConfig()` to `SiftConfig` (`config.py:124-134`, alongside
`mcm: McmConfig = McmConfig()`). Add one entry to `_ENV_SCALARS` (`config.py:154-166`):

```python
"SIFT_EUSTACK_RULES_PATH": ("eustack", "rules_path"),
```

This gets the existing CLI-flag > `SIFT_*` env > `config.toml` > default precedence for free —
`load_config`'s merge logic (`config.py:181-213`) requires no other change; `_set_nested` already
handles arbitrary new `(section, field)` pairs.

**`tests/test_config.py` additions needed** (no existing test needs *updating* — verified by
reading the full file: no test enumerates the complete `SiftConfig` field set via something like
`set(SiftConfig.model_fields) == {...}`; every existing test asserts individual fields, so adding
`eustack` is purely additive):

- `test_eustack_rules_path_defaults_to_none()` — mirrors `test_mcm_thresholds_defaults`.
- `test_eustack_rules_path_round_trips_from_toml()` — mirrors `test_embeddings_section_round_trips_from_toml`.
- `test_env_beats_toml_for_eustack_rules_path_but_flag_wins()` — mirrors the embeddings base_url
  precedence test at `test_config.py:118-129`.
- `test_unknown_key_under_eustack_is_a_loud_error()` — mirrors `test_unknown_key_under_clustering_is_a_loud_error`.

**Path-traversal/containment guard (Claude's Discretion item):** no existing precedent in this
codebase applies a containment guard to a user-supplied config path. `--kb <dir>` (ADR 0009) is the
closest analogue and explicitly "points anywhere the user chooses" with no containment check —
`rules_path` is a local file read (not a network fetch, not written to), so the risk profile is a
user pointing Sift at their own file, which they already have read access to by definition. **Recommendation:**
no containment guard, consistent with the `--kb` precedent — but this is Claude's Discretion, not a
locked finding; if the planner wants defense-in-depth anyway, the guard would be a one-line
`Path(rules_path).resolve()` existence check with a clear error message (not a jail/chroot), since
`tomllib`'s own parser has no code-execution surface to protect against (unlike YAML's tag
mechanism).

## Building the signature-preserving fixture (D-14)

**[VERIFIED: measured, this session]** Built the actual derivative and measured its size directly,
rather than estimating. For each of the 93 distinct signatures, kept the first N threads
(verbatim raw text, `TID <n>:` header + all frame lines) up to a per-signature cap:

| Cap (threads/signature) | Total threads | Signatures | Measured size |
|---|---|---|---|
| 1 | 93 | 93 (all) | **143,281 bytes (139.9 KB)** |
| 2 | 122 | 93 (all) | 179,015 bytes (174.8 KB) |
| 3 | 145 | 93 (all) | 206,069 bytes (201.2 KB) |
| 5 | 184 | 93 (all) | 242,585 bytes (236.9 KB) |

**This corrects CONTEXT.md D-14's "roughly 80 KB" estimate** — even the leanest possible
signature-preserving derivative (exactly one thread per signature, no broadcast/multiplicity
testing at all) measures **140 KB, not 80 KB**. The gap is driven by a handful of pathologically
deep, template-heavy signatures: one 60-frame signature alone (`MemProcessInfo2` →
`MBase::SmartHeapIntegrator::GetMemoryUsageInfo` → ... → deeply templated `CDSSDocumentInstance::hIterateContentToXML`
overloads with STL container template arguments) contributes several KB by itself, because D-03
forbids depth-capping and D-05 keeps template argument lists. This is not a bug in the estimate's
reasoning, just an under-measurement — the "top-ten signature table" CONTEXT.md cites
(`MILESTONE-CONTEXT-v1.3.md:79-90`) is dominated by shallow (6-10 frame) signatures, but the *tail*
beyond the top ten includes several signatures 20-60 frames deep with long templated symbol names,
and D-14 requires **all 93**, not just the shallow ones.

**140-201 KB is still a 92-94% reduction from the 2.4 MB original** and remains far smaller than
committing the full capture, but it is 11-15× the current largest committed fixture (13,410 bytes,
`tests/fixtures/eustack/threaddump.txt`) rather than the ~6× the 80 KB estimate implied. **Recommendation:**
`cap=1` (139.9 KB) as the size floor — it satisfies criterion 5 exactly (93/93 signatures reproduce
in CI) — plus a slightly higher cap (e.g. 3-5) applied *only* to the handful of highest-population
real signatures (the `MSIQTask::GetNextPreferredJob` and `MSIEvaluationTask::Run` families) so the
fixture also exercises the "broadcast one classification to N threads" multiplicity logic and gives
criterion 4's *proportions* (not just presence) something realistic to assert against in CI, without
inflating every one of the 93 signatures to that cap. This hybrid keeps the fixture close to the
140 KB floor while still testing broadcast.

**Filename/PID sanitisation:** the real files embed a customer environment identifier in the
filename (`stack_env-hnyjbci1u11xhyl5-iserver-1_...`) and a real PID (1363967) plus a real capture
timestamp. The frames themselves are pure C++ symbol text and carry no customer identifiers
(confirmed — no string literals, no hostnames, no user data appear in any frame across the sampled
signatures). **Recommendation:** commit the derivative as
`tests/fixtures/eustack/reference_capture_derivative.txt` with a synthetic `PID 999999 - process`
header and no environment identifier or real date anywhere in the file or its name — a plain,
neutral filename, unlike the real files' naming convention.

**Generation mechanism — committed script vs static artefact:** **recommend a committed,
reproducible derivation script** (e.g. `scripts/derive_eustack_fixture.py`, run manually against the
out-of-repo capture and its output committed as the fixture — not run in CI, since the source
capture is not in the repo). This mirrors ADR 0013's evidence-gathering style (measured against an
out-of-repo corpus, findings recorded) and directly avoids Pitfall 5's named failure mode (a fixture
hand-authored to match the detector) — the script performs mechanical extraction (group by
signature, cap thread count, sanitise PID/header) with no role-aware logic in it at all, so it
cannot be "written to pass." The script itself should NOT be committed as test-adjacent code that
runs in CI (it needs the out-of-repo 2.4 MB file); keep it as a documented one-off utility, or
delete it after generating the fixture and document the derivation procedure in a comment atop the
fixture file.

## `iter_frames()` on the shipped adapter (D-08)

**Current shape** (`src/sift/adapters/eustack.py`, read in full): `_FRAME_RE` at line 57
(`^#(\d+)\s+0x([0-9A-Fa-f]+)\s+(.+)$`) is already anchored and reused nowhere outside `parse()`.
`_condense_symbol` (line 69-73) splits a frame body on `" - "` once, discarding the
`lib source:line` tail, and is used only for the condensed `message` (capped at
`CONDENSED_FRAMES = 5`, line 51). `parse()` builds `Event.raw` as the verbatim joined thread block
(`raw = "".join(rec.raw_parts)`, line 149-171) — every frame line survives uncapped in `raw`.

**Minimal additive change:**

```python
# Added to src/sift/adapters/eustack.py — additive only, no change to parse()/ParseStats/Event shape.
def iter_frames(raw: str) -> Iterator[tuple[int, str]]:
    """Yield (frame_index, full_symbol_text) for every #N frame line in one thread's raw block.

    ``full_symbol_text`` includes any `` - <lib> <source>:<line>`` tail verbatim — callers that
    want the bare symbol should reuse ``_condense_symbol`` on the yielded text (D-08: shared, not
    copied), exactly as ``parse()`` already does for the condensed ``message`` field.
    """
    for line in raw.splitlines():
        m = _FRAME_RE.match(line)
        if m is not None:
            yield int(m.group(1)), m.group(3)
```

This is a pure function over a string (not over `self`/`ConfigurableAdapter` state), so it needs no
adapter instance and can be imported directly by `pipeline/eustack.py` — exactly the
`byte_lines`-from-`genericlog` precedent (`eustack.py:39,45-46`, "to avoid a drifting verbatim
copy"). **`pipeline/eustack.py`'s `normalise()` (D-05) should call `_condense_symbol` internally**
for the lib/src-tail strip (reusing the existing split, not re-implementing it), then additionally
strip the `@@GLIBC_x.y.z` suffix on top — this keeps the "` - lib src:line` tail" stripping logic in
exactly one place across both the condensed-`message` path and the classifier's normalisation path.

**`tests/test_eustack.py` constraint check:** read in full — no existing test exercises frame
iteration directly (all assertions go through `parse()`'s `Event.message`/`Event.raw`). Adding
`iter_frames()` requires new tests (`test_iter_frames_yields_index_and_full_symbol`,
`test_iter_frames_on_capped_raw_yields_fewer_frames` for the `MAX_EVENT_LINES`-truncated case) but
breaks nothing existing, since it does not touch `parse()`, `ParseStats`, or any `Event` field.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥9.1.1 (already a dev dependency) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/test_eustack.py tests/test_eustack_rules.py -x` (new rules-loader/classifier test file) |
| Full suite command | `uv run pytest` (default marker exclusion already skips `perf`/`live`/`packaging`) |

### Phase Requirements → Test Map

| Req ID | Behaviour | Test Type | Automated Command | File Exists? |
|--------|-----------|-----------|--------------------|--------------|
| EUS-01 (SC1) | Every thread in the derivative fixture lands in exactly one of the 5 buckets, none unlabelled | unit | `pytest tests/test_eustack_rules.py::test_classification_partitions_all_threads -x` | ❌ Wave 0 |
| EUS-01 (SC2) | Editing the TOML (via `rules_path` override) changes classification with no Python edit/reinstall | integration | `pytest tests/test_eustack_rules.py::test_rules_path_override_changes_classification -x` | ❌ Wave 0 |
| EUS-01 (SC4, CI half) | The capped-representative `MSIQTask::GetNextPreferredJob` signature in the derivative fixture reads `idle-parked/job-queue` | unit | `pytest tests/test_eustack_rules.py::test_reference_derivative_headline_signature -x` | ❌ Wave 0 |
| EUS-01 (SC4, full-capture half) | The real 1,715/3,902 figures reproduce against the full out-of-repo capture | manual (phase verification) | run the classifier by hand against `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/`, record in phase summary — mirrors ADR 0013's out-of-repo verification style | N/A — not automatable in CI (source file not in repo) |
| EUS-01 (SC5) | Classification cost scales with distinct-signature count, not thread count | unit (proxy) | `pytest tests/test_eustack_rules.py::test_classification_is_per_signature_not_per_thread -x` (assert the match-loop is invoked once per distinct signature, e.g. via a call-counting stub around `classify()`) | ❌ Wave 0 |
| EUS-01 (SC5, full-capture) | Wall-clock scaling confirmed against the real 3,902-thread/93-signature capture | manual (phase verification) | timed run against the real capture, recorded in phase summary | N/A |
| EUS-02 (SC3) | An unmatched signature is reported `unclassified` with count + example frame, never folded into a known role | unit | `pytest tests/test_eustack_rules.py::test_unmatched_signature_reports_count_and_example -x` | ❌ Wave 0 |
| EUS-02 (D-07 split) | A thread whose every frame is unresolved (`??`/bare address) reports `no resolvable frame`, distinct from `unclassified` | unit | `pytest tests/test_eustack_rules.py::test_all_unresolved_frames_is_distinct_category -x` | ❌ Wave 0 |
| D-06 (load-time rejection) | An un-normalised pattern in the TOML is rejected at load with the canonical form in the message | unit | `pytest tests/test_eustack_rules.py::test_unnormalised_pattern_rejected_at_load -x` | ❌ Wave 0 |
| D-01 rule-ordering | The `MSIEvaluationTask::Run()`-ancestor busy signature classifies `running`, not `idle-parked`, under the recommended rule order | unit (regression, from this research's own finding) | `pytest tests/test_eustack_rules.py::test_running_rule_precedes_evaluation_ancestor_rule -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_eustack.py tests/test_eustack_rules.py -x`
- **Per wave merge:** `uv run pytest` (full suite) + `uv run ruff check` + `uv run pyright`
- **Phase gate:** full suite green before `/gsd-verify-work`; the two manual (full-capture) checks
  above recorded by hand in the phase summary, per D-14's own split between CI-fixture and
  verification-time measurement.

### Wave 0 Gaps

- [ ] `tests/test_eustack_rules.py` — new file, covers EUS-01/EUS-02's classifier/loader behaviour
      (all rows above)
- [ ] `tests/fixtures/eustack/reference_capture_derivative.txt` — new fixture, derived per "Building
      the signature-preserving fixture" above
- [ ] `tests/test_eustack.py` additions for `iter_frames()` (additive, existing file)
- [ ] `tests/test_config.py` additions for `EustackConfig`/`rules_path` (additive, existing file)
- [ ] Framework install: none — pytest/pydantic/tomllib all already present

## Common Pitfalls

*Beyond `.planning/research/PITFALLS.md`'s eight already-documented pitfalls (all still apply — see
in particular Pitfall 3 "symbol brittleness" and Pitfall 6 "per-signature not per-thread cost",
directly relevant here). This phase's own research surfaced one additional, more specific pitfall:*

### Pitfall: Shared-ancestor-frame rule ordering (verified this session, not in PITFALLS.md)

**What goes wrong:** A rule keyed on a task-dispatch or pool-loop frame (e.g.
`MSIEvaluationTask::Run()`) that is common to *both* a task's idle-wait state and its active-work
call chain, if placed before the rules that identify the task's actual working frames, silently
reclassifies busy threads as idle. This is a strictly narrower, code-level instance of Pitfall 1
("composition-blind heuristics") — but it can slip through even a taxonomy that correctly uses
composition (frame identity) rather than motion, purely because of file ordering.

**Why it happens:** D-09's `contains` matching tests "does this pattern appear anywhere in the
stack," not "is this the frame nearest the wait primitive." A curator writing an idle rule off the
milestone's own "self-labelling frame" table (`MILESTONE-CONTEXT-v1.3.md:79-90`) can reasonably
assume that table's frames are exclusively idle-associated — for most of the ten they are, but at
least one (`MSIEvaluationTask::Run`) is not, because it is also an ancestor of the busy call chain.

**How to avoid:** place `running` rules (the most specific, deepest, least-ambiguous signal) before
any broader ancestor-frame rule that shares a common dispatch frame with active work. Verified in
this research: with `running` rules first, the one busy `_shi_allocBlock`-leaf signature in the
reference capture correctly classifies `running` rather than falling through to the
`idle-parked/evaluation` rule.

**Warning signs:** a rule pattern matches a frame that also appears, at a different stack position,
in a signature containing one of the D-02 running-signal frames.

**Phase to address:** this phase (rules-matching engine design) — flag as a review checklist item
for any future rule additions to the file, not just the shipped evaluation rule.

## Don't Hand-Roll

No new items beyond `.planning/research/STACK.md`'s existing table (plain `str` matching over
`re`/trie; `collections.Counter` over `sklearn` for exact-signature grouping; `tomllib` over
hand-rolled parsing). This research does not re-derive those findings.

## Code Examples

See "Pattern: Rules-file schema" above for the full Pydantic model tree + loader, and "`iter_frames()`
on the shipped adapter" for the adapter-side addition. Both are complete, runnable-shaped examples
built directly against this repo's existing conventions (`config.py`, `eustack.py`), not generic
boilerplate.

## State of the Art

Not applicable in the usual "library version drift" sense — this phase adds no dependency. The one
relevant "current approach" note: `tomllib` (stdlib since 3.11, PEP 680) supersedes any third-party
TOML parser for this use case; already established in `.planning/research/STACK.md`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 24-rule initial set (subsystem names, exact pattern list) is a *reasonable starting point*, not a validated-optimal one — the coverage/rule-count curve was measured only against dump A of the two-dump reference capture, not cross-validated against dump B or any other server | Seeding the initial rules file | Low — D-14 already scopes verification against the full capture at phase-verification time, which would surface any gap; the rules file is explicitly editable post-ship (that is the whole point of EUS-01) |
| A2 | No containment guard recommended for `rules_path` | The `[eustack] rules_path` config key section | Low — matches existing `--kb` precedent (ADR 0009); if the security review disagrees, this is a one-line addition, not an architecture change |
| A3 | `cap=1` + selective higher cap for top signatures is the right fixture-derivation strategy | Building the signature-preserving fixture | Low-Medium — this is a Claude's Discretion area per CONTEXT.md; the measured sizes (140-243 KB depending on cap) are the load-bearing fact, the exact cap-per-signature policy is a judgement call the planner can adjust without re-deriving the underlying numbers |

**All package/library claims in this document are `[VERIFIED: repo]` (read directly from shipped
source) or `[VERIFIED: direct build test / direct capture parse]` (this session's own empirical
checks) — no `[ASSUMED]` package-name claims exist because this phase adds no new dependency.**

## Open Questions

1. **Exact final rule count and subsystem taxonomy for day one.**
   - What we know: the 24-rule set measured above achieves 98.67% thread / 56.99% signature
     coverage; the residual is a long tail of near-singleton background threads.
   - What's unclear: whether the planner wants to chase a few more of the named singletons (Kafka,
     index-manager, session-backup) for a rounder coverage number, or ship 24 and treat the rest as
     disclosed `unclassified` by design.
   - Recommendation: ship the 24-rule set as a floor; treat "add more rules" as a data change any
     time post-ship (that is the entire point of the versioned, Python-free-editable file) rather
     than a blocker to this phase's completion.

2. **Whether the fixture derivation script should be a permanent repo artefact or a one-off.**
   - What we know: it needs the out-of-repo 2.4 MB capture as input, so it cannot run in CI.
   - What's unclear: whether keeping it (undiscoverable by CI, but reproducible if the fixture ever
     needs regenerating against an updated capture) outweighs the "why does this repo have a script
     that can never run in tests" question a future reader might have.
   - Recommendation: keep it, documented clearly as a manual/offline tool (e.g. under `scripts/`
     with a docstring explaining it needs a local capture file), mirroring the project's existing
     `docs/reference/analyze_dss8.py` vendored-reference precedent for "code that exists for
     provenance, not for CI."

## Environment Availability

Not applicable — this phase has no external tool/service/runtime dependency beyond what is already
installed (Python 3.12+, `uv`, the existing dev/runtime dependency set). No new CLI, database, or
network dependency is introduced.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase has no auth surface — library module, no CLI, no network |
| V3 Session Management | No | No session concept in this phase |
| V4 Access Control | No | No access-control surface |
| V5 Input Validation | Yes | Pydantic `extra="forbid"` + `Literal` role + non-empty-pattern + normalised-pattern validators on every rules-file field (see "Pattern: Rules-file schema"); `tomllib` for parsing (no code-execution tag mechanism, unlike YAML) |
| V6 Cryptography | No (informational use only) | `sha256(text)[:16]` content hash is a provenance/versioning tag (D-11), not a security boundary — mirrors the existing non-security `event_id`/`template_id`/`cluster_label_prompt_hash` idiom; do not treat it as integrity protection |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Arbitrary-path read via `[eustack] rules_path` | Information Disclosure (self-inflicted — user reads their own file) | No containment guard, matching the existing `--kb` (ADR 0009) precedent — the path is user-supplied to read the user's own local file, not attacker-controlled input to a server; see "Open Questions"/A2 |
| Malformed/malicious TOML causing unexpected code execution | Tampering | `tomllib` has no tag/anchor/code-execution mechanism (unlike YAML's `!!python/object`) — a malformed file can only fail to parse (`TOMLDecodeError` → `ValueError`) or fail Pydantic validation, never execute attacker content |
| A loosely-matched rule pattern colliding with an unrelated frame (the ADR 0013 class of bug) | Tampering (of classification output, not of Sift itself) | D-09's `exact`-by-default + explicit `match` field is the mitigation already locked into the schema; `contains` stays available but every use is `grep`-visible in a diff, per D-09's own rationale |

## Sources

### Primary (HIGH confidence)
- `src/sift/config.py` (full file) — `McmThresholdsConfig`/`McmConfig`/`SiftConfig`/`load_config`/`_ENV_SCALARS` shapes mirrored throughout this research
- `src/sift/adapters/eustack.py` (full file) — `_FRAME_RE`, `_condense_symbol`, `CONDENSED_FRAMES`, `MAX_EVENT_LINES`, `Event.raw` construction
- `src/sift/pipeline/mcm.py`, `src/sift/pipeline/perfmon.py` (module docstrings + structure) — single-module-per-analysis shape
- `src/sift/prompts/__init__.py`, `pyproject.toml` — package-data precedent
- `tests/test_config.py`, `tests/test_eustack.py`, `tests/test_packaging.py` (full files) — test-shape precedents and constraint checks
- `src/sift/store.py:1087-1096` (`get_meta`/`set_meta`), `src/sift/pipeline/cluster.py:216-218,399` (`_template_hash`, `set_meta("cluster_label_prompt_hash", ...)`) — content-hash idiom
- Direct parse of `/home/oliverh/Downloads/iserver1_stacks_1-minute_diff/stack_env-hnyjbci1u11xhyl5-iserver-1_1363967_20260410_160739 (12_07 PM EST).txt` (throwaway Python, this session, not committed) — signature/coverage/fixture-size measurements throughout
- Direct `uv build --wheel` test against a temporarily-added `src/sift/rules/` (this session, removed after) — packaging verification

### Secondary (MEDIUM confidence)
- `.planning/research/{MILESTONE-CONTEXT-v1.3,STACK,ARCHITECTURE,PITFALLS,SUMMARY}.md` — the settled v1.3 milestone research this phase builds on and does not re-derive
- `.planning/phases/15-thread-role-taxonomy-rules-file/15-CONTEXT.md` — the 16 locked decisions this research implements

### Tertiary (LOW confidence)
- None — every claim in this document is either read directly from the repo, measured directly
  against the reference capture, or verified via a direct build test this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependency, every claim verified against shipped source
- Architecture: HIGH — every pattern mirrors an existing, read, shipped module
- Rules-file coverage numbers: HIGH — measured directly against the real reference capture, not estimated
- Pitfalls: HIGH for the newly-surfaced rule-ordering finding (empirically demonstrated); MEDIUM for
  the "which additional rules to add" discretion call (inherently a judgement, not a fact)

**Research date:** 2026-07-25
**Valid until:** stable — no external dependency to drift; re-validate only if the reference capture
is replaced/supplemented with a different server's dump (would change the measured coverage numbers)
