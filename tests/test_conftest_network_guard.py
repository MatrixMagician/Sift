"""Regression proof for the `_no_network` autouse guard's marker carve-out.

Two halves of one invariant, proven offline (no external server, no real egress):

- **Unmarked tests stay socket-blocked** — the zero-network rule is
  installed for every ordinary test; `socket.connect` raises RuntimeError.
- **`@pytest.mark.live` tests bypass the guard** — live integration tests exist
  precisely to reach the configured loopback inference endpoint, so the guard
  must NOT patch `socket.connect` for them. Proven with an in-process loopback
  listener bound to an OS-assigned port — a determinism proof of the marker
  gate, distinct from the real-server `test_judge_live_round_trip`.
"""

from __future__ import annotations

import socket

import pytest


def test_default_suite_socket_guard_active() -> None:
    """Unmarked test: connecting a socket raises the zero-network RuntimeError."""
    client: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Network access is forbidden"):
            client.connect(("127.0.0.1", 13305))
    finally:
        client.close()


@pytest.mark.live
def test_live_marked_tests_bypass_socket_guard() -> None:
    """Live-marked test: a loopback connect to an in-process listener succeeds.

    Fully offline — the listener is created inside the test on 127.0.0.1:0, so
    the connect only ever touches loopback. FAILS before the Task 2 carve-out
    (guard blocks the connect → RuntimeError); PASSES after.
    """
    listener: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port: int = listener.getsockname()[1]
        # Must not raise: the guard is exempt for live-marked tests.
        client.connect(("127.0.0.1", port))
    finally:
        client.close()
        listener.close()
