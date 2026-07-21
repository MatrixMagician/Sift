"""Shared render-time helpers: control-char sanitisation, MB conversion, PDF error.

``sanitise`` is the single control-char strip used by BOTH the CLI (imported
back as ``_sanitise``) and the report renderers, so there is one implementation
and no ``cli`` <-> ``render`` import cycle (render never imports cli).
``mb_bytes`` is likewise the single bytes-to-MB conversion, shared by the MCM
report renderer and the MCM fact renderer (IN-01).
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


def mb_bytes(granted_bytes: int) -> float:
    """Convert bytes to megabytes, rounded deterministically to 3 dp.

    The single conversion for every granted-memory figure Sift displays, called
    by both ``render/mcm_report.py`` and ``pipeline/mcm_facts.py`` (IN-01): two
    independent divisions agree on real data but can drift apart under later
    edits, and the report and the prompt must never quote different numbers for
    the same row.
    """
    return round(granted_bytes / 1024**2, 3)


class PdfExtraMissing(RuntimeError):
    """Raised when the optional ``sift[pdf]`` extra (WeasyPrint) is unavailable.

    Defined here so ``cli.report``'s pdf branch can name it before the real
    ``render/pdf.py`` renderer lands in plan 06-05 (D-10).
    """
