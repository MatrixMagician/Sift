# Phase 15: Thread-Role Taxonomy & Rules File - Pattern Map

**Mapped:** 2026-07-25
**Files analyzed:** 9 (5 created, 4 modified — `pyproject.toml` excluded, verified not needed)
**Analogs found:** 9 / 9

RESEARCH.md's line-number citations were checked against the live source. All confirmed
accurate except the `McmThresholdsConfig`/`McmConfig` range, corrected below. Corrections are
called out inline with **[CORRECTED]**.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/sift/rules/__init__.py` | config/package-data marker | file-I/O (static) | `src/sift/prompts/__init__.py` | exact |
| `src/sift/rules/eustack_roles.toml` | config (package data) | file-I/O (static) | `src/sift/prompts/*.md` (package-data shape); `~/.config/sift/config.toml` shape (TOML syntax) | role-match |
| `src/sift/pipeline/eustack.py` | service (pure analysis: models + loader + normaliser + classifier) | transform (batch, CRUD-free) | `src/sift/pipeline/mcm.py`, `src/sift/pipeline/perfmon.py` | exact |
| `tests/test_eustack_rules.py` | test | request-response (unit) | `tests/test_config.py` (loader error-path shape) + `tests/test_eustack.py` (fixture-loading convention) | role-match |
| `tests/fixtures/eustack/reference_capture_derivative.txt` | fixture data | file-I/O (static) | `tests/fixtures/eustack/threaddump.txt` | exact |
| `src/sift/adapters/eustack.py` (additive `iter_frames()`) | adapter (parser) | streaming (line-by-line) | itself — extends existing `_FRAME_RE`/`_condense_symbol`/`parse()` in the same file | exact |
| `src/sift/config.py` (`EustackConfig`) | config model | CRUD (load/merge) | `McmConfig`/`McmThresholdsConfig` in the same file | exact |
| `tests/test_eustack.py` (additive `iter_frames()` cases) | test | request-response (unit) | existing tests in the same file | exact |
| `tests/test_config.py` (additive `EustackConfig` cases) | test | request-response (unit) | existing `mcm`/`embeddings` section tests in the same file | exact |

`pyproject.toml`: **no change needed.** RESEARCH.md verified by direct `uv build --wheel` test
that `src/sift/rules/*.toml` and `__init__.py` ship automatically under `uv_build` with zero
`pyproject.toml` edits, mirroring `src/sift/prompts/*.md` today (no `package-data`/`include`
stanza exists for prompts either). Do not add one.

## Pattern Assignments

### `src/sift/rules/__init__.py` (package marker)

**Analog:** `src/sift/prompts/__init__.py` (verbatim structure to copy)

```python
"""Versioned prompt templates (CLI-02).

This package exists so ``importlib.resources`` can load the ``*.md`` prompt
templates as package data. All prompts are plain-text files here — changing a
prompt must never require a Python change (CLI-02). The templates are loaded,
never executed, and log-derived excerpts interpolated into them are treated as
untrusted data, not instructions.
"""
```

Write `src/sift/rules/__init__.py` as the same shape: a docstring only, explaining the package
exists so `importlib.resources` can load `eustack_roles.toml` as package data, that editing the
TOML must never require a Python change (EUS-01), and that rule patterns are matched as data,
never executed (mirrors the "loaded, never executed" framing for prompts).

---

### `src/sift/pipeline/eustack.py` (service, transform)

**Analogs:** `src/sift/pipeline/mcm.py` (module-docstring shape) and
`src/sift/pipeline/perfmon.py` (module-docstring + constants shape) — both single-module-per-
analysis files. `src/sift/config.py:94-121` (Pydantic model tree) and
`src/sift/pipeline/mcm_facts.py:70-80` (`importlib.resources` loader idiom).

**Module docstring pattern** — `mcm.py` lines 1-21 and `perfmon.py` lines 1-11, both establish:
(1) a one-line purpose + requirement IDs, (2) an explicit "pure and deterministic" contract
statement naming what it never touches (network/store/CLI/filesystem for `mcm.py`; store/CLI/
model for `perfmon.py`), (3) a determinism/ordering guarantee. `pipeline/eustack.py`'s docstring
should state: purpose + EUS-01/EUS-02, that classification is pure over `list[Event]` + loaded
rules with no store/CLI/network dependency (RESEARCH.md's own Architectural Responsibility Map
row), and the D-03/D-05 determinism contract (signature keyed on normalised symbols, addresses
excluded).

```python
# mcm.py:1-21 — module docstring shape to mirror
"""Deterministic MCM (Memory Contract Manager) episode analyser (MCM-01, MCM-02).

Milestone v1.1's numeric core. Like ``salience.py`` this module is typer-free,
print-free, SQL-free and I/O-free: the caller passes in already-queried
``Event`` rows and receives typed models back. It NEVER talks to the network,
an LLM, a subprocess or the filesystem — the figures reported here are computed
from stored log text, never authored by a model. ...
"""
```

```python
# perfmon.py:1-11 — sibling shape, shorter
"""Correlate DSSPerformanceMonitor samples with MCM denial episodes (PERF-04).

Pure and deterministic: this module computes per-counter trend figures over the
span an MCM episode already resolved, and never touches the store, the CLI or a
model. Every figure carries the ``event_id`` of the sample it came from, so it
can be checked by hand against two rows of the customer's CSV.

Determinism contract (D-21), in ``analyse_mcm``'s words: ``model_dump_json`` is
byte-identical on re-run — no ``set`` iteration anywhere on the path, all
rounding at source, all ordering explicit.
"""
```

**Constants-and-imports layout** — both `mcm.py` and `perfmon.py` put `from __future__ import
annotations`, stdlib imports, then `from pydantic import BaseModel, ConfigDict`, then a
`TYPE_CHECKING`-guarded import block for cross-module types (`Event`, sibling analysis models),
then module-level regex/constant definitions with an explanatory comment tying each constant to a
decision ID. `pipeline/eustack.py` should follow this exactly: `Role`/`MatchKind` `Literal`
constants, `iter_frames` imported from `sift.adapters.eustack` (not `TYPE_CHECKING`-guarded — it
is a runtime import, a real function call), `Event` under `TYPE_CHECKING` if only used for type
hints.

**Rules-file schema (Pydantic model tree)** — mirrors `config.py`'s `ThresholdPair`/
`McmThresholdsConfig`/`McmConfig` nesting shape. RESEARCH.md's full code example (`Rule`,
`RulesMeta`, `ThreadRoleRules` classes with `field_validator`/`model_validator`) is verified
correct against the `ConfigDict(extra="forbid")` idiom actually used at `config.py:88` (
`ThresholdPair`), `config.py:106` (`McmThresholdsConfig`), `config.py:119`
(`McmConfig`) and `config.py:126` (`SiftConfig`) — every model in the file uses this exact idiom,
no exceptions. Use it verbatim for `Rule`/`RulesMeta`/`ThreadRoleRules`.

**Loader (`importlib.resources` idiom)** — verified against `mcm_facts.py:70-80`:

```python
# src/sift/pipeline/mcm_facts.py:70-80 — the exact call shape to mirror
def _load_mcm_fragment() -> str:
    """Load the versioned MCM fragment from package data (CLI-02).

    Mirrors ``hypothesise._load_triage_template`` — the same
    ``importlib.resources`` idiom, so wording changes touch no path maths.
    """
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(_MCM_FILE)
        .read_text(encoding="utf-8")
    )
```

`cluster.py:210` and `perfmon_facts.py:101` use the identical three-line chain
(`importlib.resources.files(<package>).joinpath(<file>).read_text(encoding="utf-8")`) —
`encoding="utf-8"` is always passed explicitly, never omitted. The package constant is always a
private module-level string (`_PROMPT_PACKAGE`, e.g. `"sift.prompts"`); `pipeline/eustack.py`
should declare `_RULES_PACKAGE = "sift.rules"` and `_RULES_FILE = "eustack_roles.toml"` the same
way.

**Error surfacing on load** — mirror `config.py:186-192` (**[CORRECTED]** RESEARCH.md cited
`config.py:186-192`; verified exact — no drift):

```python
# src/sift/config.py:186-192
if cfg_path.exists():
    try:
        layers |= tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        # Never fall back to defaults silently on a malformed file (T-04-02).
        raise ValueError(f"invalid config file {cfg_path}: {exc}") from exc
```

`load_rules()` in `pipeline/eustack.py` should catch `tomllib.TOMLDecodeError` the same way,
re-raising as `ValueError` naming the source file/package, then let `ThreadRoleRules.model_validate`
raise `ValidationError` unwrapped for schema violations — exactly SiftConfig's own pattern (no
`try`/`except` around `model_validate` anywhere in `config.py`).

**Content hash idiom** — `sha256(text)[:16]` per D-11, matching the `cluster_label_prompt_hash`/
`event_id`/`template_id` idiom (`hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]`). Confirm
this pattern in `pipeline/cluster.py` around the `set_meta("cluster_label_prompt_hash", ...)` call
before copying if exact wording is needed for a docstring cross-reference.

---

### `src/sift/config.py` — `EustackConfig` (config model)

**Analog:** `McmConfig`/`McmThresholdsConfig` in the same file.

**[CORRECTED]** RESEARCH.md cites `config.py:94-121` for "`McmThresholdsConfig`/`McmConfig`" as
one range; the actual boundaries, verified by direct read, are:
- `ThresholdPair` — lines 85-91
- `McmThresholdsConfig` — lines 94-113
- `McmConfig` — lines 116-121
- `SiftConfig` — lines 124-148

The pattern-mapping context's cited "`config.py:85-130`" is the correct outer bound; use that,
not RESEARCH.md's narrower `94-121`.

```python
# src/sift/config.py:116-121 — the nested-wrapper shape EustackConfig copies exactly
class McmConfig(BaseModel):
    """``[mcm]`` wrapper so the TOML table is literally ``[mcm.thresholds]``."""

    model_config = ConfigDict(extra="forbid")

    thresholds: McmThresholdsConfig = McmThresholdsConfig()
```

`EustackConfig` is simpler — one optional scalar field, no further nesting:

```python
class EustackConfig(BaseModel):
    """``[eustack]`` wrapper, mirrors McmConfig's nested-key shape."""

    model_config = ConfigDict(extra="forbid")

    rules_path: str | None = None   # None -> load the packaged default via importlib.resources
```

**Composing into `SiftConfig`** — `config.py:124-134` (verified: `SiftConfig` fields at lines
128-134, `mcm: McmConfig = McmConfig()` at line 134):

```python
# src/sift/config.py:128-134
data_dir: Path
timezones: dict[str, str] = {}
adapters: dict[str, str] = {}
generation: GenerationConfig = GenerationConfig()
embeddings: EmbeddingsConfig = EmbeddingsConfig()
clustering: ClusteringConfig = ClusteringConfig()
mcm: McmConfig = McmConfig()
```

Add `eustack: EustackConfig = EustackConfig()` as a new line directly after `mcm`.

**Env-var precedence** — `_ENV_SCALARS` dict, verified at `config.py:154-166` (exact, no drift
from RESEARCH.md's citation):

```python
# src/sift/config.py:154-166
_ENV_SCALARS: dict[str, tuple[str, str]] = {
    "SIFT_GENERATION_BASE_URL": ("generation", "base_url"),
    ...
    "SIFT_EMBEDDINGS_CONTEXT": ("embeddings", "context"),
}
```

Add one entry: `"SIFT_EUSTACK_RULES_PATH": ("eustack", "rules_path"),`. No other change is
needed — `load_config` (`config.py:181-213`, verified exact) iterates `_ENV_SCALARS` generically
via `_set_nested(layers, section, field, value)` (`config.py:169-178`), and `SiftConfig.model_validate(layers)`
at the end (`config.py:213`) picks up the new nested section automatically. CLI-flag override
merging (`config.py:199-212`) is also generic per-section — no eustack-specific code needed there
either.

---

### `src/sift/adapters/eustack.py` — additive `iter_frames()`

**Analog:** the file's own existing `_FRAME_RE`/`_condense_symbol`, extended in place.

Verified exact locations (no drift from RESEARCH.md/context citations):
- `_FRAME_RE` — line 57: `re.compile(r"^#(\d+)\s+0x([0-9A-Fa-f]+)\s+(.+)$")`
- `_condense_symbol` — lines 69-73
- `MAX_EVENT_LINES` — line 47 (`= 256`)
- `CONDENSED_FRAMES` — line 51 (`= 5`)
- shared-parser precedent (`byte_lines` imported from `genericlog`) — lines 39, 45-46:

```python
# src/sift/adapters/eustack.py:39
from sift.adapters.genericlog import byte_lines
```
```python
# src/sift/adapters/eustack.py:45-46
# The byte-line splitter (with its own MAX_EVENT_BYTES force-split) is shared from genericlog
# (IN-01) to avoid a drifting verbatim copy.
```

`_condense_symbol` (lines 69-73):
```python
def _condense_symbol(frame_body: str) -> str:
    """The bare symbol name for the condensed message — drop any
    ``- <lib> <source>:<line>`` suffix so the message stays signal, not noise.
    """
    return frame_body.split(" - ", 1)[0].strip()
```

`parse()`'s frame-scanning inner logic that `iter_frames()` must not disturb (lines 226-230,
inside the `for bline in byte_lines(...)` loop):
```python
if current.is_thread and len(current.frames) < CONDENSED_FRAMES:
    frame_match = _FRAME_RE.match(text)
    if frame_match is not None:
        symbol: str = _condense_symbol(frame_match.group(3))
        current.frames.append(symbol)
```

**Where `iter_frames()` slots in:** as a free function near `_condense_symbol`, operating on a
full `raw` string (post-parse, not the streaming line loop `parse()` uses) — RESEARCH.md's exact
proposed body:

```python
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

This is purely additive — `parse()`'s body (lines 133-258, `_Record`/`ParseStats` shapes) needs
zero edits. `pipeline/eustack.py` imports `iter_frames` from `sift.adapters.eustack`, exactly the
`byte_lines`-from-`genericlog` precedent one file over.

---

### `tests/test_eustack_rules.py` (new test file)

**Analogs:** `tests/test_config.py` (error-path/loader test shape) + `tests/test_eustack.py`
(fixture-loading convention).

**Error-path test shape** — verified present at `tests/test_config.py:79` and `:92`
(`test_unknown_config_key_is_a_loud_error_naming_the_key`, `test_malformed_toml_is_a_loud_error`).
Read these two tests directly before writing the rules-loader equivalents
(`test_unnormalised_pattern_rejected_at_load`, a duplicate-rule-rejection test, an
unknown-key-in-`[[rule]]`-table test) so the assertion style (message content, exception type)
matches house convention exactly.

**Fixture-loading convention** — `tests/test_eustack.py:23`:
```python
FIXTURES = Path(__file__).parent / "fixtures" / "eustack"
```
Reuse this constant/pattern for the new `reference_capture_derivative.txt` fixture path in
`test_eustack_rules.py`.

**No enumerating test of the full `SiftConfig` field set exists** — verified by grep: no
`model_fields` / `set(SiftConfig...)` assertion appears anywhere in `tests/test_config.py`. This
confirms RESEARCH.md's claim: adding `EustackConfig`/`eustack` to `SiftConfig` is **purely
additive** to the test suite — no existing test needs to change, only new tests need to be added.
**Concrete breakage risk: none identified** on this axis.

---

### `tests/test_eustack.py` (additive `iter_frames()` cases)

**Analog:** the file's own existing test structure, verified by listing all `def test_*`
functions (lines 69-224): each test builds a small in-memory or `tmp_path`-written fixture,
constructs `EustackAdapter()`, calls `.sniff()`/`.parse()`, and asserts on the yielded `Event`
list. New `iter_frames()` tests should follow the same house style: call `iter_frames(raw_string)`
directly (no adapter instance needed — it is a pure function over `str`), assert on the yielded
`(index, symbol)` tuples. Two cases RESEARCH.md names explicitly and should be added:
`test_iter_frames_yields_index_and_full_symbol`,
`test_iter_frames_on_capped_raw_yields_fewer_frames` (exercising the `MAX_EVENT_LINES`-truncated
case). Existing fixture at `tests/fixtures/eustack/threaddump.txt` (13,410 bytes — the current
largest committed fixture) is reusable as input.

---

### `tests/test_config.py` (additive `EustackConfig` cases)

**Analog:** the file's own `mcm`/`embeddings` section tests, verified present:
`test_unknown_config_key_is_a_loud_error_naming_the_key` (line 79),
`test_malformed_toml_is_a_loud_error` (line 92), plus (per RESEARCH.md, not independently
re-verified by line number here — read the file directly when writing these) a defaults test
mirroring `test_mcm_thresholds_defaults`, a round-trip test mirroring
`test_embeddings_section_round_trips_from_toml`, and a precedence test mirroring the embeddings
`base_url` precedence test around `test_config.py:118-129`. Four new tests to add:
`test_eustack_rules_path_defaults_to_none`, `test_eustack_rules_path_round_trips_from_toml`,
`test_env_beats_toml_for_eustack_rules_path_but_flag_wins`,
`test_unknown_key_under_eustack_is_a_loud_error`.

## Shared Patterns

### `extra="forbid"` on every Pydantic model
**Source:** every model in `src/sift/config.py` (`ThresholdPair` line 88, `McmThresholdsConfig`
line 106, `McmConfig` line 119, `SiftConfig` line 126) and every model in `mcm.py`/`perfmon.py`.
**Apply to:** `Rule`, `RulesMeta`, `ThreadRoleRules`, `EustackConfig` — no exceptions, per house
discipline "fail at load, not at use."

### `importlib.resources.files(<package>).joinpath(<file>).read_text(encoding="utf-8")`
**Source:** `mcm_facts.py:70-80`, `perfmon_facts.py:101`, `cluster.py:210`.
**Apply to:** `pipeline/eustack.py`'s `load_rules()` default-path branch. Always three chained
calls, always explicit `encoding="utf-8"`, package constant always a private module-level string.

### Malformed-TOML error surfacing
**Source:** `config.py:186-192` — `tomllib.TOMLDecodeError` caught and re-raised as `ValueError`
naming the source file, comment citing the "never fall back to defaults silently" invariant.
**Apply to:** `load_rules()` — same catch/re-raise shape, substituting the package/file source
description.

### "Shared, not copied" parser reuse
**Source:** `eustack.py:39,45-46` — `byte_lines` imported from `genericlog` with an explicit
comment naming drift risk.
**Apply to:** `pipeline/eustack.py` importing `iter_frames` from `sift.adapters.eustack` — add the
equivalent comment.

### Content-hash idiom
**Source:** `sha256(text)[:16]` pattern used for `event_id`/`template_id`/
`cluster_label_prompt_hash` (see `pipeline/cluster.py`).
**Apply to:** `load_rules()`'s returned content hash (D-11) — `hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]`.

## No Analog Found

None — every file in the D-16 file set has a strong, verified analog in the existing codebase.

## Metadata

**Analog search scope:** `src/sift/config.py`, `src/sift/pipeline/{mcm,perfmon,mcm_facts,perfmon_facts,cluster}.py`,
`src/sift/adapters/eustack.py`, `src/sift/prompts/__init__.py`, `tests/{test_config,test_eustack,test_packaging}.py`
**Files scanned:** 9 read in full or targeted range, all corroborating RESEARCH.md's own citations
**Pattern extraction date:** 2026-07-25
**Corrections to RESEARCH.md:** one line-range correction (`McmThresholdsConfig`/`McmConfig` span
is `94-121` covering two separate classes at `94-113`/`116-121`, not one contiguous block — use
the pattern-mapping context's `85-130` outer bound, which is correct and covers `ThresholdPair`
through `SiftConfig`). All other cited line numbers (`_FRAME_RE` 57, `CONDENSED_FRAMES` 51,
`MAX_EVENT_LINES` 47, `_condense_symbol` 69-73, `_ENV_SCALARS` 154-166, `load_config` 181-213,
`mcm_facts.py` loader 70-80, `test_config.py` error tests at lines 79/92) verified exact, zero
drift.
