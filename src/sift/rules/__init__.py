"""Packaged eu-stack thread-role rules (EUS-01).

This package exists so ``importlib.resources`` can load
``eustack_roles.toml`` as package data. Editing the TOML must never require a
Python change — the taxonomy is data, curated by an engineer, not code.
Rule patterns are matched as plain data (``==`` / ``str.startswith`` / ``in``)
and are never executed or evaluated.
"""
