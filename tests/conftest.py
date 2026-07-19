"""Shared test fixtures: filesystem isolation and the zero-network guard.

This conftest is owned by plan 01-01. Later plans add fixtures in their own
test files, never here.
"""

import os
import socket
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture(autouse=True)
def _isolate_dirs(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redirect XDG dirs to tmp_path and clear SIFT_* env vars.

    Case paths derive from XDG_DATA_HOME (D-04), so no test can ever read or
    write the real home directory.
    """
    data_home = tmp_path / "xdg-data"
    config_home = tmp_path / "xdg-config"
    data_home.mkdir()
    config_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    for name in [key for key in os.environ if key.startswith("SIFT_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _no_network(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make any network connection attempt fail loudly.

    Zero network egress in tests is a hard project rule (CLAUDE.md). The block is
    installed for every test EXCEPT those carrying the ``live`` marker: live
    integration tests exist precisely to reach the configured loopback inference
    endpoint (pyproject.toml, run explicitly via ``-m live``), so patching their
    socket would defeat their purpose. The default suite (``-m 'not perf and not
    live'``) never carries the marker, so it stays fully socket-blocked.
    """
    node = cast(
        pytest.Item,
        request.node,  # pyright: ignore[reportUnknownMemberType] — .node is Any
    )
    if node.get_closest_marker("live") is not None:
        return

    def _blocked(self: socket.socket, address: Any) -> None:
        raise RuntimeError(
            "Network access is forbidden in tests (zero-network-in-tests rule, "
            "see CLAUDE.md). Inject a fake instead."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
