"""Versioned prompt templates (CLI-02).

This package exists so ``importlib.resources`` can load the ``*.md`` prompt
templates as package data. All prompts are plain-text files here — changing a
prompt must never require a Python change (CLI-02). The templates are loaded,
never executed, and log-derived excerpts interpolated into them are treated as
untrusted data, not instructions.
"""
