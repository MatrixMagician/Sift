# ADR 0011: Quadlet host-reachability under the DNS-free loopback guard

**Status:** Accepted (implemented in Phase 8 / M8, Plan 08-02)
**Date:** 2026-07-19 (Phase 8 context; recorded per SPEC §10 open-question rule)
**Answers:** PKG-02 / D-06 (corrected) — what address must the shipped
`deploy/sift.container` point Sift at so an in-container Sift reaches a host-side
`llama-server` WITHOUT the `--i-know-what-im-doing` break-glass, given that the
LLM-02 SSRF guard never resolves DNS? Cross-refs SPEC.md §7 (the `deploy/` tree)
/ §8 (M8 packaging), and the guard itself at `src/sift/llm/client.py:54-84`.

## Context

D-06 originally proposed pointing the in-container base_url at Podman's host
magic-DNS hostname `host.containers.internal`, on the assumption the guard would
treat it as a local address. Reading the guard's actual source disproves that
assumption.

`_assert_local(base_url, allow_public)` (`src/sift/llm/client.py:54-84`) is
**DNS-free by design** — an anti-TOCTOU measure, since resolving a name is itself
egress and the resolved address could change between the check and the connect.
It inspects the literal host string only and accepts a host **iff** it is:

1. the name `localhost` or any `*.localhost` (matched as a literal string, never
   resolved), **or**
2. a **literal** IP that is loopback / RFC1918 / link-local
   (`ipaddress.ip_address(host)` then `ip.is_loopback or ip.is_private`).

Everything else raises `ValueError` unless `allow_public` (the
`--i-know-what-im-doing` override) is set.

The hostname `host.containers.internal` is therefore **rejected**: it is neither
`localhost`/`*.localhost` nor a literal IP, so `ipaddress.ip_address(...)` raises
`ValueError`, the host is treated as non-local, and construction fails. Shipping
it as the deploy default would have forced every operator onto the break-glass
override for what is a genuinely local endpoint — exactly the wrong signal.

## Decision

The **goal of D-06 stands** — no `--i-know-what-im-doing` in the deploy default —
achieved via a guard-compatible address rather than the rejected hostname:

- `deploy/sift.container` sets `Network=host` and points both roles at the
  **literal loopback** `127.0.0.1`:
  `SIFT_GENERATION_BASE_URL=http://127.0.0.1:8080/v1` and
  `SIFT_EMBEDDINGS_BASE_URL=http://127.0.0.1:8081/v1`. `127.0.0.1` is
  `ip.is_loopback`, so the guard returns without raising. Host networking makes
  this backend-agnostic: the container shares the host's loopback identically
  under both pasta (Podman 5.x default) and slirp4netns, so `127.0.0.1` reaches a
  host-side `llama-server` with no per-backend special-casing.
- For a network-isolated setup where `Network=host` is undesirable, the
  guard-clean alternative is a `*.localhost` alias:
  `AddHost=infra.localhost:host-gateway` (Podman 5.3.0+) with the base_url
  targeting `http://infra.localhost:8080/v1`. The guard accepts any `*.localhost`
  name as a literal string (rule 1) without resolving it; Podman resolves the
  alias to the host at connect time.
- The **guard is unchanged**. The deploy adapts to the guard; altering
  `_assert_local` (e.g. to whitelist `host.containers.internal` or to resolve
  names) is explicitly out of scope — it would reintroduce the TOCTOU egress the
  DNS-free design exists to prevent.

## Consequences

- The shipped deploy default is guard-clean: an operator enabling
  `deploy/sift.container` as-shipped reaches the host `llama-server` with no
  break-glass flag. Test A in `tests/test_packaging.py` regression-locks this by
  feeding every shipped `SIFT_*_BASE_URL` through `_assert_local(allow_public=
  False)` and asserting no raise — a future edit reintroducing a bare hostname
  would fail the suite.
- The `--i-know-what-im-doing` override retains its intended meaning: a
  break-glass for genuinely public endpoints, never a deploy convenience. If a
  deploy needs it to reach localhost, the address is wrong.
- `host.containers.internal` is documented here as the rejected mechanism so a
  future reader does not re-propose it; the pasta/slirp4netns backend question is
  sidestepped entirely by `Network=host` + `127.0.0.1`.
- This ADR corrects D-06 after verifying the guard's source directly, rather than
  propagating the assumed-DNS mechanism into the deploy files.
