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
