"""Convert a MicroStrategy Support Utility ``taskmap`` into ``[[pu]]`` rows.

The nine processing units shipped in ``rules/eustack_roles.toml`` are the
utility's **compiled-in defaults**, which its own specification records as dead
in v1.25: they are constructed at static-init and never read. The live mapping
is the ``taskmap`` file the utility fetches from a corporate share and caches at
``%ProgramData%\\MSTRSuppUtil\\taskmap``, and that file is expected to outgrow
the built-in list — the utility warns "The current PUMap contains additional PUs
that this version of the plugin cannot support" precisely when it does.

So Sift's shipped rows are a 2022 snapshot with a shelf life. This module is the
way off that snapshot: an engineer who has a current ``taskmap`` (any MSTRSuppUtil
install has one cached locally) converts it to ``[[pu]]`` rows and either replaces
the packaged file or points ``[eustack] rules_path`` at the result. No network
access, no DLL, no hand-transcription — hand-transcription is precisely how
``Delivery(NCSPU)`` acquired a space that is not in the binary.

The grammar is the utility's own parser, reproduced from its recovered
behaviour:

```
file       := line*
line       := lut | pu-header | task-entry
lut        := "LUT:" number                 ; revision counter, not a timestamp
pu-header  := ":" pu-display-name <1 char>  ; first and last character stripped
task-entry := signature "," description     ; split on the FIRST comma
```

Entries accumulate under the most recent header, and the PU index is the header's
ordinal position. Two of the utility's parsing quirks are deliberately NOT
reproduced, because both are bugs rather than format:

- It takes ``substr(1, len-2)`` on a header, stripping the leading ``:`` **and
  one trailing character** — which is the CR of a CRLF file. On an LF file that
  silently eats the last character of the queue's name. This module strips a
  trailing ``:`` when present and handles line endings properly, so ``:Command
  PU:`` yields ``Command PU`` under both.
- It caps ``PUMap`` at ten names while still inserting task groups above that,
  so a thread mapped to PU >= 10 renders ``Out of Bounds``. There is no cap here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The revision counter line. Read and reported so an operator can tell which
# taskmap generation a rules file was built from, but never used for ordering.
_LUT_RE = re.compile(r"^LUT:\s*(\d+)")

# A `subsystem` slug derived from the queue name: lowercase, non-alphanumerics
# collapsed to single hyphens. Deterministic, so re-importing the same taskmap
# yields byte-identical rows.
_SLUG_SPLIT_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class TaskmapEntry:
    """One ``signature,description`` pair under one processing unit."""

    pu_index: int
    pu_name: str
    signature: str
    description: str


@dataclass
class Taskmap:
    """A parsed taskmap: its revision counter, its queues in file order, and
    every task entry.

    ``skipped`` records lines the parser could not classify, with their line
    numbers. Nothing is dropped silently — an operator converting a taskmap
    needs to know if part of it did not survive.
    """

    lut: int | None = None
    pu_names: list[str] = field(default_factory=list[str])
    entries: list[TaskmapEntry] = field(default_factory=list[TaskmapEntry])
    skipped: list[tuple[int, str]] = field(
        default_factory=list[tuple[int, str]]
    )


def parse_taskmap(text: str) -> Taskmap:
    """Parse taskmap text. Never raises on malformed input: an unclassifiable
    line is recorded in ``skipped`` rather than aborting the import, because a
    taskmap that is 95% readable is still worth 95% of the rows.

    A task entry appearing before any ``:PU:`` header has no queue to belong to
    and is skipped rather than invented a home for.
    """
    result = Taskmap()
    current_index = -1
    current_name: str | None = None

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip("\r\n").rstrip()
        if not line.strip():
            continue
        lut_match = _LUT_RE.match(line)
        if lut_match is not None:
            result.lut = int(lut_match.group(1))
            continue
        if line.startswith(":"):
            # Strip the leading ':' and a trailing ':' when present. The utility
            # blindly drops the last character here; doing that on an LF file
            # truncates the name, so this reads the delimiter instead.
            name = line[1:]
            if name.endswith(":"):
                name = name[:-1]
            name = name.strip()
            if not name:
                result.skipped.append((line_no, raw))
                continue
            current_index += 1
            current_name = name
            result.pu_names.append(name)
            continue
        signature, sep, description = line.partition(",")
        if not sep or not signature.strip():
            result.skipped.append((line_no, raw))
            continue
        if current_name is None:
            # A task entry before any header belongs to no queue.
            result.skipped.append((line_no, raw))
            continue
        result.entries.append(
            TaskmapEntry(
                pu_index=current_index,
                pu_name=current_name,
                signature=signature.strip(),
                description=description.strip(),
            )
        )
    return result


def subsystem_slug(pu_name: str) -> str:
    """A stable ``subsystem`` slug for a queue name.

    ``Delivery(NCSPU)`` -> ``delivery-ncspu``; ``Document Data Preparation`` ->
    ``document-data-preparation``. Purely derived, so two imports of one taskmap
    agree, and a curator remains free to hand-edit the result afterwards.
    """
    slug = _SLUG_SPLIT_RE.sub("-", pu_name.lower()).strip("-")
    return slug or "unnamed"


def _toml_literal(value: str) -> str:
    """Render a string as a TOML literal (single-quoted, no escapes) when it
    can be, else a basic string with the two escapes TOML requires.

    Literal strings are preferred for patterns because a C++ symbol carries
    backslashes in no realistic case but is full of characters a basic string
    would invite escaping mistakes around.
    """
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def to_pu_rows(taskmap: Taskmap) -> str:
    """Render ``[[pu]]`` rows for every task entry, in taskmap order.

    One row per SIGNATURE, not per queue: a queue with several dispatch frames
    is legitimately several rows sharing one ``name`` and ``index``, which the
    rules loader accepts by design and aggregates into one reported row.

    ``match = "contains"`` on every row, reproducing the utility's substring
    semantics — its ``TaskMap::Lookup`` does a plain ``find`` over the whole
    thread block, so an exact-match import would silently stop matching stacks
    the utility matches.

    The output is a fragment to paste or append, not a whole rules file: it
    carries no ``[meta]``, so a careless overwrite of ``eustack_roles.toml``
    fails loudly at load rather than producing a file with no role rules.
    """
    lines: list[str] = [
        "# Generated from a MicroStrategy Support Utility taskmap by",
        "# `sift taskmap`. One row per signature; a queue with several dispatch",
        "# frames is several rows sharing one name and index, which the loader",
        "# accepts and aggregates into one reported row.",
        "#",
        "# Review before use. `subsystem` is derived from the queue name and is",
        "# free to be hand-edited; `description` is shown to the operator and to",
        "# the model, so it is worth reading for anything that would be unclear",
        "# out of context.",
    ]
    if taskmap.lut is not None:
        lines.append(f"# Source taskmap revision (LUT): {taskmap.lut}")
    for entry in taskmap.entries:
        lines.extend(
            [
                "",
                "[[pu]]",
                f"index = {entry.pu_index}",
                f"name = {_toml_literal(entry.pu_name)}",
                f"subsystem = {_toml_literal(subsystem_slug(entry.pu_name))}",
                'match = "contains"',
                f"pattern = {_toml_literal(entry.signature)}",
                f"description = {_toml_literal(entry.description or entry.pu_name)}",
            ]
        )
    return "\n".join(lines) + "\n"
