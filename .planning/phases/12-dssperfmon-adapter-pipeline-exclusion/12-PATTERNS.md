# Phase 12: `dssperfmon` Adapter & Pipeline Exclusion - Pattern Map

**Mapped:** 2026-07-20
**Files analysed:** 8 (3 created, 5 modified)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/sift/adapters/dssperfmon.py` (new) | adapter/parser | file-I/O → transform | `src/sift/adapters/dsserrors.py` | exact (simpler sibling) |
| `tests/test_dssperfmon.py` (new) | test | unit | `tests/test_dsserrors.py` | exact |
| `tests/fixtures/dssperfmon/*.csv` (new) | fixture | file-I/O | `tests/fixtures/dsserrors/`, `tests/fixtures/mcm/` | exact |
| `src/sift/adapters/__init__.py` | config/registry | lookup | 4 existing `REGISTRY` entries | exact |
| `src/sift/store.py` `iter_event_summaries` | store/SQL | streaming read | `iter_event_rows` (adjacent) + `get_events_by_ids` (`?`-bound `IN`) | exact |
| `tests/test_store.py` | test | unit | existing store cases | exact |
| `tests/test_cli.py` | test | integration | existing `CliRunner` cases | exact |
| `tests/test_cluster.py` | test | unit + fake HTTP | `_embed_handler` at `test_cluster.py:78` | exact |

---

## Pattern Assignments

### `src/sift/adapters/dssperfmon.py` (adapter, file-I/O → transform)

**Analog:** `src/sift/adapters/dsserrors.py` (whole file, 330 lines — read once, fully in context).

#### 1. Imports — copy this block verbatim, drop what is unused

`dsserrors.py:25-40`:
```python
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sift.adapters.base import (
    ConfigurableAdapter,
    ParseStats,
    open_bytes,
    read_head,
    to_utc,
    tz_override_for,
)
from sift.adapters.genericlog import byte_lines
from sift.models import Event, event_id
```
For `dssperfmon`: swap `import re` → `import csv` (D-20; the sniff is an anchored
literal prefix, so no regex is needed at all).

#### 2. Class shape + sniff

`dsserrors.py:155-169`:
```python
class DsserrorsAdapter(ConfigurableAdapter):
    """MicroStrategy DSSErrors.log adapter (INGST-08).

    Inherits ``input_root``/``tz_overrides``/``last_stats`` from
    ``ConfigurableAdapter`` — per-run config travels on the instance because
    the frozen ``Adapter`` Protocol carries no config attributes.
    """

    name = "dsserrors"

    def sniff(self, path: Path) -> float:
        head = read_head(path).decode("utf-8", errors="replace")
        if _SNIFF_SRCLOC_RE.search(head) or any(s in head for s in _SNIFF_STRINGS):
            return 0.8
        return 0.0
```
Per D-18 / RESEARCH Pitfall 3, `dssperfmon.sniff` is the **byte** form (no decode
needed, no regex):
```python
def sniff(self, path: Path) -> float:
    return 0.95 if read_head(path).startswith(b'"(PDH-CSV 4.0)') else 0.0
```

#### 3. Parse preamble — relpath / tz override / stats / offset

`dsserrors.py:171-184`:
```python
def parse(self, path: Path, case_id: str) -> Iterator[Event]:
    relpath = (
        path.relative_to(self.input_root) if self.input_root else Path(path.name)
    ).as_posix()
    parts = Path(relpath).parts
    node = parts[0] if len(parts) > 1 else None
    override_tz = tz_override_for(relpath, self.tz_overrides)
    stats = ParseStats(path=relpath)
    current: _Record | None = None
    offset = 0
    line_no = 0
```

#### 4. THE byte-offset loop — the single most load-bearing excerpt

`dsserrors.py:256-264`:
```python
with open_bytes(path) as stream:
    # DSSErrors is UTF-8: a plain b"\n" byte split suffices; byte_lines
    # still force-splits a monster line at MAX_EVENT_BYTES (T-05-20).
    for bline in byte_lines(stream, b"\n", b"", unit=1):
        line_offset = offset
        offset += len(bline)  # every byte counted, newline too
        line_no += 1
        decoded = bline.decode("utf-8", errors="replace")
        text = decoded.rstrip("\r\n")
```
`byte_lines` signature — `genericlog.py:227-229`:
```python
def byte_lines(
    stream: io.BufferedIOBase, nl: bytes, initial: bytes, unit: int = 1
) -> Iterator[bytes]:
```
It yields terminator-included byte lines and force-splits at `MAX_EVENT_BYTES`
(`genericlog.py:250-257`). `dssperfmon` calls it identically: `byte_lines(stream, b"\n", b"", unit=1)`.

**Invariants the planner must preserve (D-20):** `offset += len(bline)` executes
*before* any decode/parse, so no parse outcome perturbs it; `csv.reader([text])`
parses exactly one already-decoded row and never owns the read loop; a blank line
advances the offset then `continue`s.

#### 5. Stats close-out — the last two lines of `parse`

`dsserrors.py:326-329`:
```python
if current is not None:
    yield finish(current)
stats.total_bytes = offset
self.last_stats = stats
```
`dssperfmon` has no accumulator, so it is just the final two lines. Note
`stats.total_bytes = offset` runs *after* the loop, so `ParseStats.coverage`
(`base.py:48-53`) is correct for free.

#### 6. Event construction + attrs — `finish()`

`dsserrors.py:186-220`:
```python
def finish(rec: _Record) -> Event:
    stats.event_count += 1
    if rec.is_fallback:
        stats.unknown_fallback_bytes += rec.byte_len
    raw = "".join(rec.raw_parts)
    message = _mcm_message(raw) if rec.is_mcm else "\n".join(rec.message_lines)
    attrs: dict[str, str] = {
        "byte_offset": str(rec.offset),
        "byte_len": str(rec.byte_len),
    }
    if node is not None:
        attrs["node"] = node
    ...
    return Event(
        event_id=event_id(relpath, rec.offset),
        case_id=case_id,
        ts=rec.ts,
        ts_confidence=rec.ts_confidence,
        source=self.name,
        source_file=relpath,
        line_start=rec.line_start,
        line_end=rec.line_end,
        severity=rec.severity,
        component=rec.component,
        thread=rec.thread,
        session=rec.session,
        message=message,
        attrs=attrs,
        raw=raw,
    )
```
Notes for `dssperfmon`: `line_start == line_end` (D-04); `thread`/`session` are
`None`; `component` = host. **Keep `byte_offset`/`byte_len` in `attrs`** — the
`assert_span_partition` test helper (`test_dsserrors.py:37-47`) depends on those
exact key spellings and is worth reusing verbatim.

Frozen `Event` contract — `models.py:17-35` (`attrs: dict[str, str]`, so D-03's
"values stay strings" is a type constraint, not a style choice) and
`models.py:38-47` `event_id(source_file, byte_offset)`.

#### 7. THE tz path — ADR 0012 locks this exact shape

`dsserrors.py:103-117`:
```python
def _match_ts(text: str, override_tz: str | None) -> tuple[int, datetime, str] | None:
    """Return (prefix_end, aware-UTC datetime, ts_confidence) or None.

    An offset-bearing stamp -> ``exact``; a naive stamp -> ``inferred`` after
    the node's ``tz_overrides`` glob is applied through the shared ``to_utc``.
    """
    m = _TS_RE.match(text)
    if m is None:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace(",", "."))
    except ValueError:
        return None
    dt_utc, confidence = to_utc(dt, override_tz)
    return m.end(), dt_utc, confidence
```
`base.py:97-102` — what `to_utc` actually does:
```python
def to_utc(dt: datetime, override_tz: str | None) -> tuple[datetime, str]:
    """Normalise to aware UTC, returning (datetime, ts_confidence) per D-05."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC), "exact"
    tz = ZoneInfo(override_tz) if override_tz else UTC
    return dt.replace(tzinfo=tz).astimezone(UTC), "inferred"
```
`base.py:105-114` — `tz_override_for(relpath, tz_overrides)`, first fnmatching glob
in insertion order, else `None`.

**ADR 0012 mapping:** `dssperfmon` parses `MM/DD/YYYY HH:MM:SS.fff` with
`datetime.strptime` (not `fromisoformat`), then calls `to_utc(dt, override_tz)` with
`override_tz` from `tz_override_for` — byte-for-byte the same call shape. The header
bias is **recorded** in `attrs["tz_name"]` / `attrs["tz_offset_min"]` and disclosed
once in `ParseStats.notes`, **never applied**. `ts_confidence` is whatever `to_utc`
returns (`"inferred"` for the naive/no-override case, per D-11 revised).
A `ValueError` from `strptime` routes to the D-15 path: `ts=None`,
`ts_confidence="missing"`, `severity="unknown"`, `raw` preserved — mirroring
`_match_ts`'s `except ValueError: return None` guard above.

#### 8. Unknown-fallback pattern

`dsserrors.py:314-325`:
```python
else:
    # Leading/interstitial unparseable region -> its own
    # severity=unknown, ts=None event (counts as fallback).
    current = _Record(
        offset=line_offset,
        line_start=line_no,
        ts=None,
        ts_confidence="missing",
        severity="unknown",
        is_fallback=True,
    )
    add_line(current, text, decoded, len(bline))
```
Coupled with `finish()`'s `if rec.is_fallback: stats.unknown_fallback_bytes += rec.byte_len`
(`dsserrors.py:188-189`). `dssperfmon` sets the same flag for D-14 (bad cell),
D-15 (bad timestamp) and D-16 (column drift). Also copy the never-fabricate
discipline of `_severity_from` (`dsserrors.py:94-100`) — default `"unknown"`, and
per D-05 a good row is unconditionally `"info"`.

---

### `src/sift/adapters/__init__.py` (registry, lookup)

**Analog:** the four existing entries. Two edits, `__init__.py:11-14` and `:18-23`:
```python
from sift.adapters.dsserrors import DsserrorsAdapter
from sift.adapters.eustack import EustackAdapter
from sift.adapters.genericlog import GenericLogAdapter
from sift.adapters.journald import JournaldAdapter

SNIFF_THRESHOLD = 0.5

REGISTRY: dict[str, Adapter] = {
    "genericlog": GenericLogAdapter(),
    "journald": JournaldAdapter(),
    "dsserrors": DsserrorsAdapter(),
    "eustack": EustackAdapter(),
}
```
Add `"dssperfmon": DssperfmonAdapter(),` plus its import (alphabetical import order,
`REGISTRY` order is insertion-significant for determinism — appending is safest).

`detect()` (`__init__.py:85-91`) scores **every** registered adapter against **every**
file:
```python
scored = [(adapter.sniff(path), adapter) for adapter in REGISTRY.values()]
best = max(score for score, _ in scored)
if best >= SNIFF_THRESHOLD:
    winners = [adapter for score, adapter in scored if score == best]
    if len(winners) == 1:
        return winners[0]
return REGISTRY["genericlog"]
```
This is why D-18's `0.95`-or-`0.0` anchored prefix matters: `0.95` can never tie the
existing maxima (dsserrors `0.8`), and `0.0` on every non-PDH file leaves existing
routing untouched.

---

### `src/sift/store.py` — the exclusion seam (the phase's main hazard)

**The two adjacent methods, side by side.** `store.py:631-667`:

```python
    def iter_event_summaries(self) -> Iterator[tuple[str, str | None, str, str]]:
        """Yield (event_id, ts, severity, message) in canonical order (CLUS-01).

        Streams rows from the cursor — never fetchall — and never selects
        raw, so nothing is decompressed during dedup.
        """
        cursor = self._conn.execute(
            "SELECT event_id, ts, severity, message FROM events "
            "ORDER BY ts IS NULL, ts, source_file, line_start"
        )
        for row in cursor:
            yield (row[0], row[1], row[2], row[3])

    def iter_event_rows(
        self, filters: Mapping[str, str | int] | None = None
    ) -> Iterator[tuple[str, str | None, str, str, int, str]]:
        """Yield (event_id, ts, severity, source_file, line_start, message).

        Exactly the six fields `show events` renders, in the canonical order,
        streamed from the cursor — never fetchall, never selecting raw, so a
        1M-event case renders without hydrating Events or decompressing zstd
        (T-02-10, STORE-04). Filters are allowlisted keys mapped to fixed
        ?-bound WHERE snippets (T-02-08).
        """
        where_sql, limit_sql, params = _build_filter_clauses(
            filters, _EVENT_FILTER_SQL
        )
        cursor = self._conn.execute(
            "SELECT event_id, ts, severity, source_file, line_start, message "
            # S608 convention: where/limit SQL comes from the module-constant
            # allowlist dicts; every value is ?-bound.
            f"FROM events{where_sql} "  # noqa: S608
            f"ORDER BY ts IS NULL, ts, source_file, line_start{limit_sql}",
            params,
        )
        for row in cursor:
            yield (row[0], row[1], row[2], row[3], row[4], row[5])
```

**Why the asymmetry needs a guard (D-08 / Pitfall 2):** identical `ORDER BY`,
identical streaming-cursor idiom, identical "never fetchall / never select raw"
docstring. Only the column list and the filter differ. A future tidy-up factoring
them into one helper silently kills citation. The plan must (a) add a comment on
`iter_event_rows` stating the asymmetry is deliberate, and (b) ship
`test_iter_event_rows_unfiltered`.

**The `?`-bound `IN (...)` idiom to copy** — `get_events_by_ids`, `store.py:601-609`:
```python
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            # S608: column list is a module constant; every id is ?-bound.
            f"SELECT {_EVENT_COLUMNS} FROM events "  # noqa: S608
            f"WHERE event_id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
```
This is the exact discipline the exclusion must follow: the placeholder *count* is
interpolated, never a value; `# noqa: S608` carries a comment justifying why the
f-string is safe. `sorted(EXCLUDED_FROM_RANKING)` keeps parameter order deterministic.

**Where the constant goes** — beside the other SQL module constants at
`store.py:301-352` (`_EVENT_COLUMNS`, `_EVENT_FILTER_SQL`, ...). Note the existing
allowlist comment style (`store.py:327-331`) explaining *why* the construction is
injection-safe; the new constant should carry an equivalent PERF-03 rationale
comment. `_EVENT_FILTER_SQL` (`store.py:332-338`) already contains `"source": "source = ?"`
— the exclusion is a different, unconditional clause, not a new allowlist entry.

---

### `tests/test_dssperfmon.py` (test, unit)

**Analog:** `tests/test_dsserrors.py`.

Module docstring + fixture root, `test_dsserrors.py:1-19`:
```python
"""dsserrors adapter tests: token extraction, MCM grouping + safety caps, node
tagging, rotation-ordered-by-ts, and the criterion-4 mixed-timezone timeline
(selectable via ``pytest -k token/mcm/node/rotation/timezone/coverage/sniff``).

Fixtures live under tests/fixtures/dsserrors/ (plan 05-04 Task 1). ...
"""

from datetime import datetime
from pathlib import Path

from sift.adapters.base import ParseStats
from sift.adapters.dsserrors import (
    MAX_EVENT_LINES,
    DsserrorsAdapter,
)
from sift.models import Event

FIXTURES = Path(__file__).parent / "fixtures" / "dsserrors"
```

Parse driver — `test_dsserrors.py:22-34` (copy near-verbatim, swap the class):
```python
def run_parse(
    root: Path,
    relname: str,
    tz_overrides: dict[str, str] | None = None,
) -> tuple[list[Event], ParseStats]:
    """Parse root/relname with a fresh adapter; return (events, stats)."""
    adapter = DsserrorsAdapter()
    adapter.input_root = root
    if tz_overrides:
        adapter.tz_overrides = tz_overrides
    events = list(adapter.parse(root / relname, "case1"))
    assert adapter.last_stats is not None
    return events, adapter.last_stats
```

Byte-span determinism assertion — `test_dsserrors.py:37-47`, **reuse verbatim**;
it is the strongest available check that `offset += len(bline)` was not perturbed:
```python
def assert_span_partition(events: list[Event], total_bytes: int) -> None:
    """Event byte spans must partition the file: contiguous from 0,
    non-overlapping, summing to the total decompressed byte count."""
    pos = 0
    for e in events:
        assert int(e.attrs["byte_offset"]) == pos, (
            f"gap/overlap at {e.event_id}: span starts at "
            f"{e.attrs['byte_offset']}, expected {pos}"
        )
        pos += int(e.attrs["byte_len"])
    assert pos == total_bytes
```

Synthetic-fixture helper (D-17 — the real CSV has zero malformed cells), `test_dsserrors.py:55-59`:
```python
def write(root: Path, relname: str, data: bytes) -> Path:
    path = root / relname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
```

Sniff test pair — `test_dsserrors.py:65-73` (asserts the exact score both ways):
```python
def test_sniff_dsserrors_head_high() -> None:
    adapter = DsserrorsAdapter()
    assert adapter.sniff(FIXTURES / "node1" / "DSSErrors.log") == 0.8


def test_sniff_plain_text_zero(tmp_path: Path) -> None:
    path = write(tmp_path, "plain.txt", b"just some prose\nno tokens here\n")
    adapter = DsserrorsAdapter()
    assert adapter.sniff(path) == 0.0
```

---

### `tests/fixtures/dssperfmon/*.csv` (fixture)

**Analog:** `tests/fixtures/` contains exactly `dsserrors/`, `eustack/`, `journald/`,
`mcm/` — one directory per adapter/domain, accessed via
`Path(__file__).parent / "fixtures" / "<name>"`. Create `tests/fixtures/dssperfmon/`
holding `hartford_deny_slice.csv` (verbatim header + ~20 real rows), mirroring the
`fixtures/mcm/hartford_deny_slice.log` precedent. Cases 2–7 in RESEARCH § Q6 stay
inline via the `write()` helper.

---

### `tests/test_adapters_detect.py` (regression gate — read this before touching the registry)

Existing structure, `test_adapters_detect.py:14-25`:
```python
_PHASE5_CASES = [
    ("journald", FIXTURES / "journald" / "basic.json", "basic.json"),
    (
        "dsserrors",
        FIXTURES / "dsserrors" / "node1" / "DSSErrors.log",
        "node1/DSSErrors.log",
    ),
    ("eustack", FIXTURES / "eustack" / "threaddump.txt", "threaddump.txt"),
]
_DOMAIN_ADAPTERS = ("journald", "dsserrors", "eustack")
```
Three parametrised assertions run over it (`:142-165`): routes-to-own-adapter,
beats-genericlog, and — the one that matters most —
```python
def test_phase5_no_cross_collision(name: str, path: Path, relpath: str) -> None:
    """Exactly one domain adapter clears the threshold on each fixture, so the
    detect() maximum is unique and routing is never ambiguous."""
    claimants = [
        n for n in _DOMAIN_ADAPTERS if REGISTRY[n].sniff(path) >= SNIFF_THRESHOLD
    ]
    assert claimants == [name]
```
**Planner action:** append the `dssperfmon` fixture tuple to `_PHASE5_CASES` and
`"dssperfmon"` to `_DOMAIN_ADAPTERS`. That single edit makes all three tests cover
the 5th adapter, including proving `dssperfmon` claims nothing it shouldn't and that
nothing else claims the CSV. The `registry` fixture (`:42-50`) save/restore idiom is
there if a test needs to mutate `REGISTRY`.

---

### `tests/test_cluster.py` (test, unit + fake HTTP)

`_seed` + `_embed_handler`, `test_cluster.py:70-100` — the existing no-socket fake:
```python
def _seed(store: CaseStore, messages: list[str]) -> None:
    """Insert one event per message and rebuild template groups (one per msg)."""
    events = [_ev(i, m) for i, m in enumerate(messages)]
    with store.transaction():
        store.insert_events(events)
    dedup.rebuild_template_groups(store)


def _embed_handler(
    calls: list[str] | None = None, *, chat_content: str | None = None
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            if calls is not None:
                calls.append("embeddings")
            data = [
                {"index": i, "embedding": _VECTORS.get(text, [0.0] * 8)}
                for i, text in enumerate(inputs)
            ]
            return httpx.Response(200, json={"data": data})
        ...
```
`_seed` will need a `source`-aware variant (or an extra param) so a perfmon-sourced
event can be inserted for `test_exemplars_exclude_perfmon`. This test is optional
belt-and-braces per RESEARCH § Q2 — the template-group assertion is strictly stronger.

---

## Shared Patterns

### Zero-network + filesystem isolation (applies to every new test)
**Source:** `tests/conftest.py:15-31` (`_isolate_dirs`) and `:34-60` (`_no_network`).
Both are `autouse` — **nothing needs importing or requesting**. `_isolate_dirs`
redirects `XDG_DATA_HOME`/`XDG_CONFIG_HOME` to `tmp_path` and clears `SIFT_*`, so
`sift new` in a CLI test creates its case under tmp. `_no_network` monkeypatches
`socket.socket.connect` to raise unless the test carries the `live` marker:
```python
    def _blocked(self: socket.socket, address: Any) -> None:
        raise RuntimeError(
            "Network access is forbidden in tests (zero-network-in-tests rule, "
            "see docs/TESTING.md). Inject a fake instead."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
```
No new conftest fixtures are needed for this phase.

### SQL construction discipline
**Source:** `store.py:601-609`, `store.py:327-338`, `store.py:355-380`.
**Apply to:** the `iter_event_summaries` exclusion. Interpolate placeholder *counts*
and module-constant SQL only; bind every value with `?`; annotate the f-string with
`# noqa: S608` **plus a comment saying why it is safe**. Never interpolate a value.

### Shared UTC path
**Source:** `base.py:97-102` + `base.py:105-114`.
**Apply to:** every adapter. `tz_override_for(relpath, self.tz_overrides)` →
`to_utc(dt, override_tz)` → `(dt_utc, confidence)`. Never hand-roll `replace(tzinfo=...)`.
Locked for `dssperfmon` by ADR 0012.

### Per-run adapter config
**Source:** `base.py:76-94` `ConfigurableAdapter` (`input_root`, `tz_overrides`,
`last_stats`), used at `dsserrors.py:155`. Subclassing it is what lets
`cli.py:282-303` deliver config and `cli.py:370` read `last_stats` back with zero
CLI edits (ADR 0006, RESEARCH § Q5).

### Parse coverage
**Source:** `base.py:38-53` `ParseStats` — `total_bytes`, `unknown_fallback_bytes`,
`event_count`, `notes`, plus the `coverage` property. No new counters needed for
PERF-02; `notes` is where ADR 0012's "bias recorded, not applied" disclosure and
D-16's column-drift note go.

---

## No Analog Found

None. Every file in this phase has a close in-repo analog — which is the phase's
main signal: `dssperfmon.py` is a structurally simpler `dsserrors.py`, and the only
genuinely novel work is the four-line exclusion in `store.py`.

## Metadata

**Analog search scope:** `src/sift/adapters/`, `src/sift/store.py`, `src/sift/models.py`, `tests/`
**Files read:** 11
**Pattern extraction date:** 2026-07-20
