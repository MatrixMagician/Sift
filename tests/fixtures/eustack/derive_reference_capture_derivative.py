"""Manual, offline derivation of the signature-preserving eu-stack test fixture.

This is a provenance tool, not test code. Pytest never collects it (its
filename does not match ``test_*.py``) and it never runs in CI, because its
input is a real, out-of-repo eu-stack capture (roughly 2.4 MB per dump,
carrying a customer environment identifier) that is deliberately never
committed to this repository.

This script performs mechanical, structural extraction only. It splits the
capture into per-thread blocks the same way the shipped adapter does, groups
those blocks by their stack signature (imported, never re-derived), keeps a
capped number of blocks per group, and renumbers/redacts identifying header
fields on the way out. It has no notion of thread role, no matching-rule
concept, no per-pool or per-dependency grouping, and no logic that inspects
what a stack MEANS at all -- so the fixture it produces cannot have been
shaped to agree with anything downstream that does assign meaning to a
stack. That is the failure mode ``.planning/research/PITFALLS.md`` Pitfall 5
names, and the one the phase's own golden-fixture requirement guards
against.

Recorded invocation (the out-of-repo input path is a placeholder below --
see the paragraph above for why the real one is never written into this
repository): run this script against the earlier ("160739") of the two
reference dumps, writing to the committed fixture path::

    uv run python tests/fixtures/eustack/derive_reference_capture_derivative.py \\
        <path-to-out-of-repo-capture> \\
        tests/fixtures/eustack/reference_capture_derivative.txt

A second, optional ``--scale N`` mode (Plan 19-03, EUS-12) derives a
THREAD-PROPORTION-faithful fixture instead of a signature-preserving one: the
per-signature keep count becomes ``round(count / N)`` (a signature rounding to
zero contributes no blocks at all -- that zero is the point, since it is what
keeps a rare signature rare in the derivative too), rather than the fixed
``_HIGH_POPULATION_CAP``/``_DEFAULT_CAP`` split above. Omitting ``--scale``
leaves every existing behaviour, including the committed fixture's byte
identity, unchanged. Recorded invocation for the eu-stack-healthy golden case::

    uv run python tests/fixtures/eustack/derive_reference_capture_derivative.py \\
        <path-to-out-of-repo-capture> \\
        eval/cases/eustack-healthy/input/threaddump.txt \\
        --scale 26
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

# Shared, not copied (D-08 / the adapter's own house rule): this tool reuses
# the shipped header regex and the shipped signature function rather than
# growing a second definition of either.
from sift.adapters.eustack import _TID_RE  # pyright: ignore[reportPrivateUsage]
from sift.pipeline.eustack import signature_of

_SYNTHETIC_PID_HEADER = "PID 999999 - process\n"
_SYNTHETIC_TID_START = 100_001
_HIGH_POPULATION_CAP = 5
_DEFAULT_CAP = 1
_HIGH_POPULATION_COUNT = 3

Signature = tuple[str, ...]


def iter_thread_blocks(text: str) -> Iterator[str]:
    """Group raw capture text into per-thread blocks.

    Mirrors the shipped adapter's own grouping rule: a ``TID <n>:`` header
    line starts a new block, and every following line accrues to it until
    the next header or end of file. Any text before the first header (the
    dump's own preamble) is not a thread block and is not yielded here --
    this tool writes its own synthetic preamble on the way out instead.
    """
    block: list[str] = []
    for line in text.splitlines(keepends=True):
        if _TID_RE.match(line) is not None:
            if block:
                yield "".join(block)
            block = [line]
        elif block:
            block.append(line)
    if block:
        yield "".join(block)


def group_by_signature(blocks: Iterable[str]) -> dict[Signature, list[str]]:
    """Group thread blocks by their stack signature, in first-seen order.

    Dict insertion order is guaranteed (Python >= 3.7), so the returned
    mapping's iteration order is exactly the order each signature first
    appeared while scanning the capture top to bottom -- a mechanical
    property of the file, not a chosen ordering.
    """
    groups: dict[Signature, list[str]] = {}
    for block in blocks:
        groups.setdefault(signature_of(block), []).append(block)
    return groups


def high_population_signatures(
    groups: Mapping[Signature, list[str]], count: int = _HIGH_POPULATION_COUNT
) -> set[Signature]:
    """The ``count`` signatures with the most thread blocks, by raw count.

    Ties are broken by first-seen order (stable sort), so the result is
    reproducible from the same input without depending on Python's dict/set
    hash seed.
    """
    ranked = sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
    return {signature for signature, _blocks in ranked[:count]}


def _renumber_header(block: str, synthetic_tid: int) -> str:
    """Rewrite a block's leading ``TID <n>:`` header to a sequential
    synthetic id. Every frame line after the header passes through
    byte-verbatim -- only the header's own line is touched.
    """
    lines = block.splitlines(keepends=True)
    header = lines[0]
    if _TID_RE.match(header) is None:
        raise ValueError(f"block does not start with a TID header: {header!r}")
    new_header = _TID_RE.sub(f"TID {synthetic_tid}:", header, count=1)
    return new_header + "".join(lines[1:])


def build_derivative_body(
    groups: Mapping[Signature, list[str]],
    high_population: set[Signature],
    start_tid: int = _SYNTHETIC_TID_START,
) -> tuple[str, int]:
    """Emit the first N thread blocks per signature, headers renumbered.

    N is ``_HIGH_POPULATION_CAP`` for the highest-population signatures and
    ``_DEFAULT_CAP`` for every other signature -- every signature appears at
    least once, so the derivative reproduces every distinct signature the
    input carried. Returns the assembled body text and the total thread
    count actually emitted.
    """
    parts: list[str] = []
    tid = start_tid
    thread_count = 0
    for signature, blocks in groups.items():
        cap = _HIGH_POPULATION_CAP if signature in high_population else _DEFAULT_CAP
        for block in blocks[:cap]:
            parts.append(_renumber_header(block, tid))
            tid += 1
            thread_count += 1
    return "".join(parts), thread_count


def build_derivative_body_scaled(
    groups: Mapping[Signature, list[str]],
    scale: int,
    start_tid: int = _SYNTHETIC_TID_START,
) -> tuple[str, int]:
    """The ``--scale N`` alternative to ``build_derivative_body`` (Plan 19-03).

    Per-signature keep count is ``round(len(blocks) / scale)`` -- a signature
    whose population rounds to zero contributes NO blocks at all, which is
    what makes the derivative THREAD-PROPORTION-faithful rather than merely
    signature-preserving: a rare signature stays rare (or vanishes) in the
    derivative in the same proportion it held in the input, instead of every
    signature getting at least one representative regardless of population.
    No high-population/default-cap split exists here -- that two-tier cap
    concept belongs to ``build_derivative_body`` alone.
    """
    parts: list[str] = []
    tid = start_tid
    thread_count = 0
    for _signature, blocks in groups.items():
        keep = round(len(blocks) / scale)
        for block in blocks[:keep]:
            parts.append(_renumber_header(block, tid))
            tid += 1
            thread_count += 1
    return "".join(parts), thread_count


def build_preamble(
    original_thread_count: int,
    original_signature_count: int,
    derivative_thread_count: int,
    derivative_signature_count: int,
    *,
    scale: int | None = None,
    fixture_label: str = "tests/fixtures/eustack/reference_capture_derivative.txt",
) -> str:
    """The double-dash-prefixed provenance preamble, matching the shipped
    ``tests/fixtures/eustack/threaddump.txt`` fixture's own convention. The
    adapter's own grouping rule treats this as a ``thread=None`` fallback
    event (no ``TID`` header on any of these lines), so it can never leak
    into a thread-level assertion.

    ``scale`` states the ``--scale N`` thread-proportion policy line instead
    of the default two-tier cap policy line when set (Plan 19-03); omitting it
    leaves this function's output byte-identical to before ``--scale`` existed.
    """
    policy_line = (
        f"-- scale policy: kept round(count / {scale}) threads per signature "
        "(thread-proportion-faithful) --"
        if scale is not None
        else (
            f"-- cap policy: {_DEFAULT_CAP} thread per signature; "
            f"{_HIGH_POPULATION_CAP} threads for the "
            f"{_HIGH_POPULATION_COUNT} highest-population signatures --"
        )
    )
    lines = [
        "-- derived, sanitised eu-stack fixture -- this is NOT a raw capture --",
        policy_line,
        (
            f"-- derivative totals: {derivative_signature_count} signatures, "
            f"{derivative_thread_count} threads --"
        ),
        (
            f"-- original capture totals: {original_signature_count} signatures, "
            f"{original_thread_count} threads --"
        ),
        (
            "-- generated by: "
            "tests/fixtures/eustack/derive_reference_capture_derivative.py "
            f"<out-of-repo capture, redacted> {fixture_label}"
            + (f" --scale {scale}" if scale is not None else "")
            + " --"
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Derive a small, signature-preserving, sanitised eu-stack fixture "
            "from a real out-of-repo capture. Manual and offline -- never run "
            "in CI, since the input capture is not committed to this repo."
        )
    )
    parser.add_argument(
        "capture", type=Path, help="Path to the out-of-repo eu-stack capture."
    )
    parser.add_argument(
        "fixture", type=Path, help="Path to write the derived fixture to."
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=None,
        help=(
            "Thread-PROPORTION-faithful mode (Plan 19-03): keep "
            "round(count / N) blocks per signature instead of the default "
            "two-tier cap. Omit for the original signature-preserving "
            "behaviour (byte-identical to before this flag existed)."
        ),
    )
    args = parser.parse_args()

    text = args.capture.read_text(encoding="utf-8", errors="replace")
    blocks = list(iter_thread_blocks(text))
    groups = group_by_signature(blocks)
    if args.scale is not None:
        body, derivative_thread_count = build_derivative_body_scaled(
            groups, args.scale
        )
    else:
        high_population = high_population_signatures(groups)
        body, derivative_thread_count = build_derivative_body(
            groups, high_population
        )
    derivative_signature_count = len(groups)

    preamble = build_preamble(
        original_thread_count=len(blocks),
        original_signature_count=len(groups),
        derivative_thread_count=derivative_thread_count,
        derivative_signature_count=derivative_signature_count,
        scale=args.scale,
        fixture_label=str(args.fixture),
    )
    output_text = preamble + _SYNTHETIC_PID_HEADER + body
    args.fixture.write_text(output_text, encoding="utf-8")

    size_bytes = len(output_text.encode("utf-8"))
    print(f"signatures: {derivative_signature_count}")
    print(f"threads: {derivative_thread_count}")
    print(f"bytes: {size_bytes}")


if __name__ == "__main__":
    main()
