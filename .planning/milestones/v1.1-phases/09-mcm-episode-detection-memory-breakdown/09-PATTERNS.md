# Phase 9: MCM Episode Detection & Denial-Time Memory Breakdown - Pattern Map

**Mapped:** 2026-07-19
**Files analysed:** 4 (3 new, 0 modified, 1 vendored reference)
**Analogs found:** 4 / 4

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/pipeline/mcm.py` | pipeline stage + models | transform (stored events → typed models) | `src/sift/pipeline/salience.py` | exact (pure-function-over-stored-rows) |
| `tests/test_mcm.py` | test | transform-assert | `tests/test_salience.py` + `tests/test_dedup.py` (ingest→store) | exact (salience shape) + role-match (store ingest) |
| `tests/fixtures/mcm/hartford_deny_slice.log` | fixture | file-I/O (test input) | `tests/fixtures/node1/DSSErrors.log` (used by `tests/test_dsserrors.py`) | role-match |
| `docs/reference/analyze_dss8.py` | reference (vendored, non-executed) | n/a | n/a — provenance copy of `/home/oliverh/Downloads/analyze_dss8.py` | n/a |

**Note:** Per D-01/CONTEXT, the dsserrors adapter (`src/sift/adapters/dsserrors.py`) and `src/sift/models.py` are **read-only alignment references — NOT modified.** No new store schema (D-05), no CLI wiring (Phase 10).

## Pattern Assignments

### `src/sift/pipeline/mcm.py` (pipeline stage + typed models, transform)

**Primary analog:** `src/sift/pipeline/salience.py` — the deterministic, typer-free / print-free / SQL-free pure function over already-queried rows.

**Module-docstring + purity contract to mirror** (`salience.py:1-19`):
```python
"""Deterministic salience ranking of clusters (RAG-01, SPEC §5.4).

This module mirrors ``cluster.py``'s contract: it is typer-free, print-free and
SQL-free — the caller passes in the already-queried clusters and template
groups, and this function returns a ranked list. No I/O, no LLM.
...
"""
from __future__ import annotations
```
Copy this stance verbatim in spirit: `mcm.py` takes `events: list[Event]` (already queried), returns `list[McmEpisode]`, does no I/O and no LLM. Cite the requirement as MCM-01/MCM-02, SPEC-less (milestone v1.1).

**Entry-point signature to follow** (mirrors `salience.rank_clusters` at `salience.py:126`):
```python
def detect_episodes(events: list[Event]) -> list[McmEpisode]:
    dss = [e for e in events if e.source == "dsserrors"]   # already UTC-ordered by store
    stream = [(line, e.event_id, e.source_file)
              for e in dss for line in e.raw.split("\n")]
    ...  # ported prescan + parsers over `stream`
```
The caller passes `store.query_events()` — do NOT re-sort; the SQL `ORDER BY ts IS NULL, ts, source_file, line_start` (store.py:567) already IS the D-06 order.

**UTC helpers — reuse, do not re-derive** (`salience.py:58-77`):
```python
def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def _parse(ts: str | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(ts))
    except ValueError:
        return None
```
Prefer `event.ts` (already parsed by the adapter) for annotation timestamps over re-matching `TIMESTAMP_RE` (RESEARCH §Note on TIMESTAMP_RE). If a UTC helper is needed, follow this shape or import from salience.

**Determinism / tie-break pattern** (`salience.py:215`):
```python
ranked.sort(key=lambda item: (-item[1], item[0].cluster_id))
```
Copy the discipline: any ordered output is deterministic; no `set()` iteration (RESEARCH anti-pattern). Insertion-ordered dicts + the SQL order only.

**Local frozen-vocabulary constant pattern** (`salience.py:34-41`) — mirror for the ported marker/regex constants (`DENIAL_MARKER`, `NORMAL_MARKER`, `DETAIL_LINE_RE`, `UNIT_TO_MB`, etc.), ported verbatim from `analyze_dss8.py` lines 38-66 as module constants with a comment citing provenance.

---

**Typed-model analog:** `src/sift/models.py` — the frozen-dataclass / Pydantic `extra="forbid"` convention.

**Frozen Event dataclass (the input contract — do NOT modify)** (`models.py:17-35`): fields the analyser reads — `event_id`, `ts`, `source`, `source_file`, `line_start`, `line_end`, `raw`. MCM tokens live in `raw` (D-01), not `attrs`.

**Pydantic model convention to copy for `McmEpisode` / `MemoryBreakdown`** (`models.py:61-73`):
```python
class Hypothesis(BaseModel):
    """One ranked, evidence-cited root-cause hypothesis (SPEC §5.5 verbatim)."""
    model_config = ConfigDict(extra="forbid")
    title: str
    ...
```
Per D-04 + RESEARCH Q3 recommend `model_config = ConfigDict(frozen=True, extra="forbid")` (Phase 11 needs `model_dump_json()` for the determinism test and the analyze feed). The `MemoryBreakdown.raw_map` + `_get(substr)` fuzzy-accessor shape is spelled out in RESEARCH §Pattern 2 (ported from `analyze_dss8.py:500`).

---

### `tests/test_mcm.py` (test)

**Analog A — pure-function assertion structure:** `tests/test_salience.py`
- `from __future__ import annotations` + direct import of the module function (`test_salience.py:10-18`).
- Determinism test shape (`test_salience.py:90-104`): call twice, assert equal — adapt to `model_dump_json()` byte-identity (crit #5 / `test_determinism_byte_identical`).
- Private-symbol drift-guard import with `# pyright: ignore[reportPrivateUsage]` (`test_salience.py:15`) — use for asserting ported marker constants if needed.

**Analog B — ingest fixture → store → query round-trip:** `tests/test_dedup.py:221-224` and `tests/test_dsserrors.py:22-34`.
```python
# tests/test_dedup.py:221
store = CaseStore(tmp_path / "case.db")
store.insert_events(events)
```
```python
# tests/test_dsserrors.py:28-32 — parse a fixture through the real adapter
adapter = DsserrorsAdapter()
adapter.input_root = root
adapter.tz_overrides = tz_overrides
events = list(adapter.parse(root / relname, "case1"))
```
Compose these: parse the Hartford slice via `DsserrorsAdapter`, `store.insert_events(...)`, then `detect_episodes(store.query_events())`. Check `tests/conftest.py` and `tests/test_dsserrors.py:22 run_parse` for the established helper before writing a new one (RESEARCH Wave 0 gap).

---

### `tests/fixtures/mcm/hartford_deny_slice.log` (fixture, file-I/O)

**Analog:** `tests/fixtures/node1/DSSErrors.log` (consumed via `FIXTURES / "node1" / "DSSErrors.log"`, `test_dsserrors.py:67`).
Trimmed verbatim slice per RESEARCH Wave 0: denial banner + Format-A detail block + one preceding Info Dump (Format B, incl. `Memory Reserve = 0 (0Bytes)`), lifecycle lines (memory-status-low, offload start/complete), a few `Contract Request Succeeded` with `AvailableMCM`/`HWM(PB)`, ending **without** `State=normal`. Keep bytes verbatim so `event_id`s (sha256 of source_file+byte_offset) stay stable.

---

### `docs/reference/analyze_dss8.py` (vendored reference)

No analog — a provenance copy of `/home/oliverh/Downloads/analyze_dss8.py` (CONTEXT canonical-refs action). Non-executed; provides citable line anchors for the KEEP list (prescan 112-238, parse_detail_block 247-267, parse_abbrev_block 270-286, `_get` 500-504, constants 38-66). DISCARD list (prompts/window/attribution/report) stays out of `mcm.py`.

## Shared Patterns

### Store read API (input source — no new schema, D-01/D-05)
**Source:** `src/sift/store.py:563` `query_events() -> list[Event]` (ORDER BY `ts IS NULL, ts, source_file, line_start`, store.py:567). Also `get_events_by_ids(ids) -> dict[str, Event]` (store.py:590) and `iter_event_rows(...)` (store.py:644) exist but are NOT needed — `detect_episodes` takes the already-queried list.
**Apply to:** `mcm.py` (caller passes the result in) and `test_mcm.py`.

### Frozen model + `extra="forbid"` convention
**Source:** `src/sift/models.py:64` (`ConfigDict(extra="forbid")`) and the frozen `@dataclass` Event (models.py:17).
**Apply to:** `McmEpisode`, `MemoryBreakdown`, and any lifecycle-signal / annotation model in `mcm.py`.

### Anchored linear-scan regex discipline (V5 / no ReDoS)
**Source:** `src/sift/adapters/dsserrors.py:50` ("Anchored, linear-scan token regexes — no ReDoS") plus the 256-line / 64 KB event caps (`dsserrors.py:47-48`) and reference's 60-line block cap.
**Apply to:** every ported regex in `mcm.py` — keep `^`-anchored with a required terminator; keep the 60-line block cap.

### Adapter alignment (read-only) — why Info Dumps are NOT pre-grouped
**Source:** `src/sift/adapters/dsserrors.py:69,270` — the adapter groups an MCM block only when `stripped == _MCM_START` (a *standalone* `***** Start of Info Dump *****` line):
```python
# dsserrors.py:69
_MCM_START = "***** Start of Info Dump *****"
# dsserrors.py:270
if stripped == _MCM_START:
    ...  # opens a single is_mcm event
```
Hartford embeds the marker inside a timestamped `Contract Request Failed. ***** Start of Info Dump *****.` line, so `stripped == _MCM_START` is **false** and the Info Dump is NOT grouped into one event (RESEARCH Finding 2 / Pitfall 1). **Consequence for the planner:** `mcm.py` must scan `event.raw` line-by-line for the `Current Memory Info:` / `MCM Settings:` substrings — never assume adapter pre-grouping. Existing adapter token regexes `_MCM_SOURCE_RE` (`Source=(\S+)`, dsserrors.py:71) and `_MCM_SIZE_RE` (`\bSize=(\d+)`, dsserrors.py:72) exist; align with them but the analyser uses the reference's precise bracketed `[SID:...]`/`[OID:...]` and `\bSize=(\d+)` forms on `event.raw`.

## No Analog Found

None. Every new file maps to an existing analog; the deterministic algorithm itself is a port of `analyze_dss8.py` (RESEARCH: "port, not a research problem").

## Metadata

**Analog search scope:** `src/sift/pipeline/`, `src/sift/`, `tests/`
**Files scanned:** salience.py, models.py, store.py (563-668), adapters/dsserrors.py (40-118, 262-295), test_salience.py, test_dsserrors.py, test_dedup.py
**Pattern extraction date:** 2026-07-19
