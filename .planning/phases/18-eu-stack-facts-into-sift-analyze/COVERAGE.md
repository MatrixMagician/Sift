# API Coverage — Phase 18

No external API integration: this phase adds a fourth deterministic fact block to an existing,
already-integrated local inference call path (`src/sift/llm/client.py`); it introduces no new
endpoint, no new service, no new SDK and no new capability surface to enumerate.

The only network-touching component in Sift is the OpenAI-compatible client shipped in earlier
milestones (`/v1/chat/completions`, `/v1/embeddings`, `/props`, `/tokenize`, `/v1/models`).
Phase 18 changes the *content* of the prompt sent to `/v1/chat/completions` and nothing about
the request shape, the endpoint set, or the client. `18-RESEARCH.md` § Standard Stack records
that the phase adds no dependency, and § Package Legitimacy Audit records the legitimacy gate as
not applicable.
