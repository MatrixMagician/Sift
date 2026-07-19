---
phase: 01-skeleton-event-contract-genericlog-adapter
reviewed: 2026-07-16T00:00:00Z
depth: deep
files_reviewed: 19
files_reviewed_list:
  - docs/decisions/0001-typer-over-argparse.md
  - docs/decisions/0002-weasyprint-pdf-extra.md
  - docs/decisions/0003-hand-rolled-masking-over-drain3.md
  - src/sift/__init__.py
  - src/sift/adapters/__init__.py
  - src/sift/adapters/base.py
  - src/sift/adapters/genericlog.py
  - src/sift/cli.py
  - src/sift/config.py
  - src/sift/models.py
  - src/sift/store.py
  - tests/conftest.py
  - tests/test_acceptance.py
  - tests/test_adapters_detect.py
  - tests/test_cli.py
  - tests/test_config.py
  - tests/test_genericlog.py
  - tests/test_models.py
  - tests/test_store.py
findings:
  critical: 2
  warning: 7
  info: 6
  total: 15
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-16
**Depth:** deep
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Deep review of the Phase 1 skeleton: Event contract, per-case SQLite store,
config resolution, adapter registry/detection, genericlog adapter, and the
CLI. Call chains traced across module boundaries (CLI → detect → sniff →
read_head → open_bytes; CLI → parse → store; config → CLI → adapter), with
suspected defects confirmed by live repro rather than by reading alone.

Verified sound: the golden `event_id("app.log", 12345) == "f7fdcb4b3de90265"`
recomputes correctly; all 98 tests pass; every SQL statement in `store.py` is
parameterised (the two f-string SQL usages interpolate only a module-constant
column list and an `int()`-cast internal migration number); the byte-span
partition invariant holds across encodings and compression variants; `src/`
contains no socket, subprocess, eval, or hardcoded-secret usage; user-facing
strings are British English.

Two confirmed defects must be fixed: a single corrupt compressed file aborts
the entire ingest (all other files' events rolled back, no per-file error —
directly contradicting the code's own "loud error, keep going" contract and
the "loud errors on corrupt compressed input" constraint), and terminal
escape injection via hostile filenames bypasses the T-04-01 sanitisation in
both `ingest` and `show` output (confirmed: raw `\x1b` reaches stdout).

## Critical Issues

### CR-01: Corrupt/unreadable compressed file crashes the whole ingest during adapter detection

**File:** `src/sift/cli.py:147` (with `src/sift/adapters/__init__.py:79` and `src/sift/adapters/base.py:67-70`)
**Issue:** The per-file `try/except` in `ingest` (cli.py:154-160) only wraps
`parse` + `insert_events`. `adapters.detect(path, relpath, overrides)` at
line 147 runs **outside** it, and `detect` calls every adapter's `sniff`,
which calls `read_head` → `open_bytes` → actual decompression. A truncated
`.gz` or corrupt `.zst` (routine in real support bundles) raises
`EOFError`/`BadGzipFile`/`ZstdError` there, which propagates uncaught: the
whole ingest aborts, the transaction rolls back every already-parsed file's
events, no `ERROR <file>` line is printed, no coverage meta is written, and
the operator gets an abort instead of a per-file diagnosis. Confirmed by
repro: a directory with one good log and one truncated `.gz` produced exit 1
with output consisting solely of "Aborted." — the good file's events were
lost. This contradicts the in-code contract "A bad file never silently
vanishes: loud error, keep going" (cli.py:158) and makes ingest unusable for
any bundle containing one damaged archive. `test_compressed_corrupt_zstd_raises`
only covers the parse-level path, so the gap is untested.
**Fix:**
```python
# cli.py ingest loop — move detection (and adapter config) inside the try:
for path in files:
    relpath = path.relative_to(input_dir).as_posix()
    try:
        file_adapter = adapters.detect(path, relpath, overrides)
        if isinstance(file_adapter, GenericLogAdapter):
            file_adapter.input_root = input_dir
            file_adapter.tz_overrides = dict(config.timezones)
        events = list(file_adapter.parse(path, case))
        new_count = store.insert_events(events)
    except Exception as exc:
        failed.append(relpath)
        print(f"ERROR {relpath}: {exc}")
        continue
```
Optionally also make `GenericLogAdapter.sniff` return 0.0 on read failure so
detection degrades gracefully and the loud error surfaces from `parse`.

### CR-02: Terminal escape injection via hostile filenames — T-04-01 bypass in `ingest` and `show`

**File:** `src/sift/cli.py:160,177-180,207-210`
**Issue:** `_sanitise` is applied only to the event *message* in `show`. But
`relpath` / `e.source_file` derive from filenames inside the untrusted input
bundle, and Linux filenames may contain any byte except `/` and NUL —
including ESC. `ingest` prints `relpath` raw (lines 160, 177) and `show`
prints `e.source_file` raw (line 209). Confirmed by repro: a file named
`\x1b[31mEVIL\x1b[0m.log` puts raw `\x1b` sequences on stdout in both
commands — hostile bundle bytes driving the operator's terminal, exactly the
threat T-04-01 names. Exception text (`{exc}` at line 160) can also embed
untrusted path bytes and should be treated the same.
**Fix:**
```python
# cli.py — sanitise every untrusted string at render time:
print(f"ERROR {_sanitise(relpath)}: {_sanitise(str(exc))}")
...
print(f"{_sanitise(relpath)}  coverage {cov * 100:.1f}%  ...")
...
print(
    f"{e.event_id}  {ts}  {e.severity:<7}  "
    f"{_sanitise(e.source_file)}:{e.line_start}  {message}"
)
```
Add a regression test with an ESC byte in the *filename* (the existing
`test_show_strips_terminal_escapes` only covers file content).

## Warnings

### WR-01: `--adapter` flag does not actually beat `config.adapters` when globs differ (D-08 precedence violation)

**File:** `src/sift/cli.py:124`
**Issue:** `overrides = dict(config.adapters) | flag_overrides` merges values
per identical key, but `detect` picks the **first** glob in dict insertion
order that matches (adapters/__init__.py:72-78) — and config globs come
first. With config `"*.log" = "genericlog"` and flag
`--adapter "app.log=dsserrors"` (Phase 5), the config glob matches `app.log`
first and the flag is silently ignored. D-08 says flags > config; that only
holds today for byte-identical glob strings.
**Fix:**
```python
overrides = dict(flag_overrides) | {
    g: n for g, n in config.adapters.items() if g not in flag_overrides
}
```
(flag globs first in insertion order, so they win `detect`'s first-match
rule; identical keys keep the flag value). Add a test with overlapping but
non-identical globs.

### WR-02: Symlinks inside the untrusted bundle pull in files from outside it

**File:** `src/sift/cli.py:135`
**Issue:** `input_dir.rglob("*")` + `p.is_file()` follows file symlinks. A
hostile bundle containing `link.log -> /home/user/.ssh/id_rsa` causes Sift to
read and persist content from **outside** the input directory into the case
DB (confirmed by repro: symlinked outside content appears in `show` output).
For a privacy-preserving triage tool whose case DB feeds later report
generation, that is a trust-boundary breach: bundle contents should never
select arbitrary host files for ingestion.
**Fix:** Skip symlinks loudly:
```python
files = [p for p in sorted(input_dir.rglob("*")) if p.is_file()]
for path in files:
    if path.is_symlink():
        print(f"SKIP {_sanitise(relpath)}: symlink (not followed)")
        continue
```
(or `path.resolve().is_relative_to(input_dir)` if intra-bundle symlinks must
work). Record skipped files in the coverage meta so nothing vanishes silently.

### WR-03: `sift new` over an existing case silently repoints it — mixed-snapshot corruption

**File:** `src/sift/cli.py:86-92`
**Issue:** `new` never checks whether the case already exists. Running
`sift new demo --input /other/dir` against an existing `demo` overwrites
`input_dir`/`adapter_overrides` meta while keeping all previously ingested
events. The next `ingest` then mixes events from two different snapshots in
one case — breaking the "a case is one snapshot" model (cli.py:100-104) and
poisoning the parse-coverage meta, with no warning. No test covers this.
**Fix:** In `new`, before creating the store:
```python
if db_path.exists():
    print(f"Error: case {case_name!r} already exists at {db_path.parent}")
    raise typer.Exit(1)
```

### WR-04: Failed files are silently absent from the persisted `parse_coverage` record

**File:** `src/sift/cli.py:156-183`
**Issue:** When a file fails to parse, `continue` skips its `coverage[relpath]`
entry, then `parse_coverage` meta is written containing only successful
files. The failure is loud at ingest time (stdout + exit 1) but the
*persisted* record — which later phases (report, eval) will read — silently
omits the file, violating the nothing-dropped-silently invariant at the
storage layer. A report generated from this case would show no trace that a
file existed and failed.
**Fix:** Record failures in the same meta:
```python
except Exception as exc:
    failed.append(relpath)
    coverage[relpath] = {"error": str(exc), "event_count": 0, "coverage": 0.0}
    print(f"ERROR {_sanitise(relpath)}: {_sanitise(str(exc))}")
    continue
```

### WR-05: Config typos are silently ignored (pydantic `extra` defaults to ignore)

**File:** `src/sift/config.py:21-24`
**Issue:** `SiftConfig` is a plain `BaseModel`, so unknown keys in
`config.toml` (e.g. `data_dirr = "..."` or `[timezone]` instead of
`[timezones]`) validate cleanly and are dropped — the user's setting silently
does nothing. That contradicts T-04-02's "never fall back to defaults
silently" principle, which the same file enforces for malformed TOML but not
for well-formed-but-wrong TOML.
**Fix:**
```python
from pydantic import ConfigDict

class SiftConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
```
plus a test asserting an unknown key raises naming the key.

### WR-06: `_sanitise` passes Unicode bidi/zero-width controls — visual spoofing of triage output

**File:** `src/sift/cli.py:29-41`
**Issue:** The filter strips C0/C1/DEL but passes format characters:
RLO/LRO/isolates (U+202A–U+202E, U+2066–U+2069) and zero-width characters
(U+200B–U+200F, U+FEFF). A hostile log line containing U+202E can visually
reverse the rendered message in the operator's terminal — e.g. hiding
"ERROR" or reordering a path — which is squarely inside T-04-01's "hostile
log bytes must never drive the operator's terminal". These arrive via UTF-8
log content, not just exotic encodings.
**Fix:** Drop the `Cf` category as well:
```python
import unicodedata

def _sanitise(text: str) -> str:
    return "".join(
        ch for ch in text
        if ch in "\n\t"
        or (ord(ch) >= 0x20
            and not (0x7F <= ord(ch) <= 0x9F)
            and unicodedata.category(ch) != "Cf")
    )
```

### WR-07: UTF-16 newline byte-scan can match across character boundaries, misaligning the rest of the file

**File:** `src/sift/adapters/genericlog.py:230-264` (with `_detect_encoding`, 203-216)
**Issue:** `_byte_lines` searches for `b"\n\x00"` (LE) / `b"\x00\n"` (BE) with
a plain `bytes.find`, without enforcing 2-byte alignment. Non-ASCII UTF-16
content can produce the newline pattern straddling two characters (LE
example: U+0A41 followed by U+0100 encodes `... 41 0A 00 01 ...`, containing
`0A 00` at an odd offset), splitting mid-character. Every subsequent line of
the file then decodes misaligned via `errors="replace"` — garbled messages
and wrong timestamp parsing for the remainder of the file, with no
disclosure. The span-partition invariant survives (offsets stay byte-true),
but message/citation fidelity does not. The existing `ponytail:` comment at
lines 250-252 covers only the force-split cap boundary, not this.
**Fix:** Enforce alignment for 2-byte encodings — accept a `find` hit only at
an even offset relative to the stream start (track parity in `_byte_lines`,
e.g. pass `unit=2` and loop `i = buf.find(nl, i + 1)` while `(consumed + i) %
unit != 0`). At minimum, extend the `ponytail:` comment to name this ceiling.

## Info

### IN-01: Per-run mutable state on the shared singleton adapter

**File:** `src/sift/adapters/genericlog.py:287-290`, `src/sift/adapters/__init__.py:15-17`, `src/sift/cli.py:151-153`
**Issue:** `REGISTRY["genericlog"]` is a process-wide singleton whose
`input_root`/`tz_overrides`/`last_stats` are mutated per file by `ingest` and
never reset — state leaks across cases in the same process (one test even
asserts on the leaked state), and the pattern is unsafe if Phase 5 ever
parallelises per-file parsing.
**Fix:** Instantiate a fresh adapter per ingest run (registry maps name →
class or factory), or reset the fields after the loop.

### IN-02: `ingest`/`show` never close the CaseStore; `new` does

**File:** `src/sift/cli.py:107,203`
**Issue:** Inconsistent lifecycle — `new` calls `store.close()` but
`ingest`/`show` rely on process exit. Harmless today (WAL files are cleaned
on close by the OS/GC), but sloppy for a store that later phases will hold
longer.
**Fix:** Add `close()` to `CaseStore` as a context manager (`__enter__`/
`__exit__`) and use `with` in all three commands.

### IN-03: Duplicate `--adapter` globs: last one silently wins

**File:** `src/sift/adapters/__init__.py:50`
**Issue:** `parse_adapter_overrides(["*.log=a", "*.log=b"])` returns
`{"*.log": "b"}` with no diagnostic — a contradictory command line is
silently half-honoured.
**Fix:** `if glob in overrides: raise ValueError(f"duplicate glob {glob!r}")`.

### IN-04: Force-split of monster lines inflates line numbers

**File:** `src/sift/adapters/genericlog.py:249-254,361`
**Issue:** Each force-split piece of a single newline-less run increments
`line_no`, so `line_start`/`line_end` diverge from real file line numbers for
everything after a >64 KB line — citation display (`show` prints
`file:line_start`) will point at the wrong physical line.
**Fix:** Track "piece does not end with `nl`" and only increment `line_no`
when the previous piece was newline-terminated; or document the divergence in
the Event contract.

### IN-05: Frozen `Event` contains a mutable `dict` field

**File:** `src/sift/models.py:31`
**Issue:** `attrs: dict[str, str]` makes the frozen dataclass unhashable
(`hash(event)` raises `TypeError` because the generated `__hash__` tuples the
dict) and shallow-frozen (`event.attrs["x"] = "y"` mutates a "frozen" event).
Nothing hashes or mutates events today, but Phase 2 clustering plausibly
will.
**Fix:** Either document attrs as effectively immutable, or use
`types.MappingProxyType`/a frozen mapping in a `__post_init__`.

### IN-06: `_no_network` guard blocks TCP connect only

**File:** `tests/conftest.py:34-50`
**Issue:** Patching `socket.socket.connect` misses UDP `sendto` and DNS via
`getaddrinfo`, so the "any network connection attempt fails" claim is
slightly wider than the guard. Adequate for Phase 1 (no networking code
exists in `src/`), but worth tightening before Phase 3 relaxes it for
loopback.
**Fix:** Also patch `socket.socket.sendto` and `socket.getaddrinfo` (allowing
loopback in Phase 3).

---

_Reviewed: 2026-07-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
