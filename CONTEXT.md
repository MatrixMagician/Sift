# Context — Sift's ubiquitous language

The glossary of terms Sift uses with a precise, agreed meaning. `SPEC.md`
remains authoritative for *what the system does*; this file pins *what we call
things* so issues, tests, hypotheses and refactor proposals use one vocabulary.

Terms are added when a real ambiguity gets resolved, not upfront. Each entry
says what the term means and, where it matters, what it is deliberately **not**.

---

## Adapter — two meanings, both legitimate

**Domain sense (`sift/adapters/`):** a pluggable parser for one artefact
format, implementing `sniff()` + `parse()` (`adapters/base.py:37`). This is the
older meaning and the one the code, `SPEC.md` §5.1 and `docs/ARCHITECTURE.md`
all use.

**Design sense:** a concrete thing satisfying an interface at a seam — the
Typer CLI and the Textual TUI are two adapters at the case-command seam.

The collision is real and is not worth renaming a public package over. The
convention:

- In code, docstrings and anything describing artefact parsing, **adapter**
  means the parser. Say *parser* only when disambiguating in prose.
- In architecture discussion, **adapter** means the design role. Name it —
  "two adapters at the command seam" — so the sense is clear from context.
- Never use **adapter** unqualified in a sentence that could be read either
  way.

## Seam — always qualified, never bare

A deliberate boundary where an implementation can be substituted: for a second
caller, for a test double, or for a future rewrite. It is a **role word**, like
*adapter*, and Sift uses it for at least eight different boundaries — so a bare
"the seam" in prose is ambiguous the moment it leaves its own module.

The convention: **name which one**. The recurring ones have canonical names:

- **the command seam** — `run_x(store, config, ...) -> ExitCode` in
  `sift/commands/` (ADR 0019). The Typer CLI and the Textual TUI sit either
  side of it.
- **the client seam** — `llm.bringup.make_http_client`, the single point every
  test binds an `httpx.MockTransport` to. True of the eval suite only since
  2026-08-01: those tests used to construct an `InferenceClient` themselves and
  hand it to `run_case`, which is how eval's client came to be built without
  `tuned_embeddings` while the shipped path had it (ADR 0019). A test that binds
  below the seam cannot notice the seam drifting.
- **the ranking seam** — `store.iter_event_rows`, the one query every ranking
  stage reads, and therefore where `EXCLUDED_FROM_RANKING` takes effect.

Others (the budget seam, the decompression seam, `base.to_utc`, `announce` as
"the operator-facing seam") are named in place and are fine unqualified *inside*
the module that owns them. Nobody is renaming code over this — the ambiguity
costs nothing while reading a function and everything while reading a document.

## Case command

An operation an engineer performs against one case: `show`, `analyze`,
`report`, `validate`, `mcm`, `perfmon`, `eustack`. Its implementation lives in
`sift/commands/` as `run_x(store, config, *, ..., echo, echo_err) -> ExitCode`
and is typer-free; the CLI and the TUI are adapters that call it. See ADR 0019.

*Not* a Typer command — that is the CLI's presentation of a case command, and
several Typer commands (`new`, `list`, `delete`, `doctor`, `eval`, `tui`) are
not case commands at all.

## Exit code

The four-value vocabulary every case command returns, as `ExitCode(IntEnum)`:
`SUCCESS` (0), `ERROR` (1), `USAGE` (2), `DEGRADED` (3, meaning *degraded but
persisted*). Individual commands use a subset — ADR 0007 records that `report`
deliberately never returns 3. Contracts are fixed by ADRs 0005, 0007 and 0010.

Say **exit code** for the value crossing the seam, whether or not it ends up as
a process exit status. The TUI consumes exit codes without any process exiting.

## Flag parsing / domain-identifier parsing

Two kinds of string-to-value parsing, in two modules, deliberately.

**Flag parsing** (`commands/parse.py`) handles shapes that exist *only* because
a CLI encodes arguments as text — `--filter key=value`, an ISO string in
`--since`. Nothing in the domain knows what a `--filter` is. Raises
`ValueError`; the caller owns the message and the exit code.

**Domain-identifier parsing** (`verdicts.parse_target`) turns `hypothesis:0`
into a `TargetSpec`. That identifier is part of the verdicts model, not the
CLI's encoding of it — which is why `record_validation` accepts either the raw
string or an already-parsed spec, and why it raises its own `TargetSpecError`.

The test for which you are looking at: could a caller with no CLI still need it?
If yes it is a domain identifier and lives with its model. `commands` imports
`verdicts`, never the reverse, so consolidating the two would invert the
dependency.

## Case opening

Resolving a case name to a validated, open `CaseStore`: name validation, path
resolution, existence check, and sanitising the failure. Owned by `store.py`
(`open_case`), raising `CaseNotFound` or `CaseUnreadable`. It happens *before*
a case command runs, never inside one — which is why it raises rather than
returning an exit code.

## Client bring-up

Turning a `SiftConfig` into a configured `InferenceClient` and its underlying
`httpx.Client`, including the loopback/RFC1918 guard and the embedding tuning
knobs. Owned by `llm/bringup.py`. One canonical path for all callers, so
"which caller gets which client" cannot drift.

*Not* the same as the `InferenceClient` itself (`llm/client.py`), which knows
about endpoints and protocol but nothing about `SiftConfig`.

## Role and processing unit — two axes, never one

The two things a thread dump tells us about a thread, deliberately kept apart.

**Role** (`pipeline.eustack.Role`) is what a thread is *doing*: `idle-parked`,
`blocked-on-external`, `blocked-on-lock`, `running`, or the `unclassified`
residual. From `[[rule]]` rows, first match in file order (ADR 0015).

**Processing unit** (**PU**) is which Intelligence Server work queue a thread is
doing it *for*: Query Engine, Command PU, Evaluation and so on. From `[[pu]]`
rows, deepest matching frame wins (ADR 0022). The term is MicroStrategy's own,
adopted from the Support Utility so an engineer's existing vocabulary carries
over.

They are orthogonal and neither overrides the other: a `blocked-on-lock` Query
Engine thread and a `blocked-on-lock` Command PU thread share a role and are
different incidents. Say **role** or **processing unit**, never "classification"
unqualified — that word could mean either, and the cross-tabulation of the two
(`PuHealth`) is where the diagnostic value lives.

**Subsystem** belongs to the role axis (`Rule.subsystem`, e.g. `job-queue`,
`warehouse`) and is a finer label *within* it, not a synonym for a processing
unit. `PuRule.subsystem` exists too, and is a slug for the same queue the `name`
names; when both could be meant, say "role subsystem" or "PU subsystem".

**Unattributed** means no `[[pu]]` row matched (`pu is None`), reported as its own
row. It is an ordinary outcome for infrastructure threads and never a failure —
unlike `unclassified` on the role axis, whose rate is deliberately a
rules-drift signal. Do not describe either as "unknown", which blurs the two.

## Dump grammar

How one thread-dump format spells a thread header and a frame line, plus the
symbol-extraction rule that strips its own location and offset noise
(`adapters/threaddump.DumpGrammar`). Three ship: `eu-stack`, `solaris-pstack`,
`gdb-pstack`.

The grammar is the *only* format-dependent part of thread-dump analysis:
everything after the split — role rules, PU attribution, signature grouping,
saturation, rendering — runs on grammar-normalised frames and is identical
across formats. "Adding a format" therefore means adding a grammar, and nothing
else.

Note that `eustack` remains the adapter's name and the `Event.source` value for
all three formats, for the same reason ADR 0015's vocabulary was not renamed:
the stored value is load-bearing in queries and case databases. Which grammar
actually read a thread is recorded per event in `attrs["dump_format"]`. In
prose, prefer **thread dump** for the artefact and **eu-stack** only when the
elfutils format specifically is meant.
