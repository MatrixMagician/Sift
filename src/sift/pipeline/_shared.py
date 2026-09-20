"""Helpers shared across pipeline modules.

Small, dependency-free utilities several pipeline stages would otherwise
re-implement verbatim: the versioned-prompt loader (CLI-02), the frozen
severity rank, the representative-group sort key reading it, and the
sha256[:16] short-hash idiom.
"""

from __future__ import annotations

import hashlib
import importlib.resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sift.store import TemplateGroup

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


def salience_key(group: TemplateGroup) -> tuple[int, int]:
    """The (severity rank, count) key that picks a cluster's representative group.

    The key only, never the whole selection: the three consumers feed it
    different inputs and return different things — the representative group
    itself (the cluster signature), its exemplar text (the label excerpt) and
    its first exemplar event id (the hypothesis citation). Sharing the key is
    what stops those three answers diverging on the same cluster.
    """
    return (SEVERITY_RANK.get(group.severity_max, 0), group.count)


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
