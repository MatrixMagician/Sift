# 0022. The Wake adapter reads a snapshot directory, not a log file

## Status

Accepted.

## Context

[Wake](https://github.com/MatrixMagician/Wake) is an eBPF incident flight
recorder: it keeps kernel-level events in a bounded in-memory ring and persists
a self-contained snapshot directory when a trigger fires. Its snapshot schema is
an explicitly versioned public contract, documented in Wake's
`docs/snapshot-format.md`, and Wake's SPEC names Sift as the intended consumer.

Every existing Sift adapter takes a line-oriented log file. A Wake snapshot is a
directory:

```
<id>/
├── manifest.json        # trigger, host, drop counters, config hash
├── events.jsonl.zst     # the events themselves
├── system.json          # meminfo, PSI, uptime at trigger time
└── proc/                # scrape of the triggering process, if it still existed
```

The `Adapter` protocol is frozen (`sniff(path) -> float`, `parse(path, case_id)`),
so the question was how a directory-shaped input fits a file-shaped protocol.

## Decision

**The adapter claims `events.jsonl.zst` and reads `manifest.json` as a sibling.**

`sniff()` returns 1.0 for a file named `events.jsonl.zst` that sits next to a
`manifest.json` carrying Wake's field set, and 0.0 for anything else. Detection
is structural rather than textual because zstd-compressed JSONL is not a
distinctive byte shape, and decompressing every candidate to find out would make
sniffing expensive for no gain.

Three consequences follow, each deliberate:

### The manifest becomes synthetic events, not just metadata

Two events are emitted before the snapshot's own, both stamped with the
trigger's firing time:

1. **The trigger event** (`severity="error"`) — why this snapshot exists at all,
   with the rule, host, unit and PID in `attrs`. It is the first thing anyone
   asks of a snapshot, so it belongs in the timeline rather than in a field
   nobody reads.
2. **The drop warning** (`severity="warn"`), emitted only when Wake actually
   lost events.

### Drops are surfaced loudly

This is the load-bearing decision. Wake counts every event it lost, at every
boundary, and reports the counts in each manifest — that honesty is one of its
stated invariants. A consumer that ignored those counters would convert an
honest *partial* record into a silently *incomplete* one, and Sift would then
generate confident, evidence-cited hypotheses across a gap it could not see.

So a non-zero drop count becomes a `warn` event saying, in words, that the
timeline is incomplete and by how much. `watch_fanout` drops are excluded: per
Wake's contract they concern a live `wake watch` client and say nothing about
snapshot completeness.

### `source_file` keeps the snapshot directory name

`event_id` is `sha256(source_file, byte_offset)`, and every Wake snapshot
contains a file called `events.jsonl.zst`. A case holding two snapshots would
therefore collide on identity. `source_file` is recorded as
`<snapshot-id>/events.jsonl.zst`, which restores uniqueness and keeps
re-ingestion idempotent.

## The document-only rule

The adapter was written **from Wake's `docs/snapshot-format.md` alone**, without
reading Wake's source, because Wake's M5 acceptance criterion asserts the
document is complete enough for exactly that. It was: no field needed
clarification from the implementation.

The tests preserve the property. Their fixtures are constructed by hand from the
format document, so they test the *contract*; a fixture copied from Wake's test
data would silently start testing Wake's implementation instead. The single
exception is `test_reads_wake_reference_fixture`, which runs against the
reference snapshot Wake ships precisely so that drift between the two
implementations is caught.

## Consequences

- Sift can triage kernel-level evidence — what a process actually opened,
  connected to, and died of — alongside the application logs that omit it.
- A future Wake schema change is visible: the adapter records a parse note when
  `schema_version` is outside its tested set, and degrades rather than refusing,
  matching Wake's stated policy that compatible changes do not bump the version.
- `system.json` and `proc/` are not yet ingested. They are point-in-time state
  rather than events, and Sift's `Event` model is a poor fit for them; folding
  them in deserves its own decision rather than being smuggled in as attributes.
