# Phase 5: Domain Adapters (journald, dsserrors, eustack) - Research

**Researched:** 2026-07-17
**Domain:** Deterministic parsing of three production diagnostic formats (systemd journal JSON export, MicroStrategy DSSErrors.log, MicroStrategy/native EU-stack thread dumps) into the frozen canonical `Event` — reusing the Phase-1 adapter infrastructure
**Confidence:** HIGH for journald (format verified against systemd.io this session) and for the reuse/architecture strategy (code read this session); MEDIUM-LOW for the exact byte layout of dsserrors and eustack (proprietary MicroStrategy formats — reliable *tokens* known, exact line shape needs a user-confirmed sanitised fixture)

<locked_constraints>
## Locked Constraints (authoritative — no CONTEXT.md; SPEC.md §5.3 is the frozen contract)

No `/gsd-discuss-phase` was run for this phase by design: the per-adapter contracts are frozen in SPEC.md §5.2–§5.3, and the roadmap success criteria are the acceptance bar. Treat the following as locked decisions the planner must honour verbatim.

### Frozen per-adapter contracts (SPEC.md §5.2 build-order items 2–4)

- **journald** — consumes `journalctl -o json` export files (one JSON object per line). Maps `PRIORITY`→severity, `_SYSTEMD_UNIT`→component, `_PID`/`_COMM`→attrs. **Does NOT shell out to `journalctl`** in v1; reads exported files only.
- **dsserrors** — MicroStrategy `DSSErrors.log` and rotated `.bak00`/`.bak01` siblings. Extracts timestamp, thread ID, severity, component/module, message; recognises multi-line Memory Contract Manager (MCM) blocks as one event; `0x`-prefixed error codes → `attrs["error_code"]`; SIDs → `session`; OIDs → `attrs["oid"]`; multi-node cases (same filename under different node subdirectories) → `attrs["node"]` from the directory name.
- **eustack** — MicroStrategy EU-stack / thread-dump files. One event per thread, `message` = condensed top frames, full stack in `raw`, thread name/ID in `thread`, blocked-on / lock info into attrs where present.

### Frozen invariants inherited from Phases 1–4 (CLAUDE.md + SPEC.md §5.1)

- Adapter modules are self-contained: **adding an adapter must require zero changes outside a new module + its registration** (SPEC §5.2). *(See Architecture Pattern 1 — this invariant is currently partially violated by a Phase-1 shortcut that this phase must pay down.)*
- The `Event` dataclass and `Adapter` Protocol are **FROZEN** — no field or signature changes. Per-run config travels on the adapter *instance* (as `input_root`, `tz_overrides`, `last_stats`), never on the Protocol.
- `event_id = sha256(source_file + "\x00" + str(byte_offset))[:16]` on the **decompressed** byte stream; idempotent re-ingest.
- Nothing disappears silently: unparseable regions → `severity="unknown"`, `ts_confidence="missing"` events; every decompressed byte belongs to exactly one event; per-file parse-coverage metric emitted.
- Multi-line records (MCM blocks, thread frames) are **one** event.
- Timestamps normalise to aware UTC with `ts_confidence` ∈ {`exact`,`inferred`,`missing`}; per-glob timezone override supported; causality must never silently invert.
- `severity` MUST be one of `fatal|error|warn|info|debug|unknown` — the `events` table has a `CHECK` constraint (store.py:150). An out-of-set value makes the whole-file `INSERT` fail and rolls the file back to zero rows. Mappings must be exhaustive.
- Zero network egress; tests never touch the network (autouse socket guard in `tests/conftest.py`); British English; type hints everywhere; `ruff` + `pyright` + `pytest` clean is "done".
</locked_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **INGST-07** | journald adapter parses `journalctl -o json` export files, mapping `PRIORITY`→severity, `_SYSTEMD_UNIT`→component, `_PID`/`_COMM`→attrs | Verified JSON field-type rules (Pattern 3 + Pitfall 1); PRIORITY→severity map (Code Example 1); byte-line offset accounting reused from genericlog |
| **INGST-08** | dsserrors adapter parses `DSSErrors.log` + rotated `.bak` siblings — timestamp, thread, severity, component, multi-line MCM blocks, `0x` error codes, SIDs, OIDs, multi-node tags from directory names | MCM block delimiters (Pattern 4, ISPerfDiag domain refs); token-anchored field extraction (Code Example 2); node-from-directory needs `input_root` (Pattern 1); content-ordered timeline via per-event ts (Pattern 5) |
| **INGST-09** | eustack adapter parses EU-stack/thread-dump files — one event per thread, condensed top frames, full stack in `raw`, lock info in attrs | Per-thread grouping on `TID`/thread-header delimiters (Pattern 6, eu-stack format verified); lock-info extraction "where present" |

Roadmap success criterion 4 (mixed-timezone multi-node UTC timeline, causality never inverted) is cross-cutting across dsserrors and the shared `to_utc`/`tz_overrides` mechanism — see Pattern 5 and Validation Architecture.
</phase_requirements>

## Summary

This phase adds three *leaf* adapters on top of infrastructure that already exists and is proven: the frozen `Event`/`Adapter` contracts, the `base.open_bytes`/`read_head`/`ParseStats` helpers, the `genericlog.to_utc` UTC-normalisation + `tz_overrides` mechanism, the sniff-dispatch registry, and the streaming byte-offset discipline. None of the three needs a new dependency — everything is stdlib (`json`, `re`, `datetime`, `zoneinfo`). The work is almost entirely *format knowledge* plus disciplined byte accounting, not new architecture.

The single most important planning finding is **not** in any of the three formats: it is a Phase-1 shortcut in `cli.py`. The ingest orchestrator configures adapters and reads their coverage stats behind `isinstance(file_adapter, GenericLogAdapter)` guards (cli.py:269, 277, 345–347). As written, the three new adapters would **never receive `input_root`/`tz_overrides`** (breaking dsserrors node-tagging and multi-node timezone handling) and their `last_stats` would **never be read** — `sift ingest` would falsely report **100% coverage** for every dsserrors/eustack/journald file regardless of unparseable regions, silently violating "nothing disappears". The phase must generalise this coupling **once** into a shared `ConfigurableAdapter` base class, after which the SPEC §5.2 "zero changes to add an adapter" invariant finally holds for real. This is the highest-stakes task in the phase and gates the ≥95%-coverage success criteria at the end-to-end level.

Format-wise: **journald is easy and fully verified** — JSONL, one self-contained object per line, no multi-line grouping, an authoritative UTC timestamp (`__REALTIME_TIMESTAMP`, µs since epoch), and one real gotcha (any field, including `MESSAGE`, can be a JSON string, `null`, an **array of byte-integers 0–255** for binary content, or an **array of values** for repeated fields — verified against systemd.io this session). **dsserrors and eustack are proprietary MicroStrategy formats**: the reliable structural *tokens* are known (dsserrors `[ClassName.cpp:NNNN]` source-location tags, MCM `***** Start/End of Info Dump *****` block sentinels, `0x` codes, GUID-shaped OIDs; eustack `TID <n>:` headers with `#N 0xADDR symbol` frames), but the exact per-line field layout varies by MicroStrategy version and must be pinned by a **user-confirmed sanitised fixture** — the user is the domain authority here and should provide or verify a representative sample before the parser regexes are frozen.

**Primary recommendation:** Sequence the phase as (Wave 0) generalise the `ConfigurableAdapter` coupling + promote `to_utc`/tz-lookup into `base.py` + author the fixtures (journald handcrafted JSONL; dsserrors + eustack from a user-confirmed sample); then (Wave 1, parallel-safe — three disjoint new modules) build journald first (cheapest, fully specified), dsserrors and eustack alongside. Each adapter is a vertical slice: `sniff → parse → Event → store → sift show`. Reuse `base.ParseStats` and the every-byte-attributed coverage invariant verbatim; do not re-implement UTC normalisation, decompression, or byte-line splitting.

## Architectural Responsibility Map

Sift is a single-process local CLI; "tiers" are module layers, not network tiers.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Format detection for the 3 new formats (`sniff`) | each new `adapters/*.py` | `adapters/__init__.py` (registration) | Self-contained per SPEC §5.2; registry gains 3 lines |
| Parsing → `Event` iterator, byte-offset tracking, per-file `ParseStats` | each new `adapters/*.py` | `base.py` (shared helpers) | Only code that reads raw artefacts; zero knowledge of store/CLI |
| Per-run config delivery (`input_root`, `tz_overrides`) + coverage read-back | `base.ConfigurableAdapter` + `cli.py` ingest loop | all adapters subclass it | **New** — generalises the Phase-1 `isinstance(GenericLogAdapter)` shortcut so config/coverage flow to every adapter |
| UTC normalisation + tz-override glob lookup | `base.py` (promoted from `genericlog`) | adapters call it | Shared by genericlog + dsserrors (+ optionally eustack header ts); one code path for criterion 4 |
| Node attribution (multi-node dsserrors) | `dsserrors.py` (reads `self.input_root`) | `cli.py` sets `input_root` | Node = directory component of the case-relative path |
| Timeline ordering across rotated `.bak` siblings | **downstream** (store ts-sorted query) | dsserrors (correct per-event ts) | Per-file `parse()` signature forbids cross-file stitching; ts drives order (Pattern 5) |
| Persistence / idempotency / coverage meta | `store.py` + `cli.py` | — | Unchanged; new adapters flow through the existing `insert_events` path |

## Project Constraints (from CLAUDE.md)

The planner MUST honour these repo directives (same authority as locked decisions):

- **SPEC.md is authoritative** — read §5.1, §5.2, §5.3 before implementing; the adapter contracts are frozen there.
- **Boring technology only** — this phase needs **no new dependency**; `json`, `re`, `datetime`, `zoneinfo` are stdlib. Adding anything else requires justification and almost certainly indicates a wrong turn.
- **Commands / gate:** `uv run pytest`, `uv run ruff check`, `uv run pyright` all clean = "done"; do not start M6 while M5 is red.
- **Adding an adapter = new module + registration only** — honour this for adapters #6+; pay down the existing genericlog coupling this phase (Pattern 1).
- **Nothing disappears silently** — `severity="unknown"` events for unparseable regions; per-file coverage metric must be *real* (not the falsely-1.0 default the current cli.py would emit — see Pitfall 2).
- **Determinism** — `event_id` on decompressed byte offsets; idempotent re-ingest; identical inputs → identical events.
- **British English** in docs and user-facing strings ("normalise", "artefact", "behaviour").
- **Type hints everywhere;** pyright strict is part of the gate (watch `reportUnknownVariableType` on nested JSON-shaped literals — annotate `x: dict[str, object] = {...}`).
- **Zero network egress; never call the network in tests** — journald fixtures are handcrafted JSONL, NOT captured via `journalctl` at test time.
- **TDD:** RED→GREEN→gate→commit per task is the established project cadence.
- **New locked decisions get an ADR** in `docs/decisions/` (next number 0005) citing the SPEC section resolved — the `ConfigurableAdapter` generalisation and the "rotated-siblings ordered by ts, not filename / no cross-file stitching" decision both warrant one.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stdlib `json` | 3.12+ | Parse `journalctl -o json` JSONL entries | One object per line; `json.loads` per line, safe (no eval), stdlib [VERIFIED: journald format, systemd.io this session] |
| stdlib `re` | 3.12+ | dsserrors token extraction (`[*.cpp:NNNN]`, `0x…`, GUID OIDs, SID); eustack thread/frame delimiters | Anchored, linear-scan regexes only (no ReDoS), mirroring the genericlog/dedup discipline |
| stdlib `datetime` + `zoneinfo` | 3.12+ | UTC normalisation, µs-epoch conversion, per-node tz override | Reuse `to_utc`; `datetime.fromtimestamp(usec/1e6, tz=UTC)` for journald; `fromisoformat` for dsserrors offset timestamps [VERIFIED in Phase 1] |
| `sift.adapters.base` | in-repo | `open_bytes`, `read_head`, `ParseStats`, `SNIFF_BYTES`, (promoted) `to_utc` + tz-lookup, `ConfigurableAdapter` | Existing shared seam; adapters stay self-contained by calling it |

### Supporting (dev/test only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | (installed) | Adapter unit tests + e2e ingest slice per format | All tests; existing conftest isolation + socket guard apply |
| ruff / pyright | (installed) | Lint + strict types | Quality gate |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `json` per line | `orjson`/`ujson` | No — new dependency for zero benefit at fixture scale; violates boring-tech; `json` is fine for JSONL |
| Reuse `genericlog.to_utc` by importing from the sibling module | Promote `to_utc` (+ tz-lookup) into `base.py` | **Promote.** dsserrors importing from `genericlog` couples two leaf adapters; `base.py` is the correct shared home (one-line move, both call it) |
| Shell out to `journalctl -o json` at parse time | Read exported `.json` files only | SPEC §5.2 forbids shelling out in v1; also violates zero-network-in-tests determinism |
| New per-adapter config plumbing | Shared `ConfigurableAdapter` base class | Base class — collapses 4 `isinstance` sites in cli.py to 1 concept; enables SPEC §5.2 invariant (Pattern 1) |

**Installation:** none — no `uv add` this phase. If the planner writes an install task, it is a mistake.

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.** All parsing is stdlib (`json`, `re`, `datetime`, `zoneinfo`) plus in-repo `sift.adapters.base`. No registry lookup, no `SLOP`/`SUS`/`OK` verdicts to record. If any plan proposes `pip`/`uv add`-ing a log-parsing, journald, or thread-dump library, treat it as a red flag: it contradicts the boring-tech constraint and the "hand-rolled, auditable, deterministic" project philosophy, and would need a `checkpoint:human-verify` + ADR justifying the exception.

## Architecture Patterns

### System Architecture Diagram

```
 sift ingest <case>
        │
        ▼
 ┌────────────────────────┐   sorted(input_dir.rglob("*"))  → node1/DSSErrors.log,
 │ cli.py ingest loop     │                                    node1/DSSErrors.bak00,
 │ (one BEGIN IMMEDIATE)  │                                    node2/DSSErrors.log,
 └───────────┬────────────┘                                    journal.json, threaddump.txt
             │ per file
             ▼
 ┌────────────────────────┐   overrides (flag>config) fnmatch relpath → forced adapter
 │ adapters.detect()      │   else: every adapter.sniff(head64k); unique max ≥0.5 wins;
 │                        │   tie / all-below → genericlog
 └───────────┬────────────┘
             │  ── NEW: cli.py sets config on ANY ConfigurableAdapter, not just genericlog ──
             ▼
 ┌──────────────────────────────────────────────────────────┐
 │  if isinstance(adapter, ConfigurableAdapter):             │   ← was isinstance(GenericLogAdapter)
 │      adapter.input_root   = input_dir                     │
 │      adapter.tz_overrides = dict(config.timezones)        │
 └───────────┬──────────────────────────────────────────────┘
             ▼
 ┌───────────────────────┐   open_bytes(path)  (gzip/zstd/plain, shared seam)
 │ adapter.parse()       │   ├─ journald : split b"\n"; json.loads/line; 1 event/line
 │ → Iterator[Event]     │   ├─ dsserrors: group MCM ***** blocks; token-extract SID/OID/0x/[*.cpp:N]
 │ every byte attributed │   │              node = dir(relpath); to_utc(ts, tz_override)
 │ ParseStats accrues    │   └─ eustack  : group per TID/thread header; top frames→message, all→raw
 └───────────┬───────────┘
             ▼
 ┌───────────────────────┐   INSERT OR IGNORE (event_id PK) — idempotent
 │ store.insert_events() │   severity ∈ 6-value CHECK or file rolls back (savepoint)
 └───────────┬───────────┘
             ▼
 ┌──────────────────────────────────────────────┐
 │  NEW: stats = adapter.last_stats (ANY         │   real per-file coverage %, not 1.0 default
 │  ConfigurableAdapter); coverage → stdout+meta │   dedup.rebuild_template_groups() after commit
 └──────────────────────────────────────────────┘
             ▼
   store: events ts-sorted → `sift show events` / downstream timeline (content order, not filename)
```

### Pattern 1: Generalise `ConfigurableAdapter` — pay down the Phase-1 coupling (HIGHEST STAKES)

**What:** `cli.py` currently delivers per-run config and reads coverage only for genericlog, via four `isinstance(file_adapter, GenericLogAdapter)` sites:
- cli.py:269 — sets `input_root` + `tz_overrides`
- cli.py:277–279 — `track_offsets` progress gate
- cli.py:345–347 — reads `last_stats` (else `stats=None` → `cov=1.0`, `event_count=parsed_count`)

Introduce in `base.py`:
```python
@dataclass
class ConfigurableAdapter:
    """Shared per-run adapter state (NOT part of the frozen Adapter Protocol).
    Every concrete adapter subclasses this so cli.py delivers input_root/
    tz_overrides and reads last_stats uniformly (SPEC §5.2 self-containment)."""
    name: str  # overridden per adapter
    def __init__(self) -> None:
        self.input_root: Path | None = None
        self.tz_overrides: dict[str, str] = {}
        self.last_stats: ParseStats | None = None
```
`GenericLogAdapter` and the three new adapters all subclass it. In `cli.py`, change the config-set and stats-read guards from `isinstance(..., GenericLogAdapter)` to `isinstance(..., ConfigurableAdapter)`. Leave `track_offsets` keyed to genericlog (byte-offset progress is genericlog-specific and non-load-bearing) OR generalise it via the shared `attrs["byte_offset"]/["byte_len"]` convention if the new adapters expose it — recommend the new adapters DO expose `byte_offset`/`byte_len` in attrs for parity and mechanical span-invariant checks, but progress-bar accuracy is not a success criterion.

**Why it matters:** Without this, dsserrors gets no `input_root` (node-tagging impossible), no `tz_overrides` (multi-node timezone criterion 4 impossible), and every new-adapter file reports a **fabricated 100% coverage** — the exact "silent" failure the project forbids, and it would pass a naive test while failing the real ≥95% criterion meaningfully. This is a one-time generalisation; afterwards adapter #6 needs zero cli.py changes, finally making SPEC §5.2 true. **Record as ADR 0005.**

**Boundary:** The frozen `Adapter` Protocol (`base.py:25`) is unchanged — `ConfigurableAdapter` is a separate base class carrying instance attributes, exactly the "config travels on the instance" pattern already decided in Phase 1 (STATE.md). pyright sees a concrete type, so the `isinstance` narrowing type-checks cleanly.

### Pattern 2: journald — JSONL, one event per line (fully specified, build first)

**What:** `journalctl -o json` emits one JSON object per line, UTF-8, newline-separated. No multi-line grouping, no encoding ladder, no continuation logic. Byte accounting is the simple genericlog subset: read bytes, split on `b"\n"`, `offset += len(line_with_newline)`, `event_id(relpath, line_offset)`.

Per-entry mapping:
| Journal field | Event target | Notes |
|---------------|--------------|-------|
| `__REALTIME_TIMESTAMP` | `ts` (`exact`) | Numeric string, **µs** since epoch → `datetime.fromtimestamp(int(v)/1_000_000, tz=UTC)` [VERIFIED: systemd.io] |
| `PRIORITY` | `severity` | syslog 0–7 → 6-value map (Code Example 1); missing/invalid → `unknown` |
| `_SYSTEMD_UNIT` | `component` | e.g. `nginx.service`; may be absent (kernel msgs) → `None` |
| `_PID`, `_COMM` | `attrs["pid"]`, `attrs["comm"]` | strings |
| `_SYSTEMD_INVOCATION_ID` | `session` | SPEC §5.1 "systemd invocation ID"; may be absent |
| `MESSAGE` | `message` | **normalise value types — see Pitfall 1** |
| `_HOSTNAME`, `SYSLOG_IDENTIFIER`, `_BOOT_ID` | `attrs[…]` (optional) | useful context, low cost |

**Coverage semantics:** an entry that fails `json.loads` (or is not a JSON object) → one `severity="unknown"`, `ts=None` event whose bytes count as `unknown_fallback_bytes`. A valid entry with no `__REALTIME_TIMESTAMP` (rare) → structured event with `ts=None`, `ts_confidence="missing"` but its bytes are **covered** (it parsed). Well-formed exports hit ≥95% trivially. Blank lines between objects are attributed (to the following or preceding event) so `sum(spans)==total_bytes` holds.

**Sniff:** decode `read_head`, take the first non-blank line, `json.loads` it, and check for journald-signature keys (`__REALTIME_TIMESTAMP`, `__CURSOR`, or `_BOOT_ID`). Present → return `0.95`; not JSON / no signature → `0.0`. Highly discriminative → clean routing, never collides with dsserrors/eustack/genericlog.

### Pattern 3: journald field-value normalisation (the one real gotcha)

Verified against systemd.io this session — in `-o json`, a field value is **not always a string**:
- normal → JSON **string**
- field > 4096 bytes (with size threshold) → **`null`**
- **binary / non-UTF-8** content → **array of integers** (each byte 0–255)
- field that **appears multiple times** in the entry → **array** of the above (strings / null / int-arrays)

So `MESSAGE` (and any mapped field) must go through a normaliser:
```python
def _field_to_str(v: object) -> str | None:
    if v is None: return None
    if isinstance(v, str): return v
    if isinstance(v, list):
        # array of byte-ints, OR array of repeated values (strings/null/int-arrays)
        if all(isinstance(x, int) for x in v):
            return bytes(v).decode("utf-8", errors="replace")   # binary field
        return "\n".join(s for x in v if (s := _field_to_str(x)) is not None)
    if isinstance(v, int): return str(v)
    return None
```
Failing to handle the int-array case is the classic journald-JSON bug: a `MESSAGE` with an embedded NUL or invalid UTF-8 byte becomes `[72, 105, 0, …]` and a naive `str(v)` stores the Python list repr as the message.

### Pattern 4: dsserrors — MCM multi-line blocks + token extraction

**Line shape (representative, `[ASSUMED]` — pin to a user-confirmed fixture):** a record line begins with a timestamp and carries bracketed module/severity tags and a `[SourceFile.cpp:NNNN]` source-location token, e.g.
```
2026-01-15 12:21:03.456-05:00 [HOST][PID][12345][Kernel][Error] Contract Request Failed... [ContractManagerImpl.cpp:1235]
```
The **reliable, version-stable tokens** (use these to drive parsing; do not depend on exact column order):
- **Timestamp** at line start — parse an offset-bearing ISO-ish prefix via `to_utc` (→ `exact`); if naive, `to_utc` applies the `tz_overrides` glob for this file's node (→ `inferred`). This is the criterion-4 hook.
- **`[<Name>.cpp:<NNNN>]`** source-location → `component` (e.g. `ContractManagerImpl`) and/or `attrs["source_loc"]`. Most reliable dsserrors signature.
- **Severity** from bracketed tags (`[Fatal]`,`[Error]`,`[Warning]`,`[Info]`,`[Trace]`/`[Debug]`) or MSTR `[Kernel][Fatal]` pairs → 6-value map; unrecognised → `unknown` (never fabricate).
- **Thread ID** — a bracketed numeric field → `thread`. Exact position is version-dependent; extract by labelled/positional token in the confirmed fixture.
- **`0x`-prefixed error code** → `attrs["error_code"]` (`0[xX][0-9A-Fa-f]+`).
- **OID** — MicroStrategy object IDs are GUID-shaped (32 hex, or 8-4-4-4-12) → `attrs["oid"]`.
- **SID** — MicroStrategy session ID → `session`. Format is MSTR-specific (long hex / GUID-like); **exact pattern must come from the fixture** — flag `[ASSUMED]`.
- **node** → derived from the directory component of `self.input_root`-relative path (Pattern 1 dependency), e.g. `node1/DSSErrors.log` → `attrs["node"]="node1"`.

**MCM multi-line blocks (one event):** a Contract Request Failed dump is delimited by
`***** Start of Info Dump *****` … `***** End of Info Dump *****` (ISPerfDiag: `ContractManagerImpl.cpp:1235`/`:1244`), enclosing `Source=/Handle=/Size=`, `Current Memory Info:`, `MCM Settings:` sub-blocks. Group everything from the Start sentinel to the End sentinel into **one** event (`component="MCM"`), `message` = a condensed head (title + Source/Size), `raw` = the verbatim block. Also treat the `MCM Telemetry: { …JSON… }` line and multi-line `Total System Physical Memory` breakdowns as belonging to their record. Apply the **same safety caps as genericlog** (256 lines / 64 KB → overflow closes into a `severity="unknown"` continuation event) so a corrupt/never-terminated block cannot slurp unbounded memory.

**Coverage / byte accounting:** identical discipline to genericlog — every byte in exactly one event; interstitial normal lines are their own events; unparseable → `unknown`, `ts=None` (counts as `unknown_fallback_bytes`). ≥95% on a well-formed DSSErrors fixture is comfortable.

**Sniff:** presence of `[A-Za-z]\w*\.cpp:\d+]` source-location tokens and/or MSTR strings (`Contract Request Failed`, `MCM`, `I-Server`) in the head → return ~`0.8` (beats genericlog's `0.1`); else `0.0`. `.bak00`/`.bak01` siblings have the same content signature → sniff dsserrors too.

### Pattern 5: rotated `.bak` siblings + mixed-tz multi-node — ordered by ts, NOT filename, NO cross-file stitching

**The key architectural realisation:** `Adapter.parse(path, case_id)` is **per file** (frozen signature). An adapter cannot and must not stitch records across DSSErrors.log ↔ DSSErrors.bak00. Therefore:
- **"Orders rotated siblings by content, not filename" is satisfied downstream, for free:** each event carries its own UTC `ts`; the timeline (`sift show events`, ts-sorted store query) orders by `ts`. Filename suffix (`.bak00` vs `.bak01`) is **never** consulted for time. The adapter's only job is to give every event a *correct* ts. Do **not** attempt to infer chronology from the `.bakNN` number.
- **Accepted limitation (document + ADR):** an MCM block split across a rotation boundary (tail of `.bak01`, head of `DSSErrors.log`) fragments into two events — one per file. This satisfies "nothing disappears" (both fragments become events) and is the correct trade for the frozen per-file signature. Note it in the adapter docstring.
- **Mixed-timezone multi-node (criterion 4):** two nodes in different zones, each with (possibly naive) local timestamps. `tz_overrides` globs (`node1/*` → `America/New_York`, `node2/*` → `Europe/London`) applied through the shared `to_utc` convert each node's naive stamps to correct UTC; offset-bearing stamps go straight to `exact`. The merged ts-sorted timeline interleaves correctly — causality preserved. This reuses genericlog's exact D-05 mechanism; the only new requirement is that dsserrors is a `ConfigurableAdapter` so it *receives* `tz_overrides` (Pattern 1).

**Test both explicitly:** (a) a fixture where `.bak00` is chronologically *newer* than `.bak01` (reverse of naive numeric order) → assert ts-sorted timeline is chronologically correct and each file parsed independently; (b) two-node naive-local fixture + tz_overrides → assert no causality inversion.

### Pattern 6: eustack — one event per thread

**Format (`[ASSUMED]` primary interpretation — confirm with the user):** "EU-stack" most plausibly means **elfutils `eu-stack`** native per-thread backtraces (MicroStrategy Intelligence Server is native C++, not JVM). Verified format this session:
```
PID 715821 - process
TID 715821:
#0  0x00007f75b5c991b4 clock_nanosleep@@GLIBC_2.17
#1  0x00007f... SomeFunction
TID 715822:
#0  ...
```
Per-thread header `TID <n>:`; frames `#<N>  0x<ADDR>  <symbol>[ - <lib> <source>:<line>]`. **Group each `TID` header + its following `#N` frames into one event:** `thread` = the TID (and thread name if present), `message` = condensed top frames (e.g. first 3–5 `#N` symbol names), `raw` = the full verbatim thread block. `component`/`session` typically `None`. Lock/blocked-on info is generally **absent** in native eu-stack output — SPEC says "where present", so extract it only if the confirmed fixture contains it.

**Alternative interpretation to disambiguate with the user:** a JVM-style thread dump (`"name" #12 daemon prio=5 ... tid=0x... nid=0x... waiting on condition` + `\tat ...` frames + `- parking to wait for <0x…>` / `- waiting to lock <0x…>` / `- locked <0x…>`). This shape *does* carry rich blocked-on/lock info (→ `attrs["waiting_on"]`, `attrs["locked"]`, `attrs["state"]`) and thread state (→ `component` or `attrs["state"]`). **Because SPEC explicitly calls out "blocked-on / lock info", the planner MUST confirm which format the real MicroStrategy artefacts use before freezing regexes** — this is the phase's biggest open question. Write the parser tolerant of the confirmed shape; the grouping rule (per-thread header starts a new event, frames until the next header) is identical either way.

**Timestamp:** a thread dump usually carries at most one header timestamp (dump time), not per-thread. If present, parse via `to_utc` and stamp all threads from that dump with it; if absent, `ts=None`, `ts_confidence="missing"` — never fabricate (do not invent per-thread times). All threads from one dump sharing one ts is correct.

**Coverage:** every byte attributed — preamble/header lines become their own event (or attach to the first thread), inter-thread blank lines attributed, each thread block one event. **Sniff:** `TID \d+:` + `#\d+\s+0x` (eu-stack) or `^"[^"]+" #\d+` + `\n\tat ` (JVM) in head → ~`0.8`; else `0.0`.

### Anti-Patterns to Avoid

- **Adding a new `isinstance(<Adapter>)` branch per adapter in cli.py** — the opposite of the fix; generalise to `ConfigurableAdapter` once (Pattern 1).
- **Trusting `.bakNN` filename order for chronology** — order by ts only (Pattern 5).
- **Cross-file stitching inside `parse()`** — the signature is per-file; fragments are accepted (Pattern 5).
- **`str(message)` on journald `MESSAGE`** without the int-array normaliser (Pitfall 1).
- **Fabricating severity or timestamps** — unrecognised severity → `unknown`; no timestamp → `ts=None`/`missing`.
- **Reporting 1.0 coverage for the new adapters** — the current cli.py default; fixed by Pattern 1.
- **Shelling out to `journalctl`** — read exported files only (SPEC §5.2).
- **Importing `to_utc` from `genericlog`** — promote it to `base.py` first.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Decompression (gz/zst) | anything | `base.open_bytes` | Shared seam, magic-byte detect, multi-frame [existing] |
| Head sampling for sniff | manual read | `base.read_head` (first 64 KB decompressed) | Consistent with registry contract |
| Per-file coverage accounting | new struct | `base.ParseStats` (+ `.coverage`) | Same metric semantics as genericlog; cli.py already reads it |
| UTC normalisation + tz-override | new code per adapter | `base.to_utc` (promote from genericlog) | One code path for criterion 4; `exact`/`inferred` semantics frozen in D-05 |
| Per-run config delivery / coverage read | per-adapter isinstance | `base.ConfigurableAdapter` | Pattern 1 — enables SPEC §5.2 invariant |
| JSON parsing | manual tokeniser | stdlib `json.loads` per line | JSONL is trivially line-delimited; `json` is safe + stdlib |
| µs-epoch → datetime | manual maths | `datetime.fromtimestamp(usec/1e6, tz=UTC)` | Correct, aware, one line |
| Volatile-token masking for dedup | new masks | existing `pipeline/dedup.mask` (MASK_VERSION 2) | Already masks 0x codes, GUIDs (→`<UUID>`), 32-hex SIDs (→`<HEX>`), nums — likely covers dsserrors; verify, don't rebuild (Open Q) |

**Key insight:** the only genuinely new code is three `parse()`/`sniff()` bodies encoding *format knowledge* + the one-time `ConfigurableAdapter` generalisation. Everything structural (decompression, byte offsets, coverage, UTC, tz, dedup masks, storage, idempotency, `sift show`) already exists and must be reused, not re-implemented.

## Common Pitfalls

### Pitfall 1: journald field values are not always strings
**What goes wrong:** `MESSAGE` with binary/non-UTF-8 content is a JSON **array of byte-ints**; a repeated field is a **JSON array**; a >4 KB field is **`null`**. Naive `entry["MESSAGE"]` + `str()` stores `"[72, 105, 0]"` or crashes on `None`.
**Why:** `journalctl -o json` encodes non-string values structurally (verified: systemd.io).
**How to avoid:** route every mapped field through the `_field_to_str` normaliser (Pattern 3); decode int-arrays via `bytes(v).decode("utf-8", errors="replace")`.
**Warning signs:** a fixture with an embedded-NUL message yields a message equal to a Python list repr; `TypeError: 'NoneType'` on a large field.

### Pitfall 2: fabricated 100% coverage for the new adapters
**What goes wrong:** `cli.py` reads `last_stats` only for `GenericLogAdapter` (cli.py:345–347); for the new adapters `stats=None → cov=1.0`, so a dsserrors file full of unparseable regions reports "coverage 100.0%" and the ≥95% criterion passes *vacuously* while hiding dropped signal.
**How to avoid:** Pattern 1 `ConfigurableAdapter` + populate `self.last_stats = ParseStats(...)` in every `parse()`; assert real coverage in tests (bounded `>=95 and <100` on a fixture with a deliberate <5% unparseable region, mirroring the Phase-1 M1 gate technique).
**Warning signs:** e2e ingest prints exactly `coverage 100.0%` for every dsserrors/eustack file regardless of content.

### Pitfall 3: node tag missing because `input_root` was never set
**What goes wrong:** dsserrors computes `node` from the directory, but without `input_root` the adapter can't form the case-relative path → `node` absent or wrong; multi-node collapses.
**How to avoid:** Pattern 1 (cli.py sets `input_root` on any `ConfigurableAdapter`); test with a two-node tmp tree.
**Warning signs:** `attrs["node"]` empty; both nodes' events indistinguishable.

### Pitfall 4: severity outside the 6-value CHECK rolls the whole file back
**What goes wrong:** a journald `PRIORITY` outside 0–7, or a dsserrors severity token mapped to e.g. `"critical"`, violates the `events.severity` CHECK (store.py:150) → `sqlite3.IntegrityError` → the file's savepoint rolls back to zero rows → reported as an errored file, coverage 0.
**How to avoid:** exhaustive maps returning only `fatal|error|warn|info|debug|unknown`; default `unknown` for anything unexpected. Unit-test the full PRIORITY 0–7 range and each dsserrors tag.
**Warning signs:** a file with one odd priority ingests zero events and shows `ERROR …`.

### Pitfall 5: multi-line block never terminates → unbounded memory
**What goes wrong:** a truncated MCM dump (SIGKILL mid-write — ISPerfDiag notes DSSErrors can end mid-sentence) or a giant thread has no closing sentinel; a naive "accumulate until End" slurps the rest of the file into one event.
**How to avoid:** reuse genericlog's 256-line / 64 KB caps → overflow closes into a `severity="unknown"` continuation event; a new record-start token (next timestamped line / next `TID`) also force-closes the open block.
**Warning signs:** one dsserrors/eustack event with a multi-MB `raw`; memory spikes on a truncated fixture.

### Pitfall 6: byte-offset determinism broken by decoded-text splitting
**What goes wrong:** splitting journald/eustack on decoded text or using `.tell()` shifts offsets → `event_id` non-deterministic, idempotency breaks (Phase-1 cardinal sin).
**How to avoid:** split at the byte level on `b"\n"`, `offset += len(byte_line)`, decode per record afterwards — exactly genericlog's `_byte_lines` discipline (journald is UTF-8 so the simple `b"\n"` split suffices; no UTF-16 ladder needed).
**Warning signs:** idempotency test (`second ingest adds 0`) flaky; offsets differ between plain and gz variants.

## Code Examples

### 1. journald PRIORITY → 6-value severity (exhaustive)
```python
# syslog severities 0..7; anything else → "unknown" (never fabricate, CHECK-safe)
_PRIORITY_SEVERITY = {
    0: "fatal", 1: "fatal", 2: "fatal",   # emerg, alert, crit
    3: "error",                            # err
    4: "warn",                             # warning
    5: "info", 6: "info",                  # notice, info
    7: "debug",                            # debug
}
def _severity(priority: object) -> str:
    try:
        return _PRIORITY_SEVERITY.get(int(priority), "unknown")  # priority is a str in json
    except (TypeError, ValueError):
        return "unknown"
```

### 2. dsserrors token extraction (anchor on version-stable tokens, not column order)
```python
# All linear-scan, anchored — no ReDoS (mirrors pipeline/dedup discipline).
_SRCLOC = re.compile(r"\[([A-Za-z]\w*)\.cpp:(\d+)\]")          # component + line
_ERRCODE = re.compile(r"\b0[xX][0-9A-Fa-f]+\b")                # attrs["error_code"]
_OID = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
                  r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b|\b[0-9A-Fa-f]{32}\b")  # GUID OID
_MCM_START = "***** Start of Info Dump *****"
_MCM_END = "***** End of Info Dump *****"
# SID pattern is MicroStrategy-version-specific → derive from the confirmed fixture. [ASSUMED]
```

### 3. Promote UTC normalisation into base.py (shared by genericlog + dsserrors)
```python
# base.py — moved verbatim from genericlog; genericlog imports it back.
def to_utc(dt: datetime, override_tz: str | None) -> tuple[datetime, str]:
    if dt.tzinfo is not None:
        return dt.astimezone(UTC), "exact"
    tz = ZoneInfo(override_tz) if override_tz else UTC
    return dt.replace(tzinfo=tz).astimezone(UTC), "inferred"

def tz_override_for(relpath: str, tz_overrides: dict[str, str]) -> str | None:
    return next((tz for glob, tz in tz_overrides.items() if fnmatch(relpath, glob)), None)
```

### 4. eustack per-thread grouping (tolerant of the confirmed header shape)
```python
# Group: a thread-header line starts a new event; following frame lines accrue
# to it until the next header (or safety cap). Byte offsets tracked on raw bytes.
_TID = re.compile(r"^TID (\d+):")                    # eu-stack (native)
_JVM_HEADER = re.compile(r'^"(?P<name>[^"]+)" #(?P<id>\d+)\b')  # JVM alt (confirm)
_LOCK = re.compile(r"- (parking to wait for|waiting to lock|locked)\s+<(0x[0-9a-f]+)>")
```

## State of the Art

| Old Approach | Current Approach | When | Impact |
|--------------|------------------|------|--------|
| Shell out to `journalctl` and parse text | Read exported `-o json` JSONL, one object/line | SPEC v1 | Deterministic, testable offline; no subprocess |
| Assume journald fields are strings | Handle string / null / int-array / value-array | always (systemd design) | Pattern 3 normaliser mandatory |
| Per-adapter config coupling via isinstance | Shared `ConfigurableAdapter` base | this phase | SPEC §5.2 "zero-change add" finally true |

**Deprecated/outdated:** none relevant — these are stable OS/vendor formats. MicroStrategy DSSErrors/EU-stack layouts vary by product version, which is *why* the fixture must be user-confirmed rather than assumed from memory.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | dsserrors record line begins with a timestamp and carries `[*.cpp:NNNN]` + bracketed severity tags in the representative layout shown | Pattern 4, CE2 | MEDIUM — regex column assumptions break; mitigated by anchoring on tokens not positions + user-confirmed fixture |
| A2 | MicroStrategy SID has a hex/GUID-like shape extractable by regex | Pattern 4 | MEDIUM — wrong SID pattern → `session` empty; **needs the real fixture to pin** |
| A3 | "EU-stack" = elfutils `eu-stack` native per-thread backtraces (MSTR is native C++) | Pattern 6 | HIGH for lock-info: if artefacts are JVM-style dumps, the lock/blocked-on extraction differs entirely — **confirm with user before freezing regexes** |
| A4 | dsserrors OIDs are GUID-shaped (32-hex or 8-4-4-4-12) | Pattern 4, CE2 | LOW-MEDIUM — MSTR object IDs are conventionally GUIDs; verify against fixture |
| A5 | Existing `dedup.mask` (MASK_VERSION 2) adequately collapses dsserrors MCM template variants | Don't Hand-Roll; Open Q | LOW — if SIDs/OIDs escape masking, template groups fragment; check, cheap to extend a mask |
| A6 | journald exports for this project are UTF-8, one object per line (standard `-o json`) | Pattern 2 | LOW — verified systemd behaviour; `-o json-pretty` (multi-line) is a different format and out of scope unless the user needs it |

**These `[ASSUMED]` items — especially A2 and A3 — must be resolved by a user-confirmed sanitised fixture (a `checkpoint:human-verify` fixture-authoring task) before the dsserrors/eustack parser regexes are frozen.**

## Open Questions

1. **eustack format: elfutils `eu-stack` vs JVM-style thread dump?** (A3)
   - Known: SPEC wants thread name/ID, condensed top frames, full stack in raw, and "blocked-on / lock info … where present". Grouping rule is format-independent.
   - Unclear: native eu-stack lacks lock info; JVM dumps carry it. Which do the real MicroStrategy artefacts use?
   - Recommendation: **user provides/confirms one sanitised sample** in Wave 0; write the parser to that shape; ADR-note the choice.

2. **dsserrors exact line layout + SID pattern.** (A1, A2)
   - Known: reliable tokens (`[*.cpp:NNNN]`, `0x…`, GUID OIDs, MCM sentinels).
   - Unclear: field order, thread-ID position, SID token shape — all MSTR-version-dependent.
   - Recommendation: anchor extraction on tokens (robust to reordering) and pin the fixture from a real sanitised sample.

3. **Does `dedup.mask` need dsserrors-specific masks?** (A5)
   - Recommendation: after journald/dsserrors ingest, eyeball `sift show clusters` on the fixture; extend `_MASK` only if SID/OID variants fail to collapse. Do not pre-emptively add masks (YAGNI); if extended, bump `MASK_VERSION` (groups recompute, no migration).

4. **`byte_offset`/`byte_len` in new-adapter attrs?** Recommend yes (parity + mechanical span-invariant checks), but progress-bar accuracy for non-genericlog adapters is not a success criterion — keep `track_offsets` scoped to genericlog if generalising it adds risk.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python ≥ 3.12 (stdlib `json`/`re`/`datetime`/`zoneinfo`) | all three adapters | ✓ | 3.12+ | — |
| `journalctl` (systemd) | **NOT required** — fixtures are handcrafted JSONL | n/a | — | SPEC forbids shelling out; author fixtures by hand |
| `eu-stack` (elfutils) | **NOT required** at runtime/test — fixture is a captured/sanitised text sample | n/a | — | User-provided sample text |
| MicroStrategy Intelligence Server | **NOT required** — fixtures are sanitised static samples | n/a | — | User-provided sanitised DSSErrors/EU-stack samples |

**No external services, no network, no new packages.** The only "dependency" is human: a user-confirmed sanitised sample each for dsserrors and eustack (Open Questions 1–2).

## Validation Architecture

*(nyquist_validation is enabled — this section seeds VALIDATION.md.)*

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (installed; `[tool.pytest.ini_options]` in pyproject.toml) |
| Config file | pyproject.toml; autouse `_isolate_dirs` + `_no_network` in `tests/conftest.py` apply to all new tests |
| Quick run command | `uv run pytest tests/test_journald.py tests/test_dsserrors.py tests/test_eustack.py -x -q` |
| Full suite command | `uv run pytest && uv run ruff check && uv run pyright` |

### Phase Requirements → Test Map
| Req / Criterion | Behaviour | Test Type | Automated Command | File Exists? |
|-----------------|-----------|-----------|-------------------|-------------|
| INGST-07 | `-o json` JSONL → events; PRIORITY→severity (all 0–7); `_SYSTEMD_UNIT`→component; `_PID`/`_COMM`→attrs; µs-epoch→UTC exact | unit | `uv run pytest tests/test_journald.py -x` | ❌ Wave 0 |
| INGST-07 (Pitfall 1) | `MESSAGE` as int-array + as value-array + `null` field normalise correctly | unit | `uv run pytest tests/test_journald.py -k field_types -x` | ❌ Wave 0 |
| INGST-07 coverage | ≥95% (bounded `>=95 and <100`) on a fixture with a deliberate malformed-line region | unit | `uv run pytest tests/test_journald.py -k coverage -x` | ❌ Wave 0 |
| INGST-08 | SID→session, `0x`→attrs["error_code"], GUID→attrs["oid"], `[*.cpp:N]`→component, thread, severity | unit | `uv run pytest tests/test_dsserrors.py -x` | ❌ Wave 0 |
| INGST-08 MCM | `***** Start … End *****` block → one event; truncated block hits cap → unknown continuation | unit | `uv run pytest tests/test_dsserrors.py -k mcm -x` | ❌ Wave 0 |
| INGST-08 multi-node | `node1/…`,`node2/…` → distinct `attrs["node"]` (requires `input_root`) | unit | `uv run pytest tests/test_dsserrors.py -k node -x` | ❌ Wave 0 |
| INGST-08 rotation | `.bak00` chronologically newer than `.bak01` → ts-sorted timeline correct; filename never used for order | unit | `uv run pytest tests/test_dsserrors.py -k rotation -x` | ❌ Wave 0 |
| INGST-08 coverage | ≥95% on DSSErrors fixture | unit | `uv run pytest tests/test_dsserrors.py -k coverage -x` | ❌ Wave 0 |
| INGST-09 | exactly one event per thread; top frames→message; full stack→raw; TID→thread; lock info→attrs where present | unit | `uv run pytest tests/test_eustack.py -x` | ❌ Wave 0 |
| Criterion 4 | mixed-tz two-node fixture + `tz_overrides` → UTC timeline not inverted | integration | `uv run pytest tests/test_dsserrors.py -k timezone -x` (or `tests/test_timeline.py`) | ❌ Wave 0 |
| INGST-03 routing | each fixture sniffs to the right adapter; journald/dsserrors/eustack beat genericlog; no cross-collision | unit | `uv run pytest tests/test_adapters_detect.py -k phase5 -x` | ⚠️ extend existing |
| E2E slice | `sift new`→`sift ingest`→`sift show events` per format; **real** coverage % printed (not 1.0); idempotent re-ingest adds 0 | integration (CliRunner) | `uv run pytest tests/test_cli.py -k "journald or dsserrors or eustack" -x` | ⚠️ extend existing |

### Sampling Rate
- **Per task commit:** `uv run pytest -x -q` (RED→GREEN→gate→commit per the project cadence)
- **Per wave merge:** `uv run pytest && uv run ruff check && uv run pyright`
- **Phase gate:** full suite green (also the SPEC §8 M5 gate) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `base.ConfigurableAdapter` + promoted `to_utc`/`tz_override_for` in `base.py`; `GenericLogAdapter` subclasses it; cli.py `isinstance` sites broadened (Pattern 1) — with a regression check that genericlog behaviour/coverage is unchanged
- [ ] `tests/fixtures/journald/` — handcrafted JSONL: normal entries across PRIORITY 0–7, an entry with `MESSAGE` as int-array, an entry with a value-array field, a `null` field, a malformed line, an entry missing `_SYSTEMD_UNIT`
- [ ] `tests/fixtures/dsserrors/node1|node2/` — **user-confirmed** sanitised sample incl. an MCM dump, a truncated MCM block, `0x` codes, an OID, a SID; `.bak00`/`.bak01` with deliberately reversed chronology; naive local timestamps for the tz test
- [ ] `tests/fixtures/eustack/` — **user-confirmed** sanitised sample (eu-stack or JVM shape per Open Q1) with ≥2 threads and lock info if the format carries it
- [ ] `tests/test_journald.py`, `tests/test_dsserrors.py`, `tests/test_eustack.py`; extend `tests/test_adapters_detect.py` and `tests/test_cli.py`
- [ ] `docs/decisions/0005-*.md` — ADR for `ConfigurableAdapter` generalisation + rotated-siblings-ordered-by-ts decision

## Security Domain

*(security_enforcement enabled, ASVS L1. New surface: parsing three untrusted external formats.)*

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local single-user CLI, no auth surface |
| V3 Session Management | no | — (dsserrors `session`=MSTR SID is *data*, not an auth session) |
| V4 Access Control | no | Filesystem permissions; cli.py already skips symlinks (won't select files outside the bundle) |
| V5 Input Validation | **yes** | All three formats are **untrusted input treated strictly as data**: `json.loads` (no eval); parameterised SQL only (store.py is the sole SQL owner); no format string built from log content; existing `_sanitise` strips control chars at render |
| V6 Cryptography | no | `event_id` uses `hashlib.sha256` for identity only (existing, no change) |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Decompression / oversized-record DoS (giant single JSON line, never-terminated MCM block, monster thread) | DoS | Reuse genericlog 64 KB/256-line caps → overflow closes to `unknown` event; streaming parse; nothing written decompressed to disk (Pitfall 5) |
| Malformed JSON / partial line (SIGKILL-truncated DSSErrors, per ISPerfDiag) | DoS / Tampering | `json.loads` in try/except → `severity="unknown"` event, byte-accounted; never crash (fail-soft, matches "nothing disappears") |
| Terminal escape / ANSI injection in log content echoed by `sift show events` | Tampering/Spoofing | Existing whole-line `_sanitise` at render (Phase 2 WR-01) covers new adapters' fields automatically — verify the new attrs/session/thread fields flow through it |
| Path traversal via crafted node directory name (`attrs["node"]`) | Tampering | `node` is derived from the already-validated case-relative path (inside `input_root`; symlinks skipped by cli.py); it is metadata, never used to open a file |
| SQL injection via SID/OID/message content | Tampering | Parameterised `?` placeholders only (store.py) — unchanged; new fields ride the same path |
| Network egress | Info disclosure | Zero new network code; journald reads files, never invokes `journalctl`; autouse socket guard keeps tests offline |

No new secrets, no crypto, no auth. The security posture is entirely "untrusted-input-as-data" hardening, and the existing Phase-1/2 controls (caps, `_sanitise`, parameterised SQL, symlink skip, socket guard) extend to the new adapters for free — the plan need only verify the new fields flow through `_sanitise` and that caps are applied in the two new grouping loops.

## Sources

### Primary (verified this session)
- https://systemd.io/JOURNAL_EXPORT_FORMATS/ — JSON field encoding: strings / `null` (>4096B) / **int-arrays for binary** / **value-arrays for repeated fields**; `__REALTIME_TIMESTAMP` = µs-since-epoch numeric string [VERIFIED via WebFetch 2026-07-17]
- https://www.freedesktop.org/software/systemd/man/latest/journalctl.html — `-o json`, always-present `__CURSOR`/`__REALTIME_TIMESTAMP`/`_BOOT_ID`, `--output-fields` [CITED]
- eu-stack output format: `PID <n> - process` / `TID <n>:` / `#N 0xADDR symbol[ - lib source:line]` [VERIFIED via WebSearch 2026-07-17: Red Hat Developer / elfutils]
- Repo code read this session: `src/sift/adapters/base.py` (Protocol, `open_bytes`, `read_head`, `ParseStats`), `genericlog.py` (`to_utc`, byte-line/caps/coverage discipline), `adapters/__init__.py` (registry/detect), `cli.py:180–379` (the `isinstance(GenericLogAdapter)` coupling), `pipeline/dedup.py` (mask), `store.py:150` (severity CHECK), `models.py` (frozen Event)

### Secondary (domain knowledge — MicroStrategy)
- `~/.claude/skills/ISPerfDiag/references/dsserrors-patterns.md` — MCM `***** Start/End of Info Dump *****` sentinels, `ContractManagerImpl.cpp`/`MSIServerStateLogger.cpp`/`CDSSCubeEventReceiver.cpp` source-location tokens, MCM Telemetry JSON, mid-sentence truncation = SIGKILL [project domain reference]

### Project ground truth
- SPEC.md §5.1 (frozen Event), §5.2 (Adapter Protocol + build order + self-containment rule), §5.3 (store), §8-M5 (acceptance)
- .planning/ROADMAP.md Phase 5 success criteria; .planning/REQUIREMENTS.md INGST-07/08/09; .planning/STATE.md (Phase-1 "config travels on the instance" decision); .planning/phases/01-…/01-RESEARCH.md (house style, byte-offset/coverage patterns)
- CLAUDE.md + .claude/CLAUDE.md (boring-tech, determinism, British English, zero-network invariants)

## Metadata

**Confidence breakdown:**
- Reuse/architecture strategy (`ConfigurableAdapter`, shared helpers, coverage): **HIGH** — all source code read this session; the coupling and its consequences are concrete, not inferred
- journald format + mapping: **HIGH** — field-type rules and timestamp semantics verified against systemd.io; only real gotcha (int-arrays) captured
- dsserrors: **MEDIUM** — MCM structure and extraction tokens are reliable (domain reference); exact line layout + SID pattern are version-dependent `[ASSUMED]`, must be pinned by a user-confirmed fixture
- eustack: **MEDIUM-LOW** — grouping rule solid; the format itself (eu-stack vs JVM) is an open question gating lock-info extraction — user must confirm before regexes freeze
- Pitfalls / security: **HIGH** — all extend existing verified controls

**Research date:** 2026-07-17
**Valid until:** ~2026-09-15 (stable OS/vendor formats + stdlib; re-confirm only the dsserrors/eustack fixture shape against the user's real MicroStrategy version at plan time)
</content>
</invoke>
