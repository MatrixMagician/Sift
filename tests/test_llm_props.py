"""``determinism_warnings`` — the pure ``/props`` decision (ADR 0020, T-03-15).

Zero sockets, zero clients, zero ``CliRunner``: every case here is a dict
literal in and a list of strings out. That is the whole point of the extraction
— both defects fixed in T-03-15 survived because the branch could only be
reached by driving a mock HTTP server through the CLI, which is expensive
enough that the seed branch ended up with no test at all.

The wire-level half of this behaviour (warnings reach stderr, keep stdout
scriptable and do not fail the run) stays in ``tests/test_doctor.py`` on
``CliRunner`` — see ``test_multi_slot_warns_but_passes``. Deleting the loop in
``cli.py`` must go red there, not here.
"""

from sift.llm.props import determinism_warnings

# The verbatim shape served by a real llama.cpp /props (trimmed to the keys
# under test), captured from the operator's Lemonade-managed server. llama.cpp
# nests the sampler knobs under "params" and reports a random seed as
# UINT32_MAX (4294967295 == -1 unsigned), never as a negative int -- the two
# facts that made the warning dead code before T-03-15.
_LLAMACPP_PROPS: dict[str, object] = {
    "params": {"seed": 4294967295, "temperature": 0.800000011920929, "top_k": 40},
    "n_ctx": 32768,
}


def _warn(
    gen_settings: object = None,
    *,
    seed_override: int | None = None,
    temperature_override: float | None = None,
    **props: object,
) -> list[str]:
    """Build a ``/props`` body and return its warnings.

    ``gen_settings`` lands under ``default_generation_settings``, mirroring the
    key the server actually serves. The two overrides are the configured
    ``generation.seed`` / ``generation.temperature`` (SEED-003), passed through
    verbatim.
    """
    body = dict(props)
    if gen_settings is not None:
        body["default_generation_settings"] = gen_settings
    return determinism_warnings(
        body,
        seed_override=seed_override,
        temperature_override=temperature_override,
    )


def test_random_seed_warns_on_llamacpp_uint32_sentinel() -> None:
    """A random seed reported as UINT32_MAX under params must warn."""
    warnings = _warn(_LLAMACPP_PROPS)
    assert any("seed is random" in w for w in warnings), warnings
    assert any("4294967295" in w for w in warnings), warnings


def test_nonzero_temperature_warns() -> None:
    """temperature > 0 makes identical prompts diverge; say so."""
    warnings = _warn(_LLAMACPP_PROPS)
    assert any("temperature is 0.8" in w for w in warnings), warnings


def test_llamacpp_props_warn_seed_then_temperature_and_nothing_else() -> None:
    """Emission order and count are part of the contract, not an accident.

    The two warnings the real llama.cpp shape produces, in the order doctor
    prints them -- an assertion the previous substring-in-output tests could
    not make, because a mixed CLI stream cannot distinguish order from
    coincidence.
    """
    warnings = _warn(_LLAMACPP_PROPS)
    assert len(warnings) == 2, warnings
    assert warnings[0].startswith("Warning: server seed is random (4294967295)")
    assert warnings[1].startswith("Warning: server temperature is 0.8")


def test_deterministic_server_warns_about_neither() -> None:
    """A fixed seed at temperature 0 is silent -- the warnings must discriminate."""
    assert _warn({"params": {"seed": 42, "temperature": 0.0}}) == []


def test_negative_seed_still_warns() -> None:
    """The original `seed < 0` contract is preserved, not replaced."""
    warnings = _warn({"params": {"seed": -1, "temperature": 0.0}})
    assert any("seed is random" in w for w in warnings), warnings


def test_unnested_seed_still_warns() -> None:
    """A server exposing the knobs un-nested is still read (both shapes)."""
    warnings = _warn({"seed": 4294967295, "temperature": 0.7})
    assert any("seed is random" in w for w in warnings), warnings
    assert any("temperature is 0.7" in w for w in warnings), warnings


def test_absent_generation_settings_warns_nothing() -> None:
    """Lemonade serves no props document at all: degrade quietly (LLM-04)."""
    assert determinism_warnings({}) == []


def test_multi_slot_warns() -> None:
    """n_parallel > 1 is a multi-slot server: reproducibility is not guaranteed.

    The CLI keeps its own copy of this case (``test_multi_slot_warns_but_passes``)
    because it is the wire-level witness; this one pins the decision itself.
    """
    warnings = _warn(n_parallel=4)
    assert warnings == [
        "Warning: server reports n_parallel=4 (multi-slot); results may be "
        "non-deterministic — run a single slot for reproducible triage"
    ]


def test_single_slot_is_silent() -> None:
    """The n_parallel=1 default must not warn -- the discriminating half."""
    assert determinism_warnings({"n_parallel": 1}) == []


def test_bool_values_are_not_read_as_numbers() -> None:
    """``bool`` is a subclass of ``int``: ``n_parallel: true`` is not two slots.

    No real server sends these, but the guards exist and an unguarded
    ``n_parallel > 1`` would read ``True`` as 1 and ``seed`` as falsy-but-int.
    Pin the guards so a later simplification cannot quietly drop them.
    """
    assert determinism_warnings({"n_parallel": True}) == []
    assert _warn({"params": {"seed": True, "temperature": True}}) == []


# --- overrides suppress the risk they control (SEED-003) ----------------------


def test_configured_seed_suppresses_the_seed_warning() -> None:
    """A request-level seed beats the server's loaded one, so the warning is
    false once it is set.

    Sift now sends ``generation.seed`` in every chat body. Continuing to tell
    the operator their random server seed threatens reproducibility, when Sift
    overrides it on every request, teaches them to ignore doctor's warnings.
    """
    warnings = _warn(_LLAMACPP_PROPS, seed_override=42)
    assert not any("seed is random" in w for w in warnings), warnings
    # The temperature risk is untouched: it has its own override.
    assert any("temperature is 0.8" in w for w in warnings), warnings


def test_configured_temperature_suppresses_the_temperature_warning() -> None:
    warnings = _warn(_LLAMACPP_PROPS, temperature_override=0.0)
    assert not any("temperature is" in w for w in warnings), warnings
    assert any("seed is random" in w for w in warnings), warnings


def test_both_overrides_silence_the_sampling_warnings() -> None:
    assert _warn(_LLAMACPP_PROPS, seed_override=42, temperature_override=0.0) == []


def test_overrides_do_not_suppress_the_multi_slot_warning() -> None:
    """Slot scheduling is not something a request body can control.

    The seam only suppresses risks Sift has actually taken control of; treating
    the overrides as a blanket "determinism is handled" flag would hide a real
    multi-slot non-determinism.
    """
    warnings = _warn(
        _LLAMACPP_PROPS, seed_override=42, temperature_override=0.0, n_parallel=4
    )
    assert len(warnings) == 1
    assert "n_parallel=4" in warnings[0]
