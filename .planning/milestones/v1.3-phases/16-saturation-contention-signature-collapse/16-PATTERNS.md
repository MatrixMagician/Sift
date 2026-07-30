# Phase 16: Saturation, Contention & Signature Collapse - Pattern Map

**Mapped:** 2026-07-25
**Files analyzed:** 3 (library-only phase)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| Saturation analysis code (`SaturationAnalysis` + `analyse_saturation()` + `PoolOccupancy`/`LockSite`/`DependencyWait`/flag record + frame-walk helper) — either appended to `src/sift/pipeline/eustack.py` OR a new sibling `src/sift/pipeline/eustack_saturation.py` | service/model (pure transform) | transform (CRUD-free aggregation over an in-memory model) | `src/sift/pipeline/mcm.py` (flag/grade pattern) + `src/sift/pipeline/perfmon.py` (sibling-record pattern) + `src/sift/pipeline/eustack.py` (grouping/sort/frame-walk source data) | exact (three-way composite; no single file covers all three sub-behaviours) |
| `src/sift/config.py` — new `EustackThresholdsConfig` + extend `EustackConfig` | config | request-response (load-time validation) | `McmThresholdsConfig` / `ThresholdPair` / `McmConfig` (same file, lines 85-127) | exact |
| `tests/test_eustack_rules.py` (extend) or new `tests/test_eustack_saturation.py` | test | batch (fixture-driven unit tests) | `tests/test_eustack_rules.py` itself (helpers + ownership-blind test) + `tests/test_mcm.py`/`tests/test_perfmon.py` (graded-flag fixture style) | exact |

## Pattern Assignments

### Saturation analysis module (new symbols in `eustack.py` or a sibling module)

**Analogs:** `src/sift/pipeline/eustack.py` (source data + grouping/sort discipline), `src/sift/pipeline/mcm.py` (`_grade`, `DiagnosticFlag`), `src/sift/pipeline/perfmon.py` (`PerfmonHazard` — the "don't force DiagnosticFlag" precedent)

**D-10 module-placement choice (both options, so the planner can decide):**
- **Option A — extend in place** (`src/sift/pipeline/eustack.py`, currently 374 lines, ends at line 373 with `analyse_eustack()`). Precedent: `mcm.py` and `perfmon.py` each keep their whole domain (detection + flags) in one file. Add new symbols directly below `analyse_eustack()` (after line 374), reusing its module-level imports (`Counter`, `BaseModel`, `ConfigDict`, `Literal`) — no new import block needed except `from sift.pipeline.mcm import _grade`.
- **Option B — new sibling module** `src/sift/pipeline/eustack_saturation.py`. Precedent for the sibling-module shape: `perfmon.py` + `perfmon_facts.py` are two files, but that split is detection-vs-render (Phase 17's job), not detection-vs-detection — so Option B has no exact analog in this codebase; it is a defensible deviation, not a mirrored pattern. If chosen, the new file's header docstring should copy `eustack.py`'s own opening structure (lines 1-19) verbatim in spirit: typer-free/print-free/SQL-free/I-O-free declaration, determinism contract.

**Imports pattern** (`eustack.py` lines 21-41 — reuse verbatim if extending in place, or as the template for a sibling module's import block):
```python
from __future__ import annotations

import hashlib
import importlib.resources
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

if TYPE_CHECKING:
    from sift.models import Event

# Shared, not copied (D-08): iter_frames and _condense_symbol live on the
# shipped adapter; a second frame regex here would be free to drift from it.
from sift.adapters.eustack import (
    _condense_symbol,  # pyright: ignore[reportPrivateUsage]
    iter_frames,
)
```
Plus, new for Phase 16 (either option): `from sift.pipeline.mcm import _grade  # pyright: ignore[reportPrivateUsage]` — the exact "shared, not copied" cross-module reuse already established for `_condense_symbol`.

**Core pattern 1 — grouping-with-explicit-total-order (EUS-03 pools, EUS-05 dependencies)**

Analog: `analyse_eustack()`'s own accumulation + explicit sort, `eustack.py` lines 338-361 (verbatim):
```python
groups: list[SignatureGroup] = []
for signature, thread_count in counts.items():
    classification = classify_signature(signature, rules)
    groups.append(
        SignatureGroup(
            frames=signature,
            thread_count=thread_count,
            role=classification.role,
            subsystem=classification.subsystem,
            pattern=classification.pattern,
            frame_index=classification.frame_index,
            reason=classification.reason,
        )
    )
# Explicit total order: thread count descending, ties broken ascending on
# the frames tuple. Never Counter.most_common() (its tie behaviour is
# unspecified) and never a set iteration.
groups.sort(key=lambda g: (-g.thread_count, g.frames))

threads_by_role: dict[Role, int] = {role: 0 for role in _ALL_ROLES}
signatures_by_role: dict[Role, int] = {role: 0 for role in _ALL_ROLES}
for group in groups:
    threads_by_role[group.role] += group.thread_count
    signatures_by_role[group.role] += 1
```
Copy the discipline, not the code: `dict`-based tally (matches RESEARCH.md's Pattern 1 `defaultdict` example over `Counter.most_common()`), then `.sort(key=lambda x: (-count, tiebreak))` with a NAMED tie-break field — never bare `Counter.most_common()`, never set iteration. Three separate passes needed: pools (group all signatures by `subsystem`, split idle-parked vs rest per D-01/D-02, `subsystem` typed `str | None`), lock sites (group `blocked-on-lock` signatures by resolved site — see Pattern 2 below), dependencies (group `blocked-on-external` signatures by `subsystem` verbatim per D-06).

RESEARCH.md's concrete grouping shape (for pools/dependencies tally):
```python
from collections import defaultdict

pool_totals: dict[str | None, int] = defaultdict(int)
pool_idle: dict[str | None, int] = defaultdict(int)
for group in analysis.signatures:
    pool_totals[group.subsystem] += group.thread_count
    if group.role == "idle-parked":
        pool_idle[group.subsystem] += group.thread_count
```

**Core pattern 2 — the D-04 frame-walk helper (EUS-04)**

Analog: `_is_resolvable()` (`eustack.py` lines 200-213, copy verbatim/import) and `classify_signature()`'s own frame iteration style (lines 216-268) — but note `classify_signature` iterates `enumerate(signature)` from index 0 outward across ALL frames testing EVERY rule; the new walk is narrower: start at `frame_index + 1` (NOT 0), stop at the first hit, single denylist test, no rules file involved.

```python
# eustack.py:200-213 — copy or import verbatim, do not re-implement
_BARE_ADDRESS_RE = re.compile(r"^0x[0-9A-Fa-f]+$")

def _is_resolvable(symbol: str) -> bool:
    if not symbol or symbol == "??":
        return False
    return _BARE_ADDRESS_RE.match(symbol) is None
```

New helper (per D-04 AMENDED — leading-namespace denylist, not the RESEARCH.md draft's bare `"::" in frame` test which Pitfall 3 shows is wrong):
```python
_RUNTIME_NAMESPACE_DENYLIST = ("std::", "boost::", "__gnu_cxx::", "abi::")

def _find_enclosing_frame(frames: tuple[str, ...], frame_index: int) -> str | None:
    """D-03/D-04: the first resolvable, '::'-qualified, non-runtime frame
    ABOVE frame_index (increasing index — iter_frames() yields #1, #2, #3...
    leaf-to-entry-point; see test_eustack_rules.py:33-47 for the worked
    #0 leaf -> #3 classifying frame -> #4 entry-point example).

    `frames` entries are already normalise()'d — no re-normalisation here.
    Match the denylist against the symbol's LEADING namespace only (prefix,
    never substring) so a template argument containing e.g. std:: nested
    inside a genuine MBase:: frame is not misjudged (D-04 edge case 3).
    Returns None when no such frame exists — the caller reports
    unknown-but-counted (D-04), never drops the thread, never attributes
    it to the leaf.
    """
    for frame in frames[frame_index + 1 :]:
        if not _is_resolvable(frame):
            continue
        if "::" not in frame:
            continue
        if frame.startswith(_RUNTIME_NAMESPACE_DENYLIST):
            continue
        return frame
    return None
```
Note `str.startswith(tuple)` gives the leading-namespace-only, prefix-not-substring test for free — no need for a per-entry loop.

**Core pattern 3 — the graded-flag record and `_grade()` reuse (Success Criterion 5)**

Analog A — `mcm.py::_grade()`, lines 609-624 (import verbatim, do not re-derive):
```python
def _grade(value_pct: float, warn: float, crit: float, *, invert: bool = False) -> str:
    """Grade a ratio into info/warn/critical against two cut-points.
    ...
    """
    if invert:
        if value_pct <= crit:
            return "critical"
        return "warn" if value_pct <= warn else "info"
    if value_pct >= crit:
        return "critical"
    return "warn" if value_pct >= warn else "info"
```
Import as: `from sift.pipeline.mcm import _grade  # pyright: ignore[reportPrivateUsage]` — mirrors the `_condense_symbol` cross-module reuse already established in `eustack.py:39`. `_grade` is pure/stateless and does not care whether its input is a ratio or (per D-08) a raw count — it can grade all three flags uniformly.

Analog B — `mcm.py::DiagnosticFlag`, lines 221-237 (reuse VERBATIM for the two true-ratio flags: unclassified-thread-share, no-resolvable-frame-share):
```python
class DiagnosticFlag(BaseModel):
    """One graded MCM diagnostic signal (D-12 / MCM-03).

    ``value_pct`` is ALWAYS a ratio ``part / whole * 100`` — never an absolute GB
    (the milestone-locked machine-independence invariant: scaling every absolute
    figure by any constant leaves every flag tier and displayed % identical).
    ``event_ids`` cites the denial event whose Info-Dump block the figure was
    parsed from (D-16 provenance).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    severity: str  # "info" | "warn" | "critical"
    value_pct: float
    message: str
    event_ids: tuple[str, ...]
```

Analog C — `perfmon.py::PerfmonHazard`, lines 119-143 — the DIRECT precedent for why a raw-count flag (lock convergence, D-08 AMENDED) must NOT be forced into `DiagnosticFlag.value_pct`. Copy this record shape for the new sibling flag type used by the lock-convergence check (rename fields to fit; `event_ids` may be `()` since eu-stack threads have no per-thread event_id concept the way MCM denials do — verify against `Event`/`SignatureGroup` before assuming event_ids applies):
```python
class PerfmonHazard(BaseModel):
    """One graded perfmon correlation hazard (D-12).

    Severities are categorical string literals fixed in code — ``mcm._grade`` is
    deliberately NOT called, because these hazards grade structural conditions
    ...

    ``mcm.DiagnosticFlag`` is deliberately not reused: its ``value_pct`` is locked
    as a ratio ``part / whole * 100`` (the milestone machine-independence
    invariant), and a perfmon hazard's figure is an absolute counter reading or
    nothing at all. ``event_ids`` keeps the same D-16 provenance discipline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    severity: Literal["info", "warn", "critical"]
    message: str
    event_ids: tuple[str, ...]
    value: float | None = None
```
Note `PerfmonHazard` explicitly does NOT call `_grade()` (its severities are structural, not ratio-graded) — Phase 16's count flag is the opposite case: it DOES want `_grade()` (per D-08 AMENDED: "reuse `_grade()` verbatim... mint one sibling record type for the count flag"). So the new record should copy `PerfmonHazard`'s FIELD SHAPE (generic `value: float | None`, `Literal` severity) but DOES call `_grade()` at construction time, unlike `PerfmonHazard` itself. Use `Literal["info", "warn", "critical"]` (not bare `str` as `DiagnosticFlag` does) — `PerfmonHazard`'s docstring at lines 137-140 explains why: Pydantic rejects a typo'd severity at construction, pyright catches it at the call site.

**Fixed declared-order flag list (not sorted):** `mcm.py`'s `compute_flags()` (starts line 627) appends flags in a fixed, authored check order — mirror this for the three-check pass (unclassified-share, then no-resolvable-frame, then lock-convergence), per RESEARCH.md Pattern 3.

---

### `src/sift/config.py` (config, request-response) — extend `EustackConfig`

**Analog:** `ThresholdPair` / `McmThresholdsConfig` / `McmConfig`, same file lines 85-127 (verbatim structure to mirror):
```python
class ThresholdPair(BaseModel):
    """A (warn, critical) severity cut-point pair for one MCM diagnostic ratio."""

    model_config = ConfigDict(extra="forbid")

    warn: float
    critical: float


class McmThresholdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    working_set_pct_virtual: ThresholdPair = ThresholdPair(warn=20, critical=40)
    other_processes_pct_physical: ThresholdPair = ThresholdPair(warn=10, critical=20)
    ...


class McmConfig(BaseModel):
    """``[mcm]`` wrapper so the TOML table is literally ``[mcm.thresholds]``."""

    model_config = ConfigDict(extra="forbid")

    thresholds: McmThresholdsConfig = McmThresholdsConfig()
```

Current `EustackConfig` to extend (`config.py` lines 124-130 — verbatim, existing):
```python
class EustackConfig(BaseModel):
    """``[eustack]`` wrapper, mirrors McmConfig's nested-key shape."""

    model_config = ConfigDict(extra="forbid")

    # None -> load the packaged default via importlib.resources
    rules_path: str | None = None
```

Target shape (mirror `McmThresholdsConfig`'s nesting exactly — `ThresholdPair` is reused as-is even for the count threshold, per RESEARCH.md: `_grade()` compares floats regardless of what they represent):
```python
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

**Validation pattern:** `extra="forbid"` on every level (already the project-wide convention, T-04-02) — a typo'd threshold key raises `ValidationError` at load time. No new pattern needed beyond copying the existing `McmThresholdsConfig`/`McmConfig` nesting.

---

### `tests/test_eustack_rules.py` (extend) or new `tests/test_eustack_saturation.py`

**Analog:** the same file's own existing helpers and test style, `tests/test_eustack_rules.py` lines 308-343 (reuse verbatim; if a sibling module is chosen, either import these three helpers from `test_eustack_rules.py` or duplicate them in the new file):
```python
def _thread_raw(*frames: str) -> str:
    """One synthetic ``TID N:`` block with the given (already-normalised)
    frame symbols, in the ``#N 0xADDR symbol`` shape ``iter_frames`` expects."""
    lines = ["TID 1:\n"]
    for index, frame in enumerate(frames):
        lines.append(f"#{index}  0x{index:016x} {frame}\n")
    return "".join(lines)


def _event(raw: str, thread: str | None) -> Event:
    """A minimal, otherwise-inert Event carrying only what analyse_eustack
    reads: `.raw` (signature source) and `.thread` (the is-a-thread marker)."""
    return Event(
        event_id="0" * 16,
        case_id="case",
        ts=None,
        ts_confidence="missing",
        source="eustack",
        source_file="dump.txt",
        line_start=1,
        line_end=1,
        severity="unknown",
        component=None,
        thread=thread,
        session=None,
        message="",
        attrs={},
        raw=raw,
    )


def _parse_derivative_fixture() -> list[Event]:
    adapter = EustackAdapter()
    return list(
        adapter.parse(FIXTURES / "reference_capture_derivative.txt", "case-1")
    )
```

**Fixture-assertion style for a grouped result** (`tests/test_eustack_rules.py` lines 357-376, e.g. `test_unmatched_signature_reports_count_and_example`):
```python
def test_unmatched_signature_reports_count_and_example() -> None:
    raw = _thread_raw("TotallyUnrecognisedApplicationFrame::Nobody")
    events = [_event(raw, thread=str(i)) for i in range(3)]
    rules, rules_hash = load_rules()
    analysis = analyse_eustack(events, rules, rules_hash)

    assert len(analysis.unclassified) == 1
    group = analysis.unclassified[0]
    assert group.thread_count == 3
    ...
```
Follow this shape for the three new grouping tests (pools/lock-sites/dependencies): build synthetic `_thread_raw()` stacks with known `subsystem`-mapped patterns, run `analyse_eustack()` first to get `EustackAnalysis`, then feed it into the new `analyse_saturation()`/equivalent and assert on the grouped output.

**The ownership-blind mechanical prohibition test to extend/reuse** (`tests/test_eustack_rules.py` lines 569-589 — reads the forbidden term from `REQUIREMENTS.md` at runtime):
```python
def test_no_ownership_attributed_lock_language_in_shipped_surface() -> None:
    """The lock-ownership term REQUIREMENTS.md's Out of Scope table names as
    a permanent non-goal appears nowhere in the shipped rules file or
    classifier module. Read from REQUIREMENTS.md at runtime rather than
    hardcoded, so the test cannot itself become the only place it's typed."""
    requirements_text = _REQUIREMENTS_MD.read_text(encoding="utf-8")
    match = re.search(r'the word "(\w+)"', requirements_text)
    assert match is not None, "REQUIREMENTS.md must name the forbidden term"
    forbidden_term = match.group(1)

    rules_toml = (
        Path(__file__).parent.parent
        / "src" / "sift" / "rules" / "eustack_roles.toml"
    ).read_text(encoding="utf-8")
    classifier_source = (
        Path(__file__).parent.parent / "src" / "sift" / "pipeline" / "eustack.py"
    ).read_text(encoding="utf-8")
```
D-05 requires this same check over the NEW module's source too — if Option A (extend `eustack.py` in place) is chosen, this test already covers it with zero changes (it re-reads `eustack.py`'s full source each run). If Option B (sibling module) is chosen, add a third `Path(...)` read for `eustack_saturation.py` and assert the forbidden term is absent there too.

**Graded-flag fixture style (secondary analog):** `tests/test_mcm.py` and `tests/test_perfmon.py` — both build a minimal synthetic scenario, call the analyser, then assert `severity`/`value`/`message` fields on the returned flag/hazard record. Not read verbatim this session (line budget); same shape as the `test_unmatched_signature_reports_count_and_example` pattern above — construct input that should trigger warn/critical, and a second case that should trigger nothing (D-09's "zero flags on healthy input" gate).

---

## Shared Patterns

### Grading (`_grade`)
**Source:** `src/sift/pipeline/mcm.py:609-624`
**Apply to:** all three Phase 16 flag checks (unclassified-share, no-resolvable-frame-share, lock-convergence-count) — import, do not re-derive.

### Frozen, `extra="forbid"` Pydantic models
**Source:** every model in `eustack.py` (`Rule`, `Classification`, `SignatureGroup`, `EustackAnalysis`) and `mcm.py`/`perfmon.py`
**Apply to:** `SaturationAnalysis` and every sub-record (`PoolOccupancy`, `LockSite`, `DependencyWait`, the new flag record) — `model_config = ConfigDict(extra="forbid", frozen=True)` on all of them, matching D-10's "new frozen Pydantic model" requirement.

### Explicit total order, never `Counter.most_common()`/set iteration
**Source:** `eustack.py:352-355` (`analyse_eustack`'s own sort + its inline comment)
**Apply to:** the three new groupings (pools, lock sites, dependencies) — each needs a named `sort(key=...)` with an explicit tie-break field, exactly as `analyse_eustack` demonstrates.

### Cross-module "shared, not copied" reuse
**Source:** `eustack.py:36-41` (`_condense_symbol`/`iter_frames` imported from `adapters/eustack.py`, with the `# pyright: ignore[reportPrivateUsage]` comment explaining why)
**Apply to:** importing `mcm._grade` into the new saturation code — same comment convention, same `pyright: ignore[reportPrivateUsage]` marker.

### Config nesting under `SiftConfig`
**Source:** `config.py:85-127` (`ThresholdPair`/`McmThresholdsConfig`/`McmConfig`)
**Apply to:** `EustackThresholdsConfig`/`EustackConfig` — identical nesting shape, `extra="forbid"` at every level.

## No Analog Found

None — every file in this phase's known set has a strong, directly-applicable in-repo analog (this is an explicit strength of the phase: RESEARCH.md notes zero new dependencies and every reused symbol read directly from source this session).

## Metadata

**Analog search scope:** `src/sift/pipeline/` (`eustack.py`, `mcm.py`, `perfmon.py`), `src/sift/config.py`, `tests/test_eustack_rules.py`
**Files scanned:** 5 (all fully or targeted-read this session; `CONTEXT.md`/`RESEARCH.md` supplied exact line numbers, verified by direct read against current source)
**Pattern extraction date:** 2026-07-25
