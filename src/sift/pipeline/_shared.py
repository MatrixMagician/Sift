"""Helpers shared across pipeline modules.

Small, dependency-free utilities several pipeline stages would otherwise
re-implement verbatim: the versioned-prompt loader (CLI-02), the frozen
severity rank and the sha256[:16] short-hash idiom.
"""

from __future__ import annotations

import hashlib
import importlib.resources

_PROMPT_PACKAGE = "sift.prompts"

# Explicit severity rank — never lexicographic ('unknown' > 'error' as a
# string would be wrong). The vocabulary is frozen by the clusters/severity
# CHECK constraint, so the shared copy cannot drift.
SEVERITY_RANK = {
    "fatal": 5,
    "error": 4,
    "warn": 3,
    "info": 2,
    "debug": 1,
    "unknown": 0,
}


def load_prompt(filename: str) -> str:
    """Load a versioned prompt/fragment from package data (CLI-02).

    The single ``importlib.resources`` idiom every pipeline module routes
    through, so wording changes touch no path maths.
    """
    return (
        importlib.resources.files(_PROMPT_PACKAGE)
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


def short_hash(text: str) -> str:
    """sha256(text)[:16], mirroring the frozen event_id idiom.

    Identical input yields an identical hash — the determinism guarantee that
    makes template ids, prompt hashes and rules hashes reproducible.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
