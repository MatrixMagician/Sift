"""PKG-01 proof: build a wheel, install it offline, run the real ``sift``.

This module runs explicitly via ``uv run pytest -m packaging`` — the default
suite excludes it (pyproject.toml addopts). It is a slow end-to-end integration
test that shells out to ``uv``, so it is opt-in like the ``perf`` module.

Subprocess carve-out: the autouse ``_no_network`` conftest guard patches
``socket.socket.connect`` in the pytest process ONLY — it does not reach the
``uv``/``sift`` subprocesses spawned here. Offline-ness is therefore enforced
with uv's own flags (``--offline`` / ``UV_OFFLINE=1`` on every subprocess, plus
``--no-index --find-links`` on install), not by the socket guard. This marker
does NOT need a ``_no_network`` exemption (unlike ``live``): do not add a
``packaging`` branch to conftest.
"""

import os
import subprocess
from pathlib import Path

import pytest


def _run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess offline, failing loudly (with stderr) on non-zero exit."""
    proc = subprocess.run(argv, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(argv)} exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc


@pytest.mark.packaging
def test_offline_wheel_install_yields_working_console_script(tmp_path: Path) -> None:
    """uv build + offline ``uv tool install`` yields a runnable ``sift`` (PKG-01).

    Exercises PKG-01's exact ``uv tool install`` code path (tool-venv creation +
    PATH-injection of the entry-point script), redirected into a hermetic
    UV_TOOL_DIR/UV_TOOL_BIN_DIR under tmp_path so the real user tool state is
    never touched.
    """
    dist = tmp_path / "dist"
    tool_dir = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    data_dir = tmp_path / "cases"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "sample.log").write_text("2026-07-19 12:00:00 ERROR boom\n")

    # Belt-and-braces offline env on every uv/sift subprocess (our values win
    # over any inherited ones). ``--offline`` / ``UV_OFFLINE=1`` is the actual
    # zero-network guarantee: uv may only read from its cache and never touches
    # the network. The runtime deps (httpx, pydantic, scikit-learn, ...) resolve
    # from the warm cache populated by a prior ``uv sync`` — the documented A1
    # precondition. NB: we deliberately do NOT pass ``--no-index``. That flag
    # excludes the cache's own registry index too, so it would only resolve
    # packages physically present under ``--find-links``; building a full local
    # wheelhouse is not possible offline (uv exposes no ``pip download`` and the
    # cache holds unpacked archives, not ``.whl`` files), so ``--no-index`` can
    # never satisfy binary deps like scikit-learn. ``--offline`` alone is both
    # sufficient (zero network) and necessary (cache-backed resolution works).
    env = {
        **os.environ,
        "UV_OFFLINE": "1",
        "UV_TOOL_DIR": str(tool_dir),
        "UV_TOOL_BIN_DIR": str(bin_dir),
    }
    # The autouse `_isolate_dirs` fixture redirects XDG_DATA_HOME/XDG_CONFIG_HOME
    # to an empty tmp dir. uv needs the real ones to resolve runtime deps from
    # its warm cache offline (a redirected XDG_CONFIG_HOME hides the user's uv
    # config and makes offline resolution of binary wheels like scikit-learn
    # fail). Drop them here — isolation is still guaranteed by UV_TOOL_DIR /
    # UV_TOOL_BIN_DIR (tool location) and the explicit `--data-dir` on `sift new`.
    env.pop("XDG_DATA_HOME", None)
    env.pop("XDG_CONFIG_HOME", None)

    # 1. Build the wheel offline from the checked-out source (uv_build backend).
    _run(["uv", "build", "--offline", "--wheel", "-o", str(dist)], env)
    wheel = next(dist.glob("sift-*.whl"))

    # 2. Offline `uv tool install` — the exact PKG-01 path, not `uv pip install`.
    #    --find-links <dist> supplies the freshly-built sift wheel; runtime deps
    #    come from the warm cache under --offline (see the env note above).
    _run(
        [
            "uv",
            "tool",
            "install",
            "--offline",
            "--find-links",
            str(dist),
            str(wheel),
        ],
        env,
    )

    # 3. PATH-injection worked: the entry-point script exists before we run it.
    sift = bin_dir / "sift"
    assert sift.exists(), f"uv tool install did not inject {sift}"

    help_out = _run([str(sift), "--help"], env)
    assert "ingest" in help_out.stdout

    version_out = _run([str(sift), "--version"], env)
    assert "0.1.0" in version_out.stdout

    _run(
        [
            str(sift),
            "new",
            "smoke",
            "--input",
            str(scratch),
            "--data-dir",
            str(data_dir),
        ],
        env,
    )
