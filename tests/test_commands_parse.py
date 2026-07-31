"""Direct tests for the pure parsers behind the case commands (ADR 0019).

Pass 2 of ADR 0019: these assertions used to run through ``CliRunner``, which
meant every check of a filter-key allowlist paid for a case directory, an
``ingest`` run and an exit-code round-trip. ``parse_filters`` and
``parse_moment`` are pure functions that raise ``ValueError``, so the message
and the typed result are asserted here, and ``tests/test_cli.py`` keeps only
what is genuinely CLI: that a ``ValueError`` from these becomes exit 2 with a
sanitised message.

No ``CliRunner``, no store, no filesystem.
"""

from datetime import UTC, datetime

import pytest

from sift.commands import parse_filters, parse_moment
from sift.commands.parse import FILTER_KEYS, SEVERITIES, to_utc

EVENT_FILTER_KEYS = ("severity", "source", "file", "since", "until", "limit")
CLUSTER_FILTER_KEYS = ("severity", "min-count", "contains", "limit")


# --- the allowlists themselves ------------------------------------------------


def test_filter_key_allowlists_are_the_documented_sets() -> None:
    """``show --help`` documents these key sets; the store re-validates them as
    defence in depth. A silent widening here would widen both."""
    assert FILTER_KEYS["events"] == EVENT_FILTER_KEYS
    assert FILTER_KEYS["clusters"] == CLUSTER_FILTER_KEYS
    # hypotheses takes no filters yet: an empty allowlist makes any --filter
    # fail loudly rather than being silently ignored.
    assert FILTER_KEYS["hypotheses"] == ()


# --- accepted values ---------------------------------------------------------


def test_parse_filters_no_specs_is_an_empty_dict() -> None:
    assert parse_filters([], "events") == {}


def test_parse_filters_and_combines_distinct_keys() -> None:
    parsed = parse_filters(["severity=error", "file=app"], "events")
    assert parsed == {"severity": "error", "file": "app"}


@pytest.mark.parametrize("key", ["limit", "min-count"])
def test_parse_filters_counts_become_ints(key: str) -> None:
    """The store binds these as integers — a string would compare lexically."""
    target = "events" if key == "limit" else "clusters"
    assert parse_filters([f"{key}=2"], target) == {key: 2}


def test_parse_filters_accepts_zero_but_not_negative() -> None:
    assert parse_filters(["limit=0"], "events") == {"limit": 0}
    with pytest.raises(ValueError, match="must be non-negative"):
        parse_filters(["limit=-1"], "events")


def test_parse_filters_naive_since_is_normalised_to_utc() -> None:
    """A naive value is treated as UTC (documented in --help) and normalised
    before binding, so the string comparison in store.py is chronological."""
    parsed = parse_filters(["since=2026-07-16T10:00:01"], "events")
    assert parsed == {"since": "2026-07-16T10:00:01+00:00"}


def test_parse_filters_offset_since_is_converted_not_just_accepted() -> None:
    parsed = parse_filters(["until=2026-07-16T12:00:00+02:00"], "events")
    assert parsed == {"until": "2026-07-16T10:00:00+00:00"}


def test_parse_filters_splits_on_the_first_equals() -> None:
    """Filter keys are allowlisted names that never contain '=', so a value
    may — the deliberate opposite of parse_adapter_overrides' last-'=' split."""
    assert parse_filters(["file=name=odd.log"], "events") == {
        "file": "name=odd.log"
    }


def test_parse_filters_leaves_an_injection_shaped_value_intact() -> None:
    """T-02-08: the parser does not escape or reject SQL-shaped text — it
    passes it through as a literal for the store to bind as a parameter."""
    injection = "'; DROP TABLE events;--"
    assert parse_filters([f"file={injection}"], "events") == {"file": injection}


# --- rejected values ---------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "keys"),
    [("events", EVENT_FILTER_KEYS), ("clusters", CLUSTER_FILTER_KEYS)],
)
def test_parse_filters_unknown_key_lists_the_valid_keys(
    target: str, keys: tuple[str, ...]
) -> None:
    """The error is the operator's next action: every valid key is named."""
    with pytest.raises(ValueError) as excinfo:
        parse_filters(["bogus=1"], target)
    message = str(excinfo.value)
    assert "bogus" in message
    for key in keys:
        assert key in message, f"{key!r} missing from: {message!r}"


def test_parse_filters_rejects_every_filter_for_hypotheses() -> None:
    with pytest.raises(ValueError, match="unknown filter key"):
        parse_filters(["severity=error"], "hypotheses")


@pytest.mark.parametrize("spec", ["nosep", "=value", "key="])
def test_parse_filters_malformed_spec_names_the_shape(spec: str) -> None:
    with pytest.raises(ValueError, match="expected key=value"):
        parse_filters([spec], "events")


@pytest.mark.parametrize(
    ("target", "spec", "fragment"),
    [
        ("events", "limit=abc", "abc"),
        ("events", "since=notatime", "notatime"),
        ("clusters", "min-count=abc", "abc"),
        ("clusters", "min-count=-1", "-1"),
    ],
)
def test_parse_filters_invalid_value_names_the_offending_value(
    target: str, spec: str, fragment: str
) -> None:
    """Invalid values fail loudly naming the offending value — never an empty
    result set that looks like 'no matches'."""
    with pytest.raises(ValueError) as excinfo:
        parse_filters([spec], target)
    assert fragment in str(excinfo.value)


def test_parse_filters_invalid_severity_lists_the_vocabulary() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_filters(["severity=catastrophic"], "events")
    message = str(excinfo.value)
    assert "catastrophic" in message
    for severity in SEVERITIES:
        assert severity in message, f"{severity!r} missing from: {message!r}"


@pytest.mark.parametrize(
    ("target", "specs", "key"),
    [
        ("events", ["severity=error", "severity=warn"], "severity"),
        ("clusters", ["min-count=1", "min-count=2"], "min-count"),
    ],
)
def test_parse_filters_duplicate_key_fails_loudly(
    target: str, specs: list[str], key: str
) -> None:
    """WR-05: a repeated key is a mistake the operator must hear about — never
    silent last-wins (the fail-loud prohibition)."""
    with pytest.raises(ValueError) as excinfo:
        parse_filters(specs, target)
    assert "duplicate filter key" in str(excinfo.value)
    assert key in str(excinfo.value)


# --- parse_moment -------------------------------------------------------------


def test_parse_moment_none_is_none() -> None:
    """An absent window is absent — not an error, and not 'now'."""
    assert parse_moment(None, "since") is None


def test_parse_moment_naive_is_treated_as_utc() -> None:
    assert parse_moment("2026-07-16T10:00:00", "since") == datetime(
        2026, 7, 16, 10, 0, 0, tzinfo=UTC
    )


def test_parse_moment_offset_is_normalised_to_utc() -> None:
    assert parse_moment("2026-07-16T12:00:00+02:00", "until") == datetime(
        2026, 7, 16, 10, 0, 0, tzinfo=UTC
    )


def test_parse_moment_bad_value_names_the_label_and_the_value() -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_moment("notatime", "since")
    assert "since" in str(excinfo.value)
    assert "notatime" in str(excinfo.value)


def test_parse_moment_sanitises_the_echoed_value() -> None:
    """T-04-01: the echoed flag value is untrusted input, and the CLI prints
    this message verbatim, so the sanitising happens HERE.

    The assertions are on the ESCAPED forms, not the raw bytes: the value is
    interpolated with ``!r``, so ``repr`` would render an unsanitised ESC as
    the four harmless characters ``\\x1b``. Asserting the raw byte is absent
    would therefore pass with ``sanitise`` deleted — a test that cannot fail.
    """
    with pytest.raises(ValueError) as excinfo:
        parse_moment("\x1b[31mnot-a-time‮", "until")
    message = str(excinfo.value)
    assert "\\x1b" not in message
    assert "\\u202e" not in message
    assert "not-a-time" in message


# --- to_utc, the shared idiom -------------------------------------------------


def test_to_utc_is_the_shared_since_until_idiom() -> None:
    """Both parsers normalise through here, so the two flags and the two filter
    keys cannot drift apart on naive-value handling."""
    assert to_utc("2026-07-16T10:00:00") == datetime(
        2026, 7, 16, 10, 0, 0, tzinfo=UTC
    )
    assert to_utc("2026-07-16T05:00:00-05:00") == to_utc("2026-07-16T10:00:00")


def test_to_utc_raises_on_a_non_iso_value() -> None:
    """Each caller owns its own message and exit code — to_utc just refuses."""
    with pytest.raises(ValueError):
        to_utc("16/07/2026")
