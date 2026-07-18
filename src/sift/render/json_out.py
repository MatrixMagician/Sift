"""Canonical JSON report renderer (REPT-02) + the single determinism-exclusion
helper (REPT-03).

``render_json`` is a pure function of an analysed ``case.db`` — it reads
persisted rows and serialises them, constructing no inference client and making
no network call (T-06-08). Serialisation is key-sorted and stable
(``json.dumps(sort_keys=True, ensure_ascii=False, indent=2)`` + trailing
newline), so two runs over an identical case are byte-identical apart from the
D-06 excluded fields.

The D-06 excluded-field set (generated-at timestamp, absolute filesystem paths,
wall-clock durations) is defined ONCE here — in ``DETERMINISM_EXCLUDED`` plus
``normalise_for_determinism`` — and referenced by both the reproducibility test
and ADR 0008 (Pitfall 4). ``Event.source_file`` is already case-relative, so no
absolute path leaks from events; the helper strips any stray one defensively
(T-06-06).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sift.store import CaseStore

# The ONE place the D-06 run-level excluded fields are named. Path/duration
# exclusion is structural (see _strip_volatile) rather than a fixed key list,
# because those can appear anywhere in the document.
DETERMINISM_EXCLUDED: tuple[str, ...] = ("generated_at",)

_DURATION_MARKERS: tuple[str, ...] = ("duration", "elapsed")


def render_json(store: CaseStore) -> str:
    """Serialise an analysed case to a canonical, key-sorted JSON string.

    Carries the full hypotheses object (every ``StoredHypothesis`` field),
    cluster stats, timeline summary, unexplained signals, and a ``run``
    metadata block. Returns the dump plus a trailing newline.
    """
    doc: dict[str, object] = {
        "hypotheses": [dataclasses.asdict(h) for h in store.query_hypotheses()],
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "label": c.label,
                "signature": c.signature,
                "severity_max": c.severity_max,
                "count": c.count,
            }
            for c in store.query_clusters()
        ],
        "timeline_summary": store.get_meta("triage_timeline_summary") or "",
        "unexplained_signals": json.loads(
            store.get_meta("triage_unexplained_signals") or "[]"
        ),
        "run": {
            "model": store.get_meta("triage_model"),
            "prompt_hash": store.get_meta("triage_prompt_hash"),
            "embedding_model": store.get_meta("embedding_model"),
            "degraded": store.get_meta("triage_degraded") == "1",
            # Included for humans; EXCLUDED from the determinism comparison (D-06,
            # normalise_for_determinism drops it before byte-equality checks).
            "generated_at": store.get_meta("triage_created_at"),
        },
    }
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def normalise_for_determinism(doc: dict[str, object]) -> dict[str, object]:
    """Return a copy of ``doc`` with ONLY the D-06 excluded fields removed.

    Drops ``run.generated_at`` (the sole wall-clock field in scope), plus — as
    defence-in-depth (T-06-06) — any string value that is an absolute filesystem
    path and any key that names a wall-clock duration, anywhere in the document.
    Case-relative paths and every other field are retained. The input is not
    mutated.
    """
    out = copy.deepcopy(doc)
    run = out.get("run")
    if isinstance(run, dict):
        run_d = cast("dict[object, object]", run)
        for field in DETERMINISM_EXCLUDED:
            run_d.pop(field, None)
    _strip_volatile(out)
    return out


def _strip_volatile(value: object) -> None:
    """Recursively drop absolute-path values and duration keys, in place."""
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        for key in list(mapping.keys()):
            item = mapping[key]
            if _is_abs_path(item) or _is_duration_key(key):
                del mapping[key]
            else:
                _strip_volatile(item)
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            _strip_volatile(item)


def _is_abs_path(value: object) -> bool:
    return isinstance(value, str) and value.startswith("/")


def _is_duration_key(key: object) -> bool:
    return isinstance(key, str) and any(m in key.lower() for m in _DURATION_MARKERS)
