# ClawOS Memory Vault

Git-backed, markdown-first shared memory for all ClawOS agents.

## Structure

- `decisions/` — Architectural and business decisions
- `learnings/` — Technical learnings and gotchas
- `entities/` — Named entities (clients, APIs, services)
- `observations/` — User preferences, patterns, signals
- `todos/` — Active task lists per agent
- `summaries/` — Session summaries, daily briefs

## Format

Each file uses YAML frontmatter + markdown body:

```markdown
---
type: decision
date: 2026-08-29
agent: josh
status: active
---

# We chose agent-os over elizaOS

Reason: token-efficient routing + browser automation fits our VPS setup.
