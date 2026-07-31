"""Raw-string parsers for the case commands — pure, typer-free, testable.

Every function here turns operator-supplied text into a typed value or raises
``ValueError``. Adapters call them BEFORE opening a case store, so a malformed
``--since`` or ``--filter`` costs a usage error and nothing else (the fail-fast
ordering the analyze command has always guaranteed), and ``run_x`` receives
values that are already valid.

Sanitisation is deliberately asymmetric and matches the behaviour these
parsers were extracted from: ``parse_filters`` raises unsanitised text and its
caller sanitises, while ``parse_moment`` sanitises the echoed flag value
itself (T-04-01). Changing either changes operator-visible output.
"""

from datetime import UTC, datetime

from sift.render._util import sanitise

# The six-severity vocabulary (store CHECK constraint) for filter validation.
SEVERITIES = ("fatal", "error", "warn", "info", "debug", "unknown")

# Valid --filter keys per show target (STORE-04). Mirrors the allowlist
# snippet dicts in store.py — the store re-validates as defence in depth.
FILTER_KEYS: dict[str, tuple[str, ...]] = {
    "events": ("severity", "source", "file", "since", "until", "limit"),
    "clusters": ("severity", "min-count", "contains", "limit"),
    # hypotheses: no filters yet (query_hypotheses returns the whole ranked set).
    # An empty allowlist means any --filter fails loudly (exit 2) rather than
    # being silently ignored — a richer filter set is out of scope for M4.
    "hypotheses": (),
}


def to_utc(value: str) -> datetime:
    """Parse an ISO 8601 string to a UTC datetime — the shared since/until idiom.

    A naive value is treated as UTC (documented in --help), then normalised to
    UTC. Raises ``ValueError`` on a non-ISO value; each caller owns its own
    error message and exit code.
    """
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def parse_filters(specs: list[str], target: str) -> dict[str, str | int]:
    """Parse and validate repeated ``--filter key=value`` specs (typer-free).

    Splits on the FIRST '=': filter keys are allowlisted names that never
    contain '=', while values may (e.g. ``file=name=odd.log``). This is the
    deliberate opposite of parse_adapter_overrides' last-'=' split, where the
    '='-free side is the adapter name on the right. Raises ValueError on any
    invalid key or value — bad input fails loudly, never an empty result set
    that looks like 'no matches'. The caller converts the error to exit 2 and
    owns sanitising the echoed text.
    """
    valid_keys = FILTER_KEYS[target]
    filters: dict[str, str | int] = {}
    for spec in specs:
        key, sep, value = spec.partition("=")
        if not sep or not key or not value:
            raise ValueError(f"invalid filter {spec!r}; expected key=value")
        if key not in valid_keys:
            raise ValueError(
                f"unknown filter key {key!r} for {target}; "
                f"valid keys: {', '.join(valid_keys)}"
            )
        if key in filters:
            # WR-05: never silent last-wins — a repeated key is a mistake the
            # operator must hear about (fail-loud prohibition).
            raise ValueError(
                f"duplicate filter key {key!r}; each key may appear once"
            )
        if key == "severity":
            if value not in SEVERITIES:
                raise ValueError(
                    f"invalid severity {value!r}; "
                    f"valid severities: {', '.join(SEVERITIES)}"
                )
            filters[key] = value
        elif key in ("limit", "min-count"):
            try:
                number = int(value)
            except ValueError:
                raise ValueError(
                    f"invalid {key} value {value!r}: not an integer"
                ) from None
            if number < 0:
                raise ValueError(
                    f"invalid {key} value {value!r}: must be non-negative"
                )
            filters[key] = number
        elif key in ("since", "until"):
            try:
                # Stored ts strings are UTC isoformat — normalise before binding
                # so the string comparison in store.py is chronological.
                filters[key] = to_utc(value).isoformat()
            except ValueError:
                raise ValueError(
                    f"invalid {key} value {value!r}: not an ISO 8601 timestamp"
                ) from None
        else:
            filters[key] = value
    return filters


def parse_moment(value: str | None, label: str) -> datetime | None:
    """Parse an ISO 8601 ``--since``/``--until`` value to a UTC datetime.

    Mirrors the ``parse_filters`` datetime idiom: a naive value is treated as
    UTC then normalised to UTC. A bad value raises ``ValueError`` carrying an
    ALREADY-SANITISED message (T-04-01: the echoed flag value is untrusted) —
    a usage error, never a silent ``None`` that would look like an absent
    window. ``--hint`` is NEVER routed through here: it is free operator text,
    not a timestamp, and reaches the prompt verbatim.
    """
    if value is None:
        return None
    try:
        return to_utc(value)
    except ValueError:
        raise ValueError(
            f"invalid {label} value {sanitise(value)!r}: "
            "not an ISO 8601 timestamp"
        ) from None
