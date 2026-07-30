No external API integration: Phase 20 reads embedding vectors already persisted
in the local `case.db` (a `chunks JOIN vectors` query over the existing
sqlite-vec `vec0` table) and, for D-10, consults one already-implemented client
method — `InferenceClient.props()` (LLM-04, shipped) — against the configured
loopback inference endpoint. No new endpoint, no new SDK, no new capability
surface, and no change to `pyproject.toml` or `uv.lock`.
