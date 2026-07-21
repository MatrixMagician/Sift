# Sift

Sift is a fully local, privacy-preserving incident triage engine. It ingests
diagnostic artefacts from production systems — MicroStrategy DSSErrors logs,
EU-stack thread dumps, journald exports, generic application logs — and uses a
locally hosted LLM to cluster related events, summarise incident timelines, and
generate ranked root-cause hypotheses with citations back to the source
evidence. Every claim in a report cites a verifiable event ID; nothing leaves
your machine except calls to the local inference endpoint you configure.

This quickstart takes you from a clean checkout to your first triage report on
Fedora. Read it top to bottom the first time — the backend setup (step 2) is
where most people get stuck.

## 1. Install

Sift is distributed as a standard Python wheel and installed with
[`uv`](https://docs.astral.sh/uv/). There is no PyPI release; install from a
local checkout or directly from the repository.

```bash
# From a clean checkout of this repository:
uv tool install .

# …or straight from version control, no checkout needed:
uv tool install git+https://github.com/MatrixMagician/Sift
```

Either command puts a `sift` console script on your `PATH`. Confirm the install:

```bash
sift --version
```

Because Sift ships as an ordinary wheel with a console-script entry point, it is
equally installable with `pipx install .` if you prefer pipx to `uv tool`.

### Prerequisites: the inference backend is yours to run

Sift never downloads, builds, or serves models — it has no model management and
makes no network calls except to the local inference endpoint you point it at.
Before step 2 you need a running **OpenAI-compatible** inference server and a
GGUF model of your choosing. Two backends are supported:

- **llama.cpp `llama-server`** — obtain the binary and a GGUF model from the
  [llama.cpp project](https://github.com/ggml-org/llama.cpp).
- **Lemonade Server** — see the
  [Lemonade documentation](https://lemonade-server.ai/) for installation.

Getting the backend running is a one-time, out-of-band step; the rest of this
quickstart assumes it is up.

## 2. Start an inference backend

Sift needs **two** endpoints: one for text generation and one for embeddings.
They may be served by the same backend product, but they are always two
separate server instances (see the note on `--embeddings` below). Sift reads
their URLs from two environment variables:

- `SIFT_GENERATION_BASE_URL` — the generation endpoint (e.g. `http://127.0.0.1:8080/v1`)
- `SIFT_EMBEDDINGS_BASE_URL` — the embeddings endpoint (e.g. `http://127.0.0.1:8081/v1`)

Both must be a loopback or private (RFC1918) address — Sift refuses to talk to a
public endpoint. Optionally set `SIFT_GENERATION_MODEL` and
`SIFT_EMBEDDINGS_MODEL` to pin specific model IDs.

### Option A: llama.cpp `llama-server` (two instances)

On a gfx1151 machine (Strix Halo / Ryzen AI), the **Vulkan** build of
`llama-server` is the robust default. **ROCm 7.2+** is a documented alternative
if you have a working ROCm stack.

The `--embeddings` (a.k.a. `--embedding`) flag makes a server **embedding-only**,
so a single instance cannot serve both roles. Run two instances — one for
generation, one for embeddings:

```bash
# Generation server on :8080
llama-server -m /path/to/generation-model.gguf --host 127.0.0.1 --port 8080

# Embeddings server on :8081 (note --embeddings)
llama-server -m /path/to/embedding-model.gguf --host 127.0.0.1 --port 8081 --embeddings
```

Then point Sift at both:

```bash
export SIFT_GENERATION_BASE_URL=http://127.0.0.1:8080/v1
export SIFT_EMBEDDINGS_BASE_URL=http://127.0.0.1:8081/v1
```

### Option B: Lemonade Server

Lemonade Server exposes an OpenAI-compatible API. Its default port is **13305**
(older documentation says 8000 — always set the port explicitly, never assume
it):

```bash
export SIFT_GENERATION_BASE_URL=http://127.0.0.1:13305/v1
export SIFT_EMBEDDINGS_BASE_URL=http://127.0.0.1:13305/v1
```

> **Embeddings caveat — read this.** Lemonade's `/v1/embeddings` endpoint works
> **only** for models loaded via the `llamacpp` or `flm` recipes. Models loaded
> via the ONNX / OGA recipes — the common Strix Halo chat default — will list in
> `/v1/models` but **cannot embed**, and Sift's clustering stage will fail. Do
> not trust the model list; run `sift doctor` (step 3), which performs a real
> `/v1/embeddings` round-trip and catches exactly this failure mode by name.

## 3. Verify with `sift doctor`

Before analysing anything, confirm both endpoints are reachable and that
embeddings actually work:

```bash
sift doctor
```

`doctor` checks in dependency order and stops at the first critical failure,
naming the failure mode. Its embedding check is a genuine round-trip — the only
thing that catches a Lemonade OGA/ONNX-recipe model that lists but cannot embed.
A clean `doctor` run means you are ready to triage.

## 4. Your first case

The pipeline is four commands: **new → ingest → analyze → report**.

```bash
# 1. Create a case pointing at a directory of diagnostic artefacts.
sift new my-incident --input /path/to/artefacts

# 2. Parse the artefacts into canonical, deduplicated events (idempotent).
sift ingest my-incident

# 3. Embed, cluster, and generate cited root-cause hypotheses.
sift analyze my-incident

# 4. Render a self-contained triage report to stdout (Markdown by default).
sift report my-incident
```

Write the report to a file instead of stdout with `sift report my-incident --out report.md`.
Inspect intermediate state at any point with `sift show`
(e.g. `sift show my-incident clusters`, `sift show my-incident hypotheses`).

When you are finished with the incident, `sift delete my-incident` removes the
case directory — `case.db` and its `mcm/`/`perfmon/` artefacts — so the customer
log text does not linger on disk. It prompts before deleting; pass `--force` to
skip the prompt in a script. A report you exported elsewhere with `--out` is
outside the case directory and is kept.

> **Hypothesis quality depends on the generation model.** A very small or
> unstable model may return hypotheses that fail Sift's citation validation:
> the report is still produced but marked **DEGRADED**, with the raw model
> output preserved for inspection rather than presented as verified findings.
> For ranked, evidence-cited hypotheses, use a competent, stable generation
> model that returns non-empty completions. Ingestion, clustering, and the
> timeline are unaffected by the generation model.

## 5. Optional: PDF reports

PDF output is an opt-in extra so the core install stays free of system
dependencies. Install the extra and the one system library it needs (Fedora):

```bash
uv tool install '.[pdf]'      # or:  uv tool install 'sift[pdf]'
sudo dnf install pango        # WeasyPrint's only system dependency
```

Then:

```bash
sift report my-incident --format pdf --out report.pdf
```

Without the extra, `sift report --format pdf` errors helpfully and points you
here. Markdown and JSON (`--format json`) need no extra.

## Optional: containerised deployment

For a rootless Podman deployment, ready-to-adapt Quadlet units ship in
[`deploy/`](deploy/); the design and its interaction with Sift's SSRF guard are
recorded in [ADR 0011](docs/decisions/0011-quadlet-loopback-guard.md).

## Supported artefact types

Ingestion is adapter-driven. Each adapter sniffs a file and reports a
confidence; the best match wins, and anything unrecognised falls back to the
generic log parser rather than being dropped. Five adapters ship today:

| Adapter | Handles |
| --- | --- |
| `dsserrors` | MicroStrategy Intelligence Server `DSSErrors` logs, including multi-line MCM memory-contract blocks |
| `dssperfmon` | MicroStrategy `DSSPerformanceMonitor` PDH-CSV exports — one sample row per event, each individually citable |
| `eustack` | EU-stack thread dumps (one dump block = one event) |
| `journald` | systemd journal exports |
| `genericlog` | Any other plain-text application log — the fallback |

Perfmon samples are deliberately held out of dedup, clustering, and salience
ranking — a case's cluster output is byte-identical whether or not a perfmon CSV
was ingested — while remaining individually citable by event ID. They exist to
corroborate the error timeline, not to compete with it in the clusters.

Override the automatic choice per file pattern when you need to:

```bash
sift new my-incident --input /path/to/artefacts --adapter '*.log=dsserrors'
```

`--adapter` is repeatable, and takes `glob=adapter-name`.

## MCM memory-pressure forensics

For MicroStrategy cases, `sift mcm` produces a deterministic memory-contract
analysis alongside the LLM triage. It is computed entirely from the log text —
no model authors any figure, and no network call is made:

```bash
sift mcm my-incident
```

It always writes both `<case>/mcm/mcm_report.md` (or `mcm_report.json` with
`--format json`) and `<case>/mcm/mcm_attribution.csv`, then prints a short
summary. Thresholds and the lead-up window are configuration-only, so the same
case and configuration always yield the same bundle.

## DSSPerformanceMonitor correlation

When a case also contains a `DSSPerformanceMonitor` PDH-CSV export, `sift perfmon`
correlates the machine's memory counters against the MCM denial episodes — each
episode annotated with the counter value at denial time, the slope across the
lead-up window, and the peak, computed over the **same** window `sift mcm`
already selects. Like the MCM analysis it is fully deterministic: every figure is
computed from the CSV, no model authors any number, and no network call is made.

```bash
sift perfmon my-incident
```

It writes both `<case>/perfmon/perfmon_report.md` (or `perfmon_report.json` with
`--format json`) and `<case>/perfmon/perfmon_trend.csv`, then prints a short
summary. It works on a case that contains a perfmon CSV and **no DSSErrors log at
all**, degrading to a plain counter-trend report. Correlation hazards — a CSV and
log whose time windows do not overlap, an always-zero `Total MCM Denial` counter,
or a counter set that drifts mid-file — are reported as explicit flags rather
than silently producing a fabricated correlation.

When present, these computed perfmon figures are also fed into `sift analyze` as
**cited** evidence: hypotheses may cite a counter reading by event ID, but the
figures are built before generation, so the model can neither alter nor invent
them. A case with no perfmon data produces a byte-identical prompt to before.

## Requirements

- Python 3.12 or newer.
- Fedora is the reference platform; nothing in Sift is Fedora-specific, but the
  system-package instructions above assume `dnf`.
- A local OpenAI-compatible inference backend you run yourself (see step 2).

## Further documentation

- [Getting started](docs/GETTING-STARTED.md) — a longer walkthrough than this quickstart.
- [Architecture](docs/ARCHITECTURE.md) — the ingest → cluster → retrieve → hypothesise → render pipeline.
- [Configuration](docs/CONFIGURATION.md) — every `SIFT_*` variable and `config.toml` key.
- [Development](docs/DEVELOPMENT.md) — working on Sift itself.
- [Testing](docs/TESTING.md) — the test suite and the `sift eval` golden-case harness.
- [Contributing](CONTRIBUTING.md) — how to propose changes.
- [Architecture decision records](docs/decisions/) — why things are the way they are.

## Licence

Apache-2.0.
