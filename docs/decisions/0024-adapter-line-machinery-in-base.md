# ADR 0024: the shared line machinery and record accumulator live in `base.py`

**Status:** Accepted
**Date:** 2026-09-20
**Answers:** SPEC.md §5.2 (adapter protocol and self-containment) — where does
the shared multi-line-record machinery live, given that `adapters/base.py`
claims to be the single shared seam but does not hold it?
**Cross-refs:** ADR 0021 (the analyser registry describes the prompt path
only) — unaffected; this ADR is about the adapter layer, not the bundle
commands. Issue #5, and issue #11 which depends on this one.

## Context

`adapters/base.py:5-6` states that decompression "lives here (`open_bytes`)
as the single shared seam: adapters receive a `Path` and call `open_bytes`
themselves, staying self-contained." Measured on 2026-09-20, that is not true.

The line-splitting machinery lives in a *domain* adapter. `MAX_EVENT_LINES`
and `MAX_EVENT_BYTES` are defined at `genericlog.py:44-45`, `byte_lines` at
`genericlog.py:215`, and four sibling adapters import them:

```
dsserrors.py:39   MAX_EVENT_BYTES, MAX_EVENT_LINES, byte_lines
eustack.py:43     MAX_EVENT_BYTES, MAX_EVENT_LINES, byte_lines
journald.py:34    byte_lines
dssperfmon.py:39  byte_lines
```

`grep -c 'byte_lines\|MAX_EVENT' src/sift/adapters/base.py` returns 0. So
`genericlog.py` is a de facto second base module, and a sixth adapter needing
safe multi-line accumulation must import from a domain peer.

The accumulator is copy-pasted alongside it. All three record-carrying
adapters declare a `_Record` dataclass whose first nine fields are identical,
in the same order — `offset`, `line_start`, `ts`, `ts_confidence`, `severity`,
`line_end`, `byte_len`, `message_lines`, `raw_parts`. `genericlog._Record` is
*only* those nine. The `add_line` bodies at `dsserrors.py:211-216` and
`eustack.py:219-224` are byte-identical, confirmed with `diff`.

`base.py` already hosts `ConfigurableAdapter`, whose own docstring
(`base.py:85-96`) says it exists so that "the SPEC §5.2 'adding an adapter =
new module + registration only' invariant finally holds". The seam is already
there. The line machinery simply never moved into it.

## Decision

**Both the machinery and the record base move to `base.py`, in two commits.**

Three seams were considered.

- **Machinery only.** Move `byte_lines` and the caps, delete the four
  cross-imports. Fixes the layering inversion and makes the docstring true,
  but leaves the nine-field block and `add_line` duplicated three ways.
- **Machinery plus a `RecordBase` the three `_Record` classes subclass.**
  Chosen. Removes the duplication as well as the inversion.
- **Machinery plus composition,** a `LineAccumulator` held as a field.
  Declined: it avoids coupling to a base's field order, but turns every read
  site from `rec.byte_len` into `rec.acc.byte_len`, and there are many. That
  trades duplication for indirection at the point of reading, which is the
  wrong direction.

`RecordBase` is a plain `@dataclass`, not `kw_only`. Dataclass inheritance
works here without ceremony because every base field after the five required
ones carries a default, and every domain field the three subclasses add also
carries a default. A future adapter needing a *required* domain field will hit
the "non-default argument follows default argument" wall; the answer then is
`kw_only=True` on that subclass, not a redesign of the base.

`add_line` becomes a method taking `line_no` explicitly, because the two
copies it replaces are closures over the parse loop's `line_no` local.

`journald` and `dssperfmon` are not put on `RecordBase`. One JSON object and
one CSV row are each a whole event, so they accumulate nothing; they take the
moved `byte_lines` and nothing else.

**The sequencing is part of the decision.** The pure move lands first and
alone, so the commit that touches five adapters is verifiable as a no-op
against the pin. The reshape lands second and is independently revertible. A
single combined commit would make a byte-offset regression bisect to one
change spanning both concerns.

## Consequences

- `base.py`'s docstring becomes accurate rather than aspirational, and is
  amended to name the line machinery alongside `open_bytes`.
- A sixth adapter needing multi-line accumulation subclasses `RecordBase` and
  imports nothing from a domain peer.
- Pinned by `pin_adapters.py`, which forces all five adapters over all
  fixtures and captures `event_id`, line span, severity, `ts_confidence` and
  parse coverage for 6414 events across 100 adapter/file pairs. `event_id` is
  `sha256(source_file, byte_offset)[:16]`, so an unchanged digest is an
  unchanged byte offset. Both commits must leave the baseline byte-identical.
- This does not address `ingest.py:168-170`, which still special-cases
  `GenericLogAdapter` by concrete type for offset tracking. That is issue #11,
  which depends on this ADR's protocol work.
