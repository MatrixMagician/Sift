"""Shared test fixtures: filesystem isolation and the zero-network guard.

This conftest is owned by plan 01-01. Later plans add fixtures in their own
test files, never here.
"""

import os
import socket
from pathlib import Path
from typing import Any

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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make any network connection attempt fail loudly.

    Zero network egress in tests is a hard project rule (CLAUDE.md).
    Phase 3 will relax this for loopback only.
    """

    def _blocked(self: socket.socket, address: Any) -> None:
        raise RuntimeError(
            "Network access is forbidden in tests (zero-network-in-tests rule, "
            "see CLAUDE.md). Inject a fake instead."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
