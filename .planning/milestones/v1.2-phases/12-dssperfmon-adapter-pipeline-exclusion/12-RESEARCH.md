# Phase 12: `dssperfmon` Adapter & Pipeline Exclusion - Research

**Researched:** 2026-07-20
**Domain:** PDH-CSV parsing, adapter integration, cross-cutting pipeline exclusion
**Confidence:** HIGH (all load-bearing claims verified against real artefacts and shipped code)

## Summary

Phase 12 is a small phase with one large trap. The adapter itself is routine — it mirrors
`dsserrors.py` almost exactly (byte-line loop for offsets, `ConfigurableAdapter` subclass, one
`REGISTRY` line), and the exclusion is genuinely a one-method edit because
`CaseStore.iter_event_summaries()` really is the sole read seam feeding all four ranking-stage
consumers. D-06/D-07's analysis is confirmed correct by reading the code.

The trap is D-13, and it is worse than CONTEXT.md anticipated. The concern was framed as a 1-hour
DST risk. The actual risk is a **5-hour skew**, and it is caused not by DST but by D-10 itself.
The shipped `dsserrors` adapter routes naive log timestamps through `base.to_utc(dt, None)`, which
stamps them UTC verbatim with no offset applied. If the perfmon adapter applies the header's +300
minute bias as D-10 instructs, the two artefacts in the same case land 5 hours apart in UTC space
— destroying exactly the correlation Phase 13 exists to compute. The empirical evidence below is
unambiguous, and the recommendation is to **not apply the declared bias**, carrying it in `attrs`
as metadata instead. This contradicts D-10 and arguably roadmap criterion 2, so it needs a human
decision gate in the plan rather than a silent parser choice.

**Primary recommendation:** Build the adapter as a near-copy of `dsserrors.py`; treat PDH sample
timestamps as naive and pass them through `base.to_utc(dt, override_tz)` **without** applying the
header bias (record it in `attrs` instead); implement the exclusion as a single
`WHERE source NOT IN (...)` in `iter_event_summaries` driven by a module constant; make criterion
4's guard a CLI-level byte-comparison test that needs no embeddings at all.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PDH header sniff | Adapter (`dssperfmon.py`) | — | `base.read_head` over decompressed bytes; adapters own their own sniff |
| Sample-row → `Event` | Adapter | — | Adapter self-containment (SPEC §5.2) |
| Byte-offset accounting | Adapter, via `genericlog.byte_lines` | — | Determinism contract lives on the raw byte stream |
| UTC normalisation | `base.to_utc` (shared) | Adapter supplies the naive `datetime` | D-05 convention: one shared tz path for every adapter |
| Parse coverage | `base.ParseStats` | Adapter populates | Existing machinery; no new types needed |
| Ranking exclusion | Store (`iter_event_summaries`) | — | `store.py` owns all SQL; one seam, not four |
| Citation retrieval | Store (`iter_event_rows`, `get_events`) | — | Must stay unfiltered (D-08) |

## Priority Question 1: DST / offset semantics (D-13) — RESOLVED, and the answer changes D-10

### Evidence gathered

**PDH-CSV header (verified, `head -c` on the real file):**

```
"(PDH-CSV 4.0) (Eastern Standard Time)(300)","\\env-325602laio1use1\System\Total CPU",...
```

**CSV first and last sample rows [VERIFIED: real artefact]:**

| | Timestamp |
|---|---|
| First data row | `04/02/2026 19:21:38.236` |
| Last data row | `04/07/2026 12:39:39.397` |
| Row count | 13,597 lines = 1 header + 13,596 samples ✓ matches CONTEXT.md |

**Paired DSSErrors log [VERIFIED: real artefact]:**

| | Timestamp |
|---|---|
| First log line | `2026-04-07 12:39:18.794` |
| Denial activity begins | `2026-04-07 12:39:40.005` |
| Last log line | `2026-04-07 12:39:52.291` |

The log is a narrow ~34-second slice around the incident. Log timestamps are naive local
wall-clock — no offset suffix, no `Z`, no zone name anywhere on the line.

### The alignment test

Comparing the two files **at face value, with no offset applied to either**:

- CSV last sample: `12:39:39.397`
- Denial banner (per REQUIREMENTS.md § Reference Data): `12:39:45`
- Delta: **5.6 seconds**

This is the roadmap's own "the CSV ends 6 s before the denial banner" claim, and it **holds exactly
— but only under the reading that neither file's timestamps are shifted**. [VERIFIED: direct
comparison of both artefacts]

### The 5-hour finding

`src/sift/adapters/dsserrors.py:116` calls `to_utc(dt, override_tz)`. With no `--tz` override,
`base.to_utc` (`base.py:97-102`) does:

```python
tz = ZoneInfo(override_tz) if override_tz else UTC
return dt.replace(tzinfo=tz).astimezone(UTC), "inferred"
```

A naive local timestamp is therefore **stamped UTC verbatim, offset 0**, with
`ts_confidence="inferred"`. The Hartford denial lands in the store at `12:39:45Z`.

If the perfmon adapter applies D-10's `UTC = local + 300 min`, the CSV's last sample lands at
`17:39:39Z`. The CSV would then appear to end **5 hours after** the denial it precedes by 6
seconds. Phase 13's window overlap check would fire a non-overlap flag on a perfectly aligned
pair, or worse, silently correlate nothing.

**This is not a DST problem.** DST would be a 1-hour discrepancy on top. The 5-hour skew arises
purely from applying an offset to one member of a pair whose other member gets none.

### PDH format semantics [CITED / partially inconclusive]

Independent sources confirm the structural facts:

- The bias is stored **only in the header**, so the format "has no way to indicate when the local
  timezone offset changes during the recording of the file", producing duplicated timestamps
  across a DST transition [CITED: digitalflapjack.com/blog/be-wary-of-timestamps-for-windows-performance-data/]
- Windows `Bias` is defined as UTC − local in minutes [CITED: learn.microsoft.com TIME_ZONE_INFORMATION]

The sign convention is consistent with 300 = UTC−5. Whether PDH writes the *standard-time* bias or
the *active-at-write* bias is **not authoritatively resolvable** from available sources: the cited
blog's `(GMT Standard Time)(-60)` example implies an active bias, while the Hartford file declares
300 (EST) across a window entirely in EDT (240), implying a standard bias. [ASSUMED — sources
conflict]

This ambiguity is itself the strongest argument for the recommendation: **an offset Sift cannot
interpret unambiguously must not be applied silently.**

### Recommendation (contradicts D-10 — needs a human gate)

**Option A (recommended).** Treat the PDH sample timestamp as naive and route it through
`base.to_utc(dt, tz_override_for(relpath, self.tz_overrides))` exactly as `dsserrors` does. Do
**not** apply the header bias arithmetically. Record it as metadata:

- `attrs["tz_name"] = "Eastern Standard Time"` (verbatim header zone string)
- `attrs["tz_offset_min"] = "300"` (declared bias, parsed but unapplied)
- `ParseStats.notes` entry disclosing that the declared bias was recorded, not applied

Consequences:
- CSV and log align to the same 6-second delta the roadmap asserts ✓
- A `--tz glob=America/New_York` override shifts **both** files consistently ✓
- D-13's DST question becomes moot — no offset is applied, so EST-vs-EDT never arises ✓
- Phase 13 retains the declared bias in `attrs` if it ever needs a true-UTC anchor ✓
- `ts_confidence = "inferred"`, matching `dsserrors` [see note below]

**Option B (as D-10 literally specifies).** Apply +300 min. Produces a 5-hour skew against every
other adapter in the same case. **Do not do this.**

**Option C.** "Fix" `dsserrors` to apply a real zone. Out of scope — it would change v1.0/v1.1
timestamps for every existing case and break the milestone gate.

**Tension to resolve at plan time:** roadmap criterion 2 says "the header's declared zone/offset
*yields UTC timestamps* via `base.to_utc` with `ts_confidence` recorded". Option A satisfies the
`to_utc` routing and the `ts_confidence` recording, but not the natural reading of "the declared
offset yields UTC". D-11's `ts_confidence = "exact"` also becomes wrong under Option A —
"inferred" is the honest value, and it matches `dsserrors`. **The planner must add a
`checkpoint:human-verify` task before the parser's timestamp logic is written**, presenting this
evidence. This is a decision about what "correct" means, not an implementation detail.

**Also note for Phase 13:** because PDH carries a single header bias, a file spanning a fall-back
DST transition contains duplicate wall-clock timestamps. Phase 12 is unaffected (`event_id` derives
from byte offset, so duplicate timestamps still yield distinct events), but the canonical
`ORDER BY ts` becomes non-injective across the transition. Worth a `ParseStats.notes` disclosure if
detected cheaply; flagging is Phase 13's PERF-05. [VERIFIED: format limitation confirmed by cited
source; the Hartford window 04/02–04/07 contains no transition, so this is latent not active]

## Priority Question 2: Cluster byte-identity test design (criterion 4 / D-09)

### The lazy path: no embeddings needed

`cli.py:583` shows `sift show clusters` renders `store.query_clusters()` **only if that table is
non-empty**, else it falls back to `store.query_template_groups()` (`cli.py:599`). The clusters
table is populated by `sift analyze`, not `sift ingest`.

So a test that runs `sift ingest` + `sift show clusters` — with no `analyze` — exercises the
template-group path with **zero LLM or embedding involvement**. That satisfies criterion 4's
literal wording (`sift show clusters` byte-identical) at CLI level, socket-blocked, fast.

This is sound rather than merely convenient: `cluster.py:113 _exemplar_messages` derives its input
from template groups. If the `template_groups` table is byte-identical, every downstream stage is
identical **by construction**. Asserting at the template-group level is the stronger, cheaper
assertion.

### Recommended three-test structure

| Test | Level | What it asserts |
|------|-------|-----------------|
| `test_cluster_output_identical_with_and_without_perfmon` | CLI (`CliRunner`) | Ingest case A (log only) and case B (log + CSV); assert `sift show clusters` stdout is byte-identical |
| `test_template_groups_identical_with_and_without_perfmon` | Unit (store) | Same two cases; assert `store.query_template_groups()` returns equal lists |
| `test_cluster_exemplars_exclude_perfmon` | Unit (fake embeddings) | Optional belt-and-braces: run `cluster_and_label` with the existing fake and assert no perfmon message reaches an exemplar |

### Concrete helpers to reuse

- `tests/conftest.py::_isolate_dirs` — autouse, redirects XDG so case paths are tmp-scoped. Nothing
  extra needed for case creation.
- `tests/conftest.py::_no_network` — autouse socket block. Confirms the CLI-level tests cannot
  accidentally reach a server.
- `tests/test_cluster.py:78 _embed_handler` + `_client(...)` — the existing `httpx.MockTransport`
  fake ("Every embedding and chat call is faked with `httpx.MockTransport` — no socket", per the
  module docstring). `_VECTORS` maps text → vector with a `[0.0] * 8` default. Use this **only**
  for the optional third test.
- `tests/test_cli.py` — the established `CliRunner` invocation patterns for `sift new` / `ingest` /
  `show`. This is where the criterion-4 test belongs.

### Trap to avoid

Do **not** assert on the two cases' `case.db` files being byte-identical — case B legitimately
contains the perfmon events. Assert on the *derived* artefacts (`show clusters` stdout,
`query_template_groups()`), which is what criterion 4 actually claims.

## Priority Question 3: Exclusion implementation shape — D-06/D-07 CONFIRMED

### Seam verification

`iter_event_summaries` (`store.py:631`) is confirmed as the sole ranking-path read seam. Its four
consumers, checked individually:

| Consumer | Exclusion correct? | Reasoning |
|----------|-------------------|-----------|
| `pipeline/dedup.py:102` `rebuild_template_groups` | ✅ Yes | This is the point of the phase |
| `pipeline/cluster.py:113` `_exemplar_messages` | ✅ Yes | Inherits from dedup output |
| `pipeline/hypothesise.py:191` | ✅ Yes | Perfmon rows must not consume prompt budget |
| `eval/runner.py:63` `_cluster_exemplar_texts` | ✅ **Yes — verified harmless** | Reads the full stream only to resolve `wanted` (a set of exemplar event IDs drawn from `query_clusters()` → `query_template_groups()`). Since perfmon events can never *be* exemplars once dedup excludes them, filtering removes only rows that would never match `wanted`. No behaviour change. |

**No consumer of `iter_event_summaries` needs perfmon rows.** [VERIFIED: read all four call sites]

`pipeline/salience.py:126 rank_clusters` consumes `Cluster`/`TemplateGroup` only — inherits the
exclusion transitively, confirming D-06. No edit there.

### Unconditional vs parameterised

**Unconditional**, per D-07. The exclusion is a property of the source kind, not the caller. A
`include_excluded: bool = False` parameter is exactly the kind of speculative flexibility that lets
a future caller silently reintroduce the regression criterion 4 guards against. If a legitimate
need for unfiltered summaries ever appears, that's the moment to add it — and it will be a visible
change, not a default that drifted.

### Where the constant lives

Put it in `store.py` as a module-level constant beside the other SQL constants:

```python
# Perfmon samples are observations, not diagnostics: they are excluded from
# every ranking stage (dedup/embed/cluster/salience) by source kind, but stay
# fully retrievable by event_id for citation (PERF-03).
EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon"})
```

Rationale over a shared module: `store.py` already owns all SQL and the constant's only consumer is
one SQL string. A new module for one frozenset is an abstraction with one implementation. The
placeholder list must be `?`-bound to stay consistent with the `# noqa: S608` convention already
used throughout the file:

```python
placeholders = ",".join("?" for _ in sorted(EXCLUDED_FROM_RANKING))
cursor = self._conn.execute(
    "SELECT event_id, ts, severity, message FROM events "  # noqa: S608
    f"WHERE source NOT IN ({placeholders}) "
    "ORDER BY ts IS NULL, ts, source_file, line_start",
    tuple(sorted(EXCLUDED_FROM_RANKING)),
)
```

`sorted()` keeps the parameter order deterministic (a frozenset's iteration order is not
guaranteed stable across builds).

### The D-08 guard

`iter_event_rows` (`store.py:644`) sits immediately below `iter_event_summaries` and reads almost
identically. Both stream from a cursor, both use the same `ORDER BY`. A future tidy-up that factors
them into a shared helper would silently break citation. The plan must include a test asserting
`iter_event_rows` still yields perfmon rows, and a comment on `iter_event_rows` stating the
asymmetry is deliberate.

`get_events` (`store.py:~600`) takes explicit IDs and needs no change.

## Priority Question 4: Byte-offset + stdlib `csv` integration (D-20)

### The pattern to mirror

`dsserrors.py:259-261` [VERIFIED: read source]:

```python
for bline in byte_lines(stream, b"\n", b"", unit=1):
    line_offset = offset
    offset += len(bline)  # every byte counted, newline too
```

`byte_lines` (`genericlog.py:227`) signature: `(stream, nl, initial, unit=1) -> Iterator[bytes]`,
yields terminator-included byte lines with a `MAX_EVENT_BYTES` force-split.

### Specified loop shape

```python
with open_bytes(path) as stream:
    offset = 0
    header_columns: list[str] | None = None
    for bline in byte_lines(stream, b"\n", b"", unit=1):
        line_offset = offset
        offset += len(bline)          # ALL bytes, terminator included
        text = bline.decode("utf-8", errors="replace").rstrip("\r\n")
        if not text:
            continue                  # blank line: offset already advanced
        row = next(csv.reader([text]))   # single-row parse, decoded text only
        if header_columns is None:
            header_columns = row      # header is not an event (D-01)
            continue
        yield self._row_event(row, header_columns, line_offset, ...)
```

The load-bearing points:
1. `offset += len(bline)` happens **before** any decoding or parsing, so no parse outcome can
   perturb it.
2. `csv.reader([text])` parses exactly one already-decoded row. `csv`'s own file iteration never
   owns the read loop.
3. Blank lines advance the offset then `continue` — PDH emits a trailing newline, so this matters.

### The embedded-newline trap

A quoted CSV field may in principle contain a literal newline. `byte_lines` splits on `b"\n"`
unconditionally, so such a record would be split across two byte lines. Each fragment then hits
`csv.reader([text])` on unbalanced quotes.

Behaviour if it occurs: `csv.reader` does **not** raise on unbalanced quotes in a single-row parse
— it returns the fragment with the quote consumed, yielding a wrong column count. That lands
squarely in D-16's column-count-mismatch path: both fragments become `severity="unknown"` events
with `raw` preserved verbatim and a `ParseStats.notes` entry. **Nothing disappears, offsets stay
correct, determinism holds.** [VERIFIED: `csv` module quoting behaviour; ASSUMED that PDH never
emits embedded newlines — counter paths are `\\host\Object(Instance)\Counter`, and neither Windows
object names nor instance names may contain a newline]

Recommended handling: none. The D-16 path already covers it correctly. Do not add
multi-line-record reassembly — that is speculative complexity for a case the format cannot produce,
and it would compromise the offset contract. Add one test with a synthetic embedded-newline row
asserting the two unknown events and the preserved bytes, so the behaviour is pinned rather than
accidental.

### Column-count note

The header row and data rows must be compared on parsed column count. The Hartford header has 23
fields (1 timestamp label + 22 counters) [VERIFIED 2026-07-20 by parsing the real artefact and the
committed fixture with `csv.reader`: both yield 23 fields per row. An earlier count of 23 counters /
24 fields, recorded in CONTEXT.md and REQUIREMENTS.md, was off by one and has been corrected]. `header_columns[0]` is the `(PDH-CSV 4.0) (Zone)(bias)` string, not a counter —
parse the zone/bias from it, do not treat it as column 0 of the counter set.

## Priority Question 5: Ingest orchestration touchpoints — no `cli.py` change needed

`cli.py:282-303` [VERIFIED: read source]:

```python
file_adapter = adapters.detect(path, relpath, overrides)
...
if isinstance(file_adapter, ConfigurableAdapter):
    file_adapter.input_root = input_dir
    file_adapter.tz_overrides = dict(config.timezones)
```

and `cli.py:370` reads back `file_adapter.last_stats`. Everything is `isinstance`-narrowed on
`ConfigurableAdapter` — **no adapter is named individually** except one `GenericLogAdapter` branch
at `cli.py:298` (a genericlog-specific concern that a perfmon adapter does not enter).

`adapters/__init__.py` confirms the self-containment claim in its own docstring: "adding adapter #5
must require exactly a new module plus one registration line here — nothing else changes."
[VERIFIED: read source]

### Adapter-name enumeration audit

| Site | Behaviour with a 5th adapter |
|------|------------------------------|
| `adapters.get()` KeyError message | Auto-derives from `sorted(REGISTRY)` — self-updating ✓ |
| `parse_adapter_overrides` ValueError | Same ✓ |
| `cli.py:216` unknown-adapter error | Same ✓ |
| `detect()` sniff loop | Iterates `REGISTRY.values()` — self-updating ✓ |
| `doctor` | No adapter enumeration found ✓ |

**One real risk:** `detect()` scores **every** registered adapter against **every** file. Adding
`dssperfmon` means its `sniff()` now runs against every DSSErrors log, thread dump and journald
export in every existing test case. If the sniff is not tightly anchored on the literal
`(PDH-CSV 4.0)` prefix it could tie or win against an existing adapter and change v1.0/v1.1
detection. D-18's "high confidence on the literal token, 0.0 otherwise" is exactly right — and
`tests/test_adapters_detect.py` is the existing regression guard that must stay green.

Recommended sniff: return `0.95` iff `read_head(path)` starts with `b'"(PDH-CSV 4.0)'`, else `0.0`.
Anchored prefix check, no regex, no scanning — satisfies the no-ReDoS discipline trivially.

## Priority Question 6: Test fixture strategy (D-17)

### Where fixtures live

`tests/fixtures/<adapter-name>/` is the established convention (`tests/fixtures/dsserrors/`,
`eustack/`, `journald/`, `mcm/`). Create `tests/fixtures/dssperfmon/`.

`tests/test_dsserrors.py:19` establishes the access pattern:
```python
FIXTURES = Path(__file__).parent / "fixtures" / "dsserrors"
```

### Two fixture styles, both already in use

| Style | Used for | Example |
|-------|----------|---------|
| Checked-in file under `tests/fixtures/` | Realistic multi-row content worth reading | `fixtures/mcm/hartford_deny_slice.log` |
| Inline `write(tmp_path, name, body)` helper | Small targeted edge cases | `test_dsserrors.py:58` `path.write_bytes(data)` |

### Recommended fixture set

**Checked-in (`tests/fixtures/dssperfmon/`):**

1. `hartford_deny_slice.csv` — a cut of the real file: the verbatim header + ~20 sample rows
   spanning first and last timestamps. Mirrors the `mcm/hartford_deny_slice.log` precedent exactly.
   Drives sniff, parse, idempotence, tz, and the criterion-4 pairing test.

**Synthetic, inline via a local `write()` helper (D-17 — the real file has zero malformed cells):**

2. Blank counter cell → `severity="unknown"`, `unparsed_columns` in `attrs` (D-14)
3. Non-numeric counter cell (e.g. `" "` or `"N/A"`) → same path (D-14)
4. Unparseable timestamp → `severity="unknown"`, `ts=None`, `ts_confidence="missing"` (D-15)
5. Column count ≠ header → `severity="unknown"` + `ParseStats.notes` (D-16)
6. Header with no parseable bias → `ts_confidence="inferred"` + notes disclosure (D-11)
7. Embedded newline in a quoted field → two unknown events, offsets intact (Q4 trap)

Inline is right for 2–7: each is one or two lines of CSV whose whole point is a single malformed
cell. A checked-in file would hide the defect being tested.

### Also needed

8. A no-perfmon twin of fixture 1's case for the criterion-4 pairing — this is just the existing
   `fixtures/mcm/hartford_deny_slice.log` reused, no new fixture required.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV field splitting | Regex or `str.split(",")` | stdlib `csv.reader` | Counter paths contain `\`, `(`, `)` and are quoted; naive splitting breaks on any quoted comma |
| Byte-line iteration | A new splitter | `genericlog.byte_lines` | Already handles `MAX_EVENT_BYTES` force-split and unit alignment; reused by `dsserrors` |
| UTC normalisation | `datetime.replace(tzinfo=...)` inline | `base.to_utc` | D-05 single shared tz path; `--tz` override support comes free |
| Decompression | `gzip`/`zstandard` calls in the adapter | `base.open_bytes` | Magic-byte detection, concatenated gzip members, zstd frame handling |
| `event_id` | Any hashing | `models.event_id(source_file, byte_offset)` | Frozen determinism contract |
| Parse coverage | New counters | `base.ParseStats` | `coverage` property already exists |
| Windows zone → IANA | A mapping table | Nothing — record the string | D-10; and under the Q1 recommendation no zone resolution happens at all |
| Per-stage exclusion | Filters in dedup/cluster/hypothesise/eval | One `WHERE` in `iter_event_summaries` | Four filters is four chances to drift out of sync |

## Common Pitfalls

### Pitfall 1: Applying the header bias (the 5-hour skew)
**What goes wrong:** Perfmon events land 5 hours from the log events they should align with.
**Why it happens:** D-10 says apply it; `dsserrors` applies nothing. The asymmetry is invisible in
a single-adapter test.
**How to avoid:** See Q1. Add a test ingesting **both** artefacts into one case and asserting the
CSV's last sample `ts` precedes the denial `ts` by under 10 seconds. This is the only test that
catches it.
**Warning signs:** Every perfmon test passing while Phase 13 correlation returns nothing.

### Pitfall 2: Tidying `iter_event_rows` and `iter_event_summaries` together
**What goes wrong:** Perfmon samples vanish from `sift show events` and from citation.
**Why it happens:** The two methods are adjacent and near-identical; the asymmetry looks like an
oversight.
**How to avoid:** Comment on both stating the asymmetry is deliberate (D-08); test that
`iter_event_rows` still yields perfmon rows.

### Pitfall 3: Sniff collateral damage
**What goes wrong:** `detect()` now runs a 5th sniff on every file in every existing case; a loose
sniff changes v1.0/v1.1 adapter selection.
**How to avoid:** Anchored literal prefix check only. `tests/test_adapters_detect.py` must stay
green — treat it as a regression gate, not an optional check.

### Pitfall 4: `csv` owning the read loop
**What goes wrong:** `event_id` determinism breaks silently; re-ingest stops being idempotent.
**How to avoid:** The Q4 loop shape. Test: ingest twice, assert zero new events (criterion 1).

### Pitfall 5: 13,596 events in one file
**What goes wrong:** Nothing in Phase 12, but `attrs` carries 23 keys per event × 13,596 rows.
**How to avoid:** Nothing to do here — but note it for Phase 14's fact-block cap (already deferred).
Do not downsample (REQUIREMENTS.md § Out of Scope).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 |
| Config file | `pyproject.toml` (markers: `live`, `perf`, `packaging`) |
| Quick run command | `uv run pytest tests/test_dssperfmon.py -x` |
| Full suite command | `uv run pytest` |
| Gate | `uv run ruff check && uv run pyright && uv run pytest` |

### Success Criteria → Test Map

| Criterion | Behaviour | Test Type | Command | File |
|-----------|-----------|-----------|---------|------|
| 1 | One event per sample row, deterministic `event_id` | unit | `pytest tests/test_dssperfmon.py::test_one_event_per_sample_row -x` | ❌ Wave 0 |
| 1 | Re-ingest adds zero new events | integration (CLI) | `pytest tests/test_cli.py::test_ingest_perfmon_idempotent -x` | ❌ Wave 0 |
| 2 | `(PDH-CSV 4.0)` sniffed with no `--adapter` | unit | `pytest tests/test_dssperfmon.py::test_sniff_pdh_header -x` | ❌ Wave 0 |
| 2 | Existing adapter detection unchanged | regression | `pytest tests/test_adapters_detect.py -x` | ✅ exists |
| 2 | Timestamps → UTC via `base.to_utc`, `ts_confidence` recorded | unit | `pytest tests/test_dssperfmon.py::test_timestamp_utc_and_confidence -x` | ❌ Wave 0 |
| 2 | **CSV/log alignment** (Pitfall 1 guard) | integration | `pytest tests/test_dssperfmon.py::test_csv_aligns_with_paired_log -x` | ❌ Wave 0 |
| 2 | `--tz` override still wins | unit | `pytest tests/test_dssperfmon.py::test_tz_override_applies -x` | ❌ Wave 0 |
| 3 | Blank/non-numeric cell → `severity="unknown"` | unit (synthetic) | `pytest tests/test_dssperfmon.py -k unknown_fallback -x` | ❌ Wave 0 |
| 3 | Unparseable timestamp → `ts=None`, event survives | unit (synthetic) | `pytest tests/test_dssperfmon.py::test_bad_timestamp_survives -x` | ❌ Wave 0 |
| 3 | Column-count drift → unknown + notes | unit (synthetic) | `pytest tests/test_dssperfmon.py::test_column_drift_unknown -x` | ❌ Wave 0 |
| 3 | Coverage reflects unknown bytes | unit | `pytest tests/test_dssperfmon.py::test_parse_coverage -x` | ❌ Wave 0 |
| 4 | **`sift show clusters` byte-identical ± CSV** | integration (CLI) | `pytest tests/test_cli.py::test_cluster_output_identical_with_and_without_perfmon -x` | ❌ Wave 0 |
| 4 | `template_groups` identical ± CSV | unit (store) | `pytest tests/test_store.py::test_template_groups_exclude_perfmon -x` | ❌ Wave 0 |
| 4 | Exemplars never perfmon | unit (fake embed) | `pytest tests/test_cluster.py::test_exemplars_exclude_perfmon -x` | ❌ Wave 0 |
| 5 | `iter_event_rows` still yields perfmon | unit (store) | `pytest tests/test_store.py::test_iter_event_rows_unfiltered -x` | ❌ Wave 0 |
| 5 | `get_events` by `event_id` returns perfmon | unit (store) | `pytest tests/test_store.py::test_get_events_returns_perfmon -x` | ❌ Wave 0 |
| 5 | `sift show events` lists perfmon rows | integration (CLI) | `pytest tests/test_cli.py::test_show_events_includes_perfmon -x` | ❌ Wave 0 |
| — | Whole v1.0/v1.1 suite unaffected | regression | `uv run pytest` | ✅ exists |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_dssperfmon.py tests/test_store.py tests/test_adapters_detect.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** `uv run ruff check && uv run pyright && uv run pytest` all clean before
  `/gsd-verify-work`. Because this phase edits shipped pipeline code, the **full** suite (not a
  subset) is the merge gate for every wave, not just the last.

### Wave 0 Gaps

- [ ] `tests/test_dssperfmon.py` — new file, covers PERF-01/PERF-02
- [ ] `tests/fixtures/dssperfmon/hartford_deny_slice.csv` — verbatim header + ~20 real sample rows
- [ ] New cases appended to `tests/test_store.py` — exclusion + unfiltered-citation pair (PERF-03)
- [ ] New cases appended to `tests/test_cli.py` — criterion 4 byte-identity, criterion 5 show events
- [ ] Optional case in `tests/test_cluster.py` reusing `_embed_handler` (`test_cluster.py:78`)

No framework install needed. No new conftest fixtures needed — `_isolate_dirs` and `_no_network` are
autouse and sufficient.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface; local CLI |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Filesystem permissions only |
| V5 Input Validation | **yes** | PDH-CSV is untrusted customer input. stdlib `csv`; anchored non-backtracking prefix sniff; `MAX_EVENT_BYTES` force-split via `byte_lines`; every malformed input degrades to `severity="unknown"` rather than raising |
| V6 Cryptography | no | `event_id` uses `hashlib.sha256` for determinism, not security |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `source` value | Tampering | `?`-bound placeholders in the `NOT IN` clause; the constant is module-owned, never user-supplied |
| ReDoS via crafted counter names | DoS | No regex over row content; anchored literal prefix sniff only (project no-ReDoS discipline) |
| Memory exhaustion via a huge single line | DoS | `byte_lines` `MAX_EVENT_BYTES` force-split, already shipped |
| Decompression bomb (`.csv.gz`) | DoS | Existing `base.open_bytes` behaviour — unchanged by this phase, no new exposure |
| Network egress | Info disclosure | None added; the adapter is pure parsing. `_no_network` conftest guard enforces it in tests |

## Project Constraints (from CLAUDE.md)

- Python 3.12+, `uv`-managed; boring technology (stdlib `csv` qualifies, no new dependency needed)
- "Done" = `ruff check` + `pyright` + `pytest` all clean
- Type hints everywhere; pyright strict
- British English in docs and user-facing strings (`normalise`, `analyse`, `behaviour`)
- Zero network egress; never call the network in tests
- `store.py` owns all SQL; pipeline modules stay SQL-free, typer-free, print-free
- Adapter self-containment: new module + one `REGISTRY` line — deliberately broken once here for
  the exclusion, confined to the single seam
- Determinism: `event_id = sha256(source_file, byte_offset)[:16]`; idempotent re-ingest
- Nothing disappears silently: unparseable regions → `severity="unknown"`
- Anchored, linear-scan regexes only (no ReDoS)
- Record open-question decisions in `docs/decisions/` — **the Q1 timestamp resolution warrants an
  ADR**, since it overrides a locked CONTEXT.md decision

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PDH never emits embedded newlines inside quoted fields | Q4 | Low — the D-16 unknown path handles it correctly if it occurs; pinned by test |
| A2 | Whether the PDH bias is standard-time or active-at-write is unresolved (sources conflict) | Q1 | None under the recommendation — the ambiguity *is* the argument for not applying it |
| A3 | The denial banner is at `12:39:45` (taken from REQUIREMENTS.md; the log slice shows denial activity from `12:39:40.005` and ends `12:39:52.291`) | Q1 | Low — the alignment conclusion holds for any banner time in the observed 12:39:40–12:39:52 range |
| A4 | pytest 9.1.1 (from project memory, not re-verified this session) | Validation | Cosmetic |

## Open Questions

1. **Does the header bias get applied? (D-10 vs the 5-hour skew)**
   - What we know: applying it puts perfmon 5 hours from every other adapter in the same case; not
     applying it reproduces the roadmap's own 6-second alignment claim exactly.
   - What's unclear: whether roadmap criterion 2's "declared offset yields UTC timestamps" is a
     hard requirement or a description written before the `dsserrors` asymmetry was noticed.
   - Recommendation: **Option A (do not apply; record in `attrs`)**, gated behind a
     `checkpoint:human-verify` task before the timestamp logic is written. Write an ADR recording
     whichever way it goes.

2. **`ts_confidence` value under Option A**
   - D-11 specifies `"exact"`. Under Option A the honest value is `"inferred"` — matching
     `dsserrors` for the same naive-timestamp situation.
   - Recommendation: `"inferred"`, decided alongside Q1.

## Sources

### Primary (HIGH confidence)
- `/home/oliverh/Downloads/hartford/hartford_Linux_DenyDSSPerformanceMonitor16234.csv` — header,
  first/last sample, row count, column structure
- `/home/oliverh/Downloads/hartford/hartford_linux_deny_.log` — timestamp format, denial window,
  file span
- `src/sift/adapters/base.py` — `to_utc`, `ConfigurableAdapter`, `ParseStats`, `open_bytes`
- `src/sift/adapters/dsserrors.py` — byte-offset loop, tz path
- `src/sift/adapters/__init__.py` — `REGISTRY`, `detect`, `SNIFF_THRESHOLD`
- `src/sift/store.py:631,644` — the two seams
- `src/sift/eval/runner.py:45-70` — `_cluster_exemplar_texts`
- `src/sift/cli.py:282-303,368-370,583-599` — adapter orchestration, `show clusters` fallback
- `src/sift/adapters/genericlog.py:227` — `byte_lines`
- `tests/conftest.py`, `tests/test_cluster.py:78`, `tests/test_dsserrors.py:19,58`

### Secondary (MEDIUM confidence)
- [Be wary of timestamps for Windows Performance Monitor data](https://digitalflapjack.com/blog/be-wary-of-timestamps-for-windows-performance-data/) — PDH header-only bias, DST duplicate-timestamp limitation
- [TIME_ZONE_INFORMATION (timezoneapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/timezoneapi/ns-timezoneapi-time_zone_information) — Windows `Bias` = UTC − local, in minutes

## Metadata

**Confidence breakdown:**
- Timestamp/alignment finding: HIGH — direct measurement of both real artefacts plus source read of
  `base.to_utc`
- Exclusion seam: HIGH — all four consumers read individually
- Test design: HIGH — `show clusters` fallback and the existing fakes read directly
- PDH bias semantics (standard vs active): LOW — sources conflict; recommendation designed not to
  depend on it

**Research date:** 2026-07-20
**Valid until:** 2026-08-19 (stable — internal codebase and a frozen file format)
