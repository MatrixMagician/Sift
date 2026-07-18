---
phase: 06-renderers-kb-retrieval
reviewed: 2026-07-18T00:00:00Z
depth: deep
files_reviewed: 22
files_reviewed_list:
  - src/sift/render/__init__.py
  - src/sift/render/_util.py
  - src/sift/render/markdown.py
  - src/sift/render/json_out.py
  - src/sift/render/pdf.py
  - src/sift/pipeline/retrieve.py
  - src/sift/pipeline/hypothesise.py
  - src/sift/store.py
  - src/sift/cli.py
  - src/sift/prompts/triage.md
  - docs/decisions/0007-report-exit-codes.md
  - docs/decisions/0008-report-determinism-scope.md
  - docs/decisions/0009-kb-index-per-case.md
  - tests/_report_fixtures.py
  - tests/test_render_markdown.py
  - tests/test_render_json.py
  - tests/test_report_determinism.py
  - tests/test_kb_retrieval.py
  - tests/test_kb_analyze.py
  - tests/test_render_pdf.py
  - tests/test_cli_report.py
  - tests/test_store.py
  - tests/test_store_vectors.py
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-07-18
**Depth:** deep
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Phase 6 delivers the three report renderers (Markdown / JSON / PDF), the KB
retrieval data path, and the `sift report` CLI. The load-bearing invariants are
mostly well-defended and well-tested:

- **KB non-citability (D-01)** is genuinely structural — `kb_chunks` has no
  `event_id` column, `knn_kb_chunks` returns texts only, `_assemble` never adds
  KB text to `prompted_ids`, and the citation gate is untouched. The
  end-to-end FLAGGED test proves a KB "citation" degrades. No leak found.
- **Zero-egress PDF** — HTML is self-contained (inline `<style>`, no `<img>`,
  only `#evt-` anchors) and `url_fetcher` rejects every fetch. Tests assert
  both content and fetcher behaviour. Sound.
- **JSON determinism (REPT-03)** — single canonical dump, single exclusion
  helper, no floats. The excluded-field set is single-sourced. Sound.
- **SQL hygiene / migration additivity** — all values `?`-bound, migration 5 is
  purely additive, head schema v5 verified by tests.

The defects concentrate at the **error-handling and output-sanitisation edges**,
where the code diverges from its own stated invariants ("never crash", "never a
traceback", ADR 0007 exit codes, and the Markdown docstring's anti-injection
claims). One is a reproducible unhandled crash on ordinary operator input.

## Critical Issues

### CR-01: `sift analyze --kb <dir>` crashes with an unhandled `sqlite3.OperationalError` when the KB directory has no indexable `*.md` files

**File:** `src/sift/pipeline/retrieve.py:82-93` (early return) and
`src/sift/pipeline/retrieve.py:96-116` (`retrieve_kb`), reached via
`src/sift/cli.py:782-792`; the missing table is queried at
`src/sift/store.py:878-892` (`knn_kb_chunks`).

**Issue:** `index_kb` returns early (`if not texts: return 0`) **before** it
calls `store.ensure_kb_vectors_table(dim)`, so when the `--kb` directory
contains no `*.md` files (or none that produce chunks) the lazy `kb_vectors`
vec0 table is never created. The CLI then calls `retrieve_kb`
unconditionally; with non-empty cluster labels/signatures as `query_texts`, it
embeds the query and calls `store.knn_kb_chunks(...)`, which executes
`SELECT ... FROM kb_vectors v JOIN kb_chunks kb ...`. That raises
`sqlite3.OperationalError: no such table: kb_vectors`. The surrounding handler
in `cli.analyze` is `except (httpx.HTTPError, ValueError)` — it does **not**
catch `sqlite3.OperationalError`, so the exception propagates as a raw
traceback (exit 1 in real use, `result.exception` set under `CliRunner`).

This is a realistic input: operators frequently keep runbooks as `.txt`/`.rst`,
or point `--kb` at a directory that happens to have no Markdown. It violates the
project's load-bearing "never crash / helpful message" invariant and is untested
(every KB test writes a `runbook.md` first).

**Fix:** Make retrieval tolerate an un-indexed KB, either by short-circuiting in
the CLI or (preferred, root-cause) guarding the retrieval layer:

```python
# retrieve.py — retrieve_kb, before the KNN call
def retrieve_kb(store, client, query_texts, k=KB_TOP_K):
    queries = [q for q in query_texts if q.strip()]
    if not queries:
        return []
    if store.get_meta("embedding_dim") is None:  # KB never indexed → no vec table
        return []
    vectors = client.embed(queries)
    ...
```

or have `knn_kb_chunks` treat a missing table as an empty index:

```python
try:
    rows = self._conn.execute("SELECT kb.text FROM kb_vectors v ...", ...).fetchall()
except sqlite3.OperationalError:
    return []  # KB not indexed on this case yet
```

Add a test: `sift analyze demo --kb <empty-dir> --no-label` must exit cleanly,
not traceback.

## Warnings

### WR-01: `report --format md|json --out <path>` leaks a raw traceback on a write failure (ADR 0007 says exit 1 with a helpful message, "never a traceback")

**File:** `src/sift/cli.py:909-910`

**Issue:** The md/json branch does `out.write_text(text, encoding="utf-8")`
with no error handling. An unwritable path, missing parent directory, or a
full disk raises `OSError` that is not caught anywhere in `report`, producing an
uncaught traceback. ADR 0007 explicitly promises "a render or `--out` write
failure → exit 1 … a helpful message, never a traceback." The PDF branch handles
`OSError`; the md/json branch does not.

**Fix:** Wrap the write and map to a clean exit 1:

```python
try:
    if out is not None:
        out.write_text(text, encoding="utf-8")
    else:
        print(text)
except OSError as exc:
    print(f"Error: cannot write report to {out}: {_sanitise(str(exc))}")
    raise typer.Exit(1) from None
```

### WR-02: `render_pdf` misreports every `OSError` (including an unwritable `--out` path) as "install the sift[pdf] extra and pango"

**File:** `src/sift/render/pdf.py:86-92`

**Issue:** The `except OSError` around `write_pdf(str(out))` assumes any
`OSError` means missing pango/harfbuzz, but `write_pdf` opens the output path
and will raise `OSError`/`FileNotFoundError`/`PermissionError` for an
unwritable or non-existent `--out` directory too. Those get re-raised as
`PdfExtraMissing`, and `cli.report` then prints "PDF rendering unavailable;
install the sift[pdf] extra and pango" — a wrong, misleading diagnosis for a
plain filesystem error. Determining the pango case reliably by exception type is
not possible here, so at minimum the write-target error should be distinguished.

**Fix:** Validate/perform the file open at a point you control, or narrow the
diagnosis. Simplest: check the parent directory is writable before rendering
(raise a distinct error), or render to bytes and write yourself so a write
`OSError` is reported as a write failure, reserving the pango message for the
`HTML(...)`/rendering step.

### WR-03: A hard-degraded run (zero schema-valid hypotheses, `triage_raw` persisted) makes `sift report` exit 1 with "run 'sift analyze' first" and never surfaces the persisted raw output or degraded banner

**File:** `src/sift/cli.py:882-884`; persisted-but-hidden raw at
`src/sift/pipeline/hypothesise.py:481-482`; the Markdown banner that can never
fire in this state at `src/sift/render/markdown.py:144-149`.

**Issue:** When the model output cannot be schema-validated even after the
repair round-trip, `_persist` writes **zero** hypotheses rows, sets
`triage_degraded="1"`, and stores the raw text in `triage_raw` (by design, so
the operator can inspect it). But `report` gates entirely on
`store.query_hypotheses()` being non-empty: a hard-degraded case therefore
reports "No hypotheses to report; run 'sift analyze' first" — factually wrong
(analyze *did* run) — and exits 1. The Markdown DEGRADED banner only renders
inside `render_markdown`, which is never reached. `sift show hypotheses`
(Phase 4) also early-returns on empty rows before its degraded check, so the
persisted `triage_raw` is invisible to **every** command. This contradicts the
"nothing disappears silently" invariant: the raw is stored but unreachable
without opening the sqlite file by hand.

**Fix:** In `report`, treat a persisted degraded/raw run as reportable even with
zero rows — render at least the DEGRADED banner plus the raw model output (or
print a distinct message pointing at `triage_raw`), and reserve the "run
analyze first" message for the genuine no-triage case
(`triage_created_at is None`). Mirror the fix in `show hypotheses`.

### WR-04: Model- and DB-sourced text fields are rendered without HTML/Markdown escaping — `sanitise()` only strips control characters, so it does not prevent the "markdown-injection" the renderer claims to defend against

**File:** `src/sift/render/markdown.py` (titles/narratives/reasoning/steps/labels
at lines 81-99, 117-130, 155-183) and `src/sift/render/pdf.py:84` (`markdown.markdown`
with raw-HTML passthrough); CLI PDF handler catches only
`(ImportError, PdfExtraMissing, OSError)` at `src/sift/cli.py:894`.

**Issue:** `sanitise` (`_util.py:11-30`) removes control/format characters only;
`<`, `>`, `&`, `[`, backticks etc. all pass through. The module docstring claims
titles, narratives and labels are protected against "markdown-injection", but
only the appendix *raw* is actually protected (by the longer-fence trick). A
hypothesis title/narrative or a cluster label/signature (attacker-influenced log
content, or a prompt-injected local-LLM response) can therefore inject Markdown
structure (headings, links, fake "OK" markers) into the report. In the PDF path
this becomes real HTML: `markdown.markdown` passes inline HTML through, so a
narrative containing e.g. `<img src="http://evil/x">` produces an `<img>` that
WeasyPrint hands to `_block_all`, which raises `ValueError` — **not** in the
`(ImportError, PdfExtraMissing, OSError)` set — giving an uncaught traceback
(egress is still blocked, but `sift report --format pdf` crashes). Report
integrity is load-bearing here (the anti-hallucination signal must be
trustworthy), so silent structural spoofing is a real defect.

**Fix:** Escape Markdown/HTML metacharacters in DB/model-sourced inline fields
before emission (or render the PDF from Markdown with `markdown`'s
`safe_mode`/an HTML-sanitiser and disable raw-HTML passthrough except for the
controlled `#evt-` anchors). Also add `ValueError` to the PDF `except` set in
`cli.report` so a blocked-fetch never becomes a traceback.

### WR-05: The evidence-appendix anchor id is neither sanitised nor escaped, though the module docstring states cited ids are sanitised

**File:** `src/sift/render/markdown.py:108`

**Issue:** `lines.append(f'#### <a id="evt-{eid}"></a>\`evt:{eid}\`')` inserts
`eid` verbatim into an HTML `id` attribute and a code span. Every other
id/field on the appendix entry is sanitised (provenance line 110) or regex-gated
to `[0-9a-f]{16}` (`_link_citations`), and the docstring explicitly lists "cited
ids" among the sanitised fields — but this anchor is not. In normal operation
`event_id` is `sha256(...)[:16]` (safe hex), but the review threat model
includes a tampered/shared `case.db` (the reason `_coerce_str_list` and the
whole-line sanitisation exist). A tampered `events.event_id` that is both cited
and present would flow unescaped into the HTML attribute (attribute break-out /
anchor spoofing in the PDF/HTML path).

**Fix:** Sanitise and, for the PDF/HTML path, HTML-attribute-escape `eid` before
interpolation, or gate the anchor emission on the same `[0-9a-f]{16}` shape used
by `_link_citations` so a non-conforming id renders as inert text.

## Info

### IN-01: `normalise_for_determinism` drops *any* string value beginning with `/`, so the ADR/docstring claim "case-relative paths and every other field are retained" is inaccurate

**File:** `src/sift/render/json_out.py:107-108` (`_is_abs_path`), applied by
`_strip_volatile` (92-105).

**Issue:** `_is_abs_path` is "starts with `/`", so a legitimate field value that
happens to begin with `/` (a cluster signature or narrative quoting a log path,
a next-step like `/etc/...`) causes its **key** to be deleted from the
normalised document. This is benign for the current determinism test (both runs
strip identically, so byte-equality still holds), but it means the helper could
mask a genuine run-to-run difference in such a field, and it contradicts the
ADR 0008 / docstring promise that only `generated_at` + real absolute paths go.

**Fix:** Tighten the heuristic (e.g. only strip keys whose *name* implies a path,
or match a `data_dir`-anchored prefix), or document the actual behaviour.

### IN-02: JSON report is not sanitised for C1/bidi terminal-injection bytes, unlike the Markdown report

**File:** `src/sift/render/json_out.py:70`

**Issue:** `json.dumps(..., ensure_ascii=False)` escapes C0 controls but emits
C1 controls (0x80-0x9F, e.g. single-byte CSI) and Cf format chars (bidi
overrides, zero-width) as raw UTF-8. The Markdown renderer strips these via
`sanitise` for T-04-01/T-06-01; the JSON renderer does not, so `cat report.json`
in a terminal remains exposed to the same terminal-injection the project
otherwise defends against. This is likely a deliberate fidelity/determinism
trade-off (sanitising JSON would break round-trip fidelity), but it is
undocumented.

**Fix:** Either document that JSON output is machine-oriented and unsanitised, or
use `ensure_ascii=True` for the JSON report so all non-ASCII (including C1/Cf) is
`\u`-escaped and terminal-safe while staying deterministic.

### IN-03: `index_kb` follows symlinks under the `--kb` directory with no trust-boundary check, unlike `ingest`

**File:** `src/sift/pipeline/retrieve.py:73-76`

**Issue:** `root.rglob("*.md")` will traverse symlinked directories and read
symlinked files, and there is no `path.is_symlink()` skip. `ingest` treats
symlinks as a hostile-bundle trust boundary and skips them loudly
(`cli.py:222-234`); `index_kb` does not. The `--kb` dir is operator-supplied
(lower risk than an ingested bundle), but a symlinked `x.md → /etc/…` would be
read and its content embedded into the prompt, and symlinked directory loops are
possible. Inconsistent with the established convention.

**Fix:** Skip symlinks in the KB walk for parity with `ingest`, or document that
`--kb` trusts its directory tree.

### IN-04: `report` (md path) queries `query_hypotheses()` twice

**File:** `src/sift/cli.py:882` (guard) and `src/sift/render/markdown.py:135`
(via `render_markdown`).

**Issue:** The emptiness guard and the renderer each run `query_hypotheses()`.
Harmless and cheap, but redundant; a boolean "has any triage output" check
(`triage_created_at`) would also fix WR-03's mis-messaging.

**Fix:** Optional — gate on run-meta presence instead of re-querying rows.

---

_Reviewed: 2026-07-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
