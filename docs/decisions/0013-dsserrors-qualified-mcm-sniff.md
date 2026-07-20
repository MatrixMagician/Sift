# ADR 0013: `dsserrors` sniff markers qualify "MCM" rather than matching it bare

**Status:** Accepted (implemented in Phase 12 plan 12-03 / v1.2)
**Date:** 2026-07-20
**Answers:** How should `DsserrorsAdapter.sniff` recognise MicroStrategy MCM content now that a second
adapter (`dssperfmon`, PERF-01) parses artefacts from the same product and therefore shares its
domain vocabulary? Cross-refs SPEC.md §5.2 (adapter self-containment), INGST-03 (detection),
ROADMAP.md Phase 12 criterion 2, and REQUIREMENTS.md PERF-01 / PERF-05.

**Changes shipped v1.0 behaviour.** `_SNIFF_STRINGS` in `src/sift/adapters/dsserrors.py` has been a
stable detection input since Phase 5. This ADR exists because that input changed.

## Context

Registering `DssperfmonAdapter` as the fifth adapter turned
`tests/test_adapters_detect.py::test_phase5_no_cross_collision` red on its very first run against
the new PDH-CSV fixture:

```
assert claimants == ['dssperfmon']
AssertionError: assert ['dsserrors', 'dssperfmon'] == ['dssperfmon']
```

Scores on `tests/fixtures/dssperfmon/hartford_deny_slice.csv`:

| Adapter | Sniff |
|---|---|
| `dssperfmon` | 0.95 |
| `dsserrors` | **0.80** |
| `genericlog`, `journald`, `eustack` | 0.00 |

### The collision mechanism

`_SNIFF_STRINGS` contained the bare substring `"MCM"`, matched with `s in head` against the first
64 KB of decompressed content. A PDH-CSV header line enumerates every sampled counter path, and at
byte 941 of the fixture:

```
"\\env-325602laio1use1\MicroStrategy Server Jobs(CastorServer)\Total MCM Denial"
```

`Total MCM Denial` is **the very counter PERF-05 tracks** (ROADMAP v1.2 records it reading 0 across
all 13,596 Hartford deny samples). It is emitted by DSSPerformanceMonitor by default. This is
therefore not a fixture artefact and not incidental: **every real perfmon CSV collides**, permanently.

More generally, a bare three-letter substring matched against 64 KB of arbitrary content is an
inherently weak signature — any file containing those letters anywhere scored 0.8.

### What was, and was not, broken

Routing was **already correct**. `detect()` picks a strict unique maximum, and 0.95 > 0.80, so PDH
CSVs routed to `DssperfmonAdapter` regardless. No existing fixture changed adapter. The failing
property was the stricter sole-claimant invariant: exactly one domain adapter clears
`SNIFF_THRESHOLD` on each domain fixture.

The residual risk that made this worth fixing rather than tolerating: **a PDH-CSV whose header does
not match `dssperfmon`'s anchored `"(PDH-CSV 4.0)` prefix** — truncated, byte-shifted, or a variant
PDH version — scores `dssperfmon 0.00` and `dsserrors 0.80`. It would then be silently parsed as a
DSSErrors log rather than degrading to the `genericlog` fallback, which is exactly the
misrouting-hijack class the invariant exists to gate (threat T-12-11).

## Decision

Replace the bare `"MCM"` marker with two qualified, DSSErrors-only spellings:

```python
_SNIFF_STRINGS = (
    "Contract Request Failed",
    "Info Dump",
    "AvailableMCM",
    "MCM Settings",
    "I-Server",
)
```

Both are attested in real logs (`AvailableMCM=` appears in the memory-contract dumps;
`MCM Settings:` heads the configuration block), and neither is a legal substring of any PDH counter
path. Note that the perfmon spelling is `Total MCM Denial` with a capital D — `"MCM denial"` was
rejected as a candidate marker precisely because case-sensitivity would have been the only thing
separating it from a collision, which is too fragile to rely on.

## Evidence the bare marker was redundant

Measured across the full local corpus of real DSSErrors artefacts (11 files under
`~/Downloads/hartford/` and `~/Downloads/DSSErrors*.log`, plus the committed fixture):

- **All 11 match the `[Xxx.cpp:NNNN]` source-location regex** (`_SNIFF_SRCLOC_RE`), which alone
  returns 0.8 independently of any string marker.
- `hartford_Linux_snapshotDSSErrors (3).log` **contains no `"MCM"` substring at all** and still
  detects correctly — direct proof the marker was not load-bearing.
- After the change, all 11 still sniff **0.80** and still route to `DsserrorsAdapter`.

Real-world detection coverage is therefore unchanged. The full suite is green (557 passed,
8 deselected; baseline was 554 before Phase 12 plan 12-03 added 3 parametrised cases).

## Consequences

**Positive.** The sole-claimant invariant holds for all five adapters without weakening the test.
A variant or truncated PDH header now degrades to `genericlog` instead of being misparsed as a
DSSErrors log. `dsserrors`'s signature no longer depends on a three-letter substring.

**Negative / accepted.** A hypothetical DSSErrors log whose first 64 KB contains `MCM` only in some
third spelling — neither `AvailableMCM` nor `MCM Settings` — and which also lacks a `.cpp:NNNN`
source location, a `Contract Request Failed` banner, an `Info Dump`, and `I-Server`, would now fall
back to `genericlog`. No such file exists in the corpus, and the five remaining markers are
substantially redundant with one another. `genericlog` is a lossless fallback, so the failure mode
is degraded structure, never dropped events.

**Scope note.** This edit was outside plan 12-03's declared `files_modified`. It was escalated as a
blocking decision rather than auto-applied, and the scope widening was explicitly approved before
implementation.

## Alternatives considered

**Relax the test to assert only the unique maximum.** Cheaper, in-scope, and arguably what the
invariant was originally described as — plan 12-03's own threat model calls T-12-11 "the
unique-maximum assertion" while the test asserts sole-claimancy. Rejected: it leaves the
variant-header misrouting risk open and weakens a deliberately strict gate to accommodate a genuine
signature defect. The divergence between the threat-model prose and the test is real and is recorded
in `12-03-SUMMARY.md`; the test is the stricter of the two and is kept as written.

**Lower `dsserrors`'s score on files that also look like PDH-CSVs.** Rejected: cross-adapter
awareness inside a single adapter's `sniff` violates SPEC.md §5.2 self-containment — adapter #6
would then need to know about adapters #1..#5.

**Leave it alone; routing is correct.** Rejected on the residual risk above, and because the
collision is universal across real perfmon artefacts rather than a fixture quirk.
