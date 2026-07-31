"""Client bring-up: turn a ``SiftConfig`` into a guarded ``InferenceClient``.

The single config-to-client path for every caller — the analyse command, the
eval harness and ``sift doctor`` (ADR 0019). It lives in ``llm/`` because that
package is the only one that talks HTTP and already owns the ``Endpoint`` pair;
keeping one canonical bring-up is what stops callers drifting into subtly
different clients.

``make_http_client`` is a module-level seam so tests bind an
``httpx.MockTransport`` and open no socket (EVAL-05) while the real SSRF guard
still runs at ``InferenceClient`` construction. ``build_client`` resolves it
through module globals at call time, so patching the attribute reaches every
caller.
"""

import httpx

from sift.config import SiftConfig
from sift.llm.client import Endpoint, InferenceClient


def make_http_client(timeout: float) -> httpx.Client:
    """Build the injected httpx.Client for doctor/analyze (per-request timeouts).

    Explicit timeouts treat the local server as untrusted (Pitfall 4 /
    T-03-05): a hostile or misconfigured endpoint can never hang doctor.
    """
    return httpx.Client(timeout=httpx.Timeout(timeout))


def build_client(
    config: SiftConfig, *, allow_public: bool, tuned_embeddings: bool = False
) -> tuple[httpx.Client, InferenceClient, Endpoint, Endpoint]:
    """Build the httpx client plus SSRF-guarded ``InferenceClient`` (LLM-02).

    The shared analyze/eval/doctor bring-up: the Endpoint pair, one
    ``httpx.Client`` sized to the larger role timeout, then ``InferenceClient``
    construction — which runs the loopback/RFC1918 SSRF guard on BOTH base_urls;
    a public endpoint without the override raises ``ValueError``, propagated
    with the httpx client already closed so each caller owns only its message
    and exit path. ``tuned_embeddings`` threads the analyze-only embedding
    knobs (``max_input_chars``/``context``); eval and doctor keep the client
    defaults. Returns ``(http, client, gen_ep, emb_ep)``; the caller owns
    ``http.close()``.
    """
    gen_ep = Endpoint(
        base_url=config.generation.base_url, model=config.generation.model
    )
    emb_ep = Endpoint(
        base_url=config.embeddings.base_url, model=config.embeddings.model
    )
    http = make_http_client(
        max(config.generation.timeout, config.embeddings.timeout)
    )
    tuning: dict[str, int] = (
        {
            "max_input_chars": config.embeddings.max_input_chars,
            "context": config.embeddings.context,
        }
        if tuned_embeddings
        else {}
    )
    try:
        client = InferenceClient(
            generation=gen_ep,
            embeddings=emb_ep,
            http=http,
            allow_public=allow_public,
            retries=config.generation.retries,
            backoff_base=config.generation.backoff_base,
            batch_size=config.embeddings.batch_size,
            **tuning,
        )
    except ValueError:
        http.close()
        raise
    return http, client, gen_ep, emb_ep
