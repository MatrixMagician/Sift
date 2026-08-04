"""Thread-dump grammars: the only format-dependent part of stack analysis.

A native ``eu-stack`` dump, a Solaris ``pstack`` dump and a Linux ``pstack``
(gdb ``thread apply all bt``) dump all express the same thing — one call stack
per thread — in three spellings. The reverse-engineered MicroStrategy Support
Utility reached the same conclusion from the other direction: its stack-format
menu is a table of *thread delimiter* + *thread-header regex* pairs, and
everything downstream of the split (role detection, processing-unit lookup,
grouping) runs on the raw block text and is byte-for-byte identical across
formats.

This module is that table, as data. A ``DumpGrammar`` says how to spot a thread
header, how to read its thread id, how to spot a frame line and how to reduce a
frame line to a bare symbol. Adding a fourth format (AIX ``dbx``, WinDBG) is a
new ``DumpGrammar`` here and its registration in ``GRAMMARS`` — no change to the
adapter, the classifier, the processing-unit mapping or any renderer.

Detection is per thread block, not per file (``grammar_for_block``), so a
concatenation of captures from two hosts in different formats still parses.
Cheap because a block's first line decides it.

Symbol extraction is the one place the formats genuinely differ in what must be
DISCARDED, and the rule throughout is *strip location and offset noise, keep
the symbol including its C++ argument and template lists*. Keeping argument
lists is deliberate and measured: dropping them collapses the v1.3 reference
capture from 93 distinct signatures to 88, merging stacks that are genuinely
different work.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

# --- eu-stack (elfutils) -----------------------------------------------------
# PID 21874 - process
# TID 21874:
# #0  0x00007f3c1a2e7b0d __pthread_cond_wait
# #1  0x0000000004b1a5c1 SemaphoreImpl::WaitForResource - libfoo.so foo.cpp:91
_EU_HEADER_RE = re.compile(r"^TID (\d+):")
_EU_FRAME_RE = re.compile(r"^#(\d+)\s+0x([0-9A-Fa-f]+)\s+(.+)$")

# --- Solaris pstack ----------------------------------------------------------
# -----------------  lwp# 41 / thread# 41  --------------------
#  fffffd7ffe62b2ba lwp_park (0, 0, 0)
#  0000000004b1a5c1 SemaphoreImpl::WaitForResource (0x1) + 91
# The header line also carries "thread# 41"; the lwp number is the kernel
# thread id and the one an engineer correlates against other diagnostics, so
# it is what group 1 captures.
_SOLARIS_HEADER_RE = re.compile(r"^-*\s*lwp#\s*(\d+)")
# Six or more hex digits: an instruction address, never a frame number. The
# leading whitespace is required — it is what distinguishes a frame line from
# the header rule above and from prose.
_SOLARIS_FRAME_RE = re.compile(r"^\s+([0-9A-Fa-f]{6,})\s+(\S.*)$")
# " + 91" / " + 2b3" — the offset into the function, always last on the line.
_SOLARIS_OFFSET_RE = re.compile(r"\s+\+\s+[0-9A-Fa-f]+\s*$")

# --- Linux pstack / gdb "thread apply all bt" --------------------------------
# Thread 7 (Thread 0x7f0d5c1f7700 (LWP 21875)):
# #0  0x00007f0d5e9a1234 in pthread_cond_wait@@GLIBC_2.3.2 () from /lib64/x.so
# #1  0x0000000004b1a5c1 in SemaphoreImpl::WaitForResource (this=0x1) at s.cpp:91
# #2  0x00000000049f3210 in MSIQTask::GetNextJob ()
# The LWP is the kernel thread id and is preferred over gdb's own sequential
# thread number, which is an artefact of the debugging session and correlates
# with nothing outside it. gdb omits the LWP when the target has no threads;
# group 1 then carries the sequential number as the honest best available.
_GDB_HEADER_RE = re.compile(r"^Thread \d+ \(.*?LWP (\d+)\)")
_GDB_HEADER_FALLBACK_RE = re.compile(r"^Thread (\d+) \(")
# The address is optional: gdb omits it for a frame whose PC is exactly a
# function entry, printing "#0  sym () at f.c:1".
_GDB_FRAME_RE = re.compile(r"^#(\d+)\s+(?:0x([0-9A-Fa-f]+)\s+)?in\s+(.+)$")
# gdb prints the frame's source location or providing object last. Both are
# location noise, and both are stripped: the same stack captured with and
# without debug symbols installed must produce the same signature, or a
# signature would silently mean "this stack on this machine".
_GDB_LOCATION_RE = re.compile(r"\s+(?:at\s+\S+:\d+|from\s+\S+)\s*$")
# eu-stack's own equivalent location tail (" - <lib> <source>:<line>").
_EU_LOCATION_SEPARATOR = " - "


def strip_call_arguments(symbol: str) -> str:
    """Drop a trailing balanced ``(...)`` argument group from a symbol.

    Applied to the pstack grammars and NOT to eu-stack, because the three
    formats put different things in those parentheses:

    - eu-stack prints a demangled TYPE signature (``Wait(unsigned int)``),
      which is identical for every thread in the function. Keeping it is
      measured to matter: dropping type signatures collapses the v1.3
      reference capture from 93 distinct signatures to 88, merging genuinely
      different overloads.
    - gdb prints argument VALUES (``(this=0x55f1c0, timeout=30)``) and Solaris
      pstack prints raw argument words (``lwp_park (0, 0, 0)``). Those differ
      per thread and per capture, so keeping them would give every thread its
      own signature and defeat grouping entirely — the exact failure the
      MicroStrategy Support Utility documents as its own sharp edge, where
      hit-count dedup "is only meaningful for symbol-only stack formats".

    Balanced-scan from the right rather than a regex, so a nested group
    (``foo(std::pair<int, int>(1, 2))``) is removed whole. Anything after the
    closing parenthesis (a ``const``/``volatile`` qualifier) is dropped with
    it, since it qualifies the call that is being dropped.

    A symbol whose trailing group IS its name — ``operator()`` — is returned
    unchanged: stripping there would turn every functor frame into a bare
    ``operator`` and merge unrelated stacks.
    """
    text = symbol.rstrip()
    # Walk back over a trailing qualifier such as ` const` to find the ')'.
    end = text.rfind(")")
    if end == -1 or text[end + 1 :].strip() not in ("", "const", "volatile"):
        return symbol.strip()
    depth = 0
    for position in range(end, -1, -1):
        char = text[position]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                head = text[:position].rstrip()
                if not head or head.endswith("operator"):
                    return symbol.strip()
                return head
    return symbol.strip()


def eu_symbol(body: str) -> str:
    """Drop eu-stack's ``- <lib> <source>:<line>`` tail.

    The demangled type signature in parentheses is deliberately KEPT — see
    ``strip_call_arguments`` for the measurement behind that.
    """
    return body.split(_EU_LOCATION_SEPARATOR, 1)[0].strip()


def solaris_symbol(body: str) -> str:
    """Drop Solaris pstack's ``+ <offset>`` tail and its argument values."""
    return strip_call_arguments(_SOLARIS_OFFSET_RE.sub("", body))


def gdb_symbol(body: str) -> str:
    """Drop gdb's ``at <file>:<line>`` / ``from <object>`` location tail and
    its argument values."""
    return strip_call_arguments(_GDB_LOCATION_RE.sub("", body))


@dataclass(frozen=True)
class DumpGrammar:
    """How one thread-dump format spells a thread header and a frame.

    ``name`` is reported verbatim in the ``## Dumps`` table so an engineer can
    see which grammar their file was read with, rather than inferring it from
    whether the output looks plausible.
    """

    name: str
    header: re.Pattern[str]
    frame: re.Pattern[str]
    # Which capture group of `frame` holds the frame body.
    body_group: int
    symbol: Callable[[str], str]
    # Consulted only when `header` does not match; lets gdb fall back from the
    # LWP to its own sequential thread number.
    header_fallback: re.Pattern[str] | None = None

    def match_header(self, line: str) -> str | None:
        """The thread id this line declares, or ``None`` if it declares none."""
        found = self.header.match(line)
        if found is not None:
            return found.group(1)
        if self.header_fallback is not None:
            fallback = self.header_fallback.match(line)
            if fallback is not None:
                return fallback.group(1)
        return None


EUSTACK_GRAMMAR = DumpGrammar(
    name="eu-stack",
    header=_EU_HEADER_RE,
    frame=_EU_FRAME_RE,
    body_group=3,
    symbol=eu_symbol,
)

SOLARIS_PSTACK_GRAMMAR = DumpGrammar(
    name="solaris-pstack",
    header=_SOLARIS_HEADER_RE,
    frame=_SOLARIS_FRAME_RE,
    body_group=2,
    symbol=solaris_symbol,
)

GDB_PSTACK_GRAMMAR = DumpGrammar(
    name="gdb-pstack",
    header=_GDB_HEADER_RE,
    frame=_GDB_FRAME_RE,
    body_group=3,
    symbol=gdb_symbol,
    header_fallback=_GDB_HEADER_FALLBACK_RE,
)

# Order is the detection precedence for `grammar_for_block`. eu-stack is first
# because it is Sift's primary format and its header is the most specific of
# the three; gdb is tried before Solaris because a gdb frame line can never be
# mistaken for a Solaris one (it starts with '#') while the reverse is also
# true, so the pair is order-independent in practice.
GRAMMARS: tuple[DumpGrammar, ...] = (
    EUSTACK_GRAMMAR,
    GDB_PSTACK_GRAMMAR,
    SOLARIS_PSTACK_GRAMMAR,
)


def grammar_for_header(line: str) -> DumpGrammar | None:
    """The grammar whose thread-header rule this line satisfies, if any."""
    for grammar in GRAMMARS:
        if grammar.match_header(line) is not None:
            return grammar
    return None


def grammar_for_block(raw: str) -> DumpGrammar | None:
    """The grammar for one raw thread block, decided by its header line.

    A block whose first line is no grammar's header (a preamble region, or a
    block handed in without its header) falls back to whichever grammar can
    read a frame out of it, so a caller holding frames-only text still gets a
    signature rather than silence.
    """
    lines = raw.splitlines()
    for line in lines:
        found = grammar_for_header(line)
        if found is not None:
            return found
        if line.strip():
            break
    for grammar in GRAMMARS:
        if any(grammar.frame.match(line) is not None for line in lines):
            return grammar
    return None


def iter_frames(raw: str) -> Iterator[tuple[int, str]]:
    """Split a raw thread block into ``(frame_index, symbol)`` pairs, in file
    order, over the full block depth, in whichever grammar the block is in.

    The index is the frame's POSITION IN THIS BLOCK, counted from zero, not
    the number the dump prints. For eu-stack and gdb the two coincide; Solaris
    pstack prints no frame numbers at all, so a position is the only thing all
    three formats can agree on, and every consumer (rule ``frame_index``, the
    processing-unit attribution depth, the enclosing-application-frame walk)
    is a position already.

    The symbol has already had its format's location and offset noise removed;
    ``pipeline.eustack.normalise`` then handles the cross-format concerns (the
    ``@GLIBC_2.2.5`` version suffix).
    """
    grammar = grammar_for_block(raw)
    if grammar is None:
        return
    position = 0
    for line in raw.splitlines():
        found = grammar.frame.match(line)
        if found is not None:
            yield position, grammar.symbol(found.group(grammar.body_group))
            position += 1
