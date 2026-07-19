# Phase 7: Evaluation Harness & Golden Cases - Pattern Map

**Mapped:** 2026-07-18
**Files analysed:** 14 new/modified (6 eval package modules + 1 prompt + CLI stub + thresholds.toml + golden fixtures + tests)
**Analogs found:** 13 / 14 (one file — `truth.yaml` schema — has no in-repo analog; RESEARCH gives the shape)

This phase is a **codebase-internal reuse phase**. Almost every metric is already a property of the persisted `case.db`; the new code sequences existing pipeline calls and reads rows back. Below, each new file names its closest analog with concrete `file:line` excerpts to copy.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/sift/eval/runner.py` | service (orchestrator) | batch | `src/sift/cli.py` analyze body (722–823) + `tests/test_analyze.py::_seed_case` (75–83) | role-match (exact sequence) |
| `src/sift/eval/metrics.py` | utility (pure fns) | transform | `src/sift/render/json_out.py` `normalise_for_determinism` (85) + `hypothesise._gather_exemplar_messages` (146) | role-match |
| `src/sift/eval/truth.py` | model (loader) | file-I/O | `src/sift/config.py` Pydantic models (23–58) + `_load_triage_template` (hypothesise.py:107) | role-match |
| `src/sift/eval/thresholds.py` | config (loader) | file-I/O | `src/sift/config.py` `tomllib` load (15) | exact (same lib/pattern) |
| `src/sift/eval/judge.py` | service | request-response | `hypothesise._generate`/`_load_triage_template` (hypothesise.py:107,262) | role-match |
| `src/sift/eval/report.py` | utility (renderer) | transform | `src/sift/render/json_out.py::render_json` (49) | role-match |
| `src/sift/eval/__init__.py` | package init | — | any existing `__init__.py` | exact |
| `src/sift/cli.py::eval_()` (fill stub :956) | route (CLI command) | request-response | `analyze`/`report` commands (cli.py:711,870) | exact |
| `src/sift/prompts/judge.md` | config (prompt template) | file-I/O | `src/sift/prompts/triage.md` | exact |
| `eval/thresholds.toml` | config (data) | file-I/O | `~/.config/sift/config.toml` shape (config.py) | role-match |
| `eval/cases/<name>/truth.yaml` | config (fixture) | file-I/O | RESEARCH §Golden-Case Authoring (no repo analog) | none |
| `eval/cases/<name>/input/*` | test fixture (data) | file-I/O | adapter sample artefacts under `tests/fixtures/` | role-match |
| `tests/test_eval.py` | test | request-response | `tests/test_analyze.py` (`_handler`/`_patch_http`/`_seed_case`) | exact |
| judge live test | test | request-response | `tests/test_render_pdf.py:226` `@pytest.mark.live` | exact |

## Pattern Assignments

### `src/sift/eval/runner.py` (orchestrator, batch)

**Analog:** `src/sift/cli.py` analyze body (722–823) and `tests/test_analyze.py::_seed_case` (75–83).

**Case-seeding pattern** (`test_analyze.py:75-83`) — build a temp `case.db`, insert events inside one transaction, rebuild template groups:
```python
store = CaseStore(case_db_path(load_config().data_dir, case))
try:
    with store.transaction():
        store.insert_events([_ev(i, m) for i, m in enumerate(messages)])
    dedup.rebuild_template_groups(store)
finally:
    store.close()
```
For golden cases the harness ingests the real `input/` dir instead of fabricated events — reuse `cli._ingest` (cli.py:150) which dispatches adapters and records coverage; do not re-parse directories by hand. Use a `tempfile` temp dir for the per-case db (never the user data dir — mirror conftest XDG isolation).

**Pipeline sequence** (`cli.py:778,812`) — the exact two calls `analyze` makes; reuse verbatim:
```python
n_clusters = cluster_and_label(store, client, config.clustering, label=not no_label)  # cli.py:778
outcome = hypothesise(                                                                # cli.py:812
    store, client,
    top_clusters=top_clusters,
    incident_time=until_dt, since=since_dt, until=until_dt,
    hint=hint, kb_context=kb_context,
    ctx_fallback=_TRIAGE_CTX_FALLBACK, reserve_out=_TRIAGE_RESERVE_OUT,
)
```
`hypothesise` returns `Outcome(hypotheses, raw, degraded, failed, citations_valid, prompt_hash)` (hypothesise.py:89-104) and NEVER raises on bad model output — it degrades and persists.

**Error handling** — mirror analyze's `finally: store.close()` (cli.py:855) so the WAL checkpoints on every path; wrap the embed/cluster leg in `except (httpx.HTTPError, ValueError)` (cli.py:781).

---

### `src/sift/eval/metrics.py` (pure functions, transform)

**Analog:** store query methods + `_gather_exemplar_messages` (hypothesise.py:146) + `normalise_for_determinism` (json_out.py:85).

Signatures to read rows back from (all zero-arg on `CaseStore`):
- `query_clusters()` → `store.py:924` (salience-ordered; slice `[:top_clusters]` = "clusters fed to the model")
- `query_template_groups()` → `store.py:693` (exemplar messages)
- `query_hypotheses()` → `store.py:1002` → `list[StoredHypothesis]`
- `get_meta(key)` → `store.py:1030`

**citation_validity_rate — DO NOT re-derive.** Read the persisted gate verdict `StoredHypothesis.citations_valid` (store.py:441):
```python
# store.py:429-441 — the row already carries the gate's per-hypothesis verdict
@dataclass(frozen=True)
class StoredHypothesis:
    hyp_index: int
    title: str
    narrative: str
    confidence: str  # 'high' | 'medium' | 'low'
    ...
    citations_valid: bool  # the per-hypothesis citation-gate verdict (T-04-02)
```
Metric = `mean(h.citations_valid for h in query_hypotheses())`.

**Exemplar-text gathering for retrieval_hit_rate** — mirror `_gather_exemplar_messages` (hypothesise.py:146-164): stream `iter_event_summaries()` once, keep only exemplar messages of the top-N clusters' groups. Then apply the D-03 regex-any check (RESEARCH Pattern 1):
```python
hits = sum(1 for pat in required_evidence if re.search(pat, haystack, re.IGNORECASE))
return hits / len(required_evidence)
```

**hit@k** — `query_hypotheses()[:k]`, case-insensitive any-of keyword match against `f"{h.title}\n{h.narrative}"`.

**determinism_drift — reuse the M6 seam, never hand-roll a field-stripper** (anti-pattern, ADR 0008). `render_json` (json_out.py:49) then `normalise_for_determinism` (json_out.py:85):
```python
a = normalise_for_determinism(json.loads(render_json(store_run1)))
b = normalise_for_determinism(json.loads(render_json(store_run2)))
identical = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
```
`render_json` already emits `sort_keys=True, ensure_ascii=True, indent=2` (json_out.py:82) and `normalise_for_determinism` drops only `run.generated_at` + volatile path/duration keys (json_out.py:85-102). Express as `determinism_stability` (higher-better) for a uniform `value >= floor` gate — see RESEARCH direction gotcha.

---

### `src/sift/eval/truth.py` (model/loader, file-I/O)

**Analog:** `src/sift/config.py` Pydantic models (23–58, `ConfigDict(extra="forbid")`) + prompt template load idiom.

Use `yaml.safe_load` ONLY (never `yaml.load`/`full_load` — RCE vector), then validate through a Pydantic `Truth` model (fields per D-03: `root_cause: str`, `required_evidence: list[str]`, `acceptable_keywords: list[str]`, `expect_no_incident: bool = False`). Match the project convention `model_config = ConfigDict(extra="forbid")` (config.py:27) so a typo'd truth key fails loudly. Full illustrative loader in RESEARCH §Code Examples (lines 362-377).

---

### `src/sift/eval/thresholds.py` (config loader, file-I/O)

**Analog:** `src/sift/config.py` (imports `tomllib` at line 15, stdlib).

**Load pattern** (mirror config.py exactly — binary mode required):
```python
import tomllib
with path.open("rb") as f:            # tomllib requires binary mode
    return {k: float(v) for k, v in tomllib.load(f).items()}
```
Floors per D-07: `retrieval_hit_rate`, `hypothesis_hit_at_k`, `citation_validity_rate`, `determinism_stability`. `citation_validity_rate = 1.00` (the anti-hallucination invariant).

---

### `src/sift/eval/judge.py` (service, request-response — advisory only)

**Analog:** `hypothesise._load_triage_template` (hypothesise.py:107) + `_generate` (hypothesise.py:262).

**Prompt load** — the versioned-template idiom (hypothesise.py:107-113), so tuning the judge never touches Python (CLI-02):
```python
importlib.resources.files(_PROMPT_PACKAGE).joinpath(_PROMPT_FILE).read_text(encoding="utf-8")
```
Call the sole HTTP boundary `InferenceClient.chat` — no framework (LangChain/instructor forbidden by CLAUDE.md). Parse leniently and degrade to no-judge-score rather than raise (the "never crash on model output" idiom, mirror `_validate` at hypothesise.py:234). **Judge scores are advisory — reported alongside, NEVER enter the gate (D-08).**

---

### `src/sift/eval/report.py` (renderer, transform)

**Analog:** `src/sift/render/json_out.py::render_json` (49) — canonical key-sorted JSON:
```python
return json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=2) + "\n"
```
Plain-text metric table by default; `--json` emits the machine-readable shape (D-05). Display drift = `1 - stability` if the SPEC "determinism drift" wording is wanted, while gating on stability internally.

---

### `src/sift/cli.py::eval_()` — fill the stub at cli.py:956 (route, request-response)

**Analog:** the `analyze` (cli.py:711) and `report` (cli.py:870) Typer commands in the same file.

Current stub to replace:
```python
@app.command("eval")
def eval_() -> None:
    """Run the golden-case evaluation suite."""
    print("eval arrives in Phase 7 (M7)")
    raise typer.Exit(1)
```
**Signature (D-05):** `sift eval [--suite <dir>] [--json] [--judge]`, default suite `eval/cases/`. Use `Annotated[..., typer.Option(...)]` params like `report` (cli.py:873-881).

**Exit-code contract** — the CLI command owns `typer.Exit` (mirror analyze's CLI-04 block, cli.py:832-853). Record in a NEW ADR 0010 (0009 is taken by KB-index):

| Code | Meaning |
|------|---------|
| 0 | All keyword metrics meet their floors |
| 1 | A metric regressed below its floor (SPEC §8 acceptance) / a case could not run |
| 2 | Typer/Click usage error (bad `--suite` path) |

Judge scores never enter the gate (D-08). Sanitise any untrusted text with `_sanitise` before printing (cli.py:754).

**Offline client injection** — the fake client reaches the harness through the `_make_http_client` seam (cli.py:972); tests monkeypatch it (see below).

---

### `src/sift/prompts/judge.md` (prompt template)

**Analog:** `src/sift/prompts/triage.md`. Versioned markdown template loaded via `importlib.resources` (hypothesise.py:107). Changing it must never require touching Python (CLI-02).

---

### `eval/cases/<name>/` golden fixtures + `eval/thresholds.toml`

**Analog for `input/`:** adapter sample artefacts under `tests/fixtures/` (genericlog/journald/dsserrors/eustack) — feed the existing adapters unchanged. **`truth.yaml`** has no repo analog; shape is in RESEARCH lines 251-267. 6 cases per D-01 (dependency-timeout doubles as mixed-tz; +quiet-cause +negative). Author sanitised content directly (REPT-05 redaction deferred).

---

### `tests/test_eval.py` (test)

**Analog:** `tests/test_analyze.py` — reuse `_handler` (86-137), `_patch_http` (140-150), `_seed_case` (75-83) verbatim.

**Offline seam** (test_analyze.py:140-150) — bind a `MockTransport` so the autouse `_no_network` guard stays enforced (EVAL-05):
```python
def _patch_http(monkeypatch, handler):
    def _factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler),
                            timeout=httpx.Timeout(timeout))
    monkeypatch.setattr("sift.cli._make_http_client", _factory)
```
**Planted-regression gate** (the SPEC §8 acceptance, not optional): a "good" handler returns keyword-hitting hypotheses (`hyp_content` override at test_analyze.py:127) → exit 0; a "regressed" handler returns keyword-missing hypotheses → a floor breaches → assert exit code 1. `CliRunner().invoke(app, ["eval", ...])` like test_analyze.py:161.

**Judge live test** — `@pytest.mark.live` (mirror `tests/test_render_pdf.py:226`), excluded from the socket-blocked default suite (`addopts = "-m 'not perf and not live'"`).

## Shared Patterns

### Store lifecycle (WAL checkpoint on close)
**Source:** `src/sift/cli.py:855-858` (analyze), `cli.py:951-953` (report).
**Apply to:** every runner path that opens a `CaseStore`.
```python
finally:
    store.close()  # clean close checkpoints the WAL (Pitfall 4)
```

### Sanitise untrusted text before printing
**Source:** `src/sift/cli.py:754` (`_sanitise(str(exc))`).
**Apply to:** all CLI/report error and table output that can contain server/DB/model text.

### Versioned prompt template load (no Python change to tune)
**Source:** `src/sift/pipeline/hypothesise.py:107-113`.
**Apply to:** `judge.py`.
```python
importlib.resources.files(_PROMPT_PACKAGE).joinpath(_PROMPT_FILE).read_text(encoding="utf-8")
```

### Pydantic "extra=forbid" for loaded config/data
**Source:** `src/sift/config.py:27` (`model_config = ConfigDict(extra="forbid")`).
**Apply to:** the `Truth` model — a typo'd truth key fails loudly.

### Offline test seam (zero sockets)
**Source:** `tests/test_analyze.py:140-150` (`_patch_http` → `MockTransport` via `cli._make_http_client`).
**Apply to:** all offline `test_eval.py` cases (EVAL-05).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `eval/cases/<name>/truth.yaml` | config fixture | file-I/O | No existing YAML ground-truth file in the repo. Schema fully specified in RESEARCH lines 251-267 + D-03/D-04; validate through the new `Truth` Pydantic model. |

## Metadata

**Analog search scope:** `src/sift/cli.py`, `src/sift/pipeline/hypothesise.py`, `src/sift/store.py`, `src/sift/render/json_out.py`, `src/sift/config.py`, `tests/test_analyze.py`, `tests/test_render_pdf.py`.
**Files scanned:** 7 primary analogs (targeted reads).
**Pattern extraction date:** 2026-07-18
