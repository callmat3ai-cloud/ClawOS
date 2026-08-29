---
type: decision
date: 2026-08-29
agent: josh
status: active
tags: [architecture, stack]
---

# ClawOS Stack Decision

**Decision:** Build ClawOS on portabledesktop + Hermes + custom voice layer.

**Rejected alternatives:**
- use-agent-os/agent-os — good but competes with Hermes
- modimihir07/agentic-os — dashboard only, no desktop control
- elizaos/eliza — too heavy, parallel runtime
- basecamp/omarchy — needs real hardware, not VPS-friendly

**Rationale:** portabledesktop gives visual desktop, Hermes gives intelligence, custom voice layer gives Jarvis experience. No external dependencies.
