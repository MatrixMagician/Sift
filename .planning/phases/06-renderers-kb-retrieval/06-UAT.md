---
status: complete
phase: 06-renderers-kb-retrieval
source: [06-VERIFICATION.md]
started: 2026-07-18
updated: 2026-07-18
---

## Current Test

[testing complete]

## Tests

### 1. Real PDF byte generation via the sift[pdf] extra (REPT-04, SC4)
expected: |
  `uv sync --extra pdf` and `dnf install pango` on the reference machine, then either:
    - `uv run pytest tests/test_render_pdf.py -m live`  (asserts %PDF magic bytes + url_fetcher never fired), or
    - `sift report <case> --format pdf --out report.pdf` and open the PDF to eyeball layout.
  All non-live PDF legs are already automated and green in the default suite:
  missing-extra → PdfExtraMissing → CLI exit 1 helpful message (ImportError and OSError),
  self-contained HTML, rejecting url_fetcher, core deps free of markdown/weasyprint imports.
result: [passed]
verified: 2026-07-18
evidence: |
  Reference machine (Fedora Strix Halo): pango 1.57.1 present, `uv sync --extra pdf` clean.
  Leg 1 — `uv run --extra pdf pytest tests/test_render_pdf.py -m live`:
    test_render_pdf_live_writes_real_pdf_without_external_fetch PASSED (real WeasyPrint;
    asserts output starts with %PDF and the _block_all spy recorded zero fetches).
  Leg 2 — real CLI end-to-end in an isolated scratch dir on a fixture-built analysed case:
    `sift report demo --format pdf --out report.pdf` → exit 0, 20,771-byte file,
    magic bytes `%PDF-1.7`, trailer `%%EOF`, `file(1)` → "PDF document, version 1.7".
  Both legs confirm real PDF byte generation with the egress-blocking url_fetcher never firing.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
