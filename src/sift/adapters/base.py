"""Adapter protocol and shared input helpers.

The ``Adapter`` protocol is copied verbatim from SPEC.md §5.2 and is FROZEN
after Phase 1 so Phase 5 adapters can be built in parallel against it.
Decompression lives here (``open_bytes``) as the single shared seam: adapters
receive a ``Path`` and call ``open_bytes`` themselves, staying self-contained.
"""

import gzip
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import zstandard

from sift.models import Event

GZIP_MAGIC = b"\x1f\x8b"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SNIFF_BYTES = 65536


class Adapter(Protocol):
    """SPEC.md §5.2 verbatim — FROZEN after Phase 1."""

    name: str

    def sniff(self, path: Path) -> float: ...  # 0.0-1.0 confidence this file is mine

    def parse(self, path: Path, case_id: str) -> Iterator[Event]: ...


@dataclass
class ParseStats:
    """Per-file parse statistics an adapter records after each parse run."""

    path: str
    total_bytes: int = 0
    unknown_fallback_bytes: int = 0
    event_count: int = 0
    notes: list[str] = field(default_factory=list[str])  # D-05 tz disclosures

    @property
    def coverage(self) -> float:
        """1 - (unknown-fallback bytes / total bytes); 1.0 for an empty file."""
        if self.total_bytes == 0:
            return 1.0
        return 1.0 - self.unknown_fallback_bytes / self.total_bytes


def open_bytes(path: Path) -> io.BufferedIOBase:
    """Open a file as a decompressed byte stream, detecting gzip/zstd by magic bytes."""
    with path.open("rb") as fh:
        head = fh.read(4)
    if head[:2] == GZIP_MAGIC:
        return gzip.open(path, "rb")  # stdlib handles concatenated members
    if head == ZSTD_MAGIC:
        raw = path.open("rb")
        dctx = zstandard.ZstdDecompressor()
        reader = dctx.stream_reader(raw, read_across_frames=True)
        return io.BufferedReader(reader)  # pyright: ignore[reportArgumentType]
    return path.open("rb")


def read_head(path: Path) -> bytes:
    """First SNIFF_BYTES of DECOMPRESSED content — never sniff compressed bytes."""
    with open_bytes(path) as stream:
        return stream.read(SNIFF_BYTES)
