## Deferred (out of scope for 14-05) — logged 2026-07-20T19:13:30Z

- Live `sift eval` (EVAL-03, operator CI gate) exits non-zero in THIS sandbox because the
  local Lemonade endpoint (:13305) returns `400 Bad Request` on `/v1/embeddings` — the loaded
  model does not support embeddings (documented ONNX/OGA-recipe caveat: /v1/embeddings needs a
  llamacpp/flm-recipe model). This affects ALL 8 golden cases identically (mcm-denial, disk-full,
  etc.), is a pre-existing operator-endpoint condition, and is NOT introduced by plan 14-05.
  The authoritative zero-network gate (EVAL-05, MockTransport) is fully green — see SUMMARY.
