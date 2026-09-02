---
name: enterprise-ai-project-delivery-workbuddy-adapter
description: WorkBuddy adapter candidate for enterprise-ai-project-delivery. Probes and connects only verifiable lifecycle capabilities; never fabricates human authority.
metadata:
  adapter_version: 0.2.0-dev
  core_compatibility: v3.0.6
---

# WorkBuddy Delivery Controller Adapter

Run the conformance probe before any connection claim. A missing WorkBuddy conversation or message identity is a hard block for human-controlled transitions. Do not infer those transitions from natural-language text.

This Adapter may observe tool execution, preserve project-scoped bridge state, and request a Stop/Evidence gate only when its project contract is explicitly enabled. It must remain inert for all other projects. It never replaces the formal enterprise-ai-project-delivery Core.

Implementation map (`workbuddy-full-delivery-controller`):

- Harness Capability Router — `src/harness_skill_snapshot.py` (legal candidate source =
  current-session Skill-tool snapshot only) and `src/capability_router.py` (eligibility +
  text-overlap decision; no hardcoded skill names).
- Canonical Evidence — `src/harness_receipts.py` (HARNESS_EXECUTION receipts only from
  PostToolUse-shaped real tool results; event-level replay rejected; ledger completion gate).
- Human Authority — `src/human_authority.py` (adapter_message_id only from a real
  UserPromptSubmit payload; exact user controls; persisted, replay-safe).
- Scope cleanup — `src/scope_control.py` (per-invocation temp context + audit).
- `hooks/hooks.json` declares candidate hooks but stays INERT (enabled:false) — nothing is
  registered globally, no WorkBuddy settings are modified.
