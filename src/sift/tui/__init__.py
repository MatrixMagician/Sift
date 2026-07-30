"""Interactive case browser (SPEC.md §5.7): the Textual TUI package.

Read-side composition only: every byte the TUI shows comes through the
existing ``CaseStore`` read APIs — no SQL lives here (store.py owns all
SQL), and nothing in this package talks HTTP. The TUI adds zero egress
(R020).
"""
