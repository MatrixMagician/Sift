"""Determinism-risk interpretation of an inference server's ``/props`` payload.

``sift doctor`` reports three reproducibility risks a server can carry: a
multi-slot configuration, a random seed, and a non-zero temperature. Sift sends
neither seed nor temperature in its chat payload, so the server's loaded
settings fully determine reproducibility — which is exactly why doctor must
read them back and say so.

The decision is PURE and returns its warnings rather than printing them, so the
whole thing is testable against a dict literal with no client, no transport and
no ``CliRunner`` — the same discipline ``commands.resolve_generation_ctx``
documents for the generation-context decision. That is not a stylistic
preference: both the seed defects fixed in T-03-15 survived precisely because
the branch had no interface to test through (ADR 0020).

It lives in ``llm/`` and not ``commands/`` because ``/props`` is llama.cpp wire
knowledge — the ``params`` nesting and the UINT32_MAX sentinel below are
protocol shape, not CLI presentation — and because ``doctor`` is not a case
command, so there is no ``run_doctor`` in ``commands/`` for it to sit beside
(CONTEXT.md, *Case command*; ADR 0020).
"""

from collections.abc import Mapping
from typing import cast

# llama.cpp reports "seed a random value each request" as UINT32_MAX in /props
# rather than as a negative int, so a `seed < 0` test alone can never detect it
# (T-03-15). Named so the determinism check reads as intent, not as magic.
_RANDOM_SEED_SENTINEL = 0xFFFFFFFF


def determinism_warnings(props: Mapping[str, object]) -> list[str]:
    """Every reproducibility risk ``props`` reports, as rendered warning lines.

    Returned in emission order — multi-slot, then seed, then temperature — and
    complete with the ``Warning: `` prefix, so the caller is a loop and nothing
    about how an operator reads a warning is split across two modules.

    Warnings are non-fatal by definition: they never contribute an exit code
    (D-02 reserves stopping for the critical checks). ``/props`` is
    feature-detected and returns ``{}`` when absent (Lemonade), so an empty
    payload warns nothing.

    Every value is bool-guarded as well as type-guarded: ``bool`` is a subclass
    of ``int``, and a server reporting ``n_parallel: true`` must not be read as
    a two-slot server.
    """
    warnings: list[str] = []

    n_parallel = props.get("n_parallel")
    if (
        isinstance(n_parallel, int)
        and not isinstance(n_parallel, bool)
        and n_parallel > 1
    ):
        warnings.append(
            f"Warning: server reports n_parallel={n_parallel} (multi-slot); "
            "results may be non-deterministic — run a single slot for "
            "reproducible triage"
        )

    gen_settings = props.get("default_generation_settings")
    if not isinstance(gen_settings, dict):
        return warnings
    settings = cast("dict[str, object]", gen_settings)
    # llama.cpp nests the sampler knobs under a "params" sub-dict and reports a
    # random seed as UINT32_MAX (4294967295 == -1 unsigned), never as a
    # negative int. Read both shapes, and treat either sentinel as random: the
    # earlier `seed < 0` test against the un-nested key could not fire on any
    # real llama.cpp build, so this warning was silently dead and a
    # non-deterministic endpoint went unreported (measured against llama.cpp
    # b7000-era /props).
    params = settings.get("params")
    source = (
        cast("dict[str, object]", params) if isinstance(params, dict) else settings
    )

    seed = source.get("seed")
    if (
        isinstance(seed, int)
        and not isinstance(seed, bool)
        and (seed < 0 or seed == _RANDOM_SEED_SENTINEL)
    ):
        warnings.append(
            f"Warning: server seed is random ({seed}); set a fixed seed "
            "for reproducible triage"
        )

    temperature = source.get("temperature")
    if (
        isinstance(temperature, int | float)
        and not isinstance(temperature, bool)
        and temperature > 0
    ):
        warnings.append(
            f"Warning: server temperature is {temperature} (> 0); "
            "identical prompts can yield different triage output — load "
            "the model at temperature 0 for reproducible triage"
        )

    return warnings
