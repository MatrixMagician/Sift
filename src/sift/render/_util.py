"""Shared render-time helpers: control-char sanitisation + PDF-extra error.

``sanitise`` is the single control-char strip used by BOTH the CLI (imported
back as ``_sanitise``) and the report renderers, so there is one implementation
and no ``cli`` <-> ``render`` import cycle (render never imports cli).
"""

import unicodedata


def sanitise(text: str) -> str:
    """Strip control characters (except newline and tab) from rendered text.

    T-04-01: hostile log bytes must never drive the operator's terminal.
    Removes C0 controls (below 0x20), DEL (0x7f), C1 controls (0x80-0x9f,
    e.g. the single-byte CSI) and Unicode format characters (category Cf:
    bidi overrides like U+202E, zero-width characters) that can visually
    reorder or hide rendered triage output. Applied at render time only —
    stored raw and message text stay verbatim for citation fidelity.
    """
    return "".join(
        ch
        for ch in text
        if ch in "\n\t"
        or (
            ord(ch) >= 0x20
            and not (0x7F <= ord(ch) <= 0x9F)
            and unicodedata.category(ch) != "Cf"
        )
    )


class PdfExtraMissing(RuntimeError):
    """Raised when the optional ``sift[pdf]`` extra (WeasyPrint) is unavailable.

    Defined here so ``cli.report``'s pdf branch can name it before the real
    ``render/pdf.py`` renderer lands in plan 06-05 (D-10).
    """
