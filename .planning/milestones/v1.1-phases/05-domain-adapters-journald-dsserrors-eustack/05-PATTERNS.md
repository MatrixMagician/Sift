# Phase 5: Domain Adapters (journald, dsserrors, eustack) - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 11 (4 new adapter/base modules, 2 modified core, 5 new/extended tests + fixtures + ADR)
**Analogs found:** 11 / 11 (every new file has a strong in-repo analog — this is a "clone the reference adapter" phase, not greenfield)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/adapters/journald.py` (new) | adapter | transform (JSONL → Event) | `src/sift/adapters/genericlog.py` | role-exact, data-flow-subset |
| `src/sift/adapters/dsserrors.py` (new) | adapter | transform (multi-line grouped → Event) | `src/sift/adapters/genericlog.py` | exact (both do timestamp ladder + multi-line grouping + caps) |
| `src/sift/adapters/eustack.py` (new) | adapter | transform (per-thread grouped → Event) | `src/sift/adapters/genericlog.py` | role-exact, grouping-analogue |
| `src/sift/adapters/base.py` (modified — add `ConfigurableAdapter`, promote `to_utc`/`tz_override_for`) | base/protocol | — | `genericlog.GenericLogAdapter.__init__` + `genericlog.to_utc` | exact (moving existing code up) |
| `src/sift/adapters/__init__.py` (modified — 3 registry lines) | registry | dispatch | itself (existing `REGISTRY` dict) | exact |
| `src/sift/cli.py` (modified — broaden 3 isinstance sites) | controller/orchestrator | request-response (per-file ingest loop) | itself (`GenericLogAdapter` guards at 269/277/345) | exact (generalise in place) |
| `tests/test_journald.py` (new) | test | — | `tests/test_genericlog.py` | exact (same helper layout) |
| `tests/test_dsserrors.py` (new) | test | — | `tests/test_genericlog.py` | exact |
| `tests/test_eustack.py` (new) | test | — | `tests/test_genericlog.py` | exact |
| `tests/test_adapters_detect.py` (extend) | test | — | itself | exact |
| `tests/test_cli.py` (extend) | test (integration/CliRunner) | — | itself | exact |
| `tests/fixtures/{journald,dsserrors,eustack}/` (new) | fixture | — | inline `write_log` helpers in `test_genericlog.py` | pattern-match |
| `docs/decisions/0005-*.md` (new) | ADR | — | existing `docs/decisions/` ADRs (0001–0004) | pattern-match |

**Note on `models.py` and `pipeline/dedup.py`:** neither is modified. `models.py` is the frozen `Event` contract the new adapters *populate*; `dedup.py` is checked (Open Question 3) but only extended if SID/OID template variants fail to collapse. Both are reference-only inputs, mapped below under Shared Patterns.

## Pattern Assignments

### `src/sift/adapters/journald.py` (adapter, JSONL→Event)

**Analog:** `src/sift/adapters/genericlog.py` — journald is the *simplest subset*: one event per line, no continuation grouping, no encoding ladder (UTF-8 only), authoritative timestamp.

**Imports pattern** (mirror `genericlog.py:19-29`, drop the timestamp-ladder machinery, add `json`):
```python
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sift.adapters.base import ConfigurableAdapter, ParseStats, open_bytes, read_head
from sift.models import Event, event_id
```

**Class + config pattern** — subclass the NEW `ConfigurableAdapter` (do NOT re-declare `input_root`/`tz_overrides`/`last_stats`; inherit them). Contrast with the current standalone init at `genericlog.py:294-302`:
```python
class GenericLogAdapter:            # genericlog.py:294 — CURRENT, standalone
    name = "genericlog"
    def __init__(self) -> None:
        self.input_root: Path | None = None
        self.tz_overrides: dict[str, str] = {}
        self.last_stats: ParseStats | None = None
```
After Pattern 1, journald/dsserrors/eustack become `class JournaldAdapter(ConfigurableAdapter): name = "journald"` and inherit those three attributes.

**Sniff pattern** (analog `genericlog.py:304-316`) — decode `read_head`, take first non-blank line, `json.loads`, check for signature keys (`__REALTIME_TIMESTAMP`/`__CURSOR`/`_BOOT_ID`) → `0.95`, else `0.0`. Highly discriminative (genericlog deliberately returns the low `0.1` at line 313 so a domain adapter always wins).

**Byte-line / offset discipline** — reuse the exact idiom from `genericlog.parse` `open_bytes` + byte-level split (`genericlog.py:367-374`): split on `b"\n"`, `offset += len(bline)`, `event_id(relpath, line_offset)`. journald is UTF-8 so the simple `b"\n"` split suffices — no UTF-16 `unit` alignment needed (`_byte_lines` at `genericlog.py:230-276` is the reference; journald can use a plain split, not the full helper).

**Severity map** (RESEARCH Code Example 1) — mirror the exhaustive dict + safe default shape of `genericlog.py:75-102` (`_SEVERITY_MAP` + `_severity` never fabricating):
```python
_PRIORITY_SEVERITY = {0:"fatal",1:"fatal",2:"fatal",3:"error",4:"warn",5:"info",6:"info",7:"debug"}
def _severity(priority: object) -> str:
    try: return _PRIORITY_SEVERITY.get(int(priority), "unknown")
    except (TypeError, ValueError): return "unknown"
```

**Field normaliser (Pitfall 1, journald-specific — no analog, genuinely new)** — string / null / int-array / value-array; see RESEARCH Pattern 3 `_field_to_str`. This is the one piece with no codebase precedent.

**Stats / coverage pattern** (analog `genericlog.py:331, 339-342, 433, 451`) — build `ParseStats(path=relpath)`, increment `event_count`, add unparseable bytes to `unknown_fallback_bytes`, set `stats.total_bytes = offset`, assign `self.last_stats = stats` at the end. Verbatim discipline.

---

### `src/sift/adapters/dsserrors.py` (adapter, multi-line grouped→Event)

**Analog:** `src/sift/adapters/genericlog.py` — this is the *closest structural clone*: it needs the timestamp-parse + `to_utc`/tz-override path AND the multi-line grouping-with-caps loop.

**Timestamp + tz-override** — reuse the PROMOTED `base.to_utc` (currently `genericlog.py:91-96`) and the tz-glob lookup currently inlined at `genericlog.py:322-329`:
```python
override_glob, override_tz = next(
    ((glob, tz) for glob, tz in self.tz_overrides.items() if fnmatch(relpath, glob)),
    (None, None),
)
```
RESEARCH Code Example 3 promotes this to `base.tz_override_for(relpath, tz_overrides)`.

**Multi-line grouping + safety caps** — clone the `_Record` accumulator (`genericlog.py:279-291`) and the "new record-start closes the current, else append with cap check" loop (`genericlog.py:383-430`). The MCM `***** Start/End of Info Dump *****` sentinels replace the timestamp-line record-start trigger; the caps are identical:
```python
MAX_EVENT_LINES = 256          # genericlog.py:38
MAX_EVENT_BYTES = 65536        # genericlog.py:39
# genericlog.py:404-416 — cap breach closes into a severity="unknown" continuation:
if lines_in_event >= MAX_EVENT_LINES or current.byte_len + len(bline) > MAX_EVENT_BYTES:
    yield finish(current)
    current = _Record(offset=line_offset, line_start=line_no, ts=None,
                      ts_confidence="missing", severity="unknown")
```
Reuse this VERBATIM (Pitfall 5 — truncated MCM block cannot slurp unbounded memory).

**Token extraction (dsserrors-specific, RESEARCH Code Example 2)** — anchored linear-scan regexes in the style of `genericlog.py:47-74` (`_ISO_RE`/`_SEVERITY_RE`): `_SRCLOC = [([A-Za-z]\w*)\.cpp:(\d+)]`, `_ERRCODE`, `_OID` (GUID), `_MCM_START`/`_MCM_END`. SID pattern `[ASSUMED]` — pin to user-confirmed fixture.

**Node attribution** — depends on `self.input_root` (inherited from `ConfigurableAdapter`); compute `relpath` exactly as `genericlog.py:319-321`, then `attrs["node"] = Path(relpath).parts[0]`.

**Event construction** — mirror the `finish()` builder at `genericlog.py:339-365`; populate `session` (SID), `thread`, `component` (`.cpp` name or `"MCM"`), `attrs["error_code"]/["oid"]/["node"]/["byte_offset"]/["byte_len"]`.

---

### `src/sift/adapters/eustack.py` (adapter, per-thread grouped→Event)

**Analog:** `src/sift/adapters/genericlog.py` — same grouping skeleton as dsserrors; the record-start trigger is a `TID <n>:` header (or JVM `"name" #id` header — Open Question 1, confirm fixture) instead of a timestamp line.

**Grouping loop** — identical structure to `genericlog.py:383-430`: a header line closes the current thread event and opens a new one; frame lines (`#N 0xADDR symbol`) accrue; same 256-line/64 KB caps (Pitfall 5). `message` = condensed top frames, `raw` = verbatim block (reuse `raw_parts` accumulation at `genericlog.py:291, 430`).

**Timestamp** — usually one dump-time header ts (not per-thread); parse via promoted `base.to_utc`, stamp all threads; absent → `ts=None`, `ts_confidence="missing"` (never fabricate — same rule as `genericlog._severity`/ts).

**Regexes** (RESEARCH Code Example 4) — `_TID`, `_JVM_HEADER`, `_LOCK`, anchored linear-scan per `genericlog.py:47-74` discipline.

---

### `src/sift/adapters/base.py` (add `ConfigurableAdapter`, promote `to_utc` + `tz_override_for`)

**Analog:** the code being promoted already exists — `genericlog.to_utc` (`genericlog.py:91-96`) and the per-instance config attrs (`genericlog.py:299-302`).

**Existing seam to extend** (`base.py:35-50` `ParseStats`, `base.py:53-64` `open_bytes`, `base.py:67-70` `read_head` — all reused unchanged). Add alongside:
```python
@dataclass  # RESEARCH Pattern 1 — carries per-run state OUTSIDE the frozen Adapter Protocol (base.py:25-32)
class ConfigurableAdapter:
    def __init__(self) -> None:
        self.input_root: Path | None = None
        self.tz_overrides: dict[str, str] = {}
        self.last_stats: ParseStats | None = None

# moved verbatim from genericlog.py:91-96; genericlog imports it back
def to_utc(dt: datetime, override_tz: str | None) -> tuple[datetime, str]: ...
def tz_override_for(relpath: str, tz_overrides: dict[str, str]) -> str | None: ...
```
**Boundary:** the frozen `Adapter` Protocol at `base.py:25-32` is UNCHANGED — `ConfigurableAdapter` is a separate concrete base so `isinstance` narrowing type-checks under pyright strict.

---

### `src/sift/adapters/__init__.py` (registry — 3 lines)

**Analog:** the file itself. `REGISTRY` at `__init__.py:15-17` currently holds one entry:
```python
REGISTRY: dict[str, Adapter] = {
    "genericlog": GenericLogAdapter(),
}
```
Add imports + three entries (`journald`, `dsserrors`, `eustack`). `detect()` (`__init__.py:54-85`) needs ZERO changes — it iterates `REGISTRY.values()` and applies the `SNIFF_THRESHOLD = 0.5` / unique-max / genericlog-fallback rule generically. This is the SPEC §5.2 "new module + registration only" invariant, and it already holds for the registry side.

---

### `src/sift/cli.py` (broaden 3 isinstance sites — Pattern 1, HIGHEST STAKES)

**Analog:** the file itself. Three sites currently key on `GenericLogAdapter` (import at `cli.py:31`):

**Site 1 — config delivery** (`cli.py:269-271`):
```python
if isinstance(file_adapter, GenericLogAdapter):        # → ConfigurableAdapter
    file_adapter.input_root = input_dir
    file_adapter.tz_overrides = dict(config.timezones)
```

**Site 2 — offset progress gate** (`cli.py:277-279`) — RESEARCH says leave keyed to genericlog OR generalise via the shared `attrs["byte_offset"]/["byte_len"]` convention (new adapters expose it too); progress-bar accuracy is NOT a success criterion:
```python
track_offsets = isinstance(file_adapter, GenericLogAdapter) and path.suffix not in (".gz", ".zst")
```

**Site 3 — coverage read-back** (`cli.py:345-360`) — the load-bearing fix (Pitfall 2). Currently `stats=None → cov=1.0` for any non-genericlog adapter, fabricating 100% coverage:
```python
stats = file_adapter.last_stats if isinstance(file_adapter, GenericLogAdapter) else None  # → ConfigurableAdapter
cov = stats.coverage if stats else 1.0            # 1.0 default is the silent-failure bug
event_count = stats.event_count if stats else parsed_count
```
Change both `isinstance(..., GenericLogAdapter)` guards (sites 1 and 3) to `isinstance(..., ConfigurableAdapter)`. After this, adapter #6 needs zero cli.py changes.

---

### `tests/test_journald.py` / `test_dsserrors.py` / `test_eustack.py` (new)

**Analog:** `tests/test_genericlog.py` (lines 1-60 read). Copy its harness:
- `write_log(root, relname, data: bytes)` helper (`test_genericlog.py:24-29`) — writes fixture bytes, creates parents.
- `run_parse(root, relname, tz_overrides=None) -> tuple[list[Event], ParseStats]` (`test_genericlog.py:32-45`) — fresh adapter, set `input_root`, assert `last_stats is not None`, return both.
- `assert_span_partition(events, total_bytes)` (`test_genericlog.py:53+`) — the every-byte-attributed invariant (`byte_offset` contiguous from 0, non-overlapping, summing to total). REUSE for all three new adapters — it is the mechanical coverage check.
- `set_mtime` (`test_genericlog.py:47-50`) if timestamp-year inference is exercised.
- Fixtures built inline via `write_log` / handcrafted bytes (journald), or read from `tests/fixtures/{dsserrors,eustack}/` for the user-confirmed samples. `conftest.py` autouse `_isolate_dirs` + `_no_network` apply automatically.

### `tests/test_adapters_detect.py` (extend)

**Analog:** the file itself (lines 1-50 read) — `DummyAdapter` + `registry` fixture (saves/restores `REGISTRY`). Add phase-5 cases: each fixture sniffs to its own adapter and beats genericlog's `0.1`; no cross-collision.

## Shared Patterns

### ConfigurableAdapter (per-run config delivery + coverage read-back)
**Source:** promoted from `genericlog.py:299-302` into `base.py`; consumed at `cli.py:269-271` and `cli.py:345-360`.
**Apply to:** all three new adapters (subclass it) + `GenericLogAdapter` (retrofit to subclass, drop its own `__init__` body).
**Why load-bearing:** without it, new adapters get no `input_root` (Pitfall 3, node-tagging dead), no `tz_overrides` (criterion 4 dead), and fabricate 100% coverage (Pitfall 2). ADR 0005.

### UTC normalisation + tz-override (criterion 4)
**Source:** `genericlog.to_utc` `genericlog.py:91-96` (promote to `base.to_utc`); tz-glob lookup `genericlog.py:322-329` (promote to `base.tz_override_for`).
**Apply to:** dsserrors (naive multi-node timestamps) and eustack header ts.
```python
def to_utc(dt: datetime, override_tz: str | None) -> tuple[datetime, str]:
    if dt.tzinfo is not None:
        return dt.astimezone(UTC), "exact"
    tz = ZoneInfo(override_tz) if override_tz else UTC
    return dt.replace(tzinfo=tz).astimezone(UTC), "inferred"
```

### Byte-offset determinism (event_id idempotency)
**Source:** `genericlog._byte_lines` (`genericlog.py:230-276`) + offset accounting (`genericlog.py:372-374`); identity `models.event_id` (`models.py:38-47`).
**Apply to:** all three — split at byte level on `b"\n"`, `offset += len(bline)`, `event_id(relpath, line_offset)`. journald/eustack are UTF-8: plain split, no UTF-16 `unit` alignment (Pitfall 6).

### Multi-line grouping with safety caps
**Source:** `_Record` (`genericlog.py:279-291`) + cap-breach close (`genericlog.py:404-416`); constants `MAX_EVENT_LINES`/`MAX_EVENT_BYTES` (`genericlog.py:38-39`).
**Apply to:** dsserrors (MCM blocks) and eustack (thread blocks) — Pitfall 5.

### Coverage / ParseStats accounting
**Source:** `base.ParseStats` (`base.py:35-50`, `.coverage` property `base.py:45-50`); usage in `genericlog.finish`/parse (`genericlog.py:331, 339-342, 433, 451`).
**Apply to:** all three — set `self.last_stats` at parse end; cli.py reads `.coverage`.

### Severity → 6-value CHECK safety
**Source:** `genericlog._SEVERITY_MAP` + `_severity` (`genericlog.py:75-102`); DB constraint `store.py:150`.
**Apply to:** all three — exhaustive map, default `"unknown"`; out-of-set value rolls the whole file back (Pitfall 4).

### Event construction (the frozen target)
**Source:** `models.Event` (`models.py:17-35`); builder `genericlog.finish` (`genericlog.py:339-365`).
**Apply to:** all three — populate `session`/`thread`/`component`/`attrs` per adapter; keep `attrs["byte_offset"]/["byte_len"]` for span-partition tests.

### Dedup masking (verify, do not rebuild — Open Question 3)
**Source:** `pipeline/dedup._MASK` (dedup.py:27-40, `MASK_VERSION = 2`) — already masks `0x` codes, GUIDs (`<UUID>`), 32-hex SIDs (`<HEX>`), numbers, paths, timestamps.
**Apply to:** dsserrors — likely covers SID/OID variants already. If groups fragment, extend `_MASK` and bump `MASK_VERSION` (no migration). Do NOT pre-emptively add masks (YAGNI).

## No Analog Found

Genuinely new code with no in-repo precedent (planner uses RESEARCH.md patterns directly):

| Code | File | Reason |
|------|------|--------|
| `_field_to_str` journald value normaliser (string/null/int-array/value-array) | `journald.py` | No JSON-field-type-coercion precedent; RESEARCH Pattern 3 is the spec. Pitfall 1. |
| MCM `***** Start/End of Info Dump *****` block sentinels | `dsserrors.py` | Domain-specific delimiter; no existing sentinel-grouped adapter. Grouping *skeleton* is genericlog's, but the trigger is new. |
| `TID <n>:` / JVM header per-thread grouping + `_LOCK` extraction | `eustack.py` | No thread-dump adapter exists. Open Question 1 (eu-stack vs JVM) gates the regex shape — needs user-confirmed fixture before freezing. |

## Metadata

**Analog search scope:** `src/sift/adapters/` (genericlog, base, __init__), `src/sift/cli.py` (ingest loop 255-364), `src/sift/models.py`, `src/sift/pipeline/dedup.py`, `tests/` (test_genericlog, test_adapters_detect).
**Files scanned:** 8 source + 2 test.
**Pattern extraction date:** 2026-07-17
</content>
</invoke>
