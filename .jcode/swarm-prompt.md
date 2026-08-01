<!--
This file IS the swarm config. Swarms are complicated, dynamic systems, so
routing policy is passed to the models as a prompt rather than as options in
a standard config file. Edit freely: override globally at
~/.jcode/swarm-prompt.md or per-project at ./.jcode/swarm-prompt.md.
-->

Model routing guidance for spawned swarm agents. Pass `model` and `effort` when
spawning or assigning swarm work. Run `swarm list_models` first when you need to
confirm which models/routes are actually available.

## Routing policy (required)

- **Planning and research** -> `claude-opus-5` with `effort: "high"`.
  This covers: planning, decomposition, architecture and design, research,
  investigation, exploration, root-cause debugging analysis, code review,
  verification, and synthesis of other agents' findings.
- **Coding and testing** -> `claude-sonnet-5` with `effort: "high"`.
  This covers: implementation, refactoring, writing and running tests, fixing
  build/test failures, and mechanical edits.
- **Bulk context fetching / summarization** -> `claude-sonnet-5` with
  `effort: "low"`.
- If the user explicitly asks for a specific model, that request wins over the
  rules above.
- If a requested route is unavailable, fall back to the nearest available
  Anthropic model of the same tier, or omit `model` to inherit the
  coordinator's model.

Never spawn without an explicit `model` and `effort` unless deliberately
inheriting.

## Structure guidance for spawned swarm agents

- Always pass `label` when spawning (e.g. `label: "api reviewer"`) so the swarm
  UI shows what each agent is for. The explicit `spawn` action rejects missing or
  blank labels.
- In normal and light-swarm mode, only the root session may spawn agents. Workers
  must complete their assigned task directly and report back rather than creating
  another generation.
- Recursive spawning is reserved for a root running in `swarm-deep` mode. In that
  mode the spawner owns its children, and manager-style decomposition may create
  deeper subtrees when it materially improves coverage.
