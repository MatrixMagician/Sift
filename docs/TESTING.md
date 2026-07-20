<!-- generated-by: gsd-doc-writer -->
# Testing

Sift's test suite is the mechanism that keeps three load-bearing invariants honest:
**zero network egress**, **determinism**, and **citation validity**. Everything below
is about running, reading, and extending that suite.

## Test framework and setup

- **Framework:** pytest (>= 9.1.1, declared in the `dev` dependency group of
  `pyproject.toml`).
- **Setup:** `uv sync` — nothing else. No servers, no fixtures to download, no
  network. The whole default suite (509 test functions across `tests/`) runs offline.
- **Config:** `[tool.pytest.ini_options]` in `pyproject.toml`. `testpaths = ["tests"]`
  and `addopts = "-m 'not perf and not live and not packaging'"`.

`respx` is declared in the dev group, but the suite in practice injects fakes with
`httpx.MockTransport` rather than `respx` — see *The zero-network rule* below.

## Running tests

```bash
uv run pytest                                  # the default suite (offline, fast)
uv run pytest tests/test_dsserrors.py          # a single file
uv run pytest tests/test_dsserrors.py -k mcm   # a single file, selected by substring
uv run pytest -k "determinism or citation"     # selection across the whole suite
uv run pytest -x -q                            # stop at first failure, quiet
```

### Marked suites (excluded by default)

Three markers are declared in `pyproject.toml` and filtered out by `addopts`. An
explicit `-m` on the command line overrides that filter:

| Command | What it runs |
|---------|--------------|
| `uv run pytest -m perf` | 100 MB-scale ingest gates (`tests/perf/test_perf_ingest.py`) |
| `uv run pytest -m live` | integration tests against a real loopback inference server |
| `uv run pytest -m packaging` | offline `uv tool install` smoke + Quadlet dry-run (`tests/test_packaging.py`) |

`-m live` is the only path on which real sockets are permitted — see below.

## The quality gate

"Done" for any milestone means all three of these are clean. A red gate blocks the
next milestone:

```bash
uv run ruff check
uv run pyright
uv run pytest
```

`pyright` runs in `strict` mode over `src` and `tests` — test code is type-checked to
the same standard as production code. There is no CI workflow directory in the
repository; the gate is run locally (and by the `sift eval` golden-case harness for
hypothesis quality).

## Test layout

`tests/` is flat — one module per unit of behaviour, not a package (pytest's prepend
import mode puts `tests/` on `sys.path`, which is why `pyproject.toml` declares
matching `extraPaths` execution environments for pyright).

| Area | Files | Covers |
|------|-------|--------|
| Core models & store | `test_models.py`, `test_store.py`, `test_store_vectors.py`, `test_disk_full.py` | `event_id` derivation, SQLite migrations, sqlite-vec vector table, disk-exhaustion behaviour |
| Adapters | `test_adapters_detect.py`, `test_dsserrors.py`, `test_eustack.py`, `test_journald.py`, `test_genericlog.py`, `test_configurable_adapter.py` | sniff/parse contract, registry + override resolution, per-format parsing |
| MCM analysis | `test_mcm.py`, `test_mcm_facts.py`, `test_mcm_report.py`, `test_mcm_analyze.py`, `test_cli_mcm.py` | episode detection, memory breakdown, attribution, fact rendering into `analyze` |
| Pipeline | `test_dedup.py`, `test_cluster.py`, `test_salience.py`, `test_kb_retrieval.py`, `test_kb_analyze.py`, `test_budget.py` | masking/templating, HDBSCAN clustering, ranking, KB retrieval, token budgeting |
| LLM boundary | `test_llm_client.py`, `test_hypothesise.py` | endpoint guards, retries, llama.cpp `response_format` shape, schema + citation enforcement |
| Rendering | `test_render_markdown.py`, `test_render_json.py`, `test_render_pdf.py`, `test_report_determinism.py`, `test_cli_report.py` | report output and byte-identity |
| CLI & end-to-end | `test_cli.py`, `test_analyze.py`, `test_doctor.py`, `test_acceptance.py` | subcommand behaviour, exit codes, whole-pipeline acceptance |
| Eval harness | `test_eval_truth.py`, `test_eval_harness.py`, `test_eval_thresholds.py`, `test_eval_judge.py`, `test_eval_cases.py` | truth loading, metrics, gate/exit codes, advisory judge, the committed golden cases |
| Guards | `test_conftest_network_guard.py`, `test_packaging.py` | the socket guard itself; packaging smoke |
| Perf | `tests/perf/` | `generate_synthetic.py` plus the `perf`-marked 100 MB gate |

Two shared helper modules sit alongside the tests. They are plain modules, imported
by name (`from _report_fixtures import ...`), deliberately **not** conftest fixtures —
`tests/conftest.py` is owned by the first plan and stays minimal:

- `tests/_report_fixtures.py` — `build_analysed_case()` / `open_case()`: builds a real
  analysed `case.db` offline, then plants exact hypotheses and `triage_*` run-meta via
  the public store API so renderers can be tested against controllable citations,
  FLAGGED verdicts and the degraded flag.
- `tests/_eval_fixtures.py` — `single_case_suite()`, `eval_handler()`, `patch_http()`,
  `GOOD_HYPSET`: the offline eval-harness rig.

## Shared fixtures (`tests/conftest.py`)

Two **autouse** fixtures apply to every test; neither needs to be requested.

### `_isolate_dirs`

Redirects `XDG_DATA_HOME` and `XDG_CONFIG_HOME` into `tmp_path` and deletes every
`SIFT_*` environment variable. Case paths derive from `XDG_DATA_HOME`, so no test can
read or write your real home directory, and no ambient `SIFT_*` setting can leak into
config precedence.

One consequence worth knowing: a test that shells out to a tool which itself reads XDG
(notably `uv tool install` in `test_packaging.py`) must restore or pop those variables
in that subprocess's own env, and isolate via tool-specific flags (`UV_TOOL_DIR`,
`UV_TOOL_BIN_DIR`) instead.

### `_no_network`

Monkeypatches `socket.socket.connect` to raise `RuntimeError` for every test **except**
those carrying the `live` marker. See the next section.

## The zero-network rule

Sift never touches the network in tests. This is a hard project rule, enforced in
three layers:

1. **The socket guard.** `_no_network` in `tests/conftest.py` replaces
   `socket.socket.connect` with a function that raises:

   > `Network access is forbidden in tests (zero-network-in-tests rule, see CLAUDE.md).
   > Inject a fake instead.`

   `live`-marked tests are exempted — they exist precisely to reach the configured
   loopback inference endpoint, so patching their socket would defeat their purpose.
   The default suite never carries the marker and stays fully socket-blocked.
   Both halves of that contract are themselves tested, in
   `tests/test_conftest_network_guard.py`
   (`test_default_suite_socket_guard_active`, `test_live_marked_tests_bypass_socket_guard`).

2. **The injection seam.** `src/sift/llm/` is the only module that talks HTTP, and the
   `httpx.Client` used by `analyze`/`eval` is built by `sift.cli._make_http_client`.
   Tests monkeypatch that one factory:

   ```python
   def patch_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
       def _factory(timeout: float) -> httpx.Client:
           return httpx.Client(
               transport=httpx.MockTransport(handler), timeout=httpx.Timeout(timeout)
           )
       monkeypatch.setattr("sift.cli._make_http_client", _factory)
   ```

   Tests that construct an `InferenceClient` directly pass an `httpx.Client` bound to a
   `MockTransport` the same way. Around 42 call sites across the suite use
   `httpx.MockTransport`.

3. **The fake OpenAI-compatible server.** There is no separate server process — the
   "server" is a request handler function. `_eval_fixtures.eval_handler()` is the
   canonical example and serves the three calls the pipeline makes:

   - `/v1/embeddings` → a deterministic pseudo-embedding per input text
     (`sha256(text)` bytes scaled to 8 floats), so identical text always yields an
     identical vector. That determinism is what makes the N=2 determinism check
     byte-identical offline.
   - `/v1/chat/completions` **without** `response_format` → the cluster-label call;
     returns `{}` so clusters keep their signatures.
   - `/v1/chat/completions` **with** `response_format` → the generation call; returns a
     `HypothesisSet` JSON body (`GOOD_HYPSET` by default, overridable via
     `eval_handler(hyp_content=...)` to plant malformed JSON, bad citations, etc.).
   - anything else → `404`.

   `tests/test_llm_client.py` uses the same technique at a lower level to exercise
   retries, 4xx-vs-5xx behaviour, dimension mismatches, non-finite embeddings, the
   llama.cpp-shaped `response_format`, and `/props` / `/tokenize` feature detection.

If you find yourself needing a real endpoint, the answer is a `live`-marked test, not
an unblocked socket.

## Adapter tests and sample artefacts

Sample artefacts live under `tests/fixtures/<adapter>/`:

```
tests/fixtures/dsserrors/node1/DSSErrors.log, DSSErrors.bak00, DSSErrors.bak01
tests/fixtures/dsserrors/node2/DSSErrors.log
tests/fixtures/eustack/threaddump.txt
tests/fixtures/journald/basic.json, field_types.json
tests/fixtures/mcm/hartford_deny_slice.log, hartford_deny_double.log,
                   hartford_deny_predenial_multisid.log, hartford_two_episode_partial.log
```

Adapter tests bind them with a module-level constant and a small local helper, e.g. in
`tests/test_dsserrors.py`:

```python
FIXTURES = Path(__file__).parent / "fixtures" / "dsserrors"

def run_parse(root, relname, tz_overrides=None) -> tuple[list[Event], ParseStats]:
    adapter = DsserrorsAdapter()
    adapter.input_root = root
    ...
    events = list(adapter.parse(root / relname, "case1"))
    assert adapter.last_stats is not None
    return events, adapter.last_stats
```

The same file also defines `assert_span_partition(events, total_bytes)`, which asserts
byte spans are contiguous from 0, non-overlapping, and sum to the decompressed byte
count. That is the executable form of the "nothing disappears silently" invariant: no
region of an input file may be unaccounted for.

Note the two-directory `dsserrors` fixture layout: `node1/` and `node2/` exist to test
per-node tagging derived from the subdirectory, and
`test_node_omitted_for_root_level_file` covers the case where the file sits at the root
and there is no subdirectory to name a node after.

### Adding a test for a new adapter

1. Drop a small, synthetic sample under `tests/fixtures/<name>/`. Keep it minimal and
   free of real customer data; hand-cut a slice rather than committing a whole log.
2. Create `tests/test_<name>.py` with a `FIXTURES` constant and a `run_parse` helper
   in the style above.
3. Cover, at minimum:
   - **sniff** — high confidence on your own format, and ~zero on plain prose
     (`test_sniff_dsserrors_head_high` / `test_sniff_plain_text_zero` are the pattern).
   - **parse coverage** — `assert_span_partition`, plus an unparseable region emitting
     a `severity="unknown"` event rather than vanishing.
   - **multi-line records** — one logical record is one `Event`, including the
     truncated-at-EOF case and the line-cap case.
   - **severity mapping** — no emitted severity outside the canonical six-value set.
   - **timestamps** — timezone handling; the timeline must not be causally inverted.
4. Add the registration/detection cases to `tests/test_adapters_detect.py`. That module
   exposes a fixture yielding the mutable `REGISTRY` (saved and restored afterwards),
   so you can assert that your adapter wins on high confidence, that a tie at
   `SNIFF_THRESHOLD` falls back to `genericlog`, and that a `--adapter glob=name`
   override beats a losing sniff score.

Registration itself should be the only change outside your new module.

## Determinism testing

Determinism is asserted at every level of the stack, not just end-to-end:

- **`event_id` stability** — `tests/test_models.py`: `test_event_id_golden_value`
  (a frozen expected hash), `test_event_id_shape_is_16_lowercase_hex`, and
  `test_event_id_nul_separator_disambiguates` (the NUL separator prevents
  `source_file`/`byte_offset` concatenation collisions).
- **Idempotent re-ingest** — `test_store.py::test_reingest_idempotent`,
  `test_cli.py::test_reingest_adds_zero_events`,
  `test_dedup.py::test_reingest_rebuild_idempotent`, and
  `test_acceptance.py::test_acceptance_idempotent_reingest`. Re-ingesting the same
  input adds zero rows.
- **Compression-invariance** — `test_journald.py::test_event_id_plain_vs_gzip_identical`:
  the same content yields the same ids whether read plain or gzipped.
- **Stable ordering** — `test_store.py::test_query_events_deterministic_order`,
  `test_salience.py::test_ties_break_by_cluster_id_and_are_deterministic`,
  `test_cluster.py::test_cluster_assignment_is_deterministic`,
  `test_kb_retrieval.py::test_index_kb_is_deterministic`.
- **Byte-identical output** — `tests/test_report_determinism.py`:
  `test_two_runs_byte_identical_after_normalisation`, plus tests pinning exactly which
  fields the normaliser drops (the volatile timestamps/paths) and asserting it does not
  mutate its input. MCM has its own byte-identity tests
  (`test_mcm.py::test_determinism_byte_identical`,
  `test_mcm_report.py::test_json_deterministic` / `test_csv_deterministic`,
  `test_mcm_analyze.py::test_mcm_block_deterministic`).
- **Prompt stability** — `test_hypothesise.py::test_determinism_prompt_hash`: the same
  case and config produce the same prompt.

When you add a feature that touches ordering, hashing, or serialisation, add a
determinism test alongside it. "Runs twice, same bytes" is cheap to assert and
expensive to retrofit.

## Citation validation (the anti-hallucination guard)

Every hypothesis's `supporting_event_ids` must exist in the case store. The enforcement
ladder — validate, regenerate once, then flag — is covered in
`tests/test_hypothesise.py`:

| Test | Asserts |
|------|---------|
| `test_citation_valid_golden` | valid citations pass through untouched |
| `test_regenerate_badcite_then_good` | one invalid-citation response triggers exactly one regeneration, which then succeeds |
| `test_flagged_badcite_twice` | two consecutive invalid-citation responses degrade to a FLAGGED result — no crash, no silent acceptance |
| `test_schema_valid_good_path` / `test_repair_bad_then_good` / `test_degrade_bad_json_twice` | the parallel JSON-schema ladder: validate → one repair round-trip → degrade gracefully |
| `test_malformed_generation_no_choices` / `_absent_content` / `_empty_content` | malformed server responses never crash the pipeline |
| `test_transport_error_is_failed_not_persisted` | a transport error marks the run failed rather than persisting partial output |
| `test_atomic_persist_rolls_back` | a failed persist rolls back rather than leaving half a hypothesis set |
| `test_successful_reanalyze_clears_stale_raw` | a successful re-run clears previously persisted raw degraded output |

The harness scores the same invariant as a suite metric: `citation_validity_rate`, with
a floor of `1.00`.

## The `sift eval` golden-case harness

`sift eval` runs the committed golden cases through the **real** ingest → cluster →
hypothesise pipeline against a temporary `case.db`, scores four metrics against each
case's frozen ground truth, and gates the suite aggregates against
`eval/thresholds.toml`. It is the CI-shaped signal for hypothesis quality.

```bash
uv run sift eval                          # defaults: --suite eval/cases --thresholds eval/thresholds.toml
uv run sift eval --json                   # machine-readable metric table
uv run sift eval --judge                  # add the advisory LLM-as-judge score (never gates)
uv run sift eval --suite path/to/cases --thresholds path/to/thresholds.toml
```

### What a golden case consists of

A case is a directory under `eval/cases/` with three parts:

```
eval/cases/disk-full/
├── README.md      # prose: the planted scenario and what a good triage run must trace
├── truth.yaml     # frozen ground truth
└── input/         # the raw artefacts sift ingests (system.log)
```

The seven committed cases are `dependency-timeout-mixed-tz`, `disk-full`,
`mcm-denial`, `memory-watermark-cascade`, `negative-no-incident`,
`smtp-rejection-storm`, and `thread-pool-exhaustion`.
`tests/test_eval_cases.py::test_suite_is_exactly_the_seven_cases` pins that set, and
`test_special_shapes_present` pins the special shapes (the negative case, the mixed-
timezone case, the MCM case).

### The truth file format

`truth.yaml` is parsed with `yaml.safe_load` only (never `yaml.load`/`full_load` — a
code-execution vector at the eval trust boundary) and validated through the `Truth`
Pydantic model in `src/sift/eval/truth.py`, which sets `extra="forbid"` so a typo'd key
fails loudly instead of being silently dropped.

```yaml
root_cause: >
  Prose statement of the planted root cause.
required_evidence:            # regexes, matched case-insensitively against the
  - "ENOSPC|no space left on device"   # clusters fed to the model
acceptable_keywords:          # any-of, case-insensitive, vs hypothesis title + narrative
  - disk
  - space
expect_no_incident: false     # true marks the negative case
```

`required_evidence` and `acceptable_keywords` both default to empty lists;
`expect_no_incident` defaults to `false`.

**Truth files are frozen.** They are authored before any prompt tuning and must never
be edited to make a run pass — a regression has to fail, not be quietly accommodated.

### Metrics and thresholds

Four metrics (`src/sift/eval/metrics.py`), gated against the lower-bound floors in
`eval/thresholds.toml` (`src/sift/eval/thresholds.py::gate`):

| Metric | Floor | Meaning |
|--------|-------|---------|
| `retrieval_hit_rate` | `0.80` | fraction of `required_evidence` patterns actually surfaced to the model |
| `hypothesis_hit_at_k` | `1.00` | a top-k hypothesis hits an `acceptable_keywords` entry |
| `citation_validity_rate` | `1.00` | the anti-hallucination invariant |
| `determinism_stability` | `1.00` | fraction of cases whose N=2 repeated runs are byte-identical |

All four share the "higher is better" direction, so the gate is one uniform
`value >= floor` comparison. The report *displays* `drift = 1 − stability` (the SPEC's
wording) while the gate compares the stability floor — one direction internally, two
labels on the surface (ADR 0010).

The LLM-as-judge (`src/sift/eval/judge.py`, `--judge`) is **advisory only**. Its score
is reported alongside the keyword metrics and never consulted by `gate()`.

### Exit codes

Per `docs/decisions/0010-eval-exit-codes.md`:

| Exit | Meaning |
|------|---------|
| `0` | every keyword-metric aggregate meets its floor, every case ran, and no negative case emitted a confident hypothesis |
| `1` | a metric regressed below its floor; **or** a case could not run (`run_failed`); **or** an `expect_no_incident` case emitted a confident hypothesis; **or** there is no scorable positive case |
| `2` | usage error — a missing/invalid `--suite` path or an unreadable/malformed `--thresholds` file |

The last three exit-1 conditions are the **anti-vacuity rules**, and they are part of
`gate()` itself rather than the CLI. `SuiteResult`'s aggregate helpers exclude
`run_failed` and `expect_no_incident` cases, and an *empty* positive set would average
to a vacuous `1.0` — so a totally broken pipeline could otherwise report a perfect score
and pass. A crashed run is a regression, never a silent exclusion. When changing
anything in the aggregation path, run the real command end to end: a suite showing a
perfect score while a case reads `FAILED` is a red flag, not a pass.

### Adding a new golden case

1. `mkdir -p eval/cases/<case-name>/input` and place the synthetic artefacts in
   `input/`. Keep node names, paths and identifiers synthetic — no real customer data.
2. Write `README.md` describing the planted scenario, what the loud symptoms are, and
   what a good triage run must conclude. Note any special shape (negative case,
   mixed timezone, MCM-sensitive) explicitly.
3. Write `truth.yaml` **before** touching prompts. Set `required_evidence` regexes
   against the evidence text, `acceptable_keywords` against the conclusion you expect,
   and `expect_no_incident: true` if this is a negative case.
4. Update the pinned set in `tests/test_eval_cases.py`
   (`test_suite_is_exactly_the_seven_cases`, and `test_special_shapes_present` if your
   case has a special shape).
5. Add a case-specific offline test if the case guards something particular. The
   `mcm-denial` case is the model here: `test_mcm_denial_case_discovered_and_scored_positive`,
   `test_mcm_denial_ingests_via_dsserrors_autosniff` (the adapter must auto-sniff it,
   no override), and `test_mcm_denial_citation_validity_is_mcm_sensitive` (the case
   genuinely exercises the MCM path rather than passing by accident).
6. Run `uv run sift eval` and confirm exit 0 — then run the full gate.

Use `_eval_fixtures.single_case_suite(tmp_path, case="<name>")` when you want a test to
run against a one-case copy of the suite rather than all of `eval/cases`; the shared
good handler only hits the `memory-watermark-cascade` keywords, so machinery tests are
deliberately decoupled from the real suite's breadth.
