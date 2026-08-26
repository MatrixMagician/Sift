"""Startup-cost lock: ``sift.cli`` must not drag in the clustering stack.

``sklearn`` (and the ``scipy`` it imports) cost roughly 0.56 s to import, which
is more than twice the whole of the rest of Sift's startup. They are needed by
exactly two functions in ``pipeline.cluster``, both of which run only inside
``sift analyze``. Importing them at module scope charged that cost to every
invocation, including ``sift --help``, ``sift show`` and ``sift eustack``.

These tests run in a subprocess deliberately: by the time the suite reaches
this module some other test has almost certainly imported sklearn already, so
an in-process ``sys.modules`` assertion would pass no matter what ``cluster.py``
does. A fresh interpreter is the only honest check.
"""

import subprocess
import sys

# Guarded against regression rather than merely observed: any of these appearing
# in a fresh `import sift.cli` means an eager import crept back in.
_FORBIDDEN_AT_STARTUP = ("sklearn", "scipy")


def _modules_after(import_statement: str) -> set[str]:
    """Return the top-level module names loaded by ``import_statement``."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            f"{import_statement}\n"
            "import sys\n"
            "print('\\n'.join(sorted({m.split('.')[0] for m in sys.modules})))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(proc.stdout.split())


def test_cli_import_does_not_load_sklearn() -> None:
    """Importing the CLI must not pay the clustering stack's import cost."""
    loaded = _modules_after("import sift.cli")
    assert not loaded.intersection(_FORBIDDEN_AT_STARTUP)


def test_clustering_still_reaches_sklearn_when_used() -> None:
    """The lazy import is deferred, not deleted — the call site still loads it.

    Without this, the test above would also pass if clustering had quietly lost
    its dependency (or its callers).
    """
    loaded = _modules_after(
        "from sift.pipeline.cluster import _cluster_labels\n"
        "import numpy as np\n"
        "from sift.config import ClusteringConfig\n"
        "_cluster_labels(np.zeros((4, 3)), ClusteringConfig())"
    )
    assert "sklearn" in loaded
