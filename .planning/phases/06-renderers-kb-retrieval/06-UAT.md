---
status: testing
phase: 06-renderers-kb-retrieval
source: [06-VERIFICATION.md]
started: 2026-07-18
updated: 2026-07-18
---

## Current Test

number: 1
name: Real PDF byte generation via the sift[pdf] extra (REPT-04, SC4)
expected: |
  With the optional extra and its system library installed
  (`uv sync --extra pdf` + `dnf install pango`), `sift report <case> --format pdf`
  produces a valid PDF (starts with the %PDF magic bytes) rendered from the
  Markdown report, and the egress-blocking url_fetcher (`_block_all`) never fires.
awaiting: user response

## Tests

### 1. Real PDF byte generation via the sift[pdf] extra (REPT-04, SC4)
expected: |
  `uv sync --extra pdf` and `dnf install pango` on the reference machine, then either:
    - `uv run pytest tests/test_render_pdf.py -m live`  (asserts %PDF magic bytes + url_fetcher never fired), or
    - `sift report <case> --format pdf --out report.pdf` and open the PDF to eyeball layout.
  All non-live PDF legs are already automated and green in the default suite:
  missing-extra → PdfExtraMissing → CLI exit 1 helpful message (ImportError and OSError),
  self-contained HTML, rejecting url_fetcher, core deps free of markdown/weasyprint imports.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
