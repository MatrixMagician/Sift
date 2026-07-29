# Stack Research

**Domain:** eu-stack hang/slowdown analysis (v1.3) — rule-driven thread classification,
deterministic saturation/contention metrics, multi-dump diffing, embedding-vector reuse
**Researched:** 2026-07-25
**Confidence:** HIGH (sqlite-vec read-back empirically verified against the exact installed
version; TOML/tomllib claims verified against the spec and stdlib docs; matching-performance and
Counter-vs-sklearn claims are arithmetic/architectural reasoning against measured v1.3 volumes, not
external sources — flagged MEDIUM where they rest on reasoning rather than a fetched source)

**Scope note:** this supersedes the v1.0 stack validation that previously occupied this path
(2026-07-16 — Python/httpx/Pydantic/sqlite-vec/scikit-learn/Typer/zstandard/PDF/embeddings
questions). That validation is not re-litigated here: it shipped, it is unchanged, and its
findings are preserved verbatim in `.claude/CLAUDE.md`'s "Technology Stack" section. This document
is scoped **only** to the four new v1.3 asks below.

## Verdict: no new runtime dependency for any of the four asks

Every one of (a)–(d) is covered by stdlib or an already-declared dependency. The recommendation
below is deliberately "add nothing" four times over, because that is what the evidence supports —
not a default answer reached by not looking.

### (a) Rules-file format — **TOML via stdlib `tomllib`**

| Format | Verdict | Why |
|--------|---------|-----|
| **TOML (`tomllib`)** | **Use this** | Already the project's human-edited config format (`~/.config/sift/config.toml`) — this is a second file in the same format the team already reads and diffs, not a new convention. `tomllib` is stdlib since Python 3.11 (PEP 680); Sift's floor is 3.12, so it costs nothing. An ordered array of tables (`[[rule]]`) preserves file order 1:1 with parse order in Python's dict-preserves-insertion-order semantics — first-match-wins falls out for free, with no separate "priority" field to keep in sync with row position. |
| YAML (PyYAML) | Reject | Not stdlib — currently scoped to the M7 eval harness only (`truth.yaml`); pulling it into the rules-loading path (used by every `sift eustack` run, not just `sift eval`) broadens a test-only dependency into a runtime one. YAML's unquoted-scalar ambiguities (the "Norway problem" class: bare `no`/`off`/`null`-like tokens coerce to booleans/null; a bare `key: value` colon-space is a mapping delimiter) are a real hazard surface for hand-typed C++ symbol text that a reviewer must get right on every edit — TOML's literal strings sidestep this entirely (below). |
| Markdown-with-tables | Reject | No stdlib parser exists — you would hand-roll a markdown-table parser, which is *more* code than calling `tomllib.load()`, not less. Worse: pipe (`\|`) is the markdown table cell delimiter, and C++ symbols legitimately contain literal pipes — `operator\|`, `operator\|=`, `operator\|\|` are real overload names that would need per-cell escaping in every row that mentions them. TOML has no such collision. |

**Escaping/quoting check (the specific hazard named in the question), verified against the TOML
spec:** patterns are demangled C++ symbols containing `<`, `>`, `::`, `&`, quotes and commas.
TOML's **literal strings** (single-quoted, `'...'`) perform **zero escaping** — every one of those
characters is legal verbatim inside `'...'`. The only character that cannot appear in a literal
string is a literal single quote itself (vanishingly rare in a demangled symbol; TOML's multi-line
literal-string form is the escape hatch if one ever shows up). Practical rule-file row:

```toml
[[rule]]
role = "idle-parked"
subsystem = "job-queue"
match = "contains"
pattern = 'MSIQTask::GetNextPreferredJob'
```

No new dependency, no escaping code, first-match-wins is just "iterate the list in file order."

### (b) Symbol matching — **plain `str` methods (`in`/`startswith`), not `re`, not a trie**

Order-of-magnitude check against the *measured* v1.3 volumes (not the naive worst case): there are
**93 distinct stack signatures per dump**, not 4,000 independent threads to classify — classifying
a signature is what has to happen; tallying which of the 4,000 threads owns which signature is a
`Counter` lookup (see (c)), not a second classification pass. So the real workload is:

- **93 signatures × ≤19 frames (max observed depth) × R hand-curated rules.** Even at a generously
  large R = 200 rules, that is 93 × 19 × 200 ≈ 353,000 string comparisons, once per dump.
- Plain Python `str.startswith`/`in` over short strings (symbol names, tens of characters) runs at
  roughly 10–50M ops/sec on any modern CPU — this workload finishes in **single-digit
  milliseconds**, not seconds.
- Even the pessimistic per-thread naive scan (4,000 threads × 10 frames × 200 rules = 8M
  comparisons) is still well under a second in pure Python. There is no scale at which this
  analysis is a bottleneck.

**Conclusion: an anchored-prefix trie or a precompiled alternation regex is solving a performance
problem that does not exist at this N.** Reach for it only if a future dump is orders of magnitude
larger (hundreds of thousands of frames) — not speculatively now.

Between plain `str` methods and `re`: **prefer plain `str` methods** (`match = "exact" |
"prefix" | "contains"` as a rule field, dispatched to `==`, `str.startswith`, `str.__contains__`).
This is not just laziness — it is consistent with an explicit existing convention in this exact
adapter family: `eustack.py`'s own regexes are commented **"Anchored, linear-scan regexes — no
ReDoS"** (`_TID_RE`, `_FRAME_RE`). A hand-curated, human-edited rules file is precisely the kind of
input where a reviewer might paste in a `.*`-heavy pattern without thinking about backtracking;
plain string containment/prefix checks have no ReDoS surface at all, by construction. If wildcard
patterns are genuinely needed later (rare — demangled symbols are exact, not glob-shaped), stdlib
`fnmatch` is the escape hatch: it translates glob syntax to a compiled `re` internally and caches
compiled patterns (`_MAXCACHE`) automatically, so it costs nothing extra to reach for if the need
arises — but do not add it speculatively now; `contains`/`prefix`/`exact` almost certainly covers
every rule in the reference taxonomy (self-labelling frames like `MSIQTask::GetNextPreferredJob`,
`CDSSQueryEngine::WaitUntilFinished`, `curl_multi_poll` are exact function names, not patterns
needing wildcards).

**Integration note for the roadmap:** the classifier needs the *full* frame list per thread, not
just the top-5 "condensed" message the `eustack` adapter already stores (`CONDENSED_FRAMES = 5` in
`src/sift/adapters/eustack.py`). The measured self-labelling frames sit at depth ~8–10 in a
10-frame stack, below the condensation cutoff. The full frame text is still present, uncompressed,
in `Event.raw` for any thread block under the 4 KB zstd threshold (`store.py`'s
`_RAW_ZSTD_THRESHOLD`) — a typical ~10-line eu-stack thread block is well under that, so no new
storage path or dependency, just read `raw` instead of `message` in the classifier's frame source.

### (c) Signature grouping — **`collections.Counter` over frame tuples, not scikit-learn**

Confirmed: this is exact structural grouping (identical frame sequence ⇒ identical signature), not
fuzzy semantic similarity. `sklearn.cluster.HDBSCAN`/`AgglomerativeClustering` (both already
dependencies, used for the *semantic* embedding-space clustering of free-text log messages
elsewhere in the pipeline) solve a different problem — approximate grouping over a continuous
distance metric. Applying an ML clustering algorithm to decide whether two identical tuples of
frame strings are "the same" would be strictly worse than `==`: slower, non-deterministic across
library versions in the general case, and unnecessary because equality is exact and free.

- **Per-dump signature composition:** `collections.Counter(tuple(frames) for frames in threads)` —
  one pass, O(n), stdlib only. This *is* the "93 distinct stack signatures" measurement from the
  milestone context, computed directly.
- **Multi-dump progression (per-signature population deltas):** two `Counter`s, diffed with plain
  dict arithmetic (`Counter` subtraction/`|`/`&`, or a manual `set(a) | set(b)` walk to also
  surface *which* TIDs appeared/disappeared per signature, since the milestone also wants per-TID
  advancement, not just per-signature counts). No new dependency; this is arithmetic over
  dictionaries already keyed by signature.

### (d) SEED-002 vector reuse — **read the existing `vectors` vec0 table directly; no BLOB column**

This was the one open API question worth actually testing rather than reasoning about, so it was
verified empirically against the exact pinned version in this environment
(`sqlite-vec==0.1.9`, `src/sift/store.py`'s existing `_load_sqlite_vec`/`_blob_to_vec` path) with a
live in-memory round-trip:

```python
conn.execute("create virtual table vectors using vec0(chunk_id integer primary key, embedding float[4])")
conn.execute("insert into vectors (chunk_id, embedding) values (?, ?)", (2, blob))
conn.execute("select embedding from vectors where chunk_id = ?", (2,)).fetchone()
# -> returns the exact stored float32 blob, no MATCH/KNN clause needed
conn.execute("select chunk_id, embedding from vectors").fetchall()
# -> plain unfiltered scan also returns embeddings directly
```

**Both a point lookup by primary key and a full unfiltered scan work on the `vec0` table exactly
like an ordinary table column** — no `MATCH`/`k =` KNN machinery is required to read a vector back
out; that machinery is only for *similarity* search. `store.py` already has the read half of the
confined vector-serialisation pair, `_blob_to_vec` (currently only pyright-suppressed as unused
outside tests) — SEED-002's incremental-embed path is: `SELECT chunk_id, embedding FROM vectors
WHERE chunk_id IN (...)` (mirroring the existing `?`-bound `IN (...)` idiom already used by
`get_events_by_ids`), decode with `_blob_to_vec`, and only call `client.embed()` for the chunk_ids
not returned. **No parallel BLOB column, no schema migration, no new dependency.** This closes the
concrete API question the milestone flagged as needing verification rather than assumption.

## Recommended Stack

### Core Technologies

No new core technology. All four capabilities are built on what is already declared in
`pyproject.toml`.

### Supporting Libraries (already present — zero version change)

| Library | Version (pinned) | New use in v1.3 | Why it already covers this |
|---------|-------------------|------------------|------------------------------|
| `tomllib` (stdlib) | 3.12+ (no package) | Parse the versioned thread-role rules file | Same format as `~/.config/sift/config.toml`; literal strings need no escaping for `< > :: &` or quotes |
| `sqlite-vec` | 0.1.9 (pinned exact) | Read persisted vectors back for SEED-002 reuse | Verified: point-select and full-scan both return the stored blob without KNN |
| `scikit-learn` | 1.9.0 (pinned exact) | **Not used** for eu-stack signature grouping (see (c)) — stays scoped to its existing semantic-clustering role | Confirms the negative: don't reach for it here |
| `collections` (stdlib) | — | `Counter`-based signature tally and multi-dump diff | Exact-match grouping is a dict operation, not an ML problem |
| `re` (stdlib) | — | Only if a rule genuinely needs a pattern beyond exact/prefix/contains | Kept as an escape hatch, not the default matcher |
| `fnmatch` (stdlib) | — | Only if hand-curated glob wildcards are later needed in the rules file | Caches compiled patterns automatically; not needed for the reference taxonomy |

### Development Tools

No change. `ruff`, `pyright`, `pytest` continue to gate "done" as already configured.

## Installation

```bash
# Nothing to add — every capability above resolves to stdlib or an already-pinned dependency.
uv sync   # unchanged
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| TOML (`tomllib`) rules file | YAML (PyYAML) | Only if the rules file needs structures TOML genuinely can't express well (deep nesting, anchors/refs) — the flat `[[rule]]` list here doesn't |
| TOML (`tomllib`) rules file | Markdown table (matches `sift/prompts/*.md`) | Never for *data* the program parses — Markdown convention stays reserved for LLM prompt text, which is prose, not a row-oriented table with an ordering contract |
| Plain `str` matching (`contains`/`prefix`/`exact`) | `re` | If a rule genuinely needs alternation/character classes beyond literal substrings — write the pattern anchored, per the adapter's existing "no ReDoS" convention |
| Plain `str` matching | `fnmatch` | If hand-curated glob wildcards (`*`, `?`) are needed — stdlib, cached, no new dependency, but not warranted by the reference taxonomy's exact symbol names |
| `collections.Counter` signature grouping | `sklearn.cluster.HDBSCAN`/`AgglomerativeClustering` | Never for this — those solve approximate similarity over embeddings, a different problem than exact frame-tuple equality |
| Read vectors back from the existing `vectors` vec0 table | A parallel BLOB column for vector storage | Never needed — empirically verified point-select and full-scan both work directly on `vec0` |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| PyYAML for the rules file | Broadens a test-only dependency to a runtime one; unquoted-scalar ambiguity is a real editing hazard for hand-typed symbol text | `tomllib` (stdlib, already the config format) |
| A hand-rolled Markdown-table parser for the rules file | More code than `tomllib.load()`; `\|` collides with real C++ operator-overload symbol names | `tomllib` |
| A prefix trie / precompiled alternation over frame patterns | Solves a throughput problem that doesn't exist at 93 signatures × ≤19 frames × ~hundreds of rules (sub-10ms either way) | Plain `str.startswith`/`in`, dispatched by a `match` field in the rule row |
| `sklearn.cluster.*` for stack-signature grouping | Approximate ML clustering applied to an exact-equality problem — slower and the wrong tool | `collections.Counter` over frame tuples |
| A new parallel BLOB column for vector storage (SEED-002) | Unnecessary — the existing `vectors` vec0 table already supports cheap point-select and full-scan read-back | `SELECT ... FROM vectors WHERE chunk_id IN (...)` + the existing `_blob_to_vec` |

## Stack Patterns by Variant

**If a rule needs a wildcard later (not needed for the reference taxonomy):**
- Add `match = "glob"` dispatching to `fnmatch.fnmatch` (stdlib), alongside the existing
  `exact`/`prefix`/`contains` dispatch — additive, no new dependency, no breaking change to
  existing rule rows.

**If eu-stack event volume per case grows by orders of magnitude in a future milestone:**
- Revisit the "plain `str` matching is fast enough" conclusion — at that point (not before) a
  precompiled alternation (`re.compile("|".join(...))`) is the next lazy step before reaching for
  anything heavier.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `tomllib` | Python 3.12+ | Sift's floor is already 3.12; `tomllib` shipped in 3.11 (PEP 680) — no compatibility gap |
| `sqlite-vec==0.1.9` | Python 3.12/3.13 `sqlite3` | Already pinned; point-select/full-scan read-back verified against this exact version, not a newer/older one |
| `scikit-learn==1.9.0` | numpy 2.x | Unchanged — deliberately not extended to cover eu-stack signature grouping |

## Sources

- `/asg017/sqlite-vec` (Context7, docs on auxiliary/metadata columns and KNN — did not
  explicitly document plain point-select, which is why it was verified empirically instead) — MEDIUM
- **Empirical verification**, live in-memory round-trip against the exact pinned
  `sqlite-vec==0.1.9` in this project's own `.venv` (point-select by primary key + full unfiltered
  scan both returned the stored float32 vector without a `MATCH`/`k =` clause) — **HIGH**
- https://toml.io (TOML spec, literal-string escaping rules — fetched via web search,
  cross-referenced against the official spec text) — MEDIUM
- https://docs.python.org/3/library/tomllib.html and PEP 680 (`tomllib` stdlib since 3.11) — MEDIUM
- `src/sift/adapters/eustack.py`, `src/sift/store.py` (this repo) — read directly; ReDoS-avoidance
  convention, `CONDENSED_FRAMES`/`raw` frame-depth mismatch, and the existing `_blob_to_vec`/
  `get_events_by_ids` idioms are all first-party facts, not external sources — HIGH (primary source)
- Order-of-magnitude matching-performance and Counter-vs-sklearn reasoning: arithmetic against the
  measured v1.3 volumes in `.planning/research/MILESTONE-CONTEXT-v1.3.md` (93 signatures, ≤19
  frames, ~4,000 threads) — MEDIUM (reasoning, not a fetched benchmark source)

---
*Stack research for: eu-stack hang/slowdown analysis (Sift v1.3)*
*Researched: 2026-07-25*
