"""Adapter registry and auto-detection (INGST-03).

SPEC.md §5.2 self-containment rule: adding adapter #5 must require exactly a
new module plus one registration line here — nothing else changes.
"""

from fnmatch import fnmatch
from pathlib import Path

from sift.adapters.base import Adapter
from sift.adapters.dsserrors import DsserrorsAdapter
from sift.adapters.dssperfmon import DssperfmonAdapter
from sift.adapters.eustack import EustackAdapter
from sift.adapters.genericlog import GenericLogAdapter
from sift.adapters.journald import JournaldAdapter

SNIFF_THRESHOLD = 0.5

REGISTRY: dict[str, Adapter] = {
    "genericlog": GenericLogAdapter(),
    "journald": JournaldAdapter(),
    "dsserrors": DsserrorsAdapter(),
    "eustack": EustackAdapter(),
    "dssperfmon": DssperfmonAdapter(),
}


def get(name: str) -> Adapter:
    """Return the registered adapter, or raise KeyError naming the known ones."""
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown adapter {name!r}; known adapters: {sorted(REGISTRY)}"
        ) from None


def parse_adapter_overrides(specs: list[str]) -> dict[str, str]:
    """Parse ``glob=name`` override specs into an ordered mapping.

    Each spec splits on its LAST equals sign: adapter names are registry
    identifiers and can never contain ``=``, so this is the split that lets a
    glob containing ``=`` survive intact (Pitfall 8). Unknown adapter names
    raise ValueError listing the registered names — this module stays
    typer-free; the CLI converts the error.
    """
    overrides: dict[str, str] = {}
    for spec in specs:
        glob, sep, name = spec.rpartition("=")
        if not sep or not glob or not name:
            raise ValueError(
                f"invalid adapter override {spec!r}; expected glob=name"
            )
        if name not in REGISTRY:
            raise ValueError(
                f"unknown adapter {name!r}; known adapters: {sorted(REGISTRY)}"
            )
        overrides[glob] = name
    return overrides


def detect(path: Path, relpath: str, overrides: dict[str, str]) -> Adapter:
    """Pick the adapter for a file (INGST-03).

    Algorithm, in order:

    1. The first glob in ``overrides`` (dict insertion order) that fnmatches
       ``relpath`` wins unconditionally; an unknown adapter name raises
       ValueError naming the registered adapters.
    2. Otherwise every registered adapter sniffs the file — each adapter reads
       its own head via ``base.read_head``, so detection always sees the first
       ``SNIFF_BYTES`` (65536) of DECOMPRESSED content, byte-based.
    3. A unique maximum confidence wins when >= ``SNIFF_THRESHOLD``.
    4. A tie at the maximum, or all scores below the threshold, falls back to
       genericlog.

    Determinism: iteration is insertion order over the REGISTRY dict, which is
    fixed at import time — identical inputs always pick the same adapter.
    """
    for glob, name in overrides.items():
        if fnmatch(relpath, glob):
            if name not in REGISTRY:
                raise ValueError(
                    f"unknown adapter {name!r}; known adapters: {sorted(REGISTRY)}"
                )
            return REGISTRY[name]
    scored = [(adapter.sniff(path), adapter) for adapter in REGISTRY.values()]
    best = max(score for score, _ in scored)
    if best >= SNIFF_THRESHOLD:
        winners = [adapter for score, adapter in scored if score == best]
        if len(winners) == 1:
            return winners[0]
    return REGISTRY["genericlog"]
