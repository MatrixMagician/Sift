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
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

# _assert_local is module-private; the guard-acceptability lock (PKG-02) must
# exercise the real guard, so import it directly under a scoped suppression.
from sift.llm.client import _assert_local  # pyright: ignore[reportPrivateUsage]

_DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def _shipped_base_urls() -> list[str]:
    """Extract every ``SIFT_*_BASE_URL`` value from ``deploy/sift.container``."""
    text = (_DEPLOY / "sift.container").read_text()
    return re.findall(r"SIFT_\w+_BASE_URL=(\S+)", text)


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


@pytest.mark.packaging
def test_deploy_base_urls_are_guard_clean() -> None:
    """The shipped Quadlet default reaches the host llama-server WITHOUT override.

    Regression-locks PKG-02 (D-06 corrected): every ``SIFT_*_BASE_URL`` in
    ``deploy/sift.container`` must pass ``_assert_local(allow_public=False)``
    without raising — i.e. no ``--i-know-what-im-doing`` is ever needed for the
    deploy default. If a future edit reintroduced a bare hostname (e.g.
    ``host.containers.internal``) the DNS-free guard would raise and this fails.
    Each host is additionally pinned to the literal loopback ``127.0.0.1``.
    """
    urls = _shipped_base_urls()
    assert urls, "deploy/sift.container defines no SIFT_*_BASE_URL entries"
    for url in urls:
        # No raise = guard accepts the shipped default with no break-glass.
        _assert_local(url, allow_public=False)
        assert urlsplit(url).hostname == "127.0.0.1", url


@pytest.mark.packaging
def test_quadlet_generator_dry_run_validates_or_skips() -> None:
    """The Podman Quadlet generator lints ``deploy/`` — graceful skip if absent (D-07).

    The systemd generator dry-run is the authoritative Quadlet linter (NOT
    ``podman quadlet install --dry-run``, which previews updates, not parse
    validity). Where the generator binary is present we assert a clean run whose
    generated stdout references the ``sift`` unit; where it is absent (the likely
    CI case) we skip rather than fail — D-07 requires the dry-run to be
    best-effort, never a hard CI failure.
    """
    generator = next(
        (
            p
            for p in (
                "/usr/lib/systemd/system-generators/podman-system-generator",
                "/usr/libexec/podman/quadlet",  # legacy pre-5.x path
            )
            if Path(p).exists()
        ),
        None,
    )
    if generator is None:
        pytest.skip("podman quadlet generator absent; dry-run is best-effort (D-07)")

    proc = subprocess.run(
        [generator, "--user", "--dryrun"],
        env={**os.environ, "QUADLET_UNIT_DIRS": str(_DEPLOY)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"quadlet dry-run exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "sift" in proc.stdout, proc.stdout
