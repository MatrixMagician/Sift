"""Adapter registry.

SPEC.md §5.2 self-containment rule: adding adapter #5 must require exactly a
new module plus one registration line here — nothing else changes.
"""

from pathlib import Path

from sift.adapters.base import Adapter
from sift.adapters.genericlog import GenericLogAdapter

REGISTRY: dict[str, Adapter] = {
    "genericlog": GenericLogAdapter(),
}


def get(name: str) -> Adapter:
    """Return the registered adapter, or raise KeyError naming the known ones."""
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown adapter {name!r}; known adapters: {sorted(REGISTRY)}"
        ) from None


def detect(path: Path, relpath: str, overrides: dict[str, str]) -> Adapter:
    """Pick the adapter for a file.

    v0: always genericlog. Plan 01-04 implements the full sniff algorithm
    (INGST-03: overrides via fnmatch, sniff on the first 64 KB decompressed,
    highest confidence >= 0.5 wins, fallback genericlog). Signature is the
    one that algorithm needs — keep it stable.
    """
    return REGISTRY["genericlog"]
