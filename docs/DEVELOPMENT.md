<!-- generated-by: gsd-doc-writer -->
# Development

How to work on Sift itself. For the process side — raising issues, branch and PR
etiquette — see [CONTRIBUTING.md](../CONTRIBUTING.md). This document is the
technical companion: environment, quality gate, layout, conventions, and the
walkthroughs you are most likely to need.

## Local setup

Sift is a `uv`-managed, src-layout Python 3.12+ package. `uv` is the only tool
you need; it provisions the interpreter, the virtualenv, and the dependencies.

```bash
git clone https://github.com/MatrixMagician/Sift.git
cd Sift
uv sync
```

`uv sync` creates `.venv/`, installs the runtime dependencies and the `dev`
dependency group (`pytest`, `ruff`, `pyright`, `respx`), and installs `sift`
itself in editable mode via the `uv_build` backend. There is no separate
"editable install" step — edits under `src/sift/` take effect immediately.

Run the CLI from the checkout with `uv run`:

```bash
uv run sift --help
uv run sift doctor          # verify sqlite-vec loads and the endpoints answer
```

`sift doctor` is the fastest way to confirm your environment is usable: it
checks that `sqlite3` can load the sqlite-vec extension and round-trips a real
embedding call against the configured endpoint, rather than merely listing
models. See [CONFIGURATION.md](CONFIGURATION.md) for the `SIFT_*` variables
that point it at your inference server.

Optional extras:

```bash
uv sync --extra pdf         # markdown + WeasyPrint for `sift report --format pdf`
```

The `pdf` extra additionally needs the pango system library, which pip cannot
install (`sudo dnf install pango` on Fedora, the reference platform). The core
install deliberately stays free of system dependencies — see
[ADR 0002](decisions/0002-weasyprint-pdf-extra.md).

## The quality gate

Three commands. All three clean is the definition of done — for a commit, for a
plan, for a milestone. Nothing else counts as finished.

```bash
uv run ruff check           # lint (E, F, I, UP, B, DTZ), target py312
uv run pyright              # strict mode over src/ and tests/, 0 errors
uv run pytest               # default suite
```

Notes that bite people:

- **pyright runs in `strict` mode** (`[tool.pyright]` in `pyproject.toml`) over
  both `src` and `tests`. Test code is held to the same standard as production
  code. Suppressions must be narrow (`# pyright: ignore[ruleName]`) and carry a
  comment saying why.
- **The default pytest run excludes three marker groups.** `addopts` filters out
  `perf`, `live`, and `packaging`. Run them explicitly when your change touches
  what they cover:

  ```bash
  uv run pytest -m perf         # 100 MB-scale gates
  uv run pytest -m live         # real inference-server integration
  uv run pytest -m packaging    # offline install smoke + Quadlet dry-run
  ```

  `-m live` is the only marker whose tests are permitted to open a socket.
- **`docs/reference/` is excluded from linting** (`extend-exclude`). It holds a
  vendored, byte-verbatim reference source kept for provenance; do not reformat
  it.
- Single test, single file:

  ```bash
  uv run pytest tests/test_dsserrors.py -k timestamp
  ```

Do not start work on the next milestone while the current one's tests are red.

## Project layout

```
src/sift/
  cli.py            Typer app — the nine subcommands (new, ingest, show, analyze,
                    report, mcm, perfmon, eval, doctor) and the ingest orchestrator
  config.py         config precedence: CLI flags > SIFT_* env > config.toml > defaults
  models.py         frozen Event dataclass + event_id(); Hypothesis/HypothesisSet
  store.py          SQLite + sqlite-vec case store; owns migrations and the
                    EXCLUDED_FROM_RANKING source-kind seam
  adapters/         pluggable parsers (base.py holds the frozen Adapter protocol);
                    five shipped: genericlog, journald, dsserrors, eustack, dssperfmon
  pipeline/         dedup, cluster, salience, retrieve, hypothesise; mcm + mcm_facts
                    (MCM denial episodes), perfmon + perfmon_facts (DSSPerformanceMonitor)
  llm/              client.py — the ONLY module that opens HTTP; budget.py
  render/           markdown (primary), json_out, mcm_report, perfmon_report, pdf (extra)
  prompts/          versioned *.md prompt templates, loaded as package data
  eval/             golden-case harness behind `sift eval`
tests/              pytest suite; tests/perf and tests/fixtures alongside
eval/               golden cases + thresholds.toml
docs/decisions/     architecture decision records
deploy/             Quadlet container unit
```

[ARCHITECTURE.md](ARCHITECTURE.md) explains how these fit together and why the
case store is the single seam between stages; this section is only a map.

## Conventions that actually bind

- **Type hints everywhere.** pyright strict is a gate, not a suggestion. Prefer
  making the pipeline more auditable over making it more clever.
- **British English** in documentation and user-facing strings ("normalise",
  "artefact", "licence").
- **Boring technology.** The dependency set is deliberately small: stdlib,
  httpx, Pydantic, sqlite-vec, scikit-learn, Typer, zstandard. Anything beyond
  it needs a justification in the pull request, and probably an ADR. No vendor
  SDKs — the LLM client is hand-rolled httpx precisely so Sift controls the
  request shape.
- **Prompts are data, not code.** Every prompt lives as a Markdown template in
  `src/sift/prompts/` and is loaded with `importlib.resources`. Changing a
  prompt must never require touching Python.
- **Determinism.** `event_id = sha256(source_file, byte_offset)[:16]`. Identical
  case, config, model, and seed must produce byte-identical JSON (modulo
  timestamps). Anything that introduces ordering nondeterminism — set iteration,
  unstable sorts, dict-of-floats comparisons — is a bug.
- **Nothing disappears silently.** Unparseable regions become
  `severity="unknown"` events; adapters report per-file parse coverage. A parser
  that drops input is worse than one that admits defeat loudly.
- **Citation validation is load-bearing.** Every hypothesis's
  `supporting_event_ids` must exist in the case store. Invalid citations trigger
  one regeneration, then a flag in the report. This is the anti-hallucination
  mechanism, not polish; do not weaken it for convenience.
- **Frozen contracts.** The `Event` dataclass (`models.py`) and the `Adapter`
  protocol (`adapters/base.py`) are frozen. Breaking either requires a milestone
  decision recorded in `docs/decisions/` and a store migration — never an
  in-place edit.
- **ADRs.** Decisions that close an open question go in `docs/decisions/` as
  `NNNN-kebab-title.md`, numbered sequentially, with a Status, Date, the
  question being answered, Context, and the decision. Read the existing eleven
  before adding the twelfth — several answer questions you may be about to
  re-ask.

## Walkthrough: adding a new adapter

The invariant: **adding an adapter requires exactly a new module plus one
registration line — nothing else changes.** If your change touches `cli.py`,
`store.py`, or the pipeline, you have found a leak in the abstraction; fix the
leak rather than routing around it.

`dssperfmon` (`src/sift/adapters/dssperfmon.py`) is the most recent worked
example — the fifth adapter, added in v1.2 for MicroStrategy
DSSPerformanceMonitor PDH-CSV samples. It held to the invariant with one
sanctioned exception, covered in step 5: a whole *source kind* that must remain
citable but be held out of the ranking pipeline. Read it alongside this
walkthrough.

### 1. The contract

`src/sift/adapters/base.py` holds the frozen protocol:

```python
class Adapter(Protocol):
    name: str

    def sniff(self, path: Path) -> float: ...   # 0.0-1.0 confidence this file is mine
    def parse(self, path: Path, case_id: str) -> Iterator[Event]: ...
```

`parse` yields the canonical frozen `Event` (`src/sift/models.py`) — every
adapter normalises into the same shape:

```python
Event(
    event_id=event_id(relpath, byte_offset),  # sha256(source_file, offset)[:16]
    case_id=case_id,
    ts=..., ts_confidence="exact" | "inferred" | "missing",
    source="myformat",           # your adapter name
    source_file=relpath,         # case-relative POSIX path
    line_start=..., line_end=...,  # 1-based, inclusive; a multi-line record is ONE event
    severity="fatal" | "error" | "warn" | "info" | "debug" | "unknown",
    component=..., thread=..., session=...,
    message=...,                 # normalised text, multi-line permitted
    attrs={...},                 # adapter-specific extras, str -> str
    raw=...,                     # verbatim source text, for citation display
)
```

### 2. Write the module

Create `src/sift/adapters/myformat.py`. Subclass `ConfigurableAdapter` — it
carries the per-run state the ingest orchestrator sets and reads back
(`input_root`, `tz_overrides`, `last_stats`), and subclassing is what lets the
orchestrator treat every adapter uniformly:

```python
from sift.adapters.base import ConfigurableAdapter, ParseStats, open_bytes, read_head

class MyFormatAdapter(ConfigurableAdapter):
    name = "myformat"

    def sniff(self, path: Path) -> float:
        head = read_head(path)      # first 64 KiB of DECOMPRESSED bytes
        ...

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        stats = ParseStats(path=relpath)
        with open_bytes(path) as stream:   # gzip/zstd handled here, not by you
            ...
        self.last_stats = stats
```

Points that are not optional:

- **Sniff decompressed content.** Use `read_head`, never the raw bytes of a
  `.gz`/`.zst` file. `open_bytes` detects gzip and zstd by magic bytes.
- **Compute byte offsets on the decompressed byte stream, never on decoded
  text.** `event_id` determinism depends on it: a plain copy and a gzipped copy
  of the same file must yield identical ids.
- **Populate `ParseStats`** (`total_bytes`, `unknown_fallback_bytes`,
  `event_count`, plus any timezone-inference `notes`) and assign it to
  `self.last_stats` before returning. The CLI reads it to report real per-file
  coverage; an adapter that leaves it `None` is reported as unmeasured rather
  than fabricated as 100%.
- **Never fabricate a severity** outside the six-value set — `store.py` enforces
  it with a CHECK constraint.
- **Normalise timestamps through `to_utc` / `tz_override_for`** so the shared
  timezone-override path applies to your adapter too.

### 3. Register it

One line in `src/sift/adapters/__init__.py`:

```python
REGISTRY: dict[str, Adapter] = {
    "genericlog": GenericLogAdapter(),
    "journald": JournaldAdapter(),
    "dsserrors": DsserrorsAdapter(),
    "eustack": EustackAdapter(),
    "dssperfmon": DssperfmonAdapter(),
    "myformat": MyFormatAdapter(),   # your new adapter
}
```

Registration order is the detection order, and it is fixed at import time —
that is what makes auto-detection deterministic. `detect()` resolves a file by:
explicit `--adapter glob=name` override (first matching glob wins) → highest
unique sniff confidence at or above `SNIFF_THRESHOLD` (0.5) → `genericlog` as
the fallback on a tie or an all-below-threshold scan. Your `sniff` must
therefore be conservative: a false positive on a plain log file is worse than a
missed detection, because the fallback is already correct.

### 4. Test it

Add `tests/test_myformat.py` plus a fixture under `tests/fixtures/`, and extend
`tests/test_adapters_detect.py` so your format is covered by the shared
detection matrix — including the negative case that your adapter does *not*
claim other adapters' fixtures. Then run the gate.

### 5. The one sanctioned exception: source-kind ranking exclusion

Most adapters produce diagnostic events that should flow through the whole
pipeline. Some do not. `dssperfmon` emits periodic monitoring samples —
thousands of near-identical PDH-CSV rows that carry no incident signal to
dedup, cluster, salience or hypothesis excerpts, and would dominate template
counts if ranked. They must stay fully **citable** (a hypothesis can reference
a sample, and `sift show events` lists them) while being **held out of
ranking**.

That is the sole case in which adding a source touches an existing file, and it
is a deliberately single seam: one entry in the `EXCLUDED_FROM_RANKING`
frozenset in `src/sift/store.py`.

```python
EXCLUDED_FROM_RANKING: frozenset[str] = frozenset({"dssperfmon"})
```

The store's ranking-facing readers filter by this set; the citation- and
display-facing readers deliberately do not, so exclusion never means the events
disappear. Exclusion is a property of the *source kind*, owned in `store.py`
and never caller-supplied — which is why it lives in exactly one place rather
than being threaded as a flag through every pipeline stage. If your adapter
produces monitoring or telemetry data rather than incidents, add its name here;
otherwise leave the set alone. This is the only pipeline-adjacent edit a new
adapter is permitted to make.

## Walkthrough: working on prompts

All prompts live in `src/sift/prompts/` as Markdown and are loaded at runtime
with `importlib.resources`:

| Template | Loaded by |
|---|---|
| `triage.md` | `pipeline/hypothesise.py` |
| `cluster_label.md` | `pipeline/cluster.py` |
| `mcm_facts.md` | `pipeline/mcm_facts.py` |
| `perfmon_facts.md` | `pipeline/perfmon_facts.py` |
| `judge.md` | `eval/judge.py` |

Rules for changing one:

- **Edit only the Markdown.** If a prompt change forces a Python change, the
  template has the wrong seam — move the prose into the template.
- **Respect the sentinels.** Some templates carry delimited blocks (for example
  the KB reference-material block in `triage.md`, marked with HTML-comment
  sentinels) that Python fills in. Keep the sentinel lines exactly as they are;
  put your prose around them.
- **Log-derived text is untrusted data, never instructions.** Excerpts
  interpolated into a prompt come from customer artefacts. Templates are loaded
  and interpolated, never executed, and the surrounding wording must keep
  quoted evidence clearly framed as evidence.
- **A prompt change is a behavioural change.** Re-run the golden-case harness —
  `uv run sift eval` — and compare against `eval/thresholds.toml` before
  proposing it. The harness exits non-zero on a threshold regression, which is
  the point.
- Prompts ship as package data; adding a new template means adding the file and
  the module that loads it, nothing more.

## Testing rules you must know before writing a test

Two project rules are enforced automatically by `tests/conftest.py` via autouse
fixtures:

- **Zero network in tests.** `socket.socket.connect` is monkeypatched to raise
  for every test that does not carry the `live` marker. There is no opt-out
  short of that marker. The LLM client (`InferenceClient`, `src/sift/llm/`) is
  injectable — every pipeline function that talks to a model takes it as a
  parameter — so tests pass a fake or use `respx` to mock httpx. If you find
  yourself wanting a real endpoint, you want a `live`-marked test.
- **Filesystem isolation.** `XDG_DATA_HOME` and `XDG_CONFIG_HOME` are redirected
  into `tmp_path` and all `SIFT_*` environment variables are cleared, so no test
  can read or write your real home directory or inherit your local config.

`tests/conftest.py` is shared infrastructure — add fixtures in your own test
module, not there.

Full detail on the suite, the markers, and the `sift eval` golden-case harness
is in [TESTING.md](TESTING.md).
