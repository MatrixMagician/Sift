# ADR 0006: `ConfigurableAdapter` base + rotated-siblings ordered by timestamp

**Status:** Accepted (implementation lands in Phase 5 / M5)
**Date:** 2026-07-17 (Phase 5 context; recorded per SPEC §10 open-question rule)
**Answers:** How does the ingest orchestrator deliver per-run config to, and
read parse coverage back from, *every* adapter rather than just genericlog; and
how are rotated log siblings (`DSSErrors.log`, `DSSErrors.bak00`, …) ordered
into a single timeline? Cross-refs SPEC.md §5.2 (adapter self-containment), §5.3
(coverage / "nothing disappears silently"), and Phase 5 RESEARCH Patterns 1
and 5.

## Context

`cli.py`'s ingest loop must do two per-file things for an adapter: **set** its
per-run configuration (`input_root` for node attribution, `tz_overrides` for
D-05 timezone handling) and **read back** its `ParseStats` to report real
parse coverage. The frozen `Adapter` Protocol (`base.py`, SPEC §5.2 verbatim)
deliberately carries no config attributes — its surface is only `name`,
`sniff()` and `parse()` — so this state travels on the adapter *instance*
instead (the Phase 1 "config on the instance" decision).

Phase 1 wired that instance state up with three `isinstance(file_adapter,
GenericLogAdapter)` guards, because genericlog was the only adapter. Two of
those guards are load-bearing:

1. **Config delivery** — `input_root` / `tz_overrides` were set only when the
   adapter *was* a `GenericLogAdapter`. Any other adapter would parse with
   `input_root = None` (node-tagging impossible) and `tz_overrides = {}`
   (multi-node timezone normalisation impossible).
2. **Coverage read-back** — `last_stats` was read only for a
   `GenericLogAdapter`; for anything else the code fell through to a
   `stats = None → cov = 1.0` default. That default **fabricated 100 %
   coverage** for every non-genericlog file regardless of how many bytes fell
   into severity-unknown fallback events — the exact silent failure SPEC §5.3
   forbids ("nothing disappears silently"). A naive test would pass while the
   real ≥95 % coverage criterion was meaningless.

Adding the three Phase-5 domain adapters (journald, dsserrors, eustack) behind
those same guards would either require a new `isinstance` branch per adapter in
`cli.py` — the opposite of the SPEC §5.2 "adding an adapter = new module +
registration only" invariant — or silently inherit both bugs.

A second, related question surfaced with dsserrors: MicroStrategy rotates
`DSSErrors.log` into `.bak00`, `.bak01`, … siblings. How should events from a
log and its rotated siblings be ordered into one timeline, and should an
adapter stitch a record split across a rotation boundary back together?

## Decision

**1. Introduce a concrete `ConfigurableAdapter` base class in `base.py`.** It
carries the three per-run attributes (`input_root`, `tz_overrides`,
`last_stats`) and nothing else. Every concrete adapter — `GenericLogAdapter`
today, the three Phase-5 adapters, and adapter #6 tomorrow — subclasses it.
`cli.py` changes both load-bearing guards from
`isinstance(..., GenericLogAdapter)` to `isinstance(..., ConfigurableAdapter)`,
so config is delivered and real coverage is read for *any* adapter uniformly.
The `stats = None → cov = 1.0` fallback then only ever applies to a genuine
non-`ConfigurableAdapter` (e.g. a bare-Protocol test double), never to a real
adapter with unparseable regions.

`ConfigurableAdapter` is a **separate concrete base**, NOT part of the frozen
`Adapter` Protocol — the Protocol (`base.py`) stays byte-unchanged. Because it
is a concrete type, `isinstance` narrowing type-checks cleanly under pyright
strict. `to_utc` and `tz_override_for` are promoted alongside it into `base.py`
as the single shared UTC / tz-override code path; genericlog imports `to_utc`
back and its behaviour is unchanged (regression-guarded by the existing
`tests/test_genericlog.py` suite).

The `track_offsets` progress-bar guard stays keyed to `GenericLogAdapter`
deliberately: byte-offset progress accuracy is genericlog-specific and is
explicitly **not** a success criterion, and broadening it would add
decompressed-offset risk for `.gz`/`.zst` inputs.

**2. Rotated siblings are ordered by each event's own UTC `ts`, never by
filename suffix, and `Adapter.parse` stays strictly per-file.** `DSSErrors.log`
and `DSSErrors.bak00` are parsed independently; the merged timeline is produced
downstream by sorting on each event's normalised UTC timestamp. Filename suffix
ordering is rejected — rotation numbering is not a reliable chronological key
across nodes or reconfigurations, and per-event `ts` is the authoritative order
(SPEC §5.3). No adapter stitches a record across a file boundary.

## Consequences

- **SPEC §5.2 finally holds for real:** adapter #6 needs a new module plus one
  registration line and zero `cli.py` changes. The per-adapter `isinstance`
  ladder is collapsed to one concept.
- **The fabricated-coverage bug is closed:** `sift ingest` reports the true
  `ParseStats.coverage` for every adapter; a regression test
  (`tests/test_configurable_adapter.py`) fails if coverage is ever hard-coded to
  1.0 again — a stub adapter emitting 10 % unknown-fallback bytes must report
  90.0 %, never 100.0 %.
- **dsserrors node-tagging and multi-node timezone handling become reachable:**
  the adapter receives `input_root` (node from the first relative-path
  component) and `tz_overrides` (per-node globs → IANA zones) like genericlog.
- **Accepted limitation (rotation-boundary fragmentation):** because parse is
  per-file with no cross-file stitching, a multi-line MCM block that begins in
  `DSSErrors.log` and continues in `DSSErrors.bak00` fragments into two events
  — one per file. Both events survive and both cite their real byte offsets, so
  "nothing disappears silently" still holds; only the block's internal grouping
  is split. Cross-file stitching is deliberately out of scope: it would break
  per-file determinism and the savepoint-per-file rollback model for a rare
  boundary case. A future phase may revisit if real cases show it matters.
