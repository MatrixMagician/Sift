"""The D-05 lock-ownership vocabulary prohibition, as a product constant.

eu-stack output carries no monitor-ownership edges, so a wait-for graph cannot
be constructed from it at all — JVM ``jstack`` can only do that because the JVM
records ownership. Emitting any of these terms would assert a relationship the
data cannot support, which is a correctness claim rather than a wording
preference. This is a PERMANENT non-goal, never deferred work.

Why this module exists at all, rather than the constant living in
``eustack.py``: the eu-stack vocabulary gates previously parsed the forbidden
term out of ``.planning/REQUIREMENTS.md`` at runtime, which coupled the test
suite to a planning document and broke the whole suite the moment that document
was archived at milestone close. The prohibition is a property of the product,
so it belongs in the product.

It is deliberately NOT in ``eustack.py``: a shipped invariant test asserts the
classifier's own source text contains none of these terms, and a module that
declares them as string literals would trip its own gate. Isolating them here
keeps that assertion meaningful — this module is the single declared exception,
and it emits nothing.
"""

from __future__ import annotations

# Ordered most-specific first: the first entry is the term the original Phase 15
# gate scoped its whole-source grep to, and the full tuple is what the runtime
# output gates (S-7) enforce over emitted strings.
PROHIBITED_OWNERSHIP_TERMS: tuple[str, ...] = ("deadlock", "owner", "holder")
