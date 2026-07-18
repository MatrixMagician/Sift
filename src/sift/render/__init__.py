"""Report renderers (SPEC.md §5.7): Markdown now, JSON/PDF in later 06 plans.

Every renderer is a pure function of an open ``CaseStore`` — no HTTP client is
ever constructed and no re-inference happens, so the zero-egress invariant is
obviously intact and REPT-03 determinism is trivial.
"""
