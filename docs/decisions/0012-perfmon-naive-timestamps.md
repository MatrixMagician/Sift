# ADR 0012: `dssperfmon` records the PDH declared bias but does not apply it

**Status:** Accepted (implementation lands in Phase 12 / v1.2)
**Date:** 2026-07-20 (Phase 12 context; recorded per SPEC §10 open-question rule)
**Answers:** Should the `dssperfmon` adapter convert PDH-CSV sample timestamps to UTC using the
zone/offset declared in the file's own header — e.g. `(PDH-CSV 4.0) (Eastern Standard Time)(300)`?
Cross-refs SPEC.md §5.1 (`ts`/`ts_confidence` on the frozen `Event`), the D-05 timezone-handling
decision, ROADMAP.md Phase 12 criterion 2, and REQUIREMENTS.md PERF-02 / § Out of Scope.

**Supersedes:** the original Phase 12 CONTEXT.md decisions D-10 and D-11 ("trust the declared
numeric bias verbatim"; `ts_confidence = "exact"`), which were made before the reference artefacts
were measured.

## Context

A DSSPerformanceMonitor PDH-CSV declares a timezone in its header line:

```
"(PDH-CSV 4.0) (Eastern Standard Time)(300)","\\env-325602laio1use1\System\Total CPU",...
```

The obvious reading — and the one Phase 12's discussion originally locked — is that `300` is the
offset in minutes west of UTC, so `UTC = local + 300 min`. Roadmap criterion 2 was written in those
terms. Applying it looks like straightforward correctness: the artefact tells us its zone, so we
honour it.

Two facts, both established by measurement rather than inference, make that wrong here.

**1. The paired DSSErrors log carries naive local wall-clock timestamps and receives no offset.**

A real log line:

```
2026-04-07 12:39:18.794 [HOST:env-325602laio1use1][SERVER:CastorServer][PID:16234]...
```

There is no zone token and no offset. `dsserrors.py:116` calls `base.to_utc(dt, override_tz)`, and
with no `--tz` override `override_tz` is `None`, so `base.py:97-102` takes the naive branch:

```python
tz = ZoneInfo(override_tz) if override_tz else UTC
return dt.replace(tzinfo=tz).astimezone(UTC), "inferred"
```

`replace(tzinfo=UTC)` stamps the wall-clock time as UTC **verbatim — zero shift**. Every shipped
adapter (`dsserrors`, `eustack`, `genericlog`) behaves this way.

**2. Applying the bias to only one member of a matched pair destroys the join.**

| Artefact | Naive timestamp | Bias applied (+300) | Bias recorded only |
|---|---|---|---|
| CSV last sample | `04/07/2026 12:39:39.397` | `2026-04-07 17:39:39Z` | `2026-04-07 12:39:39Z` |
| Log denial activity | `2026-04-07 12:39:40.005` | `2026-04-07 12:39:40Z` | `2026-04-07 12:39:40Z` |

The roadmap's characterisation — the CSV ends ~6 s before the denial — holds *exactly*, and only in
the right-hand column. Applying the declared bias puts the CSV's final sample **five hours after**
the denial it precedes by six seconds. Phase 13's non-overlap hazard flag would then fire on the
very reference case v1.2 is built around.

Note the failure is not DST. The original Phase 12 risk note (D-13) worried about a 1-hour
EST/EDT skew, since `300` is the Eastern *standard* bias while the file spans April (EDT, 240).
The real defect is an order of magnitude larger and has a different cause: mixing offset-applied
and offset-naive timestamps in one correlation.

**3. The bias semantics are genuinely ambiguous anyway.**

Available documentation is not self-consistent about whether the PDH bias is the zone's *standard*
bias or the bias *active when the file was written*. A commonly cited example, `(GMT Standard
Time)(-60)`, implies an active bias; Hartford's `(300)` across an EDT date implies a standard bias.
We could not resolve this from sources. A field we cannot interpret reliably is a poor foundation
for a load-bearing timestamp conversion.

## Decision

**Record the declared zone and offset; do not apply them.**

1. Parse the naive sample timestamp (`MM/DD/YYYY HH:MM:SS.fff`) and route it through
   `base.to_utc(dt, override_tz)` with `override_tz` from `base.tz_override_for` — byte-for-byte
   the same call shape as `dsserrors`, `eustack` and `genericlog`. With no override this stamps
   the wall-clock time as UTC verbatim.
2. `ts_confidence` is whatever `base.to_utc` returns — `"inferred"` for the naive/no-override
   case. Not `"exact"`: nothing about the timestamp's true zone has been established.
3. The header's zone name and numeric bias are preserved in `Event.attrs` as `tz_name` and
   `tz_offset_min`, and disclosed once per file in `ParseStats.notes`. They are evidence, not
   inputs.
4. A `--tz glob=Zone` override continues to win, exactly as for every other adapter.

## Consequences

**Positive**

- The CSV and its paired log land on one timeline, because both are naive-stamped identically.
  Phase 13 can correlate them; the 6-second lead-in is preserved.
- One timestamp convention across all five adapters. No per-adapter special case to remember, and
  the shared `base.to_utc` seam stays the single UTC code path (D-05).
- The EST/EDT ambiguity becomes moot — no offset is applied under either reading.
- Nothing is discarded: the declared zone survives in `attrs`, so a future phase can revisit this
  without re-ingesting.
- No change to shipped v1.0/v1.1 behaviour, so no stored case is invalidated and the Phase 7
  golden-eval hashes are untouched.

**Negative / accepted**

- Stored perfmon `ts` values are **not** true UTC instants when the source host was not on UTC.
  They are consistent-with-the-log local wall-clock stamped as UTC. Any future feature that
  compares a perfmon timestamp against a genuinely UTC-anchored source must apply `tz_offset_min`
  from `attrs` itself. This is the real cost and it is deliberate: Sift correlates artefacts
  against each other, not against wall-clock truth.
- ROADMAP.md Phase 12 criterion 2 needed rewording — its original text specified that the declared
  zone/offset "yields UTC timestamps". Amended in the same change as this ADR.
- Two ingested artefacts from hosts in *different* zones would still misalign. Out of scope for
  v1.2 (PERFV2-02 covers multi-host); Phase 13's non-overlap flag is the guard.

## Alternatives considered

**Apply the bias as originally decided (D-10).** Literal compliance with criterion 2's wording,
but produces the 5-hour skew above and breaks the milestone's own reference case. Rejected.

**Apply a declared bias to the DSSErrors log as well, so the pair shifts together.** Internally
consistent, but requires editing shipped v1.0/v1.1 adapter behaviour, changes the stored `ts` of
every existing case, and risks the Phase 7 golden hashes — far outside Phase 12's boundary. The
log has no declared zone to read in any case. Rejected.

**Infer the offset by maximising CSV/log window overlap.** Explicitly forbidden by REQUIREMENTS.md
§ Out of Scope — it can invent an alignment that is not real. Rejected on principle, not cost.

**Map the Windows zone name to IANA and resolve DST per sample.** Needs a mapping table and makes
Sift infer rather than record. Also still leaves the log un-shifted, so it does not fix the join.
Rejected.
