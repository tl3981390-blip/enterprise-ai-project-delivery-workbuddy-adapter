---
name: enterprise-ai-project-delivery-workbuddy-adapter
description: WorkBuddy adapter candidate for enterprise-ai-project-delivery. Probes and connects only verifiable lifecycle capabilities; never fabricates human authority.
metadata:
  adapter_version: 0.2.0-dev
  core_compatibility: v3.0.6
---

# WorkBuddy Delivery Controller Adapter

Run the conformance probe (`src/probe_workbuddy.py`, read-only) before any connection
claim. A missing WorkBuddy conversation or message identity is a hard block for
human-controlled transitions; do not infer them from natural-language text and never
treat a hook event id as a message id.

Safe subset this adapter may provide - only for a project whose
`.workbuddy/delivery-contract.json` is exactly enabled:

1. observe real tool results via PostToolUse receipts;
2. persist project-scoped bridge state (`.workbuddy/bridge/`);
3. enforce a Stop/Evidence gate at completion (block when evidence is missing or weak).

It must stay fully inert for every other project, never register hooks globally, never
modify WorkBuddy settings, and never replace or copy the formal
enterprise-ai-project-delivery Core. Full Human Authority control is
`CONTROLLER_NOT_CONNECTED` until the host supplies session_id + conversation_id +
message_id and distinct user-control events, verified in a real run.
