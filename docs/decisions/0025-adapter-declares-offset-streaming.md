# ADR 0025: adapters declare offset streaming on the `Adapter` protocol

**Status:** Accepted
**Date:** 2026-09-20
**Answers:** SPEC.md §5.2 (adapter protocol, FROZEN after Phase 1, and the
"adding an adapter = new module + registration only" invariant) — how does
`pipeline/ingest.py` learn that an adapter's byte offsets track the input
stream, without naming a concrete adapter class?
**Cross-refs:** ADR 0024 (the shared line machinery and record accumulator
live in `base.py`), which this ADR's closing note was raised by. ADR 0006
(`ConfigurableAdapter`), which established that per-run state lives off the
frozen protocol. Issue #11.

## Context

`ingest.py` streams each file's events in bounded batches and advances the
progress bar as it goes. Advancing mid-file needs the last event of a batch to
carry a `byte_offset`/`byte_len` pair that means something about the file on
disk. At 9b8d924 the orchestrator decided that by asking which class it held.

```python
track_offsets = isinstance(
    file_adapter, GenericLogAdapter
) and path.suffix not in (".gz", ".zst")
```

That was `ingest.py:168-170`, and the import at `ingest.py:34` existed for it
alone. Measured on 2026-09-20, `grep -rn GenericLogAdapter src/sift/pipeline/`
returned exactly those two lines.

So mid-file progress was a privilege of one named adapter. A sixth adapter
that streamed in ascending byte order could not claim it without an edit to
`ingest.py`, which is the change outside "a new module plus registration" that
SPEC.md §5.2 forbids. The frozen `Adapter` protocol had no way to say "my
offsets track the stream".

## Decision

**`Adapter` gains one member, `streams_offsets: bool`.**
`ConfigurableAdapter` defaults it to `False`. `GenericLogAdapter` sets it to
`True`. `ingest.py` reads the flag and imports no adapter module.

The protocol is frozen, so the addition is deliberate and is the whole of the
change to it. Four seams were considered.

- **Widen the `isinstance` to a tuple of streaming adapter classes.** Declined.
  It keeps the dispatch in `ingest.py` and still costs an edit there per
  adapter, which is the thing the invariant forbids.
- **`getattr(file_adapter, "streams_offsets", False)`, no protocol member.**
  Declined. Nothing type-checks the name, so a typo in a new adapter disables
  its tracking silently and forever, and the capability is invisible to anyone
  reading the protocol.
- **A second `runtime_checkable` `StreamingAdapter` protocol, tested with
  `isinstance`.** Declined. A `runtime_checkable` protocol only checks that
  the attributes exist, so this is the flag with a second protocol to keep in
  step with the first.
- **A `bool` member on `Adapter`, defaulted by the base.** Chosen. The
  orchestrator asks a question instead of naming a class, an adapter opts in
  with one line in its own module, and pyright checks the name.

**The `.gz`/`.zst` test stays in `ingest.py`.** A decompressed stream's offsets
do not map to on-disk bytes whatever the adapter promises about its own
output, and the progress bar's total is the on-disk file size. That is a fact
about how ingest reads the file, not about the adapter, so it belongs at the
call site and is not folded into the flag.

**Only genericlog flips the flag.** Every adapter emits `byte_offset` and
`byte_len` attrs, so more of them may well qualify. The flag asserts something
stronger than emitting the attrs, namely that the last event of every batch
carries the largest offset seen so far. Whether `eustack` and `dssperfmon`
hold that across their aggregate and two-pass output was not audited here.
Turning the flag on for another adapter changes observable progress behaviour
and needs its own evidence, so it stays a separate change.

## Consequences

- `ingest.py` imports no adapter module.
  `grep -rn GenericLogAdapter src/sift/pipeline/` returns nothing.
- A future streaming adapter is a new module plus a registration line plus
  `streams_offsets = True`, with `ingest.py` untouched. Pinned by
  `test_streaming_adapter_opts_in_without_editing_ingest`
  (`tests/test_ingest_offsets.py`), which registers a throwaway sixth adapter
  declaring the flag and asserts it gets the mid-file advance. Restoring the
  `isinstance` makes that test fail.
- `Adapter` is a structural protocol, so a class implementing it *without*
  subclassing `ConfigurableAdapter` must now declare `streams_offsets` itself.
  That cost was paid once, by `DummyAdapter` in
  `tests/test_adapters_detect.py`. A future such class hits the same wall, and
  the answer is one declared line, not a redesign.
- Behaviour is unchanged. `GenericLogAdapter` is the only adapter with the flag
  set, so every file takes the same branch it took at 9b8d924. Pinned two ways.
  Re-ingesting a fixture per adapter still inserts zero new events
  (`tests/test_ingest_offsets.py`), and the adapter dump over every fixture
  under all five adapters is byte-identical across the change, 6514 lines,
  sha256 `98d36e3c6bd6759c7587ee1ef6f6faa40da79a9d67a5d66ccc439941c406e91e`.
