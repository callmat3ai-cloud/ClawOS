---
type: learning
date: 2026-08-26
agent: josh
priority: high
tags: [freeai, transport, hermes]
---

# FreeAI Provider Transport

FreeAI.jembatanai.com uses Anthropic-style `/v1/messages` endpoint.
Hermes needs `transport: anthropic_messages` to work with it.
Direct API test succeeds but Telegram integration fails without correct transport.
