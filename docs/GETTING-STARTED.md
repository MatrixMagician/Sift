<!-- generated-by: gsd-doc-writer -->
# Getting started with Sift

This is the longer companion to the [README quickstart](../README.md). The
README gets you installed, gets a backend running, and gets one report out.
This guide assumes all of that already works and covers what comes next:

- what each pipeline stage actually produces, and how to look at it
- how to read a triage report, and what **DEGRADED** and **FLAGGED** mean
- inspecting intermediate state with `sift show`
- when you need `--adapter glob=name`
- the MCM memory-pressure workflow
- re-running stages, idempotency, and the exit-code contracts
- the failure modes you are most likely to hit

If you have not yet got `sift doctor` passing, go back to the README first —
nothing below will work until it does.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.12 or newer | Declared in `pyproject.toml`; 3.13 is fine. |
| `uv` (or `pipx`) | Sift ships as an ordinary wheel with a console script. |
| A running generation endpoint | `SIFT_GENERATION_BASE_URL`, loopback or RFC1918 only. |
| A running embeddings endpoint | `SIFT_EMBEDDINGS_BASE_URL`, likewise. |
| `pango` + the `sift[pdf]` extra | Only if you want `--format pdf`. |

Sift never downloads or serves a model. The two endpoints are yours to run;
see the README for `llama-server` and Lemonade Server setup, and
[CONFIGURATION.md](CONFIGURATION.md) for every `SIFT_*` variable and
`config.toml` key.

Verify before you start:

```bash
sift doctor
```

`doctor` runs its checks in dependency order and stops at the first critical
failure, naming the failure mode. Pass a case name to also check the server's
embedding dimension against that case's recorded index dimension:

```bash
sift doctor my-incident
```

That last check matters if you ever change embedding model between runs — a
dimension mismatch against an existing case index is a hard failure, not a
silent re-embed.

## The commands, at a glance

| Command | Does | Talks to the LLM? |
| --- | --- | --- |
| `sift new <case> --input <dir>` | Registers a case pointing at a directory of artefacts | No |
| `sift ingest <case>` | Parses artefacts into canonical events + template groups | No |
| `sift analyze <case>` | Embeds, clusters, labels, ranks, generates cited hypotheses | Yes |
| `sift report <case>` | Renders a self-contained report from `case.db` | No |
| `sift show <case> <target>` | Inspects events, clusters or hypotheses | No |
| `sift mcm <case>` | Deterministic MicroStrategy memory-contract forensics | No |
| `sift eval` | Runs the golden-case suite and gates on thresholds | Yes |
| `sift doctor [case]` | Verifies endpoints, embeddings round-trip, sqlite-vec | Yes |

Only `analyze`, `eval` and `doctor` construct an inference client. `report`
and `mcm` are pure functions of the case database — you can render and
re-render them with the backend shut down entirely.

Every command accepts `--data-dir` to override where case directories live.

## A worked end-to-end walkthrough

### 1. Create the case

```bash
sift new hartford-oom --input ~/diagnostics/hartford-2026-05-11
```

```
Created case 'hartford-oom' for /home/you/diagnostics/hartford-2026-05-11
```

This writes `<data-dir>/hartford-oom/case.db` and records three things in it:
the resolved input directory, a creation timestamp, and any `--adapter`
overrides you passed. Nothing is parsed yet.

A case is **one snapshot of artefacts**. `sift new` refuses to overwrite an
existing case rather than silently repointing it at a different directory —
mixing two snapshots into one case would poison the parse-coverage metadata.
If the input directory is empty you get a warning, not an error.

### 2. Ingest

```bash
sift ingest hartford-oom
```

```
DSSErrors_2026-05-11.log  coverage 99.4%  184213 events  184213 new
  note: 41 unparseable regions emitted as severity=unknown
iserver1_stacks.txt       coverage 100.0%  62 events  62 new
Total: 184275 new events
Template groups: 1904
```

Read that output carefully — it is the honesty layer:

- **coverage** is the fraction of file bytes that landed in a structured
  event. Anything below ~95% usually means the wrong adapter was chosen (see
  [Adapter overrides](#adapter-overrides-when-you-need-them)).
- **events** is the total parsed from that file; **new** is how many were not
  already in the store. On a re-run, `new` is zero.
- A file that fails to parse prints `ERROR <file>: <reason>`, is recorded in
  the coverage metadata, and ingestion **continues**. The command then exits
  1 at the end so the failure cannot be missed. Nothing disappears silently:
  unparseable regions become `severity="unknown"` events rather than being
  dropped.
- Symlinks are reported as `SKIP <file>: symlink (not followed)`.

**Template groups** are the pre-semantic dedup layer: volatile tokens
(numbers, hex, UUIDs, SIDs, OIDs, paths, timestamps) are masked, and events
sharing a masked string are grouped. 184,275 events collapsing to 1,904
groups is the normal shape. Groups are rebuilt after the event transaction
commits, so they always reflect what is actually stored.

### 3. Inspect before you spend inference time

```bash
sift show hartford-oom clusters --filter min-count=100 --filter limit=10
```

Before `analyze` has run, `show clusters` renders the **template groups** —
the pre-cluster view:

```
0a3f1c2e     8842  error    2026-05-11T04:12:07+00:00  2026-05-11T06:55:31+00:00  Memory Contract Manager denied request for <NUM> bytes
    exemplars: 8f2a1c0d4e6b7a91 3c5d9e1f7b2a4680
```

Columns are template id, count, maximum severity, first timestamp, last
timestamp, and the masked template — followed by exemplar event IDs you can
look up directly. This is the cheapest possible sanity check that ingestion
found the right thing, and it costs no tokens.

### 4. Analyze

```bash
sift analyze hartford-oom --until 2026-05-11T06:00:00Z --top-clusters 15
```

```
Clusters: 214 (214 labelled)
Hypotheses: 4
Run 'sift show hypotheses' to view them
```

This is the whole triage slice in one command:

1. **Embed** — each template group's exemplar text is embedded via
   `/v1/embeddings`.
2. **Cluster** — HDBSCAN over the embeddings, with an agglomerative
   fallback. Synonymous templates that survived masking get merged here.
3. **Label** — each cluster is given a short human-readable label by the
   generation model. Skip this with `--no-label` and clusters keep their raw
   signature instead; it is the fastest way to cut inference time when you
   only care about hypotheses.
4. **Rank by salience** — clusters are scored partly by proximity to the
   incident time. `--top-clusters` (default 12) caps how many reach the
   prompt.
5. **Hypothesise** — the top clusters, their evidence, and (for
   MicroStrategy cases) deterministic MCM facts are sent to the model, which
   must cite event IDs it was actually shown.

Everything in steps 1–3 is persisted inside a single transaction. If the
embed call fails partway, the run rolls back to zero clusters and zero
vectors — you never end up with a half-clustered case.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--until <ISO 8601>` | Bounds the ranked clusters **and** sets the salience incident-time anchor. Omitted, the anchor is the case-end timestamp. |
| `--since <ISO 8601>` | Lower bound on ranked clusters. |
| `--top-clusters <N>` | How many top-salience clusters feed the prompt (default 12). |
| `--hint "<text>"` | Operator context appended to the prompt verbatim. Never parsed as a time — put times in `--until`. |
| `--no-label` | Skip LLM cluster labelling. |
| `--kb <dir>` | Index a directory of runbooks/RCAs and thread the nearest chunks into the prompt as **non-citable** reference material. |
| `--model <id>` | Override the model id for **both** roles for this run. |
| `--i-know-what-im-doing` | Permit a non-loopback, non-RFC1918 endpoint. |

`--until` deliberately carries two jobs (window bound and incident anchor) to
keep the flag surface small; this is recorded in
[ADR 0005](decisions/0005-analyze-exit-codes.md).

A note on `--kb`: knowledge-base chunks are reference material, not evidence.
The model may use them to reason but cannot cite them — only real event IDs
from the case count as citations.

### 5. Report

```bash
sift report hartford-oom --out triage.md
```

Or straight to stdout, or as JSON, or as PDF:

```bash
sift report hartford-oom
sift report hartford-oom --format json --out triage.json
sift report hartford-oom --format pdf --out triage.pdf   # --out is required for pdf
```

`report` constructs no inference client and makes no network call. Given an
identical `case.db` it is byte-deterministic, so it is safe to regenerate as
often as you like.

## How to read a triage report

A Markdown report has a fixed set of sections, in this order.

### The DEGRADED banner

If present, it sits directly under the title:

> **DEGRADED RUN** — some hypotheses are FLAGGED (invalid citations) or raw
> model output was persisted; treat flagged rows with care.

This means the *analyze* run that produced the data could not be fully
validated. The render itself succeeded — see
[Exit codes](#exit-codes) for why `report` still exits 0.

### Executive summary

One line: how many ranked hypotheses, across how many clusters, and how many
are FLAGGED. If the FLAGGED count is not zero, read the flagged hypotheses
last and with suspicion.

### Ranked hypotheses

Each hypothesis renders as:

```markdown
### 1. Cube cache growth exhausted the MCM working-set budget  (high, OK)

The Memory Contract Manager began denying allocations at 04:12 after …

*Confidence reasoning:* Three independent signals agree on the same window …
*Contradicting evidence:* No corresponding rise in report execution volume …

*Suggested next steps:*
- Compare cube cache size against MaxMemoryConsumption
- …

Cites: [evt:8f2a1c0d4e6b7a91] [evt:3c5d9e1f7b2a4680]
```

The heading carries three things: the rank, the title, and a
`(confidence, marker)` pair.

- **Confidence** is `high`, `medium` or `low` — the model's own assessment,
  explained in *Confidence reasoning*. It is not a calibrated probability.
  Treat it as a reading order, not a number.
- **The marker** is `OK` or `FLAGGED`. This is the load-bearing one.

**`OK`** means every event ID this hypothesis cites was in the set actually
shown to the model, and exists in the case store. The citations are
verifiable, and each `[evt:…]` links straight to the evidence appendix.

**`FLAGGED`** means at least one citation did not survive validation — the
model referenced an event it was not shown, or one that does not exist. Sift
regenerates once when this happens; if the regenerated output still fails,
the hypothesis is persisted **and marked**, never silently accepted or
silently dropped. A flagged hypothesis may still be a good hypothesis, but
its evidence trail is broken: verify every claim against the appendix by hand
before acting on it.

*Contradicting evidence* and *Suggested next steps* appear only when the
model supplied them.

### Raw model output (unvalidated)

This section appears only after a hard degradation — the model output could
not be schema-validated even after one repair round-trip, so zero
schema-valid hypotheses were persisted. Rather than losing the output, the
raw text is stored and shown here, fenced and byte-capped. It is the same
"nothing disappears silently" rule applied to the model itself.

### Evidence appendix

Every cited event, sorted by ID, with an anchor so `[evt:…]` citations link to
it:

```markdown
#### `evt:8f2a1c0d4e6b7a91`
DSSErrors_2026-05-11.log:88231-88247 · error

```
[2026-05-11 04:12:07] Memory Contract Manager denied request …
```
```

Provenance is `source_file:line_start-line_end · severity`. That is the whole
point of the tool — you can open the original file at that line and see the
bytes for yourself. Very long raw blocks (stack traces, MCM dumps) are
truncated with an explicit `… [truncated N → M bytes]` marker.

### Cluster inventory, Timeline, Unexplained signals

The cluster table gives cluster id, event count, maximum severity and label —
the shape of the case beyond the top-ranked hypotheses. **Unexplained
signals** are things the model saw but could not fold into any hypothesis;
they are frequently the most interesting part of the report on a hard case.

### Run metadata

Model, prompt hash, embedding model, degraded yes/no, generated-at. The
prompt hash is what makes a run reproducible — same case, same config, same
model, same hash, same output.

## Inspecting intermediate state with `sift show`

`sift show <case> <target>` takes exactly three targets: `events`,
`clusters`, `hypotheses`. Filters are `--filter key=value`, repeatable, and
AND-combined. A bad or duplicated key fails loudly (exit 2) rather than
quietly returning nothing.

### `show events`

Keys: `severity`, `source`, `file`, `since`, `until`, `limit`.

```bash
sift show hartford-oom events --filter severity=fatal --filter limit=20
sift show hartford-oom events --filter file=DSSErrors --filter since=2026-05-11T04:00:00Z
sift show hartford-oom events --filter source=eustack
```

Output is `event_id  timestamp  severity  file:line  message`. Valid
severities are `fatal`, `error`, `warn`, `info`, `debug`, `unknown`.
`source` matches the adapter name. `file` matches are literal substrings — no
wildcards.

Two semantics worth knowing: a naive (timezone-less) `since`/`until` value is
treated as UTC, and `since`/`until` **exclude events with no timestamp**.
That is a deliberate filter semantic, not silent loss — drop the time filters
to see the untimestamped events.

### `show clusters`

Keys: `severity`, `min-count`, `contains`, `limit`.

```bash
sift show hartford-oom clusters --filter contains=Memory --filter min-count=50
```

Before `analyze`, this renders template groups (with exemplar event IDs).
After `analyze`, it renders the real clusters:
`cluster_id  count  severity_max  label`. The switch is decided on the
unfiltered table, so a filter that excludes every cluster shows zero rows
rather than silently falling back to the template-group view.

If you see `Warning: template groups are stale (last ingest did not
complete)`, an ingest was interrupted between committing events and
rebuilding the groups. Re-run `sift ingest`.

### `show hypotheses`

No filters — it returns the whole ranked set.

```bash
sift show hartford-oom hypotheses
```

```
1  high    OK       Cube cache growth exhausted the MCM working-set budget
    cites: 8f2a1c0d4e6b7a91 3c5d9e1f7b2a4680
2  medium  FLAGGED  Connection pool exhaustion under report load
    cites: aa11bb22cc33dd44
```

Three responses distinguish three different states, and the difference
matters:

- `No hypotheses yet; run 'sift analyze' first` — analyze has genuinely never
  run on this case.
- `No schema-valid hypotheses; the last analyze degraded and persisted raw
  model output…` (on stderr) — analyze **did** run and hard-degraded. Run
  `sift report` to see the banner and the raw output.
- Rows, plus a stderr warning that the last analyze degraded — some rows are
  FLAGGED.

Warnings go to stderr and data to stdout, so piping `sift show` into another
tool stays clean.

## Adapter overrides: when you need them

Ingestion is adapter-driven. Each adapter sniffs a file, returns a
confidence, and the highest scorer wins; anything unrecognised falls back to
`genericlog` rather than being dropped. Four adapters ship: `dsserrors`,
`eustack`, `journald`, `genericlog`.

Auto-detection is right nearly always. Override it when it is not:

```bash
sift new my-case --input ./artefacts \
  --adapter '*.log=dsserrors' \
  --adapter 'stacks_*.txt=eustack'
```

The spec is `glob=adapter-name`, and `--adapter` is repeatable. The **last**
`=` splits the spec, so a glob containing `=` still works. Overrides are
validated at `sift new` — a typo'd adapter name fails immediately rather than
mid-ingest — and persisted into the case, so `sift ingest` reuses them
without you repeating the flags.

You need an override when:

- **A file lands on `genericlog` that shouldn't.** The tell is `source=genericlog`
  in `sift show events` for a file you know is a DSSErrors log, usually
  together with mediocre coverage. Domain adapters extract structured fields
  (SIDs, OIDs, thread IDs) and handle multi-line records as single events;
  `genericlog` treats every line as its own event, which shreds stack traces
  and MCM blocks.
- **A non-standard filename defeats the sniffer.** Renamed, rotated, or
  concatenated exports frequently look wrong on the first few bytes.
- **Coverage is unexpectedly low.** Below ~95% on a file you know the format
  of usually means the wrong parser is trying.

Persistent overrides for file patterns you always see belong in
`config.toml` instead; CLI flags win over config per glob. See
[CONFIGURATION.md](CONFIGURATION.md).

## MCM memory-pressure forensics

For MicroStrategy cases, `sift mcm` produces a quantitative Memory Contract
Manager analysis. Everything in it is computed from the log text — no figure
is model-authored, and the command makes no network call:

```bash
sift mcm hartford-oom
```

```
Analysed 2 MCM denial episodes; wrote mcm_report.md + mcm_attribution.csv to
/home/you/.local/share/sift/hartford-oom/mcm
  Episode 1: critical — physical memory at 96.2% of HWM at denial time
  Episode 2: warn — working-set offload triggered without recovery marker
```

It **always** writes both files into `<case>/mcm/`:

- `mcm_report.md` (or `mcm_report.json` with `--format json`) — a
  timeline-first narrative: episode lifecycle first, then diagnostic flags,
  then the memory breakdown.
- `mcm_attribution.csv` — per-OID, per-Source and per-SID memory attribution
  in one file with a `dimension` column. Each row carries the owning event
  IDs, so attribution stays traceable to source evidence.

Flags are graded `info` / `warn` / `critical`. Thresholds and the lead-up
window are **configuration-only** — there is no per-run CLI knob, deliberately,
so the same case and configuration always yield the same bundle. Tune them
under `[mcm.thresholds]` in `config.toml`.

`sift mcm` and `sift analyze` are complementary, not alternatives. The same
deterministic MCM facts are also spliced into the triage prompt as cited
evidence, so a MicroStrategy case's hypotheses can reference real memory
figures instead of inventing them. Running `mcm` gives you the full
quantitative bundle; running `analyze` gives you the narrative that uses it.

An empty case (no MCM episodes found) still writes the bundle and exits 0.

## Re-running stages and idempotency

Event identity is `sha256(source_file, byte_offset)[:16]`. That single fact
governs all re-run behaviour:

- **`sift ingest` is idempotent.** Re-running against the same snapshot adds
  zero events; the summary reports `0 new`. Safe to run after an interrupted
  ingest.
- **New files appearing in the input directory simply add events.** You can
  drop another artefact in and re-ingest.
- **Renamed files produce duplicates.** Identity is `source_file` +
  `byte_offset`; renaming a file changes the first half. This is a documented
  limitation, not a bug — if the snapshot has changed materially, collect it
  into a new case rather than mutating an existing one.
- **`sift analyze` re-clusters from scratch.** It is not incremental. Re-run
  it after ingesting more events, after changing the embedding model, or with
  different `--since` / `--until` / `--top-clusters` to re-rank the same
  case around a different incident time. Each run replaces the previous
  clusters and hypotheses.
- **`sift report` and `sift mcm` are pure reads.** Run them as often as you
  like, with the backend down.

Determinism holds across runs: an identical case, config, model and seed
produce byte-identical JSON output, modulo timestamps. The recorded prompt
hash in the report's run metadata is how you confirm two runs used the same
prompt.

To delete a case, delete its directory. A clean command exit checkpoints the
write-ahead log, so the directory holds only `case.db` (plus `mcm/` if you
ran `sift mcm`).

## Exit codes

The contracts differ per command, deliberately. Automation can branch on them
without parsing stdout.

### `sift analyze` — 0 / 3 / 1 / 2

| Exit | Meaning |
| --- | --- |
| `0` | Success — hypotheses generated, every citation valid. |
| `3` | **Degraded** — ran to completion, but repair failed or a citation was still invalid. Output persisted and FLAGGED. |
| `1` | Failure — inference transport error, egress-guard refusal, or corrupt/absent `case.db`. Nothing new persisted. |
| `2` | Usage error (Typer/Click), including a malformed `--since` / `--until`. |

Exit 3 is the signal that says *review this — it is flagged, not clean, and
not broken*. Full rationale in
[ADR 0005](decisions/0005-analyze-exit-codes.md).

### `sift report` — 0 / 1 / 2

| Exit | Meaning |
| --- | --- |
| `0` | Rendered — **including a degraded case**. |
| `1` | No analysis to report, a render or `--out` write failure, or `--format pdf` without the `sift[pdf]` extra / pango. |
| `2` | Usage error, including an unknown `--format` value. |

`report` has no code 3. It reads a prior verdict rather than producing one; a
degraded case still renders successfully, and the degradation is communicated
by the in-document banner and FLAGGED rows, not by the exit code. See
[ADR 0007](decisions/0007-report-exit-codes.md).

### `sift mcm` — 0 / 1 / 2

`0` bundle written (including an empty case), `1` missing case or write
failure, `2` bad `--format`.

### `sift ingest`

`0` if every file parsed; `1` if any file failed (after ingesting everything
that did parse); `1` on disk exhaustion, with zero events committed and the
transaction rolled back.

### `sift eval`

`0` when every metric aggregate clears its floor and no case failed; `1` on a
metric regression, a case that could not run, or a negative case emitting a
confident hypothesis; `2` for a missing suite directory or unreadable
thresholds file. The advisory `--judge` score never affects the gate.

Exit `2` is reserved for usage errors everywhere and is never reused for a
semantic outcome.

## Troubleshooting

### `embeddings unsupported on this model/recipe`

The most common Lemonade failure. Your model was loaded via an ONNX/OGA
recipe — it lists in `/v1/models` but cannot embed. Load a `llamacpp` or
`flm` recipe embedding model instead, or, on llama.cpp, start a second
`llama-server` with `--embeddings`. Never infer embedding support from the
model listing; only a real round-trip reveals this, which is exactly what
`sift doctor` performs.

### `generation endpoint … unreachable` / `embeddings endpoint … unreachable`

The server is not running, is bound to a different interface, or is on a
different port. Check the port explicitly — Lemonade's current default is
13305, and older documentation says 8000. Confirm by hand:

```bash
curl http://127.0.0.1:8080/v1/models
```

### The endpoint is refused before any request is made

Sift's egress guard rejects any base URL that is not loopback or RFC1918,
at client construction. If you genuinely need a private-network endpoint that
the guard rejects, `--i-know-what-im-doing` overrides it — but read
[the egress guard section of CONFIGURATION.md](CONFIGURATION.md) first, and
understand that you are removing the one structural guarantee that customer
diagnostic data cannot leave the machine.

### `embedding dimension mismatch`

The case index was built with a different embedding model. Either point at
the original embedding model, or start a new case. Sift hard-fails rather
than mixing vector spaces. `sift doctor <case>` catches this before you spend
an analyze run on it.

### `embedding/clustering failed`

Usually an oversized input. Real DSSErrors logs contain MCM memory dumps of
16 KB or more, which exceed a typical 8192-token embedding context. Sift caps
embedding inputs at `embeddings.max_input_chars` (default 8000) — if you have
lowered it, or your model has a smaller context, raise or lower it to match.
See [CONFIGURATION.md](CONFIGURATION.md).

### `Nothing to cluster; run 'sift ingest' first`

Zero template groups. Either ingest has not run, or it parsed nothing. Check
with `sift show <case> events --filter limit=5`.

### Empty or poor hypotheses

Hypothesis quality is a function of the generation model. A very small or
unstable model may return empty completions or output that fails schema
validation, which degrades the run (exit 3, DEGRADED banner) without any
fault in the pipeline. Ingestion, clustering, the timeline and the MCM
analysis are all unaffected by the generation model — if those look right and
only the hypotheses are poor, change the model, not the case.

Also worth trying: raise `--top-clusters` if the relevant signal was ranked
out; use `--until` to anchor salience on the real incident moment rather than
the end of the log; add `--hint` with what you already know; point `--kb` at
your runbooks.

### `PDF rendering unavailable`

Install both halves — the Python extra and the system library:

```bash
uv tool install '.[pdf]'
sudo dnf install pango
```

`--format pdf` also requires `--out <path>`; it cannot write to stdout.

### A file failed to parse

`sift ingest` prints `ERROR <file>: <reason>`, continues with the remaining
files, records the failure in the case's coverage metadata, and exits 1. The
failure survives into a later report — the file is never quietly forgotten.
If the reason looks like a format mismatch, try an
[adapter override](#adapter-overrides-when-you-need-them).

## Where to go next

- [CONFIGURATION.md](CONFIGURATION.md) — every `SIFT_*` variable, every
  `config.toml` key, precedence rules, and the egress guard in detail.
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the ingest → cluster → retrieve →
  hypothesise → render pipeline is put together, the adapter protocol, and
  the citation-validation mechanism.
- [DEVELOPMENT.md](DEVELOPMENT.md) — working on Sift itself.
- [TESTING.md](TESTING.md) — the test suite and the `sift eval` golden-case
  harness.
- [Architecture decision records](decisions/) — why things are the way they
  are.
