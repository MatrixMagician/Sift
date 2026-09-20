"""Helpers shared across pipeline modules.

Small, dependency-free utilities several pipeline stages would otherwise
re-implement verbatim: the versioned-prompt loader (CLI-02), the frozen
severity rank, the representative-group sort key reading it, and the
sha256[:16] short-hash idiom.
"""

from __future__ import annotations

import hashlib
import importlib.resources
from typing import TYPE_CHECKING, get_args

from sift.models import Severity

if TYPE_CHECKING:
    from sift.store import TemplateGroup

_PROMPT_PACKAGE = "sift.prompts"

# Numeric severity rank — never lexicographic ('unknown' > 'error' as a string
# would be wrong). Derived from the Severity Literal rather than re-typed, so
# the vocabulary has one spelling and this copy cannot fall out of step with
# the one the adapters and the events CHECK constraint are held to. Severity is
# declared most severe first, so reversing it makes the index the rank, giving
# unknown=0 through fatal=5. test_severity_rank_matches_cluster_module pins
# those numbers, so reordering the Literal fails loudly.
SEVERITY_RANK: dict[str, int] = {
    name: rank for rank, name in enumerate(reversed(get_args(Severity)))
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
