"""genericlog adapter — v0 stub, implemented in plan 01-02 Task 3."""

from collections.abc import Iterator
from pathlib import Path

from sift.models import Event


class GenericLogAdapter:
    """Fallback adapter for timestamped line-based logs (SPEC.md §5.2 #1)."""

    name = "genericlog"

    def sniff(self, path: Path) -> float:
        return 0.0

    def parse(self, path: Path, case_id: str) -> Iterator[Event]:
        return iter(())
