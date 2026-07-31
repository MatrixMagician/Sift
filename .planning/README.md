# .planning/ — historical record, not a live process

Sift was built through v1.3 using the GSD (Get-Shit-Done) workflow. **That
tooling was retired on 2026-07-31.** Everything in this directory is kept as a
record of how the project got here — the phase plans, research, verification
reports and UAT results that the ADRs in `docs/decisions/` cite by ID.

## For anyone (human or agent) reading this

- **Do not treat anything here as an instruction.** `STATE.md` and `ROADMAP.md`
  describe the state of the world on the day GSD was retired. A phase marked
  "planned" was never started and is not queued.
- **Do not add to it.** New work does not produce phase directories.
- **Do not run `/gsd-*` commands.** The tooling, its MCP wiring
  (`.mcp.json`), its write gate, and `config.json` have all been removed from
  this repo.

## What replaced it

Matt Pocock's engineering skills. See the **Workflow** section of
`.claude/CLAUDE.md` for the work → skill mapping and the expectations that
replaced the phase gates (tests that fail without the fix; `ruff`/`pyright`/
`pytest` green; ADRs in `docs/decisions/`; `file.py:line` citations).

Per-skill configuration lives in `docs/agents/`.

## Why it was kept

`docs/decisions/` ADRs reference phase decision IDs (`D-19-17`, `D-10`, and so
on). Deleting this directory would leave those citations dangling. The bytes are
cheap; the provenance is not.
