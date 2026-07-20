<!-- generated-by: gsd-doc-writer -->
# Configuration

Sift resolves every setting through one function, `load_config()` in
`src/sift/config.py`, and validates the merged result once with Pydantic. There is no
second configuration path: if a knob is not in the table below, it is not configurable.

## Precedence

Later layers win, per key:

```
CLI flags  >  SIFT_* environment  >  $XDG_CONFIG_HOME/sift/config.toml  >  defaults
```

Two details matter in practice:

- **Nested merges are deep.** A flag that sets `generation.model` does not discard a
  `generation.base_url` supplied by TOML or the environment — sections are merged per
  field, not replaced wholesale.
- **Unknown keys are a hard error.** Every config model sets `extra="forbid"`, so a
  typo such as `bas_url` fails loudly at startup rather than being silently ignored.
  A malformed `config.toml` also raises rather than falling back to defaults.

The config file is read from `$XDG_CONFIG_HOME/sift/config.toml`, which is
`~/.config/sift/config.toml` unless `XDG_CONFIG_HOME` is set. It is optional; if it does
not exist, defaults and environment alone apply.

## Reference

Every row corresponds to a field in `src/sift/config.py`. Where the "CLI flag" column is
empty, there is deliberately no per-run flag.

### Top level

| TOML key | Env var | CLI flag | Type | Default | Meaning |
|---|---|---|---|---|---|
| `data_dir` | `SIFT_DATA_DIR` | `--data-dir` | path | `$XDG_DATA_HOME/sift` (i.e. `~/.local/share/sift`) | Root directory holding one subdirectory per case, each with its `case.db`. |
| `timezones` | — | — | table of `glob = "IANA zone"` | `{}` | Per-file timezone attribution for naive log timestamps. Zone names are validated at config load, so a bad name fails before ingest starts, not mid-run. |
| `adapters` | — | `--adapter glob=name` (on `sift new`) | table of `glob = "adapter"` | `{}` | Force a named adapter for files matching a glob. Known adapters: `genericlog`, `journald`, `dsserrors`, `eustack`. |

`--data-dir` is accepted by every case-scoped command (`new`, `ingest`, `show`,
`analyze`, `report`, `mcm`, `eval`, `doctor`).

Adapter overrides passed to `sift new --adapter` are persisted into the case and reused
by `sift ingest`. At ingest time flag globs are merged ahead of `[adapters]` globs, so a
flag glob always wins the first-match detection order.

### `[generation]` — the chat-completions endpoint

| TOML key | Env var | CLI flag | Type | Default | Meaning |
|---|---|---|---|---|---|
| `generation.base_url` | `SIFT_GENERATION_BASE_URL` | — | str | `http://localhost:13305/v1` | OpenAI-compatible base URL for `/chat/completions`. |
| `generation.model` | `SIFT_GENERATION_MODEL` | `--model` | str \| null | `null` | Model identity. `null` sends no `model` field and lets the server use whatever it has loaded. |
| `generation.timeout` | `SIFT_GENERATION_TIMEOUT` | — | float | `60.0` | Per-request HTTP timeout, in seconds. |
| `generation.retries` | `SIFT_GENERATION_RETRIES` | — | int | `2` | Extra attempts after the first, on connect error, timeout or HTTP 5xx. |
| `generation.backoff_base` | — | — | float | `0.5` | Exponential backoff base in seconds: attempt *n* sleeps `base * 2**n`. TOML-only. |
| `generation.context` | `SIFT_GENERATION_CONTEXT` | — | int \| null | `null` | Fallback generation context window (tokens) used only when the server does not expose llama.cpp's `/props` (e.g. Lemonade). Set it to the model's actual loaded context so the prompt budget trims to fit; otherwise an over-context prompt is rejected. `/props`-reported `n_ctx` always wins. |

### `[embeddings]` — the embeddings endpoint

| TOML key | Env var | CLI flag | Type | Default | Meaning |
|---|---|---|---|---|---|
| `embeddings.base_url` | `SIFT_EMBEDDINGS_BASE_URL` | — | str | `http://localhost:13305/v1` | OpenAI-compatible base URL for `/embeddings`. |
| `embeddings.model` | `SIFT_EMBEDDINGS_MODEL` | `--model` | str \| null | `null` | Embedding model identity; `null` defers to the server's loaded model. |
| `embeddings.timeout` | `SIFT_EMBEDDINGS_TIMEOUT` | — | float | `60.0` | Per-request HTTP timeout, in seconds. |
| `embeddings.batch_size` | `SIFT_EMBEDDINGS_BATCH_SIZE` | — | int | `64` | Maximum inputs per `/embeddings` request. |
| `embeddings.max_input_chars` | `SIFT_EMBEDDINGS_MAX_INPUT_CHARS` | — | int | `8000` | Each embedding input is truncated to this many characters before sending. |

`max_input_chars` exists because a single large multi-line record — an MCM memory dump,
a full stack trace — can exceed the embedding model's context window and cause the
backend to reject the entire batch, aborting `sift analyze`. Roughly 8000 characters is
2000–2700 tokens, comfortably inside an 8192-token context; lower it for a small-context
model (bge-small, for example, has a 512-token context). Embedded text is never cited,
so prefix truncation is safe. When the server rejects a batch, Sift's error message
names this knob and its current value.

### `[clustering]` — semantic clustering

Configurable via `config.toml` only: there are no environment variables and no CLI flags
for these, which keeps a run reproducible from the case plus the config file.

| TOML key | Type | Default | Meaning |
|---|---|---|---|
| `clustering.algorithm` | str | `"hdbscan"` | `"hdbscan"`, or `"agglomerative"` to force the cosine-average fallback. |
| `clustering.min_cluster_size` | int | `2` | HDBSCAN minimum cluster size. Fewer points than this in total routes to the fallback path. |
| `clustering.min_samples` | int | `1` | HDBSCAN `min_samples`. scikit-learn counts the point itself, so this is +1 relative to the standalone `hdbscan` package's semantics. |
| `clustering.epsilon` | float | `0.0` | Passed as `cluster_selection_epsilon`. |
| `clustering.distance_threshold` | float | `0.3` | Cosine distance threshold for the agglomerative fallback. |

### `[mcm.thresholds]` — MCM diagnostic cut-points

Each entry is a percentage of a high-water mark or total, never an absolute number of
gigabytes — that is what keeps the diagnosis machine-independent. Overrides are
config-only by design: there is no per-run CLI knob, so a report is reproducible from
the case and the config file alone. Each threshold is a `{warn, critical}` pair unless
noted.

| TOML key | Type | Default | Meaning |
|---|---|---|---|
| `mcm.thresholds.working_set_pct_virtual` | pair | `warn = 20`, `critical = 40` | Working set as a percentage of IServer virtual memory. |
| `mcm.thresholds.other_processes_pct_physical` | pair | `warn = 10`, `critical = 20` | Non-IServer processes as a percentage of physical memory. |
| `mcm.thresholds.cube_pct_virtual` | pair | `warn = 25`, `critical = 40` | Cube memory as a percentage of IServer virtual memory. |
| `mcm.thresholds.mmf_pct_of_cube_low` | float | `10` | Below this, MMF coverage of the cube is flagged as underutilised. |
| `mcm.thresholds.smartheap_pool_pct_virtual` | pair | `warn = 5`, `critical = 15` | SmartHeap pool as a percentage of IServer virtual memory. |
| `mcm.thresholds.system_free_headroom_pct` | pair | `warn = 20`, `critical = 5` | Inverted metric — lower free headroom is worse. Values are stored as authored; the grader flips the comparison direction, not the config. |

Omitting the `[mcm.thresholds]` table yields exactly the defaults above.

### Settings that are not in `config.toml`

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `--top-clusters` | `sift analyze` flag | `12` | How many top-salience clusters are fed to the hypothesiser. |
| `--i-know-what-im-doing` | `analyze`, `eval`, `doctor` flag | off | Disables the endpoint egress guard — see below. |
| `--no-label` | `sift analyze` flag | off | Skip LLM cluster labelling; clusters keep their template signature. |
| `--hint`, `--kb`, `--since`, `--until` | `sift analyze` flags | unset | Per-run scoping and prompt context. |
| `--suite`, `--thresholds` | `sift eval` flags | `eval/cases`, `eval/thresholds.toml` | Golden-case suite and the regression gate's floors. The thresholds file is a separate TOML, unrelated to `~/.config/sift/config.toml`. |

The prompt token budget is mostly derived: `sift analyze` reads `n_ctx` from the
generation server's `/props` and falls back to `generation.context` (else 8192 tokens)
when the endpoint or key is absent, reserving 1024 tokens for output. Cluster labelling
uses a fixed 4096-token budget.

The MCM and DSSPerformanceMonitor fact blocks that `sift analyze` folds into the prompt
have no config surface either. Their caps — the number of MCM episodes and the number of
perfmon correlation groups retained (most-severe-first) so a correlation storm cannot
inflate the prompt — and the set of salient perfmon counters are hard-coded module
constants in `src/sift/pipeline/mcm_facts.py` and `src/sift/pipeline/perfmon_facts.py`.
There is deliberately no `[perfmon]` (or `[mcm]` fact-block) table, no `SIFT_PERFMON_*`
environment variable, and no CLI flag; the only MCM knobs exposed to `config.toml` are the
severity cut-points in `[mcm.thresholds]` above.

## Worked example

`~/.config/sift/config.toml`:

```toml
# Where cases live. Optional — defaults to ~/.local/share/sift.
data_dir = "/srv/evidence/sift"

# Attribute naive timestamps per file glob. Zone names are validated at load.
[timezones]
"*/prod-emea/**/DSSErrors*.log" = "Europe/London"
"*/prod-apac/**/DSSErrors*.log" = "Asia/Singapore"

# Force an adapter where sniffing would be ambiguous.
[adapters]
"*/thread-dumps/*.txt" = "eustack"
"*.jsonl" = "journald"

[generation]
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3-30b-a3b"
timeout = 120.0
retries = 3
backoff_base = 0.5

[embeddings]
base_url = "http://127.0.0.1:8081/v1"
model = "nomic-embed-text-v1.5"
batch_size = 32
max_input_chars = 8000

[clustering]
algorithm = "hdbscan"
min_cluster_size = 2
min_samples = 1
distance_threshold = 0.3

[mcm.thresholds]
working_set_pct_virtual = { warn = 15, critical = 35 }
system_free_headroom_pct = { warn = 25, critical = 8 }
```

Overriding for a single run:

```bash
SIFT_GENERATION_MODEL=qwen3-14b sift analyze mycase
sift analyze mycase --model qwen3-14b --top-clusters 20   # flag wins over env
```

## Generation and embeddings are separate endpoints

The two roles have independent `base_url` and `model` settings because they usually
cannot be served by the same process. llama.cpp's `llama-server` treats `--embedding` as
a mode switch: a server started for embeddings serves embeddings only, so a generation
model and an embedding model need two server instances (or a manager such as Lemonade
Server running both).
<!-- VERIFY: llama-server's --embedding flag restricts a server instance to embeddings only -->

Both defaults point at `http://localhost:13305/v1`, which suits a single Lemonade Server
handling both roles. For the two-instance llama.cpp layout, set each `base_url`
explicitly — as the example above does with ports 8080 and 8081.
<!-- VERIFY: 13305 is Lemonade Server's default port in the versions targeted -->

`--model` is a convenience that sets *both* roles' model at once, which is what you want
when a single server is serving both and you are switching models for one run. To pin
the roles independently, use `SIFT_GENERATION_MODEL` and `SIFT_EMBEDDINGS_MODEL`, or the
TOML keys.

Neither `model` has a baked default. Leaving it `null` omits the `model` field from the
request entirely, letting the server use whatever it has loaded. Sift records the model
identity the embeddings server actually reports for provenance, so an unset value still
yields an auditable case.

Note that Lemonade's `/v1/embeddings` support depends on the recipe a model was loaded
with; `sift doctor` performs a real embedding round-trip rather than trusting
`/v1/models`, precisely because listing a model does not prove it can embed.
<!-- VERIFY: Lemonade ONNX/OGA-recipe models list in /v1/models but cannot serve /v1/embeddings -->

## The egress guard

Sift's only permitted network traffic is to the configured local inference endpoints. The
guard (`_assert_local` in `src/sift/llm/client.py`) runs when the inference client is
constructed and checks *both* `base_url` values. It accepts:

- the literal name `localhost`, and any `*.localhost` name;
- any literal IP that is loopback, RFC1918 private, or link-local.

Anything else raises, with a message naming the override. The guard **never resolves
DNS** — resolution is itself egress, and a resolved address can change between the check
and the connection, so a bare hostname is rejected as a string rather than looked up.

To deliberately point Sift at a non-local endpoint, pass `--i-know-what-im-doing`
(accepted by `sift analyze`, `sift eval` and `sift doctor`). It is a break-glass for a
genuinely public endpoint, not a convenience for awkward addressing — if a hostname is
being rejected, the right fix is usually a guard-clean address.

That distinction is why the shipped Podman Quadlet unit (`deploy/sift.container`) uses
`Network=host` with literal loopback addresses:

```ini
Environment=SIFT_GENERATION_BASE_URL=http://127.0.0.1:8080/v1
Environment=SIFT_EMBEDDINGS_BASE_URL=http://127.0.0.1:8081/v1
```

`127.0.0.1` passes the guard as a loopback literal. Podman's magic-DNS name
`host.containers.internal` would be rejected, being neither `localhost`-suffixed nor a
literal IP. Where host networking is undesirable, the guard-clean alternative is a
`*.localhost` alias — `AddHost=infra.localhost:host-gateway` with the base URL targeting
`http://infra.localhost:8080/v1` — which the guard accepts as a string and Podman
resolves at connect time. The rationale is recorded in
`docs/decisions/0011-quadlet-loopback-guard.md`.
<!-- VERIFY: AddHost=...:host-gateway requires Podman 5.3.0+ -->

## PDF output

PDF rendering lives behind an optional extra and is not installed by default:

```toml
[project.optional-dependencies]
pdf = ["markdown==3.10.2", "weasyprint==69.0"]
```

Install it, plus WeasyPrint's system libraries, before using `sift report --format pdf`:

```bash
uv tool install 'sift[pdf]'
sudo dnf install pango          # Fedora; harfbuzz and gdk-pixbuf come with it
```

`--format pdf` also requires `--out <path>` — the renderer writes a file, never stdout.
Both failure modes — the extra missing, and its pango/harfbuzz system libraries missing
at render time — produce the same helpful message rather than a traceback. The PDF is
generated from the Markdown report with URL fetching disabled and a fully inline
stylesheet, so rendering cannot make a network request.

## Troubleshooting

- **`refusing non-local inference endpoint ...`** — the `base_url` host is not
  `localhost`, not `*.localhost`, and not a private/loopback literal IP. Use a literal
  IP or a `*.localhost` alias; use `--i-know-what-im-doing` only if the endpoint really
  is public.
- **`embeddings response has no 'data' list`** — an input exceeded the model's context
  window. Lower `embeddings.max_input_chars` or raise the server's context size.
- **`invalid config file ...`** — the TOML failed to parse. Sift refuses to fall back to
  defaults silently; fix the file.
- **A validation error naming an unexpected key** — `extra="forbid"` caught a typo.
  Check the key against the reference tables above.
- **`invalid timezone ... not a known IANA zone name`** — a `[timezones]` value is not a
  zone the system's tz database knows.
</content>
</invoke>
