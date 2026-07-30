"""Paged data access for the TUI: the R008 responsiveness contract.

The events table is the only case table that grows without bound, so it is
the only one the TUI must never ``fetchall``: :class:`EventPager` pulls
fixed-size pages from ``CaseStore.iter_event_rows``'s streaming cursor on
demand and keeps what it has already materialised, so the cost of showing
the next page is bounded by ``page_size`` — never by case size. The other
tables (hypotheses, clusters, template groups) are aggregates orders of
magnitude smaller and stay on the store's existing list-returning APIs.

No SQL lives here (store.py owns ALL SQL) and no error handling either:
``sqlite3`` errors from a locked, corrupt or vanished case.db deliberately
bubble to the caller — the app shell's error screens (R012) sanitise and
present them; swallowing them here would hide store failures mid-session.
"""

from collections.abc import Iterator, Mapping
from itertools import islice
from typing import NamedTuple

from sift.store import CaseStore

# One DataTable page. Large enough that a page fills any plausible terminal
# with headroom, small enough that hydrating one is imperceptible.
DEFAULT_PAGE_SIZE = 200


class EventRow(NamedTuple):
    """One timeline row — exactly the six ``iter_event_rows`` fields.

    Deliberately NOT the full ``Event``: hydrating ``raw`` (and possibly
    zstd-decompressing it) is deferred until the user drills into a single
    event, via ``CaseStore.get_events_by_ids``.
    """

    event_id: str
    ts: str | None
    severity: str
    source_file: str
    line_start: int
    message: str


class EventPager:
    """Lazy forward-paging view over the events table (R008).

    Wraps ONE streaming cursor per (filters) combination: page N+1 resumes
    the open cursor instead of re-running the query, and previously fetched
    pages replay from the kept rows without touching SQLite at all. Rows
    arrive in the store's canonical order (ts NULLs last, ts, source_file,
    line_start) and are unfiltered by ranking exclusions — the timeline
    shows uncited, perfmon and severity="unknown" events alike (R002).

    Filters use the store's allowlisted keys (severity, source, file,
    since, until, limit); an unknown key raises ``ValueError`` from the
    store on the first :meth:`page` call — construction costs nothing
    because the underlying generator body (allowlist check included) only
    runs once the first row is pulled.
    """

    def __init__(
        self,
        store: CaseStore,
        filters: Mapping[str, str | int] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {page_size}")
        self._page_size = page_size
        self._cursor: Iterator[tuple[str, str | None, str, str, int, str]] = (
            store.iter_event_rows(filters)
        )
        self._rows: list[EventRow] = []
        self._exhausted = False

    @property
    def page_size(self) -> int:
        return self._page_size

    @property
    def loaded_count(self) -> int:
        """How many rows have been pulled from the cursor so far."""
        return len(self._rows)

    @property
    def exhausted(self) -> bool:
        """True once the cursor has proven there are no further rows."""
        return self._exhausted

    def page(self, index: int) -> list[EventRow]:
        """Rows for the 0-based page ``index``; empty past the end.

        Pulls from the cursor only the shortfall between what is already
        materialised and the end of the requested page — asking for a page
        already seen costs zero SQLite work, and asking for the next page
        costs at most ``page_size`` streamed rows.
        """
        if index < 0:
            raise ValueError(f"page index must be >= 0, got {index}")
        end = (index + 1) * self._page_size
        while not self._exhausted and len(self._rows) < end:
            shortfall = end - len(self._rows)
            batch = [EventRow(*r) for r in islice(self._cursor, shortfall)]
            self._rows.extend(batch)
            if len(batch) < shortfall:
                self._exhausted = True
        return self._rows[index * self._page_size : end]
