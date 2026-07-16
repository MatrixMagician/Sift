"""Deterministic synthetic-log generator for the M2 perf gate (SPEC §8 M2).

Importable from tests (``import generate_synthetic`` — pytest prepend mode
inserts tests/perf on sys.path) and runnable directly::

    python tests/perf/generate_synthetic.py OUT MB [SEED]

Seeded via random.Random(seed): repeated generation is byte-identical for the
same seed and size. Lines are ISO-8601-timestamped and cycle ~20 template
shapes whose only variation is volatile tokens (numbers, 0x-hex, 32-hex
session ids, paths, IPs) — so template masking (CLUS-01) collapses them to
roughly ``len(TEMPLATES)`` groups (the ≥90% reduction property).

ASCII only: written character counts equal byte counts, so the size loop can
count ``len(line)`` without re-encoding.
"""

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ~20 realistic shapes: MCM contract denials with 0x codes and 32-hex
# sessions, pool-exhaustion warnings with peer IPs, request-completed infos.
# Volatile tokens stay whitespace-delimited (never glued to letters, e.g.
# "user {n}" not "u{n}") so the <NUM> word-boundary mask fires on them.
TEMPLATES: list[str] = [
    "ERROR [Thread-{thread}] MCM contract {hex8} denied for session {sid}",
    "WARN connection pool exhausted after {n} retries (peer {ip}:{port})",
    "INFO request {sid} completed in {ms} ms",
    "INFO worker {thread} picked up job {n} from queue depth {k}",
    "ERROR failed to open {path}: errno {k}",
    "WARN slow query took {ms} ms on connection {n}",
    "INFO flushed {n} rows to {path} in {ms} ms",
    "DEBUG heartbeat from node {ip} seq {n}",
    "ERROR session {sid} expired after {n} s of inactivity",
    "INFO cache eviction removed {n} entries ({k} MB reclaimed)",
    "WARN retrying RPC to {ip}:{port} attempt {k}",
    "INFO checkpoint {hex8} written to {path}",
    "ERROR deadlock detected on lock {hex8} held by thread {thread}",
    "DEBUG GC pause {ms} ms, heap {n} MB",
    "INFO user {n} authenticated from {ip}",
    "WARN certificate for node {ip} expires in {k} days",
    "ERROR contract request failed with status {hex8} after {ms} ms",
    "INFO compacted segment {path} ({n} records)",
    "WARN thread pool queue depth {k} exceeds soft limit {n}",
    "DEBUG scheduler tick {n} completed in {ms} ms",
]

_BASE_TS = datetime(2026, 7, 16, 0, 0, 0, tzinfo=UTC)


def _tokens(rng: random.Random) -> dict[str, str | int]:
    """One line's volatile-token values (all rng-driven, deterministic)."""
    return {
        "n": rng.randrange(1, 100_000),
        "k": rng.randrange(1, 512),
        "ms": rng.randrange(1, 30_000),
        "thread": rng.randrange(1, 128),
        "port": rng.randrange(1024, 65_536),
        "hex8": f"0x{rng.getrandbits(32):08x}",
        "sid": f"{rng.getrandbits(128):032x}",
        "ip": f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(256)}",
        "path": f"/opt/app/data/shard{rng.randrange(64)}"
        f"/segment{rng.randrange(4096)}.dat",
    }


def generate(path: Path, target_mb: int = 1, seed: int = 42) -> None:
    """Write ~target_mb MiB of seeded synthetic log lines to ``path``."""
    rng = random.Random(seed)
    target = target_mb * 2**20
    written = 0
    i = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        while written < target:
            ts = (_BASE_TS + timedelta(seconds=i)).isoformat()
            body = TEMPLATES[i % len(TEMPLATES)].format(**_tokens(rng))
            line = f"{ts} {body}\n"
            fh.write(line)
            written += len(line)  # ASCII: chars == bytes
            i += 1


if __name__ == "__main__":
    if not 3 <= len(sys.argv) <= 4:
        sys.exit(f"usage: {sys.argv[0]} OUT MB [SEED]")
    generate(
        Path(sys.argv[1]),
        int(sys.argv[2]),
        int(sys.argv[3]) if len(sys.argv) == 4 else 42,
    )
