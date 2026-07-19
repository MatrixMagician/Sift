"""Golden-case evaluation harness (SPEC.md §6, EVAL-01..05).

Adds *measurement*, not pipeline behaviour: every metric is a pure read of the
already-persisted ``case.db`` rows plus a frozen ``truth.yaml``. The package is
driven by the ``sift eval`` CLI command, which runs each golden case through the
existing ingest → cluster → hypothesise pipeline against a temp ``case.db`` with
an injectable OpenAI-compatible client (offline: a fake; live: the local model).
"""
