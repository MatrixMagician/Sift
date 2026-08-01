# ADR 0020: `/props` determinism interpretation is pure and lives in `llm/`

**Status:** Accepted (implemented)
**Date:** 2026-08-01
**Answers:** SPEC.md §5.8 (CLI) / §7 (repository layout) — where does the
logic of a Typer command that is **not** a case command live, now that
ADR 0019 has given the seven case commands a seam that `doctor` is explicitly
outside of?
**Cross-refs:** ADR 0019 (the command seam) — this ADR does not extend that
seam, and says why not.

## Context

`sift doctor` runs seven checks in dependency order and stops at the first
critical failure (D-02). The seventh is different in kind from the other six:
it is not a check that can fail, it is an **interpretation**. The server's
`/props` payload is read for three reproducibility risks — a multi-slot
configuration, a random seed, and a non-zero temperature — each emitted as a
non-fatal warning on stderr. Sift sends neither seed nor temperature in its
chat payload, so the endpoint's loaded settings fully determine reproducibility,
which is why doctor must report them at all.

That interpretation had no interface. It sat inline in the Typer command body
in `cli.py`, and reaching it in a test meant standing up an `httpx.MockTransport`
and driving the whole command through `CliRunner`. It was expensive enough that
the seed branch ended up with **no test at all** — and it shipped with two
independent defects (commit 2281e93, 30 Jul 2026):

- it read `default_generation_settings["seed"]`, but llama.cpp nests the sampler
  knobs under a `params` sub-dict, so the key was always absent;
- it tested `seed < 0`, but llama.cpp reports a random seed as UINT32_MAX
  (`4294967295 == -1` unsigned), never as a negative int.

Between them the warning was unreachable on every real build. A live
`sift eval` returning `determinism_stability` of 0.00 therefore looked like a
Sift regression rather than an endpoint setting, which is what prompted the
investigation.

The codebase already names the fix. `commands.resolve_generation_ctx`, which
resolves the generation context window from the same `/props` payload, carries
this in its docstring: *"The warning is RETURNED rather than printed so the
whole decision is unit-testable without a `CliRunner`."* Doctor's three
warnings were the one place that rule had not been applied, and the one place a
warning went dead unnoticed.

## Decision

**The decision becomes a pure function.** `determinism_warnings(props) ->
list[str]` takes the `/props` mapping and returns fully-rendered warning lines —
`Warning: ` prefix included, in emission order (multi-slot, seed, temperature).
The caller is a loop. Nothing about how an operator reads a warning is split
across two modules, and the whole decision is testable against a dict literal
with no client, no transport and no `CliRunner`.

**It lives in `src/sift/llm/props.py`, not in `commands/`.** Two reasons, and
the first is the one a future reader is most likely to get wrong:

- `doctor` is **not a case command** (CONTEXT.md, *Case command*: `new`, `list`,
  `delete`, `doctor`, `eval` and `tui` are not). There is no `run_doctor` in
  `commands/` for the helper to sit beside, and `commands/`'s own package
  docstring describes its contents as `run_x(store, config, ...) -> ExitCode`
  bodies. A lone pure function there would contradict it.
- The payload shape is llama.cpp **wire knowledge** — the `params` nesting and
  the UINT32_MAX sentinel are protocol, not presentation — and per CLAUDE.md
  `llm/` is the package that owns the wire. `_RANDOM_SEED_SENTINEL` moves out of
  `cli.py`, where a llama.cpp protocol constant did not belong.

`resolve_generation_ctx` deliberately does **not** move. It reads the same
payload for `n_ctx`, but it has one consumer, it already sits with that consumer
by the precedent ADR 0019 cites, and no duplication exists today. Consolidating
two readers of one payload into one module is a change to make when there is a
third, not before.

**The full seam move is declined.** Moving all 159 of `doctor`'s lines behind a
`run_doctor(...) -> ExitCode` was considered and rejected for now:

- `doctor` has **one adapter**. ADR 0019's own justification is that "the seam
  is justified by variation that exists, not variation that might" — it cited
  two real adapters (Typer, Textual) plus the eval harness. Doctor has the CLI
  and nothing else, and no requirement asks for doctor in the TUI.
- The test win would be nil. The other six checks need an `httpx.MockTransport`
  wherever their body lives; only the seventh became cheaper to test by being
  extracted, and extracting it does not require moving the other six.

What the move *would* buy is consistency and 159 fewer lines in `cli.py`. That
is real but it is not urgent, and ADR 0019 already records that `cli.py` keeps
`doctor`'s inline lines and `eval`'s 46, so "the codebase carries two
conventions until those are addressed". This ADR does not change that; it
narrows it by one function and states the remaining gap deliberately rather
than leaving it to be rediscovered.

**Warnings stay non-fatal and stay on stderr.** Neither is new; both are now
pinned by a test that did not exist before (below).

## Test split

The pure decision moves to `tests/test_llm_props.py` — ten cases, dict literals
in, lists out. Six migrated from `tests/test_doctor.py`; four are new and were
unreachable at CLI level in any affordable way: emission order and count for the
real llama.cpp shape, the `n_parallel=1` silent case, and the `bool`-is-a-subclass-
of-`int` guards.

One test stays on `CliRunner` and is the reason the migration does not delete
coverage. `test_multi_slot_warns_but_passes` is the **wire-level witness**: it
proves `client.props()` reaches `determinism_warnings`, that the lines land on
stderr, that stdout stays scriptable, and that a warning does not fail the run.
It was tightened from `result.output` — Typer 0.27's interleaved terminal view,
which cannot distinguish the two streams — to `result.stderr` plus a negative
assertion on `result.stdout`. The stdout/stderr routing was previously
unwitnessed by any test.

Without that witness, deleting the loop from `cli.py` would leave every test in
the pure suite green while doctor silently stopped warning — reintroducing
exactly the defect this ADR exists to prevent. That is the general lesson,
recorded during ADR 0019 pass 3 and confirmed again here: **after moving a test
off `CliRunner`, check the caller's coverage, not just the callee's.**

Each claim above was mutation-checked rather than trusted:

| mutation | goes red |
| --- | --- |
| delete the loop in `cli.py` | `test_multi_slot_warns_but_passes` |
| `file=sys.stderr` → stdout | `test_multi_slot_warns_but_passes` |
| read `settings["seed"]`, never `params` | 4 tests in `test_llm_props.py` |
| restore `seed < 0` as the only test | 3 tests in `test_llm_props.py` |
| drop the `bool` guards | `test_bool_values_are_not_read_as_numbers` |

## Consequences

- The class of defect that caused T-03-15 — a warning branch with no interface,
  therefore no test, therefore dead — is closed for `/props` interpretation.
  Adding a fourth determinism risk costs one branch and one dict-literal test.
- `cli.py` loses the llama.cpp sentinel constant and ~50 lines; it keeps
  `doctor`'s remaining checks inline, deliberately.
- `tests/test_doctor.py` drops from 13 tests to 7 and its `_make_transport` loses
  the `default_generation_settings` knob, which no longer has a caller.
- An architecture review that proposes `commands/doctor.py` as the home for this
  logic, or proposes the full seam move on consistency grounds, should read this
  ADR first. Both were considered here.
