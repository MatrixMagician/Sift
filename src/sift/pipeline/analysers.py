"""The deterministic-analyser registry (the analyser counterpart of ``adapters``).

Each domain analyser family (MCM, perfmon, eu-stack, ...) contributes one
``Analyser`` entry: a name, the triage-template block it owns (``marker`` +
``slot`` — see ``prompts/triage.md``), the event ``sources`` it consumes, and a
``build`` function that turns stored events into a fact block — the
``(block_text, citable_ids)`` pair every ``*_facts`` renderer returns.

``hypothesise`` iterates ``ANALYSERS`` instead of naming each domain: adding
analyser #4 is a new pipeline module plus ONE registry entry plus one sentinel
block in ``triage.md`` — ``hypothesise.py`` does not change. This mirrors the
adapter registry's "new module + one registration line" contract
(``adapters/__init__.py``).

That cost is the cost to the PROMPT path, which is the only thing this registry
describes. A ``sift <domain>`` bundle command is separate, optional work with
its own module in ``commands/`` and its own Typer command: mcm, perfmon and
eu-stack each have one because they are operator-facing forensics products, not
because an analyser requires it. ADR 0021 records why the registry deliberately
stops here rather than also describing the bundle surface — and
``tests/test_analysers.py`` pins the one invariant that spans both paths, that a
bundle command reads exactly the ``sources`` its entry declares.

Declaring ``sources`` here is load-bearing for memory: the fact-block path
reads only the union of the registered sources from the store
(``CaseStore.query_events(sources=...)``), never the whole case — a multi-GB
genericlog case no longer materialises every decompressed ``raw`` blob just to
build MCM/perfmon/eu-stack facts.

The MCM analysis is shared: perfmon's correlator consumes ``analyse_mcm``'s
output, so builders receive a per-run ``shared`` scratch dict and the MCM
builder stashes its analysis there (single-analysis-pass discipline). Builders
run in registry order, so a dependent analyser may rely on its dependency
having run first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sift.config import EustackThresholdsConfig, McmThresholdsConfig
from sift.pipeline import eustack
from sift.pipeline.eustack_facts import render_eustack_facts
from sift.pipeline.eustack_progression import analyse_eustack_bundle
from sift.pipeline.mcm import analyse_mcm
from sift.pipeline.mcm_facts import render_mcm_facts
from sift.pipeline.perfmon import analyse_perfmon
from sift.pipeline.perfmon_facts import render_perfmon_facts

if TYPE_CHECKING:
    from collections.abc import Callable

    from sift.config import SiftConfig
    from sift.models import Event
    from sift.pipeline.mcm import McmAnalysis

# The (block_text, citable_ids) pair every ``*_facts`` renderer returns.
# ``("", set())`` means "no data" and strips the block residue-free.
FactBlock = tuple[str, set[str]]


@dataclass(frozen=True)
class AnalyserSettings:
    """Per-run analyser configuration, threaded as ONE value (not one kwarg per
    domain) so ``hypothesise``'s signature stops growing per analyser."""

    mcm_thresholds: McmThresholdsConfig = field(default_factory=McmThresholdsConfig)
    eustack_rules_path: str | None = None
    eustack_thresholds: EustackThresholdsConfig = field(
        default_factory=EustackThresholdsConfig
    )

    @classmethod
    def from_config(cls, config: SiftConfig) -> AnalyserSettings:
        """The CLI seam: lift the analyser-relevant slices out of SiftConfig."""
        return cls(
            mcm_thresholds=config.mcm.thresholds,
            eustack_rules_path=config.eustack.rules_path,
            eustack_thresholds=config.eustack.thresholds,
        )


@dataclass(frozen=True)
class Analyser:
    """One registered deterministic analyser.

    ``marker`` names the sentinel pair in ``triage.md``
    (``<!-- {marker}_BLOCK_START/END -->``) and ``slot`` the placeholder the
    fact text replaces. ``sources`` are the ``Event.source`` values the builder
    consumes — the store query is scoped to their union. ``build`` is pure and
    LLM-free: events in, fact block out.
    """

    name: str
    marker: str
    slot: str
    sources: tuple[str, ...]
    build: Callable[[list[Event], AnalyserSettings, dict[str, object]], FactBlock]


def apply_block(
    template: str, marker: str, slot: str, fact_block: str | None
) -> str:
    """Resolve one delimited template block against a fact body.

    No data → the entire sentinel block (start marker through end marker,
    including the trailing newline) is removed, leaving the block-free prompt
    byte-identical to its pre-domain form. Data present → the two marker lines
    are dropped and the slot is replaced with ``fact_block`` (already
    ``sanitise``d value-by-value by the fact renderer — this fn only splices,
    it does NOT re-sanitise). Each block is stripped independently, so one
    domain's presence can never perturb another domain's prompt bytes.
    """
    block_re = re.compile(
        rf"<!-- {marker}_BLOCK_START.*?-->\n.*?<!-- {marker}_BLOCK_END.*?-->\n",
        re.DOTALL,
    )
    if not fact_block:
        return block_re.sub("", template)
    marker_re = re.compile(rf"<!-- {marker}_BLOCK_(?:START|END).*?-->\n")
    return marker_re.sub("", template).replace(slot, fact_block)


def _shared_mcm_analysis(
    events: list[Event], settings: AnalyserSettings, shared: dict[str, object]
) -> McmAnalysis:
    """The single MCM analysis pass, memoised in ``shared`` for perfmon."""
    analysis = shared.get("mcm_analysis")
    if analysis is None:
        analysis = analyse_mcm(events, settings.mcm_thresholds)
        shared["mcm_analysis"] = analysis
    return analysis  # pyright: ignore[reportReturnType] — only ever an McmAnalysis


def _build_mcm(
    events: list[Event], settings: AnalyserSettings, shared: dict[str, object]
) -> FactBlock:
    return render_mcm_facts(_shared_mcm_analysis(events, settings, shared))


def _build_perfmon(
    events: list[Event], settings: AnalyserSettings, shared: dict[str, object]
) -> FactBlock:
    mcm_analysis = _shared_mcm_analysis(events, settings, shared)
    return render_perfmon_facts(analyse_perfmon(mcm_analysis, events))


def _build_eustack(
    events: list[Event], settings: AnalyserSettings, shared: dict[str, object]
) -> FactBlock:
    # Attribute access rather than a from-import is incidental here, not
    # load-bearing: no test patches ``load_rules`` while driving this builder,
    # and a module-level from-import leaves the suite green. The rule-neutering
    # monkeypatch seam this used to claim to preserve lives in
    # ``eval/runner.py``, which is where the constraint is documented.
    rules, rules_hash = eustack.load_rules(settings.eustack_rules_path)
    bundle = analyse_eustack_bundle(
        events, rules, rules_hash, settings.eustack_thresholds
    )
    return render_eustack_facts(bundle, events)


# Registration order is prompt order (the blocks appear in triage.md in this
# order) AND build order (perfmon depends on the shared MCM analysis).
ANALYSERS: tuple[Analyser, ...] = (
    Analyser(
        name="mcm",
        marker="MCM",
        slot="<<MCM_FACTS>>",
        sources=("dsserrors",),
        build=_build_mcm,
    ),
    Analyser(
        name="perfmon",
        marker="PERFMON",
        slot="<<PERFMON_FACTS>>",
        # dsserrors too: the correlator anchors trends on MCM denial episodes.
        sources=("dsserrors", "dssperfmon"),
        build=_build_perfmon,
    ),
    Analyser(
        name="eustack",
        marker="EUSTACK",
        slot="<<EUSTACK_FACTS>>",
        sources=("eustack",),
        build=_build_eustack,
    ),
)

# The union of every registered analyser's event sources — the exact event
# universe the fact-block path needs from the store.
ANALYSER_SOURCES: tuple[str, ...] = tuple(
    sorted({s for a in ANALYSERS for s in a.sources})
)


def build_fact_blocks(
    events: list[Event], settings: AnalyserSettings
) -> dict[str, FactBlock]:
    """Run every registered analyser over ``events`` (one shared scratch pass).

    Returns ``{analyser.name: (block_text, citable_ids)}`` in registry order.
    A domain without data contributes ``("", set())``, which the prompt
    assembly strips residue-free.
    """
    shared: dict[str, object] = {}
    return {a.name: a.build(events, settings, shared) for a in ANALYSERS}
